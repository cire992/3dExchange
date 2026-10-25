"""The service's write API (Roadmap phase 6e): curation edits with this session's Undo and Redo,
history, collections, the Unidentified desk, suggestions, lexicons and a busy library."""

import sqlite3
import time

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from builders import copy_fixture, write  # noqa: E402
from exchange.definitions import load_definitions  # noqa: E402
from exchange.service import edits  # noqa: E402
from exchange.service.app import create_app  # noqa: E402

TOKEN = "test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
V1 = "/api/v1"


@pytest.fixture
def make_client(db_path):
    made = []

    def make():
        # Fresh definitions: lexicon edits change them in memory.
        app = create_app(db_path, token=TOKEN, definitions=load_definitions(include_user_dir=False))
        client = TestClient(app, base_url="http://127.0.0.1", headers=AUTH)
        made.append(app)
        return client

    yield make
    for app in made:
        app.state.library.close()


@pytest.fixture
def client(scan, mixed, make_client):
    scan(mixed)
    return make_client()


def uid_of(db_path, name):
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT uid FROM dossier WHERE name = ?", (name,)).fetchall()
    assert len(rows) == 1, (name, rows)
    return rows[0][0]


def detail(client, uid):
    return client.get(f"{V1}/dossiers/{uid}").json()


def ok(response):
    assert response.status_code == 200, response.text
    return response.json()


def test_every_edit_needs_the_token(client):
    for path in ("/edits/fields", "/edits/tags", "/undo", "/collections", "/suggestions/accept"):
        assert client.post(V1 + path, json={}, headers={"Authorization": "Bearer wrong"}).status_code == 401, path
    assert client.get(f"{V1}/lexicons", headers={"Authorization": ""}).status_code == 401


def test_field_edits_with_undo_and_redo(client, db_path):
    barrel = uid_of(db_path, "Barrel01")
    result = ok(client.post(f"{V1}/edits/fields", json={"uids": [barrel], "field": "name", "value": "Oak Barrel"}))
    assert result["label"] == "rename" and result["refresh"] == "detail" and result["session"] == {"undo": "rename", "redo": None}
    assert detail(client, barrel)["name"] == "Oak Barrel"
    undone = ok(client.post(f"{V1}/undo"))
    assert undone == {"label": "rename", "refresh": "detail", "session": {"undo": None, "redo": "rename"}}
    assert detail(client, barrel)["name"] == "Barrel01"
    ok(client.post(f"{V1}/redo"))
    assert detail(client, barrel)["name"] == "Oak Barrel"
    assert ok(client.get(f"{V1}/session")) == {"undo": "rename", "redo": None}
    # Nothing left to redo; undo twice reaches the start.
    assert ok(client.post(f"{V1}/redo"))["label"] is None
    ok(client.post(f"{V1}/undo"))
    assert ok(client.post(f"{V1}/undo"))["label"] is None

    # Bulk: a field on several assets is one step; a null value reverts; names go one at a time.
    pink, blue = uid_of(db_path, "Donut01_Pink"), uid_of(db_path, "Donut01_Blue")
    bulk = ok(client.post(f"{V1}/edits/fields", json={"uids": [pink, blue], "field": "author", "value": "Jane Doe"}))
    assert bulk["label"] == "set author of 2 assets"
    assert detail(client, blue)["fields"]["author"] == {"value": "Jane Doe", "source": "user"}
    ok(client.post(f"{V1}/edits/fields", json={"uids": [blue], "field": "author", "value": None}))
    assert "author" not in detail(client, blue)["fields"]
    refused = client.post(f"{V1}/edits/fields", json={"uids": [pink, blue], "field": "name", "value": "X"})
    assert refused.status_code == 409 and "one asset at a time" in refused.json()["detail"]
    assert client.post(f"{V1}/edits/fields", json={"uids": [pink], "field": "uid", "value": "x"}).status_code == 409
    assert client.post(f"{V1}/edits/fields", json={"uids": ["nope"], "field": "notes", "value": "x"}).status_code == 404
    retyped = ok(client.post(f"{V1}/edits/fields", json={"uids": [pink], "field": "type_id", "value": "static_mesh"}))
    assert retyped["refresh"] == "all" and detail(client, pink)["type_id"] == "static_mesh"


