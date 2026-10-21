"""Unreal Engine projects: detection, content packs, plugins and asset types."""

from builders import root_report
from exchange.scanner.detection import detect
from exchange.scanner.discovery import discover


def test_unreal_project_is_detected(definitions, unreal):
    envs = detect(discover(unreal), definitions)
    assert [e.definition.id for e in envs] == ["unreal_project"]
    assert envs[0].confidence == 1.0
    assert "glob *.uproject" in envs[0].signals


def test_unreal_containers_products_and_types(scan, unreal, library):
    report = scan(unreal)
    stats = root_report(report, "unreal_project").identification
    assert stats.layer_config == {"project": "MyGame", "engine_association": "5.4"}

    conn = library()
    containers = {r["name"]: r["kind"] for r in conn.execute("SELECT name, kind FROM container")}
    assert containers == {"MyGame": "project_content", "MegaPack": "content_pack", "Cool Tools": "plugin"}

    rows = conn.execute(
        "SELECT d.name, d.type_id, d.confidence, p.name AS parent FROM dossier d"
        " LEFT JOIN dossier p ON p.id = d.parent_id").fetchall()
    d = {r["name"]: r for r in rows}
    assert d["MegaPack"]["type_id"] == "product" and d["MegaPack"]["confidence"] == 0.55
    assert d["SM_Rock"]["type_id"] == "static_mesh" and d["SM_Rock"]["parent"] == "MegaPack"
    assert d["T_Rock_D"]["type_id"] == "texture"
    assert d["M_Rock"]["type_id"] == "material"
    assert d["BP_Player"]["type_id"] == "unreal_blueprint_actor"
    assert d["Main"]["type_id"] == "unreal_level"
    assert d["Cool Tools"]["type_id"] == "product" and d["Cool Tools"]["confidence"] == 0.9
    assert d["SK_Robot"]["type_id"] == "skinned_mesh" and d["SK_Robot"]["parent"] == "Cool Tools"
    assert "junk" not in d  # Intermediate/ is ignored, even though .obj is a mesh format

    fields = dict(conn.execute(
        "SELECT f.field, f.value FROM dossier_field f JOIN dossier d ON d.id = f.dossier_id"
        " WHERE d.name = 'Cool Tools'").fetchall())
    assert fields["version"] == '"2.1"'
    assert fields["authors"] == '["Jane Doe"]'
    assert fields["preview"] == '"Plugins/CoolTools/Resources/Icon128.png"'

    states = dict(conn.execute("SELECT rel_path, state FROM file").fetchall())
    assert states["Saved/Logs/MyGame.log"] == "ignored"
    assert states["Plugins/CoolTools/Source/CoolTools.cpp"] == "ignored"
    assert states["MyGame.uproject"] == "ignored"
    assert states["Content/Developers/me/Scratch.uasset"] == "present"  # project content
