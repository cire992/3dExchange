"""Claim paths, whose turn it is, walking, and the Converted and Installed milestones (R3b)."""

import datetime as dt
import sys
from pathlib import Path

import pytest

from builders import copy_fixture, png_bytes, write
from exchange import claims
from exchange.curation import Curator
from exchange.processes.registry import install, load_registry, trust
from exchange.requisitions import lifecycle
from exchange.requisitions.runner import run_queue

PROCESSES = Path(__file__).parent / "fixtures" / "processes"
TODAY = dt.date(2026, 10, 29)
GONE = "The source files are gone: rescan or relink"


@pytest.fixture
def world(scan, tmp_path, library, definitions, db_path):
    """A Daz library and loose files side by side; Barrel01's mesh has a texture linked onto it."""
    root = tmp_path / "scan" / "Assets"
    copy_fixture("fake_daz_library", root / "Daz Library")
    loose = copy_fixture("loose_files", root / "Loose")
    write(loose / "Downloads" / "barrel" / "Barrel01_N.png", png_bytes((64, 32)))
    scan(root)
    conn = library()
    envs = {r["type_id"]: r for r in conn.execute("SELECT * FROM environment")}
    loose_root = conn.execute("SELECT id FROM environment_root WHERE environment_id = ?",
                              (envs["loose_files"]["id"],)).fetchone()
    barrel = conn.execute("SELECT uid FROM dossier WHERE name = 'Barrel01'").fetchone()[0]
    Curator(conn, definitions).link_files(barrel, [(loose_root["id"], "loose/downloads/barrel/barrel01_n.png")])
    return {"conn": conn, "root": root, "loose": loose, "barrel": barrel, "envs": envs, "scan": scan,
            "ding": conn.execute("SELECT uid FROM dossier WHERE name = 'ding'").fetchone()[0],
            "definitions": definitions, "db": db_path}


def registry_with(*names, trusted=True):
    """The built-ins (but never the machine-dependent convert_mesh) and these fixture packages."""
    for name in names:
        package = install(PROCESSES / name)
        if trusted:
            trust(package)
    registry = load_registry()
    registry.packages.pop("convert_mesh", None)
    return registry


def claim_of(w, thing, place, **kwargs):
    return claims.new(w["conn"], thing, w["envs"][place]["id"], today=TODAY, **kwargs)


def path_of(w, registry, claim):
    return claims.find_path(w["conn"], w["definitions"], registry, claim, {})


def turn_of(w, registry, claim):
    return claims.whose_turn(w["conn"], w["definitions"], registry, claim, tools={})


def walk(w, registry, claim):
    return claims.walk(w["conn"], w["definitions"], registry, claim.id, {})


def reread(w, claim):
    return claims.read_one(w["conn"], claim.id)


def test_no_path_is_the_builds_turn(world):
    registry = registry_with()
    for thing in (world["ding"], world["barrel"]):
        claim = claim_of(world, thing, "daz_studio")
        path = path_of(world, registry, claim)
        assert path["status"] == "none" and path["route"] is None and path["processes"] == []
        assert path["process"] is None and world["envs"]["daz_studio"]["name"] in path["problem"]
        assert turn_of(world, registry, claim) == ("build", "No path yet: a process has to be built")
    assert "as prop" in path_of(world, registry, claim_of(world, world["barrel"], "daz_studio", role="prop"))["problem"]


def test_an_untrusted_process_is_not_ready_and_never_imported(world):
    registry = registry_with("to_daz", trusted=False)
    for name in [n for n in sys.modules if n.startswith("exchange_process_to_daz")]:
        del sys.modules[name]
    claim = claim_of(world, world["barrel"], "daz_studio")
    path = path_of(world, registry, claim)
    assert path["status"] == "not_ready" and path["route"] == "convert" and path["processes"] == ["to_daz"]
    assert path["process"] == "to_daz" and path["problem"] == "not trusted" and path["source_entry_id"]
    assert turn_of(world, registry, claim) == ("you", "Set up to_daz: trust it")
    assert not [n for n in sys.modules if n.startswith("exchange_process_to_daz")]


def test_an_unmet_prerequisite_says_how_to_fix_it(world):
    registry = registry_with("to_daz")
    claim = claim_of(world, world["barrel"], "daz_studio")
    path = path_of(world, registry, claim)
    assert path["status"] == "not_ready" and path["process"] == "to_daz"
    assert "exchange tools set exchange_test_missing_tool" in path["problem"]
    turn, line = turn_of(world, registry, claim)
    assert turn == "you" and line.startswith("Set up to_daz: fix ")
    assert "exchange tools set exchange_test_missing_tool" in line


