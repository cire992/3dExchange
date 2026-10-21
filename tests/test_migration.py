"""A Phase 1 (schema 1) library migrates to schema 2 with its data and the user's work intact."""

import sqlite3
from importlib import resources

from exchange.db import SCHEMA_VERSION, open_library
from exchange.db import repository as repo


def make_v1_library(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    sql = resources.files("exchange.db").joinpath("migrations", "0001_initial.sql").read_text(encoding="utf-8")
    conn = sqlite3.connect(path)
    conn.executescript(sql + "\nPRAGMA user_version = 1;")
    conn.executescript("""
        INSERT INTO environment VALUES (1, 'env1', 'loose_files', 'Loose', 'C:\\Stuff', 'c:\\stuff',
            NULL, '{}', 0.5, '[]', 'online', '2026-01-01', '2026-01-02');
        INSERT INTO scan (id, environment_id, started_at) VALUES (1, 1, '2026-01-01');
        INSERT INTO container VALUES (1, 1, 'folder', 'props', 'props', 'props', '{}');
        INSERT INTO file VALUES (1, 1, 1, 'props/Donut.glb', 'props/donut.glb', '.glb', 10, 5, 0, NULL,
            'present', 1, 1);
        INSERT INTO dossier VALUES (1, 'uid1', 'mesh', 'Donut', NULL, NULL, 0.56, '[]', '2026', '2026');
        INSERT INTO dossier_field VALUES (1, 'variant', '"pink"', 'scan:folder', '2026');
        INSERT INTO ledger VALUES (1, 1, 1);
        INSERT INTO entry VALUES (1, 1, 1, 'file:donut.glb', 'origin', NULL, NULL, '2026', NULL);
        INSERT INTO entry_file VALUES (1, 1, 'primary');
        INSERT INTO override_field VALUES ('uid1', 'name', '"Pink Donut"', '2026');
    """)
    conn.close()


def test_v1_library_migrates(db_path):
    make_v1_library(db_path)
    conn = open_library(db_path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert list(db_path.parent.glob("library.v1.*.bak.db"))

    [root] = repo.list_roots(conn)
    assert (root["path"], root["environment_id"], root["last_scanned_at"]) == ("C:\\Stuff", 1, "2026-01-02")
    assert conn.execute("SELECT root_id FROM file").fetchone()[0] == root["id"]
    assert conn.execute("SELECT root_id FROM container").fetchone()[0] == root["id"]
    assert conn.execute("SELECT root_id FROM scan").fetchone()[0] == root["id"]
    assert conn.execute("SELECT user_config FROM environment").fetchone()[0] == "{}"
    # Old per-handler scanned fields are dropped (the next scan rewrites them); user work stays.
    assert conn.execute("SELECT count(*) FROM dossier_field").fetchone()[0] == 0
    assert repo.effective_dossier(conn, "uid1")["name"] == "Pink Donut"
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    conn.close()
