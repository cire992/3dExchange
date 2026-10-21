"""Environments with several roots, offline roots, environment settings and forgetting."""

import shutil

from builders import env_report, root_report
from exchange.db import repository as repo
from exchange.scanner.scan import run_rescan


def test_daz_content_directories_form_one_environment(scan, daz_two_dirs, library):
    report = scan(daz_two_dirs)
    daz = env_report(report, "daz_studio")
    assert daz.name == "Daz Studio"
    assert sorted(r.path.rsplit("\\", 1)[-1].rsplit("/", 1)[-1] for r in daz.roots) == ["Daz Connect", "My Library"]

    conn = library()
    assert [e["type_id"] for e in repo.list_environments(conn)] == ["daz_studio"]
    containers = conn.execute("SELECT name, kind FROM container ORDER BY name").fetchall()
    assert [tuple(c) for c in containers] == [("Daz Connect", "content_directory"),
                                              ("My Library", "content_directory")]


def test_dim_and_connect_installs_are_one_product(scan, daz_two_dirs, library):
    scan(daz_two_dirs)
    conn = library()
    marius = conn.execute(
        "SELECT d.id, d.name, count(DISTINCT e.id) AS entries FROM dossier d"
        " JOIN ledger l ON l.dossier_id = d.id JOIN entry e ON e.ledger_id = l.id"
        " WHERE d.id IN (SELECT dossier_id FROM dossier_field WHERE field = 'product_key'"
        " AND value = '\"daz:12345\"') GROUP BY d.id").fetchall()
    assert len(marius) == 1
    assert marius[0]["name"] == "Marius HD-8K for Genesis 9"  # the manifest's name beats the placeholder
    assert marius[0]["entries"] == 2
    # Connect files are typed as if the cloud folder were a content directory.
    connect_preset = conn.execute("SELECT type_id, parent_id FROM dossier WHERE name = 'Marius Connect'").fetchone()
    assert connect_preset["type_id"] == "daz_character_preset"
    assert connect_preset["parent_id"] == marius[0]["id"]


def test_rescanning_again_keeps_the_merge(scan, daz_two_dirs, library):
    scan(daz_two_dirs)
    first = dict(library().execute("SELECT name, uid FROM dossier").fetchall())
    scan(daz_two_dirs / "Daz Connect")  # one root only: the other root's entries must stay live
    scan(daz_two_dirs)
    conn = library()
    assert dict(conn.execute("SELECT name, uid FROM dossier").fetchall()) == first
    assert conn.execute("SELECT count(*) FROM entry WHERE status = 'retired'").fetchone()[0] == 0


def test_missing_root_goes_offline_and_keeps_entries(scan, definitions, db_path, daz_two_dirs, library):
    scan(daz_two_dirs)
    shutil.rmtree(daz_two_dirs / "Daz Connect")
    report = run_rescan(db_path=db_path, definitions=definitions)
    daz = env_report(report, "daz_studio")
    statuses = sorted(r.status for r in daz.roots)
    assert statuses == ["offline", "scanned"]
    offline = next(r for r in daz.roots if r.status == "offline")
    assert offline.offline_days == 0
    conn = library()
    assert conn.execute("SELECT count(*) FROM entry WHERE status = 'retired'").fetchone()[0] == 0
    roots = {r["status"]: r for r in repo.list_roots(conn)}
    assert roots["offline"]["offline_since"]


def test_long_offline_root_prompts(scan, definitions, db_path, daz_two_dirs, library):
    scan(daz_two_dirs)
    conn = library()
    conn.execute("UPDATE environment_root SET status = 'offline', offline_since = '2020-01-01T00:00:00+00:00'"
                 " WHERE path LIKE '%Connect'")
    shutil.rmtree(daz_two_dirs / "Daz Connect")
    report = run_rescan(db_path=db_path, definitions=definitions)
    assert any("offline for" in n and "exchange env forget" in n for n in report.notes)


def test_user_ignore_rules_apply_on_rescan(scan, definitions, db_path, mo2_instance, library):
    scan(mo2_instance)
    conn = library()
    env_id = repo.list_environments(conn)[0]["id"]
    with repo.transaction(conn):
        repo.set_user_config(conn, env_id, {"ignore": ["mods/Test Requisitions/**"]})
    report = run_rescan(db_path=db_path, definitions=definitions)
    root = root_report(report, "skyrim_se")
    assert root.identification.products == 1
    assert root.identification.retired_entries == 2  # the mod's product and its mesh


def test_forget_environment(scan, mixed, library):
    scan(mixed)
    conn = library()
    daz = next(e for e in repo.list_environments(conn) if e["type_id"] == "daz_studio")
    uid = conn.execute("SELECT uid FROM dossier WHERE name = 'Loose Boots'").fetchone()[0]
    with repo.transaction(conn):
        repo.set_override_field(conn, uid, "name", "Cowboy Boots")
        removed = repo.forget_environment(conn, daz["id"])
    assert removed == 7
    assert "daz_studio" not in [e["type_id"] for e in repo.list_environments(conn)]
    assert conn.execute("SELECT count(*) FROM dossier WHERE uid = ?", (uid,)).fetchone()[0] == 0
    # The user's edit is kept, ready if the environment comes back with the same identity.
    assert conn.execute("SELECT count(*) FROM override_field WHERE dossier_uid = ?", (uid,)).fetchone()[0] == 1
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert (mixed / "Daz Library" / "People").is_dir()  # nothing on disk changed