def test_a_tool_that_is_set_makes_it_ready(world, tmp_path):
    registry = registry_with("to_daz")
    tool = write(tmp_path / "tool.exe", b"")
    claim = claim_of(world, world["barrel"], "daz_studio")
    path = claims.find_path(world["conn"], world["definitions"], registry, claim,
                            {"exchange_test_missing_tool": str(tool)})
    assert path["status"] == "ready" and path["route"] == "convert" and path["processes"] == ["to_daz"]
    assert path["process"] is None and path["problem"] is None


def test_the_role_filter_keeps_one_chain_and_drops_another(world):
    registry = registry_with("stamp_images", "copy_as_prop")
    plain = path_of(world, registry, claim_of(world, world["barrel"], "loose_files"))
    assert plain["status"] == "ready" and plain["route"] == "convert"
    for role in ("prop", "Prop"):
        path = path_of(world, registry, claim_of(world, world["barrel"], "loose_files", role=role))
        assert path["status"] == "ready" and path["route"] == "convert" and path["processes"] == ["copy_as_prop"]
    assert path_of(world, registry, claim_of(world, world["barrel"], "loose_files", role="figure"))["status"] == "none"


def test_a_copy_never_satisfies_a_role(world):
    registry = registry_with("copy_as_prop")
    plain = path_of(world, registry, claim_of(world, world["ding"], "loose_files"))
    assert plain["status"] == "ready" and plain["route"] == "copy"  # the place already holds it
    claim = claim_of(world, world["ding"], "loose_files", role="prop")
    path = path_of(world, registry, claim)
    assert path["status"] == "none" and path["processes"] == [] and "as prop" in path["problem"]
    assert turn_of(world, registry, claim) == ("build", "No path yet: a process has to be built")
    with pytest.raises(claims.ClaimError, match="No path yet"):
        walk(world, registry, claim)
    assert reread(world, claim).meta["requisitions"] == []


def test_a_role_no_process_has_is_not_a_path_elsewhere(world):
    registry = registry_with("to_daz")
    path = path_of(world, registry, claim_of(world, world["barrel"], "daz_studio", role="prop"))
    assert path["status"] == "none"


def marius(world):
    return world["conn"].execute("SELECT uid FROM dossier WHERE name LIKE 'Marius%' AND parent_id IS NULL").fetchone()[0]


def items_of(world, rid):
    return {row[0]: row[1] for row in world["conn"].execute(
        "SELECT d.name, i.include FROM requisition_item i JOIN dossier_effective d ON d.uid = i.dossier_uid"
        " WHERE i.requisition_id = ?", (rid,))}


def test_a_products_path_is_its_childrens(world):
    registry = registry_with("character_to_loose", "morph_to_loose")
    claim = claim_of(world, marius(world), "loose_files")
    path = path_of(world, registry, claim)
    assert path["status"] == "ready" and path["route"] == "children" and path["source_entry_id"] is None
    assert sorted(path["processes"]) == ["character_to_loose", "morph_to_loose"]
    assert turn_of(world, registry, claim) == ("you", "Walk it")
    _, rid = walk(world, registry, claim)
    assert items_of(world, rid) == {"Marius HD-8K": 1, "Marius Head": 1, "Marius Body": 1}


def test_a_role_on_a_product_keeps_the_children_that_grant_it(world):
    registry = registry_with("character_to_loose", "morph_to_loose")
    claim = claim_of(world, marius(world), "loose_files", role="Figure")
    path = path_of(world, registry, claim)
    assert path["route"] == "children" and path["processes"] == ["character_to_loose"]
    _, rid = walk(world, registry, claim)
    assert items_of(world, rid) == {"Marius HD-8K": 1, "Marius Head": 0, "Marius Body": 0}


def test_a_product_in_its_place_needs_a_process_for_a_role(world):
    registry = registry_with("character_to_loose")
    claim = claim_of(world, marius(world), "daz_studio", role="figure")
    assert path_of(world, registry, claim)["status"] == "none"
    assert turn_of(world, registry, claim)[0] == "build"


def test_a_product_nothing_can_move_is_the_builds_turn(world):
    registry = registry_with()
    path = path_of(world, registry, claim_of(world, marius(world), "loose_files"))
    assert path["status"] == "none" and path["processes"] == []


def test_a_childs_unready_process_is_named(world):
    registry = registry_with("character_to_loose", trusted=False)
    claim = claim_of(world, marius(world), "loose_files")
    path = path_of(world, registry, claim)
    assert path["status"] == "not_ready" and path["route"] == "children" and path["source_entry_id"] is None
    assert path["process"] == "character_to_loose" and path["processes"] == ["character_to_loose"]
    assert turn_of(world, registry, claim) == ("you", "Set up character_to_loose: trust it")