def test_tags_and_products(client, db_path):
    pink, blue = uid_of(db_path, "Donut01_Pink"), uid_of(db_path, "Donut01_Blue")
    ok(client.post(f"{V1}/edits/tags", json={"uids": [pink, blue], "add": ["Snack"], "remove": []}))
    assert "Snack" in detail(client, blue)["tags"]
    ok(client.post(f"{V1}/edits/tags/revert", json={"uid": blue, "tag": "Snack"}))
    assert "Snack" not in detail(client, blue)["tags"]
    assert client.post(f"{V1}/edits/tags", json={"uids": [pink], "add": [], "remove": []}).status_code == 409

    made = ok(client.post(f"{V1}/edits/products", json={"name": "Donut box", "children": [pink, blue]}))
    box = made["new_uid"]
    assert made["refresh"] == "all" and {c["uid"] for c in detail(client, box)["children"]} == {pink, blue}
    ok(client.post(f"{V1}/edits/parent", json={"uids": [blue], "parent": None}))
    assert {c["uid"] for c in detail(client, box)["children"]} == {pink}
    ok(client.post(f"{V1}/edits/parent/revert", json={"uid": blue}))  # back to the scanned parent: none
    assert {c["uid"] for c in detail(client, box)["children"]} == {pink}
    ok(client.post(f"{V1}/undo"))  # the revert
    ok(client.post(f"{V1}/undo"))  # taking blue out
    ok(client.post(f"{V1}/undo"))  # the product
    assert client.get(f"{V1}/dossiers/{box}").status_code == 404


def test_merge_fold_split_and_dismiss(client, db_path):
    pink, blue = uid_of(db_path, "Donut01_Pink"), uid_of(db_path, "Donut01_Blue")
    assert client.post(f"{V1}/edits/merge", json={"uid": pink, "into": pink}).status_code == 409
    folded = ok(client.post(f"{V1}/edits/fold-variant", json={"uid": blue, "into": pink, "variant": "blue",
                                                             "target_variant": "pink"}))
    assert folded["label"] == "fold in variant blue"
    assert sorted(detail(client, pink)["variants"]) == ["blue", "pink"]
    promoted = ok(client.post(f"{V1}/edits/promote-variant", json={"uid": pink, "variant": "blue"}))
    assert detail(client, promoted["new_uid"])["name"] == "Donut01_Pink blue"
    entry = detail(client, pink)["ledgers"][0]["entries"][0]["id"]
    assert client.post(f"{V1}/edits/split", json={"uid": pink, "entries": [999999]}).status_code == 409
    ok(client.post(f"{V1}/undo"))  # the promotion: the asset it made is gone again
    assert client.get(f"{V1}/dossiers/{promoted['new_uid']}").status_code == 404
    split = ok(client.post(f"{V1}/edits/split", json={"uid": pink, "entries": [entry], "name": "Pink alone"}))
    assert detail(client, split["new_uid"])["name"] == "Pink alone"
    dismissed = ok(client.post(f"{V1}/edits/dismiss", json={"uids": [split["new_uid"]]}))
    assert dismissed["label"] == "mark an asset as not an asset"
    assert detail(client, split["new_uid"])["fields"]["not_an_asset"]["value"] is True


