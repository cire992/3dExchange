"""Requisitions v1 (Roadmap phase 4a): process packages, planning, the queue, writing output,
sidecars, staleness, removal and the command line."""

import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from builders import copy_fixture, png_bytes, write
from exchange.cli import main
from exchange.curation import Curator
from exchange.db import repository as repo
from exchange.errors import DefinitionError
from exchange.locks import Lock, LockBusy
from exchange.processes.manifest import parse_manifest
from exchange.processes.registry import (
    ProcessError,
    check_prerequisites,
    install,
    load_registry,
    ready,
    set_tool,
    trust,
    validate,
)
from exchange.requisitions import lifecycle
from exchange.requisitions.plan import plan_requisition, queue_plan, routes
from exchange.requisitions.runner import run_queue
from exchange.requisitions.runner import test_process as harness

STAMP = Path(__file__).parent / "fixtures" / "processes" / "stamp_images"


@pytest.fixture
def setup(scan, tmp_path, library, definitions, db_path):
    """A loose-files library whose Barrel01 mesh has a (real) texture linked onto it, and the
    test process installed and trusted."""
    folder = copy_fixture("loose_files", tmp_path / "scan" / "Loose")
    write(folder / "Downloads" / "barrel" / "Barrel01_N.png", png_bytes((64, 32)))
    scan(folder)
    conn = library()
    root = conn.execute("SELECT id, environment_id FROM environment_root").fetchone()
    barrel = conn.execute("SELECT uid FROM dossier WHERE name = 'Barrel01'").fetchone()[0]
    Curator(conn, definitions).link_files(barrel, [(root["id"], "downloads/barrel/barrel01_n.png")])
    trust(install(STAMP))
    return {"conn": conn, "folder": folder, "env": root["environment_id"], "barrel": barrel,
            "registry": load_registry(), "definitions": definitions, "db": db_path}


def plan(s, **kwargs):
    kwargs.setdefault("processes", ["stamp_images"])
    return plan_requisition(s["conn"], s["definitions"], s["registry"], s["barrel"], s["env"], **kwargs)


def run(s, **kwargs):
    return run_queue(s["db"], s["definitions"], s["registry"], **kwargs)


def entries_of(conn, uid):
    return conn.execute("SELECT e.* FROM entry e JOIN ledger l ON l.id = e.ledger_id JOIN dossier d ON d.id = l.dossier_id"
                        " WHERE d.uid = ? ORDER BY e.id", (uid,)).fetchall()


# Packages ---------------------------------------------------------------------------------------


def test_manifests_are_strict():
    base = {"process": {"id": "x", "name": "X", "version": "1", "format_version": 1},
            "output": {"environment": "same"}, "step": [{"id": "a", "operation": "core.copy"}]}
    assert parse_manifest(base, "x").steps[0].inputs == ("source",)
    for broken, message in (
            ({**base, "colour": 1}, "unknown key"),
            ({**base, "step": [{"id": "a", "operation": "core.copy", "inputs": ["later"]}]}, "not an earlier step"),
            ({**base, "step": [{"id": "a", "operation": "core.copy", "params": {"x": "{nope}"}}]}, "unknown parameter"),
            ({**base, "parameter": [{"id": "n", "type": "int", "default": "big"}]}, "must be a number"),
            ({**base, "parameter": [{"id": "c", "type": "choice", "default": "a"}]}, "choices is required"),
            ({**base, "step": []}, "at least one")):
        with pytest.raises(DefinitionError, match=message):
            parse_manifest(broken, "x")


