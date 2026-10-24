"""The service's read API (Roadmap phase 6b): auth, the library routes, the committed schema, and
``exchange serve`` as the shell starts it."""

import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from exchange.curation import Curator  # noqa: E402
from exchange.db import open_library  # noqa: E402
from exchange.library.query import list_dossiers, sidebar  # noqa: E402
from exchange.service.app import create_app  # noqa: E402
from exchange.service.schema import openapi_schema  # noqa: E402

TOKEN = "test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
SCHEMA = Path(__file__).parent.parent / "docs" / "api" / "openapi.json"


@pytest.fixture
def library(mixed, scan, db_path, definitions):
    scan(mixed, enrich=True)  # with thumbnails
    conn = open_library(db_path)
    curator = Curator(conn, definitions)
    curator.create_collection("Everything barrel", query="barrel")
    first = conn.execute("SELECT uid FROM dossier ORDER BY id LIMIT 1").fetchone()["uid"]
    curator.create_collection("Picked")
    curator.add_to_collection("Picked", [first])
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture
def client(library, definitions):
    app = create_app(library, token=TOKEN, definitions=definitions)
    with TestClient(app, base_url="http://127.0.0.1") as c:
        yield c
    app.state.library.close()


def test_health_needs_no_token_and_says_nothing_about_the_library(client):
    body = client.get("/health").json()
    assert body["service"] == "exchange" and body["api"] == 1 and isinstance(body["schema_version"], int)


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer wrong"}, {"Authorization": TOKEN}])
def test_every_api_route_needs_the_token(client, headers):
    for path in ("/api/v1/sidebar", "/api/v1/dossiers", "/api/v1/environments", "/api/v1/collections"):
        assert client.get(path, headers=headers).status_code == 401, path


def test_requests_for_another_host_name_are_refused(library, definitions):
    app = create_app(library, token=TOKEN, definitions=definitions)
    with TestClient(app, base_url="http://attacker.example") as c:
        assert c.get("/api/v1/sidebar", headers=AUTH).status_code == 403
        assert c.get("/health").status_code == 403
    with TestClient(app, base_url="http://localhost:5000") as c:
        assert c.get("/health").status_code == 200
    app.state.library.close()


def test_no_docs_or_schema_are_served(client):
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path, headers=AUTH).status_code == 404


def test_sidebar_matches_the_window(client, library, definitions):
    conn = open_library(library)
    expected = sidebar(conn, definitions)
    conn.close()
    body = client.get("/api/v1/sidebar", headers=AUTH).json()
    assert body["all"] == expected["all"] > 0
    assert [e["name"] for e in body["environments"]] == [e["name"] for e in expected["environments"]]
    assert body["environments"][0]["containers"] and body["environments"][0]["types"]


def test_pages_filters_and_search(client, library, definitions):
    conn = open_library(library)
    everything = list_dossiers(conn, definitions, group="all", limit=1000)
    conn.close()
    page = client.get("/api/v1/dossiers", params={"group": "all", "limit": 3}, headers=AUTH).json()
    assert page["total"] == everything.total and len(page["items"]) == 3 and page["offset"] == 0
    assert [b["uid"] for b in page["items"]] == [b.uid for b in everything.items[:3]]
    following = client.get("/api/v1/dossiers", params={"group": "all", "limit": 3, "offset": 3}, headers=AUTH).json()
    assert [b["uid"] for b in following["items"]] == [b.uid for b in everything.items[3:6]]
    brick = page["items"][0]
    assert set(brick) == {"uid", "name", "type_id", "type_name", "confidence", "unidentified", "thumbnail_url",
                          "format", "environments", "entries", "children"}

    envs = client.get("/api/v1/environments", headers=AUTH).json()
    one = envs[0]["id"]
    in_env = client.get("/api/v1/dossiers", params={"group": "all", "environment": one, "limit": 1000}, headers=AUTH).json()
    assert 0 < in_env["total"] <= everything.total
    assert all(envs[0]["name"] in b["environments"] for b in in_env["items"])

    found = client.get("/api/v1/dossiers", params={"query": "barrel"}, headers=AUTH).json()
    assert found["total"] > 0 and all("barrel" in b["name"].lower() for b in found["items"])
    bad = client.get("/api/v1/dossiers", params={"query": "type:not_a_type"}, headers=AUTH)
    assert bad.status_code == 400 and "unknown dossier type" in bad.json()["detail"]
    assert client.get("/api/v1/dossiers", params={"group": "nope"}, headers=AUTH).status_code == 400
    assert client.get("/api/v1/dossiers", params={"limit": 5000}, headers=AUTH).status_code == 422


