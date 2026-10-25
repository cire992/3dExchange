"""The service's jobs API, part 2 (Roadmap phase 6g): process packages, tools and presets,
endpoints, planning and queueing requisitions, the queue's actions, and running it (and removing
output) as jobs."""

import json
import sqlite3
import time
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from builders import copy_fixture, png_bytes, write  # noqa: E402
from exchange.curation import Curator  # noqa: E402
from exchange.definitions import load_definitions  # noqa: E402
from exchange.requisitions.endpoints import configured_folder  # noqa: E402
from exchange.service.app import create_app  # noqa: E402

TOKEN = "test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
V1 = "/api/v1"
STAMP = Path(__file__).parent / "fixtures" / "processes" / "stamp_images"


@pytest.fixture
def setup(scan, tmp_path, library, definitions, db_path):
    """A loose-files library whose Barrel01 mesh has a texture linked onto it, and a client."""
    folder = copy_fixture("loose_files", tmp_path / "scan" / "Loose")
    write(folder / "Downloads" / "barrel" / "Barrel01_N.png", png_bytes((64, 32)))
    scan(folder)
    conn = library()
    root = conn.execute("SELECT id, environment_id FROM environment_root").fetchone()
    barrel = conn.execute("SELECT uid FROM dossier WHERE name = 'Barrel01'").fetchone()[0]
    Curator(conn, definitions).link_files(barrel, [(root["id"], "downloads/barrel/barrel01_n.png")])
    app = create_app(db_path, token=TOKEN, definitions=load_definitions(include_user_dir=False), watch=False)
    client = TestClient(app, base_url="http://127.0.0.1", headers=AUTH)
    yield {"client": client, "env": root["environment_id"], "barrel": barrel, "folder": folder, "db": db_path,
           "tmp": tmp_path}
    app.state.library.close()


def ok(response):
    assert response.status_code == 200, response.text
    return response.json()


def finish(client, job, timeout=120):
    deadline = time.monotonic() + timeout
    while job["state"] == "running":
        assert time.monotonic() < deadline, job
        job = ok(client.get(f"{V1}/jobs/{job['id']}", params={"since": job["version"], "wait": 10}))
    return job


def processes(client):
    return {p["id"]: p for p in ok(client.get(f"{V1}/processes"))["processes"]}


def installed(client):
    """The test process, installed and trusted through the API."""
    package = ok(client.post(f"{V1}/processes/install", json={"folder": str(STAMP)}))
    assert package["state"] == "not trusted" and package["trusted"] is False
    assert any(line.startswith("Writes to:") for line in package["trust"])
    trusted = ok(client.post(f"{V1}/processes/stamp_images/trust"))
    assert trusted["state"] == "ready"
    return trusted


def test_requisition_routes_need_the_token(setup):
    client = setup["client"]
    for path in ("/processes", "/presets", "/endpoints", "/requisitions", "/tools"):
        assert client.get(V1 + path, headers={"Authorization": "Bearer wrong"}).status_code == 401, path
    assert client.post(f"{V1}/requisitions/plan", json={}, headers={"Authorization": ""}).status_code == 401


def test_processes_tools_and_presets(setup, tmp_path):
    client = setup["client"]
    found = processes(client)
    assert found["copy_entry"]["builtin"] and found["copy_entry"]["state"] == "ready"
    assert "stamp_images" not in found
    stamp = installed(client)
    assert [p["id"] for p in stamp["parameters"]] == ["size", "review", "note"]
    size = stamp["parameters"][0]
    assert size["type"] == "int" and size["label"] and size["default"] is not None
    assert client.post(f"{V1}/processes/install", json={"folder": str(tmp_path / "nope")}).status_code == 400
    assert client.post(f"{V1}/processes/nope/trust").status_code == 404

    # Tools: a path must be a file; null forgets it.
    assert client.post(f"{V1}/tools", json={"tool": "faketool", "path": str(tmp_path / "none.exe")}).status_code == 400
    tool = write(tmp_path / "faketool.exe", b"MZ")
    assert ok(client.post(f"{V1}/tools", json={"tool": "faketool", "path": str(tool)})) == {"faketool": str(tool)}
    assert ok(client.post(f"{V1}/tools", json={"tool": "faketool", "path": None})) == {}

    # Presets: saved, listed, deleted.
    saved = ok(client.post(f"{V1}/presets", json={"name": "Tiny", "options": {"stamp_images": {"size": 4}},
                                                  "environment": "loose_files"}))
    assert saved == {"name": "Tiny", "description": "", "environment": "loose_files", "shipped": False,
                     "processes": ["stamp_images"], "options": {"stamp_images": {"size": 4}}}
    assert [p["name"] for p in ok(client.get(f"{V1}/presets"))] == ["Tiny"]
    assert client.post(f"{V1}/presets", json={"name": " ", "options": {}}).status_code == 409
    assert ok(client.delete(f"{V1}/presets/Tiny")) == []
    assert client.delete(f"{V1}/presets/Tiny").status_code == 404