def test_a_product_walks_to_installed_through_its_children(world):
    registry = registry_with("character_to_loose")
    claim, rid = walk(world, registry, claim_of(world, marius(world), "loose_files", role="figure"))
    run_queue(world["db"], world["definitions"], registry, only=[rid])
    claim = reread(world, claim)
    assert claim.milestone == "installed"
    assert turn_of(world, registry, claim) == ("you", "Close it, or take it into play")


def test_a_hand_edited_claim_has_no_path_not_an_error(world):
    registry = registry_with()
    claim = claim_of(world, world["barrel"], "daz_studio")
    claim.meta["thing"] = "nosuch"
    assert path_of(world, registry, claim)["problem"] == "no dossier nosuch in the library"
    claim.meta["thing"], claim.meta["place"] = world["barrel"], "nosuch"
    path = path_of(world, registry, claim)
    assert path["status"] == "none" and path["problem"] == "no environment nosuch in the library"
    assert turn_of(world, registry, claim)[0] == "build"


def test_walking_queues_and_records_the_uid(world):
    registry = registry_with("stamp_images")
    claim = claim_of(world, world["barrel"], "loose_files")
    assert turn_of(world, registry, claim) == ("you", "Walk it")
    claim, rid = walk(world, registry, claim)
    row = world["conn"].execute("SELECT uid, state FROM requisition WHERE id = ?", (rid,)).fetchone()
    assert row["state"] == "queued" and claim.meta["requisitions"] == [row["uid"]]
    assert claims.read_one(world["conn"], claim.id).meta["requisitions"] == [row["uid"]]
    assert turn_of(world, registry, claim) == ("exchange", "")


def test_walking_is_refused_without_a_ready_path_or_on_exchanges_turn(world):
    registry = registry_with("stamp_images")
    count = lambda: world["conn"].execute("SELECT count(*) FROM requisition").fetchone()[0]  # noqa: E731
    nowhere = claim_of(world, world["barrel"], "daz_studio")
    with pytest.raises(claims.ClaimError, match="No path yet"):
        walk(world, registry, nowhere)
    claim = claim_of(world, world["barrel"], "loose_files")
    claim, rid = walk(world, registry, claim)
    with pytest.raises(claims.ClaimError, match=f"requisition {rid} is queued; it is Exchange's turn"):
        walk(world, registry, claim)
    lifecycle.hold(world["conn"], rid)
    assert turn_of(world, registry, reread(world, claim)) == ("you", f"Release requisition {rid}")
    with pytest.raises(claims.ClaimError, match=f"Release requisition {rid}"):
        walk(world, registry, claim)
    closed = claims.close(world["conn"], claim.id, today=TODAY)
    before = closed.path.read_bytes()
    with pytest.raises(claims.ClaimError, match="is closed"):
        walk(world, registry, claim)
    assert count() == 1 and closed.path.read_bytes() == before


def test_walking_an_untrusted_process_is_refused(world):
    registry = registry_with("to_daz", trusted=False)
    claim = claim_of(world, world["barrel"], "daz_studio")
    before = claim.path.read_bytes()
    with pytest.raises(claims.ClaimError, match="Set up to_daz: trust it"):
        walk(world, registry, claim)
    assert claim.path.read_bytes() == before
    assert world["conn"].execute("SELECT count(*) FROM requisition").fetchone()[0] == 0


def installed_claim(world, registry):
    claim, rid = walk(world, registry, claim_of(world, world["barrel"], "loose_files"))
    run_queue(world["db"], world["definitions"], registry, only=[rid])
    return reread(world, claim), rid


def test_a_run_ends_installed(world):
    registry = registry_with("stamp_images")
    claim, rid = installed_claim(world, registry)
    assert claim.milestone == "installed" and "milestone: installed" in claim.path.read_text(encoding="utf-8")
    assert turn_of(world, registry, claim) == ("you", "Close it, or take it into play")
    assert world["conn"].execute("SELECT state FROM requisition WHERE id = ?", (rid,)).fetchone()[0] == "fulfilled"


