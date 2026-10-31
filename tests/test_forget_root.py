"""exchange env forget --root: one folder of a place goes, the place stays (R3d-5)."""

import json
import shutil
from pathlib import Path

import pytest

from builders import glb_bytes, write
from exchange.cli import main
from exchange.db import repository as repo
from exchange.environments import can_forget_root, register_root
from exchange.paths import fold
from exchange.scanner.scan import run_rescan
from test_claim_paths import registry_with, world  # noqa: F401  (the fixture)
from test_cli_claim_walk import add, claim_cmd, claim_file, use
from test_endpoints_join_place import run_to

OLD = "2020-01-01T00:00:00+00:00"
COUNTED = ("environment_root", "file", "container", "entry", "ledger", "dossier", "scan")
OVERRIDES = ("override_field", "override_tag", "override_link", "collection_member", "curation_log")


def counts(conn, tables=COUNTED):
    return {t: conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in tables}


def rows(conn, tables=OVERRIDES):
    return {t: [tuple(r) for r in conn.execute(f"SELECT * FROM {t} ORDER BY 1, 2")] for t in tables}


def disk(*folders):
    return {str(p): (p.stat().st_size, p.stat().st_mtime_ns)
            for folder in folders for p in sorted(folder.rglob("*")) if p.is_file()}


def forget(capsys, db, env_id, *argv):
    code = main(["env", "forget", str(env_id), *argv, "--db", str(db)])
    out = capsys.readouterr()
    return code, out.out, out.err


def join_folder(conn, definitions, db, folder, env_id):
    """A folder that joined the place as a later root, holding one mesh, scanned."""
    write(folder / "box.glb", glb_bytes())
    register_root(conn, definitions, folder, repo.get_environment(conn, env_id)["type_id"], environment_id=env_id)
    run_rescan(db_path=db, definitions=definitions)
    return folder


def root_row(conn, folder):
    return repo.find_root(conn, fold(str(folder.resolve())))


def first_path(conn, env_id):
    return Path(repo.list_roots(conn, env_id)[0]["path"])


@pytest.fixture
def joined(world, tmp_path):
    """The world's loose-files place with a folder elsewhere joined to it, holding box.glb."""
    conn, env_id = world["conn"], world["envs"]["loose_files"]["id"]
    folder = join_folder(conn, world["definitions"], world["db"], tmp_path / "elsewhere" / "joined", env_id)
    return {**world, "env_id": env_id, "joined": folder, "root": root_row(conn, folder),
            "name": world["envs"]["loose_files"]["name"]}


def first_dossiers(conn, env_id):
    """uid, name and entry count of every dossier with an entry on the place's first root."""
    first = repo.list_roots(conn, env_id)[0]["id"]
    return sorted(tuple(r) for r in conn.execute(
        "SELECT d.uid, d.name, (SELECT count(*) FROM ledger l JOIN entry e ON e.ledger_id = l.id"
        " WHERE l.dossier_id = d.id) FROM dossier d WHERE d.id IN (SELECT l.dossier_id FROM ledger l"
        " JOIN entry e ON e.ledger_id = l.id JOIN container c ON c.id = e.container_id"
        " WHERE c.root_id = ?)", (first,)))


def only_on(conn, root_id):
    """The uids of the dossiers whose entries are all on this root."""
    return {r[0] for r in conn.execute(
        "SELECT d.uid FROM dossier d WHERE EXISTS (SELECT 1 FROM ledger l JOIN entry e ON e.ledger_id = l.id"
        " JOIN container c ON c.id = e.container_id WHERE l.dossier_id = d.id AND c.root_id = ?)"
        " AND NOT EXISTS (SELECT 1 FROM ledger l JOIN entry e ON e.ledger_id = l.id"
        " JOIN container c ON c.id = e.container_id WHERE l.dossier_id = d.id AND c.root_id != ?)",
        (root_id, root_id))}


def in_fts(conn, uid):
    return conn.execute("SELECT count(*) FROM dossier_fts WHERE rowid = (SELECT id FROM dossier WHERE uid = ?)",
                        (uid,)).fetchone()[0]


