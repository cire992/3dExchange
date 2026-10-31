"""R4c: what is new, through the service: GET /dossiers?new=true and POST /dossiers/new/seen."""

import shutil
import sqlite3
import sys

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from exchange.library.new import marker  # noqa: E402
from exchange.scanner.scan import run_rescan  # noqa: E402
from exchange.service import edits  # noqa: E402
from exchange.service import jobs as jobs_module  # noqa: E402
from exchange.service.app import create_app  # noqa: E402
from test_claim_paths import world  # noqa: E402,F401  (the fixture)
from test_service_claim_walk import barrel, use  # noqa: E402
from test_service_claims import AUTH, TOKEN, V1, api, ok  # noqa: E402,F401  (the fixture)
from test_service_jobs import SLOW  # noqa: E402
from test_service_requisitions import finish  # noqa: E402

SEEN = f"{V1}/dossiers/new/seen"


@pytest.fixture
def client(db_path, definitions):
    app = create_app(db_path, token=TOKEN, definitions=definitions, watch=False)
    yield TestClient(app, base_url="http://127.0.0.1", headers=AUTH)
    app.state.library.close()


@pytest.fixture
def two(scan, client, loose_folder, mo2_instance):
    """The loose files scanned first, then an MO2 instance: four new things."""
    scan(loose_folder)
    scan(mo2_instance)
    return client


def read(db_path, sql, *args):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(sql, args).fetchall()
    finally:
        conn.close()


def current(db_path):
    conn = sqlite3.connect(db_path)
    try:
        return marker(conn)
    finally:
        conn.close()


def highest(db_path):
    return read(db_path, "SELECT max(id) FROM dossier")[0][0]


def listing(client, **params):
    return ok(client.get(f"{V1}/dossiers", params=params))


def names(client, **params):
    return sorted(i["name"] for i in listing(client, **params)["items"])


def new_uids(client, **params):
    return sorted(i["uid"] for i in listing(client, new="true", group="all", **params)["items"])


def drop_marker(db_path):
    conn = sqlite3.connect(db_path, isolation_level=None)
    conn.execute("DELETE FROM library_setting WHERE key = 'new_marker'")
    conn.close()


def test_seen_needs_the_token(two, db_path):
    before = current(db_path)
    for headers in ({"Authorization": "Bearer wrong"}, {"Authorization": ""}):
        assert two.post(SEEN, headers=headers).status_code == 401
    bare = TestClient(two.app, base_url="http://127.0.0.1")
    assert bare.post(SEEN).status_code == 401
    assert current(db_path) == before < highest(db_path)


def test_a_first_scan_has_nothing_new(client, scan, loose_folder, db_path):
    scan(loose_folder)
    for group in ("product", "type", "all"):
        page = listing(client, new="true", group=group)
        assert page["items"] == [] and page["total"] == 0
    assert current(db_path) == highest(db_path)


def test_a_second_scan_lists_what_it_found(two):
    page = listing(two, new="true")
    assert sorted(i["name"] for i in page["items"]) == ["Lard Lads Donuts", "Test Requisitions"] and page["total"] == 2
    assert listing(two, new="true", group="all")["total"] == 4
    assert names(two, new="true", group="type") == ["donut01", "donut01_pink"]
    plain, off = listing(two), listing(two, new="false")
    assert plain == off and plain["total"] > 2
    assert {"props", "Lard Lads Donuts"} <= {i["name"] for i in plain["items"]}


def test_no_marker_lists_nothing_and_a_bad_search_is_still_a_400(client, scan, loose_folder, db_path, definitions):
    scan(loose_folder)
    drop_marker(db_path)
    page = listing(client, new="true")
    assert page["items"] == [] and page["total"] == 0
    assert client.get(f"{V1}/dossiers", params={"new": "true", "query": "type:nonsense"}).status_code == 400
    run_rescan(db_path=db_path, definitions=definitions)
    assert current(db_path) == highest(db_path) and listing(client, new="true")["total"] == 0


def test_a_rescan_finding_nothing_leaves_the_list_as_it_was(two, db_path, definitions):
    before, first = new_uids(two), current(db_path)
    run_rescan(db_path=db_path, definitions=definitions)
    assert new_uids(two) == before and len(before) == 4 and current(db_path) == first


def test_a_new_product_is_listed_once_without_its_children(two):
    assert names(two, new="true", group="product") == ["Lard Lads Donuts", "Test Requisitions"]
    lard = next(i["uid"] for i in listing(two, new="true")["items"] if i["name"] == "Lard Lads Donuts")
    assert names(two, new="true", parent=lard) == ["donut01"]


def test_a_new_child_of_an_old_product_is_listed_but_not_in_the_plain_listing(client, scan, mo2_instance, db_path,
                                                                              definitions):
    scan(mo2_instance)
    meshes = mo2_instance / "mods" / "Lard Lads Donuts" / "meshes"
    shutil.copy(meshes / "clutter" / "donut01.nif", meshes / "donut02.nif")
    run_rescan(db_path=db_path, definitions=definitions)
    assert names(client, new="true") == ["donut02"]
    assert "donut02" not in names(client)


def test_a_thing_whose_files_are_gone_is_no_longer_new(client, scan, loose_folder, db_path, definitions):
    scan(loose_folder)
    chime = loose_folder / "sounds" / "chime.wav"
    shutil.copy(loose_folder / "sounds" / "ding.wav", chime)
    run_rescan(db_path=db_path, definitions=definitions)
    assert "chime" in names(client, new="true", group="all") and names(client, new="true", group="product")
    chime.unlink()
    run_rescan(db_path=db_path, definitions=definitions)
    assert names(client, new="true", group="product") == [] and names(client, new="true", group="all") == []


