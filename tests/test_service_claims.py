"""The service's claims API (R4a): read, make, preview and close claims, and what a hand-edited file may do."""

import datetime as dt
import json
import re
import shutil
import threading
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from exchange import claims  # noqa: E402
from exchange.cli import main  # noqa: E402
from exchange.scanner.scan import run_rescan  # noqa: E402
from exchange.service.app import create_app  # noqa: E402
from test_claim_paths import registry_with, world  # noqa: E402,F401  (the fixture)

TOKEN = "test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
V1 = "/api/v1"
PROP = Path(__file__).parent / "fixtures" / "processes" / "copy_as_prop"
LIST_KEYS = {"id", "thing", "thing_name", "as", "place", "place_name", "folder", "milestone", "created", "closed",
             "turn", "turn_line", "already_there", "path"}


@pytest.fixture
def api(world, db_path):
    """A client on the Daz and loose-files library of ``test_claim_paths``."""
    app = create_app(db_path, token=TOKEN, definitions=world["definitions"], watch=False)
    client = TestClient(app, base_url="http://127.0.0.1", headers=AUTH)
    yield {**world, "client": client, "app": app, "loose": world["envs"]["loose_files"]["id"],
           "daz": world["envs"]["daz_studio"]["id"]}
    app.state.library.close()


def ok(response):
    assert response.status_code == 200, response.text
    return response.json()


def request(api, place="loose", **extra):
    return {"uid": api["ding"], "environment": api[place], **extra}


def make(api, place="loose", **extra):
    return ok(api["client"].post(f"{V1}/claims", json=request(api, place, **extra)))


def files():
    folder = claims.claims_dir()
    return sorted(folder.glob("*")) if folder.exists() else []


def edit(claim_id, key, value):
    """Hand-edit one top-level line of a claim file."""
    path = claims.claims_dir() / f"{claim_id}.md"
    text = path.read_text(encoding="utf-8")
    changed = re.sub(rf"(?m)^{key}:.*$", f"{key}: {value}", text, count=1)
    assert changed != text
    path.write_text(changed, encoding="utf-8", newline="\n")
    return path


def listed(api, **params):
    return ok(api["client"].get(f"{V1}/claims", params=params))


def test_the_claims_routes_need_the_token(api):
    client, wrong = api["client"], {"Authorization": "Bearer wrong"}
    calls = [client.post(f"{V1}/claims/preview", json=request(api), headers=wrong),
             client.post(f"{V1}/claims", json=request(api), headers=wrong),
             client.get(f"{V1}/claims", headers=wrong),
             client.get(f"{V1}/claims/x", headers=wrong),
             client.post(f"{V1}/claims/x/close", headers=wrong)]
    assert [c.status_code for c in calls] == [401] * 5
    assert files() == []


def test_a_preview_is_the_claim_then_made(api):
    client = api["client"]
    body = request(api, **{"as": "prop"}) | {"folder": "Props"}
    first = ok(client.post(f"{V1}/claims/preview", json=body))
    assert not claims.claims_dir().exists()
    made = ok(client.post(f"{V1}/claims", json=body | {"note": "hello"}))
    assert set(first) == LIST_KEYS and not {"notes", "requisitions"} & set(first)
    assert {"notes", "requisitions"} <= set(made)
    for key in ("path", "turn", "turn_line", "milestone", "thing", "place", "as", "folder", "already_there", "id",
                "created"):
        assert first[key] == made[key], key
    assert made["notes"] == "hello\n"


def test_a_preview_writes_nothing(api):
    ok(api["client"].post(f"{V1}/claims/preview", json=request(api)))
    assert not claims.claims_dir().exists()
    assert listed(api) == {"claims": [], "problems": []}
    assert not claims.claims_dir().exists()


@pytest.mark.parametrize("route", ["/claims/preview", "/claims"])
def test_both_refuse_what_the_core_refuses(api, route):
    client, conn = api["client"], api["conn"]
    assert issubclass(claims.ClaimNotFound, claims.ClaimError) and issubclass(claims.FolderLeavesPlace, claims.ClaimError)
    cases = [({"uid": "no-such-thing"}, 404), ({"environment": 9999}, 404), ({"folder": "../out"}, 400)]
    for change, code in cases:
        body = request(api) | change
        response = client.post(V1 + route, json=body)
        assert response.status_code == code, response.text
        with pytest.raises(claims.ClaimError) as raised:
            claims.prepare(conn, body["uid"], body["environment"], folder=body.get("folder"),
                           definitions=api["definitions"])
        assert response.json()["detail"] == str(raised.value)
    assert files() == []


