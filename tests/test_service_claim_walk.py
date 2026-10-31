"""R4b: planning and walking a claim's path through the service (and the core split under it)."""

import sqlite3
import sys
import threading
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi import HTTPException  # noqa: E402

from exchange import claims  # noqa: E402
from exchange.processes.registry import install, trust  # noqa: E402
from exchange.requisitions.endpoints import EndpointError  # noqa: E402
from exchange.requisitions.plan import PlanError  # noqa: E402
from exchange.requisitions.presets import _last_file, last_used, remember  # noqa: E402
from exchange.service import jobs as jobs_module  # noqa: E402
from test_claim_paths import PROCESSES, marius, world  # noqa: E402,F401  (the fixture)
from test_service_claims import V1, api, edit, ok  # noqa: E402,F401  (the fixture)
from test_service_jobs import SLOW  # noqa: E402
from test_service_requisitions import finish  # noqa: E402

PLAN_KEYS = {"plans", "problems", "forms", "included"}


def use(api, *names):
    """Install and trust these fixture packages for the service, without the machine-dependent convert_mesh."""
    for name in names:
        trust(install(PROCESSES / name))
    registry = api["app"].state.library.processes.registry(reload=True)
    registry.packages.pop("convert_mesh", None)
    return registry


def rows(api, sql="SELECT count(*) FROM requisition", *args):
    conn = sqlite3.connect(api["db"])
    try:
        return conn.execute(sql, args).fetchone()[0]
    finally:
        conn.close()


def make(api, uid, **extra):
    return ok(api["client"].post(f"{V1}/claims", json={"uid": uid, "environment": api["loose"], **extra}))


def barrel(api, **extra):
    return make(api, api["barrel"], **extra)


def plan(api, claim, **body):
    return api["client"].post(f"{V1}/claims/{claim['id']}/plan", json=body)


def walk(api, claim, **body):
    return api["client"].post(f"{V1}/claims/{claim['id']}/walk", json={"run": False, **body})


def item_params(api, rid):
    detail = ok(api["client"].get(f"{V1}/requisitions/{rid}"))
    return detail["items"][0]["params"]["stamp_images"]


def plan_params(result):
    return result["plans"][0]["items"][0]["params"]["stamp_images"]


def test_the_new_routes_need_the_token(api):
    client, wrong = api["client"], {"Authorization": "Bearer wrong"}
    calls = [client.post(f"{V1}/claims/x/plan", json={}, headers=wrong),
             client.post(f"{V1}/claims/x/walk", json={}, headers=wrong),
             client.get(f"{V1}/claims/changes", headers=wrong)]
    assert [c.status_code for c in calls] == [401] * 3


def test_plan_shows_the_path_and_writes_nothing(api):
    use(api, "stamp_images")
    claim = barrel(api)
    before = rows(api)
    result = ok(plan(api, claim))
    assert set(result) == PLAN_KEYS and len(result["plans"]) == 1
    assert [f["process"] for f in result["forms"]] == ["stamp_images"] and result["included"] == 1
    assert result["plans"][0]["items"][0]["source_entry_id"] == claim["path"]["source_entry_id"]
    assert rows(api) == before
    assert ok(api["client"].get(f"{V1}/claims/{claim['id']}"))["requisitions"] == []


def test_plan_follows_the_claims_role_and_folder(api):
    use(api, "copy_as_prop")
    prop = ok(plan(api, barrel(api, **{"as": "prop"})))
    assert prop["plans"][0]["items"][0]["processes"] == ["copy_as_prop"]
    endpoint = ok(plan(api, barrel(api, folder="Out")))["plans"][0]["endpoint"]
    assert Path(endpoint["folder"]) == Path(endpoint["root"]) / "Out"
    assert ok(plan(api, barrel(api)))["plans"][0]["endpoint"]["folder"] != endpoint["folder"]


def test_plan_and_walk_agree(api):
    use(api, "stamp_images")
    claim = barrel(api)
    body = {"options": {"stamp_images": {"size": 3}}, "on_collision": "rename"}
    planned = ok(plan(api, claim, **body))["plans"][0]
    walked = ok(walk(api, claim, **body))
    queued = ok(api["client"].get(f"{V1}/requisitions/{walked['requisition']['id']}"))
    assert planned["on_collision"] == queued["on_collision"] == "rename"
    assert planned["endpoint"]["folder"] == queued["endpoint"]["folder"]
    assert len(planned["items"]) == len(queued["items"])
    for want, got in zip(planned["items"], queued["items"]):
        assert want["dossier_uid"] == got["dossier_uid"] and want["include"] == bool(got["include"])
        assert want["source_entry_id"] == got["source_entry_id"]
        assert want["processes"] == [p["id"] for p in got["processes"]] and want["params"] == got["params"]