def test_collections(client, db_path):
    barrel = uid_of(db_path, "Barrel01")
    made = ok(client.post(f"{V1}/collections", json={"name": "Keep"}))
    assert made["refresh"] == "collections"
    ok(client.post(f"{V1}/collections/{made['new_uid']}/members", json={"uids": [barrel]}))
    assert [c["count"] for c in client.get(f"{V1}/collections").json() if c["name"] == "Keep"] == [1]
    smart = ok(client.post(f"{V1}/collections", json={"name": "Donuts", "query": "donut"}))
    refused = client.post(f"{V1}/collections/{smart['new_uid']}/members", json={"uids": [barrel]})
    assert refused.status_code == 409 and "saved search" in refused.json()["detail"]
    assert client.post(f"{V1}/collections", json={"name": "Keep"}).status_code == 409
    assert client.post(f"{V1}/collections", json={"name": "Broken", "query": "type:not_a_type"}).status_code == 409
    ok(client.delete(f"{V1}/collections/{made['new_uid']}"))
    assert "Keep" not in {c["name"] for c in client.get(f"{V1}/collections").json()}
    ok(client.post(f"{V1}/undo"))
    assert [c["count"] for c in client.get(f"{V1}/collections").json() if c["name"] == "Keep"] == [1]
    assert client.delete(f"{V1}/collections/nope").status_code == 404


def test_suggestions_history_and_undoing_an_entry(client, db_path):
    page = ok(client.get(f"{V1}/suggestions", params={"kind": "texture_link"}))
    assert page["total"] == page["counts"]["texture_link"] == len(page["items"]) >= 2
    barrel = next(s for s in page["items"] if s["subject_name"] == "Barrel01")
    accepted = ok(client.post(f"{V1}/suggestions/accept", json={"ids": [barrel["id"]]}))
    assert accepted["label"] == "accept 1 suggestion" and accepted["refresh"] == "all"
    others = [s["id"] for s in page["items"] if s["id"] != barrel["id"]]
    ok(client.post(f"{V1}/suggestions/reject", json={"ids": others}))
    assert ok(client.get(f"{V1}/suggestions", params={"kind": "texture_link"}))["total"] == 0
    assert client.post(f"{V1}/suggestions/accept", json={"ids": [barrel["id"]]}).status_code == 409

    log = ok(client.get(f"{V1}/history", params={"limit": 2}))
    assert [e["action"] for e in log] == ["reject_suggestions", "accept_texture_link"]
    assert log[1]["undoable"] and log[1]["dossiers"] == [uid_of(db_path, "Barrel01")]
    assert "inverse" not in log[1]["details"] and log[1]["details"]["suggestion"] == barrel["id"]
    undone = ok(client.post(f"{V1}/history/{log[1]['id']}/undo"))
    assert undone["label"] == "undo accept texture link"
    assert ok(client.get(f"{V1}/suggestions", params={"kind": "texture_link"}))["total"] == 1
    assert client.post(f"{V1}/history/999999/undo").status_code == 404


def test_lexicons(client):
    lexicons = {lex["id"]: lex for lex in ok(client.get(f"{V1}/lexicons"))}
    assert lexicons["authors"]["generated"] and not lexicons["category"]["generated"]
    food = next(t for t in lexicons["category"]["terms"] if t["value"] == "Food")
    assert "donut" in food["words"]
    added = ok(client.post(f"{V1}/lexicons/category/words", json={"value": "Food", "word": "kringle"}))
    assert added["refresh"] == "none" and added["label"] == "add the word kringle to Food"
    ignored = ok(client.post(f"{V1}/lexicons/ignore/words", json={"value": "", "word": "draft"}))
    assert ignored["label"] == "add the word draft to the Ignore lexicon"
    ok(client.post(f"{V1}/undo"))
    food = next(t for t in {lex["id"]: lex for lex in ok(client.get(f"{V1}/lexicons"))}["category"]["terms"]
                if t["value"] == "Food")
    assert "kringle" in food["words"]
    ok(client.post(f"{V1}/undo"))
    food = next(t for t in {lex["id"]: lex for lex in ok(client.get(f"{V1}/lexicons"))}["category"]["terms"]
                if t["value"] == "Food")
    assert "kringle" not in food["words"]
    assert client.post(f"{V1}/lexicons/nope/words", json={"value": "x", "word": "y"}).status_code == 404
    choices = ok(client.get(f"{V1}/choices"))
    assert "Food" in choices["tags"] and "name" in choices["fields"]
    assert {"id": "static_mesh", "name": "Static mesh", "extends": "mesh"} in choices["types"]