# Forgetting a joined root -----------------------------------------------------------------------


def test_the_place_and_the_first_roots_dossiers_stay(capsys, joined):
    conn, env_id = joined["conn"], joined["env_id"]
    env = dict(repo.get_environment(conn, env_id))
    first = repo.list_roots(conn, env_id)[0]["id"]
    before = first_dossiers(conn, env_id)
    assert before
    code, out, err = forget(capsys, joined["db"], env_id, "--root", str(joined["joined"]), "--yes")
    assert code == 0 and err == "" and out.startswith("Forgot ")
    after = dict(repo.get_environment(conn, env_id))
    assert (after["name"], after["user_config"]) == (env["name"], env["user_config"])
    assert [r["id"] for r in repo.list_roots(conn, env_id)] == [first]
    assert first_dossiers(conn, env_id) == before


@pytest.mark.parametrize("as_json", [False, True])
def test_dossiers_only_the_joined_root_held_go_and_are_counted(capsys, joined, as_json):
    conn, env_id, root = joined["conn"], joined["env_id"], joined["root"]
    write(joined["joined"] / "tick.wav", b"RIFF....WAVEfmt ")
    run_rescan(db_path=joined["db"], definitions=joined["definitions"])
    gone = only_on(conn, root["id"])
    assert len(gone) >= 2 and all(in_fts(conn, u) for u in gone)
    args = ["--root", str(joined["joined"]), "--yes", *(["--json"] if as_json else [])]
    code, out, _ = forget(capsys, joined["db"], env_id, *args)
    assert code == 0
    if as_json:
        assert json.loads(out) == {"forgotten": env_id, "root": root["path"], "dossiers_removed": len(gone)}
    else:
        assert out.strip() == (f"Forgot {root['path']} from {joined['name']}; "
                               f"{len(gone)} dossiers no longer in any environment were removed.")
    for uid in gone:
        assert conn.execute("SELECT count(*) FROM dossier WHERE uid = ?", (uid,)).fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM dossier_fts").fetchone()[0] == counts(conn)["dossier"]


def test_nothing_scanned_from_the_root_is_left(capsys, joined):
    conn, env_id, root = joined["conn"], joined["env_id"], joined["root"]
    conn.execute("INSERT INTO lexicon_generated (lexicon_id, root_id, value, word) VALUES ('l', ?, 'v', 'w')",
                 (root["id"],))
    file_ids = [r[0] for r in conn.execute("SELECT id FROM file WHERE root_id = ?", (root["id"],))]
    assert file_ids
    code, _, _ = forget(capsys, joined["db"], env_id, "--root", str(joined["joined"]), "--yes")
    assert code == 0
    for table in ("file", "container", "scan", "lexicon_generated"):
        assert conn.execute(f"SELECT count(*) FROM {table} WHERE root_id = ?", (root["id"],)).fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM environment_root WHERE id = ?", (root["id"],)).fetchone()[0] == 0
    marks = ",".join("?" * len(file_ids))
    assert conn.execute(f"SELECT count(*) FROM entry_file WHERE file_id IN ({marks})", file_ids).fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM entry_file WHERE file_id NOT IN (SELECT id FROM file)"
                        " OR entry_id NOT IN (SELECT id FROM entry)").fetchone()[0] == 0
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_a_dossier_on_both_roots_keeps_its_ledger_and_first_entries(capsys, joined):
    conn, env_id, root = joined["conn"], joined["env_id"], joined["root"]
    run_to(joined, joined["barrel"], env_id, joined["joined"])
    barrel = conn.execute("SELECT id FROM dossier WHERE uid = ?", (joined["barrel"],)).fetchone()[0]
    ledger = conn.execute("SELECT id FROM ledger WHERE dossier_id = ? AND environment_id = ?",
                          (barrel, env_id)).fetchone()[0]

    def entries():
        return [tuple(r) for r in conn.execute(
            "SELECT e.id, c.root_id FROM entry e JOIN container c ON c.id = e.container_id"
            " WHERE e.ledger_id = ? ORDER BY e.id", (ledger,))]

    def places():
        return conn.execute("SELECT places FROM dossier_fts WHERE rowid = ?", (barrel,)).fetchone()[0].split()

    before = entries()
    assert {r[1] for r in before} == {root["id"], repo.list_roots(conn, env_id)[0]["id"]}
    assert "Barrel01" in places()
    code, _, _ = forget(capsys, joined["db"], env_id, "--root", str(joined["joined"]), "--yes")
    assert code == 0
    assert entries() == [e for e in before if e[1] != root["id"]]
    assert conn.execute("SELECT id FROM ledger WHERE dossier_id = ? AND environment_id = ?",
                        (barrel, env_id)).fetchone()[0] == ledger
    assert "Barrel01" not in places() and "barrel" in places()


