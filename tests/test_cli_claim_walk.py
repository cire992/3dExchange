"""exchange claim: path and whose turn in show, list, add and close; walk and walk --run (R3b)."""

import json

import pytest

from exchange import claims, cli_claims
from exchange.cli import main
from exchange.requisitions import lifecycle
from exchange.requisitions.plan import plan_requisition, queue_plan
from exchange.requisitions.runner import run_queue
from test_claim_paths import registry_with, world  # noqa: F401  (the fixture)


def use(monkeypatch, registry):
    monkeypatch.setattr(cli_claims, "load_registry", lambda: registry)


@pytest.fixture
def ready(monkeypatch):
    use(monkeypatch, registry_with("stamp_images", "to_daz"))


def claim_cmd(capsys, w, *argv):
    code = main(["claim", *argv, "--db", str(w["db"])])
    out = capsys.readouterr()
    return code, out.out, out.err


def add(capsys, w, thing, place, *extra):
    code, out, _ = claim_cmd(capsys, w, "add", w[thing][:12], "--env", str(w["envs"][place]["id"]), "--json", *extra)
    assert code == 0
    return json.loads(out)


def claim_file(claim):
    return claims.claims_dir() / f"{claim['id']}.md"


def count(w):
    return w["conn"].execute("SELECT count(*) FROM requisition").fetchone()[0]


def state_of(w, rid):
    return w["conn"].execute("SELECT state FROM requisition WHERE id = ?", (rid,)).fetchone()[0]


def test_add_show_and_close_carry_the_path_and_the_turn(capsys, world, ready):
    nowhere = add(capsys, world, "ding", "daz_studio")
    assert nowhere["turn"] == "build" and nowhere["turn_line"] == "No path yet: a process has to be built"
    assert set(nowhere["path"]) == {"status", "route", "processes", "process", "problem", "source_entry_id"}
    assert nowhere["path"]["status"] == "none" and world["envs"]["daz_studio"]["name"] in nowhere["path"]["problem"]
    code, out, _ = claim_cmd(capsys, world, "show", nowhere["id"], "--json")
    assert code == 0 and json.loads(out) == nowhere
    code, out, _ = claim_cmd(capsys, world, "show", nowhere["id"])
    assert "turn: build" in out and "turn_line: No path yet" in out and "path: {'status': 'none'" in out
    code, out, _ = claim_cmd(capsys, world, "close", nowhere["id"], "--json")
    closed = json.loads(out)
    assert code == 0 and closed["turn"] == "none" and closed["turn_line"] == "" and closed["path"]["status"] == "none"
    assert closed["closed"]


def test_the_untrusted_and_unmet_paths_in_json(capsys, world, monkeypatch):
    use(monkeypatch, registry_with("to_daz", trusted=False))
    claim = add(capsys, world, "barrel", "daz_studio")
    assert claim["path"]["status"] == "not_ready" and claim["path"]["process"] == "to_daz"
    assert claim["turn"] == "you" and claim["turn_line"] == "Set up to_daz: trust it"
    use(monkeypatch, registry_with("to_daz"))
    code, out, _ = claim_cmd(capsys, world, "show", claim["id"], "--json")
    assert json.loads(out)["turn_line"].startswith("Set up to_daz: fix ")


def test_walk_queues_and_records_the_uid(capsys, world, ready):
    claim = add(capsys, world, "barrel", "loose_files", "--note", "mine")
    before = claim_file(claim).read_text(encoding="utf-8").splitlines()
    code, out, err = claim_cmd(capsys, world, "walk", claim["id"], "--json")
    data = json.loads(out)
    assert code == 0 and err == ""
    rid = data["requisition"]["id"]
    row = world["conn"].execute("SELECT uid, state FROM requisition WHERE id = ?", (rid,)).fetchone()
    assert data["requisition"]["uid"] == row["uid"] and row["state"] == "queued"
    assert data["requisitions"] == [row["uid"]]
    assert (data["turn"], data["turn_line"]) == ("exchange", "")
    text = claim_file(claim).read_text(encoding="utf-8")
    after = text.splitlines()
    assert row["uid"] in text and claims.read_one(world["conn"], claim["id"]).meta["requisitions"] == [row["uid"]]
    keep = lambda lines: [line for line in lines  # noqa: E731
                          if not line.startswith(("requisitions:", "milestone:")) and row["uid"] not in line]
    assert keep(after) == keep(before)


def test_walk_text_names_the_claim_and_the_requisition(capsys, world, ready):
    claim = add(capsys, world, "barrel", "loose_files")
    code, out, _ = claim_cmd(capsys, world, "walk", claim["id"])
    rid = world["conn"].execute("SELECT id FROM requisition").fetchone()[0]
    assert code == 0 and claim["id"] in out and f"requisition {rid}" in out


