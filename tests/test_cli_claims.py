import json
import re

import pytest

from exchange import claims
from exchange.cli import main
from exchange.db import open_library


@pytest.fixture
def lib(scan, loose_folder, db_path):
    scan(loose_folder)
    conn = open_library(db_path)
    uid = conn.execute("SELECT uid FROM dossier WHERE name = 'ding'").fetchone()[0]
    env = conn.execute("SELECT id, name FROM environment").fetchone()
    conn.close()
    return {"db": str(db_path), "uid": uid, "env": str(env["id"]), "env_name": env["name"]}


def run(capsys, lib, *argv):
    code = main(["claim", *argv, "--db", lib["db"]])
    out = capsys.readouterr()
    return code, out.out, out.err


def add(capsys, lib, *extra):
    code, out, _ = run(capsys, lib, "add", lib["uid"][:12], "--env", lib["env"], "--json", *extra)
    assert code == 0
    return json.loads(out)


def files():
    folder = claims.claims_dir()
    return sorted(folder.glob("*.md")) if folder.exists() else []


def test_add(capsys, lib):
    code, out, _ = run(capsys, lib, "add", lib["uid"][:12], "--env", lib["env"], "--as", "prop", "--note", "hi")
    assert code == 0 and "acquired" in out
    assert len(files()) == 1 and files()[0].stem in out and f"File: {files()[0]}" in out
    claim = add(capsys, lib, "--as", "prop", "--note", "hi")
    assert claim["id"].endswith("-ding-2")
    assert claim["thing"] == lib["uid"] and claim["as"] == "prop" and claim["notes"] == "hi\n"
    assert claim["milestone"] == "acquired" and claim["place_name"] == lib["env_name"] and claim["place"]
    assert re.fullmatch(r"\d{4}-\d\d-\d\d", claim["created"])


def test_add_refusals_write_nothing(capsys, lib):
    code, _, err = run(capsys, lib, "add", "zzzz", "--env", lib["env"])
    assert code == 2 and err.startswith("exchange: error:") and "zzzz" in err
    code, _, err = run(capsys, lib, "add", lib["uid"], "--env", "999")
    assert code == 2 and err.startswith("exchange: error:") and "environment 999" in err
    assert files() == []


def test_list(capsys, lib):
    keep = add(capsys, lib, "--as", "prop")
    closed = add(capsys, lib)
    assert run(capsys, lib, "close", closed["id"])[0] == 0

    code, out, _ = run(capsys, lib, "list")
    assert code == 0 and keep["id"] in out and closed["id"] not in out
    assert all(word in out for word in ("acquired", "ding", "as prop", lib["env_name"]))

    code, out, _ = run(capsys, lib, "list", "--all")
    assert keep["id"] in out and closed["id"] in out
    assert re.search(re.escape(closed["id"]) + r".*closed \d{4}-\d\d-\d\d", out)

    code, out, _ = run(capsys, lib, "list", "--json")
    data = json.loads(out)
    assert data["problems"] == [] and [c["id"] for c in data["claims"]] == [keep["id"]]


def test_list_with_nothing(capsys, lib):
    assert run(capsys, lib, "list")[1].strip() == "No claims."


def test_a_broken_file_is_a_problem_line(capsys, lib):
    good = add(capsys, lib)
    (claims.claims_dir() / "2026-01-01-broken.md").write_text("---\na: 1\na: 2\n---\n", encoding="utf-8")
    code, out, _ = run(capsys, lib, "list")
    assert code == 0 and good["id"] in out and "problem: 2026-01-01-broken.md" in out
    assert run(capsys, lib, "show", "2026-01-01-broken")[0] == 2


def test_show(capsys, lib):
    claim = add(capsys, lib, "--as", "prop", "--folder", "Props", "--note", "the notes")
    code, out, _ = run(capsys, lib, "show", claim["id"])
    assert code == 0
    for key, value in claim.items():
        if key != "notes" and value not in (None, []):
            assert str(value) in out
    assert "milestone: acquired" in out and "the notes" in out
    assert out.startswith(f"File: {files()[0]}")
    code, out, _ = run(capsys, lib, "show", claim["id"], "--json")
    assert json.loads(out) == claim
    assert run(capsys, lib, "show", "nosuch")[0] == 2
    assert run(capsys, lib, "show", "..\\something")[0] == 2


def test_close(capsys, lib):
    claim = add(capsys, lib, "--note", "first")
    path = files()[0]
    code, out, _ = run(capsys, lib, "close", claim["id"], "--reason", "done by hand")
    assert code == 0 and "Closed" in out
    text = path.read_text(encoding="utf-8")
    assert re.search(r"^closed: \d{4}-\d\d-\d\d$", text, re.M) and "milestone: acquired" in text
    assert text.endswith("first\ndone by hand\n")
    before = path.read_bytes()
    code, _, err = run(capsys, lib, "close", claim["id"])
    assert code == 2 and "already closed" in err
    assert path.read_bytes() == before


def test_the_frozen_claims_commands_live_under_project(capsys):
    for command in (["project", "claims"], ["claim"]):
        with pytest.raises(SystemExit) as exit_:
            main([*command, "--help"])
        assert exit_.value.code == 0
        capsys.readouterr()
    with pytest.raises(SystemExit) as exit_:
        main(["claims", "list"])
    assert exit_.value.code == 2
    assert "invalid choice" in capsys.readouterr().err