def test_packages_trust_and_prerequisites(tmp_path):
    registry = load_registry()
    assert ready(registry.get("copy_entry"))
    package = install(STAMP)
    registry = load_registry()
    untrusted = registry.get("stamp_images")
    assert not untrusted.trusted and not ready(untrusted)
    with pytest.raises(ProcessError, match="not trusted"):
        untrusted.operations()  # its code is never imported before it is trusted
    trust(untrusted)
    assert ready(load_registry().get("stamp_images"))
    # Changing its code needs trusting again.
    (package.path / "operations" / "stamp.py").write_text("# changed\n", encoding="utf-8")
    assert not load_registry().get("stamp_images").trusted

    # A tool prerequisite is red until the tool is found.
    copy = tmp_path / "needs_tool"
    shutil.copytree(STAMP, copy)
    manifest = (copy / "process.toml").read_text(encoding="utf-8").replace('id = "stamp_images"', 'id = "needs_tool"')
    manifest += '\n[[prerequisite]]\nid = "fake"\nkind = "tool"\ntool = "faketool"\nhint = "install it"\n'
    (copy / "process.toml").write_text(manifest, encoding="utf-8")
    trust(install(copy))
    needy = load_registry().get("needs_tool")
    [status] = check_prerequisites(needy)
    assert not status.ok and "exchange tools set faketool" in status.detail and not ready(needy)
    tool = write(tmp_path / "faketool.exe", b"MZ")
    set_tool("faketool", str(tool))
    assert ready(load_registry().get("needs_tool"))


def test_chain_types_are_checked(tmp_path):
    copy = tmp_path / "bad"
    shutil.copytree(STAMP, copy)
    text = (copy / "process.toml").read_text(encoding="utf-8").replace('id = "stamp_images"', 'id = "bad"')
    (copy / "process.toml").write_text(text.replace('operation = "stamp.mark"', 'operation = "stamp.nothing"'),
                                        encoding="utf-8")
    trust(install(copy))
    assert any("no operation 'stamp.nothing'" in p for p in validate(load_registry().get("bad")))


# Planning and running ------------------------------------------------------------------------


def test_routes_and_plan(setup):
    s = setup
    found = routes(s["conn"], s["definitions"], s["registry"], s["barrel"], s["env"])
    assert {r["route"] for r in found} == {"copy", "convert"}  # the target environment already holds it
    p = plan(s, params={"size": 8, "stamp_images.note": "hello"})
    [item] = p.items
    assert item.route == "convert" and item.params["stamp_images"] == {"size": 8, "review": False, "note": "hello"}
    assert p.endpoint.folder.endswith("Exchange Conversions") and p.endpoint.visibility == "personal"
    bad = plan(s, params={"size": "big"})
    assert not bad.items[0].include and "size must be a number" in bad.items[0].problems[0]


def test_run_writes_output_sidecar_and_entries(setup):
    s, conn = setup, setup["conn"]
    req_id = queue_plan(conn, plan(s, params={"size": 8}), s["registry"])
    assert run(s) == [req_id]
    d = lifecycle.detail(conn, req_id)
    assert d["state"] == "fulfilled", d
    out = Path(d["endpoint"]["folder"]) / "Stamped" / "Barrel01"
    assert sorted(p.name for p in out.rglob("*") if p.is_file()) == ["Barrel01.fbx", "Barrel01_N.png", "NOTE.txt"]
    from PIL import Image
    assert max(Image.open(out / "Barrel01_N.png").size) == 8  # shrunk, laid out as in its container
    assert (out / "NOTE.txt").read_text(encoding="utf-8") == "stamped Barrel01"
    sidecar = json.loads((Path(d["endpoint"]["folder"]) / ".exchange" / f"{d['uid']}.json").read_text(encoding="utf-8"))
    assert sidecar["outputs"][0]["dossier"] == s["barrel"] and len(sidecar["outputs"][0]["files"]) == 3

    # After the rescan the output is an entry of Barrel01 itself, requisitioned from its origin.
    entries = entries_of(conn, s["barrel"])
    made = [e for e in entries if e["status"] == "requisitioned"]
    assert len(made) == 1 and made[0]["requisition_id"] == req_id and made[0]["source_entry_id"] == entries[0]["id"]
    assert conn.execute("SELECT count(*) FROM dossier WHERE name = 'NOTE'").fetchone()[0] == 0  # no new dossiers
    from exchange.requisitions.runner import work_dir
    assert not work_dir(d["uid"]).exists()  # intermediates go once it is fulfilled


