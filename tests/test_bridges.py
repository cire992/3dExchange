"""Bridges to external apps (Roadmap phase 4b), with stand-ins for Blender and Daz Studio; the real
Blender runs too when it is installed."""

import json
import os
import shutil
import sys
import threading
import time
from pathlib import Path

import pytest

from builders import copy_fixture, glb_bytes, write
from exchange.bridges import BridgeError, make_bridge
from exchange.locks import Lock
from exchange.pipelines.registry import install, load_registry, resolve_tool, set_tool, trust, validate
from exchange.requisitions import lifecycle
from exchange.requisitions.plan import plan_requisition, queue_plan
from exchange.requisitions.runner import run_queue

HERE = Path(__file__).parent
FAKES = HERE / "fixtures" / "fake_apps"
DEMO = HERE / "fixtures" / "pipelines" / "bridge_demo"


def fake_app(tmp_path: Path, name: str) -> Path:
    """A .cmd that runs one of the stand-ins with this Python."""
    cmd = tmp_path / "apps" / f"{name}.cmd"
    cmd.parent.mkdir(parents=True, exist_ok=True)
    cmd.write_text(f'@"{sys.executable}" "{FAKES / (name + ".py")}" %*\n', encoding="utf-8")
    return cmd


@pytest.fixture
def logs():
    return []


def test_blender_bridge(tmp_path, logs):
    bridge = make_bridge("blender", fake_app(tmp_path, "fake_blender"), tmp_path / "work", logs.append)
    script = DEMO / "scripts" / "make.py"
    source = write(tmp_path / "in" / "thing.glb", b"glTF")
    result = bridge.run(script, {"word": "hi", "source": str(source), "target": str(tmp_path / "work" / "out.txt")})
    assert (tmp_path / "work" / "out.txt").read_text(encoding="utf-8") == "hi from thing.glb"
    assert result == {"files": [str(tmp_path / "work" / "out.txt")]}
    calls = (tmp_path / "work" / "fake_blender_calls.txt").read_text(encoding="utf-8")
    assert calls.startswith("-b --factory-startup --python-exit-code 1 --python")
    assert any("finished" in line for line in logs)

    with pytest.raises(BridgeError, match="RuntimeError: the script failed on purpose"):
        bridge.run(script, {"word": "boom", "source": str(source), "target": str(tmp_path / "x.txt")})
    with pytest.raises(BridgeError, match="no Blender template"):
        bridge.run(script, {}, template=tmp_path / "missing.blend")


def test_daz_bridge_closes_daz_studio_after_the_result(tmp_path, logs):
    bridge = make_bridge("daz_studio", fake_app(tmp_path, "fake_daz"), tmp_path / "work", logs.append)
    script = write(tmp_path / "scripts" / "convert.dsa", b"function exchangeRun(args) { return {}; }")
    started = time.monotonic()
    result = bridge.run(script, {"figure": "Genesis 8 Female"}, timeout=60)
    assert time.monotonic() - started < 30  # closed once the result was written, not after its 120 s
    assert result["echo"] == {"figure": "Genesis 8 Female"}  # the wrapper adds workdir inside Daz Studio
    assert result["flags"] == ["-instanceName", "Exchange", "-noPrompt", "-noDefaultScene"]
    assert any("closing it" in line for line in logs)
    wrapper = (tmp_path / "work" / "exchange_daz_job.dsa").read_text(encoding="utf-8")
    assert "include(" in wrapper and "App.delayedExit" in wrapper

    failing = write(tmp_path / "scripts" / "bad.dsa", b"// FAIL")
    with pytest.raises(BridgeError, match="failed on purpose"):
        bridge.run(failing, {}, timeout=60)


@pytest.mark.skipif(sys.platform != "win32", reason="Daz Studio keeps its settings in the Windows registry")
def test_daz_instance_settings_come_from_the_main_instance(tmp_path, logs):
    import winreg

    from exchange.bridges import daz

    base = daz.REGISTRY_KEY  # a test key, not the user's (conftest)
    main = {"AutoUpdate": (3, winreg.REG_DWORD), "NumContentDirs": (2, winreg.REG_DWORD),
            "ContentDir0": ("D:/Daz/My Library", winreg.REG_SZ), "ContentDir1": ("D:/Daz/Personal", winreg.REG_SZ),
            "Startups": (1263, winreg.REG_DWORD)}
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"{base}\Studio4") as key:
            for name, (value, kind) in main.items():
                winreg.SetValueEx(key, name, 0, kind, value)
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"{base}\Studio4[Exchange]") as key:
            winreg.SetValueEx(key, "ContentDir2", 0, winreg.REG_SZ, "C:/Users/Public/Documents/My DAZ 3D Library")
            winreg.SetValueEx(key, "Startups", 0, winreg.REG_DWORD, 2)

        assert daz.sync_instance_settings() == ["AutoUpdate", "ContentDir0", "ContentDir1", "NumContentDirs"]
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"{base}\Studio4[Exchange]") as key:
            got = {winreg.EnumValue(key, i)[0]: winreg.EnumValue(key, i)[1] for i in range(winreg.QueryInfoKey(key)[1])}
        assert got == {"AutoUpdate": 3, "NumContentDirs": 2, "ContentDir0": "D:/Daz/My Library",
                       "ContentDir1": "D:/Daz/Personal", "Startups": 2}  # stale ContentDir2 gone; own values kept
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"{base}\Studio4") as key:
            assert winreg.QueryInfoKey(key)[1] == len(main)  # the main instance is only read
    finally:
        for key in (rf"{base}\Studio4[Exchange]", rf"{base}\Studio4", base, base.rsplit("\\", 1)[0]):
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key)
            except OSError:
                pass

    # A failed job quotes Daz Studio's own log of the run, copied into the work folder.
    log = daz.instance_folder() / "log.txt"
    write(log, b"[INFO] :: Application update detected\n")
    os.utime(log, (time.time() + 60, time.time() + 60))
    bridge = make_bridge("daz_studio", fake_app(tmp_path, "fake_daz"), tmp_path / "work", logs.append)
    with pytest.raises(BridgeError, match="Application update detected"):
        bridge.run(write(tmp_path / "scripts" / "bad.dsa", b"// FAIL"), {}, timeout=60)
    assert (tmp_path / "work" / "daz_studio_log.txt").is_file()


