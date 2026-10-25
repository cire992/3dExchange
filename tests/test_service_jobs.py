"""The service's jobs API, part 1 (Roadmap phase 6g): detecting, registering and scanning
environments in worker processes, following a job by version, one writing job at a time,
stopping, classification, environment settings and change notices."""

import sqlite3
import sys
import time

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from exchange.autodiscover import Found  # noqa: E402
from exchange.definitions import load_definitions  # noqa: E402
from exchange.service import jobs as jobs_module  # noqa: E402
from exchange.service.app import create_app  # noqa: E402
from exchange.service.watch import Observer  # noqa: E402

TOKEN = "test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
V1 = "/api/v1"

# A stand-in worker: progress lines, then it waits to be stopped (or exits as told).
SLOW = """
import json, sys, time
print(json.dumps({"event": "progress", "phase": 1, "environment": "Fake", "step": "discovery", "done": 1, "total": 4}), flush=True)
time.sleep(0.3)
print(json.dumps({"event": "progress", "phase": 1, "environment": "Fake", "step": "discovery", "done": 2, "total": 4}), flush=True)
time.sleep(60)
"""
FAILING = "import sys; print('exchange: error: the folder went away', file=sys.stderr); sys.exit(2)"


@pytest.fixture
def make_client(db_path):
    made = []

    def make(**kwargs):
        app = create_app(db_path, token=TOKEN, definitions=load_definitions(include_user_dir=False), **kwargs)
        made.append(app)
        return TestClient(app, base_url="http://127.0.0.1", headers=AUTH)

    yield make
    for app in made:
        app.state.library.close()


@pytest.fixture
def client(make_client):
    return make_client()


def ok(response):
    assert response.status_code == 200, response.text
    return response.json()


def finish(client, job, timeout=120):
    """Follow a job by version until it ends."""
    deadline = time.monotonic() + timeout
    while job["state"] == "running":
        assert time.monotonic() < deadline, job
        job = ok(client.get(f"{V1}/jobs/{job['id']}", params={"since": job["version"], "wait": 10}))
    return job


def environments(db_path):
    with sqlite3.connect(db_path) as conn:
        return conn.execute("SELECT id, name, type_id, user_config FROM environment ORDER BY id").fetchall()


def test_jobs_need_the_token(client):
    for path in ("/jobs", "/jobs/1", "/changes", "/environment-types", "/environments/discover"):
        assert client.get(V1 + path, headers={"Authorization": "Bearer wrong"}).status_code == 401, path
    assert client.post(f"{V1}/jobs/rescan", json={}, headers={"Authorization": ""}).status_code == 401


def test_detect_then_register_then_rescan(client, mixed, db_path):
    # Detection lists the environments in a folder and writes nothing.
    detected = finish(client, ok(client.post(f"{V1}/jobs/detect", json={"folder": str(mixed)})))
    assert detected["state"] == "done" and detected["writes"] is False, detected
    report = detected["report"]
    assert report["dry_run"] is True
    found = {root["path"]: env["type_id"] for env in report["environments"] for root in env["roots"]}
    assert {"daz_studio", "skyrim_se"} <= set(found.values()), found
    assert environments(db_path) == []

    # Register the Daz library and the loose files, never the MO2 instance (the wizard's untick).
    daz = next(p for p, t in found.items() if t == "daz_studio")
    mo2 = next(p for p, t in found.items() if t == "skyrim_se")
    plans = [{"type_id": "daz_studio", "name": "My Daz", "roots": [{"path": daz, "confidence": 0.9}],
              "config": {"visibility": "personal", "ignore": ["*.bak"]}},
             {"type_id": "loose_files", "roots": [{"path": str(mixed / "Loose")}]}]
    made = ok(client.post(f"{V1}/environments/register", json={"environments": plans, "exclude": [mo2]}))["environments"]
    assert [e["name"] for e in made][0] == "My Daz" and [e["type_id"] for e in made] == ["daz_studio", "loose_files"]
    daz_env = ok(client.get(f"{V1}/environments/{made[0]['id']}"))
    assert daz_env["user_config"] == {"visibility": "personal", "ignore": ["*.bak"]}
    assert [r["path"] for r in daz_env["roots"]] == [daz]

    # Rescan them: progress arrives while it runs; the sidebar counts what it found.
    job = ok(client.post(f"{V1}/jobs/rescan", json={"environments": [e["id"] for e in made]}))
    assert job["kind"] == "rescan" and job["writes"] and job["label"] == f"Rescanning My Daz, {made[1]['name']}"
    seen = set()
    while job["state"] == "running":
        job = ok(client.get(f"{V1}/jobs/{job['id']}", params={"since": job["version"], "wait": 10}))
        if job["progress"]:
            seen.add(job["progress"]["phase"])
    assert job["state"] == "done", job
    assert seen, "no progress arrived"
    assert {e["id"] for e in job["report"]["environments"]} == {e["id"] for e in made}
    sidebar = ok(client.get(f"{V1}/sidebar"))
    assert sidebar["all"] > 0 and {e["name"] for e in sidebar["environments"]} == {"My Daz", made[1]["name"]}
    listed = ok(client.get(f"{V1}/jobs"))
    assert [j["kind"] for j in listed["jobs"]] == ["rescan", "detect"] and listed["jobs"][0]["report"] is None


