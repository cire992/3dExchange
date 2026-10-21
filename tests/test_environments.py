"""Registering reviewed environments and excluding folders (what the add-environment wizard does)."""

import json

import pytest

from builders import copy_fixture, env_report
from exchange.cli import main
from exchange.db import repository as repo
from exchange.environments import excluded_roots, register_root, set_excluded
from exchange.errors import ScanError
from exchange.scanner.scan import run_rescan


def test_registered_type_and_settings_are_used(library, definitions, db_path, mo2_instance):
    conn = library()
    with repo.transaction(conn):
        env_id = register_root(conn, definitions, mo2_instance, "mo2_generic", name="My Skyrim",
                               config={"mo2_profile": "Default", "visibility": "publishable"})
    env = repo.get_environment(conn, env_id)
    assert (env["name"], env["type_id"]) == ("My Skyrim", "mo2_generic")
    assert repo.user_config(conn, env_id) == {"mo2_profile": "Default", "visibility": "publishable"}
    assert conn.execute("SELECT count(*) FROM file").fetchone()[0] == 0  # nothing read yet

    report = run_rescan(db_path=db_path, definitions=definitions, environment_ids=[env_id])
    env = env_report(report, "mo2_generic")  # the user's choice beats detecting skyrim_se
    assert env.name == "My Skyrim"
    assert env.roots[0].identification.products == 2


def test_changing_the_type_of_a_known_root(scan, library, definitions, loose_folder):
    scan(loose_folder)
    conn = library()
    [env] = repo.list_environments(conn)
    with repo.transaction(conn):
        same = register_root(conn, definitions, loose_folder, "daz_studio")
    assert same == env["id"]
    assert repo.get_environment(conn, same)["type_id"] == "daz_studio"


def test_daz_roots_join_one_environment(library, definitions, daz_two_dirs):
    conn = library()
    with repo.transaction(conn):
        a = register_root(conn, definitions, daz_two_dirs / "My Library", "daz_studio")
        b = register_root(conn, definitions, daz_two_dirs / "Daz Connect", "daz_studio")
    assert a == b
    assert len(repo.list_roots(conn, a)) == 2


def test_register_errors(library, definitions, tmp_path):
    conn = library()
    with pytest.raises(ScanError, match="unknown environment type"):
        register_root(conn, definitions, tmp_path, "spaceship")
    with pytest.raises(ScanError, match="not a folder"):
        register_root(conn, definitions, tmp_path / "missing", "loose_files")
    with pytest.raises(ScanError, match="visibility"):
        register_root(conn, definitions, tmp_path, "loose_files", config={"visibility": "world"})


def test_excluded_folders_are_skipped(scan, library, mixed):
    conn = library()
    with repo.transaction(conn):
        set_excluded(conn, mixed / "MO2")
    report = scan(mixed)
    assert {e.type_id for e in report.environments} == {"daz_studio", "loose_files"}
    assert report.excluded == [str(mixed / "MO2")]
    assert conn.execute("SELECT count(*) FROM file WHERE rel_path LIKE 'MO2/%'").fetchone()[0] == 0

    scan(mixed / "MO2")  # scanning an excluded folder by name includes it again
    assert excluded_roots(conn) == []
    assert "skyrim_se" in {e["type_id"] for e in repo.list_environments(conn)}


def test_cli_env_add_and_exclude(capsys, db_path, mo2_instance, tmp_path):
    other = copy_fixture("loose_files", tmp_path / "scan" / "Other")
    assert main(["env", "add", str(mo2_instance), "--type", "skyrim_se", "--profile", "Default",
                 "--db", str(db_path), "--json"]) == 0
    added = json.loads(capsys.readouterr().out)
    assert added["type_id"] == "skyrim_se"
    assert main(["env", "exclude", str(other), "--db", str(db_path)]) == 0
    assert str(other) in capsys.readouterr().out
    assert main(["env", "exclude", str(other), "--undo", "--db", str(db_path)]) == 0
    assert "No folders are excluded" in capsys.readouterr().out
    assert main(["env", "add", str(other), "--type", "nope", "--db", str(db_path)]) == 2
