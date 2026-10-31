"""An endpoint folder outside a place joins the requisition's own environment (R3d-4)."""

import json

import pytest

from exchange import claims  # noqa: F401
from exchange.cli import main
from exchange.db import repository as repo
from exchange.environments import register_root
from exchange.paths import fold
from exchange.requisitions.plan import plan_requisition, queue_plan
from exchange.requisitions.runner import run_queue
from exchange.scanner.scan import environment_name, run_rescan
from test_claim_paths import registry_with, world  # noqa: F401  (the fixture)
from test_cli_claim_walk import add, claim_cmd, claim_file, use


def counts(conn):
    return tuple(conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                 for table in ("environment", "environment_root"))


def root_of(conn, folder):
    return repo.find_root(conn, fold(str(folder.resolve())))


def run_to(w, uid, env_id, folder=None, processes=("stamp_images",)):
    """Plan, queue and run one requisition; returns its id."""
    registry = registry_with("stamp_images", "to_daz")
    plan = plan_requisition(w["conn"], w["definitions"], registry, uid, env_id, processes=list(processes),
                            endpoint_folder=None if folder is None else str(folder))
    rid = queue_plan(w["conn"], plan, registry)
    run_queue(w["db"], w["definitions"], registry, only=[rid])
    return rid


def state_of(w, rid):
    return w["conn"].execute("SELECT state FROM requisition WHERE id = ?", (rid,)).fetchone()[0]


def live_entries(w, rid):
    return w["conn"].execute(
        "SELECT e.id, l.environment_id FROM entry e JOIN ledger l ON l.id = e.ledger_id"
        " WHERE e.requisition_id = ? AND e.status != 'retired'", (rid,)).fetchall()


def assert_joined(w, rid, folder, env_id, before):
    assert state_of(w, rid) == "fulfilled"
    assert counts(w["conn"])[0] == before[0]
    assert root_of(w["conn"], folder)["environment_id"] == env_id
    entries = live_entries(w, rid)
    assert entries and {e["environment_id"] for e in entries} == {env_id}


@pytest.fixture
def outside(tmp_path):
    folder = tmp_path / "elsewhere" / "out"
    folder.mkdir(parents=True)
    return folder


def test_output_outside_a_single_root_place_joins_it(world, outside):
    env_id, before = world["envs"]["loose_files"]["id"], counts(world["conn"])
    rid = run_to(world, world["barrel"], env_id, outside)
    assert_joined(world, rid, outside, env_id, before)
    assert counts(world["conn"]) == (before[0], before[1] + 1)


def test_a_claim_walked_outside_reaches_installed(capsys, world, outside, monkeypatch):
    use(monkeypatch, registry_with("stamp_images", "to_daz"))
    claim = add(capsys, world, "barrel", "loose_files", "--folder", str(outside))
    code, out, err = claim_cmd(capsys, world, "walk", claim["id"], "--run", "--json")
    data = json.loads(out)
    assert code == 0 and err == ""
    assert data["milestone"] == "installed" and data["turn"] == "you"
    assert data["turn_line"] == "Close it, or take it into play"
    assert "milestone: installed" in claim_file(claim).read_text(encoding="utf-8")
    assert root_of(world["conn"], outside)["environment_id"] == world["envs"]["loose_files"]["id"]


def test_a_second_requisition_finds_the_root_known(world, outside):
    env_id = world["envs"]["loose_files"]["id"]
    run_to(world, world["barrel"], env_id, outside)
    after_first = counts(world["conn"])
    donut = world["conn"].execute("SELECT uid FROM dossier WHERE name = 'Donut01_Pink'").fetchone()[0]
    rid = run_to(world, donut, env_id, outside, processes=("copy_entry",))
    assert_joined(world, rid, outside, env_id, after_first)
    assert counts(world["conn"]) == after_first


def test_a_folder_outside_a_multi_root_place_behaves_as_today(world, outside):
    daz_id = world["envs"]["daz_studio"]["id"]
    dress = world["conn"].execute("SELECT uid FROM dossier WHERE name = 'Summer Dress'").fetchone()[0]
    before = counts(world["conn"])
    rid = run_to(world, dress, daz_id, outside, processes=("copy_entry",))
    assert_joined(world, rid, outside, daz_id, before)


def test_the_environments_own_endpoint_setting_outside_its_root(world, outside):
    env_id, before = world["envs"]["loose_files"]["id"], counts(world["conn"])
    repo.set_user_config(world["conn"], env_id, {"endpoint": str(outside)})
    rid = run_to(world, world["barrel"], env_id)
    assert_joined(world, rid, outside, env_id, before)


