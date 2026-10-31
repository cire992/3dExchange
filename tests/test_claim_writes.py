"""Claim files are rewritten safely while the service reads them on several threads (R4a)."""

import datetime as dt
import threading

import pytest

from exchange import claims
from exchange.db import open_library_readonly
from test_claim_paths import world  # noqa: F401  (the fixture)

TODAY = dt.date(2026, 10, 29)
WRITERS, ROUNDS = 16, 4


def stale(world):
    """A claim whose saved milestone is wrong, with a hand-added key and a hand-written note line; and
    the text its file should have once the milestone is right."""
    claim = claims.new(world["conn"], world["ding"], world["envs"]["loose_files"]["id"], note="first note",
                       today=TODAY)
    text = claim.path.read_text(encoding="utf-8")
    expected = text.replace("---\n", "---\npriority: high\n", 1) + "my own line\n"
    claim.path.write_text(expected.replace("milestone: acquired", "milestone: claimed"), encoding="utf-8",
                          newline="\n")
    return claim, expected


def run_threads(targets):
    errors = []

    def guarded(target):
        try:
            target()
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=guarded, args=(t,)) for t in targets]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return errors


def test_many_updates_lose_nothing(world):
    claim, _ = stale(world)
    copies = [claims.Claim(claim.id, claim.path, dict(claim.meta)) for _ in range(WRITERS)]

    def writer(n, mine):
        def work():
            for i in range(ROUNDS):
                claims.update(mine, {"milestone": claims.MILESTONES[(n + i) % 4]}, append=f"line {n}.{i}")
        return work

    assert run_threads([writer(n, c) for n, c in enumerate(copies)]) == []
    text = claim.path.read_text(encoding="utf-8")
    for n in range(WRITERS):
        for i in range(ROUNDS):
            assert f"line {n}.{i}\n" in text
    assert "first note\nmy own line\n" in text and "priority: high\n" in text
    assert sorted(p.name for p in claims.claims_dir().iterdir()) == [claim.path.name]


def test_readers_during_writes(world, db_path):
    claim, _ = stale(world)
    seen, start = [], threading.Barrier(5)

    def writer():
        mine = claims.Claim(claim.id, claim.path, dict(claim.meta))
        start.wait()
        for i in range(30):
            claims.update(mine, {"milestone": claims.MILESTONES[i % 4]}, append=f"w{i}")

    def reader():
        conn = open_library_readonly(db_path)
        try:
            start.wait()
            for _ in range(60):
                seen.append(claims.read_one(conn, claim.id).meta.get("priority"))
        finally:
            conn.close()

    assert run_threads([writer, writer, reader, reader, reader]) == []
    assert seen == ["high"] * 180
    assert [p.suffix for p in claims.claims_dir().iterdir()] == [".md"]


def test_a_failed_replace_leaves_the_file_and_is_a_problem_line(world, monkeypatch):
    claim, _ = stale(world)
    before = claim.path.read_bytes()

    def refuse(src, dst):
        raise OSError("refused")

    monkeypatch.setattr(claims.os, "replace", refuse)
    found, problems = claims.read_all(world["conn"])
    assert [c.milestone for c in found] == ["acquired"]
    assert len(problems) == 1 and problems[0].startswith(claim.path.name) and "refused" in problems[0]
    assert claim.path.read_bytes() == before
    assert [p.suffix for p in claims.claims_dir().iterdir()] == [".md"]
    with pytest.raises(OSError):
        claims.update(found[0], {"milestone": "claimed"}, append="x")
    assert found[0].meta["milestone"] == "acquired" and found[0].notes == "first note\nmy own line\n"


def test_the_bytes_are_the_text_with_the_milestone_changed(world):
    claim, expected = stale(world)
    claims.read_one(world["conn"], claim.id)
    data = claim.path.read_bytes()
    assert data == expected.encode("utf-8") and b"\r" not in data
    assert b"milestone: acquired\n" in data and b"my own line\n" in data and b"priority: high\n" in data


def test_a_preview_prepares_without_a_file(world):
    folder = claims.claims_dir()
    claim = claims.prepare(world["conn"], world["ding"], world["envs"]["loose_files"]["id"], today=TODAY)
    assert claim.path == folder / f"{claim.id}.md" and claim.id.startswith("2026-10-29-")
    assert not folder.exists()
    made = claims.new(world["conn"], world["ding"], world["envs"]["loose_files"]["id"], today=TODAY)
    assert made.id == claim.id
