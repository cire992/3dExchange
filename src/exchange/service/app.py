"""The Exchange service's HTTP API (Roadmap phase 6): what the desktop shell's Workspace window reads.

Local and single-user. The service listens on loopback only; every ``/api`` request carries the
per-launch token as ``Authorization: Bearer <token>``, and requests addressed to any other host
name are refused (a web page cannot reach it through DNS rebinding). No browser origin is allowed
directly: the shell's own local service proxies it on the Workspace's origin.

The library is read through read-only connections, one per worker thread, exactly as the PySide6
window does; scans and edits may write at the same time (WAL mode).
"""

from __future__ import annotations

import hmac
import sqlite3
import threading
from pathlib import Path
from urllib.parse import quote

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse

from exchange import __version__
from exchange.db import SCHEMA_VERSION, open_library, open_library_readonly
from exchange.db import repository as repo
from exchange.definitions import DefinitionSet, load_definitions
from exchange.errors import ExchangeError
from exchange.library.query import GROUPS, dossier_detail, list_collections, list_dossiers, sidebar
from exchange.paths import is_within
from exchange.scanner.enrichment import thumbnail_dir
from exchange.scanner.scan import DEFAULT_THRESHOLD
from exchange.service import API_VERSION, models

PREFIX = f"/api/v{API_VERSION}"
MAX_PAGE = 1000


class Library:
    """The database the service reads, with one read-only connection per thread."""

    def __init__(self, db_path: Path, definitions: DefinitionSet, threshold: float) -> None:
        self.db_path = Path(db_path).resolve()
        self.definitions = definitions
        self.threshold = threshold
        self.thumbnails = thumbnail_dir(self.db_path)
        open_library(self.db_path).close()  # create or migrate once; then read only
        self._local = threading.local()
        self._open: list[sqlite3.Connection] = []
        self._lock = threading.Lock()

    def conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            # Worker threads only read; one connection each, closed with the service.
            conn = self._local.conn = open_library_readonly(self.db_path)
            with self._lock:
                self._open.append(conn)
        return conn

    def close(self) -> None:
        with self._lock:
            for conn in self._open:
                try:
                    conn.close()
                except sqlite3.ProgrammingError:  # opened by another thread; it closes when the process ends
                    pass
            self._open.clear()


def _thumbnail_url(uid: str) -> str:
    return f"{PREFIX}/dossiers/{quote(uid)}/thumbnail"