def test_scan_a_folder_and_classify(client, loose_folder, db_path):
    job = finish(client, ok(client.post(f"{V1}/jobs/scan", json={"folder": str(loose_folder)})))
    assert job["state"] == "done", job
    assert [e["type_id"] for e in job["report"]["environments"]] == ["loose_files"]
    assert len(environments(db_path)) == 1
    classified = finish(client, ok(client.post(f"{V1}/jobs/classify", json={})))
    assert classified["state"] == "done", classified
    assert classified["result"]["classification"]["dossiers"] > 0 and "suggestions" in classified["result"]


def test_bad_requests(client, tmp_path):
    assert client.post(f"{V1}/jobs/scan", json={"folder": str(tmp_path / "nope")}).status_code == 400
    assert client.post(f"{V1}/jobs/detect", json={"folder": "relative/folder"}).status_code == 400
    assert client.post(f"{V1}/jobs/rescan", json={"environments": [42]}).status_code == 404
    assert client.get(f"{V1}/jobs/999").status_code == 404
    assert client.post(f"{V1}/jobs/999/stop").status_code == 404
    plan = {"type_id": "no_such_type", "roots": [{"path": str(tmp_path)}]}
    assert client.post(f"{V1}/environments/register", json={"environments": [plan]}).status_code == 400
    plan = {"type_id": "loose_files", "roots": [{"path": str(tmp_path)}], "config": {"visibility": "everyone"}}
    assert client.post(f"{V1}/environments/register", json={"environments": [plan]}).status_code == 400
    plan = {"type_id": "loose_files", "roots": [{"path": str(tmp_path)}], "config": {"colour": "red"}}
    assert client.post(f"{V1}/environments/register", json={"environments": [plan]}).status_code == 422


def test_one_writing_job_at_a_time_and_stopping(client, monkeypatch, mixed, tmp_path):
    monkeypatch.setattr(jobs_module.Jobs, "command", lambda self, args, json_output: [sys.executable, "-c", SLOW])
    job = ok(client.post(f"{V1}/jobs/rescan", json={}))
    assert job["label"] == "Rescanning every environment"
    job = ok(client.get(f"{V1}/jobs/{job['id']}", params={"since": job["version"], "wait": 10}))
    assert job["progress"] == {"phase": 1, "environment": "Fake", "step": "discovery", "done": 1, "total": 4}
    job = ok(client.get(f"{V1}/jobs/{job['id']}", params={"since": job["version"], "wait": 10}))
    assert job["progress"]["done"] == 2

    # Another writer waits; detection (read-only) may run beside it; so may reading.
    refused = client.post(f"{V1}/jobs/scan", json={"folder": str(mixed)})
    assert refused.status_code == 409 and "Rescanning every environment is running" in refused.json()["detail"]
    assert client.post(f"{V1}/jobs/classify", json={"regroup": True}).status_code == 409
    plan = {"type_id": "loose_files", "roots": [{"path": str(tmp_path)}]}
    assert client.post(f"{V1}/environments/register", json={"environments": [plan]}).status_code == 409
    beside = ok(client.post(f"{V1}/jobs/detect", json={"folder": str(mixed)}))
    assert beside["state"] == "running"

    # Waiting without a change returns after the wait, unchanged.
    started = time.monotonic()
    same = ok(client.get(f"{V1}/jobs/{job['id']}", params={"since": job["version"], "wait": 0.5}))
    assert same["version"] == job["version"] and time.monotonic() - started >= 0.4

    stopped = finish(client, ok(client.post(f"{V1}/jobs/{job['id']}/stop")))
    assert stopped["state"] == "stopped" and stopped["error"] == "Stopped; everything finished before that is saved."
    finish(client, ok(client.post(f"{V1}/jobs/{beside['id']}/stop")))
    again = ok(client.post(f"{V1}/jobs/rescan", json={}))  # the writer's place is free again
    finish(client, ok(client.post(f"{V1}/jobs/{again['id']}/stop")))


