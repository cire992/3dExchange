from pathlib import Path

from exchange.scanner.detection import RegisteredEnvironment, detect
from exchange.scanner.discovery import discover


def by_type(envs):
    return {e.definition.id: e for e in envs}


def test_single_environments(definitions, daz_library, mo2_instance, loose_folder):
    daz = detect(discover(daz_library), definitions)
    assert [(e.definition.id, e.root_rel) for e in daz] == [("daz_studio", "")]
    assert daz[0].confidence == 1.0
    assert "dir Runtime/Support" in daz[0].signals

    mo2 = detect(discover(mo2_instance), definitions)
    assert [e.definition.id for e in mo2] == ["skyrim_se"]  # beats mo2_generic
    assert any("gameName" in s for s in mo2[0].signals)

    loose = detect(discover(loose_folder), definitions)
    assert [(e.definition.id, e.root_rel, len(e.files)) for e in loose] == [("loose_files", "", 7)]


def test_mixed_folder_is_split(definitions, mixed):
    envs = by_type(detect(discover(mixed), definitions))
    assert set(envs) == {"daz_studio", "skyrim_se", "loose_files"}
    assert envs["daz_studio"].root == mixed / "Daz Library"
    assert envs["skyrim_se"].root == mixed / "MO2"
    assert envs["loose_files"].root == mixed
    # Files are re-rooted at their environment, and each belongs to exactly one.
    assert any(f.rel == "ModOrganizer.ini" for f in envs["skyrim_se"].files)
    assert all(f.rel.startswith("Loose/") for f in envs["loose_files"].files)
    total = sum(len(e.files) for e in envs.values())
    assert total == len(discover(mixed).files)


def test_unknown_mo2_game_falls_back_to_generic(definitions, mo2_instance):
    ini = mo2_instance / "ModOrganizer.ini"
    ini.write_text(ini.read_text().replace("Skyrim Special Edition", "Cyberpunk 2077"))
    envs = detect(discover(mo2_instance), definitions)
    assert [e.definition.id for e in envs] == ["mo2_generic"]


def test_detection_is_case_insensitive(definitions, daz_library):
    (daz_library / "Runtime").rename(daz_library / "runtime")
    (daz_library / "People").rename(daz_library / "PEOPLE")
    assert detect(discover(daz_library), definitions)[0].definition.id == "daz_studio"


def test_lone_marker_is_not_enough(definitions, tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "thing.bin").write_bytes(b"x")
    assert [e.definition.id for e in detect(discover(tmp_path), definitions)] == ["loose_files"]


def test_registered_environment_keeps_its_type(definitions, mixed):
    # The user registered the MO2 folder as a generic instance; re-detection must not change it.
    registered = [RegisteredEnvironment(mixed / "MO2", "mo2_generic", 0.6)]
    envs = by_type(detect(discover(mixed), definitions, registered))
    assert "skyrim_se" not in envs
    assert envs["mo2_generic"].registered
    assert envs["mo2_generic"].root == Path(mixed / "MO2")