def test_collisions_resume_and_remove(setup):
    s, conn = setup, setup["conn"]
    first = queue_plan(conn, plan(s, params={"note": "first"}), s["registry"])
    run(s)
    second = queue_plan(conn, plan(s, params={"note": "second"}), s["registry"])
    run(s)
    d = lifecycle.detail(conn, second)
    assert d["state"] == "needs_attention" and "already exist" in d["message"]
    note = Path(lifecycle.detail(conn, first)["endpoint"]["folder"]) / "Stamped" / "Barrel01" / "NOTE.txt"
    assert note.read_text(encoding="utf-8") == "first Barrel01"  # nothing written yet
    lifecycle.resume(conn, second, on_collision="overwrite")
    run(s)
    d = lifecycle.detail(conn, second)
    assert d["state"] == "fulfilled" and note.read_text(encoding="utf-8") == "second Barrel01"
    overwritten = [w for w in d["writes"] if w["action"] == "overwritten"]
    assert overwritten and all(Path(w["recycled_to"]).exists() for w in overwritten)

    # Removing the second puts the first's files back; its entry retires.
    lifecycle.remove(conn, s["db"], s["definitions"], second)
    assert note.read_text(encoding="utf-8") == "first Barrel01"
    assert lifecycle.detail(conn, second)["state"] == "removed"
    statuses = {e["requisition_id"]: e["status"] for e in entries_of(conn, s["barrel"]) if e["requisition_id"]}
    assert statuses == {first: "requisitioned", second: "retired"}  # its entry stays as history
    lifecycle.remove(conn, s["db"], s["definitions"], first)
    assert not note.exists()
    assert {e["status"] for e in entries_of(conn, s["barrel"]) if e["requisition_id"]} == {"retired"}


def test_checkpoints_and_cached_steps(setup):
    s, conn = setup, setup["conn"]
    req_id = queue_plan(conn, plan(s, params={"review": True}), s["registry"])
    run(s)
    d = lifecycle.detail(conn, req_id)
    assert d["state"] == "needs_attention" and "look at the shrunken images" in d["message"]
    lifecycle.resume(conn, req_id)
    run(s)
    assert lifecycle.detail(conn, req_id)["state"] == "fulfilled"
    from exchange.requisitions.runner import log_path
    log = log_path(d["uid"], d["items"][0]["id"]).read_text(encoding="utf-8")
    assert "waiting for you" in log and "[review] reviewed" in log


def test_stale_and_rebuild(setup, scan):
    s, conn = setup, setup["conn"]
    req_id = queue_plan(conn, plan(s), s["registry"])
    run(s)
    assert lifecycle.check_stale(conn, s["registry"]) == []
    write(s["folder"] / "Downloads" / "barrel" / "Barrel01_N.png", png_bytes((70, 30), color=(200, 10, 10)))
    scan(s["folder"])
    [(stale_id, why)] = lifecycle.check_stale(conn, s["registry"])
    assert stale_id == req_id and "source of Barrel01 changed" in why
    assert {e["status"] for e in entries_of(conn, s["barrel"]) if e["requisition_id"] == req_id} == {"stale"}
    scan(s["folder"])  # rescans keep it stale
    assert {e["status"] for e in entries_of(conn, s["barrel"]) if e["requisition_id"] == req_id} == {"stale"}

    new_id = lifecycle.rebuild(conn, s["registry"], req_id)
    run(s)
    assert lifecycle.detail(conn, req_id)["state"] == "replaced"
    assert lifecycle.detail(conn, new_id)["state"] == "fulfilled"
    live = [e for e in entries_of(conn, s["barrel"]) if e["requisition_id"] and e["status"] != "retired"]
    assert [e["requisition_id"] for e in live] == [new_id]


