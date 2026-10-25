"""The service's write API (Roadmap phase 6e): curation edits, Undo and Redo, history, suggestions,
the Unidentified desk and lexicons, as the PySide6 window makes them.

Edits go through the curation engine, so each is one undoable step in ``curation_log``. They run
on one write connection in one worker thread, one at a time, with a short busy timeout: while a
scan holds the write lock, an edit fails at once with a message (503) instead of waiting. A
refused edit (merging an asset into itself, a smart collection's members...) is a 409, and an
unknown asset or collection a 404.

Undo and Redo work on this service session's own edits, like the window's Ctrl+Z: undoing one logs
its inverse, which is what Redo undoes. Any history entry can also be undone by its id. The PySide6
window keeps its own stack; avoid editing in both at once.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from fastapi import FastAPI, HTTPException, Query

from exchange.curation import EDITABLE_FIELDS, CurationError, Curator
from exchange.db import open_library
from exchange.db import repository as repo
from exchange.definitions.schema import GENERATED_LEXICON_KINDS
from exchange.errors import ExchangeError
from exchange.lexicons import with_generated
from exchange.library.desk import unattached_files, unattached_folders, unattached_roots
from exchange.service import models
from exchange.suggestions import list_suggestions

BUSY = "The library is busy: a scan is writing to it. Try again when the scan finishes."
WRITE_TIMEOUT_MS = 1500
MAX_FOLDER_FILES = 5000  # more files than this under one folder is a category, not an asset
_NOT_FOUND = re.compile(r"^no (dossier|collection|history entry|entry|lexicon|environment|suggestion|file) ")


class Busy(Exception):
    pass


class Editor:
    """Edits on one write connection in one worker thread, with this session's Undo and Redo."""

    def __init__(self, library) -> None:
        self.library = library
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="exchange-edits")
        self._curator: Curator | None = None
        self.undo_stack: list[tuple[int, str, str]] = []  # (log id, label, refresh)
        self.redo_stack: list[tuple[int, str, str]] = []
        self._closed = threading.Event()

    def _curation(self) -> Curator:  # in the worker thread
        if self._curator is None:
            conn = open_library(self.library.db_path)
            conn.execute(f"PRAGMA busy_timeout = {WRITE_TIMEOUT_MS}")
            self._curator = Curator(conn, self.library.definitions)
        return self._curator

    def run(self, fn: Callable[[Curator], Any]) -> Any:
        """Run ``fn`` with the curator in the worker thread; HTTP errors for refusals and a busy library."""
        def call():
            try:
                return fn(self._curation())
            except sqlite3.OperationalError as exc:
                if "locked" in str(exc) or "busy" in str(exc):
                    raise Busy(BUSY) from exc
                raise
        try:
            return self._pool.submit(call).result()
        except Busy as exc:
            raise HTTPException(503, str(exc), headers={"Retry-After": "2"}) from exc
        except (CurationError, ExchangeError) as exc:
            raise HTTPException(404 if _NOT_FOUND.match(str(exc)) else 409, str(exc)) from exc

    def session(self) -> dict:
        return {"undo": self.undo_stack[-1][1] if self.undo_stack else None,
                "redo": self.redo_stack[-1][1] if self.redo_stack else None}

    def edit(self, label: str, refresh: str, fn: Callable[[Curator], Any]) -> dict:
        def make(curator: Curator):
            result = fn(curator)
            log_id, new_uid = result if isinstance(result, tuple) else (result, None)
            self.undo_stack.append((log_id, label, refresh))
            self.redo_stack.clear()
            return log_id, new_uid
        log_id, new_uid = self.run(make)
        return {"log_id": log_id, "label": label, "new_uid": new_uid, "refresh": refresh, "session": self.session()}

    def _step(self, source: list, target: list) -> dict:
        def step(curator: Curator):
            if not source:
                return None, "none"
            log_id, label, refresh = source[-1]
            done = curator.undo(log_id)
            source.pop()
            target.append((done, label, refresh))
            return label, refresh
        label, refresh = self.run(step)
        return {"label": label, "refresh": refresh, "session": self.session()}

    def undo(self) -> dict:
        return self._step(self.undo_stack, self.redo_stack)

    def redo(self) -> dict:
        return self._step(self.redo_stack, self.undo_stack)

    def close(self) -> None:
        def shut():
            if self._curator is not None:
                self._curator.conn.close()
        if not self._closed.is_set():
            self._closed.set()
            self._pool.submit(shut).result()
            self._pool.shutdown()


def _count(n: int, one: str, many: str | None = None) -> str:
    return f"{n:,} {one if n == 1 else many or one + 's'}"


def _assets(uids: list[str]) -> str:
    return "an asset" if len(uids) == 1 else _count(len(uids), "asset")