def test_the_cli_and_the_api_agree(api, capsys):
    made = make(api)
    code = main(["claim", "show", made["id"], "--json", "--db", str(api["db"])])
    shown = json.loads(capsys.readouterr().out)
    assert code == 0
    assert (shown["thing"], shown["place"], shown["milestone"]) == (made["thing"], made["place"], made["milestone"])
    assert shown["already_there"] is made["already_there"]
    code = main(["claim", "add", api["ding"][:12], "--env", str(api["daz"]), "--json", "--db", str(api["db"])])
    added = json.loads(capsys.readouterr().out)
    assert code == 0 and added["already_there"] is False
    assert ok(api["client"].get(f"{V1}/claims/{added['id']}"))["id"] == added["id"]


def test_the_list(api):
    conn, registry = api["conn"], registry_with()
    old, mid, new = (claims.new(conn, api["ding"], api["loose"], today=dt.date(2026, 10, day)) for day in (1, 2, 3))
    same = claims.new(conn, api["ding"], api["loose"], today=dt.date(2026, 10, 3))
    assert same.id != new.id
    ids = [c["id"] for c in listed(api)["claims"]]
    assert ids == [*sorted([new.id, same.id], reverse=True), mid.id, old.id]
    claims.close(conn, mid.id)
    assert mid.id not in [c["id"] for c in listed(api)["claims"]]
    assert mid.id in [c["id"] for c in listed(api, all="true")["claims"]]
    assert all(not {"notes", "requisitions"} & set(c) for c in listed(api, all="true")["claims"])
    # the turn: ding reads ready in loose_files (Walk it), builds in daz_studio
    build = claims.new(conn, api["ding"], api["daz"], today=dt.date(2026, 10, 9))
    assert [c["id"] for c in listed(api, turn="build")["claims"]] == [build.id]
    assert {c["id"] for c in listed(api, turn="you")["claims"]} == {old.id, new.id, same.id}
    assert listed(api, turn="exchange")["claims"] == []
    walked, _ = claims.walk(conn, api["definitions"], registry, old.id, {})
    assert [c["id"] for c in listed(api, turn="exchange")["claims"]] == [walked.id]
    other = claims.new(conn, api["barrel"], api["loose"], today=dt.date(2026, 10, 5))
    assert [c["id"] for c in listed(api, thing=api["barrel"])["claims"]] == [other.id]
    assert listed(api, thing="nothing")["claims"] == []
    assert api["client"].get(f"{V1}/claims", params={"turn": "bogus"}).status_code == 422


def test_a_claim_without_a_date_sorts_last(api):
    conn = api["conn"]
    dated = claims.new(conn, api["ding"], api["loose"], today=dt.date(2026, 10, 1))
    undated = claims.new(conn, api["ding"], api["loose"], today=dt.date(2026, 10, 2))
    edit(undated.id, "created", "null")
    assert [c["id"] for c in listed(api)["claims"]] == [dated.id, undated.id]


def test_the_detail_lists_the_requisitions(api):
    conn, registry = api["conn"], registry_with()
    claim = claims.new(conn, api["ding"], api["loose"])
    claim, rid = claims.walk(conn, api["definitions"], registry, claim.id, {})
    uid = claim.meta["requisitions"][0]
    claims.update(claim, {"requisitions": [uid, "no-such-uid"]})
    detail = ok(api["client"].get(f"{V1}/claims/{claim.id}"))
    row = conn.execute("SELECT id, uid, state, message FROM requisition WHERE id = ?", (rid,)).fetchone()
    assert detail["requisitions"] == [{"uid": uid, "id": rid, "state": row["state"], "message": row["message"]},
                                      {"uid": "no-such-uid", "id": None, "state": None, "message": None}]
    edit(claim.id, "requisitions", "not a list")
    assert ok(api["client"].get(f"{V1}/claims/{claim.id}"))["requisitions"] == []


