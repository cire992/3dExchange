"""A claim walked to a folder its place's layer doesn't read stops at Converted and says so (R3d-4)."""

import shutil

import pytest

from exchange import claims
from exchange.requisitions.runner import run_queue
from exchange.scanner.scan import run_rescan
from test_claim_paths import registry_with, world  # noqa: F401  (the fixture)


def walked(conn, definitions, db, type_id, folder):
    """Claim a dossier the place already holds, walk it (a copy) into ``folder`` and run it."""
    registry = registry_with()
    env_id = conn.execute("SELECT id FROM environment WHERE type_id = ?", (type_id,)).fetchone()[0]
    uid = conn.execute("SELECT d.uid FROM dossier d JOIN ledger l ON l.dossier_id = d.id"
                       " WHERE l.environment_id = ? AND d.type_id != 'product' LIMIT 1", (env_id,)).fetchone()[0]
    claim = claims.new(conn, uid, env_id, folder=str(folder), definitions=definitions)
    _, rid = claims.walk(conn, definitions, registry, claim.id, {})
    run_queue(db, definitions, registry, only=[rid])
    return claim, registry, rid


def turn(conn, definitions, registry, claim):
    return claims.whose_turn(conn, definitions, registry, claims.read_one(conn, claim.id), tools={})


def line(rid, folder, place):
    return (f"Requisition {rid} wrote to {folder}, but {place} doesn't read that folder:"
            " choose a folder it reads, then walk it again")


PLACES = [("mo2_instance", "skyrim_se"), ("unreal", "unreal_project")]


@pytest.mark.parametrize("fixture, type_id", PLACES)
def test_an_absolute_folder_outside_the_place(request, scan, library, definitions, db_path, tmp_path, fixture, type_id):
    scan(request.getfixturevalue(fixture))
    conn = library()
    outside = tmp_path / "elsewhere" / "out"
    claim, registry, rid = walked(conn, definitions, db_path, type_id, outside)
    assert any(outside.iterdir())
    place = conn.execute("SELECT name FROM environment WHERE type_id = ?", (type_id,)).fetchone()[0]
    assert claims.read_one(conn, claim.id).milestone == "converted"
    assert turn(conn, definitions, registry, claim) == ("you", line(rid, outside.resolve(), place))


@pytest.mark.parametrize("fixture, type_id, folder", [("mo2_instance", "skyrim_se", "Extras"),
                                                      ("unreal", "unreal_project", "Saved")])
def test_a_relative_folder_the_layer_does_not_read(request, scan, library, definitions, db_path, fixture, type_id,
                                                   folder):
    root = request.getfixturevalue(fixture)
    scan(root)
    conn = library()
    claim, registry, rid = walked(conn, definitions, db_path, type_id, folder)
    place = conn.execute("SELECT name FROM environment WHERE type_id = ?", (type_id,)).fetchone()[0]
    assert (root / folder).is_dir() and claims.read_one(conn, claim.id).milestone == "converted"
    assert turn(conn, definitions, registry, claim) == ("you", line(rid, (root / folder).resolve(), place))


@pytest.mark.parametrize("fixture, type_id", PLACES)
def test_the_output_deleted_and_rescanned_keeps_the_old_line(request, scan, library, definitions, db_path, tmp_path,
                                                             fixture, type_id):
    scan(request.getfixturevalue(fixture))
    conn = library()
    outside = tmp_path / "elsewhere" / "out"
    claim, registry, rid = walked(conn, definitions, db_path, type_id, outside)
    shutil.rmtree(outside)
    outside.mkdir()
    run_rescan(db_path=db_path, definitions=definitions)
    assert turn(conn, definitions, registry, claim) == (
        "you", f"Walk it again: the place no longer holds what requisition {rid} wrote")


@pytest.mark.parametrize("type_id", ["loose_files", "daz_studio"])
def test_loose_files_and_daz_studio_walked_outside_still_install(world, tmp_path, type_id):
    conn, definitions = world["conn"], world["definitions"]
    outside = tmp_path / "elsewhere" / "out"
    claim, registry, rid = walked(conn, definitions, world["db"], type_id, outside)
    assert claims.read_one(conn, claim.id).milestone == "installed"
    assert turn(conn, definitions, registry, claim) == ("you", "Close it, or take it into play")
