"""A folder that joined a place can't retype it; its first root and a multi_root place still can (R3d-5)."""

import re

import pytest

from builders import glb_bytes, write
from exchange.cli import main
from exchange.db import repository as repo
from exchange.environments import register_root
from exchange.errors import ScanError


def state(conn):
    return ([tuple(r) for r in conn.execute("SELECT * FROM environment ORDER BY id")],
            [tuple(r) for r in conn.execute("SELECT * FROM library_setting ORDER BY key")],
            [tuple(r) for r in conn.execute("SELECT id, environment_id, path FROM environment_root ORDER BY id")])


def env_add(capsys, db, folder, type_id, *extra):
    code = main(["env", "add", str(folder), "--type", type_id, *extra, "--db", str(db)])
    out = capsys.readouterr()
    return code, out.out, out.err


@pytest.fixture
def mo2_joined(scan, library, definitions, mo2_instance, tmp_path):
    """An MO2 place with a folder elsewhere joined to it."""
    scan(mo2_instance)
    conn = library()
    env_id = repo.list_environments(conn)[0]["id"]
    folder = tmp_path / "elsewhere" / "joined"
    write(folder / "box.glb", glb_bytes())
    register_root(conn, definitions, folder, "skyrim_se", environment_id=env_id)
    return conn, env_id, folder


@pytest.mark.parametrize("other", ["loose_files", "daz_studio"])
def test_a_joined_folder_cant_retype_its_place(capsys, mo2_joined, definitions, db_path, other):
    conn, env_id, folder = mo2_joined
    name = repo.get_environment(conn, env_id)["name"]
    before = state(conn)
    code, out, err = env_add(capsys, db_path, folder, other, "--name", "X", "--visibility", "publishable")
    assert code == 2 and out == "" and name in err
    assert state(conn) == before
    with pytest.raises(ScanError, match=re.escape(name)):
        register_root(conn, definitions, folder, other, name="X", config={"visibility": "publishable"})
    assert state(conn) == before


def test_a_joined_folder_given_its_places_own_type_behaves_as_today(capsys, mo2_joined, db_path):
    conn, env_id, folder = mo2_joined
    code, out, _ = env_add(capsys, db_path, folder, "skyrim_se", "--name", "Renamed")
    assert code == 0 and "Renamed" in out
    env = repo.get_environment(conn, env_id)
    assert (env["name"], env["type_id"]) == ("Renamed", "skyrim_se")
    assert len(repo.list_roots(conn, env_id)) == 2


@pytest.mark.parametrize("joined_root", [False, True])
def test_a_first_root_still_retypes_its_place(capsys, scan, library, definitions, mo2_instance, tmp_path, db_path,
                                              joined_root):
    scan(mo2_instance)
    conn = library()
    env_id = repo.list_environments(conn)[0]["id"]
    if joined_root:
        register_root(conn, definitions, tmp_path / "elsewhere", "skyrim_se", environment_id=env_id) \
            if (tmp_path / "elsewhere").mkdir() is None else None
    code, _, _ = env_add(capsys, db_path, mo2_instance, "loose_files")
    assert code == 0
    assert repo.get_environment(conn, env_id)["type_id"] == "loose_files"
    assert len(repo.list_roots(conn, env_id)) == (2 if joined_root else 1)


@pytest.mark.parametrize("which", [0, 1])
def test_a_root_of_a_multi_root_place_still_retypes_it(capsys, scan, library, db_path, daz_two_dirs, which):
    scan(daz_two_dirs)
    conn = library()
    env_id = repo.list_environments(conn)[0]["id"]
    root = repo.list_roots(conn, env_id)[which]
    code, _, _ = env_add(capsys, db_path, root["path"], "loose_files")
    assert code == 0
    assert repo.get_environment(conn, env_id)["type_id"] == "loose_files"