def test_a_dossier_with_a_ledger_in_another_place_survives_without_this_one(capsys, joined):
    conn, env_id = joined["conn"], joined["env_id"]
    box = conn.execute("SELECT id FROM dossier WHERE name = 'box'").fetchone()[0]
    daz = joined["envs"]["daz_studio"]["id"]
    container = conn.execute("SELECT id FROM container WHERE environment_id = ? LIMIT 1", (daz,)).fetchone()[0]
    ledger = conn.execute("INSERT INTO ledger (dossier_id, environment_id) VALUES (?, ?)", (box, daz)).lastrowid
    conn.execute("INSERT INTO entry (ledger_id, container_id, identity_key, status, created_at)"
                 " VALUES (?, ?, 'k', 'copied', '2026-01-01')", (ledger, container))
    code, _, _ = forget(capsys, joined["db"], env_id, "--root", str(joined["joined"]), "--yes")
    assert code == 0
    assert conn.execute("SELECT count(*) FROM dossier WHERE id = ?", (box,)).fetchone()[0] == 1
    assert [r[0] for r in conn.execute("SELECT environment_id FROM ledger WHERE dossier_id = ?", (box,))] == [daz]
    assert conn.execute("SELECT count(*) FROM dossier_fts WHERE rowid = ?", (box,)).fetchone()[0] == 1


def test_the_users_overrides_are_never_touched(capsys, joined):
    conn, env_id, root = joined["conn"], joined["env_id"], joined["root"]
    uid = conn.execute("SELECT uid FROM dossier WHERE name = 'box'").fetchone()[0]
    assert uid in only_on(conn, root["id"])
    with repo.transaction(conn):
        repo.set_override_field(conn, uid, "name", "My Box")
    conn.execute("INSERT INTO override_tag VALUES (?, 'mine', 'add', '2026-01-01')", (uid,))
    conn.execute("INSERT INTO override_link (kind, subject, target_uid, set_at)"
                 " VALUES ('dossier_to_parent', ?, NULL, '2026-01-01')", (uid,))
    conn.execute("INSERT INTO collection VALUES ('c1', 'Mine', NULL, '2026-01-01')")
    conn.execute("INSERT INTO collection_member VALUES ('c1', ?, '2026-01-01')", (uid,))
    conn.execute("INSERT INTO curation_log (at, action, payload) VALUES ('2026-01-01', 'set', '{}')")
    before = rows(conn)
    assert all(before[t] for t in OVERRIDES)
    code, _, _ = forget(capsys, joined["db"], env_id, "--root", str(joined["joined"]), "--yes")
    assert code == 0
    assert conn.execute("SELECT count(*) FROM dossier WHERE uid = ?", (uid,)).fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM override_field WHERE dossier_uid = ?", (uid,)).fetchone()[0] == 1
    assert rows(conn) == before


def test_without_yes_it_says_what_would_go_and_changes_nothing(capsys, joined):
    conn, env_id = joined["conn"], joined["env_id"]
    before = counts(conn)
    code, out, err = forget(capsys, joined["db"], env_id, "--root", str(joined["joined"]))
    assert code == 1 and err == ""
    assert joined["root"]["path"] in out and joined["name"] in out and "--yes" in out
    assert counts(conn) == before