def test_endpoints(setup, db_path):
    client, env = setup["client"], setup["env"]
    [row] = ok(client.get(f"{V1}/endpoints"))
    assert row["environment_id"] == env and row["custom"] is False and row["folder"].endswith("Exchange Conversions")
    assert row["visibility"] == "personal" and row["problem"] is None
    target = setup["tmp"] / "Out"
    ok(client.post(f"{V1}/environments/{env}/config", json={"endpoint": str(target), "visibility": "publishable"}))
    [row] = ok(client.get(f"{V1}/endpoints"))
    assert row["custom"] is True and row["folder"] == str(target.resolve()) and row["visibility"] == "publishable"
    # The window's wizard wrote {"mode", "value"}: endpoints read it too (it used to fail).
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE environment SET user_config = ? WHERE id = ?",
                     (json.dumps({"endpoint": {"mode": "content_folder", "value": "Content/Exchange"}}), env))
    [row] = ok(client.get(f"{V1}/endpoints"))
    assert Path(row["folder"]) == (setup["folder"] / "Content" / "Exchange").resolve()


def test_wizard_endpoint_settings(tmp_path):
    first = tmp_path / "MO2"
    assert configured_folder({"mode": "new_container", "value": "Exchange – {dossier}"}, "mo2", first, {}) is None
    assert configured_folder({"mode": "managed_container", "value": "Exchange Output"}, "mo2", first,
                             {"mods_dir": "mods"}) == first / "mods" / "Exchange Output"
    assert configured_folder({"mode": "content_directory", "value": str(tmp_path / "Conv")}, "daz", first, {}) == tmp_path / "Conv"
    assert configured_folder({"mode": "content_folder", "value": "Content/Exchange"}, "unreal", first, {}) == first / "Content" / "Exchange"
    assert configured_folder(str(tmp_path / "Out"), "folder", first, {}) == tmp_path / "Out"
    assert configured_folder(None, "folder", first, {}) is None and configured_folder("", "folder", first, {}) is None


