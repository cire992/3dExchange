"""The G8 path, shape (R6b): `daz_character_to_g8f` turns a Genesis 9 character into a Genesis 8
Female morph. Daz Studio and Blender are stood in for here: each stand-in writes what the real
script writes, so the operations, the rewrite and the walk to Installed are checked without the apps.
The scripts themselves run only in the apps; R6b and R6c ran them for real (see docs/PROGRESS.md)."""

import datetime as dt
import json
import zipfile
from pathlib import Path

import pytest

from builders import write
from exchange import claims
from exchange.paths import data_dir
from exchange.processes.operations import Artifact, Context, OperationError
from exchange.processes.registry import check_prerequisites, load_registry, validate
from exchange.requisitions import runner
from exchange.requisitions.runner import run_queue

TODAY = dt.date(2026, 11, 2)
PROCESS = "daz_character_to_g8f"
COPY_FIGURE = "/People/Genesis 8 Female/Genesis 8 Basic Female Exchange.duf"
COPY = "/data/Exchange/Genesis%208/Female/"


def built_morph(name):
    """A morph as Daz saves one on the Exchange G8F copy, with the random id suffix it adds."""
    return json.dumps({
        "file_version": "0.6.0.0",
        "asset_info": {"id": f"{COPY}Morphs/Exchange/{name}/{name}.dsf", "type": "modifier"},
        "modifier_library": [{"id": f"{name}-0xab0df0d", "name": name, "parent": f"{COPY}Genesis8Female.dsf#geometry",
                              "formulas": [{"output": f"hip:{COPY}Genesis8Female.dsf#hip?center_point/y",
                                            "operations": [{"op": "push", "url": f"Genesis8Female:#{name}-0xab0df0d?value"}]}]}],
    }, indent="\t")


class StandIn:
    """Daz Studio or Blender running one of the package's scripts: it writes what the script would."""

    def __init__(self, app, calls, saves=1):
        self.app, self.calls, self.saves = app, calls, saves

    def run(self, script, args, **kwargs):
        self.calls.append((self.app, Path(script).name, args))
        name = Path(script).name
        if name == "export_shape.dsa":
            write(Path(args["shape"]), b"v 0 1 0\nv 1 1 0\nv 0 2 0\nf 1 2 3\n")
            write(Path(args["base"]), b"v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n")
            return {"figure": "Marius HD-8K", "shape": {"vertices": 3, "facets": 1}, "base": {"vertices": 3, "facets": 1},
                    "log": ["loaded Marius HD-8K in 24 s", "resolution set to Base (was High Resolution)"]}
        if name == "convert_shape.py":
            assert (Path(args["addon"]) / "Daz_Generations" / "__init__.py").is_file()
            write(Path(args["out"]), b"v 0 1.5 0\nv 1 1.5 0\nv 0 2.5 0\nf 1 2 3\n")
            return {"vertices": 3, "seconds": 3.0, "rescale": "Full"}
        if name == "build_morph.dsa":
            for i in range(self.saves):
                folder = Path(args["library"]) / "data" / "Exchange" / "Genesis 8" / "Female" / "Morphs" / "Exchange"
                write(folder / args["product"] / f"{args['morph']}{i or ''}.dsf", built_morph(args["morph"]).encode())
            return {"morph": args["morph"], "deltas": 3, "frozen": 2, "largest_difference": 0.00005,
                    "log": ["Morph Loader: 3 vertices moved", "ERC Freeze: 2 joint values follow the morph"]}
        raise AssertionError(f"unexpected script {name}")


def addon_archive(path, *, complete=True):
    with zipfile.ZipFile(write(path, b""), "w") as z:
        z.writestr("Daz_Generations/__init__.py", "")
        if complete:
            z.writestr("Daz_Generations/conversionDB.db", "")
    return path


@pytest.fixture
def tools(tmp_path):
    return {"daz_studio": str(write(tmp_path / "apps" / "DAZStudio.exe", b"")),
            "blender": str(write(tmp_path / "apps" / "blender.exe", b"")),
            "daz_generations": str(addon_archive(tmp_path / "tools" / "Daz_Generations 1.1.0.zip"))}


@pytest.fixture
def stand_ins(monkeypatch):
    calls = []
    monkeypatch.setattr(runner, "bridges_for", lambda package, tools, workdir, log: lambda app: StandIn(app, calls))
    return calls


