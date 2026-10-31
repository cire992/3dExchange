"""A place holds only what is on an online root: output on an offline or deleted root reads Converted (R3d-6)."""

import shutil

import pytest

from builders import glb_bytes, write
from exchange import claims
from exchange.db import repository as repo
from exchange.environments import register_root
from exchange.paths import fold
from exchange.requisitions.runner import run_queue
from exchange.scanner.scan import run_rescan
from test_claim_paths import registry_with, world  # noqa: F401  (the fixture)
from test_claim_unread_folder import PLACES, line, turn, walked

INSTALLED = ("you", "Close it, or take it into play")


def again(rid):
    return ("you", f"Walk it again: the place no longer holds what requisition {rid} wrote")


def walked_default(conn, definitions, db, type_id):
    """Claim a dossier the place already holds and walk it with no folder: the output lands on the first root."""
    registry = registry_with()
    env_id = conn.execute("SELECT id FROM environment WHERE type_id = ?", (type_id,)).fetchone()[0]
    uid = conn.execute("SELECT d.uid FROM dossier d JOIN ledger l ON l.dossier_id = d.id"
                       " WHERE l.environment_id = ? AND d.type_id != 'product' LIMIT 1", (env_id,)).fetchone()[0]
    claim = claims.new(conn, uid, env_id, definitions=definitions)
    _, rid = claims.walk(conn, definitions, registry, claim.id, {})
    run_queue(db, definitions, registry, only=[rid])
    return claim, registry, rid


def status_of(conn, folder):
    return repo.find_root(conn, fold(str(folder.resolve())))["status"]


def milestone(conn, claim):
    return claims.read_one(conn, claim.id).milestone


def rescan(w):
    run_rescan(db_path=w["db"], definitions=w["definitions"])


def requisition_ids(conn):
    return [r[0] for r in conn.execute("SELECT id FROM requisition ORDER BY id")]


@pytest.fixture
def outside(tmp_path):
    return tmp_path / "elsewhere" / "out"


@pytest.fixture
def place_library(request, scan, library, definitions, db_path):
    """The library for a place type: the fixture world for loose files, a scanned fixture for MO2 and Unreal."""
    def build(type_id):
        if type_id == "loose_files":
            w = request.getfixturevalue("world")
            return w["conn"], w["db"], w["definitions"]
        scan(request.getfixturevalue({"skyrim_se": "mo2_instance", "unreal_project": "unreal"}[type_id]))
        return library(), db_path, definitions
    return build


@pytest.mark.parametrize("fixture, type_id", PLACES)
def test_a_joined_folder_deleted_reads_converted(request, scan, library, definitions, db_path, outside, fixture,
                                                 type_id):
    scan(request.getfixturevalue(fixture))
    conn = library()
    claim, registry, rid = walked(conn, definitions, db_path, type_id, outside)
    shutil.rmtree(outside)
    run_rescan(db_path=db_path, definitions=definitions)
    assert status_of(conn, outside) == "offline"
    assert milestone(conn, claim) == "converted"
    assert turn(conn, definitions, registry, claim) == again(rid)


def test_loose_files_folder_deleted_then_restored(world, outside):
    conn, definitions = world["conn"], world["definitions"]
    claim, registry, rid = walked(conn, definitions, world["db"], "loose_files", outside)
    assert milestone(conn, claim) == "installed"
    requisitions = claims.read_one(conn, claim.id).meta["requisitions"]
    before = requisition_ids(conn)
    aside = outside.parent / "aside"
    shutil.move(str(outside), str(aside))
    rescan(world)
    assert status_of(conn, outside) == "offline"
    assert milestone(conn, claim) == "converted"
    assert turn(conn, definitions, registry, claim) == again(rid)
    shutil.move(str(aside), str(outside))
    rescan(world)
    assert status_of(conn, outside) == "online"
    assert milestone(conn, claim) == "installed"
    assert turn(conn, definitions, registry, claim) == INSTALLED
    reread = claims.read_one(conn, claim.id).meta["requisitions"]
    assert reread == requisitions and len(reread) == 1
    assert requisition_ids(conn) == before


