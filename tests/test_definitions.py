from pathlib import Path

import pytest

from exchange.definitions import load_definitions
from exchange.errors import DefinitionError

MINIMAL_ENV = """
[environment]
id = "{id}"
name = "Test"
format_version = 1

[[detection.signature]]
kind = "file"
path = "marker.txt"
weight = 1.0

[layer]
handler = "folder"
"""


def write(base: Path, sub: str, name: str, text: str) -> Path:
    path = base / sub / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_builtins_load(definitions):
    assert {"daz_studio", "skyrim_se", "mo2_generic", "loose_files"} <= set(definitions.environments)
    assert definitions.fallback_environment.id == "loose_files"
    assert definitions.is_a("daz_wearable", "mesh")
    assert not definitions.is_a("daz_morph", "mesh")
    daz = definitions.environments["daz_studio"]
    assert daz.handler == "daz"
    assert [v.id for v in daz.variants] == ["genesis_9", "genesis_8", "genesis_3", "genesis_2"]
    assert daz.layer_options["content_types"]["Follower/Wardrobe"] == "daz_wearable"
    mesh_rules = definitions.dossier_types["mesh"].identify
    assert any(r.glob == "**/*.nif" for r in mesh_rules)


def test_extra_dir_adds_and_overrides(tmp_path):
    write(tmp_path, "environments", "test_env.toml", MINIMAL_ENV.format(id="test_env"))
    write(tmp_path, "dossier_types", "mesh.toml", """
[dossier_type]
id = "mesh"
name = "Mesh (custom)"
format_version = 1
scope = "universal"
""")
    defs = load_definitions([tmp_path], include_user_dir=False)
    assert "test_env" in defs.environments
    assert defs.dossier_types["mesh"].name == "Mesh (custom)"


def test_user_dir_is_loaded(monkeypatch, tmp_path):
    monkeypatch.setenv("EXCHANGE_DATA_DIR", str(tmp_path))
    write(tmp_path / "definitions", "environments", "mine.toml", MINIMAL_ENV.format(id="mine"))
    assert "mine" in load_definitions().environments


@pytest.mark.parametrize(
    ("text", "message"),
    [
        (MINIMAL_ENV.format(id="x") + "\n[capabilities]\nwritable = true\nreadabel = true\n",
         "unknown key capabilities.readabel"),
        (MINIMAL_ENV.format(id="Bad-Id"), "lower_snake_case"),
        (MINIMAL_ENV.format(id="x").replace('handler = "folder"', 'handler = "nope"'),
         "layer.handler 'nope'"),
        (MINIMAL_ENV.format(id="x").replace("weight = 1.0", "weight = 2"),
         "weight must be between"),
        (MINIMAL_ENV.format(id="x").replace('kind = "file"', 'kind = "regex"'),
         "kind must be one of"),
        (MINIMAL_ENV.format(id="x").replace("format_version = 1", "format_version = 7"),
         "unsupported format_version 7"),
        (MINIMAL_ENV.format(id="x") + "\n[compatibility]\nnative_dossier_types = [\"ghost\"]\n",
         "unknown dossier type 'ghost'"),
        ("[environment\nid = 1", "invalid TOML"),
    ],
)
def test_invalid_environment_reports_file_and_key(tmp_path, text, message):
    path = write(tmp_path, "environments", "broken.toml", text)
    with pytest.raises(DefinitionError) as info:
        load_definitions([tmp_path], include_user_dir=False)
    assert str(path) in str(info.value)
    assert message in str(info.value)


def dossier_type(type_id: str, body: str) -> str:
    return f'[dossier_type]\nid = "{type_id}"\nname = "T"\nformat_version = 1\n{body}\n'


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ('scope = "universal"\nextends = "nothing"', "unknown dossier type 'nothing'"),
        ('scope = "environment"', "environment is required"),
        ('scope = "environment"\nenvironment = "atlantis"', "unknown environment 'atlantis'"),
        ('scope = "universal"\n\n[[identify]]\nconfidence = 0.5', "needs glob or globs"),
    ],
)
def test_invalid_dossier_type(tmp_path, body, message):
    write(tmp_path, "dossier_types", "custom.toml", dossier_type("custom", body))
    with pytest.raises(DefinitionError, match=message):
        load_definitions([tmp_path], include_user_dir=False)


def test_dossier_type_cycle(tmp_path):
    write(tmp_path, "dossier_types", "a.toml", dossier_type("loop_a", 'scope = "universal"\nextends = "loop_b"'))
    write(tmp_path, "dossier_types", "b.toml", dossier_type("loop_b", 'scope = "universal"\nextends = "loop_a"'))
    with pytest.raises(DefinitionError, match="cycle"):
        load_definitions([tmp_path], include_user_dir=False)


def test_second_fallback_is_rejected(tmp_path):
    write(tmp_path, "environments", "other_loose.toml", """
[environment]
id = "other_loose"
name = "Other"
format_version = 1
fallback = true

[layer]
handler = "folder"
""")
    with pytest.raises(DefinitionError, match="exactly one fallback"):
        load_definitions([tmp_path], include_user_dir=False)
