"""Gap claims, dossier hints and fast capture (Roadmap phase 7b), on scratch project homes."""

from __future__ import annotations

import datetime as dt
import json
import shutil

import pytest

from exchange.cli import main
from exchange.db import open_library
from exchange.projects import frontmatter
from exchange.projects.capture import capture
from exchange.projects.claims import slug, sync_gap_claims
from exchange.projects.home import ProjectError, init_home, write_config
from exchange.projects.schema import signature_of
from exchange.projects.validate import read_hints, validate_home, write_hints

DAY1, DAY2, DAY3 = dt.date(2026, 10, 24), dt.date(2026, 10, 25), dt.date(2026, 10, 26)


@pytest.fixture
def home(tmp_path):
    write_config(git_name="Exchange Tests", git_email="tests@example.invalid")
    return init_home(tmp_path / "homes" / "Sirenne", git=False)[0]


def write_record(home, editor_id, maturity=0, body="Prose.", **fields):
    path = home.records_dir / signature_of(editor_id) / f"{editor_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(frontmatter.dump({"id": editor_id, "maturity": maturity, **fields}, body), encoding="utf-8")
    return path


def run(home, day=DAY1, db_path=None):
    report = validate_home(home, db_path=db_path, processes=set())
    write_hints(home, report.dossier_hints)
    return sync_gap_claims(home, report, today=day), report


def claims(home):
    return {p.stem: frontmatter.read(p) for p in sorted(home.claims_dir.glob("*.md"))}


def set_status(home, claim_id, status):
    path = home.claims_dir / f"{claim_id}.md"
    path.write_text(frontmatter.set_keys(path.read_text(encoding="utf-8"), {"status": status}), encoding="utf-8")


@pytest.fixture
def docks(home):
    write_record(home, "RACE_Human", 1, kind="humanoid")
    write_record(home, "LOT_SaltRowCantina", 0)
    write_record(home, "NPC_DockMaster", 1, race="RACE_Human",
                 schedule=[{"hours": "18-24", "location": "LOT_SaltRowCantina"},
                           {"hours": "06-18", "location": "LOT_Office"}])
    return home


# Opening, updating, resolving -------------------------------------------------------------------


def test_gaps_open_claims_once(docks):
    first, _ = run(docks)
    assert first.opened == ["2026-10-24-spec-lot-salt-row-cantina", "2026-10-24-spec-lot-office"]
    cantina = claims(docks)["2026-10-24-spec-lot-salt-row-cantina"]
    assert cantina.meta == {
        "id": "2026-10-24-spec-lot-salt-row-cantina", "title": "Spec LOT_SaltRowCantina", "status": "open",
        "created": "2026-10-24", "target": "LOT_SaltRowCantina", "source": "gap",
        "needed_by": ["NPC_DockMaster"], "gap": {"work": "mature", "required": 1}, "triage": "new"}
    assert "LOT_SaltRowCantina is a Sketch" in cantina.body and "schedule[0].location" in cantina.body
    office = claims(docks)["2026-10-24-spec-lot-office"]
    assert office.meta["gap"] == {"work": "mature", "required": 1, "missing": True}
    assert "does not exist yet" in office.body
    again, report = run(docks, DAY2)
    assert (again.opened, again.updated, again.resolved) == ([], [], [])
    assert len(claims(docks)) == 2
    assert report.errors == []  # the claims Exchange writes are valid claims


def test_a_new_needer_is_added_to_the_open_claim(docks):
    run(docks)
    write_record(docks, "NPC_Bartender", 1, race="RACE_Human", schedule=[{"hours": "12-24", "location": "LOT_SaltRowCantina"}])
    result, _ = run(docks, DAY2)
    assert result.opened == [] and result.updated == ["2026-10-24-spec-lot-salt-row-cantina"]
    claim = claims(docks)["2026-10-24-spec-lot-salt-row-cantina"]
    assert claim.meta["needed_by"] == ["NPC_DockMaster", "NPC_Bartender"]
    assert "- 2026-10-25: NPC_Bartender (Spec) links to LOT_SaltRowCantina" in claim.body