def test_options_come_from_the_request_then_the_preset_then_the_last_used(api):
    use(api, "stamp_images")
    client = api["client"]
    ok(client.post(f"{V1}/presets", json={"name": "Tiny", "options": {"stamp_images": {"size": 4}}}))
    last = {"stamp_images": {"size": 8, "note": "last"}}
    cases = [({}, {"size": 16, "note": "stamped"}, {}),  # neither a preset nor a last used
             ({}, {"size": 8, "note": "last"}, last),  # the last used
             ({"preset": "Tiny"}, {"size": 4, "note": "stamped"}, last),  # the preset replaces it
             ({"options": {"stamp_images": {"size": 2}}}, {"size": 2, "note": "last"}, last),
             ({"preset": "Tiny", "options": {"stamp_images": {"size": 2}}}, {"size": 2, "note": "stamped"}, last)]
    for body, want, remembered in cases:
        last_used_file = _last_file()
        if last_used_file.exists():
            last_used_file.unlink()
        remember(remembered)
        got = plan_params(ok(plan(api, barrel(api), **body)))
        assert {k: got[k] for k in want} == want, (body, got)
        if remembered:
            remember(remembered)  # the plan wrote nothing, but a walk below would
        queued = item_params(api, ok(walk(api, barrel(api), **body))["requisition"]["id"])
        assert {k: queued[k] for k in want} == want, (body, queued)


def test_walking_remembers_the_options_but_the_cli_does_not_use_them(api):
    use(api, "stamp_images")
    client = api["client"]
    walked = ok(walk(api, barrel(api), options={"stamp_images": {"size": 5, "note": "api"}}))
    assert walked["requisition"]["state"] == "queued"
    assert ok(client.get(f"{V1}/presets/last-used"))["stamp_images"] == {"size": 5, "review": False, "note": "api"}
    other = barrel(api)
    registry = api["app"].state.library.processes.registry()
    _, rid = claims.walk(api["conn"], api["definitions"], registry, other["id"], {})  # what `exchange claim walk` calls
    assert item_params(api, rid) == {"size": 16, "review": False, "note": "stamped"}


def test_a_rejected_option_is_a_problem_on_plan_and_a_refusal_on_walk(api):
    use(api, "stamp_images")
    claim = barrel(api)
    body = {"options": {"stamp_images": {"size": "big"}}}
    result = ok(plan(api, claim, **body))
    assert result["included"] == 0 and result["plans"][0]["items"][0]["problems"]
    before, text = rows(api), (claims.claims_dir() / f"{claim['id']}.md").read_text(encoding="utf-8")
    refused = walk(api, claim, **body)
    assert refused.status_code == 409, refused.text
    assert rows(api) == before and (claims.claims_dir() / f"{claim['id']}.md").read_text(encoding="utf-8") == text
    assert ok(api["client"].get(f"{V1}/claims/{claim['id']}"))["requisitions"] == []


def test_excluded_items_are_skipped_and_excluding_all_is_refused(api):
    use(api, "character_to_loose", "morph_to_loose")
    claim = make(api, marius(api))
    items = ok(plan(api, claim))["plans"][0]["items"]
    assert len(items) == 3 and all(i["include"] for i in items)
    left_out = items[0]["dossier_uid"]
    result = ok(plan(api, claim, excluded=[left_out]))
    assert result["included"] == 2
    rid = ok(walk(api, claim, excluded=[left_out]))["requisition"]["id"]
    states = {r[0]: (r[1], r[2]) for r in sqlite3.connect(api["db"]).execute(
        "SELECT dossier_uid, include, state FROM requisition_item WHERE requisition_id = ?", (rid,))}
    assert states[left_out] == (0, "skipped")
    assert [v for k, v in states.items() if k != left_out] == [(1, "queued")] * 2
    other = make(api, marius(api))
    before = rows(api)
    everything = [i["dossier_uid"] for i in items]
    assert ok(plan(api, other, excluded=everything))["included"] == 0
    refused = walk(api, other, excluded=everything)
    assert refused.status_code == 409 and refused.json()["detail"] == "nothing in this plan is included"
    assert rows(api) == before


