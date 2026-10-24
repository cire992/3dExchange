"""Project homes (Roadmap phase 7a): creating them, the formats, record schemas, validation, links
(records and dossiers), checkpoints and choosing a project."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

import pytest

from exchange.cli import main
from exchange.curation import Curator
from exchange.db import open_library
from exchange.projects import frontmatter
from exchange.projects import git as project_git
from exchange.projects.home import ProjectError, init_home, load_home, resolve_project, write_config
from exchange.projects.schema import SchemaError, load_builtin_schemas, parse_schema, signature_of
from exchange.projects.validate import validate_home


@pytest.fixture(autouse=True)
def git_identity():
    write_config(git_name="Exchange Tests", git_email="tests@example.invalid")


@pytest.fixture
def home(tmp_path):
    made, warnings = init_home(tmp_path / "homes" / "Sirenne", git=False)
    assert warnings == []
    return made


def write_record(home, editor_id: str, maturity=0, body="Prose.", **fields) -> Path:
    path = home.records_dir / signature_of(editor_id) / f"{editor_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(frontmatter.dump({"id": editor_id, "maturity": maturity, **fields}, body), encoding="utf-8")
    return path


def write_claim(home, claim_id: str, **meta) -> Path:
    path = home.claims_dir / f"{claim_id}.md"
    meta = {"id": claim_id, "status": "idea", "created": claim_id[:10], **meta}
    path.write_text(frontmatter.dump(meta, "A claim."), encoding="utf-8")
    return path


def validate(home, **kwargs):
    kwargs.setdefault("processes", {"daz-g9-to-g8-to-ue"})
    return validate_home(home, **kwargs)


def messages(report, severity=None):
    return [f.message for f in report.findings if severity is None or f.severity == severity]


# Creating a project home ---------------------------------------------------------------------


def test_init_creates_the_layout_and_a_first_commit(tmp_path):
    made, warnings = init_home(tmp_path / "NJO", kind="unreal")
    assert warnings == []
    for name in ("exchange.project.toml", "IDENTITY.md", "goals.md", "coverage-rules.yaml", ".gitignore",
                 "records", "claims", "schemas"):
        assert (made.path / name).exists(), name
    assert (made.name, made.kind) == ("NJO", "unreal")
    log = subprocess.run(["git", "log", "--format=%an <%ae>|%s"], cwd=made.path, capture_output=True, text=True).stdout
    assert log.strip() == "Exchange Tests <tests@example.invalid>|Project home created by Exchange: NJO"
    report = validate(made)
    assert report.findings == [] and report.gaps == []


def test_init_refuses_a_folder_with_files_or_one_inside_a_home(tmp_path, home):
    (tmp_path / "busy").mkdir()
    (tmp_path / "busy" / "notes.txt").write_text("x")
    with pytest.raises(ProjectError, match="not empty"):
        init_home(tmp_path / "busy", git=False)
    with pytest.raises(ProjectError, match="inside the project home"):
        init_home(home.path / "records" / "nested", git=False)
    with pytest.raises(ProjectError, match="already a project home"):
        init_home(home.path, git=False)
    (tmp_path / "empty").mkdir()
    assert init_home(tmp_path / "empty", git=False)[0].name == "empty"  # an empty folder is fine


# Front matter and schemas ----------------------------------------------------------------------


def test_front_matter_errors_name_the_line_and_repeated_keys():
    with pytest.raises(frontmatter.FrontMatterError, match="no front matter"):
        frontmatter.parse("# just text\n")
    with pytest.raises(frontmatter.FrontMatterError, match="no closing"):
        frontmatter.parse("---\nid: X\n")
    with pytest.raises(frontmatter.FrontMatterError, match=r"line 3: .*'id' appears twice"):
        frontmatter.parse("---\nid: A\nid: B\n---\n")
    doc = frontmatter.parse(frontmatter.dump({"id": "NPC_A", "look": {"dossier": "abc"}}, "Body"))
    assert doc.meta == {"id": "NPC_A", "look": {"dossier": "abc"}} and doc.body == "Body\n"


def test_the_core_schemas_load():
    types = load_builtin_schemas()
    assert set(types) == {"NPC_", "RACE", "FACT", "LOT_"}
    assert types["NPC_"].fields["race"].to == ("RACE",)
    assert types["FACT"].template_field == "template"
    assert signature_of("NPC_DockMaster") == "NPC_" and signature_of("FACT_PortAuthority") == "FACT"
    assert signature_of("NPC__X") is None and signature_of("npc_x") is None and signature_of("FACTPort") is None


@pytest.mark.parametrize("text, problem", [
    ("signature: PACK\nfields: {x: {type: blob}}", "type must be one of"),
    ("signature: PACK\nfields: {x: {type: link}}", "needs 'to'"),
    ("signature: PACK\nfields: {x: {type: enum}}", "needs 'values'"),
    ("signature: PACK\nfields: {x: {type: text, colour: red}}", "unknown keys colour"),
    ("signature: PACK\nfields: {name: text}", "common to every record"),
    ("signature: pack\nfields: {}", "four capitals"),
    ("signature: CELL\nfields: {}", "named CELL.yaml"),
    ("signature: PACK\nfields: {x: {type: text, required_at: final}}", "maturity level"),
])
def test_bad_schemas_say_why(text, problem):
    with pytest.raises(SchemaError, match=problem):
        parse_schema(text, Path("PACK.yaml"), builtin=False)


def test_project_schemas_add_signatures_but_never_change_the_core_ones(home):
    (home.schemas_dir / "PACK.yaml").write_text("signature: PACK\ntitle: AI package\nfields:\n  hours: { type: text }\n")
    (home.schemas_dir / "RACE.yaml").write_text("signature: RACE\nfields: {}\n")
    (home.schemas_dir / "BAD_.yaml").write_text("signature: BAD_\nfields: {x: {type: nope}}\n")
    report = validate(home)
    assert "PACK" in report.schemas and report.schemas["RACE"].builtin
    errors = messages(report, "error")
    assert any("RACE is defined by Exchange itself" in m for m in errors)
    assert any("type must be one of" in m for m in errors)


# Records ---------------------------------------------------------------------------------------


def test_record_files_must_match_their_id_folder_and_format(home):
    write_record(home, "NPC_DockMaster")
    bad = home.records_dir / "NPC_" / "NPC_Other.md"
    bad.write_text(frontmatter.dump({"id": "NPC_Wrong", "maturity": 0}))
    (home.records_dir / "FACT").mkdir()
    (home.records_dir / "FACT" / "NPC_Lost.md").write_text(frontmatter.dump({"id": "NPC_Lost", "maturity": 0}))
    (home.records_dir / "NPC_" / "NPC_Bad Name.md").write_text(frontmatter.dump({"id": "NPC_Bad Name", "maturity": 0}))
    (home.records_dir / "NPC_" / "NPC_NoMaturity.md").write_text(frontmatter.dump({"id": "NPC_NoMaturity"}))
    (home.records_dir / "NPC_" / "NPC_Named.md").write_text(frontmatter.dump({"id": "NPC_Named", "maturity": "spec"}))
    (home.records_dir / "NPC_" / "NPC_Broken.md").write_text("---\nid: [unclosed\n---\n")
    (home.records_dir / "notes").mkdir()
    report = validate(home)
    errors = messages(report, "error")
    assert any("does not match the file name NPC_Other.md" in m for m in errors)
    assert any("NPC_Lost is a NPC_ record but sits in records/FACT" in m for m in errors)
    assert any("is not an editor ID" in m for m in errors)
    assert any("no 'maturity'" in m for m in errors)
    assert any("maturity must be a number from 0 to 4: use 1 for Spec" in m for m in errors)
    assert any(f.path == "records/NPC_/NPC_Broken.md" and "line" in f.message for f in report.errors)
    assert any("notes is not a signature" in m for m in messages(report, "warning"))
    assert set(report.records) == {"npc_dockmaster", "npc_nomaturity", "npc_named"}


def test_fields_are_checked_against_the_schema(home):
    write_record(home, "RACE_Human", 1, kind="humanoid")
    write_record(home, "NPC_DockMaster", 1, race="RACE_Human", mood="grumpy",
                 kin=[{"npc": "NPC_DockMaster", "relation": "cousin"}],
                 schedule=[{"hours": "6-18", "location": "LOT_Office"}, {"location": "LOT_Office"}],
                 factions="FACT_PortAuthority")
    write_record(home, "RACE_Droid", 1)  # Spec without its kind
    write_record(home, "FACT_Guild", 0, template="guild", lineage="old", ranks=["Apprentice", "Master"])
    write_record(home, "LOT_Office", 0)
    report = validate(home)
    errors = messages(report, "error")
    assert any("kin[0].relation should be one of parent, child, spouse, sibling" in m for m in errors)
    assert any("schedule[0].hours '6-18' does not match" in m for m in errors)
    assert any("schedule[1].hours is empty" in m for m in errors)
    assert any("factions should be a list" in m for m in errors)
    assert any("RACE_Droid is marked Spec (1), but kind is empty" in m for m in errors)
    warnings = messages(report, "warning")
    assert any("mood is not a field of NPC_ records" in m for m in warnings)
    assert any("lineage is not a field of a guild faction" in m for m in warnings)
    assert not any("ranks" in m for m in warnings)


def test_records_without_a_schema_get_their_id_and_maturity_checked(home):
    write_record(home, "PACK_Work", 0, anything="goes")
    write_record(home, "PACK_Sleep")
    report = validate(home)
    assert report.errors == []
    assert messages(report, "warning") == ["PACK has no schema yet: only its records' id and maturity are checked"]


# Links and gaps -------------------------------------------------------------------------------


def test_links_open_gaps_by_maturity(home):
    write_record(home, "RACE_Human", 0)
    write_record(home, "FACT_PortAuthority", 1, template="company")
    write_record(home, "LOT_Office", 1, within="DIST_LowerDocks")
    write_record(home, "LOT_SaltRowCantina", 0)
    write_record(home, "NPC_DockMaster", 2, race="RACE_Human",
                 look={"dossier": "0" * 32, "process": "daz-g9-to-g8-to-ue"},
                 factions=[{"faction": "FACT_PortAuthority", "rank": "Harbormaster"}],
                 schedule=[{"hours": "06-18", "location": "LOT_Office", "package": "PACK_Work"},
                           {"hours": "18-24", "location": "LOT_SaltRowCantina", "package": "PACK_Socialize"},
                           {"hours": "00-06", "location": "LOT_Home"}],
                 kin=[{"npc": "FACT_PortAuthority", "relation": "parent"}])
    write_record(home, "NPC_Sketchy", 0, race="RACE_Nobody")  # a Sketch's links are not checked
    report = validate(home)
    gaps = {(g.kind, g.target, g.field): g for g in report.gaps if g.kind != "dossier"}
    assert set(gaps) == {
        ("immature", "RACE_Human", "race"),
        ("immature", "LOT_SaltRowCantina", "schedule[1].location"),
        ("missing", "LOT_Home", "schedule[2].location"),
    }
    # A Stub needs its links at no more than Spec (the default cap).
    assert gaps[("immature", "RACE_Human", "race")].required == 1
    assert gaps[("missing", "LOT_Home", "schedule[2].location")].needed_by == "NPC_DockMaster"
    assert "which is a Sketch (0); it needs Spec (1)" in gaps[("immature", "LOT_SaltRowCantina", "schedule[1].location")].message
    assert any("kin[0].npc links to FACT_PortAuthority, a FACT record; it takes NPC_" in m for m in messages(report, "error"))
    warnings = messages(report, "warning")
    assert any("links to PACK_Work, which has no record yet (PACK has no schema" in m for m in warnings)
    assert any("within links to DIST_LowerDocks" in m for m in warnings)
    assert not any("RACE_Nobody" in m for m in messages(report))


def test_a_link_demands_no_more_than_the_record_s_own_maturity(home):
    write_record(home, "RACE_Human", 1, kind="humanoid")
    write_record(home, "NPC_A", 1, race="RACE_Human")
    write_record(home, "NPC_B", 1, race="RACE_human")  # editor IDs ignore case
    write_record(home, "NPC_C", 1, race="race_human")  # but the signature is always capitals
    report = validate(home)
    assert report.gaps == []
    assert messages(report, "warning") == ["race says RACE_human; the record is RACE_Human"]
    assert messages(report, "error") == ["race should be an editor ID such as RACE_Name, not 'race_human'"]


def test_project_schemas_take_part_in_gaps(home):
    (home.schemas_dir / "PACK.yaml").write_text("signature: PACK\nfields: {}\n")
    write_record(home, "RACE_Human", 1, kind="humanoid")
    write_record(home, "NPC_A", 1, race="RACE_Human", schedule=[{"hours": "06-18", "location": "LOT_Home", "package": "PACK_Work"}])
    write_record(home, "LOT_Home", 1, within="DIST_X")
    report = validate(home)
    assert [(g.kind, g.target) for g in report.gaps] == [("missing", "PACK_Work")]


# Dossier links ----------------------------------------------------------------------------------


@pytest.fixture
def library(loose_folder, scan, db_path):
    scan(loose_folder)
    conn = open_library(db_path)
    rows = {r["name"]: r["uid"] for r in conn.execute("SELECT name, uid FROM dossier")}
    conn.close()
    return rows


def test_dossier_links_resolve_against_the_library(home, library, db_path, definitions, loose_folder, scan):
    write_record(home, "RACE_Human", 1, kind="humanoid")
    blue, pink, barrel = library["Donut01_Blue"], library["Donut01_Pink"], library["Barrel01"]
    for name, uid in (("NPC_Fine", barrel), ("NPC_Merged", blue), ("NPC_Lost", "f" * 32), ("NPC_Gone", pink)):
        write_record(home, name, 0, look={"dossier": uid})
    conn = open_library(db_path)
    Curator(conn, definitions).merge(blue, barrel)
    conn.commit()
    conn.close()
    (loose_folder / "Downloads" / "props" / "Donut01_Pink.glb").unlink()
    scan(loose_folder)  # the pink donut's entry is retired; its uid stays
    report = validate(home, db_path=db_path)
    gaps = {g.target: g for g in report.gaps}
    assert set(gaps) == {"NPC_Lost", "NPC_Gone"}
    assert gaps["NPC_Lost"].dossier_state == "missing" and gaps["NPC_Gone"].dossier_state == "retired"
    assert gaps["NPC_Gone"].kind == "dossier" and gaps["NPC_Gone"].field == "look.dossier"
    assert any(f"was merged into {barrel}" in m for m in messages(report, "warning"))


def test_without_a_library_dossier_links_are_not_checked(home, tmp_path):
    write_record(home, "NPC_A", 0, look={"dossier": "a" * 32})
    write_record(home, "NPC_B", 0, look={"dossier": "b" * 32})
    report = validate(home, db_path=tmp_path / "none.db")
    assert report.gaps == []
    assert [m for m in messages(report, "warning") if "not checked" in m] == \
        [f"dossier links are not checked: no library database at {tmp_path / 'none.db'}"]


def test_unknown_processes_are_warnings(home):
    write_record(home, "NPC_A", 0, look={"dossier": "a" * 32, "process": "no-such-process"})
    report = validate(home, processes=set())
    assert any("there is no process 'no-such-process' yet" in m for m in messages(report, "warning"))
    assert report.errors == []


# Claims, goals, identity and coverage rules -------------------------------------------------


def test_claims_are_checked(home):
    home.goals_path.write_text(frontmatter.dump({"goals": [
        {"id": "G1", "title": "Docks", "status": "active", "done_when": "The docks are playable"}]}))
    write_record(home, "NPC_DockMaster", 0)
    write_claim(home, "2026-10-24-a-good-one", target="NPC_DockMaster", goal="G1", status="open",
                links=["claim:2026-10-24-unfiled-idea", "NPC_DockMaster", "goal:G1"])
    write_claim(home, "2026-10-24-unfiled-idea")
    write_claim(home, "2026-10-24-problems", status="finished", source="hunch", target="dockmaster",
                goal="G9", needed_by=["NPC_Nobody"], links=["what:ever", "claim:2026-01-01-nope"], triage="later")
    write_claim(home, "2026-10-25-wrong-date", created="2026-10-24", target="LOT_Unwritten", status="claimed")
    (home.claims_dir / "Not A Claim.md").write_text(frontmatter.dump({"id": "x", "status": "idea", "created": "2026-10-24"}))
    report = validate(home)
    by_claim: dict[str, list[str]] = {}
    for f in report.findings:
        by_claim.setdefault(f.subject, []).append(f.message)
    assert "2026-10-24-a-good-one" not in by_claim
    assert by_claim["2026-10-24-unfiled-idea"] == ["unfiled: the claim has no target record"]
    problems = " | ".join(by_claim["2026-10-24-problems"])
    for expected in ("status must be one of", "source must be one of", "target must be a record's editor ID",
                     "goal G9 is not in goals.md", "needed_by: NPC_Nobody has no record",
                     "unknown kind of reference what:", "there is no claim 2026-01-01-nope",
                     "triage is 'new' or 'seen'"):
        assert expected in problems, expected
    wrong = " | ".join(by_claim["2026-10-25-wrong-date"])
    assert "is not the date in the file name" in wrong and "target LOT_Unwritten has no record yet" in wrong
    assert "claimed, but claimed_by is empty" in wrong
    assert any("file name is its date and a slug" in m for m in by_claim["Not A Claim"])


def test_gap_claims_may_target_records_that_do_not_exist_yet(home):
    write_claim(home, "2026-10-24-spec-lot-home", source="gap", target="LOT_Home", status="open", triage="new")
    assert validate(home).findings == []


def test_goals_identity_and_coverage_rules(home):
    home.goals_path.write_text(frontmatter.dump({"goals": [
        {"id": "G1", "title": "A", "status": "active", "done_when": "x"},
        {"id": "G1", "title": "B", "status": "active", "done_when": "y"},
        {"id": "Goal 2", "title": "C"},
        {"id": "G3", "title": "", "status": "someday"}]}))
    home.identity_path.write_text("# Sirenne\n\n## Premise\n\nA city.\n\n## Pillars\n\n1. Sprawl.\n")
    home.coverage_path.write_text(
        "version: 1\nrules:\n"
        "  - { id: district-has-vendor, for: DIST, says: Every District has a vendor. }\n"
        "  - { id: district-has-vendor, for: NPC_, says: Again. }\n"
        "  - { id: Bad Rule, for: npc, says: '', expect: [1] }\n")
    report = validate(home)
    text = " | ".join(f"{f.path}: {f.message}" for f in report.findings)
    for expected in ("goals.md: G1 is listed twice", "goals.md: goals[2]: id must look like G1",
                     "goals.md: G3 has no title", "goals.md: G3: status must be one of",
                     "IDENTITY.md: no '## Feel' section", "IDENTITY.md: no '## Amendment log' section",
                     "coverage-rules.yaml: district-has-vendor is listed twice",
                     "coverage-rules.yaml: Bad Rule: id must be lowercase",
                     "'for' must be a signature", "'says' must state the rule", "'expect' must be a mapping",
                     "district-has-vendor: DIST has no schema yet"):
        assert expected in text, expected


def test_a_large_home_validates_quickly(home):
    write_record(home, "RACE_Human", 1, kind="humanoid")
    for i in range(400):
        write_record(home, f"LOT_Lot{i}", 1, within="DIST_Docks")
    for i in range(1600):
        write_record(home, f"NPC_Person{i}", 1, race="RACE_Human",
                     schedule=[{"hours": "06-18", "location": f"LOT_Lot{i % 400}"},
                               {"hours": "18-24", "location": f"LOT_Lot{(i + 1) % 400}"}])
    validate(home)  # the first read of files just written pays for the virus scanner (7 ms a file here)
    started = time.perf_counter()
    report = validate(home)
    elapsed = time.perf_counter() - started
    assert len(report.records) == 2001 and report.errors == [] and report.gaps == []
    assert elapsed < 5, elapsed  # about 0.75 s on the dev machine


# Checkpoints ----------------------------------------------------------------------------------


def git_log(path: Path) -> list[str]:
    return subprocess.run(["git", "log", "--format=%s"], cwd=path, capture_output=True, text=True).stdout.split("\n")[:-1]


def test_a_checkpoint_commits_everything_but_the_cache_and_never_an_empty_commit(tmp_path):
    made, _ = init_home(tmp_path / "Home")
    write_record(made, "NPC_A")
    (made.cache_dir).mkdir()
    (made.cache_dir / "hints.json").write_text("{}")
    first = project_git.checkpoint(made.path, "bypassed session: Codex 'Docks'")
    assert first.committed and first.changed == 1
    assert git_log(made.path)[0] == "Checkpoint: bypassed session: Codex 'Docks'"
    tracked = subprocess.run(["git", "ls-files"], cwd=made.path, capture_output=True, text=True).stdout
    assert "records/NPC_/NPC_A.md" in tracked and ".exchange" not in tracked
    again = project_git.checkpoint(made.path, "again")
    assert not again.committed and again.commit == first.commit and len(git_log(made.path)) == 2


def test_the_cache_stays_out_even_without_its_gitignore_line(tmp_path):
    made, _ = init_home(tmp_path / "Home")
    (made.path / ".gitignore").write_text("")
    made.cache_dir.mkdir()
    (made.cache_dir / "hints.json").write_text("{}")
    assert project_git.checkpoint(made.path, "x").committed
    tracked = subprocess.run(["git", "ls-files"], cwd=made.path, capture_output=True, text=True).stdout
    assert ".gitignore" in tracked and ".exchange" not in tracked


def test_a_checkpoint_refuses_a_home_without_its_own_repository(tmp_path, home):
    with pytest.raises(project_git.GitError, match="is not a git repository"):
        project_git.checkpoint(home.path, "x")
    outer = tmp_path / "outer"
    outer.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=outer, check=True)
    inner, _ = init_home(outer / "Inner", git=False)
    with pytest.raises(project_git.GitError, match="inside the git repository"):
        project_git.checkpoint(inner.path, "x")


def test_a_checkpoint_without_any_git_identity_says_how_to_set_one(tmp_path, monkeypatch):
    made, _ = init_home(tmp_path / "Home", git=False)
    subprocess.run(["git", "init", "-q"], cwd=made.path, check=True)
    write_config(git_name="", git_email="")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "no-global"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("EMAIL", "")
    try:
        project_git.checkpoint(made.path, "x")
    except project_git.GitError as exc:
        assert "exchange project config --git-name" in str(exc)
    # (git may find an identity of its own on some machines; then the commit simply works)


# Choosing a project and the command line -------------------------------------------------------


def test_resolve_project_by_path_name_folder_and_default(tmp_path, home, monkeypatch):
    assert resolve_project(str(home.path)).path == home.path
    with pytest.raises(ProjectError, match="no project:"):
        resolve_project(None, cwd=tmp_path)
    assert resolve_project(None, cwd=home.records_dir).path == home.path
    write_config(root=str(home.path.parent), default="Sirenne")
    assert resolve_project("Sirenne", cwd=tmp_path).path == home.path
    assert resolve_project(None, cwd=tmp_path).path == home.path
    with pytest.raises(ProjectError, match="no project home at"):
        resolve_project("Missing", cwd=tmp_path)


def test_cli_init_validate_and_checkpoint(tmp_path, capsys, db_path):
    target = tmp_path / "Cli Home"
    assert main(["project", "init", str(target), "--name", "Cli", "--kind", "bethesda", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["kind"] == "bethesda"
    made = load_home(target)
    assert main(["project", "validate", "--project", str(target), "--db", str(db_path)]) == 0
    assert "No problems found." in capsys.readouterr().out
    write_record(made, "NPC_A", 1)
    assert main(["project", "validate", "--project", str(target), "--json", "--db", str(db_path)]) == 1
    data = json.loads(capsys.readouterr().out)
    assert data["counts"]["errors"] == 1 and data["findings"][0]["field"] == "race"
    assert main(["project", "checkpoint", "--for", str(made.records_dir), "--reason", "test", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["committed"] is True
    assert main(["project", "checkpoint", "--for", str(tmp_path), "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == {"project": None, "committed": False}
    assert main(["project", "checkpoint", "--project", str(tmp_path / "nowhere")]) == 2
    assert "no project home at" in capsys.readouterr().err
