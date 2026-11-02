"""What R6's G8 path needs from the engine: a process that takes only one figure generation
(`[input] variants`), a file it needs in Daz Studio's content directories (`content`
prerequisites), and pointing Daz files at another figure (`core.rewrite_daz_paths`)."""

import datetime as dt
import gzip
import json

import pytest

from builders import write
from exchange import claims
from exchange.errors import DefinitionError
from exchange.processes.core_ops import rewrite_daz_paths
from exchange.processes.manifest import parse_manifest
from exchange.processes.operations import Artifact, Context, OperationError
from exchange.processes.registry import check_prerequisites, install, load_registry, ready, trust, validate
from exchange.requisitions.plan import routes

TODAY = dt.date(2026, 11, 2)
EXCHANGE_G8F = "People/Genesis 8 Female/Genesis 8 Basic Female Exchange.duf"
COPY = "/data/Exchange/Genesis%208/Female/"
REGULAR = "/data/Daz%203D/Genesis%208/Female/"
BASE = {"process": {"id": "x", "name": "X", "version": "1", "format_version": 1},
        "output": {"environment": "same"}, "step": [{"id": "a", "operation": "core.copy"}]}

MANIFEST = """[process]
id = "{id}"
name = "G9 character to G8F"
version = "1"
format_version = 1

[input]
dossier_types = ["daz_character_preset"]
environments = ["daz_studio"]
{variants}

[output]
environment = "daz_studio"
roles = ["g8f_character"]
{prerequisite}
[[step]]
id = "copy"
operation = "core.copy"
"""
CONTENT = f"""
[[prerequisite]]
id = "exchange_g8f"
label = "Exchange G8F"
kind = "content"
tool = "daz_studio"
paths = ["{EXCHANGE_G8F}"]
hint = "see PROCESS_FILES.md"
"""


def package(tmp_path, process_id, *, variants='variants = ["genesis_9"]', prerequisite=""):
    folder = tmp_path / "packages" / process_id
    write(folder / "process.toml", MANIFEST.format(id=process_id, variants=variants,
                                                   prerequisite=prerequisite).encode())
    trust(install(folder))
    registry = load_registry()
    registry.packages.pop("daz_character_to_g8f")  # the built-in G8 path takes the same characters
    return registry


@pytest.fixture
def world(scan, daz_library, library, definitions):
    """The fake Daz library: Marius HD-8K for Genesis 9 (from its manifest), plus a character saved
    for Genesis 8 Female and one saved for Genesis 9."""
    write(daz_library / "People" / "Genesis 8 Female" / "Characters" / "Anna.duf", character("Anna"))
    write(daz_library / "People" / "Genesis 9" / "Characters" / "Bea.duf", character("Bea"))
    scan(daz_library)
    conn = library()

    def uid(name):
        return conn.execute("SELECT uid FROM dossier_effective WHERE name = ?", (name,)).fetchone()[0]

    env = conn.execute("SELECT * FROM environment WHERE type_id = 'daz_studio'").fetchone()
    return {"conn": conn, "definitions": definitions, "uid": uid, "env": env, "library": daz_library}


def character(name):
    return json.dumps({"file_version": "0.6.0.0", "asset_info": {"id": f"/{name}.duf", "type": "character"}}).encode()


def convert_routes(w, registry, uid):
    return [r for r in routes(w["conn"], w["definitions"], registry, uid, w["env"]["id"], {}) if r["route"] == "convert"]


def path_of(w, registry, uid):
    claim = claims.new(w["conn"], uid, w["env"]["id"], role="g8f_character", today=TODAY)
    return claims.find_path(w["conn"], w["definitions"], registry, claim, {})


# [input] variants ------------------------------------------------------------------------------


def test_variants_are_read_and_default_to_any():
    assert parse_manifest(BASE, "x").input_variants == ()
    declared = {**BASE, "input": {"variants": ["genesis_9"]}}
    assert parse_manifest(declared, "x").input_variants == ("genesis_9",)
    with pytest.raises(DefinitionError, match="must be a list"):
        parse_manifest({**BASE, "input": {"variants": "genesis_9"}}, "x")