def test_nothing_on_disk_changes(capsys, joined):
    folders = (joined["joined"], first_path(joined["conn"], joined["env_id"]))
    snapshot = disk(*folders)
    assert snapshot
    code, _, _ = forget(capsys, joined["db"], joined["env_id"], "--root", str(joined["joined"]), "--yes")
    assert code == 0
    assert disk(*folders) == snapshot


def test_the_folder_matches_in_another_case_and_with_a_trailing_separator(capsys, joined):
    spelled = str(joined["joined"]).upper() + "\\"
    code, out, _ = forget(capsys, joined["db"], joined["env_id"], "--root", spelled, "--yes")
    assert code == 0 and "Forgot" in out
    assert len(repo.list_roots(joined["conn"], joined["env_id"])) == 1


def test_a_folder_deleted_from_disk_can_be_forgotten_by_its_path(capsys, joined):
    env_id = joined["env_id"]
    shutil.rmtree(joined["joined"])
    run_rescan(db_path=joined["db"], definitions=joined["definitions"])

    def status():
        assert main(["env", "show", str(env_id), "--json", "--db", str(joined["db"])]) == 0
        return json.loads(capsys.readouterr().out)["status"]

    assert status() == "partial"
    code, _, _ = forget(capsys, joined["db"], env_id, "--root", str(joined["joined"]), "--yes")
    assert code == 0
    assert status() == "online"


def test_a_folder_that_is_not_a_root_of_the_place_is_refused(capsys, joined, tmp_path):
    conn, env_id = joined["conn"], joined["env_id"]
    daz_root = first_path(conn, joined["envs"]["daz_studio"]["id"])
    before = counts(conn)
    for folder in (tmp_path / "nowhere", daz_root):
        for extra in ([], ["--yes"]):
            code, out, err = forget(capsys, joined["db"], env_id, "--root", str(folder), *extra)
            assert code == 2 and out == "" and joined["name"] in err
            assert counts(conn) == before
    assert root_row(conn, daz_root)["environment_id"] == joined["envs"]["daz_studio"]["id"]


# Roots a place can't lose alone -------------------------------------------------------------------


def refused(capsys, conn, db, env_id, root, name=None):
    """--root is refused with and without --yes, pointing to the whole-place form; nothing changes."""
    name = name or repo.get_environment(conn, env_id)["name"]
    before = counts(conn)
    for extra in ([], ["--yes"]):
        code, out, err = forget(capsys, db, env_id, "--root", root, *extra)
        assert code == 2 and out == ""
        assert name in err and f"exchange env forget {env_id}" in err
        assert counts(conn) == before


@pytest.mark.parametrize("fixture, type_id", [
    ("loose_folder", "loose_files"), ("mo2_instance", "skyrim_se"), ("unreal", "unreal_project")])
def test_a_single_root_places_first_root_is_refused_while_a_root_joined(
        capsys, request, scan, library, definitions, db_path, tmp_path, fixture, type_id):
    scan(request.getfixturevalue(fixture))
    conn = library()
    env_id = conn.execute("SELECT id FROM environment WHERE type_id = ?", (type_id,)).fetchone()[0]
    join_folder(conn, definitions, db_path, tmp_path / "elsewhere" / "joined", env_id)
    first = repo.list_roots(conn, env_id)[0]
    assert len(repo.list_roots(conn, env_id)) == 2 and not can_forget_root(conn, definitions, first)
    refused(capsys, conn, db_path, env_id, first["path"])


def test_a_single_root_places_only_root_is_refused(capsys, scan, library, db_path, loose_folder):
    scan(loose_folder)
    conn = library()
    refused(capsys, conn, db_path, repo.list_environments(conn)[0]["id"], str(loose_folder))


