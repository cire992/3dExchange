"""Open the library database and keep its schema current.

Migrations are numbered SQL files (``NNNN_name.sql``) applied in order; ``PRAGMA user_version``
records the last one applied. An existing database is backed up before any migration runs.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path

from exchange.errors import LibraryError

_MIGRATION_NAME = re.compile(r"^(\d{4})_[\w-]+\.sql$")


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sql: str


def _migrations() -> list[Migration]:
    found = []
    for item in resources.files("exchange.db").joinpath("migrations").iterdir():
        match = _MIGRATION_NAME.match(item.name)
        if match:
            found.append(Migration(int(match.group(1)), item.name, item.read_text(encoding="utf-8")))
    found.sort(key=lambda m: m.version)
    return found


SCHEMA_VERSION = _migrations()[-1].version


def _configure(conn: sqlite3.Connection) -> sqlite3.Connection:
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def open_library(path: Path) -> sqlite3.Connection:
    """Open (creating if needed) and migrate the library at ``path``.

    The connection is in autocommit mode; use ``repository.transaction`` for atomic changes.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        conn = _configure(sqlite3.connect(path, isolation_level=None))
        conn.execute("PRAGMA journal_mode = WAL")
    except sqlite3.Error as exc:
        raise LibraryError(f"cannot open library database {path}: {exc}") from exc
    migrate(conn, path)
    return conn


def open_library_readonly(path: Path) -> sqlite3.Connection | None:
    """Open an existing library without writing to it; None if there is none yet."""
    if not path.exists():
        return None
    try:
        conn = _configure(sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True))
    except sqlite3.Error as exc:
        raise LibraryError(f"cannot open library database {path}: {exc}") from exc
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version != SCHEMA_VERSION:
        conn.close()
        raise LibraryError(
            f"library database {path} is at schema version {version}, expected {SCHEMA_VERSION}; "
            "run a scan without --dry-run to migrate it"
        )
    return conn


def migrate(conn: sqlite3.Connection, path: Path) -> list[int]:
    """Apply pending migrations; returns the versions applied."""
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    if current > SCHEMA_VERSION:
        raise LibraryError(
            f"library database {path} is schema version {current}, newer than this Exchange "
            f"supports ({SCHEMA_VERSION})"
        )
    pending = [m for m in _migrations() if m.version > current]
    if not pending:
        return []
    has_data = conn.execute("SELECT count(*) FROM sqlite_master").fetchone()[0] > 0
    if has_data:
        backup(conn, path, current)
    # Table rebuilds drop and rename tables other tables point at; check references at the end.
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        for migration in pending:
            try:
                conn.executescript(
                    f"BEGIN;\n{migration.sql}\nPRAGMA user_version = {migration.version};\nCOMMIT;"
                )
            except sqlite3.Error as exc:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise LibraryError(f"migration {migration.name} failed: {exc}") from exc
        broken = conn.execute("PRAGMA foreign_key_check").fetchall()
        if broken:
            raise LibraryError(f"migration left {len(broken)} broken references, e.g. {tuple(broken[0])}")
    finally:
        conn.execute("PRAGMA foreign_keys = ON")
    return [m.version for m in pending]


def backup(conn: sqlite3.Connection, path: Path, version: int) -> Path:
    """Copy the database next to itself, e.g. ``library.v1.20261021T120000Z.bak.db``."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    dest = path.with_name(f"{path.stem}.v{version}.{stamp}.bak{path.suffix}")
    target = sqlite3.connect(dest)
    try:
        conn.backup(target)
    finally:
        target.close()
    return dest