def test_plan_queue_run_and_remove(setup):
    client, env, barrel = setup["client"], setup["env"], setup["barrel"]
    installed(client)
    chains = ok(client.post(f"{V1}/requisitions/routes", json={"uids": [barrel], "environment": env}))
    assert {(("copy_entry",), "copy"), (("stamp_images",), "convert")} <= {(tuple(c["processes"]), c["route"]) for c in chains}
    assert any(c["label"].startswith("Copy: ") for c in chains)

    request = {"uids": [barrel], "environment": env, "processes": ["stamp_images"],
               "options": {"stamp_images": {"size": 8, "note": "hello"}}}
    planned = ok(client.post(f"{V1}/requisitions/plan", json=request))
    [plan] = planned["plans"]
    [item] = plan["items"]
    assert item["route"] == "convert" and item["process_names"] and item["include"]
    assert item["params"]["stamp_images"] == {"size": 8, "review": False, "note": "hello"}
    assert plan["endpoint"]["folder"].endswith("Exchange Conversions") and planned["included"] == 1
    [form] = planned["forms"]
    assert form["process"] == "stamp_images" and form["values"]["size"] == 8 and len(form["parameters"]) == 3
    # A bad option value is the item's problem; an excluded item is left out.
    bad = ok(client.post(f"{V1}/requisitions/plan", json={**request, "options": {"stamp_images": {"size": "big"}}}))
    assert bad["plans"][0]["items"][0]["problems"] and bad["included"] == 0
    assert ok(client.post(f"{V1}/requisitions/plan", json={**request, "excluded": [barrel]}))["included"] == 0
    assert client.post(f"{V1}/requisitions/queue", json={**request, "excluded": [barrel]}).status_code == 409
    assert client.post(f"{V1}/requisitions/plan", json={**request, "environment": 99}).status_code == 404
    assert client.post(f"{V1}/requisitions/plan", json={**request, "preset": "nope"}).status_code == 404
    unknown = ok(client.post(f"{V1}/requisitions/plan", json={**request, "uids": ["no-such-uid"]}))
    assert unknown["plans"] == [] and "no dossier" in unknown["problems"][0]

    # Queue it: the options become the last used; a second one queues behind it.
    [first] = ok(client.post(f"{V1}/requisitions/queue", json=request))["ids"]
    assert ok(client.get(f"{V1}/presets/last-used"))["stamp_images"]["note"] == "hello"
    [second] = ok(client.post(f"{V1}/requisitions/queue", json={**request, "on_collision": "skip"}))["ids"]
    rows = ok(client.get(f"{V1}/requisitions"))
    assert [(r["id"], r["state"]) for r in rows] == [(first, "queued"), (second, "queued")]
    assert ok(client.post(f"{V1}/requisitions/{second}/move", json={"position": 1}))["position"] < \
        ok(client.get(f"{V1}/requisitions/{first}"))["position"]
    assert ok(client.post(f"{V1}/requisitions/{second}/hold", json={"held": True}))["state"] == "held"
    assert client.get(f"{V1}/requisitions/999").status_code == 404
    assert client.post(f"{V1}/requisitions/999/hold", json={}).status_code == 404

    # Run the queue as a job: the held one waits.
    job = finish(client, ok(client.post(f"{V1}/jobs/requisitions", json={})))
    assert job["state"] == "done" and job["kind"] == "requisitions", job
    assert [r["id"] for r in job["result"]["ran"]] == [first]
    done = ok(client.get(f"{V1}/requisitions/{first}"))
    assert done["state"] == "fulfilled" and any(w["action"] == "created" for w in done["writes"])
    note = Path(done["endpoint"]["folder"]) / "Stamped" / "Barrel01" / "NOTE.txt"
    assert note.read_text(encoding="utf-8") == "hello Barrel01"
    assert ok(client.post(f"{V1}/requisitions/{second}/hold", json={"held": False}))["state"] == "queued"

    # Stale after the process changes; rebuild queues it again.
    assert ok(client.post(f"{V1}/requisitions/check-stale")) == []
    rebuilt = ok(client.post(f"{V1}/requisitions/{first}/rebuild"))
    assert rebuilt["replaces"] == first and rebuilt["state"] == "queued"
    assert ok(client.get(f"{V1}/requisitions/{first}"))["state"] == "replaced"

    # Removing output is a job too (it rescans).
    finish(client, ok(client.post(f"{V1}/jobs/requisitions", json={"ids": [rebuilt["id"]]})))
    assert ok(client.get(f"{V1}/requisitions/{rebuilt['id']}"))["state"] == "fulfilled"
    removed = finish(client, ok(client.post(f"{V1}/jobs/remove-output", json={"requisition": rebuilt["id"]})))
    assert removed["state"] == "done", removed
    # What the rebuild overwrote (the first run's files) is put back.
    assert ok(client.get(f"{V1}/requisitions/{rebuilt['id']}"))["state"] == "removed"
    assert note.read_text(encoding="utf-8") == "hello Barrel01"
    assert client.post(f"{V1}/jobs/remove-output", json={"requisition": 999}).status_code == 404


def test_checkpoint_and_resume(setup):
    client, env, barrel = setup["client"], setup["env"], setup["barrel"]
    installed(client)
    request = {"uids": [barrel], "environment": env, "processes": ["stamp_images"],
               "options": {"stamp_images": {"review": True}}}
    [rid] = ok(client.post(f"{V1}/requisitions/queue", json=request))["ids"]
    finish(client, ok(client.post(f"{V1}/jobs/requisitions", json={"ids": [rid]})))
    waiting = ok(client.get(f"{V1}/requisitions/{rid}"))
    assert waiting["state"] == "needs_attention" and "look at the shrunken images" in waiting["message"]
    assert ok(client.post(f"{V1}/requisitions/{rid}/resume", json={"on_collision": "overwrite"}))["state"] == "queued"
    finish(client, ok(client.post(f"{V1}/jobs/requisitions", json={})))
    assert ok(client.get(f"{V1}/requisitions/{rid}"))["state"] == "fulfilled"


def test_queue_actions_wait_while_a_job_writes(setup, monkeypatch):
    import sys

    from exchange.service import jobs as jobs_module

    client, env, barrel = setup["client"], setup["env"], setup["barrel"]
    installed(client)
    [rid] = ok(client.post(f"{V1}/requisitions/queue", json={"uids": [barrel], "environment": env,
                                                             "processes": ["stamp_images"]}))["ids"]
    monkeypatch.setattr(jobs_module.Jobs, "command",
                        lambda self, args, json_output: [sys.executable, "-c", "import time; time.sleep(60)"])
    job = ok(client.post(f"{V1}/jobs/requisitions", json={}))
    for path, body in ((f"/requisitions/{rid}/hold", {}), (f"/requisitions/{rid}/move", {"position": 1}),
                       ("/requisitions/check-stale", None), ("/requisitions/queue",
                                                             {"uids": [barrel], "environment": env})):
        assert client.post(V1 + path, json=body).status_code == 409, path
    stopped = finish(client, ok(client.post(f"{V1}/jobs/{job['id']}/stop")))
    assert stopped["error"] == "Stopped; the requisition that was running is queued again."