def test_a_higher_demand_raises_the_required_maturity(home):
    (home.schemas_dir / "PACK.yaml").write_text(
        "signature: PACK\nfields:\n  at: { type: link, to: [LOT_], max_demand: stub }\n")
    write_record(home, "LOT_Den", 1, within="DIST_Docks")
    write_record(home, "PACK_Guard", 1, at="LOT_Den")
    assert run(home)[0].opened == []
    write_record(home, "PACK_Patrol", 2, at="LOT_Den")
    result, _ = run(home, DAY2)
    assert result.opened == ["2026-10-25-stub-lot-den"]
    write_record(home, "PACK_Patrol", 1, at="LOT_Den")
    write_record(home, "LOT_Den", 0, within="DIST_Docks")
    write_record(home, "PACK_Guard", 2, at="LOT_Den")
    result, _ = run(home, DAY3)
    assert result.updated == ["2026-10-25-stub-lot-den"]  # PACK_Patrol already there; Guard joins
    assert claims(home)["2026-10-25-stub-lot-den"].meta["needed_by"] == ["PACK_Patrol", "PACK_Guard"]


def test_a_fixed_gap_moves_its_claim_to_review(docks):
    run(docks)
    write_record(docks, "LOT_SaltRowCantina", 1, within="DIST_SaltRow")
    result, _ = run(docks, DAY2)
    assert result.resolved == ["2026-10-24-spec-lot-salt-row-cantina"]
    claim = claims(docks)["2026-10-24-spec-lot-salt-row-cantina"]
    assert claim.meta["status"] == "review"
    assert "Resolved by validation on 2026-10-25" in claim.body
    assert run(docks, DAY3)[0].resolved == []  # review waits for the user; nothing more happens


def test_dropped_work_is_never_reopened_and_done_work_reopens_linked(docks):
    run(docks)
    set_status(docks, "2026-10-24-spec-lot-office", "dropped")
    set_status(docks, "2026-10-24-spec-lot-salt-row-cantina", "done")  # done, but still a Sketch
    result, _ = run(docks, DAY2)
    assert result.dropped == ["LOT_Office"]
    assert result.opened == ["2026-10-25-spec-lot-salt-row-cantina"]
    new = claims(docks)["2026-10-25-spec-lot-salt-row-cantina"]
    assert new.meta["links"] == ["claim:2026-10-24-spec-lot-salt-row-cantina"]
    assert "back after 2026-10-24-spec-lot-salt-row-cantina was done" in new.body


def test_a_needer_that_fails_to_load_does_not_resolve_its_claims(docks):
    run(docks)
    (docks.records_dir / "NPC_" / "NPC_DockMaster.md").write_text("---\nid: [broken\n---\n")
    result, report = run(docks, DAY2)
    assert report.errors and result.resolved == []
    (docks.records_dir / "NPC_" / "NPC_DockMaster.md").unlink()  # the needer is gone for real
    assert sorted(run(docks, DAY3)[0].resolved) == ["2026-10-24-spec-lot-office", "2026-10-24-spec-lot-salt-row-cantina"]


def test_claims_a_person_wrote_are_never_touched(docks):
    path = docks.claims_dir / "2026-10-20-spec-the-cantina.md"
    text = "---\nid: 2026-10-20-spec-the-cantina\nstatus: open\ncreated: 2026-10-20\ntarget: LOT_SaltRowCantina\n---\nMine.\n"
    path.write_text(text, encoding="utf-8")
    run(docks)
    write_record(docks, "LOT_SaltRowCantina", 1, within="DIST_SaltRow")
    run(docks, DAY2)
    assert path.read_text(encoding="utf-8") == text


# Editing Exchange's own claims ----------------------------------------------------------------


def test_set_keys_rewrites_only_its_keys():
    text = "---\r\nid: x\r\n# a comment\r\nneeded_by:\r\n  - A\r\n  - B\r\nstatus: open\r\n---\r\nBody\r\n"
    result = frontmatter.set_keys(text, {"needed_by": ["A", "B", "C"], "triage": "seen"}, append="- note")
    assert result == ("---\r\nid: x\r\n# a comment\r\nneeded_by: [A, B, C]\r\nstatus: open\r\ntriage: seen\r\n"
                      "---\r\nBody\r\n- note\r\n")
    tricky = "---\nstatus: open\nnote: |\n  status: closed\n---\n"
    assert frontmatter.parse(frontmatter.set_keys(tricky, {"status": "review"})).meta == \
        {"status": "review", "note": "status: closed\n"}


# Dossier hints and relink claims ---------------------------------------------------------------


