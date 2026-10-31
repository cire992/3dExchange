"""A claim's relative folder stays in its place; an absolute one is the user's choice (R3d-4)."""

import json
import re

import pytest

from exchange import claims
from exchange.requisitions import lifecycle
from test_claim_paths import registry_with, world  # noqa: F401  (the fixture)
from test_cli_claim_walk import add, claim_cmd, claim_file, count, use


@pytest.fixture
def ready(monkeypatch):
    use(monkeypatch, registry_with("stamp_images", "to_daz"))


def leaving(world):
    """Folders that leave the place, as written: climbing out, and drive-relative on another drive and the root's."""
    drive = world["root"].drive[0].upper()
    other = "D" if drive != "D" else "E"
    return [r"..\other", r"a\..\..\other", f"{other}:foo", f"{drive}:foo"]


def files_in_claims():
    folder = claims.claims_dir()
    return sorted(p.name for p in folder.iterdir()) if folder.is_dir() else []


def place_name(world):
    return world["envs"]["loose_files"]["name"]


def test_claim_add_refuses_a_folder_that_leaves(capsys, world, ready):
    for folder in leaving(world):
        before = files_in_claims()
        code, out, err = claim_cmd(capsys, world, "add", world["barrel"][:12], "--env",
                                   str(world["envs"]["loose_files"]["id"]), "--folder", folder, "--json")
        assert code == 2 and out == ""
        assert err.startswith("exchange: error:") and folder in err and place_name(world) in err, err
        assert files_in_claims() == before


def test_a_refused_add_creates_no_claims_folder(capsys, world, ready):
    assert not claims.claims_dir().exists()
    code, _, _ = claim_cmd(capsys, world, "add", world["barrel"][:12], "--env",
                           str(world["envs"]["loose_files"]["id"]), "--folder", r"..\other")
    assert code == 2 and not claims.claims_dir().exists()


def test_claim_walk_refuses_a_hand_edited_folder(capsys, world, ready):
    claim = add(capsys, world, "barrel", "loose_files")
    path = claim_file(claim)
    for folder in leaving(world):
        text = path.read_text(encoding="utf-8")
        path.write_bytes(re.sub(r"(?m)^folder:.*$", lambda _: f"folder: {folder}", text).encode("utf-8"))
        assert claims.read_one(world["conn"], claim["id"]).meta["folder"] == folder
        for argv in (("walk", claim["id"]), ("walk", claim["id"], "--run")):
            before, rows = path.read_bytes(), count(world)
            code, out, err = claim_cmd(capsys, world, *argv)
            assert code == 2 and out == ""
            assert err.startswith("exchange: error:") and folder in err and place_name(world) in err, err
            assert path.read_bytes() == before and count(world) == rows


def test_a_relative_folder_that_stays_inside_works(capsys, world, ready):
    claim = add(capsys, world, "barrel", "loose_files", "--folder", r"a\..\b")
    code, out, _ = claim_cmd(capsys, world, "walk", claim["id"], "--json")
    assert code == 0
    folder = lifecycle.detail(world["conn"], json.loads(out)["requisition"]["id"])["endpoint"]["folder"]
    assert folder == str((world["root"] / "b").resolve())


def test_an_absolute_folder_inside_the_place_works(capsys, world, ready):
    inside = world["root"] / "Props" / "Kept"
    claim = add(capsys, world, "barrel", "loose_files", "--folder", str(inside))
    code, out, _ = claim_cmd(capsys, world, "walk", claim["id"], "--json")
    assert code == 0
    folder = lifecycle.detail(world["conn"], json.loads(out)["requisition"]["id"])["endpoint"]["folder"]
    assert folder == str(inside)


def test_a_blank_hand_edited_folder_is_the_default(capsys, world, ready):
    plain = add(capsys, world, "barrel", "loose_files")
    code, out, _ = claim_cmd(capsys, world, "walk", plain["id"], "--json")
    default = lifecycle.detail(world["conn"], json.loads(out)["requisition"]["id"])["endpoint"]["folder"]
    claim = add(capsys, world, "barrel", "loose_files", "--folder", "Props")
    path = claim_file(claim)
    text = path.read_text(encoding="utf-8")
    path.write_bytes(re.sub(r"(?m)^folder:.*$", 'folder: ""', text).encode("utf-8"))
    assert claims.read_one(world["conn"], claim["id"]).meta["folder"] == ""
    code, out, _ = claim_cmd(capsys, world, "walk", claim["id"], "--json")
    assert code == 0
    assert lifecycle.detail(world["conn"], json.loads(out)["requisition"]["id"])["endpoint"]["folder"] == default