def test_on_collision_is_the_requisitions(api):
    use(api, "stamp_images")
    made = ok(walk(api, barrel(api), on_collision="skip"))
    assert ok(api["client"].get(f"{V1}/requisitions/{made['requisition']['id']}"))["on_collision"] == "skip"


def test_walking_without_running_queues_and_records(api):
    use(api, "stamp_images")
    claim = barrel(api)
    walked = ok(walk(api, claim))
    assert walked["job"] is None and walked["problem"] is None
    assert walked["claim"]["turn"] == "exchange" and walked["requisition"]["state"] == "queued"
    assert walked["requisition"]["id"] and walked["claim"]["requisitions"] == [walked["requisition"]]
    text = (claims.claims_dir() / f"{claim['id']}.md").read_text(encoding="utf-8")
    assert walked["requisition"]["uid"] in text


def test_walking_runs_only_its_requisition_by_default(api):
    use(api, "stamp_images")
    elsewhere = ok(walk(api, barrel(api)))["requisition"]
    claim = barrel(api)
    walked = ok(api["client"].post(f"{V1}/claims/{claim['id']}/walk", json={}))
    assert walked["problem"] is None and walked["job"]["kind"] == "requisitions" and walked["job"]["writes"] is True
    job = finish(api["client"], walked["job"])
    assert job["state"] == "done", job
    assert [r["id"] for r in job["result"]["ran"]] == [walked["requisition"]["id"]]
    assert ok(api["client"].get(f"{V1}/requisitions/{elsewhere['id']}"))["state"] == "queued"
    assert ok(api["client"].get(f"{V1}/claims/{claim['id']}"))["milestone"] == "installed"


@pytest.mark.parametrize("route", ["plan", "walk"])
def test_missing_claims_presets_and_folders(api, route):
    use(api, "stamp_images")
    post = plan if route == "plan" else walk
    before = rows(api)
    assert post(api, {"id": "no-such-claim"}).status_code == 404
    claim = barrel(api)
    unknown = post(api, claim, preset="Nope")
    assert unknown.status_code == 404 and unknown.json()["detail"].startswith("no preset ")
    edit(claim["id"], "folder", "../out")
    leaving = post(api, claim)
    assert leaving.status_code == 400, leaving.text
    assert rows(api) == before


@pytest.mark.parametrize("route", ["plan", "walk"])
def test_what_the_core_refuses_is_a_conflict(api, route, monkeypatch):
    use(api, "stamp_images")
    post = plan if route == "plan" else walk
    before = rows(api)

    closed = barrel(api)
    ok(api["client"].post(f"{V1}/claims/{closed['id']}/close"))
    assert post(api, closed).status_code == 409

    assert post(api, barrel(api, **{"as": "figure"})).status_code == 409  # no path

    for state in ("queued", "running", "held"):
        waiting = barrel(api)
        rid = ok(walk(api, waiting))["requisition"]["id"]
        before += 1
        sqlite3.connect(api["db"]).execute("UPDATE requisition SET state = ? WHERE id = ?", (state, rid)).connection.commit()
        refused = post(api, waiting)
        assert refused.status_code == 409, (state, refused.text)

    broken = barrel(api)
    (claims.claims_dir() / f"{broken['id']}.md").write_text("---\nthing: [unclosed\n---\n", encoding="utf-8")
    assert post(api, broken).status_code == 409

    fine = barrel(api)
    for error in (PlanError("no dossier x in the library"), EndpointError("no environment y in the library"),
                  PlanError("something else"), EndpointError("endpoint trouble")):
        def raises(*args, error=error, **kwargs):
            raise error
        monkeypatch.setattr(claims, "plan_requisition", raises)
        refused = post(api, fine)
        assert refused.status_code == 409 and refused.json()["detail"] == str(error)
    assert rows(api) == before


