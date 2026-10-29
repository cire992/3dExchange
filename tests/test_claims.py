import datetime as dt

import pytest

from exchange import claims
from exchange.curation import Curator
from exchange.db import open_library
from exchange.projects import frontmatter

TODAY = dt.date(2026, 10, 29)
KEYS = ["id", "thing", "thing_name", "as", "place", "place_name", "folder", "requisitions", "milestone",
        "created", "closed"]


@pytest.fixture
def conn(scan, loose_folder, db_path):
    scan(loose_folder)
    conn = open_library(db_path)
    yield conn
    conn.close()


def dossier(conn, name="ding"):
    return conn.execute("SELECT uid, name FROM dossier WHERE name = ?", (name,)).fetchone()


def env(conn):
    return conn.execute("SELECT id, uid, name FROM environment").fetchone()


def new(conn, **kwargs):
    return claims.new(conn, dossier(conn)["uid"], env(conn)["id"], today=TODAY, **kwargs)


def retire_ding(scan, loose_folder):
    (loose_folder / "sounds" / "ding.wav").unlink()
    scan(loose_folder)


def test_round_trip(conn):
    d, e = dossier(conn), env(conn)
    claim = new(conn, role="prop", folder="Props/Sounds", note="for the diner")
    path = claims.claims_dir() / "2026-10-29-ding.md"
    assert claim.path == path
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---")
    doc = frontmatter.parse(text)
    assert list(doc.meta) == KEYS
    assert doc.meta == {"id": "2026-10-29-ding", "thing": d["uid"], "thing_name": "ding", "as": "prop",
                        "place": e["uid"], "place_name": e["name"], "folder": "Props/Sounds",
                        "requisitions": [], "milestone": "acquired", "created": TODAY, "closed": None}
    assert doc.body == "for the diner\n"
    again = claims.read_one(conn, "2026-10-29-ding")
    assert again.meta == doc.meta and again.notes == doc.body


def test_unset_keys_are_null(conn):
    meta = frontmatter.read(new(conn).path).meta
    assert meta["as"] is None and meta["folder"] is None


def test_name_collision_numbers_the_files(conn):
    first = new(conn)
    before = first.path.read_bytes()
    second, third = new(conn), new(conn)
    assert [p.name for p in (first.path, second.path, third.path)] == [
        "2026-10-29-ding.md", "2026-10-29-ding-2.md", "2026-10-29-ding-3.md"]
    assert first.path.read_bytes() == before


def test_unknown_dossier_or_environment_writes_nothing(conn):
    with pytest.raises(claims.ClaimError, match="nosuch"):
        claims.new(conn, "nosuch", env(conn)["id"])
    with pytest.raises(claims.ClaimError, match="environment 999"):
        claims.new(conn, dossier(conn)["uid"], 999)
    assert not claims.claims_dir().exists()


def test_a_renamed_dossier_is_claimed_by_its_current_name(conn, definitions):
    Curator(conn, definitions).set_field([dossier(conn)["uid"]], "name", "Door Ding")
    assert new(conn).meta["thing_name"] == "Door Ding"


def test_broken_file_is_a_problem_not_a_crash(conn):
    good = new(conn)
    bad = claims.claims_dir() / "2026-10-29-bad.md"
    bad.write_text("---\nid: x\nid: y\n---\n", encoding="utf-8")
    found, problems = claims.read_all(conn)
    assert [c.id for c in found] == [good.id]
    assert len(problems) == 1 and "2026-10-29-bad.md" in problems[0]
    with pytest.raises(claims.ClaimError, match="2026-10-29-bad.md"):
        claims.read_one(conn, "2026-10-29-bad")


def test_no_folder_means_no_claims(conn):
    assert claims.read_all(conn) == ([], [])


def test_read_one_never_builds_a_path_from_the_id(conn):
    new(conn)
    for bad in ("..\\x", "../x", "C:/x", "nosuch", "2026-10-29-DING-2"):
        with pytest.raises(claims.ClaimError):
            claims.read_one(conn, bad)


def test_acquired_and_back_to_claimed(conn, scan, loose_folder):
    claim = new(conn)
    before = claim.path.read_text(encoding="utf-8").splitlines()
    assert "milestone: acquired" in before
    retire_ding(scan, loose_folder)
    assert claims.read_one(conn, claim.id).milestone == "claimed"
    after = claim.path.read_text(encoding="utf-8").splitlines()
    assert len(before) == len(after)
    assert [(a, b) for a, b in zip(before, after) if a != b] == [("milestone: acquired", "milestone: claimed")]


def test_a_dossier_gone_from_the_library_reads_as_claimed(conn):
    claim = new(conn)
    text = claim.path.read_text(encoding="utf-8").replace(claim.meta["thing"], "gone-uid")
    claim.path.write_text(text, encoding="utf-8")
    assert claims.read_one(conn, claim.id).milestone == "claimed"


def test_hand_edits_survive_our_updates(conn, scan, loose_folder):
    claim = new(conn, note="first note")
    text = claim.path.read_text(encoding="utf-8")
    text = text.replace("thing_name: ding", "thing_name: Ding (mine)").replace("closed: null", "closed: null\npriority: high")
    text += "a hand-written line\n"
    claim.path.write_text(text, encoding="utf-8", newline="\n")
    retire_ding(scan, loose_folder)
    claims.close(conn, claim.id, "done by hand", today=TODAY)

    expected = (text.replace("milestone: acquired", "milestone: claimed").replace("closed: null", f"closed: {TODAY}")
                + "done by hand\n")
    assert claim.path.read_text(encoding="utf-8") == expected
    meta = claims.read_one(conn, claim.id).meta
    assert meta["thing_name"] == "Ding (mine)" and meta["priority"] == "high"


def test_update_refuses_keys_it_does_not_own(conn):
    claim = new(conn)
    before = claim.path.read_bytes()
    for key in ("thing_name", "id", "as", "created"):
        with pytest.raises(claims.ClaimError):
            claims.update(claim, {key: "x"})
    with pytest.raises(claims.ClaimError):
        claims.update(claim, {"milestone": "claimed", "thing_name": "x"})
    assert claim.path.read_bytes() == before


def test_close_keeps_the_milestone_and_refuses_a_second_time(conn):
    claim = new(conn)
    closed = claims.close(conn, claim.id, "done", today=TODAY)
    assert closed.milestone == "acquired" and closed.closed
    after = claim.path.read_bytes()
    with pytest.raises(claims.ClaimError, match="already closed"):
        claims.close(conn, claim.id)
    assert claim.path.read_bytes() == after


def test_closed_claims_are_not_rederived(conn, scan, loose_folder):
    claim = new(conn)
    claims.close(conn, claim.id, today=TODAY)
    before = claim.path.read_bytes()
    retire_ding(scan, loose_folder)
    assert claims.read_one(conn, claim.id).milestone == "acquired"
    assert claim.path.read_bytes() == before


def test_a_failed_milestone_write_is_a_problem(conn, scan, loose_folder, monkeypatch):
    claim = new(conn)
    retire_ding(scan, loose_folder)

    def refuse(*args, **kwargs):
        raise OSError("read-only")

    monkeypatch.setattr(claims, "update", refuse)
    found, problems = claims.read_all(conn)
    assert found[0].milestone == "claimed" and "read-only" in problems[0]
    assert claim.path.read_text(encoding="utf-8").count("milestone: acquired") == 1


def test_milestones_are_ordered():
    assert claims.MILESTONES == ("claimed", "acquired", "converted", "installed")