def test_a_multi_root_places_only_root_is_refused(capsys, scan, library, db_path, daz_library):
    scan(daz_library)
    conn = library()
    env_id = repo.list_environments(conn)[0]["id"]
    assert len(repo.list_roots(conn, env_id)) == 1
    refused(capsys, conn, db_path, env_id, str(daz_library))


# Daz Studio: any content directory can go ---------------------------------------------------------


@pytest.fixture
def daz(scan, library, daz_two_dirs):
    scan(daz_two_dirs)
    conn = library()
    env_id = repo.list_environments(conn)[0]["id"]
    return conn, env_id, repo.list_roots(conn, env_id)


def by_name(roots):
    return {Path(r["path"]).name: r for r in roots}


def entries_of(conn, name):
    return conn.execute(
        "SELECT count(*) FROM entry e JOIN ledger l ON l.id = e.ledger_id JOIN dossier d ON d.id = l.dossier_id"
        " WHERE d.name = ?", (name,)).fetchone()[0]


def root_entries(conn, root_id):
    return [tuple(r) for r in conn.execute(
        "SELECT e.id, e.status FROM entry e JOIN container c ON c.id = e.container_id WHERE c.root_id = ?"
        " ORDER BY e.id", (root_id,))]


def test_a_daz_content_directory_can_go_and_a_product_in_both_keeps_the_other_entry(capsys, daz, db_path):
    conn, env_id, roots = daz
    mine, connect = by_name(roots)["My Library"], by_name(roots)["Daz Connect"]
    twin = "Marius HD-8K for Genesis 9"
    assert (entries_of(conn, twin), entries_of(conn, "Marius Connect")) == (2, 1)
    kept = root_entries(conn, mine["id"])
    code, out, _ = forget(capsys, db_path, env_id, "--root", connect["path"], "--yes")
    assert code == 0 and "Forgot" in out
    assert (entries_of(conn, twin), entries_of(conn, "Marius Connect")) == (1, 0)
    assert conn.execute("SELECT count(*) FROM dossier WHERE name = ?", (twin,)).fetchone()[0] == 1
    assert conn.execute("SELECT count(*) FROM dossier WHERE name = 'Marius Connect'").fetchone()[0] == 0
    assert root_entries(conn, mine["id"]) == kept


def test_a_multi_root_places_first_root_can_go_too(capsys, daz, db_path, definitions):
    conn, env_id, roots = daz
    first, other = roots
    assert can_forget_root(conn, definitions, first) and can_forget_root(conn, definitions, other)
    code, _, _ = forget(capsys, db_path, env_id, "--root", first["path"], "--yes")
    assert code == 0
    assert [r["id"] for r in repo.list_roots(conn, env_id)] == [other["id"]]
    refused(capsys, conn, db_path, env_id, other["path"])


# What happens to the rest --------------------------------------------------------------------------


def test_a_claim_walked_to_a_joined_folder_goes_back_to_converted(capsys, joined, monkeypatch):
    use(monkeypatch, registry_with("stamp_images", "to_daz"))
    conn, env_id = joined["conn"], joined["env_id"]
    claim = add(capsys, joined, "barrel", "loose_files", "--folder", str(joined["joined"]))
    code, out, _ = claim_cmd(capsys, joined, "walk", claim["id"], "--run", "--json")
    assert code == 0 and json.loads(out)["milestone"] == "installed"
    code, _, _ = forget(capsys, joined["db"], env_id, "--root", str(joined["joined"]), "--yes")
    assert code == 0
    code, out, _ = claim_cmd(capsys, joined, "show", claim["id"], "--json")
    data = json.loads(out)
    assert code == 0 and data["milestone"] == "converted"
    assert data["turn_line"].startswith("Walk it again")
    assert "milestone: converted" in claim_file(claim).read_text(encoding="utf-8")
    assert conn.execute("SELECT count(*) FROM dossier WHERE uid = ?", (joined["barrel"],)).fetchone()[0] == 1