def test_only_the_named_figure_generation_is_taken(world, tmp_path):
    registry = package(tmp_path, "g9_to_g8f")
    marius, bea, anna = (world["uid"](n) for n in ("Marius HD-8K", "Bea", "Anna"))
    assert {world["conn"].execute("SELECT value FROM dossier_field f JOIN dossier d ON d.id = f.dossier_id"
                                  " WHERE d.uid = ? AND f.field = 'variant'", (u,)).fetchone()[0]
            for u in (marius, bea)} == {'"genesis_9"'}
    assert [r["processes"] for r in convert_routes(world, registry, marius)] == [["g9_to_g8f"]]
    assert [r["processes"] for r in convert_routes(world, registry, bea)] == [["g9_to_g8f"]]
    assert convert_routes(world, registry, anna) == []
    assert path_of(world, registry, marius)["status"] == "ready"
    anna_path = path_of(world, registry, anna)
    assert anna_path["status"] == "none" and "as g8f_character" in anna_path["problem"]


def test_a_variant_matches_in_either_case(world, tmp_path):
    registry = package(tmp_path, "g9_any_case", variants='variants = ["Genesis_9"]')
    assert [r["processes"] for r in convert_routes(world, registry, world["uid"]("Bea"))] == [["g9_any_case"]]
    assert convert_routes(world, registry, world["uid"]("Anna")) == []


def test_no_variants_takes_every_generation(world, tmp_path):
    registry = package(tmp_path, "any_figure", variants="")
    assert [r["processes"] for r in convert_routes(world, registry, world["uid"]("Anna"))] == [["any_figure"]]


# content prerequisites ---------------------------------------------------------------------------


def test_a_content_prerequisite_needs_an_app_and_paths():
    def with_prerequisite(**p):
        return {**BASE, "prerequisite": [{"id": "fig", "kind": "content", **p}]}

    with pytest.raises(DefinitionError, match="tool is required for a content prerequisite"):
        parse_manifest(with_prerequisite(paths=[EXCHANGE_G8F]), "x")
    with pytest.raises(DefinitionError, match="paths is required for a content prerequisite"):
        parse_manifest(with_prerequisite(tool="daz_studio"), "x")
    parsed = parse_manifest(with_prerequisite(tool="daz_studio", paths=[EXCHANGE_G8F]), "x")
    assert parsed.prerequisites[0].kind == "content" and parsed.prerequisites[0].paths == (EXCHANGE_G8F,)


def test_content_is_looked_for_in_daz_studios_content_directories(tmp_path, daz_settings):
    registry = package(tmp_path, "needs_copy", prerequisite=CONTENT)
    needs = registry.get("needs_copy")
    status = lambda: check_prerequisites(needs, {})[0]  # noqa: E731

    assert not status().ok and status().detail == "daz_studio has no content directories (see PROCESS_FILES.md)"
    first, second = tmp_path / "Daz" / "My Library", tmp_path / "Daz" / "Exchange"
    first.mkdir(parents=True)
    daz_settings([first, second])
    assert not status().ok and status().detail == (
        f"missing {EXCHANGE_G8F} from daz_studio's content directories (see PROCESS_FILES.md)")
    assert not ready(needs, {})
    write(second.joinpath(*EXCHANGE_G8F.split("/")), b"{}")
    assert status().ok and status().detail == f"in {second}"
    assert ready(needs, {})


def test_a_missing_figure_copy_says_so_on_the_claim(world, tmp_path, daz_settings):
    registry = package(tmp_path, "g9_needs_copy", prerequisite=CONTENT)
    marius = world["uid"]("Marius HD-8K")
    daz_settings([world["library"]])
    found = path_of(world, registry, marius)
    assert found["status"] == "not_ready" and found["process"] == "g9_needs_copy"
    assert "Exchange G8F: missing People/Genesis 8 Female/" in found["problem"]
    write(world["library"].joinpath(*EXCHANGE_G8F.split("/")), b"{}")
    assert path_of(world, registry, marius)["status"] == "ready"


def test_content_directories_are_only_read(tmp_path, daz_settings):
    import winreg

    from exchange.bridges import content_directories, daz

    daz_settings([tmp_path / "A", tmp_path / "B"])
    assert content_directories("daz_studio") == [tmp_path / "A", tmp_path / "B"]
    assert content_directories("blender") == []
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"{daz.REGISTRY_KEY}\Studio4") as key:
        assert winreg.QueryInfoKey(key)[1] == 3  # NumContentDirs and the two folders, nothing added


# core.rewrite_daz_paths --------------------------------------------------------------------------


def morph(prefix):
    """A morph as Daz saves one on a figure at ``prefix``: its own id, its parent figure, and joint
    formulas naming bones by the figure's URL (about 1,000 of them in a real one)."""
    return json.dumps({
        "file_version": "0.6.0.0",
        "asset_info": {"id": f"{prefix}Morphs/Exchange/Anna/Anna.dsf", "type": "modifier"},
        "modifier_library": [{
            "id": "Anna-0xaaf77b4", "parent": f"{prefix}Genesis8Female.dsf#Genesis8Female",
            "formulas": [{"output": f"lHand:{prefix}Genesis8Female.dsf#lHand?center_point/x",
                          "operations": [{"op": "push", "url": "Genesis8Female:#Anna-0xaaf77b4?value"}]},
                         {"output": f"rHand:{prefix}Genesis8Female.dsf#rHand?end_point/y"}]}],
    }, indent="\t")


