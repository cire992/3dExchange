"""Ready means a process has a file it can read: `[input] extensions` in process manifests (R3d-3)."""

import datetime as dt
import json
import sys
from pathlib import Path

import pytest

from builders import copy_fixture, write
from exchange import claims
from exchange.cli import main
from exchange.curation import Curator
from exchange.errors import DefinitionError
from exchange.processes import manifest as manifests
from exchange.processes.manifest import parse_manifest
from exchange.processes.registry import install, load_registry, trust
from exchange.requisitions.plan import plan_requisition, routes

PROCESSES = Path(__file__).parent / "fixtures" / "processes"
TODAY = dt.date(2026, 10, 31)
MESH_EXTS = (".fbx", ".obj", ".glb", ".gltf", ".dae", ".stl", ".ply")
BASE = {"process": {"id": "x", "name": "X", "version": "1", "format_version": 1},
        "output": {"environment": "same"}, "step": [{"id": "a", "operation": "core.copy"}]}


@pytest.fixture
def world(scan, tmp_path, library, definitions, db_path):
    """A Daz library with a truck prop (a .duf) and loose files with a Thing.OBJ, a Crate.fbx beside
    the donuts, and a spare .obj, scanned together."""
    root = tmp_path / "scan" / "Assets"
    daz = copy_fixture("fake_daz_library", root / "Daz Library")
    write(daz / "Props" / "Truck" / "PickUp.duf", b'{"file_version": "0.6.0.0"}')
    loose = copy_fixture("loose_files", root / "Loose")
    write(loose / "Downloads" / "thing" / "Thing.OBJ", b"v 0 0 0\n")
    write(loose / "Downloads" / "props" / "Crate.fbx", b"fbx")
    write(loose / "Downloads" / "spare" / "Spare.obj", b"v 0 0 0\n")
    scan(root)
    conn = library()
    envs = {r["type_id"]: r for r in conn.execute("SELECT * FROM environment")}

    def uid(name):
        return conn.execute("SELECT uid FROM dossier_effective WHERE name = ?", (name,)).fetchone()[0]

    return {"conn": conn, "root": root, "loose": loose, "envs": envs, "scan": scan, "definitions": definitions,
            "db": db_path, "uid": uid, "barrel": uid("Barrel01"), "thing": uid("Thing"), "props": uid("props"),
            "prop": uid("PickUp"), "crate": uid("Crate")}


def registry_with(*names, trusted=True, mesh=False):
    """The built-ins and these fixture packages; Convert mesh only when asked (it needs Blender)."""
    for name in names:
        package = install(PROCESSES / name)
        if trusted:
            trust(package)
    registry = load_registry()
    if not mesh:
        registry.packages.pop("convert_mesh", None)
    return registry


def convert_routes(w, registry, thing, place, tools=None):
    found = routes(w["conn"], w["definitions"], registry, thing, w["envs"][place]["id"], {} if tools is None else tools)
    return [r for r in found if r["route"] == "convert"]


def entry_of(w, uid, env_type):
    row = w["conn"].execute(
        "SELECT e.id FROM dossier d JOIN ledger l ON l.dossier_id = d.id JOIN entry e ON e.ledger_id = l.id"
        " JOIN environment v ON v.id = l.environment_id WHERE d.uid = ? AND v.type_id = ?", (uid, env_type)).fetchone()
    return row[0]


def claim_of(w, thing, place, **kwargs):
    return claims.new(w["conn"], thing, w["envs"][place]["id"], today=TODAY, **kwargs)


def path_of(w, registry, claim, tools=None):
    return claims.find_path(w["conn"], w["definitions"], registry, claim, {} if tools is None else tools)


def turn_of(w, registry, claim, tools=None):
    return claims.whose_turn(w["conn"], w["definitions"], registry, claim, tools={} if tools is None else tools)


def imported(name):
    return [n for n in sys.modules if n.startswith(f"exchange_process_{name}")]


def a_tool(tmp_path):
    return {"blender": str(write(tmp_path / "blender.exe", b""))}


# The manifest ----------------------------------------------------------------------------------


def test_extensions_are_read_as_declared():
    assert manifests.FORMAT_VERSION == 1
    assert parse_manifest(BASE, "x").input_extensions == ()
    declared = {**BASE, "input": {"extensions": [".obj", ".FBX"]}}
    assert parse_manifest(declared, "x").input_extensions == (".obj", ".FBX")


def test_an_extension_needs_its_dot(tmp_path):
    with pytest.raises(DefinitionError, match="extensions"):
        parse_manifest({**BASE, "input": {"extensions": ["obj"]}}, "x")
    with pytest.raises(DefinitionError, match="must be a list"):
        parse_manifest({**BASE, "input": {"extensions": ".obj"}}, "x")
    folder = tmp_path / "processes" / "bad"
    folder.mkdir(parents=True)
    (folder / "process.toml").write_text(
        '[process]\nid = "bad"\nname = "Bad"\nversion = "1"\nformat_version = 1\n'
        '[input]\nextensions = ["obj"]\n[output]\nenvironment = "same"\n'
        '[[step]]\nid = "a"\noperation = "core.copy"\n', encoding="utf-8")
    registry = load_registry(extra_dirs=(folder.parent,), include_user=False)
    assert any("extensions" in problem for problem in registry.problems) and "bad" not in registry.packages


