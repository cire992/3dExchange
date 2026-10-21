import sqlite3

import pytest

from exchange.db import SCHEMA_VERSION, open_library, open_library_readonly
from exchange.db.connection import migrate
from exchange.errors import LibraryError


def test_fresh_library_is_migrated(db_path):
    conn = open_library(db_path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'view')")}
    assert {"environment", "container", "file", "dossier", "ledger", "entry", "entry_file",
            "override_field", "override_tag", "override_link", "dossier_effective"} <= tables
    assert migrate(conn, db_path) == []  # idempotent
    conn.close()
    assert list(db_path.parent.glob("*.bak.db")) == []  # nothing to back up on creation


def test_existing_database_is_backed_up_before_migrating(db_path):
    db_path.parent.mkdir(parents=True)
    legacy = sqlite3.connect(db_path)
    legacy.execute("CREATE TABLE legacy (x)")
    legacy.execute("INSERT INTO legacy VALUES (42)")
    legacy.commit()
    legacy.close()

    open_library(db_path).close()
    backups = list(db_path.parent.glob("library.v0.*.bak.db"))
    assert len(backups) == 1
    assert sqlite3.connect(backups[0]).execute("SELECT x FROM legacy").fetchone() == (42,)


def test_newer_database_is_refused(db_path):
    db_path.parent.mkdir(parents=True)
    conn = sqlite3.connect(db_path)
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    conn.close()
    with pytest.raises(LibraryError, match="newer"):
        open_library(db_path)


def test_readonly_open(db_path):
    assert open_library_readonly(db_path) is None
    open_library(db_path).close()
    conn = open_library_readonly(db_path)
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("INSERT INTO curation_log (at, action, payload) VALUES ('', '', '{}')")
    conn.close()


def test_entry_status_is_constrained(db_path):
    conn = open_library(db_path)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO entry (ledger_id, container_id, identity_key, status, created_at)"
                     " VALUES (1, 1, 'k', 'lost', '')")