def test_output_on_an_online_root_while_the_first_root_is_offline(world, outside):
    conn, definitions = world["conn"], world["definitions"]
    env_id = world["envs"]["loose_files"]["id"]
    claim, registry, rid = walked(conn, definitions, world["db"], "loose_files", outside)
    shutil.rmtree(repo.list_roots(conn, env_id)[0]["path"])
    rescan(world)
    assert repo.list_roots(conn, env_id)[0]["status"] == "offline"
    assert status_of(conn, outside) == "online"
    assert milestone(conn, claim) == "installed"
    assert turn(conn, definitions, registry, claim) == INSTALLED


def test_output_on_the_first_root_while_a_joined_root_is_offline(world, tmp_path):
    conn, definitions = world["conn"], world["definitions"]
    env_id = world["envs"]["loose_files"]["id"]
    claim, registry, rid = walked_default(conn, definitions, world["db"], "loose_files")
    second = tmp_path / "second"
    write(second / "box.glb", glb_bytes())
    register_root(conn, definitions, second, "loose_files", environment_id=env_id)
    rescan(world)
    assert status_of(conn, second) == "online"
    shutil.rmtree(second)
    rescan(world)
    assert status_of(conn, second) == "offline"
    assert repo.list_roots(conn, env_id)[0]["status"] == "online"
    assert milestone(conn, claim) == "installed"
    assert turn(conn, definitions, registry, claim) == INSTALLED


def test_daz_studio_content_folder_offline_and_back(world, outside):
    conn, definitions = world["conn"], world["definitions"]
    claim, registry, rid = walked(conn, definitions, world["db"], "daz_studio", outside)
    assert milestone(conn, claim) == "installed"
    requisitions = claims.read_one(conn, claim.id).meta["requisitions"]
    aside = outside.parent / "aside"
    shutil.move(str(outside), str(aside))
    rescan(world)
    assert status_of(conn, outside) == "offline"
    assert milestone(conn, claim) == "converted"
    assert turn(conn, definitions, registry, claim) == again(rid)
    shutil.move(str(aside), str(outside))
    rescan(world)
    assert status_of(conn, outside) == "online"
    assert milestone(conn, claim) == "installed"
    assert claims.read_one(conn, claim.id).meta["requisitions"] == requisitions and len(requisitions) == 1


@pytest.mark.parametrize("fixture, type_id", PLACES)
def test_an_unread_folder_still_on_disk_keeps_its_line(request, scan, library, definitions, db_path, outside, fixture,
                                                       type_id):
    scan(request.getfixturevalue(fixture))
    conn = library()
    claim, registry, rid = walked(conn, definitions, db_path, type_id, outside)
    run_rescan(db_path=db_path, definitions=definitions)
    place = conn.execute("SELECT name FROM environment WHERE type_id = ?", (type_id,)).fetchone()[0]
    assert status_of(conn, outside) == "online"
    assert milestone(conn, claim) == "converted"
    assert turn(conn, definitions, registry, claim) == ("you", line(rid, outside.resolve(), place))


@pytest.mark.parametrize("type_id", ["skyrim_se", "unreal_project", "loose_files"])
def test_an_offline_first_root_reads_converted(place_library, type_id):
    conn, db, definitions = place_library(type_id)
    claim, registry, rid = walked_default(conn, definitions, db, type_id)
    assert milestone(conn, claim) == "installed"
    env_id = conn.execute("SELECT id FROM environment WHERE type_id = ?", (type_id,)).fetchone()[0]
    shutil.rmtree(repo.list_roots(conn, env_id)[0]["path"])
    run_rescan(db_path=db, definitions=definitions)
    assert repo.list_roots(conn, env_id)[0]["status"] == "offline"
    assert milestone(conn, claim) == "converted"
    assert turn(conn, definitions, registry, claim) == again(rid)


def test_a_closed_claim_keeps_its_milestone(world, outside):
    conn, definitions = world["conn"], world["definitions"]
    claim, registry, rid = walked(conn, definitions, world["db"], "loose_files", outside)
    claims.close(conn, claim.id)
    shutil.rmtree(outside)
    rescan(world)
    assert status_of(conn, outside) == "offline"
    assert claims.read_one(conn, claim.id).milestone == "installed"