def test_walking_is_refused_while_a_job_writes(api, monkeypatch):
    use(api, "stamp_images")
    monkeypatch.setattr(jobs_module.Jobs, "command", lambda self, args, json_output: [sys.executable, "-c", SLOW])
    client = api["client"]
    job = ok(client.post(f"{V1}/jobs/rescan", json={}))
    try:
        claim, before = barrel(api), rows(api)
        refused = walk(api, claim)
        assert refused.status_code == 409 and "is running" in refused.json()["detail"]
        assert rows(api) == before
    finally:
        finish(client, ok(client.post(f"{V1}/jobs/{job['id']}/stop")))


def test_a_busy_library_is_a_503_but_a_plan_still_answers(api):
    use(api, "stamp_images")
    claim = barrel(api)
    path = claims.claims_dir() / f"{claim['id']}.md"
    text, before = path.read_text(encoding="utf-8"), rows(api)
    blocker = sqlite3.connect(api["db"], timeout=0, isolation_level=None)
    blocker.execute("BEGIN IMMEDIATE")
    try:
        busy = walk(api, claim)
        assert busy.status_code == 503, busy.text
        assert plan(api, claim).status_code == 200
    finally:
        blocker.execute("ROLLBACK")
        blocker.close()
    assert rows(api) == before and path.read_text(encoding="utf-8") == text


def test_a_job_that_will_not_start_leaves_the_requisition_queued(api, monkeypatch):
    use(api, "stamp_images")
    claim = barrel(api)
    version = ok(api["client"].get(f"{V1}/claims/changes"))["version"]

    def refuse(*args, **kwargs):
        raise HTTPException(409, "another job is writing")
    monkeypatch.setattr(api["app"].state.library.jobs, "start", refuse)
    walked = ok(api["client"].post(f"{V1}/claims/{claim['id']}/walk", json={}))
    assert walked["job"] is None and walked["problem"] == "another job is writing"
    assert walked["requisition"]["state"] == "queued"
    assert walked["requisition"]["uid"] in (claims.claims_dir() / f"{claim['id']}.md").read_text(encoding="utf-8")
    assert ok(api["client"].get(f"{V1}/claims/changes"))["version"] > version


def test_two_walks_at_once_queue_one(api):
    use(api, "stamp_images")
    claim, before = barrel(api), rows(api)
    codes: list[int] = []
    start = threading.Barrier(2)

    def go():
        start.wait()
        codes.append(walk(api, claim).status_code)
    threads = [threading.Thread(target=go) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(codes) == [200, 409]
    assert rows(api) == before + 1
    assert (claims.claims_dir() / f"{claim['id']}.md").read_text(encoding="utf-8").count("requisitions:") == 1
    assert len(ok(api["client"].get(f"{V1}/claims/{claim['id']}"))["requisitions"]) == 1


def test_plan_path_is_what_walk_queues(api):
    registry = use(api, "stamp_images")
    claim = barrel(api)
    conn, definitions = api["conn"], api["definitions"]
    found, planned = claims.plan_path(conn, definitions, registry, claim["id"], {})
    assert isinstance(found, claims.Claim) and found.id == claim["id"]
    _, rid = claims.walk(conn, definitions, registry, claim["id"], {})  # tools stay positional
    queued = [(r["dossier_uid"], bool(r["include"]), r["source_entry_id"]) for r in conn.execute(
        "SELECT * FROM requisition_item WHERE requisition_id = ?", (rid,))]
    assert queued == [(i.dossier_uid, i.include, i.source_entry_id) for i in planned.items]
    assert rows(api, "SELECT count(*) FROM requisition_item WHERE requisition_id = ?", rid) == len(queued)


def test_the_requisition_routes_answer_as_before(api):
    use(api, "stamp_images")
    client = api["client"]
    body = {"uids": [api["barrel"]], "environment": api["loose"]}
    assert set(ok(client.post(f"{V1}/requisitions/plan", json=body))) == PLAN_KEYS
    missing = client.post(f"{V1}/requisitions/plan", json=body | {"preset": "Nope"})
    assert missing.status_code == 404 and missing.json()["detail"].startswith("no preset ")
    queued = ok(client.post(f"{V1}/requisitions/queue", json=body | {"options": {"stamp_images": {"note": "kept"}}}))
    assert list(queued) == ["ids"] and len(queued["ids"]) == 1
    assert last_used()["stamp_images"]["note"] == "kept"
    nothing = client.post(f"{V1}/requisitions/queue", json=body | {"excluded": [api["barrel"]]})
    assert nothing.status_code == 409 and nothing.json()["detail"] == "nothing in this plan is included"