def rewrite(tmp_path, files, **params):
    root = tmp_path / "built"
    for rel, data in files.items():
        write(root.joinpath(*rel.split("/")), data)
    logs = []
    ctx = Context(tmp_path / "work", {"name": "Anna"}, logs.append)
    result = rewrite_daz_paths(ctx, Artifact("Files", root, list(files)), **{"source": COPY, "target": REGULAR, **params})
    return result, logs


def test_a_morph_built_on_the_copy_names_the_regular_figure(tmp_path):
    built = morph(COPY)
    result, logs = rewrite(tmp_path, {"data/Exchange/Genesis 8/Female/Morphs/Exchange/Anna/Anna.dsf": built.encode(),
                                      "data/Exchange/Genesis 8/Female/Morphs/Exchange/Anna/Anna.png": b"png"})
    assert result.files == ["data/Daz 3D/Genesis 8/Female/Morphs/Exchange/Anna/Anna.dsf",
                            "data/Daz 3D/Genesis 8/Female/Morphs/Exchange/Anna/Anna.png"]
    text = result.paths()[0].read_text(encoding="utf-8")
    assert text == morph(REGULAR) and "/data/Exchange/" not in text
    assert result.paths()[1].read_bytes() == b"png"
    assert logs == [f"{COPY} → {REGULAR}: 4 mentions; 2 of 2 files moved"]


def test_compressed_files_stay_compressed_and_others_stay_put(tmp_path):
    result, _ = rewrite(tmp_path, {"data/exchange/genesis 8/female/Morphs/A.dsf": gzip.compress(morph(COPY).encode()),
                                   "People/Genesis 8 Female/Characters/Anna.duf": morph(COPY).encode(),
                                   "readme.txt": COPY.encode()})
    assert result.files == ["data/Daz 3D/Genesis 8/Female/Morphs/A.dsf",  # the folder matched in any case
                            "People/Genesis 8 Female/Characters/Anna.duf", "readme.txt"]
    dsf, duf, txt = result.paths()
    assert gzip.decompress(dsf.read_bytes()).decode("utf-8") == morph(REGULAR)
    assert duf.read_text(encoding="utf-8") == morph(REGULAR)
    assert txt.read_bytes() == COPY.encode()  # not a Daz file: passed through as it was


def test_the_source_files_are_not_touched(tmp_path):
    source = morph(COPY).encode()
    rewrite(tmp_path, {"data/Exchange/Genesis 8/Female/A.dsf": source})
    assert (tmp_path / "built" / "data" / "Exchange" / "Genesis 8" / "Female" / "A.dsf").read_bytes() == source


def test_nothing_to_rewrite_is_an_error(tmp_path):
    with pytest.raises(OperationError, match="no file mentions /data/Exchange/Genesis%208/Female/"):
        rewrite(tmp_path, {"data/Daz 3D/Genesis 8/Female/A.dsf": morph(REGULAR).encode()})


@pytest.mark.parametrize("params", [{"source": "data/Exchange/"}, {"target": "/data/DAZ 3D/Genesis 8/Female"},
                                    {"source": ""}])
def test_the_folders_must_be_data_folders(tmp_path, params):
    with pytest.raises(OperationError, match="must be a data folder"):
        rewrite(tmp_path, {"A.dsf": morph(COPY).encode()}, **params)


def test_two_files_landing_on_one_path_is_an_error(tmp_path):
    with pytest.raises(OperationError, match="would overwrite"):
        rewrite(tmp_path, {"data/Exchange/Genesis 8/Female/A.dsf": morph(COPY).encode(),
                           "data/Daz 3D/Genesis 8/Female/a.dsf": morph(COPY).encode()})


def test_a_process_can_name_it(tmp_path):
    folder = tmp_path / "packages" / "to_regular"
    write(folder / "process.toml", (MANIFEST.format(id="to_regular", variants="", prerequisite="").replace(
        'operation = "core.copy"',
        f'operation = "core.rewrite_daz_paths"\nparams = {{ source = "{COPY}", target = "{REGULAR}" }}')).encode())
    trust(install(folder))
    assert validate(load_registry().get("to_regular")) == []