def test_a_product_of_the_users_is_listed_through_its_children(client, scan, loose_folder, db_path):
    scan(loose_folder)
    old = [i["uid"] for i in listing(client, group="all")["items"] if i["name"] in ("Barrel01", "ding")]
    assert len(old) == 2
    made = ok(client.post(f"{V1}/edits/products", json={"name": "Odds", "children": old}))
    assert names(client, new="true", group="product") == ["Odds"]
    row = read(db_path, "SELECT id FROM dossier_effective WHERE uid = ?", made["new_uid"])[0]
    assert row[0] > current(db_path)
    assert read(db_path, "SELECT count(*) FROM ledger WHERE dossier_id = ?", row[0])[0][0] == 0


def test_new_combines_with_the_other_filters(two):
    both = names(two, query="donut")
    assert "donut01" in both and "Donut01_Blue" in both
    assert names(two, new="true", query="donut") == ["Lard Lads Donuts", "Test Requisitions", "donut01", "donut01_pink"] \
        or "Donut01_Blue" not in names(two, new="true", query="donut")
    assert "Donut01_Blue" not in names(two, new="true", query="donut", group="all")
    envs = ok(two.get(f"{V1}/environments"))
    mo2 = next(e["id"] for e in envs if e["type_id"] != "loose_files")
    loose = next(e["id"] for e in envs if e["type_id"] == "loose_files")
    assert len(listing(two, new="true", group="all", environment=mo2)["items"]) == 4
    assert listing(two, new="true", group="all", environment=loose)["items"] == []
    assert names(two, new="true", type="mesh") == ["donut01", "donut01_pink"]
    first = listing(two, new="true", group="all", limit=2, offset=0)
    second = listing(two, new="true", group="all", limit=2, offset=2)
    got = [i["uid"] for i in first["items"] + second["items"]]
    assert len(set(got)) == 4 and first["total"] == second["total"] == 4
    past = listing(two, new="true", group="all", limit=2, offset=10)
    assert past["items"] == [] and past["total"] == 4


def test_seen_counts_what_was_new_then_moves_the_marker(two, scan, daz_library, db_path):
    assert listing(two, new="true", group="all")["total"] == 4
    assert ok(two.post(SEEN)) == {"seen": 4}
    assert listing(two, new="true")["items"] == [] and listing(two, new="true", group="all")["total"] == 0
    assert current(db_path) == highest(db_path)
    assert ok(two.post(SEEN)) == {"seen": 0}
    scan(daz_library)
    assert listing(two, new="true")["total"] > 0


def test_seen_with_no_marker_does_nothing(client, scan, loose_folder, db_path):
    scan(loose_folder)
    drop_marker(db_path)
    assert ok(client.post(SEEN)) == {"seen": 0}
    assert current(db_path) is None


def test_seen_is_not_an_edit(two, db_path):
    session = ok(two.get(f"{V1}/session"))
    logged = read(db_path, "SELECT count(*) FROM curation_log")[0][0]
    ok(two.post(SEEN))
    assert read(db_path, "SELECT count(*) FROM curation_log")[0][0] == logged
    assert ok(two.get(f"{V1}/session"))["undo"] == session["undo"]


def test_a_walk_adds_nothing_to_the_new_list(api, mo2_instance):
    api["scan"](mo2_instance)
    client = api["client"]
    before = new_uids(client)
    assert len(before) == 4
    use(api, "stamp_images")
    claim = barrel(api)
    walked = ok(client.post(f"{V1}/claims/{claim['id']}/walk", json={}))
    job = finish(client, walked["job"])
    assert job["state"] == "done", job
    assert ok(client.get(f"{V1}/claims/{claim['id']}"))["milestone"] == "installed"
    assert read(api["db"], "SELECT count(*) FROM entry WHERE requisition_id IS NOT NULL AND status != 'retired'")[0][0]
    assert new_uids(client) == before


def test_entries_exchange_wrote_do_not_make_a_dossier_new(two, db_path):
    assert names(two, new="true", group="type") == ["donut01", "donut01_pink"]
    conn = sqlite3.connect(db_path, isolation_level=None)
    conn.execute("UPDATE entry SET requisition_id = 1 WHERE ledger_id IN (SELECT l.id FROM ledger l"
                 " JOIN dossier d ON d.id = l.dossier_id WHERE d.name = 'donut01')")
    conn.close()
    assert names(two, new="true", group="type") == ["donut01_pink"]


def test_seen_is_refused_while_a_job_writes(api, mo2_instance, monkeypatch):
    api["scan"](mo2_instance)
    client = api["client"]
    before = current(api["db"])
    monkeypatch.setattr(jobs_module.Jobs, "command", lambda self, args, json_output: [sys.executable, "-c", SLOW])
    job = ok(client.post(f"{V1}/jobs/rescan", json={}))
    try:
        refused = client.post(SEEN)
        assert refused.status_code == 409 and "is running" in refused.json()["detail"]
        assert current(api["db"]) == before < highest(api["db"])
    finally:
        finish(client, ok(client.post(f"{V1}/jobs/{job['id']}/stop")))


def test_a_busy_library_is_a_503_and_seen_works_after(two, db_path):
    before = current(db_path)
    blocker = sqlite3.connect(db_path, timeout=0, isolation_level=None)
    blocker.execute("BEGIN IMMEDIATE")
    try:
        busy = two.post(SEEN)
        assert busy.status_code == 503 and busy.json()["detail"] == edits.BUSY
        assert current(db_path) == before
    finally:
        blocker.execute("ROLLBACK")
        blocker.close()
    assert ok(two.post(SEEN)) == {"seen": 4}