@pytest.fixture
def world(scan, daz_library, library, definitions, daz_settings, tmp_path):
    """The fake Daz library (Marius HD-8K, for Genesis 9), a character saved for Genesis 8 Female, and
    the Exchange G8F copy in a content directory of Daz Studio's."""
    write(daz_library / "People" / "Genesis 8 Female" / "Characters" / "Anna.duf", json.dumps(
        {"file_version": "0.6.0.0", "asset_info": {"id": "/Anna.duf", "type": "character"}}).encode())
    scan(daz_library)
    figures = tmp_path / "Daz" / "Exchange figures"
    for rel in ("People/Genesis 8 Female/Genesis 8 Basic Female Exchange.duf",
                "data/Exchange/Genesis 8/Female/Genesis8Female.dsf"):
        write(figures.joinpath(*rel.split("/")), b"{}")
    daz_settings([daz_library, figures])
    conn = library()
    uid = lambda name: conn.execute("SELECT uid FROM dossier_effective WHERE name = ?", (name,)).fetchone()[0]  # noqa: E731
    env = conn.execute("SELECT * FROM environment WHERE type_id = 'daz_studio'").fetchone()
    return {"conn": conn, "definitions": definitions, "uid": uid, "env": env, "figures": figures,
            "library": daz_library, "registry": load_registry(include_user=False)}


def claim_of(w, name, folder=None):
    return claims.new(w["conn"], w["uid"](name), w["env"]["id"], role="g8f_character", folder=folder, today=TODAY,
                      definitions=w["definitions"])


# The package ---------------------------------------------------------------------------------------


def test_the_package_declares_what_it_takes_and_needs():
    package = load_registry(include_user=False).get(PROCESS)
    m = package.manifest
    assert package.builtin and package.trusted and validate(package) == []
    assert (m.input_types, m.input_variants, m.input_environments, m.input_extensions) == (
        ("daz_character_preset",), ("genesis_9",), ("daz_studio",), (".duf",))
    assert (m.output_environment, m.output_folder, m.roles) == ("daz_studio", "", ("g8f_character",))
    assert [s.id for s in m.steps] == ["export", "convert", "build", "rewrite"]
    assert {p.id: p.kind for p in m.prerequisites} == {
        "daz_studio": "tool", "blender": "tool", "daz_generations": "tool", "exchange_g8f": "content"}
    rewrite = m.steps[-1].params
    assert rewrite == {"source": COPY, "target": "/data/Daz%203D/Genesis%208/Female/"}


def test_the_scripts_ship_with_it():
    folder = load_registry(include_user=False).get(PROCESS).path / "scripts"
    assert {p.name for p in folder.iterdir()} >= {"export_shape.dsa", "convert_shape.py", "build_morph.dsa"}


def test_a_g9_character_has_a_path_once_set_up(world, tools):
    claim = claim_of(world, "Marius HD-8K")
    path = claims.find_path(world["conn"], world["definitions"], world["registry"], claim, tools)
    assert (path["status"], path["processes"]) == ("ready", [PROCESS])
    unset = {k: v for k, v in tools.items() if k != "daz_generations"}
    path = claims.find_path(world["conn"], world["definitions"], world["registry"], claim, unset)
    assert path["status"] == "not_ready" and path["process"] == PROCESS
    assert path["problem"].startswith("Daz Generations: not found; set it with: exchange tools set daz_generations")


def test_the_figure_copy_must_be_in_a_content_directory(world, tools, daz_settings):
    daz_settings([world["library"]])
    path = claims.find_path(world["conn"], world["definitions"], world["registry"], claim_of(world, "Marius HD-8K"), tools)
    assert path["status"] == "not_ready" and path["problem"].startswith(
        "Exchange G8F: missing People/Genesis 8 Female/Genesis 8 Basic Female Exchange.duf")


def test_a_g8_character_has_none(world, tools):
    path = claims.find_path(world["conn"], world["definitions"], world["registry"], claim_of(world, "Anna"), tools)
    assert path["status"] == "none"


# Walking it ------------------------------------------------------------------------------------------


def test_a_claim_walks_to_installed(world, tools, stand_ins, db_path, tmp_path):
    endpoint = tmp_path / "Daz" / "Exchange Conversions"
    claim = claim_of(world, "Marius HD-8K", folder=str(endpoint))
    _, rid = claims.walk(world["conn"], world["definitions"], world["registry"], claim.id, tools)
    run_queue(db_path, world["definitions"], world["registry"], only=[rid], tools=tools)

    state = world["conn"].execute("SELECT state FROM requisition WHERE id = ?", (rid,)).fetchone()[0]
    assert state == "fulfilled"
    morph = endpoint / "data" / "Daz 3D" / "Genesis 8" / "Female" / "Morphs" / "Exchange" / "Marius HD-8K" / "MariusHD8K.dsf"
    text = morph.read_text(encoding="utf-8")
    assert "/data/Exchange/" not in text and "0xab0df0d" not in text
    assert '"id": "MariusHD8K"' in text and "Genesis8Female:#MariusHD8K?value" in text
    assert claims.read_one(world["conn"], claim.id).meta["milestone"] == "installed"

    (export_app, export_script, export), (_, _, convert), (build_app, _, build) = stand_ins
    assert (export_app, export_script) == ("daz_studio", "export_shape.dsa")
    assert export["source"].endswith("People/Genesis 9/Characters/Marius/Marius HD-8K.duf")
    assert export["target"] == COPY_FIGURE
    assert convert["method"] == "v3" and convert["shape"].endswith("character.obj")
    assert build_app == "daz_studio" and build["figure"] == COPY_FIGURE
    assert (build["morph"], build["label"], build["product"], build["tolerance"]) == (
        "MariusHD8K", "Marius HD-8K", "Marius HD-8K", 0.01)
    assert not (world["library"] / "data" / "DAZ 3D" / "Genesis 8").exists()  # nothing beside the source


