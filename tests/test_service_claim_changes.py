"""R4b: the claims change notices: the version, waiting on it, and the claims folder's watcher."""

import os
import sys
import threading
import time

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from exchange import claims  # noqa: E402
from exchange.processes.registry import install, trust  # noqa: E402
from exchange.service import jobs as jobs_module  # noqa: E402
from exchange.service import watch  # noqa: E402
from exchange.service.app import create_app  # noqa: E402
from test_claim_paths import PROCESSES, world  # noqa: E402,F401  (the fixture)
from test_service_claims import AUTH, TOKEN, V1, api, ok, request  # noqa: E402,F401  (the fixture)
from test_service_jobs import FAILING  # noqa: E402
from test_service_requisitions import finish  # noqa: E402

QUICK = "pass"


def changes(client, **params):
    return ok(client.get(f"{V1}/claims/changes", params=params))


def version(client):
    return changes(client)["version"]


def grew(client, since, wait=10):
    """The version once it differs from ``since`` (the wait ends at once when it already does)."""
    return changes(client, since=since, wait=wait)["version"]


def use_stamp(api):
    trust(install(PROCESSES / "stamp_images"))
    registry = api["app"].state.library.processes.registry(reload=True)
    registry.packages.pop("convert_mesh", None)


def barrel(api):
    return ok(api["client"].post(f"{V1}/claims", json={"uid": api["barrel"], "environment": api["loose"]}))


def test_the_changes_route_is_not_a_claim_called_changes(api):
    result = changes(api["client"])
    assert set(result) == {"available", "version"} and result["available"] is False


def test_the_service_bumps_the_version_for_making_closing_and_walking(api):
    client = api["client"]
    use_stamp(api)
    v = version(client)
    claim = barrel(api)
    assert version(client) > v
    v = version(client)
    ok(client.post(f"{V1}/claims/{claim['id']}/walk", json={"run": False}))
    assert version(client) > v
    v = version(client)
    ok(client.post(f"{V1}/claims/{claim['id']}/close"))
    assert version(client) > v


def test_a_job_that_ends_bumps_the_version_done_or_failed(api, monkeypatch):
    client = api["client"]
    for script, state in ((QUICK, "done"), (FAILING, "failed")):
        monkeypatch.setattr(jobs_module.Jobs, "command", lambda self, args, json_output, s=script: [sys.executable, "-c", s])
        v = version(client)
        job = finish(client, ok(client.post(f"{V1}/jobs/rescan", json={})))
        assert job["state"] == state
        assert grew(client, v) > v


def test_refusals_plans_and_previews_do_not_bump(api):
    client = api["client"]
    use_stamp(api)
    closed, other = barrel(api), barrel(api)
    ok(client.post(f"{V1}/claims/{closed['id']}/close"))
    v = version(client)
    assert client.post(f"{V1}/claims", json=request(api) | {"uid": "no-such-thing"}).status_code == 404
    assert client.post(f"{V1}/claims/nope/close").status_code == 404
    assert client.post(f"{V1}/claims/{closed['id']}/walk", json={}).status_code == 409
    assert client.post(f"{V1}/claims/nope/walk", json={}).status_code == 404
    assert client.post(f"{V1}/claims/{other['id']}/plan", json={}).status_code == 200
    assert client.post(f"{V1}/claims/preview", json=request(api)).status_code == 200
    ok(client.get(f"{V1}/claims"))
    assert version(client) == v


def test_without_watchdog_posting_a_claim_still_bumps(world, db_path, monkeypatch):
    monkeypatch.setattr(watch, "Observer", None)
    app = create_app(db_path, token=TOKEN, definitions=world["definitions"])
    client = TestClient(app, base_url="http://127.0.0.1", headers=AUTH)
    try:
        before = changes(client)
        assert before["available"] is False and not claims.claims_dir().exists()  # no folder to watch, none made
        ok(client.post(f"{V1}/claims", json={"uid": world["barrel"], "environment": world["envs"]["loose_files"]["id"]}))
        assert changes(client)["version"] > before["version"]
    finally:
        app.state.library.close()