def test_walk_refusals_write_nothing(capsys, world, monkeypatch):
    use(monkeypatch, registry_with("stamp_images", "to_daz", trusted=False))
    untrusted = add(capsys, world, "barrel", "daz_studio")
    use(monkeypatch, registry_with("stamp_images"))
    nowhere = add(capsys, world, "ding", "daz_studio")
    queued = add(capsys, world, "barrel", "loose_files")
    held = add(capsys, world, "barrel", "loose_files")
    closed = add(capsys, world, "ding", "loose_files")
    assert claim_cmd(capsys, world, "close", closed["id"])[0] == 0
    assert claim_cmd(capsys, world, "walk", queued["id"])[0] == 0
    code, out, _ = claim_cmd(capsys, world, "walk", held["id"], "--json")
    held_rid = json.loads(out)["requisition"]["id"]
    lifecycle.hold(world["conn"], held_rid)

    def refused(claim, *expect):
        before, rows = claim_file(claim).read_bytes(), count(world)
        code, out, err = claim_cmd(capsys, world, "walk", claim["id"])
        assert code == 2 and err.startswith("exchange: error:") and out == ""
        assert all(text in err for text in expect), err
        assert claim_file(claim).read_bytes() == before and count(world) == rows

    refused(nowhere, "No path yet")
    use(monkeypatch, registry_with("stamp_images", "to_daz", trusted=False))
    refused(untrusted, "Set up to_daz")
    refused(queued, "Exchange's turn")
    refused(held, f"Release requisition {held_rid}")
    refused(closed, "is closed")
    data = json.loads(claim_cmd(capsys, world, "show", held["id"], "--json")[1])
    assert (data["turn"], data["turn_line"]) == ("you", f"Release requisition {held_rid}")


def test_walk_run_ends_installed_and_runs_only_that_requisition(capsys, world, ready):
    registry = registry_with("stamp_images")
    other = queue_plan(world["conn"], plan_requisition(
        world["conn"], world["definitions"], registry, world["barrel"], world["envs"]["loose_files"]["id"],
        processes=["copy_entry"]), registry)
    claim = add(capsys, world, "barrel", "loose_files")
    code, out, err = claim_cmd(capsys, world, "walk", claim["id"], "--run", "--json")
    data = json.loads(out)
    assert code == 0 and err == ""
    assert data["requisition"]["state"] == "fulfilled" and data["milestone"] == "installed"
    assert data["turn"] == "you" and data["turn_line"] == "Close it, or take it into play"
    assert "milestone: installed" in claim_file(claim).read_text(encoding="utf-8")
    assert state_of(world, other) == "queued"


def test_walk_run_prints_progress_on_stderr_and_the_turn(capsys, world, ready):
    claim = add(capsys, world, "barrel", "loose_files")
    code, out, err = claim_cmd(capsys, world, "walk", claim["id"], "--run")
    assert code == 0 and "·" in err and "fulfilled" in out and "turn: you" in out and "Close it" in out


def test_a_failed_run_shows_in_show(capsys, world, ready):
    claim = add(capsys, world, "barrel", "loose_files")
    assert claim_cmd(capsys, world, "walk", claim["id"])[0] == 0
    (world["loose"] / "Downloads" / "barrel" / "Barrel01.fbx").unlink()
    rid = world["conn"].execute("SELECT id FROM requisition").fetchone()[0]
    run_queue(world["db"], world["definitions"], registry_with("stamp_images"), only=[rid])
    data = json.loads(claim_cmd(capsys, world, "show", claim["id"], "--json")[1])
    assert data["turn"] == "you" and "source file missing" in data["turn_line"]
    out = claim_cmd(capsys, world, "show", claim["id"])[1]
    assert any(line.startswith(f"{data['requisitions'][0]}  {rid}  failed") for line in out.splitlines())


def test_show_lists_a_removed_uid(capsys, world, ready):
    claim = add(capsys, world, "barrel", "loose_files")
    claims.update(claims.read_one(world["conn"], claim["id"]), {"requisitions": ["gone-uid"]})
    out = claim_cmd(capsys, world, "show", claim["id"])[1]
    assert "gone-uid  removed" in out.splitlines()


def test_a_relative_folder_lands_under_the_places_root(capsys, world, ready):
    claim = add(capsys, world, "barrel", "loose_files", "--folder", "Props/Barrels")
    code, out, _ = claim_cmd(capsys, world, "walk", claim["id"], "--json")
    folder = lifecycle.detail(world["conn"], json.loads(out)["requisition"]["id"])["endpoint"]["folder"]
    assert code == 0 and folder.replace("\\", "/").endswith("/Assets/Props/Barrels")


def test_list_shows_the_turn_and_filters_on_it(capsys, world, ready):
    build = add(capsys, world, "ding", "daz_studio")
    waiting = add(capsys, world, "barrel", "loose_files")
    walked = add(capsys, world, "barrel", "loose_files")
    assert claim_cmd(capsys, world, "walk", walked["id"])[0] == 0
    out = claim_cmd(capsys, world, "list")[1]
    rows = {line.split()[0]: line.split() for line in out.splitlines()}
    assert rows[build["id"]][2] == "build" and rows[waiting["id"]][2] == "you" and rows[walked["id"]][2] == "exchange"
    out = claim_cmd(capsys, world, "list", "--turn", "build")[1]
    assert build["id"] in out and waiting["id"] not in out and walked["id"] not in out
    data = json.loads(claim_cmd(capsys, world, "list", "--turn", "exchange", "--json")[1])
    assert [c["id"] for c in data["claims"]] == [walked["id"]] and data["problems"] == []
    assert {"path", "turn", "turn_line"} <= set(data["claims"][0])
    with pytest.raises(SystemExit):  # not one of you, exchange, build
        claim_cmd(capsys, world, "list", "--turn", "nobody")