def create_app(db_path: Path, *, token: str, definitions: DefinitionSet | None = None,
               threshold: float = DEFAULT_THRESHOLD, allowed_hosts: tuple[str, ...] = ("127.0.0.1", "localhost")) -> FastAPI:
    library = Library(db_path, definitions or load_definitions(), threshold)
    expected = f"Bearer {token}".encode()
    app = FastAPI(title="Exchange", version=__version__, docs_url=None, redoc_url=None, openapi_url=None,
                  description="The local API of the Exchange service, for the desktop shell's Workspace window.")
    app.state.library = library

    @app.middleware("http")
    async def only_this_host(request: Request, call_next):
        host = (request.headers.get("host") or "").rsplit(":", 1)[0].strip("[]").lower()
        if host not in allowed_hosts:
            return JSONResponse({"detail": "Unexpected host"}, status_code=403)
        return await call_next(request)

    def authorized(request: Request) -> None:
        given = (request.headers.get("authorization") or "").encode()
        if not hmac.compare_digest(given, expected):
            raise HTTPException(401, "Missing or wrong service token")

    errors = {401: {"model": models.Problem}, 404: {"model": models.Problem}, 400: {"model": models.Problem}}

    @app.get("/health", response_model=models.Health, tags=["service"])
    def health() -> models.Health:
        """Whether the service is up. Needs no token and reveals nothing about the library."""
        return models.Health(version=__version__, api=API_VERSION, schema_version=SCHEMA_VERSION)

    api = Depends(authorized)

    @app.get(f"{PREFIX}/sidebar", response_model=models.Sidebar, dependencies=[api], responses=errors, tags=["library"])
    def get_sidebar() -> dict:
        """Counts for the sidebar: the whole library, Unidentified, and each environment's containers and types."""
        return sidebar(library.conn(), library.definitions, threshold=library.threshold)

    @app.get(f"{PREFIX}/environments", response_model=list[models.Environment], dependencies=[api], responses=errors,
             tags=["library"])
    def get_environments() -> list[dict]:
        """Every environment with its roots (no counts; see the sidebar for those)."""
        conn = library.conn()
        out = []
        for env in repo.list_environments(conn):
            roots = repo.list_roots(conn, env["id"])
            statuses = {r["status"] for r in roots}
            out.append({**{k: env[k] for k in ("id", "uid", "name", "type_id", "added_at", "last_scanned_at")},
                        "status": "online" if statuses == {"online"} else "offline" if statuses == {"offline"} else "partial",
                        "roots": [{"id": r["id"], "path": r["path"], "status": r["status"],
                                   "offline_since": r["offline_since"]} for r in roots]})
        return out

    @app.get(f"{PREFIX}/dossiers", response_model=models.Page, dependencies=[api], responses=errors, tags=["library"])
    def get_dossiers(
        query: str = Query("", description="The search language, e.g. `donut env:starfield tag:food`"),
        group: str = Query("product", description="product, type or all; searches, type, collection and "
                           "Unidentified views always list all, as the window does"),
        environment: int | None = Query(None, description="Only assets with a live entry in this environment"),
        container: int | None = Query(None, description="Only assets with a live entry in this container"),
        type: str | None = Query(None, description="Only this dossier type and its subtypes"),
        parent: str | None = Query(None, description="One product's contents, by its uid"),
        collection: str | None = Query(None, description="One collection's members, by its uid"),
        unidentified: bool = Query(False, description="Only Unidentified assets"),
        offset: int = Query(0, ge=0),
        limit: int = Query(200, ge=1, le=MAX_PAGE),
    ) -> dict:
        """A page of item cards, sorted by name (by type, then name, when grouped by type)."""
        if group not in GROUPS:
            raise HTTPException(400, f"group must be one of {', '.join(GROUPS)}")
        parts = [query] + (["is:unidentified"] if unidentified else []) + ([f"collection:{collection}"] if collection else [])
        effective_group = "all" if query or type or unidentified or collection else group
        try:
            page = list_dossiers(library.conn(), library.definitions, query=" ".join(p for p in parts if p),
                                 group=effective_group, environment_id=environment, container_id=container,
                                 type_id=type, parent_uid=parent, offset=offset, limit=limit,
                                 threshold=library.threshold)
        except ExchangeError as exc:  # a search that does not parse
            raise HTTPException(400, str(exc)) from exc
        return {"total": page.total, "offset": page.offset, "items": [
            {"uid": b.uid, "name": b.name, "type_id": b.type_id, "type_name": b.type_name, "confidence": b.confidence,
             "unidentified": b.unidentified, "thumbnail_url": _thumbnail_url(b.uid) if b.thumbnail else None,
             "format": b.format, "environments": b.environments, "entries": b.entries, "children": b.children}
            for b in page.items]}

    @app.get(PREFIX + "/dossiers/{uid}", response_model=models.DossierDetail, dependencies=[api], responses=errors,
             tags=["library"])
    def get_dossier(uid: str) -> dict:
        """Everything the inspector shows for one asset, with its parent product's fields."""
        conn = library.conn()
        detail = dossier_detail(conn, library.definitions, uid, threshold=library.threshold)
        if detail is None:
            raise HTTPException(404, f"No asset {uid}")
        detail["thumbnail_url"] = _thumbnail_url(uid) if detail.pop("thumbnail") else None
        detail["parent_fields"] = ({k: {"value": v, "source": s}
                                    for k, (v, s) in repo.field_sources(conn, detail["parent"]["uid"]).items()}
                                   if detail["parent"] else {})
        return detail

    @app.get(PREFIX + "/dossiers/{uid}/thumbnail", dependencies=[api], responses={**errors, 200: {
        "content": {"image/png": {}, "image/jpeg": {}, "image/webp": {}}, "description": "The thumbnail image"}},
        response_class=FileResponse, tags=["library"])
    def get_thumbnail(uid: str) -> FileResponse:
        """An asset's thumbnail, from the thumbnail cache next to the database."""
        conn = library.conn()
        row = conn.execute("SELECT t.rel_path FROM thumbnail t JOIN dossier_effective d ON d.id = t.dossier_id"
                           " WHERE d.uid = ?", (uid,)).fetchone()
        file = library.thumbnails / Path(*row["rel_path"].split("/")) if row else None
        if file is None or not is_within(file, library.thumbnails) or not file.is_file():
            raise HTTPException(404, f"No thumbnail for {uid}")
        return FileResponse(file, headers={"Cache-Control": "private, max-age=300"})

    @app.get(f"{PREFIX}/collections", response_model=list[models.Collection], dependencies=[api], responses=errors,
             tags=["library"])
    def get_collections() -> list[dict]:
        """Manual and smart collections with their member counts."""
        return list_collections(library.conn(), library.definitions, threshold=library.threshold)

    return app