def test_waiting_ends_on_a_change_or_a_different_version(api):
    client = api["client"]
    current = version(client)
    started = time.monotonic()
    assert changes(client, since=current + 5)["version"] == current  # other than current returns at once
    assert changes(client, since=current - 1)["version"] == current
    assert time.monotonic() - started < 2
    started = time.monotonic()
    assert changes(client, since=current, wait=0.2)["version"] == current
    assert time.monotonic() - started >= 0.15
    started = time.monotonic()
    maker = threading.Timer(0.3, barrel, args=(api,))
    maker.start()
    assert changes(client, since=current, wait=5)["version"] > current
    maker.join()
    assert time.monotonic() - started < 3
    assert client.get(f"{V1}/claims/changes", params={"wait": 26}).status_code == 422


# The claims folder's watcher ---------------------------------------------------------------------


@pytest.fixture
def watched(world, db_path):
    pytest.importorskip("watchdog")
    app = create_app(db_path, token=TOKEN, definitions=world["definitions"], watch=True)
    client = TestClient(app, base_url="http://127.0.0.1", headers=AUTH)
    yield {**world, "client": client, "app": app, "loose": world["envs"]["loose_files"]["id"]}
    app.state.library.close()


def settled(client):
    time.sleep(0.4)  # a file operation can raise more than one event
    return version(client)


def test_claim_files_changing_move_the_version(watched):
    client = watched["client"]
    assert changes(client)["available"] is True
    folder = claims.claims_dir()
    steps = [lambda: (folder / "a.md").write_text("one", encoding="utf-8"),
             lambda: (folder / "a.md").write_text("two", encoding="utf-8"),
             lambda: (folder / "a.md").unlink(),
             lambda: (folder / "B.MD").write_text("upper", encoding="utf-8"),
             lambda: ((folder / "c.md.1.tmp").write_text("x", encoding="utf-8"),
                      os.replace(folder / "c.md.1.tmp", folder / "c.md")),
             lambda: os.replace(folder / "c.md", folder / "c.txt")]
    v = settled(client)
    for step in steps:
        step()
        assert grew(client, v) != v
        v = settled(client)


def test_a_temporary_file_alone_and_a_subfolder_do_not(watched):
    client = watched["client"]
    folder = claims.claims_dir()
    changes(client)
    v = settled(client)
    (folder / "d.md.1.tmp").write_text("x", encoding="utf-8")
    assert grew(client, v, wait=1) == v
    (folder / "sub").mkdir()
    (folder / "sub" / "e.md").write_text("x", encoding="utf-8")
    assert grew(client, v, wait=1) == v


def test_the_folder_is_made_by_the_first_changes_and_watched_once(world, db_path):
    pytest.importorskip("watchdog")
    app = create_app(db_path, token=TOKEN, definitions=world["definitions"], watch=True)
    client = TestClient(app, base_url="http://127.0.0.1", headers=AUTH)
    library = app.state.library
    try:
        ok(client.post(f"{V1}/claims/preview", json={"uid": world["barrel"],
                                                     "environment": world["envs"]["loose_files"]["id"]}))
        assert not claims.claims_dir().exists() and library.claim_watcher._observer is None
        assert changes(client)["available"] is True and claims.claims_dir().is_dir()
        observer = library.claim_watcher._observer
        assert observer is not None and observer.is_alive()
        changes(client)
        assert library.claim_watcher._observer is observer
    finally:
        library.close()
    assert not observer.is_alive()


def test_an_unwatchable_folder_leaves_the_other_sources(world, db_path, monkeypatch):
    pytest.importorskip("watchdog")
    app = create_app(db_path, token=TOKEN, definitions=world["definitions"], watch=True)
    client = TestClient(app, base_url="http://127.0.0.1", headers=AUTH)

    def fail(self, *args, **kwargs):
        raise OSError("not watchable")
    monkeypatch.setattr(watch.Observer, "schedule", fail)
    try:
        assert changes(client)["available"] is False
        v = version(client)
        ok(client.post(f"{V1}/claims", json={"uid": world["barrel"], "environment": world["envs"]["loose_files"]["id"]}))
        assert version(client) > v
    finally:
        app.state.library.close()