def test_a_failing_job_says_why(client, monkeypatch, loose_folder):
    monkeypatch.setattr(jobs_module.Jobs, "command", lambda self, args, json_output: [sys.executable, "-c", FAILING])
    job = finish(client, ok(client.post(f"{V1}/jobs/scan", json={"folder": str(loose_folder)})))
    assert job["state"] == "failed" and job["error"] == "the folder went away"


def test_closing_the_service_stops_its_jobs(make_client, monkeypatch):
    monkeypatch.setattr(jobs_module.Jobs, "command", lambda self, args, json_output: [sys.executable, "-c", SLOW])
    client = make_client()
    job = ok(client.post(f"{V1}/jobs/rescan", json={}))
    library = client.app.state.library
    process = library.jobs.get(job["id"]).process
    library.jobs.close()
    assert process.poll() is not None
    assert client.post(f"{V1}/jobs/rescan", json={}).status_code == 503


def test_environment_settings(client, scan, loose_folder, mixed, db_path):
    scan(mixed)
    by_type = {t: i for i, _, t, _ in environments(db_path)}
    env_id = by_type["loose_files"]
    config = ok(client.post(f"{V1}/environments/{env_id}/config", json={"ignore": ["*.tmp"], "visibility": "publishable",
                                                                        "endpoint": str(loose_folder)}))
    assert config["user_config"] == {"ignore": ["*.tmp"], "visibility": "publishable", "endpoint": str(loose_folder)}
    # Only the fields given change; null (or an empty list) removes one.
    config = ok(client.post(f"{V1}/environments/{env_id}/config", json={"endpoint": None, "ignore": []}))
    assert config["user_config"] == {"visibility": "publishable"}
    assert client.post(f"{V1}/environments/{env_id}/config", json={"visibility": "everyone"}).status_code == 400
    assert client.post(f"{V1}/environments/999/config", json={}).status_code == 404
    mo2 = by_type["skyrim_se"]
    assert client.post(f"{V1}/environments/{mo2}/config", json={"mo2_profile": "Nope"}).status_code == 400
    assert ok(client.post(f"{V1}/environments/{mo2}/config", json={"mo2_profile": "Default"}))["user_config"]["mo2_profile"] == "Default"
    assert ok(client.get(f"{V1}/environments/mo2-profiles", params={"folder": str(mixed / "MO2")})) == {
        "profiles": ["Default"], "selected": "Default"}
    assert ok(client.get(f"{V1}/environments/{mo2}"))["layer_config"]["profiles"] == ["Default"]
    assert client.get(f"{V1}/environments/999").status_code == 404


def test_environment_types_and_discovery(client, monkeypatch, tmp_path):
    types = {t["id"]: t for t in ok(client.get(f"{V1}/environment-types"))}
    assert types["daz_studio"]["handler"] == "daz" and types["daz_studio"]["multi_root"] is True
    assert types["loose_files"]["fallback"] is True and types["skyrim_se"]["handler"] == "mo2"
    found = Found(path=str(tmp_path), name="Starfield", via="Steam", type_id="starfield", confidence=0.9, signals=["exe"])
    monkeypatch.setattr(jobs_module, "discover_sources", lambda definitions, registered_roots=(): [found])
    assert ok(client.get(f"{V1}/environments/discover")) == [{
        "path": str(tmp_path), "name": "Starfield", "via": "Steam", "type_id": "starfield", "confidence": 0.9,
        "signals": ["exe"], "registered": False}]

    def broken(*args, **kwargs):
        raise OSError("registry unreadable")
    monkeypatch.setattr(jobs_module, "discover_sources", broken)
    assert ok(client.get(f"{V1}/environments/discover")) == []


@pytest.mark.skipif(Observer is None, reason="needs watchdog")
def test_change_notices(make_client, scan, loose_folder, db_path):
    scan(loose_folder)
    client = make_client()
    env_id = environments(db_path)[0][0]
    state = ok(client.get(f"{V1}/changes"))
    assert state["available"] is True and state["environments"] == []
    (loose_folder / "new_crate.obj").write_text("v 0 0 0\n")
    changed = ok(client.get(f"{V1}/changes", params={"since": state["version"], "wait": 10}))
    assert changed["environments"] == [env_id]
    # A rescan of it clears the notice.
    finish(client, ok(client.post(f"{V1}/jobs/rescan", json={"environments": [env_id]})))
    cleared = ok(client.get(f"{V1}/changes"))
    assert cleared["environments"] == [] and cleared["version"] > changed["version"]