def test_a_moved_asset_s_relink_claim_lists_where_it_went(home, loose_folder, scan, db_path):
    scan(loose_folder, enrich=True)
    conn = open_library(db_path)
    uid = conn.execute("SELECT uid FROM dossier WHERE name = 'Donut01_Pink'").fetchone()[0]
    conn.close()
    write_record(home, "NPC_Baker", 0, look={"dossier": uid})
    first, _ = run(home, db_path=db_path)
    assert first.opened == []
    hint = read_hints(home)[uid]
    assert hint["name"] == "Donut01_Pink" and hint["hash"] and hint["path"].endswith("Donut01_Pink.glb")
    shutil.move(loose_folder / "Downloads" / "props", loose_folder / "Downloads" / "props_moved")
    scan(loose_folder, enrich=True)
    result, report = run(home, DAY2, db_path=db_path)
    assert result.opened == ["2026-10-25-relink-npc-bakers-dossier"]
    gap = report.gaps[0]
    assert gap.dossier_state == "retired" and gap.candidates[0]["why"] == "the same file"
    claim = claims(home)["2026-10-25-relink-npc-bakers-dossier"]
    assert claim.meta["gap"] == {"work": "relink", "dossiers": [uid]}
    assert f"`dossier:{gap.candidates[0]['uid']}`, the same file" in claim.body
    # Without the library nothing is checked, so nothing is resolved.
    result, _ = run(home, DAY3, db_path=None)
    assert result.resolved == [] and read_hints(home)[uid] == hint
    write_record(home, "NPC_Baker", 0, look={"dossier": gap.candidates[0]["uid"]})
    assert run(home, DAY3, db_path=db_path)[0].resolved == ["2026-10-25-relink-npc-bakers-dossier"]


# Fast capture --------------------------------------------------------------------------------


def test_capture_makes_sketch_records_and_idea_claims(home):
    made = capture(home, "NPC_DockMaster: gruff harbormaster who hates the Port Authority", today=DAY1)
    assert made.kind == "record" and made.warnings == []
    doc = frontmatter.read(made.path)
    assert doc.meta == {"id": "NPC_DockMaster", "maturity": 0}
    assert doc.body == "gruff harbormaster who hates the Port Authority\n"
    with pytest.raises(ProjectError, match="already exists"):
        capture(home, "NPC_dockmaster another")
    assert "PACK has no schema yet" in capture(home, "PACK_Work").warnings[0]
    idea = capture(home, "What if the House secretly funds the gang?", today=DAY1)
    assert idea.id == "2026-10-24-what-if-the-house-secretly-funds-the-gang"
    assert idea.warnings[0].startswith("unfiled")
    same = capture(home, "What if the House secretly funds the gang?", on="FACT_House", goal="G1", today=DAY1)
    assert same.id == "2026-10-24-what-if-the-house-secretly-funds-the-gang-2"
    assert frontmatter.read(same.path).meta == {
        "id": same.id, "status": "idea", "created": "2026-10-24", "source": "manual",
        "target": "FACT_House", "goal": "G1"}
    assert same.warnings == ["FACT_House has no record yet"]
    report = validate_home(home, processes=set())
    assert report.errors == []
    with pytest.raises(ProjectError, match="not an editor ID"):
        capture(home, "an idea", on="the house")
    assert slug("NPC_DockMaster's look") == "npc-dock-masters-look"


def test_capture_claims_and_ack_on_the_command_line(docks, capsys, monkeypatch):
    monkeypatch.chdir(docks.records_dir)  # the project holding the current folder
    assert main(["capture", "LOT_Office:", "the", "harbormaster's", "office", "--maturity", "spec"]) == 0
    out = capsys.readouterr().out
    assert "Record LOT_Office: records/LOT_/LOT_Office.md" in out and "created at Spec" in out
    assert frontmatter.read(docks.records_dir / "LOT_" / "LOT_Office.md").meta["maturity"] == 1
    assert main(["project", "validate"]) == 1  # LOT_Office is Spec without its 'within'
    capsys.readouterr()
    assert main(["project", "claims", "list", "--new", "--json"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert [r["id"] for r in rows] == ["%s-spec-lot-salt-row-cantina" % dt.date.today().isoformat()]
    assert main(["project", "claims", "ack"]) == 2
    assert "pass --all" in capsys.readouterr().err
    assert main(["project", "claims", "ack", "--all"]) == 0
    assert "Acknowledged 1 claims" in capsys.readouterr().out
    assert main(["project", "claims", "list", "--new"]) == 0
    assert capsys.readouterr().out.strip() == "No claims."
    assert main(["capture", "x", "--maturity", "final"]) == 2