def test_closing(api):
    client = api["client"]
    made = make(api, note="first")
    closed = ok(client.post(f"{V1}/claims/{made['id']}/close", json={"reason": "done"}))
    assert re.fullmatch(r"\d{4}-\d\d-\d\d", closed["closed"]) and closed["turn"] == "none"
    assert closed["notes"].endswith("done\n") and closed["notes"].startswith("first\n")
    path = claims.claims_dir() / f"{made['id']}.md"
    assert "done" in path.read_text(encoding="utf-8")
    before = path.read_bytes()
    again = client.post(f"{V1}/claims/{made['id']}/close", json={"reason": "again"})
    assert again.status_code == 409 and made["id"] in again.json()["detail"]
    assert path.read_bytes() == before
    assert ok(client.post(f"{V1}/claims/{make(api, 'daz')['id']}/close"))["closed"]
    other = make(api)
    assert ok(client.post(f"{V1}/claims/{other['id']}/close", json={"reason": None}))["closed"]


def test_two_closes_at_once_close_once(api):
    made = make(api)
    codes = []

    def close():
        codes.append(api["client"].post(f"{V1}/claims/{made['id']}/close", json={"reason": "once"}).status_code)

    threads = [threading.Thread(target=close) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(codes) == [200, 409]
    assert (claims.claims_dir() / f"{made['id']}.md").read_text(encoding="utf-8").count("once") == 1


def test_an_id_is_never_a_path(api):
    client = api["client"]
    make(api)
    assert client.get(f"{V1}/claims/nosuch").status_code == 404
    for odd in ("..", "..%5Cx", "..%2Fx"):
        assert client.get(f"{V1}/claims/{odd}").status_code == 404, odd
        assert client.post(f"{V1}/claims/{odd}/close").status_code == 404, odd


def test_wrong_types_read_as_text_or_null(api):
    made = make(api)
    path = claims.claims_dir() / f"{made['id']}.md"
    for key, value in [("thing_name", "true"), ("folder", "[a, b]"), ("as", "{x: 1}"), ("thing", "123")]:
        edit(made["id"], key, value)
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace("---\n", "---\npriority: high\n", 1), encoding="utf-8", newline="\n")
    ok(api["client"].post(f"{V1}/claims/{made['id']}/close"))
    seen = [listed(api, all="true")["claims"][0], ok(api["client"].get(f"{V1}/claims/{made['id']}"))]
    for claim in seen:
        assert (claim["thing"], claim["thing_name"], claim["folder"], claim["as"]) == ("123", "True", None, None)
        assert re.fullmatch(r"\d{4}-\d\d-\d\d", claim["created"]) and re.fullmatch(r"\d{4}-\d\d-\d\d", claim["closed"])
        assert "priority" not in claim
    assert "priority: high" in path.read_text(encoding="utf-8")


def test_a_wrong_typed_closed_is_still_closed(api):
    made = make(api)
    edit(made["id"], "closed", "[a]")
    assert listed(api)["claims"] == []
    assert listed(api, all="true")["claims"][0]["closed"] is None


def test_an_unresolved_thing_or_place_still_has_a_turn(api):
    made = make(api)
    edit(made["id"], "thing", "no-such-dossier")
    gone = ok(api["client"].get(f"{V1}/claims/{made['id']}"))
    assert gone["turn"] == "you" and gone["path"]["status"] == "none" and gone["already_there"] is False
    other = make(api)
    edit(other["id"], "place", "no-such-place")
    lost = ok(api["client"].get(f"{V1}/claims/{other['id']}"))
    assert lost["turn"] == "build" and lost["already_there"] is False
    assert len(listed(api)["claims"]) == 2


def test_files_that_do_not_parse_are_problems(api, capsys):
    good = make(api)
    folder = claims.claims_dir()
    bad = {"twice": b"---\nid: x\nid: y\n---\n", "date": b"---\ncreated: 2026-02-30\n---\n",
           "key": b"---\n[a, b]: 1\n---\n", "bytes": b"---\nthing: \xff\xfe\n---\n"}
    for name, content in bad.items():
        (folder / f"{name}.md").write_bytes(content)
    found = listed(api)
    assert [c["id"] for c in found["claims"]] == [good["id"]]
    assert len(found["problems"]) == len(bad)
    for name in bad:
        assert sum(line.startswith(f"{name}.md:") for line in found["problems"]) == 1
        for response in (api["client"].get(f"{V1}/claims/{name}"), api["client"].post(f"{V1}/claims/{name}/close")):
            assert response.status_code == 409 and f"{name}.md" in response.json()["detail"], name
    assert main(["claim", "list", "--db", str(api["db"])]) == 0
    capsys.readouterr()


