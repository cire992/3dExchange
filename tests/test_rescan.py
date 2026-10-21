import os

from conftest import env_report
from exchange.db import open_library
from exchange.db import repository as repo


def uids(conn):
    return dict(conn.execute("SELECT name, uid FROM dossier").fetchall())


def test_unchanged_rescan_keeps_identity(scan, mixed, db_path):
    scan(mixed)
    first = uids(open_library(db_path))
    report = scan(mixed)
    for env in report.environments:
        assert (env.new, env.changed, env.gone) == (0, 0, 0)
        assert env.unchanged == env.files
        assert env.registered
    assert uids(open_library(db_path)) == first


def test_changes_are_tracked_and_history_kept(scan, mo2_instance, db_path):
    scan(mo2_instance)
    mods = mo2_instance / "mods"
    (mods / "Test Requisitions" / "meshes" / "food" / "donut01_pink.nif").unlink()
    esp = mods / "Lard Lads Donuts" / "LardLads.esp"
    esp.write_bytes(b"a bigger plugin")
    (mods / "Lard Lads Donuts" / "meshes" / "clutter" / "cruller01.nif").write_bytes(b"nif")

    env = env_report(scan(mo2_instance), "skyrim_se")
    assert (env.new, env.changed, env.gone) == (1, 1, 1)
    assert env.identification.retired_entries == 1

    conn = open_library(db_path)
    row = conn.execute(
        "SELECT e.status, e.retired_at, f.state FROM dossier d JOIN ledger l ON l.dossier_id = d.id"
        " JOIN entry e ON e.ledger_id = l.id JOIN entry_file ef ON ef.entry_id = e.id"
        " JOIN file f ON f.id = ef.file_id WHERE d.name = 'donut01_pink'").fetchone()
    assert row["status"] == "retired" and row["retired_at"] and row["state"] == "gone"
    assert conn.execute("SELECT count(*) FROM dossier WHERE name = 'cruller01'").fetchone()[0] == 1


def test_returning_file_revives_its_entry(scan, loose_folder, db_path):
    wav = loose_folder / "sounds" / "ding.wav"
    scan(loose_folder)
    data = wav.read_bytes()
    wav.unlink()
    scan(loose_folder)
    wav.write_bytes(data)
    env = env_report(scan(loose_folder), "loose_files")
    assert env.new == 1
    conn = open_library(db_path)
    statuses = conn.execute(
        "SELECT e.status FROM dossier d JOIN ledger l ON l.dossier_id = d.id"
        " JOIN entry e ON e.ledger_id = l.id WHERE d.name = 'ding'").fetchall()
    assert [s[0] for s in statuses] == ["origin"]


def test_user_overrides_survive_rescans(scan, daz_library, db_path):
    scan(daz_library)
    conn = open_library(db_path)
    ids = uids(conn)
    boots, marius = ids["Loose Boots"], ids["Marius HD-8K for Genesis 9"]
    with repo.transaction(conn):
        repo.set_override_field(conn, boots, "name", "Cowboy Boots")
        repo.set_override_field(conn, boots, "license", "personal use")
        repo.set_override_tag(conn, boots, "Footwear", "add")
        repo.set_override_parent(conn, boots, marius)
    conn.close()

    # Touch the file so the rescan really reprocesses it.
    boots_file = daz_library / "People" / "Genesis 9" / "Clothing" / "Loose Boots" / "Loose Boots.duf"
    boots_file.write_bytes(b"changed")
    os.utime(boots_file, ns=(1, 1))
    scan(daz_library)

    conn = open_library(db_path)
    eff = repo.effective_dossier(conn, boots)
    assert eff["name"] == "Cowboy Boots" and eff["name_overridden"]
    assert eff["parent_id"] == conn.execute("SELECT id FROM dossier WHERE uid = ?", (marius,)).fetchone()[0]
    assert repo.effective_fields(conn, boots)["license"] == "personal use"
    assert repo.effective_tags(conn, boots) == {"Footwear"}
    # The scanned layer is still the scanner's own and is shown when the override is reverted.
    assert conn.execute("SELECT name FROM dossier WHERE uid = ?", (boots,)).fetchone()[0] == "Loose Boots"
    with repo.transaction(conn):
        repo.revert_override_field(conn, boots, "name")
    assert repo.effective_dossier(conn, boots)["name"] == "Loose Boots"
    assert conn.execute("SELECT count(*) FROM curation_log").fetchone()[0] == 5


def test_scanning_a_subfolder_rescans_its_environment(scan, mo2_instance, db_path):
    scan(mo2_instance)
    report = scan(mo2_instance / "mods" / "Lard Lads Donuts")
    assert report.notes and "inside the environment" in report.notes[0]
    env = env_report(report, "skyrim_se")
    assert env.gone == 0
    assert env.unchanged == env.files
