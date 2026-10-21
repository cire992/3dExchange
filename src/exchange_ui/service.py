"""The window's view of the library: a read-only connection plus the core's query API.

Scans run in a separate process and write to the database; the window only reads (WAL mode
lets both happen at once), so the UI never holds a write lock.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from exchange.db import open_library, open_library_readonly
from exchange.db import repository as repo
from exchange.definitions import DefinitionSet, load_definitions
from exchange.library.query import Page, dossier_detail, list_dossiers, sidebar
from exchange.paths import fold
from exchange.scanner.enrichment import thumbnail_dir
from exchange.scanner.scan import DEFAULT_THRESHOLD


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

    def effective_group(self) -> str:
        """Searches, type and Unidentified views list child dossiers too; grouping by product
        would hide them."""
        return "all" if self.query or self.type_id or self.unidentified else self.group

    def full_query(self) -> str:
        return f"{self.query} is:unidentified".strip() if self.unidentified else self.query


class LibraryService:
    def __init__(self, db_path: Path, definitions: DefinitionSet | None = None,
                 threshold: float = DEFAULT_THRESHOLD) -> None:
        self.db_path = Path(db_path).resolve()
        self.definitions = definitions or load_definitions()
        self.threshold = threshold
        self.thumbnails = thumbnail_dir(self.db_path)
        # Create or migrate once, then read only.
        open_library(self.db_path).close()
        self._conn: sqlite3.Connection = open_library_readonly(self.db_path)

    def close(self) -> None:
        self._conn.close()  # closing twice is harmless

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

    def connection_for_tests(self) -> sqlite3.Connection:
        return self._conn

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