def test_the_options_reach_the_apps(world, tools, stand_ins, db_path, tmp_path):
    claim = claim_of(world, "Marius HD-8K", folder=str(tmp_path / "Daz" / "Out"))
    _, rid = claims.walk(world["conn"], world["definitions"], world["registry"], claim.id, tools,
                         params={f"{PROCESS}.method": "v1", f"{PROCESS}.tolerance": 0.05})
    run_queue(db_path, world["definitions"], world["registry"], only=[rid], tools=tools)
    assert stand_ins[1][2]["method"] == "v1" and stand_ins[2][2]["tolerance"] == 0.05


# The operations --------------------------------------------------------------------------------------


def ops():
    return {name.rsplit('.', 1)[-1]: spec for name, spec in load_registry(include_user=False).get(PROCESS).operations().items()}


def context(tmp_path, calls, tools=None, saves=1, name="Luanne HD"):
    get_tool = (lambda t: Path(tools[t])) if tools else None
    return Context(tmp_path / "work", {"name": name}, lambda m: None,
                   bridges=lambda app: StandIn(app, calls, saves), tools=get_tool)


@pytest.mark.parametrize("files, problem", [(["Luanne.png"], "found none"), (["A.duf", "B.duf"], "found A.duf, B.duf")])
def test_export_needs_one_character_file(tmp_path, files, problem):
    for rel in files:
        write(tmp_path / "in" / rel, b"{}")
    with pytest.raises(OperationError, match=f"expected one character file \\(.duf\\), {problem}"):
        ops()["export_shape"].func(context(tmp_path, []), Artifact("Files", tmp_path / "in", files))


def test_the_addon_is_extracted_once_and_never_installed(tmp_path, tools):
    calls = []
    shapes = ops()["export_shape"].func(context(tmp_path, calls), Artifact("Files", write(
        tmp_path / "in" / "Luanne.duf", b"{}").parent, ["Luanne.duf"]), target_figure=COPY_FIGURE)
    convert = ops()["convert_shape"].func
    convert(context(tmp_path, calls, tools), shapes)
    folder = data_dir() / "tools" / "daz_generations" / "Daz_Generations 1.1.0"
    assert Path(calls[-1][2]["addon"]) == folder and (folder / "Daz_Generations" / "conversionDB.db").is_file()
    (folder / "Daz_Generations" / "marker").write_text("kept", encoding="utf-8")
    convert(context(tmp_path, calls, tools), shapes)
    assert (folder / "Daz_Generations" / "marker").is_file()  # not extracted again
    assert zipfile.ZipFile(tools["daz_generations"]).namelist() == [
        "Daz_Generations/__init__.py", "Daz_Generations/conversionDB.db"]  # the archive is only read


def test_another_archive_is_refused(tmp_path, tools):
    tools = {**tools, "daz_generations": str(addon_archive(tmp_path / "tools" / "Other.zip", complete=False))}
    shapes = Artifact("Files", tmp_path, ["character.obj", "target.obj"])
    with pytest.raises(OperationError, match="Other.zip is not the Daz Generations add-on"):
        ops()["convert_shape"].func(context(tmp_path, [], tools), shapes)


def test_the_build_keeps_one_morph_with_a_stable_id(tmp_path):
    shape = Artifact("Files", tmp_path / "shape", ["shape.obj"])
    built = ops()["build_morph"].func(context(tmp_path, []), shape, figure=COPY_FIGURE)
    assert built.files == ["data/Exchange/Genesis 8/Female/Morphs/Exchange/Luanne HD/LuanneHD.dsf"]
    text = built.paths()[0].read_text(encoding="utf-8")
    assert '"id": "LuanneHD"' in text and "#LuanneHD?value" in text and "0x" not in text
    with pytest.raises(OperationError, match="saved 2 morph files, not one"):
        ops()["build_morph"].func(context(tmp_path / "two", [], saves=2), shape, figure=COPY_FIGURE)


def test_names_come_from_the_characters():
    from exchange.processes.builtin.daz_character_to_g8f.operations import g8f_ops

    assert g8f_ops.morph_name("ES3D Luanne") == "ES3DLuanne"
    assert g8f_ops.morph_name("9 Lives") == "Exchange9Lives"
    assert g8f_ops.morph_name("¡¿") == "Exchange"
    assert g8f_ops.folder_name('Mia: "HD"') == "Mia   HD"
