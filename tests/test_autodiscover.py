import json

from builders import unreal_project, write
from conftest import copy_fixture
from exchange.autodiscover import Places, discover_sources, parse_vdf


def test_parse_vdf():
    data = parse_vdf('"libraryfolders"\n{\n "0"\n {\n  "path" "C:\\\\Steam"\n  "apps" { "489830" "1" }\n }\n}')
    assert data == {"libraryfolders": {"0": {"path": "C:\\Steam", "apps": {"489830": "1"}}}}


def test_discovers_from_every_source(definitions, tmp_path):
    steam, games = tmp_path / "Steam", tmp_path / "SteamLibrary"
    write(steam / "steamapps" / "libraryfolders.vdf",
          f'"libraryfolders" {{ "0" {{ "path" "{str(games).replace(chr(92), chr(92) * 2)}" }} }}'.encode())
    write(games / "steamapps" / "appmanifest_4000.acf",
          b'"AppState" { "appid" "4000" "name" "Garry\'s Mod" "installdir" "GarrysMod" }')
    (games / "steamapps" / "common" / "GarrysMod").mkdir(parents=True)

    program_data, local = tmp_path / "ProgramData", tmp_path / "Local"
    epic_game = tmp_path / "Epic" / "SomeGame"
    epic_game.mkdir(parents=True)
    write(program_data / "Epic" / "EpicGamesLauncher" / "Data" / "Manifests" / "abc.item",
          json.dumps({"DisplayName": "Some Game", "InstallLocation": str(epic_game)}).encode())

    project = unreal_project(tmp_path / "Projects" / "MyGame")
    write(local / "UnrealEngine" / "5.4" / "Saved" / "Config" / "WindowsEditor" / "EditorSettings.ini",
          f'[/Script/UnrealEd.EditorSettings]\nRecentlyOpenedProjectFiles=(ProjectName="{project / "MyGame.uproject"}",LastOpenTime=0)\n'.encode())

    daz = copy_fixture("fake_daz_library", tmp_path / "Daz" / "My Library")
    copy_fixture("fake_mo2", local / "ModOrganizer" / "Skyrim SE")
    public = tmp_path / "Public"

    registry = {"Software\\Valve\\Steam": {"SteamPath": str(steam)},
                "Software\\DAZ\\Studio4": {"ContentDir0": str(daz), "ContentDir1": str(tmp_path / "gone"),
                                           "Language": "en"}}
    places = Places(local_appdata=local, program_data=program_data, public=public,
                    registry=lambda key: registry.get(key, {}))
    found = {f.name: f for f in discover_sources(definitions, places, registered_roots=[str(daz)])}

    assert found["My Library"].type_id == "daz_studio" and found["My Library"].registered
    assert found["My Library"].via == "Daz Studio settings"
    assert found["MyGame"].type_id == "unreal_project"
    assert found["Skyrim SE (Skyrim Special Edition)"].type_id == "skyrim_se"
    assert found["Garry's Mod"].type_id is None  # found, but no definition yet
    assert found["Some Game"].via == "Epic Games launcher"
    assert "gone" not in found  # missing folders are dropped
    assert "My DAZ 3D Library" not in found  # the default public library does not exist here
    assert list(found.values())[0].type_id is not None  # recognized ones first


def test_nothing_configured(definitions):
    assert discover_sources(definitions, Places()) == []