def test_a_rescan_does_not_bring_a_forgotten_folder_back(capsys, joined):
    conn, env_id, root = joined["conn"], joined["env_id"], joined["root"]
    gone = only_on(conn, root["id"])
    assert gone
    code, _, _ = forget(capsys, joined["db"], env_id, "--root", str(joined["joined"]), "--yes")
    assert code == 0 and joined["joined"].is_dir()
    report = run_rescan(db_path=joined["db"], definitions=joined["definitions"])
    assert str(joined["joined"]) not in [r.path for e in report.environments for r in e.roots]
    assert root_row(conn, joined["joined"]) is None
    assert conn.execute("SELECT count(*) FROM dossier WHERE uid IN (%s)" % ",".join("?" * len(gone)),
                        list(gone)).fetchone()[0] == 0


def test_forgetting_the_whole_place_is_unchanged(capsys, joined):
    conn, env_id = joined["conn"], joined["env_id"]
    daz_dossiers = conn.execute("SELECT count(*) FROM dossier WHERE name = 'Loose Boots'").fetchone()[0]
    code, out, _ = forget(capsys, joined["db"], env_id)
    assert code == 1 and "--yes" in out and repo.get_environment(conn, env_id) is not None
    code, out, _ = forget(capsys, joined["db"], env_id, "--yes")
    assert code == 0 and "Forgot" in out
    assert repo.get_environment(conn, env_id) is None
    assert repo.list_roots(conn, env_id) == [] and root_row(conn, joined["joined"]) is None
    assert conn.execute("SELECT count(*) FROM dossier WHERE name IN ('box', 'ding', 'Barrel01')").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM dossier WHERE name = 'Loose Boots'").fetchone()[0] == daz_dossiers


# The 30-day note ----------------------------------------------------------------------------------


def long_offline(conn, root_id):
    conn.execute("UPDATE environment_root SET status = 'offline', offline_since = ? WHERE id = ?", (OLD, root_id))


def offline_notes(db, definitions):
    return [n for n in run_rescan(db_path=db, definitions=definitions).notes if "offline for" in n]


def test_a_joined_root_offline_for_long_advises_forgetting_it_alone(joined):
    conn, env_id, root = joined["conn"], joined["env_id"], joined["root"]
    long_offline(conn, root["id"])
    shutil.rmtree(joined["joined"])
    notes = offline_notes(joined["db"], joined["definitions"])
    assert len(notes) == 1
    assert notes[0].endswith(f'run: exchange env forget {env_id} --root "{root["path"]}"')


@pytest.mark.parametrize("which", [0, 1])
def test_a_multi_root_places_offline_root_advises_forgetting_it_alone(daz, daz_two_dirs, db_path, definitions, which):
    conn, env_id, roots = daz
    root = roots[which]
    long_offline(conn, root["id"])
    shutil.rmtree(root["path"])
    notes = offline_notes(db_path, definitions)
    assert len(notes) == 1
    assert notes[0].endswith(f'run: exchange env forget {env_id} --root "{root["path"]}"')


def test_an_offline_first_root_advises_forgetting_the_place(joined):
    conn, env_id = joined["conn"], joined["env_id"]
    first = repo.list_roots(conn, env_id)[0]
    long_offline(conn, first["id"])
    shutil.rmtree(first["path"])
    notes = offline_notes(joined["db"], joined["definitions"])
    assert len(notes) == 1 and "--root" not in notes[0]
    assert notes[0] == (f"{first['path']} has been offline for {notes[0].split('offline for ')[1].split(' ')[0]}"
                        f" days; if it is gone for good, run: exchange env forget {env_id}")


def test_an_offline_only_root_advises_forgetting_the_place(scan, library, db_path, definitions, loose_folder):
    scan(loose_folder)
    conn = library()
    env_id = repo.list_environments(conn)[0]["id"]
    long_offline(conn, repo.list_roots(conn, env_id)[0]["id"])
    shutil.rmtree(loose_folder)
    notes = offline_notes(db_path, definitions)
    assert len(notes) == 1 and "--root" not in notes[0]
    assert notes[0].endswith(f"if it is gone for good, run: exchange env forget {env_id}")