def test_already_there_is_true_for_a_plain_claim_on_a_place_holding_the_thing(api, capsys):
    preview = ok(api["client"].post(f"{V1}/claims/preview", json=request(api)))
    made = make(api)
    shown = ok(api["client"].get(f"{V1}/claims/{made['id']}"))
    main(["claim", "show", made["id"], "--json", "--db", str(api["db"])])
    cli = json.loads(capsys.readouterr().out)
    assert preview["already_there"] is shown["already_there"] is cli["already_there"] is True
    # saying so changes nothing else: the path and the turn are the core's own
    registry = api["app"].state.library.processes.registry()
    claim = claims.read_one(api["conn"], made["id"])
    assert shown["path"] == claims.find_path(api["conn"], api["definitions"], registry, claim)
    assert (shown["turn"], shown["turn_line"]) == claims.whose_turn(api["conn"], api["definitions"], registry, claim)
    assert (shown["turn"], shown["turn_line"]) == ("you", "Walk it")


def test_already_there_is_false_when_anything_else_is_asked(api):
    for extra in ({"as": "prop"}, {"folder": "Props"}):
        assert make(api, **extra)["already_there"] is False
    assert make(api, "daz")["already_there"] is False
    walked = claims.new(api["conn"], api["ding"], api["loose"])
    walked, _ = claims.walk(api["conn"], api["definitions"], registry_with(), walked.id, {})
    assert ok(api["client"].get(f"{V1}/claims/{walked.id}"))["already_there"] is False
    claims.update(walked, {"requisitions": ["no-such-uid"]})
    assert ok(api["client"].get(f"{V1}/claims/{walked.id}"))["already_there"] is False


def test_already_there_is_false_on_an_offline_root(api):
    assert ok(api["client"].post(f"{V1}/claims/preview", json=request(api)))["already_there"] is True
    shutil.rmtree(api["root"] / "Loose")
    run_rescan(db_path=api["db"], definitions=api["definitions"])
    assert ok(api["client"].post(f"{V1}/claims/preview", json=request(api)))["already_there"] is False


def test_already_there_is_false_when_the_entry_is_retired(api):
    made = make(api)
    for path in (api["root"] / "Loose").rglob("ding*"):
        path.unlink()
    run_rescan(db_path=api["db"], definitions=api["definitions"])
    assert ok(api["client"].get(f"{V1}/claims/{made['id']}"))["already_there"] is False


def test_processes_show_their_roles(api):
    client = api["client"]
    assert ok(client.post(f"{V1}/processes/install", json={"folder": str(PROP)}))["roles"] == ["prop"]
    found = {p["id"]: p for p in ok(client.get(f"{V1}/processes"))["processes"]}
    assert found["copy_as_prop"]["roles"] == ["prop"] and found["copy_entry"]["roles"] == []


def test_the_contract_names_the_claims_routes():
    committed = json.loads((Path(__file__).parent.parent / "docs" / "api" / "openapi.json").read_text(encoding="utf-8"))
    for path, method in [("/claims", "get"), ("/claims", "post"), ("/claims/preview", "post"),
                         ("/claims/{id}", "get"), ("/claims/{id}/close", "post")]:
        assert committed["paths"][f"{V1}{path}"][method]["tags"] == ["claims"]
    schemas = committed["components"]["schemas"]
    assert "as" in schemas["ClaimView"]["properties"] and "as" in schemas["ClaimPreviewRequest"]["properties"]


def stale_claim(api):
    made = make(api)
    path = claims.claims_dir() / f"{made['id']}.md"
    path.write_text(path.read_text(encoding="utf-8").replace("milestone: acquired", "milestone: claimed"),
                    encoding="utf-8", newline="\n")
    return made, path


def test_concurrent_reads_of_a_stale_claim(api):
    made, path = stale_claim(api)
    codes = []

    def read():
        client = TestClient(api["app"], base_url="http://127.0.0.1", headers=AUTH)
        for _ in range(5):
            codes.append(client.get(f"{V1}/claims/{made['id']}").status_code)

    threads = [threading.Thread(target=read) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert codes == [200] * 40
    assert [p.name for p in files()] == [path.name] and "milestone: acquired" in path.read_text(encoding="utf-8")


def test_a_failed_save_is_a_problem_line_not_an_error(api, monkeypatch):
    made, path = stale_claim(api)
    before = path.read_bytes()

    def refuse(src, dst):
        raise OSError("refused")

    monkeypatch.setattr(claims.os, "replace", refuse)
    found = listed(api)
    assert [c["milestone"] for c in found["claims"]] == ["acquired"]
    assert len(found["problems"]) == 1 and path.name in found["problems"][0]
    assert path.read_bytes() == before and [p.suffix for p in files()] == [".md"]