def test_the_format_comment_documents_the_key():
    assert "extensions = [" in manifests.__doc__


def test_convert_mesh_declares_what_it_reads():
    from exchange.processes.builtin.convert_mesh.operations import blender_ops

    declared = load_registry(include_user=False).get("convert_mesh").manifest.input_extensions
    assert declared == MESH_EXTS == blender_ops.MESH_EXTS


# The check -------------------------------------------------------------------------------------


def test_a_process_is_offered_only_from_an_entry_with_a_file_it_reads(world):
    registry = registry_with("read_obj")
    assert [r["processes"] for r in convert_routes(world, registry, world["thing"], "loose_files")] == [["read_obj"]]
    assert convert_routes(world, registry, world["barrel"], "loose_files") == []


def test_extensions_match_in_both_cases(world):
    registry = registry_with("read_obj_caps")
    # Thing.OBJ is stored as .obj; the manifest says .OBJ
    assert [r["processes"] for r in convert_routes(world, registry, world["thing"], "loose_files")] == [
        ["read_obj_caps"]]
    stored = world["conn"].execute("SELECT ext FROM file WHERE rel_key LIKE '%thing.obj'").fetchone()[0]
    assert stored == ".obj"


def test_a_file_of_any_role_counts_and_a_gone_file_does_not(world):
    registry = registry_with("read_obj")
    assert convert_routes(world, registry, world["barrel"], "loose_files") == []
    conn = world["conn"]
    root_id, rel_key = conn.execute("SELECT root_id, rel_key FROM file WHERE rel_key LIKE '%spare.obj'").fetchone()
    Curator(conn, world["definitions"]).link_files(world["barrel"], [(root_id, rel_key)])
    assert [r["processes"] for r in convert_routes(world, registry, world["barrel"], "loose_files")] == [["read_obj"]]
    (world["loose"] / "Downloads" / "spare" / "Spare.obj").unlink()
    world["scan"](world["root"])
    assert convert_routes(world, registry, world["barrel"], "loose_files") == []


def test_the_check_is_per_entry(world):
    registry = registry_with("mesh_to_loose")  # takes any environment, so both entries could be sources
    Curator(world["conn"], world["definitions"]).merge(world["prop"], world["thing"])
    assert entry_of(world, world["thing"], "daz_studio") != entry_of(world, world["thing"], "loose_files")
    found = convert_routes(world, registry, world["thing"], "loose_files")
    assert found and {r["source_entry_id"] for r in found} == {entry_of(world, world["thing"], "loose_files")}


def test_a_process_with_no_extensions_is_unchanged(world):
    registry = registry_with("stamp_images")
    assert [r["processes"] for r in convert_routes(world, registry, world["barrel"], "loose_files")] == [
        ["stamp_images"]]
    claim = claim_of(world, world["barrel"], "loose_files")
    path = path_of(world, registry, claim)
    assert path["status"] == "ready" and path["route"] == "convert"


def test_only_the_first_process_of_a_chain_is_checked(world):
    registry = registry_with("fbx_to_stage", "stage_to_loose")  # the second reads .zzz, which no source holds
    found = convert_routes(world, registry, world["barrel"], "loose_files")
    assert [r["processes"] for r in found] == [["fbx_to_stage", "stage_to_loose"]]


def test_a_longer_chain_is_not_hidden_by_a_direct_process_that_cannot_read(world):
    registry = registry_with("read_obj", "fbx_to_stage", "stage_to_loose")
    found = convert_routes(world, registry, world["barrel"], "loose_files")
    assert [r["processes"] for r in found] == [["fbx_to_stage", "stage_to_loose"]]
    path = path_of(world, registry, claim_of(world, world["barrel"], "loose_files"))
    assert path["status"] == "ready" and path["processes"] == ["fbx_to_stage", "stage_to_loose"]
    # on a source that can be read directly, the direct process is the shortest chain again
    assert [r["processes"] for r in convert_routes(world, registry, world["thing"], "loose_files")] == [["read_obj"]]


def test_a_named_chain_that_cannot_read_is_refused_in_the_plan(world):
    registry = registry_with("read_obj")
    plan = plan_requisition(world["conn"], world["definitions"], registry, world["barrel"],
                            world["envs"]["loose_files"]["id"], processes=["read_obj"], tools={})
    item = plan.items[0]
    assert item.route == "none" and not item.include and item.problems == ["read_obj does not take it there"]


def test_a_copy_is_not_checked(world, tmp_path):
    registry = registry_with(mesh=True)
    tools = a_tool(tmp_path)
    found = routes(world["conn"], world["definitions"], registry, world["prop"], world["envs"]["daz_studio"]["id"],
                   tools)
    assert [r["route"] for r in found] == ["copy"]
    assert not [r for r in found if r["processes"] == ["convert_mesh"]]


