"""A single-root place writes only through its first root, online or not; a folder that joined it never stands in (R3d-4)."""

import json
from pathlib import Path

import pytest

from exchange import claims
from exchange.db import repository as repo
from exchange.environments import register_root
from exchange.requisitions import lifecycle
from exchange.requisitions.endpoints import EndpointError, default_endpoint
from test_claim_paths import registry_with, world  # noqa: F401  (the fixture)
from test_cli_claim_walk import add, claim_cmd, count, use


def first_root(conn, env_id):
    return repo.list_roots(conn, env_id)[0]


def set_status(conn, root_id, status):
    conn.execute("UPDATE environment_root SET status = ? WHERE id = ?", (status, root_id))
    conn.commit()


def join(conn, definitions, folder, env_id):
    """A folder that joined the place as a later root (an endpoint outside it)."""
    folder.mkdir(parents=True)
    register_root(conn, definitions, folder, repo.get_environment(conn, env_id)["type_id"], environment_id=env_id)
    return folder


def refusals(conn, definitions, env_id, joined):
    """Every way of asking for an endpoint in a place whose first root is offline: all refused, nothing written."""
    absolute = joined.parent / "absolute"
    for setting in (None, "Content/Other", "mods/Other"):
        repo.set_user_config(conn, env_id, {} if setting is None else {"endpoint": setting})
        for folder in (None, absolute):
            with pytest.raises(EndpointError, match="has no online folder to write to"):
                default_endpoint(conn, definitions, env_id, "x", folder)
    with pytest.raises(EndpointError, match="has no online folder to write to"):
        default_endpoint(conn, definitions, env_id, "x", Path("Relative"))
    # a relative claim folder is not resolved against the joined root either
    assert claims._claim_folder(conn, definitions, "Sub/Dir", env_id, "place") is None
    assert not absolute.exists() and list(joined.iterdir()) == []


@pytest.mark.parametrize("fixture, type_id", [("mo2_instance", "skyrim_se"), ("unreal", "unreal_project")])
def test_an_offline_first_root_refuses_every_endpoint(request, scan, library, definitions, tmp_path, fixture, type_id):
    scan(request.getfixturevalue(fixture))
    conn = library()
    env_id = conn.execute("SELECT id FROM environment WHERE type_id = ?", (type_id,)).fetchone()[0]
    joined = join(conn, definitions, tmp_path / "elsewhere" / "joined", env_id)
    online = default_endpoint(conn, definitions, env_id, "x")
    assert Path(online.root) == Path(first_root(conn, env_id)["path"])
    set_status(conn, first_root(conn, env_id)["id"], "offline")
    refusals(conn, definitions, env_id, joined)


def loose_with_joined(w, tmp_path):
    conn, env_id = w["conn"], w["envs"]["loose_files"]["id"]
    return env_id, join(conn, w["definitions"], tmp_path / "elsewhere" / "joined", env_id)


def test_a_loose_files_claim_with_its_first_root_offline_does_not_walk(capsys, world, monkeypatch, tmp_path):
    use(monkeypatch, registry_with("stamp_images", "to_daz"))
    conn = world["conn"]
    env_id, joined = loose_with_joined(world, tmp_path)
    claim = add(capsys, world, "barrel", "loose_files")
    set_status(conn, first_root(conn, env_id)["id"], "offline")
    before = count(world)
    for argv in (("walk", claim["id"]), ("walk", claim["id"], "--run")):
        code, out, err = claim_cmd(capsys, world, *argv)
        assert code == 2 and out == "" and "has no online folder to write to" in err
    assert count(world) == before and list(joined.iterdir()) == []
    assert claims.read_one(conn, claim["id"]).milestone != "installed"


def test_with_the_first_root_online_the_default_endpoint_is_in_it(world, tmp_path):
    conn, definitions = world["conn"], world["definitions"]
    env_id, joined = loose_with_joined(world, tmp_path)
    assert joined.resolve() != Path(first_root(conn, env_id)["path"])
    endpoint = default_endpoint(conn, definitions, env_id, "x")
    assert Path(endpoint.root) == Path(first_root(conn, env_id)["path"])
    assert Path(endpoint.folder).parent == Path(first_root(conn, env_id)["path"])


def test_a_second_online_root_is_never_the_base_of_a_relative_folder(capsys, world, monkeypatch, tmp_path):
    use(monkeypatch, registry_with("stamp_images", "to_daz"))
    conn = world["conn"]
    env_id, _ = loose_with_joined(world, tmp_path)
    root = Path(first_root(conn, env_id)["path"])
    claim = add(capsys, world, "barrel", "loose_files", "--folder", "Props/Kept")
    code, out, _ = claim_cmd(capsys, world, "walk", claim["id"], "--json")
    assert code == 0
    folder = lifecycle.detail(conn, json.loads(out)["requisition"]["id"])["endpoint"]["folder"]
    assert folder == str((root / "Props" / "Kept").resolve())


def test_a_multi_root_place_with_its_first_root_offline_uses_another_online_root(world, tmp_path):
    conn, definitions = world["conn"], world["definitions"]
    daz_id = world["envs"]["daz_studio"]["id"]
    extra = tmp_path / "elsewhere" / "Second Library"
    extra.mkdir(parents=True)
    register_root(conn, definitions, extra, "daz_studio")
    assert len(repo.list_roots(conn, daz_id)) == 2
    set_status(conn, first_root(conn, daz_id)["id"], "offline")
    endpoint = default_endpoint(conn, definitions, daz_id, "x")
    assert Path(endpoint.folder) == extra.resolve().parent / "Exchange Conversions"
    assert claims._claim_folder(conn, definitions, "Sub", daz_id, "place") == str((extra.resolve() / "Sub"))
