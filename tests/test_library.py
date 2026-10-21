"""Search language, browsing pages, sidebar counts and dossier details."""

import pytest

from builders import glb_bytes, write
from exchange.db import repository as repo
from exchange.library.query import dossier_detail, list_dossiers, sidebar
from exchange.library.search import SearchError, parse_query


@pytest.fixture
def indexed(scan, mixed, library, db_path):
    write(mixed / "Loose" / "Downloads" / "props" / "Teapot.glb", glb_bytes())
    scan(mixed, enrich=True)
    return library()


def names(conn, definitions, query, **kw):
    page = list_dossiers(conn, definitions, query=query, group=kw.pop("group", "all"), **kw)
    return {b.name for b in page.items}


def test_parse_query():
    terms = parse_query('donut env:starfield -tag:damaged author:"Jane Doe" "two words"')
    assert [(t.negated, t.key, t.value) for t in terms] == [
        (False, None, "donut"), (False, "env", "starfield"), (True, "tag", "damaged"),
        (False, "author", "Jane Doe"), (False, None, "two words")]
    with pytest.raises(SearchError, match="unknown filter"):
        parse_query("colour:pink")


def test_free_text(indexed, definitions):
    assert names(indexed, definitions, "donut") == {
        "Donut01_Pink", "Donut01_Blue", "donut01", "donut01_pink", "Lard Lads Donuts"}  # prefix match
    assert names(indexed, definitions, "donut pink") == {"Donut01_Pink", "donut01_pink"}
    assert names(indexed, definitions, "marius") == {"Marius HD-8K", "Marius Head", "Marius Body",
                                                     "Marius HD-8K for Genesis 9"}
    assert names(indexed, definitions, "lard") >= {"Lard Lads Donuts", "donut01"}  # container names


def test_filters(indexed, definitions):
    assert names(indexed, definitions, "donut env:skyrim_se") == {"donut01", "donut01_pink", "Lard Lads Donuts"}
    assert names(indexed, definitions, "donut -env:skyrim_se -is:product") == {"Donut01_Pink", "Donut01_Blue"}
    assert "Teapot" in names(indexed, definitions, "type:mesh")  # includes static_mesh
    assert names(indexed, definitions, "type:mesh") >= {"Summer Dress", "donut01"}  # daz_wearable is a mesh
    assert names(indexed, definitions, "type:daz_morph") == {"Marius Head", "Marius Body"}
    assert names(indexed, definitions, 'author:"jane doe"') == {"Marius HD-8K for Genesis 9"}
    assert names(indexed, definitions, "variant:genesis_8") == {"Summer Dress"}
    assert names(indexed, definitions, "container:\"lard lads\" -is:product") == {"donut01"}
    assert names(indexed, definitions, "is:unidentified") == {"props"}
    assert "Teapot" in names(indexed, definitions, "has:thumbnail")
    assert "Marius HD-8K" in names(indexed, definitions, "has:broken")
    with pytest.raises(SearchError, match="phase 4"):
        names(indexed, definitions, "has:candidate")
    with pytest.raises(SearchError, match="unknown dossier type"):
        names(indexed, definitions, "type:spaceship")


def test_tags_and_renames_are_searchable(indexed, definitions):
    uid = indexed.execute("SELECT uid FROM dossier WHERE name = 'Teapot'").fetchone()[0]
    with repo.transaction(indexed):
        repo.set_override_tag(indexed, uid, "Kitchen", "add")
        repo.set_override_field(indexed, uid, "name", "Grandma's Teapot")
    assert names(indexed, definitions, "tag:kitchen") == {"Grandma's Teapot"}
    assert names(indexed, definitions, "grandma") == {"Grandma's Teapot"}
    assert names(indexed, definitions, "is:overridden") == {"Grandma's Teapot"}


def test_retired_dossiers_are_hidden_by_default(scan, mixed, indexed, definitions):
    (mixed / "Loose" / "sounds" / "ding.wav").unlink()
    scan(mixed)
    assert "ding" not in names(indexed, definitions, "")
    assert names(indexed, definitions, "status:retired") == {"ding"}


def test_grouping_and_paging(indexed, definitions):
    top = list_dossiers(indexed, definitions, group="product", limit=500)
    top_names = {b.name for b in top.items}
    assert "Marius HD-8K for Genesis 9" in top_names and "Marius Head" not in top_names
    assert "Loose Boots" in top_names  # standalone

    by_type = list_dossiers(indexed, definitions, group="type", limit=500)
    assert all(b.type_id != "product" for b in by_type.items)
    assert [b.type_id for b in by_type.items] == sorted(b.type_id for b in by_type.items)

    first = list_dossiers(indexed, definitions, group="all", limit=3)
    second = list_dossiers(indexed, definitions, group="all", limit=3, offset=3)
    assert first.total == second.total > 6
    assert not {b.uid for b in first.items} & {b.uid for b in second.items}

    marius = next(b for b in top.items if b.name == "Marius HD-8K for Genesis 9")
    assert marius.children == 3 and marius.entries == 1 and marius.environments == ["Daz Studio"]
    kids = list_dossiers(indexed, definitions, parent_uid=marius.uid)
    assert {b.name for b in kids.items} == {"Marius Head", "Marius Body", "Marius HD-8K"}


def test_sidebar(indexed, definitions):
    bar = sidebar(indexed, definitions)
    assert bar["all"] == 6 + 7 + 4  # loose files, Daz, MO2: every live dossier once
    assert bar["unidentified_dossiers"] == 1
    envs = {e["type_id"]: e for e in bar["environments"]}
    mo2 = envs["skyrim_se"]
    assert mo2["status"] == "online"
    assert {c["name"]: c["count"] for c in mo2["containers"]} == {"Lard Lads Donuts": 2, "Test Requisitions": 2}
    assert {t["type_id"]: t["count"] for t in envs["daz_studio"]["types"]}["daz_morph"] == 2


def test_dossier_detail(indexed, definitions, db_path):
    uid = indexed.execute("SELECT uid FROM dossier WHERE name = 'Marius HD-8K'").fetchone()[0]
    with repo.transaction(indexed):
        repo.set_override_field(indexed, uid, "license", "personal")
    d = dossier_detail(indexed, definitions, uid)
    assert d["type_name"] == "Daz character preset"
    assert d["parent"]["name"] == "Marius HD-8K for Genesis 9"
    assert d["variant"] == "genesis_9"
    assert d["fields"]["license"] == {"value": "personal", "source": "user"}
    assert "references" not in d["fields"]
    [ledger] = d["ledgers"]
    assert ledger["environment"]["name"] == "Daz Studio"
    [entry] = ledger["entries"]
    assert entry["status"] == "origin" and entry["files"][0]["role"] == "primary"
    assert entry["files"][0]["path"].endswith("Marius HD-8K.duf")
    broken = [x for x in d["dependencies"] if x["status"] == "broken"]
    assert [x["reference"] for x in broken] == ["data/DAZ 3D/Genesis 9/Base/Genesis9.dsf"]
    assert [h["action"] for h in d["history"]] == ["entry_added", "set_field"]

    product = indexed.execute("SELECT uid FROM dossier WHERE name = 'Marius HD-8K for Genesis 9'").fetchone()[0]
    required_by = dossier_detail(indexed, definitions, product)["required_by"]
    assert [r["name"] for r in required_by] == ["Marius Body", "Marius HD-8K", "Marius Head"]
    assert dossier_detail(indexed, definitions, "nope") is None