def test_converted_is_separate_from_installed(world):
    registry = registry_with("stamp_images")
    claim, rid = walk(world, registry, claim_of(world, world["barrel"], "loose_files"))
    assert claim.milestone == "acquired"
    run_queue(world["db"], world["definitions"], registry, only=[rid], rescan=False)
    claim = reread(world, claim)
    assert claim.milestone == "converted"
    assert turn_of(world, registry, claim) == (
        "you", f"Walk it again: the place no longer holds what requisition {rid} wrote")
    world["scan"](world["root"])
    claim = reread(world, claim)
    assert claim.milestone == "installed"
    lifecycle.remove(world["conn"], world["db"], world["definitions"], rid)
    claim = reread(world, claim)
    assert claim.milestone == "converted"
    assert turn_of(world, registry, claim)[1].startswith("Walk it again")
    claim, second = walk(world, registry, claim)
    assert len(claim.meta["requisitions"]) == 2 and second != rid


def test_a_failed_run_is_your_turn_with_the_reason(world):
    registry = registry_with("stamp_images")
    claim, rid = walk(world, registry, claim_of(world, world["barrel"], "loose_files"))
    (world["loose"] / "Downloads" / "barrel" / "Barrel01.fbx").unlink()
    run_queue(world["db"], world["definitions"], registry, only=[rid])
    turn, line = turn_of(world, registry, reread(world, claim))
    assert world["conn"].execute("SELECT state FROM requisition WHERE id = ?", (rid,)).fetchone()[0] == "failed"
    assert turn == "you" and "source file missing" in line


def test_colliding_outputs_need_attention(world):
    registry = registry_with("stamp_images")
    claim, _ = installed_claim(world, registry)
    claim, second = walk(world, registry, claim)
    run_queue(world["db"], world["definitions"], registry, only=[second])
    message = lifecycle.detail(world["conn"], second)["message"]
    turn, line = turn_of(world, registry, reread(world, claim))
    assert turn == "you" and "already exist" in line and line == message


def test_gone_source_and_removed_uids(world):
    registry = registry_with("stamp_images")
    claim, rid = walk(world, registry, claim_of(world, world["barrel"], "loose_files"))
    uid = claim.meta["requisitions"][0]
    claims.update(claim, {"requisitions": [uid, "no-such-uid"]})
    claim = reread(world, claim)
    assert [(u, r["id"] if r else None) for u, r in claims.resolve_requisitions(world["conn"], claim.meta)] == [
        (uid, rid), ("no-such-uid", None)]
    assert turn_of(world, registry, claim) == ("exchange", "")  # the latest is the real one
    claims.update(claim, {"requisitions": "not a list"})
    assert claims.resolve_requisitions(world["conn"], reread(world, claim).meta) == []


def test_gone_source(world):
    registry = registry_with("stamp_images")
    claim = claim_of(world, world["ding"], "loose_files")
    (world["loose"] / "sounds" / "ding.wav").unlink()
    world["scan"](world["root"])
    assert turn_of(world, registry, reread(world, claim)) == ("you", GONE)


def test_a_relative_folder_is_joined_onto_the_places_first_root(world):
    registry = registry_with("stamp_images")
    claim, rid = walk(world, registry, claim_of(world, world["barrel"], "loose_files", folder="Props/Barrels"))
    root = world["conn"].execute("SELECT path FROM environment_root WHERE environment_id = ? ORDER BY id",
                                 (world["envs"]["loose_files"]["id"],)).fetchone()[0]
    folder = lifecycle.detail(world["conn"], rid)["endpoint"]["folder"]
    assert Path(folder) == (Path(root) / "Props" / "Barrels").resolve()


def test_describe_adds_the_path_and_the_turn(world):
    registry = registry_with()
    claim = claim_of(world, world["barrel"], "daz_studio")
    data = claims.describe(world["conn"], world["definitions"], registry, claim, {})
    assert {k: v for k, v in data.items() if k not in ("path", "turn", "turn_line")} == claim.to_json()
    assert data["turn"] == "build" and data["path"]["status"] == "none"
    closed = claims.close(world["conn"], claim.id, today=TODAY)
    data = claims.describe(world["conn"], world["definitions"], registry, closed, {})
    assert (data["turn"], data["turn_line"]) == ("none", "") and data["path"]["status"] == "none"


def test_a_long_failure_message_is_one_line_with_a_pointer(world):
    registry = registry_with("stamp_images")
    claim, rid = walk(world, registry, claim_of(world, world["barrel"], "loose_files"))
    message = "Blender failed\nTraceback (most recent call last):\n  File x\nValueError: no"
    world["conn"].execute("UPDATE requisition SET state = 'failed', message = ? WHERE id = ?", (message, rid))
    assert turn_of(world, registry, reread(world, claim)) == (
        "you", f"Blender failed (exchange requisition show {rid})")
    assert claims.one_line("already exist", 3) == "already exist" and claims.one_line(None, 3) == ""