def test_copy_route_and_failures(setup):
    s, conn = setup, setup["conn"]
    p = plan_requisition(conn, s["definitions"], s["registry"], s["barrel"], s["env"], processes=["copy_entry"])
    req_id = queue_plan(conn, p, s["registry"])
    run(s)
    assert lifecycle.detail(conn, req_id)["state"] == "fulfilled"
    copied = [e for e in entries_of(conn, s["barrel"]) if e["status"] == "copied"]
    assert len(copied) == 1

    # A source that vanished fails the item, with the reason; nothing is written.
    req_id = queue_plan(conn, plan(s, on_collision="rename"), s["registry"])
    (s["folder"] / "Downloads" / "barrel" / "Barrel01.fbx").unlink()
    run(s)
    d = lifecycle.detail(conn, req_id)
    assert d["state"] == "failed" and "source file missing" in d["items"][0]["message"]


def test_one_worker_and_the_test_harness(setup, tmp_path):
    s = setup
    with Lock("queue"):
        with pytest.raises(LockBusy):
            run(s)
    written = harness(s["conn"], STAMP, s["barrel"], tmp_path / "harness", {"size": 4})
    assert sorted(p.name for p in written) == ["Barrel01.fbx", "Barrel01_N.png", "NOTE.txt"]
    assert not list((s["folder"]).rglob("NOTE.txt"))  # the environment was not touched


def test_lost_library_is_rebuilt_from_sidecars(setup, scan, tmp_path, definitions):
    s, conn = setup, setup["conn"]
    queue_plan(conn, plan(s), s["registry"])
    run(s)
    fresh = tmp_path / "fresh" / "library.db"
    from exchange.scanner.scan import run_scan
    run_scan(s["folder"], db_path=fresh, definitions=definitions)
    again = sqlite3.connect(fresh)
    rows = again.execute("SELECT d.uid, e.status FROM entry e JOIN ledger l ON l.id = e.ledger_id"
                         " JOIN dossier d ON d.id = l.dossier_id WHERE e.status = 'requisitioned'").fetchall()
    assert rows == [(s["barrel"], "requisitioned")]  # the output's asset, by its original uid


def test_presets_and_lenient_defaults(setup, capsys):
    s = setup
    # A preset or last-used value the process no longer takes is dropped, not an error.
    p = plan(s, defaults={"stamp_images.size": "big", "stamp_images.gone": 1, "stamp_images.note": "kept"},
             params={"stamp_images.review": True})
    assert p.items[0].include and p.items[0].params["stamp_images"] == {"size": 16, "review": True, "note": "kept"}

    db = str(s["db"])
    assert main(["requisition", "plan", s["barrel"][:10], "--env", str(s["env"]), "--process", "stamp_images",
                 "--param", "size=5", "--save-preset", "Five", "--db", db]) == 0
    capsys.readouterr()
    assert main(["presets", "list", "--db", db]) == 0
    assert "Five  (stamp_images)" in capsys.readouterr().out
    assert main(["requisition", "plan", s["barrel"][:10], "--env", str(s["env"]), "--process", "stamp_images",
                 "--preset", "Five", "--param", "note=hi", "--db", db, "--json"]) == 0
    item = json.loads(capsys.readouterr().out)["items"][0]
    assert item["params"]["stamp_images"] == {"size": 5, "review": False, "note": "hi"}
    assert main(["presets", "delete", "Five", "--db", db]) == 0
    assert main(["requisition", "plan", s["barrel"][:10], "--env", str(s["env"]), "--preset", "Five", "--db", db]) == 2


def test_cli(setup, capsys):
    s = setup
    db = str(s["db"])
    assert main(["processes", "list", "--db", db]) == 0
    assert "stamp_images" in capsys.readouterr().out
    assert main(["requisition", "plan", s["barrel"][:10], "--env", str(s["env"]), "--process", "stamp_images",
                 "--param", "size=8", "--queue", "--db", db]) == 0
    out = capsys.readouterr().out
    assert "[x] Barrel01" in out and "Queued as requisition" in out
    assert main(["requisition", "run", "--db", db, "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["ran"][0]["state"] == "fulfilled"
    assert main(["requisition", "list", "--db", db]) == 0
    assert "fulfilled" in capsys.readouterr().out
    assert main(["requisition", "plan", s["barrel"][:10], "--env", str(s["env"]), "--process", "nope", "--db", db]) == 0
    assert "does not take it there" in capsys.readouterr().out