@pytest.fixture
def desk_client(scan, tmp_path, make_client):
    folder = copy_fixture("loose_files", tmp_path / "scan" / "Loose")
    for name in ("a.dat", "b.dat"):
        write(folder / "Junk" / "Cache" / name, b"x")
    write(folder / "Junk" / "c.dat", b"x")
    scan(folder)
    return make_client()


def test_the_unidentified_desk(desk_client, monkeypatch):
    client = desk_client
    [root] = ok(client.get(f"{V1}/desk/roots"))
    level = ok(client.get(f"{V1}/desk/folders", params={"root": root["id"], "folder": "junk"}))
    assert level == {"folders": [{"name": "Cache", "path": "Junk/Cache", "count": 2}], "files": 1, "total": 3}
    assert [f["rel_path"] for f in ok(client.get(f"{V1}/desk/files", params={"root": root["id"], "folder": "Junk"}))] == [
        "Junk/c.dat", "Junk/Cache/a.dat", "Junk/Cache/b.dat"]
    made = ok(client.post(f"{V1}/edits/products", json={"name": "Cache stuff", "folder": {"root": root["id"], "path": "Junk/Cache"}}))
    assert ok(client.get(f"{V1}/desk/folders", params={"root": root["id"], "folder": "Junk"}))["total"] == 1
    linked = ok(client.post(f"{V1}/edits/link-files", json={"uid": made["new_uid"], "folder": {"root": root["id"], "path": "Junk"}}))
    assert linked["label"] == "link a folder"
    assert ok(client.get(f"{V1}/desk/folders", params={"root": root["id"], "folder": "Junk"}))["total"] == 0
    empty = client.post(f"{V1}/edits/link-files", json={"uid": made["new_uid"], "folder": {"root": root["id"], "path": "Junk"}})
    assert empty.status_code == 409 and "no unattached files" in empty.json()["detail"]
    ok(client.post(f"{V1}/undo"))
    ok(client.post(f"{V1}/edits/ignore-folder", json={"environment": root["environment_id"], "folder": "Junk"}))
    assert not any(f["name"] == "Junk" for f in ok(client.get(f"{V1}/desk/folders", params={"root": root["id"]}))["folders"])
    ok(client.post(f"{V1}/undo"))
    monkeypatch.setattr(edits, "MAX_FOLDER_FILES", 0)
    big = client.post(f"{V1}/edits/products", json={"name": "Everything", "folder": {"root": root["id"], "path": "Junk"}})
    assert big.status_code == 409 and "a category, not an asset" in big.json()["detail"]


def test_a_busy_library_answers_at_once(client, db_path):
    barrel = uid_of(db_path, "Barrel01")
    blocker = sqlite3.connect(db_path, isolation_level=None)
    blocker.execute("BEGIN IMMEDIATE")  # what a scan holds while it writes
    try:
        started = time.monotonic()
        busy = client.post(f"{V1}/edits/fields", json={"uids": [barrel], "field": "notes", "value": "x"})
        assert busy.status_code == 503 and busy.json()["detail"] == edits.BUSY
        assert busy.headers["retry-after"] == "2"
        assert time.monotonic() - started < 5
        assert ok(client.get(f"{V1}/session"))["undo"] is None  # nothing was recorded
    finally:
        blocker.execute("ROLLBACK")
        blocker.close()
    ok(client.post(f"{V1}/edits/fields", json={"uids": [barrel], "field": "notes", "value": "x"}))
    assert detail(client, barrel)["fields"]["notes"]["value"] == "x"