def test_collections_and_their_members(client):
    collections = {c["name"]: c for c in client.get("/api/v1/collections", headers=AUTH).json()}
    assert collections["Picked"]["count"] == 1 and not collections["Picked"]["smart"]
    assert collections["Everything barrel"]["smart"] and collections["Everything barrel"]["query"] == "barrel"
    members = client.get("/api/v1/dossiers", params={"collection": collections["Picked"]["uid"]}, headers=AUTH).json()
    assert members["total"] == 1


def test_detail_and_thumbnail(client, library):
    conn = open_library(library)
    with_thumb = conn.execute("SELECT d.uid FROM thumbnail t JOIN dossier d ON d.id = t.dossier_id LIMIT 1").fetchone()
    without = conn.execute("SELECT uid FROM dossier WHERE id NOT IN (SELECT dossier_id FROM thumbnail) LIMIT 1").fetchone()
    conn.close()
    assert with_thumb and without, "the fixture library needs assets with and without thumbnails"

    detail = client.get(f"/api/v1/dossiers/{with_thumb['uid']}", headers=AUTH).json()
    assert detail["uid"] == with_thumb["uid"] and detail["ledgers"] and detail["ledgers"][0]["entries"]
    assert detail["thumbnail_url"] == f"/api/v1/dossiers/{with_thumb['uid']}/thumbnail"
    assert "thumbnail" not in detail and isinstance(detail["parent_fields"], dict)
    image = client.get(detail["thumbnail_url"], headers=AUTH)
    assert image.status_code == 200 and image.headers["content-type"].startswith("image/") and image.content
    assert client.get(detail["thumbnail_url"]).status_code == 401

    assert client.get(f"/api/v1/dossiers/{without['uid']}", headers=AUTH).json()["thumbnail_url"] is None
    assert client.get(f"/api/v1/dossiers/{without['uid']}/thumbnail", headers=AUTH).status_code == 404
    assert client.get("/api/v1/dossiers/not-a-uid", headers=AUTH).status_code == 404


def test_the_committed_schema_is_up_to_date():
    committed = json.loads(SCHEMA.read_text(encoding="utf-8"))
    assert committed == openapi_schema(), "regenerate it: exchange serve --openapi > docs/api/openapi.json"


def test_serve_as_the_shell_starts_it(library):
    env = {**os.environ, "EXCHANGE_SERVICE_TOKEN": TOKEN, "PYTHONPATH": str(Path(__file__).parent.parent / "src")}
    process = subprocess.Popen([sys.executable, "-m", "exchange", "serve", "--db", str(library), "--exit-with-stdin"],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, text=True)
    try:
        ready = json.loads(process.stdout.readline())
        assert ready["event"] == "ready" and ready["api"] == 1 and "token" not in ready
        assert ready["url"].startswith("http://127.0.0.1:")
        with urllib.request.urlopen(ready["url"] + "/health", timeout=10) as response:
            assert json.loads(response.read())["service"] == "exchange"
        request = urllib.request.Request(ready["url"] + "/api/v1/sidebar", headers=AUTH)
        with urllib.request.urlopen(request, timeout=10) as response:
            assert json.loads(response.read())["all"] > 0
        process.stdin.close()  # the shell went away
        assert process.wait(timeout=15) == 0
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