# Claims ----------------------------------------------------------------------------------------


def test_a_prop_that_holds_no_mesh_has_no_path(world):
    registry = registry_with("mesh_to_loose")
    claim = claim_of(world, world["prop"], "loose_files")
    path = path_of(world, registry, claim)
    assert path["status"] == "none" and path["processes"] == [] and path["process"] is None
    assert turn_of(world, registry, claim) == ("build", "No path yet: a process has to be built")
    with pytest.raises(claims.ClaimError, match="No path yet"):
        claims.walk(world["conn"], world["definitions"], registry, claim.id, {})
    assert world["conn"].execute("SELECT count(*) FROM requisition").fetchone()[0] == 0
    assert claims.read_one(world["conn"], claim.id).meta["requisitions"] == []


def test_a_claim_on_a_mesh_file_is_unchanged(world, tmp_path):
    registry = registry_with(mesh=True)
    tools = a_tool(tmp_path)
    claim = claim_of(world, world["barrel"], "loose_files")
    path = path_of(world, registry, claim, tools)
    assert path["status"] == "ready" and path["route"] == "convert" and path["processes"] == ["convert_mesh"]
    assert turn_of(world, registry, claim, tools) == ("you", "Walk it")


def test_the_look_past_readiness_never_names_a_process_that_cannot_read(world):
    registry = registry_with("obj_to_daz", trusted=False)
    for name in [n for n in sys.modules if n.startswith("exchange_process_obj_to_daz")]:
        del sys.modules[name]
    lacking = claim_of(world, world["barrel"], "daz_studio")
    path = path_of(world, registry, lacking)
    assert path["status"] == "none" and path["process"] is None and path["processes"] == []
    assert turn_of(world, registry, lacking) == ("build", "No path yet: a process has to be built")
    readable = path_of(world, registry, claim_of(world, world["thing"], "daz_studio"))
    assert readable["status"] == "not_ready" and readable["process"] == "obj_to_daz"
    assert readable["problem"] == "not trusted"
    assert not imported("obj_to_daz")


def test_an_unmet_prerequisite_is_not_named_when_the_source_cannot_be_read(world):
    registry = registry_with("obj_to_daz_tool")
    assert path_of(world, registry, claim_of(world, world["barrel"], "daz_studio"))["status"] == "none"
    path = path_of(world, registry, claim_of(world, world["thing"], "daz_studio"))
    assert path["status"] == "not_ready" and path["process"] == "obj_to_daz_tool"


def items_of(w, rid):
    return {row[0]: row[1] for row in w["conn"].execute(
        "SELECT d.name, i.include FROM requisition_item i JOIN dossier_effective d ON d.uid = i.dossier_uid"
        " WHERE i.requisition_id = ?", (rid,))}


def test_a_product_leaves_out_the_children_that_cannot_be_read(world):
    registry = registry_with("glb_to_daz")
    claim = claim_of(world, world["props"], "daz_studio")
    path = path_of(world, registry, claim)
    assert path["status"] == "ready" and path["route"] == "children" and path["processes"] == ["glb_to_daz"]
    plan = plan_requisition(world["conn"], world["definitions"], registry, world["props"],
                            world["envs"]["daz_studio"]["id"], tools={})
    by_name = {i.name: i for i in plan.items}
    assert by_name["Donut01_Blue"].include and by_name["Donut01_Pink"].include
    assert by_name["Crate"].route == "none" and not by_name["Crate"].include
    _, rid = claims.walk(world["conn"], world["definitions"], registry, claim.id, {})
    assert items_of(world, rid) == {"Donut01_Blue": 1, "Donut01_Pink": 1, "Crate": 0}


def test_an_unready_childs_process_is_named_when_that_child_can_be_read(world):
    registry = registry_with("glb_to_daz", trusted=False)
    path = path_of(world, registry, claim_of(world, world["props"], "daz_studio"))
    assert path["status"] == "not_ready" and path["route"] == "children" and path["process"] == "glb_to_daz"


def test_an_unready_process_no_child_can_read_is_not_named(world):
    registry = registry_with("obj_to_daz", trusted=False)  # no donut or crate is an .obj
    path = path_of(world, registry, claim_of(world, world["props"], "daz_studio"))
    assert path["status"] == "none" and path["process"] is None


# The command line ------------------------------------------------------------------------------


def test_processes_show_prints_what_a_process_reads(world, capsys):
    db = str(world["db"])
    assert main(["processes", "show", "convert_mesh", "--db", db]) == 0
    assert "  takes mesh (Files) reading .fbx, .obj, .glb, .gltf, .dae, .stl, .ply → same mesh" in capsys.readouterr().out
    assert main(["processes", "show", "convert_mesh", "--db", db, "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["input"]["extensions"] == list(MESH_EXTS)
    assert main(["processes", "show", "copy_entry", "--db", db, "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["input"]["extensions"] == []
    assert main(["processes", "show", "copy_entry", "--db", db]) == 0
    takes = next(line for line in capsys.readouterr().out.splitlines() if "takes" in line)
    assert "reading" not in takes
