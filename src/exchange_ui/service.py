"""The window's view of the library: a read-only connection plus the core's query API, and the
user's edits through the curation engine.

Scans run in a separate process and write to the database. The window reads on its own
connection (WAL mode lets both happen at once); edits go through a second connection in short
transactions. A scan holds the write lock while it identifies a root, so an edit made then fails
quickly with a message instead of freezing the window.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from exchange.curation import CurationError, Curator
from exchange.db import open_library, open_library_readonly
from exchange.db import repository as repo
from exchange.definitions import DefinitionSet, load_definitions
from exchange.errors import ExchangeError
from exchange.lexicons import with_generated
from exchange.library.desk import unattached_files, unattached_roots
from exchange.library.query import Page, dossier_detail, list_collections, list_dossiers, sidebar
from exchange.paths import fold, is_within
from exchange.scanner.enrichment import thumbnail_dir
from exchange.scanner.scan import DEFAULT_THRESHOLD
from exchange.suggestions import list_suggestions


@dataclass
class Filter:
    """What the browser shows: a sidebar selection plus the search text."""

    query: str = ""
    group: str = "product"  # product | type
    environment_id: int | None = None
    container_id: int | None = None
    type_id: str | None = None
    unidentified: bool = False
    parent_uid: str | None = None  # showing one product's contents
    parent_name: str = ""
    collection_uid: str | None = None
    collection_name: str = ""

    def effective_group(self) -> str:
        """Searches, type, collection and Unidentified views list child dossiers too; grouping
        by product would hide them."""
        return "all" if self.query or self.type_id or self.unidentified or self.collection_uid else self.group

    def full_query(self) -> str:
        parts = [self.query]
        if self.unidentified:
            parts.append("is:unidentified")
        if self.collection_uid:
            parts.append(f"collection:{self.collection_uid}")
        return " ".join(p for p in parts if p)


BUSY = "The library is busy: a scan is writing to it. Try again when the scan finishes."
WRITE_TIMEOUT_MS = 1500


class EditError(ExchangeError):
    """An edit that could not be made, with a message for the user."""


class LibraryService:
    def __init__(self, db_path: Path, definitions: DefinitionSet | None = None,
                 threshold: float = DEFAULT_THRESHOLD, user_dir: Path | None = None) -> None:
        self.db_path = Path(db_path).resolve()
        self.definitions = definitions or load_definitions()
        self.threshold = threshold
        self.user_dir = user_dir  # lexicon edits; None is the user's definitions folder
        self.thumbnails = thumbnail_dir(self.db_path)
        # Create or migrate once, then read only.
        open_library(self.db_path).close()
        self._conn: sqlite3.Connection = open_library_readonly(self.db_path)
        self._curator: Curator | None = None
        # This session's actions as (curation_log id, label); undoing one logs its inverse,
        # which is what redo undoes.
        self.undo_stack: list[tuple[int, str]] = []
        self.redo_stack: list[tuple[int, str]] = []

    def close(self) -> None:
        self._conn.close()  # closing twice is harmless
        if self._curator is not None:
            self._curator.conn.close()

    def sidebar(self) -> dict:
        return sidebar(self._conn, self.definitions, threshold=self.threshold)

    def page(self, flt: Filter, offset: int = 0, limit: int = 200) -> Page:
        return list_dossiers(
            self._conn, self.definitions, query=flt.full_query(), group=flt.effective_group(),
            environment_id=flt.environment_id, container_id=flt.container_id, type_id=flt.type_id,
            parent_uid=flt.parent_uid,
            offset=offset, limit=limit, threshold=self.threshold, thumbnail_dir=self.thumbnails)

    def detail(self, uid: str) -> dict | None:
        detail = dossier_detail(self._conn, self.definitions, uid, threshold=self.threshold,
                                thumbnail_dir=self.thumbnails)
        if detail is not None and detail["parent"]:
            # Origin (author, license, source) usually lives on the product.
            detail["parent_fields"] = {k: {"value": v, "source": s} for k, (v, s) in
                                       repo.field_sources(self._conn, detail["parent"]["uid"]).items()}
        return detail

    def collections(self) -> list[dict]:
        return list_collections(self._conn, self.definitions, threshold=self.threshold)

    def reader(self) -> sqlite3.Connection:
        """A new read-only connection, for a background thread (connections stay in one thread)."""
        return open_library_readonly(self.db_path)

    def desk_roots(self) -> list[dict]:
        return unattached_roots(self._conn)

    def unattached_keys(self, root_id: int, folder: str) -> list[tuple[int, str]]:
        """The unattached files under a folder as (root id, rel_key), for a product or link."""
        return [(root_id, f["rel_key"]) for f in unattached_files(self._conn, root_id, folder)]

    def suggestions(self, kind: str | None = None, limit: int = 300, offset: int = 0) -> tuple[list[dict], int]:
        """Pending suggestions (one page) and how many there are in all."""
        total = self._conn.execute("SELECT count(*) FROM suggestion WHERE state = 'pending'"
                                   + (" AND kind = ?" if kind else ""), [kind] if kind else []).fetchone()[0]
        return list_suggestions(self._conn, kind=kind, limit=limit, offset=offset), total

    def lexicons(self) -> dict:
        """Lexicons as scans use them: the files, plus the words scans found (known authors)."""
        return with_generated(self.definitions, repo.generated_words(self._conn)).lexicons

    def suggestion_counts(self) -> dict[str, int]:
        return dict(self._conn.execute(
            "SELECT kind, count(*) FROM suggestion WHERE state = 'pending' GROUP BY kind").fetchall())

    def connection_for_tests(self) -> sqlite3.Connection:
        return self._conn

    # Editing ------------------------------------------------------------------------------------

    def _curation(self) -> Curator:
        if self._curator is None:
            conn = open_library(self.db_path)
            conn.execute(f"PRAGMA busy_timeout = {WRITE_TIMEOUT_MS}")
            self._curator = Curator(conn, self.definitions, user_dir=self.user_dir)
        return self._curator

    def _call(self, fn: Callable[[Curator], Any]) -> Any:
        try:
            return fn(self._curation())
        except CurationError as exc:
            raise EditError(str(exc)) from exc
        except sqlite3.OperationalError as exc:
            if "locked" in str(exc) or "busy" in str(exc):
                raise EditError(BUSY) from exc
            raise

    def edit(self, label: str, fn: Callable[[Curator], Any]) -> Any:
        """Make one undoable edit: ``fn`` calls the curator and returns its log id (or a tuple
        starting with it). ``label`` names it for Undo/Redo. Raises EditError."""
        result = self._call(fn)
        log_id = result[0] if isinstance(result, tuple) else result
        self.undo_stack.append((log_id, label))
        self.redo_stack.clear()
        return result

    def undo(self) -> str | None:
        """Undo this session's latest edit; returns its label, or None if there is none."""
        if not self.undo_stack:
            return None
        log_id, label = self.undo_stack[-1]
        undone = self._call(lambda c: c.undo(log_id))
        self.undo_stack.pop()
        self.redo_stack.append((undone, label))
        return label

    def redo(self) -> str | None:
        if not self.redo_stack:
            return None
        log_id, label = self.redo_stack[-1]
        redone = self._call(lambda c: c.undo(log_id))
        self.redo_stack.pop()
        self.undo_stack.append((redone, label))
        return label

    def undo_entry(self, log_id: int, label: str) -> None:
        """Undo one entry of a dossier's history (any session); itself undoable."""
        self.edit(f"undo {label}", lambda c: c.undo(log_id))

    # Requisitions ---------------------------------------------------------------------------------

    def registry(self, reload: bool = False):
        """Process packages (cached; ``reload`` after installing or trusting one)."""
        from exchange.processes.registry import load_registry

        if reload or getattr(self, "_registry", None) is None:
            self._registry = load_registry()
        return self._registry

    def environments(self) -> list[dict]:
        return [{**dict(e), "user_config": json.loads(e["user_config"] or "{}")} for e in repo.list_environments(self._conn)]

    def plan(self, uid: str, environment_id: int, **kwargs):
        """Plan one asset (or product) into an environment (see requisitions.plan)."""
        from exchange.requisitions.plan import plan_requisition

        return plan_requisition(self._conn, self.definitions, self.registry(), uid, environment_id, **kwargs)

    def routes(self, uid: str, environment_id: int) -> list[dict]:
        from exchange.requisitions.plan import routes

        return routes(self._conn, self.definitions, self.registry(), uid, environment_id)

    def _write(self, fn: Callable[[sqlite3.Connection], Any]) -> Any:
        """Run ``fn`` on the write connection; a busy library or a refused action is an EditError."""
        try:
            return fn(self._curation().conn)
        except sqlite3.OperationalError as exc:
            if "locked" in str(exc) or "busy" in str(exc):
                raise EditError(BUSY) from exc
            raise
        except ExchangeError as exc:
            raise EditError(str(exc)) from exc

    def queue(self, plans: list) -> list[int]:
        """Queue plans (remembering their options as each process's last used); their ids."""
        from exchange.requisitions.plan import queue_plan
        from exchange.requisitions.presets import remember

        ids = self._write(lambda conn: [queue_plan(conn, p, self.registry()) for p in plans
                                        if any(i.include for i in p.items)])
        options: dict = {}
        for plan in plans:
            for item in plan.items:
                if item.include:
                    options.update(item.params)
        remember(options)
        return ids

    def requisitions(self) -> list[dict]:
        from exchange.requisitions.lifecycle import list_requisitions

        return list_requisitions(self._conn)

    def requisition(self, ref) -> dict:
        from exchange.requisitions.lifecycle import detail

        return detail(self._conn, ref)

    def requisition_action(self, action: str, ref, *args) -> Any:
        """hold, release, move (position), resume (on_collision), check_stale."""
        from exchange.requisitions import lifecycle

        if action == "hold":
            return self._write(lambda conn: lifecycle.hold(conn, ref, True))
        if action == "release":
            return self._write(lambda conn: lifecycle.hold(conn, ref, False))
        if action == "move":
            return self._write(lambda conn: lifecycle.move(conn, ref, *args))
        if action == "resume":
            return self._write(lambda conn: lifecycle.resume(conn, ref, *args))
        if action == "rebuild":
            return self._write(lambda conn: lifecycle.rebuild(conn, self.registry(), ref))
        if action == "check_stale":
            return self._write(lambda conn: lifecycle.check_stale(conn, self.registry()))
        raise ValueError(action)

    def default_endpoint(self, environment_id: int, name: str = "<name>"):
        from exchange.requisitions.endpoints import default_endpoint

        return default_endpoint(self._conn, self.definitions, environment_id, name)

    def set_endpoint(self, environment_id: int, folder: str | None, visibility: str | None) -> None:
        """An environment's endpoint folder (None: the default) and visibility."""
        def write(conn):
            config = repo.user_config(conn, environment_id)
            if folder:
                config["endpoint"] = folder
            else:
                config.pop("endpoint", None)
            if visibility:
                config["visibility"] = visibility
            with repo.transaction(conn):
                repo.set_user_config(conn, environment_id, config)
        self._write(write)

    def file_key(self, path: str | Path) -> tuple[int, str] | None:
        """(root id, rel_key) of a file inside a known root, for linking; None if outside all."""
        path = Path(path).resolve()
        for root in repo.list_roots(self._conn):
            base = Path(root["path"])
            if is_within(path, base):
                return root["id"], fold(path.relative_to(base.resolve()).as_posix())
        return None

    def files_of(self, uid: str) -> list[tuple[int, str]]:
        """The files of a dossier's live entries, as (root id, rel_key), for linking elsewhere."""
        rows = self._conn.execute(
            "SELECT DISTINCT f.root_id, f.rel_key FROM dossier d JOIN ledger l ON l.dossier_id = d.id"
            " JOIN entry e ON e.ledger_id = l.id AND e.status != 'retired'"
            " JOIN entry_file ef ON ef.entry_id = e.id JOIN file f ON f.id = ef.file_id WHERE d.uid = ?", (uid,))
        return [(r[0], r[1]) for r in rows]

    def roots(self) -> list:
        return repo.list_roots(self._conn)

    def environment_for_root(self, path: str) -> dict | None:
        """The environment a folder already belongs to, with its settings, if any."""
        row = repo.find_root(self._conn, fold(str(Path(path).resolve())))
        if row is None:
            return None
        env = repo.get_environment(self._conn, row["environment_id"])
        return {"id": env["id"], "name": env["name"], "type_id": env["type_id"],
                "user_config": json.loads(env["user_config"])}

    def type_name(self, type_id: str) -> str:
        dtype = self.definitions.dossier_types.get(type_id)
        return dtype.name if dtype else type_id