def test_command_bridge_timeouts_and_one_job_per_app(tmp_path, logs):
    tool = tmp_path / "apps" / "slow.cmd"
    tool.parent.mkdir(parents=True)
    tool.write_text(f'@"{sys.executable}" -c "import sys, time; print(\'working\'); time.sleep(float(sys.argv[1])); '
                    f'sys.exit(int(sys.argv[2]))" %*\n', encoding="utf-8")
    bridge = make_bridge("slowtool", tool, tmp_path / "work", logs.append)
    assert "working" in bridge.run_command(["0", "0"])
    with pytest.raises(BridgeError, match="exit code 3"):
        bridge.run_command(["0", "3"])
    with pytest.raises(BridgeError, match="did not finish within 1 s"):
        bridge.run_command(["30", "0"], timeout=1)

    # Another job holds the app: this one waits, then runs.
    lock = Lock("app-slowtool")
    lock.acquire()
    threading.Timer(1.5, lock.release).start()
    started = time.monotonic()
    bridge.run_command(["0", "0"])
    assert time.monotonic() - started >= 1.4 and any("waiting for another" in line for line in logs)

    with pytest.raises(BridgeError, match="not found"):
        make_bridge("blender", tmp_path / "nope.exe", tmp_path, logs.append)


def test_tools_resolve_newest_and_apps_must_be_declared(tmp_path):
    for version in ("Tool 1.2", "Tool 1.10", "Tool 1.9"):
        write(tmp_path / "Apps" / version / "tool.exe", b"MZ")
    copy = tmp_path / "pkg"
    shutil.copytree(DEMO, copy)
    text = (copy / "pipeline.toml").read_text(encoding="utf-8")
    (copy / "pipeline.toml").write_text(text.replace('tool = "blender"', f'tool = "blender"\npaths = ["{(tmp_path / "Apps").as_posix()}/Tool */tool.exe"]'),
                                        encoding="utf-8")
    trust(install(copy))
    package = load_registry().get("bridge_demo")
    assert Path(resolve_tool(package, "blender")).parent.name == "Tool 1.10"  # newest, by version
    set_tool("blender", str(tmp_path / "Apps" / "Tool 1.2" / "tool.exe"))
    assert Path(resolve_tool(package, "blender")).parent.name == "Tool 1.2"  # the user's choice wins

    (copy / "pipeline.toml").write_text(text.split("[[prerequisite]]")[0] + "[[step]]" + text.split("[[step]]")[1],
                                        encoding="utf-8")
    trust(install(copy))
    assert any("declare it as a [[prerequisite]]" in p for p in validate(load_registry().get("bridge_demo")))


@pytest.fixture
def meshes(scan, tmp_path, library, definitions, db_path):
    folder = copy_fixture("loose_files", tmp_path / "scan" / "Loose")
    write(folder / "Downloads" / "props" / "Teapot.glb", glb_bytes())
    scan(folder)
    conn = library()
    env = conn.execute("SELECT environment_id FROM environment_root").fetchone()[0]
    return conn, env, definitions, db_path


def test_a_requisition_through_a_bridge(meshes, tmp_path):
    conn, env, definitions, db_path = meshes
    set_tool("blender", str(fake_app(tmp_path, "fake_blender")))
    trust(install(DEMO))
    registry = load_registry()
    teapot = conn.execute("SELECT uid FROM dossier WHERE name = 'Teapot'").fetchone()[0]
    plan = plan_requisition(conn, definitions, registry, teapot, env, pipelines=["bridge_demo"], params={"word": "made"})
    req = queue_plan(conn, plan, registry)
    run_queue(db_path, definitions, registry)
    d = lifecycle.detail(conn, req)
    assert d["state"] == "fulfilled", d
    out = Path(d["endpoint"]["folder"]) / "Demo" / "Teapot" / "made.txt"
    assert out.read_text(encoding="utf-8") == "made from Teapot.glb"


BLENDER = resolve_tool(load_registry(include_user=False).get("convert_mesh"), "blender", {})


@pytest.mark.skipif(BLENDER is None, reason="Blender is not installed")
def test_real_blender_converts_a_mesh(meshes):
    conn, env, definitions, db_path = meshes
    registry = load_registry()
    teapot = conn.execute("SELECT uid FROM dossier WHERE name = 'Teapot'").fetchone()[0]
    plan = plan_requisition(conn, definitions, registry, teapot, env, pipelines=["convert_mesh"], params={"format": "obj"})
    req = queue_plan(conn, plan, registry)
    run_queue(db_path, definitions, registry)
    d = lifecycle.detail(conn, req)
    assert d["state"] == "fulfilled", d
    out = Path(d["endpoint"]["folder"]) / "Teapot"
    assert (out / "Teapot.obj").read_text(encoding="utf-8").count("\nv ") > 0