def register(app: FastAPI, library, editor: Editor, api, errors: dict) -> None:
    prefix = app.state.prefix
    write_errors = {**errors, 409: {"model": models.Problem}, 503: {"model": models.Problem}}

    def post(path: str, **kwargs):
        return app.post(prefix + path, response_model=models.EditResult, dependencies=[api], responses=write_errors,
                        tags=["editing"], **kwargs)

    def folder_files(conn: sqlite3.Connection, folder: models.DeskFolder) -> list[tuple[int, str]]:
        files = unattached_files(conn, folder.root, folder.path, limit=MAX_FOLDER_FILES + 1)
        if len(files) > MAX_FOLDER_FILES:
            raise HTTPException(409, f"{folder.path or 'This root'} holds more than {MAX_FOLDER_FILES:,} unattached "
                                "files: that is a category, not an asset")
        if not files:
            raise HTTPException(409, f"{folder.path or 'This root'} has no unattached files")
        return [(folder.root, f["rel_key"]) for f in files]

    # Assets -------------------------------------------------------------------------------------

    @post("/edits/fields")
    def edit_fields(body: models.FieldEdit) -> dict:
        """Set a field on one asset or many (bulk edit); a null value reverts to the scanned one."""
        if body.field == "name" and len(body.uids) > 1:
            raise HTTPException(409, "names are edited one asset at a time")
        verb = "revert" if body.value is None else "rename" if body.field == "name" else "set"
        label = "rename" if verb == "rename" else f"{verb} {body.field.replace('_id', '')} of {_assets(body.uids)}"
        refresh = "all" if body.field == "type_id" else "detail"
        return editor.edit(label, refresh, lambda c: c.set_field(body.uids, body.field, body.value))

    @post("/edits/tags")
    def edit_tags(body: models.TagEdit) -> dict:
        """Add or remove tags on one asset or many."""
        words = [*(f"+{t}" for t in body.add), *(f"-{t}" for t in body.remove)]
        return editor.edit(f"tag {_assets(body.uids)} {' '.join(words)}", "detail",
                           lambda c: c.tag(body.uids, body.add, body.remove))

    @post("/edits/tags/revert")
    def revert_tag(body: models.TagRevert) -> dict:
        """Forget the user's choice about one tag (back to what scans found)."""
        return editor.edit(f"revert tag {body.tag}", "detail", lambda c: c.revert_tag(body.uid, body.tag))

    @post("/edits/parent")
    def edit_parent(body: models.ParentEdit) -> dict:
        """Put assets into a product, or (parent null) take them out of any product."""
        label = f"move {_assets(body.uids)} into a product" if body.parent else f"take {_assets(body.uids)} out of its product"
        return editor.edit(label, "all", lambda c: c.set_parent(body.uids, body.parent))

    @post("/edits/parent/revert")
    def revert_parent(body: models.ParentRevert) -> dict:
        return editor.edit("revert product", "all", lambda c: c.revert_parent(body.uid))

    @post("/edits/merge")
    def merge(body: models.MergeEdit) -> dict:
        """The same asset found twice: `uid`'s entries and children join `into`."""
        return editor.edit("merge", "all", lambda c: c.merge(body.uid, body.into))

    @post("/edits/fold-variant")
    def fold_variant(body: models.FoldEdit) -> dict:
        """`uid` becomes a variant of `into`: one asset, two variants."""
        return editor.edit(f"fold in variant {body.variant}", "all",
                           lambda c: c.fold_variant(body.uid, body.into, body.variant, body.target_variant))

    @post("/edits/split")
    def split(body: models.SplitEdit) -> dict:
        """Entries wrongly grouped into an asset become an asset of their own (new_uid)."""
        return editor.edit("split", "all", lambda c: c.split(body.uid, body.entries, body.name))

    @post("/edits/promote-variant")
    def promote(body: models.PromoteEdit) -> dict:
        """A variant becomes its own asset again (new_uid)."""
        return editor.edit(f"make variant {body.variant} its own asset", "all",
                           lambda c: c.promote_variant(body.uid, body.variant))

    @post("/edits/products")
    def create_product(body: models.ProductEdit) -> dict:
        """A new product (new_uid) holding assets and/or a desk folder's unattached files."""
        def make(c: Curator):
            files = folder_files(c.conn, body.folder) if body.folder else []
            return c.create_product(body.name, body.children, files=files)
        return editor.edit(f"new product {body.name.strip()}", "all", make)

    @post("/edits/link-files")
    def link_files(body: models.LinkEdit) -> dict:
        """Link files (or a desk folder's unattached files) onto an asset."""
        def make(c: Curator):
            files = [(f.root, f.key) for f in body.files] + (folder_files(c.conn, body.folder) if body.folder else [])
            return c.link_files(body.uid, files)
        return editor.edit(f"link {'a folder' if body.folder else _count(len(body.files), 'file')}", "all", make)

    @post("/edits/unlink-files")
    def unlink_files(body: models.UnlinkEdit) -> dict:
        return editor.edit(f"unlink {_count(len(body.files), 'file')}", "all",
                           lambda c: c.unlink_files([(f.root, f.key) for f in body.files]))

    @post("/edits/dismiss")
    def dismiss(body: models.DismissEdit) -> dict:
        """Mark assets as not assets (out of Unidentified and default views), or count them again."""
        label = f"mark {_assets(body.uids)} as not an asset" if body.dismissed else f"count {_assets(body.uids)} again"
        return editor.edit(label, "all", lambda c: c.dismiss(body.uids, body.dismissed))

    @post("/edits/ignore-folder")
    def ignore_folder(body: models.IgnoreEdit) -> dict:
        """Ignore a folder from now on: its unattached files leave the desk, and rescans skip it."""
        return editor.edit(f"{'ignore' if body.ignored else 'stop ignoring'} {body.folder}", "all",
                           lambda c: c.ignore_folder(body.environment, body.folder, body.ignored))

    # Collections ----------------------------------------------------------------------------------

    @post("/collections")
    def create_collection(body: models.CollectionCreate) -> dict:
        """A manual collection, or a smart one (a saved search); new_uid is its uid."""
        return editor.edit(f"new collection {body.name.strip()}", "collections",
                           lambda c: c.create_collection(body.name, body.query))

    @app.delete(prefix + "/collections/{uid}", response_model=models.EditResult, dependencies=[api],
                responses=write_errors, tags=["editing"])
    def delete_collection(uid: str) -> dict:
        return editor.edit("delete collection", "collections", lambda c: c.delete_collection(uid))

    @post("/collections/{uid}/members")
    def collection_members(uid: str, body: models.MembersEdit) -> dict:
        """Add assets to a manual collection, or (present false) remove them."""
        verb = "add" if body.present else "remove"
        return editor.edit(f"{verb} {_assets(body.uids)} {'to' if body.present else 'from'} a collection", "collections",
                           lambda c: c.add_to_collection(uid, body.uids, body.present))

    # Lexicons -------------------------------------------------------------------------------------

    @app.get(prefix + "/lexicons", response_model=list[models.LexiconView], dependencies=[api], responses=errors,
             tags=["editing"])
    def get_lexicons() -> list[dict]:
        """Every lexicon as scans use it: the file's terms, plus the words scans found (known authors)."""
        files = library.definitions.lexicons
        merged = with_generated(library.definitions, repo.generated_words(library.conn())).lexicons
        out = []
        for lexicon_id, lexicon in sorted(merged.items()):
            own = {t.value.casefold(): t for t in files[lexicon_id].terms} if lexicon_id in files else {}
            terms = []
            for term in lexicon.terms:
                mine = own.get(term.value.casefold())
                words = list(mine.words) if mine else []
                terms.append({"value": term.value, "words": words, "patterns": list(term.patterns),
                              "found": [w for w in term.words if w.casefold() not in {x.casefold() for x in words}]})
            out.append({"id": lexicon_id, "name": lexicon.name, "kind": lexicon.kind,
                        "generated": lexicon.kind in GENERATED_LEXICON_KINDS, "terms": terms,
                        "exclude": list(files[lexicon_id].exclude) if lexicon_id in files else []})
        return out

    @post("/lexicons/{lexicon_id}/words")
    def lexicon_word(lexicon_id: str, body: models.WordEdit) -> dict:
        """Add a word to a lexicon term (written to the user's lexicon file), or remove it. Applies on the
        next rescan or classification."""
        verb = "add" if body.present else "remove"
        lexicon = library.definitions.lexicons.get(lexicon_id)
        # Ignore and index lexicons are plain word lists: their terms have no value to name.
        where = body.value or f"the {lexicon.name if lexicon else lexicon_id} lexicon"
        return editor.edit(f"{verb} the word {body.word} {'to' if body.present else 'from'} {where}", "none",
                           lambda c: c.set_lexicon_word(lexicon_id, body.value, body.word, body.present))

    # Suggestions ----------------------------------------------------------------------------------

    @app.get(prefix + "/suggestions", response_model=models.Suggestions, dependencies=[api], responses=errors,
             tags=["editing"])
    def get_suggestions(kind: str | None = Query(None, description="texture_link, variant_group or lexicon_word"),
                        offset: int = Query(0, ge=0), limit: int = Query(300, ge=1, le=1000)) -> dict:
        """Pending suggestions, one page at a time, with counts by kind."""
        conn = library.conn()
        counts = dict(conn.execute("SELECT kind, count(*) FROM suggestion WHERE state = 'pending' GROUP BY kind").fetchall())
        total = counts.get(kind, 0) if kind else sum(counts.values())
        return {"total": total, "counts": counts, "offset": offset,
                "items": list_suggestions(conn, kind=kind, limit=limit, offset=offset)}

    @post("/suggestions/accept")
    def accept(body: models.SuggestionIds) -> dict:
        """Accept suggestions in one undoable step (the desk's batches)."""
        return editor.edit(f"accept {_count(len(body.ids), 'suggestion')}", "all", lambda c: c.accept_many(body.ids))

    @post("/suggestions/reject")
    def reject(body: models.SuggestionIds) -> dict:
        """Reject suggestions: they are not offered again."""
        return editor.edit(f"reject {_count(len(body.ids), 'suggestion')}", "none", lambda c: c.reject(body.ids))

    # The Unidentified desk ------------------------------------------------------------------------

    @app.get(prefix + "/desk/roots", response_model=list[models.DeskRoot], dependencies=[api], responses=errors,
             tags=["editing"])
    def desk_roots() -> list[dict]:
        """Online roots, the desk's top level for unattached files (counts come per folder)."""
        return unattached_roots(library.conn())

    @app.get(prefix + "/desk/folders", response_model=models.DeskLevel, dependencies=[api], responses=errors,
             tags=["editing"])
    def desk_folders(root: int, folder: str = Query("", description="Root-relative, '/' separators")) -> dict:
        """One folder level of a root's unattached files: subfolders with counts, and files directly in it."""
        return unattached_folders(library.conn(), root, folder)

    @app.get(prefix + "/desk/files", response_model=list[models.DeskFile], dependencies=[api], responses=errors,
             tags=["editing"])
    def desk_files(root: int, folder: str = "", limit: int = Query(500, ge=1, le=MAX_FOLDER_FILES)) -> list[dict]:
        """Unattached files under a folder (all levels)."""
        return unattached_files(library.conn(), root, folder, limit=limit)

    # History, Undo and Redo -----------------------------------------------------------------------

    @app.get(prefix + "/history", response_model=list[models.HistoryEntry], dependencies=[api], responses=errors,
             tags=["editing"])
    def history(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=500)) -> list[dict]:
        """The library's edits, newest first (every session's, the window's included)."""
        out = []
        for row in library.conn().execute("SELECT id, at, action, payload FROM curation_log ORDER BY id DESC"
                                          " LIMIT ? OFFSET ?", (limit, offset)):
            payload = json.loads(row["payload"])
            out.append({"id": row["id"], "at": row["at"], "action": row["action"],
                        "dossiers": payload.get("dossiers", []), "undoable": "inverse" in payload,
                        "details": {k: v for k, v in payload.items()
                                    if k not in ("changes", "inverse", "dossiers", "dossier", "action")}})
        return out

    @app.post(prefix + "/history/{log_id}/undo", response_model=models.EditResult, dependencies=[api],
              responses=write_errors, tags=["editing"])
    def undo_entry(log_id: int) -> dict:
        """Undo one history entry, from any session; the undo is itself undoable."""
        row = library.conn().execute("SELECT action FROM curation_log WHERE id = ?", (log_id,)).fetchone()
        label = f"undo {row['action'].replace('_', ' ')}" if row else "undo"
        return editor.edit(label, "all", lambda c: c.undo(log_id))

    @app.get(prefix + "/session", response_model=models.Session, dependencies=[api], responses=errors,
             tags=["editing"])
    def session() -> dict:
        """What Undo and Redo would do now."""
        return editor.session()

    @app.post(prefix + "/undo", response_model=models.UndoResult, dependencies=[api], responses=write_errors,
              tags=["editing"])
    def undo() -> dict:
        """Undo this session's latest edit (label null when there is none)."""
        return editor.undo()

    @app.post(prefix + "/redo", response_model=models.UndoResult, dependencies=[api], responses=write_errors,
              tags=["editing"])
    def redo() -> dict:
        return editor.redo()

    # Choices --------------------------------------------------------------------------------------

    @app.get(prefix + "/choices", response_model=models.Choices, dependencies=[api], responses=errors,
             tags=["editing"])
    def choices() -> dict:
        """What editors offer: dossier types, the category tags, and the editable fields."""
        defs = library.definitions
        types = sorted(({"id": t.id, "name": t.name, "extends": t.extends} for t in defs.dossier_types.values()),
                       key=lambda t: t["name"].casefold())
        tags = sorted({term.value for lex in defs.lexicons.values() if lex.kind == "category" for term in lex.terms},
                      key=str.casefold)
        return {"types": types, "tags": tags, "fields": list(EDITABLE_FIELDS)}