def test_register_root_with_an_environment_joins_it(world, outside):
    conn, env_id = world["conn"], world["envs"]["loose_files"]["id"]
    before = counts(conn)
    assert register_root(conn, world["definitions"], outside, "loose_files", environment_id=env_id) == env_id
    assert root_of(conn, outside)["environment_id"] == env_id
    assert counts(conn) == (before[0], before[1] + 1)


def test_register_root_with_an_environment_joins_whatever_its_type(world, outside):
    conn, env_id = world["conn"], world["envs"]["loose_files"]["id"]
    before = counts(conn)
    assert register_root(conn, world["definitions"], outside, "unreal_project", environment_id=env_id) == env_id
    assert counts(conn) == (before[0], before[1] + 1)


def test_a_known_root_keeps_its_environment(world):
    conn = world["conn"]
    daz_id, loose_id = world["envs"]["daz_studio"]["id"], world["envs"]["loose_files"]["id"]
    known = world["root"] / "Daz Library"
    before = counts(conn)
    assert register_root(conn, world["definitions"], known, "daz_studio", environment_id=loose_id) == daz_id
    assert counts(conn) == before


def test_without_the_keyword_a_single_root_type_makes_an_environment_each(world, tmp_path):
    conn, definitions = world["conn"], world["definitions"]
    before = counts(conn)
    ids = []
    for name in ("one", "two"):
        folder = tmp_path / "fresh" / name
        folder.mkdir(parents=True)
        ids.append(register_root(conn, definitions, folder, "loose_files"))
        assert repo.get_environment(conn, ids[-1])["name"] == environment_name(
            definitions.environments["loose_files"], folder.resolve())
    assert len(set(ids)) == 2 and counts(conn) == (before[0] + 2, before[1] + 2)


def test_without_the_keyword_a_multi_root_type_gathers_its_roots(world, tmp_path):
    conn, definitions = world["conn"], world["definitions"]
    daz_id = world["envs"]["daz_studio"]["id"]
    before = counts(conn)
    for name in ("one", "two"):
        folder = tmp_path / "fresh" / name
        folder.mkdir(parents=True)
        assert register_root(conn, definitions, folder, "daz_studio") == daz_id
    assert counts(conn) == (before[0], before[1] + 2)


def check_layer_config(w, outside, type_id):
    """Copy something out of a scanned place to ``outside`` and rescan: the place keeps its settings."""
    conn = w["conn"]
    env_id = conn.execute("SELECT id FROM environment WHERE type_id = ?", (type_id,)).fetchone()[0]
    config = repo.get_environment(conn, env_id)["layer_config"]
    uid = conn.execute("SELECT d.uid FROM dossier d JOIN ledger l ON l.dossier_id = d.id"
                       " WHERE l.environment_id = ? AND d.type_id != 'product' LIMIT 1", (env_id,)).fetchone()[0]
    before = counts(conn)
    rid = run_to(w, uid, env_id, outside, processes=("copy_entry",))
    assert state_of(w, rid) == "fulfilled"
    assert root_of(conn, outside)["environment_id"] == env_id
    assert counts(conn) == (before[0], before[1] + 1)
    assert repo.get_environment(conn, env_id)["layer_config"] == config
    run_rescan(db_path=w["db"], definitions=w["definitions"])
    assert repo.get_environment(conn, env_id)["layer_config"] == config
    assert counts(conn) == (before[0], before[1] + 1)
    return env_id, config


def test_a_joined_root_leaves_an_mo2_places_settings_alone(scan, mo2_instance, library, definitions, db_path,
                                                          tmp_path):
    scan(mo2_instance)
    outside = tmp_path / "elsewhere" / "mo2out"
    outside.mkdir(parents=True)
    world = {"conn": library(), "definitions": definitions, "db": db_path}
    env_id, config = check_layer_config(world, outside, "skyrim_se")
    assert json.loads(config)["profiles"] == ["Default"]
    assert main(["env", "config", str(env_id), "--profile", "Default", "--db", str(db_path)]) == 0


def test_a_joined_root_leaves_an_unreal_places_settings_alone(scan, unreal, library, definitions, db_path, tmp_path):
    scan(unreal)
    outside = tmp_path / "elsewhere" / "unrealout"
    outside.mkdir(parents=True)
    world = {"conn": library(), "definitions": definitions, "db": db_path}
    _, config = check_layer_config(world, outside, "unreal_project")
    assert json.loads(config)["engine_association"] == "5.4"
