"""Phase 3 core: lexicons, classification, curation (with undo), suggestions and collections."""

import json

import pytest

from builders import copy_fixture, write
from exchange.cli import main
from exchange.curation import CurationError, Curator, history
from exchange.db import repository as repo
from exchange.definitions import load_definitions
from exchange.errors import DefinitionError
from exchange.lexicons import LexiconIndex, with_generated, word_forms
from exchange.library.query import dossier_detail, list_collections, list_dossiers
from exchange.scanner.classify import classify
from exchange.scanner.tokenize import tokenize
from exchange.suggestions import list_suggestions


@pytest.fixture
def defs():
    """Definitions this test may change (lexicon edits), fresh each time."""
    return load_definitions(include_user_dir=False)


@pytest.fixture
def lib(scan, mixed, library, defs):
    scan(mixed)
    conn = library()
    return conn, Curator(conn, defs)


def uid_of(conn, name, type_id=None):
    sql, args = "SELECT uid FROM dossier WHERE name = ?", [name]
    if type_id:
        sql += " AND type_id = ?"
        args.append(type_id)
    rows = conn.execute(sql, args).fetchall()
    assert len(rows) == 1, (name, len(rows))
    return rows[0][0]


def names(conn, defs, query):
    return {b.name for b in list_dossiers(conn, defs, query=query, group="all", limit=500).items}


# Lexicons -----------------------------------------------------------------------------------------


def test_lexicon_matching(defs):
    assert ("donuts",) in word_forms("donut") and ("berries",) in word_forms("berry")
    assert word_forms("d") == {("d",)}  # no plurals for letters
    index = LexiconIndex(defs)
    matches = {(m.kind, m.value) for m in index.match(tokenize("Rock_BaseColor"))}
    assert ("texture_channel", "BaseColor") in matches  # a two-token word
    assert index.clean(tokenize("Barrel_final_v2_copy")) == ["barrel"]
    assert index.is_index("01") and index.is_index("b") and not index.is_index("barrel")
    assert index.tag_names["food"] == "Food"


def test_lexicon_file_errors(tmp_path):
    folder = tmp_path / "lexicons"
    folder.mkdir()
    (folder / "bad.toml").write_text('[lexicon]\nid = "bad"\nname = "B"\nkind = "category"\nformat_version = 1\n'
                                     '\n[[term]]\nwords = ["x"]\n', encoding="utf-8")
    with pytest.raises(DefinitionError, match="value is required"):
        load_definitions([tmp_path], include_user_dir=False)


# Classification ---------------------------------------------------------------------------------


def test_classification_tags_and_confidence(lib, defs):
    conn, _ = lib
    donut = uid_of(conn, "donut01")
    tags = {t["tag"]: t for t in dossier_detail(conn, defs, donut)["tag_sources"]}
    assert set(tags["Food"]["sources"]) == {"name", "folder"}  # "donut01" and the "Lard Lads Donuts" mod folder
    row = conn.execute("SELECT confidence, confidence_base FROM dossier WHERE uid = ?", (donut,)).fetchone()
    assert row["confidence"] > row["confidence_base"]  # agreeing evidence raised it
    assert "donut01" in names(conn, defs, "tag:food")
    dress = conn.execute("SELECT uid FROM dossier WHERE name = 'Summer Dress' AND type_id = 'daz_wearable'").fetchone()[0]
    assert "Clothing" in repo.effective_tags(conn, dress)  # from the Daz manifest's category


def test_structural_files_are_hidden(scan, tmp_path, library, defs):
    root = tmp_path / "scan" / "Kit"
    for name in ("SM_Chair.fbx", "SM_Chair_LOD1.fbx", "UCX_SM_Chair.fbx", "Chair_LOD0.fbx"):
        write(root / name, b"fbx")
    scan(root)
    conn = library()
    assert names(conn, defs, "-is:product") == {"SM_Chair", "Chair_LOD0"}
    assert names(conn, defs, "is:structural") == {"SM_Chair_LOD1", "UCX_SM_Chair"}


def test_reclassifying_is_stable_and_follows_lexicon_edits(lib, defs, tmp_path):
    conn, curator = lib
    before = conn.execute("SELECT count(*) FROM dossier_tag").fetchone()[0]
    stats = classify(conn, defs)
    assert stats.changed_confidence == 0
    assert conn.execute("SELECT count(*) FROM dossier_tag").fetchone()[0] == before
    curator.user_dir = tmp_path / "user"
    log_id = curator.set_lexicon_word("category", "Audio", "ding")
    assert (tmp_path / "user" / "lexicons" / "category.toml").is_file()
    classify(conn, defs)
    assert "ding" in names(conn, defs, "tag:audio")
    curator.undo(log_id)
    classify(conn, defs)
    assert "ding" not in names(conn, defs, "tag:audio")


# Curation ----------------------------------------------------------------------------------------


def test_field_edits_bulk_and_undo(lib, defs):
    conn, curator = lib
    a, b = uid_of(conn, "Donut01_Pink"), uid_of(conn, "Donut01_Blue")
    log_id = curator.set_field([a, b], "license", "CC-BY")
    assert repo.effective_fields(conn, a)["license"] == "CC-BY" == repo.effective_fields(conn, b)["license"]
    curator.undo(log_id)
    assert "license" not in repo.effective_fields(conn, a)
    rename = curator.set_field(a, "name", "Pink Frosted")
    assert "Pink Frosted" in names(conn, defs, "frosted")
    curator.undo(curator.undo(rename))  # undo, then redo
    assert repo.effective_dossier(conn, a)["name"] == "Pink Frosted"
    assert [h["action"] for h in history(conn, 3)] == ["undo", "undo", "set_field"]
    with pytest.raises(CurationError, match="not editable"):
        curator.set_field(a, "uid", "x")
    with pytest.raises(CurationError, match="unknown dossier type"):
        curator.set_field(a, "type_id", "spaceship")


def test_tags_and_lexicon_word_suggestion(lib, defs):
    conn, curator = lib
    ding = uid_of(conn, "ding")
    log_id = curator.tag(ding, add=["Bell"], remove=["Audio"])
    assert repo.effective_tags(conn, ding) == {"Bell"}
    s = list_suggestions(conn, kind="lexicon_word")
    assert [x["payload"]["word"] for x in s] == ["ding"] and s[0]["payload"]["value"] == "Bell"
    curator.undo(log_id)
    assert "Bell" not in repo.effective_tags(conn, ding)


def test_merge_and_undo_survive_rescans(scan, mixed, lib, defs):
    conn, curator = lib
    pink, blue = uid_of(conn, "Donut01_Pink"), uid_of(conn, "Donut01_Blue")
    log_id = curator.merge(blue, pink)
    assert "Donut01_Blue" not in names(conn, defs, "")
    assert len(dossier_detail(conn, defs, pink)["ledgers"][0]["entries"]) == 2
    assert dossier_detail(conn, defs, pink)["aliases"][0]["uid"] == blue
    scan(mixed)  # the rescan keeps the merge and does not rename Pink after Blue
    assert repo.effective_dossier(conn, pink)["name"] == "Donut01_Pink"
    assert "Donut01_Blue" not in names(conn, defs, "")
    curator.undo(log_id)
    assert {"Donut01_Pink", "Donut01_Blue"} <= names(conn, defs, "donut01")
    scan(mixed)
    assert uid_of(conn, "Donut01_Blue") == blue


def test_variants_fold_and_promote(lib, defs):
    conn, curator = lib
    pink, blue = uid_of(conn, "Donut01_Pink"), uid_of(conn, "Donut01_Blue")
    curator.fold_variant(blue, pink, "Blue", target_variant="Pink")
    assert dossier_detail(conn, defs, pink)["variants"] == ["Blue", "Pink"]
    assert "Donut01_Pink" in names(conn, defs, "has:variants")
    _, new = curator.promote_variant(pink, "Blue")
    assert repo.effective_dossier(conn, new)["name"] == "Donut01_Pink Blue"
    assert dossier_detail(conn, defs, pink)["variants"] == ["Pink"]


def test_split_and_create_product(lib, defs):
    conn, curator = lib
    pink, blue = uid_of(conn, "Donut01_Pink"), uid_of(conn, "Donut01_Blue")
    curator.merge(blue, pink)
    entries = [e["id"] for e in dossier_detail(conn, defs, pink)["ledgers"][0]["entries"]]
    log_id, new = curator.split(pink, entries[1:], name="Blue again")
    assert "Blue again" in names(conn, defs, "")
    curator.undo(log_id)
    assert conn.execute("SELECT count(*) FROM dossier WHERE uid = ?", (new,)).fetchone()[0] == 0
    with pytest.raises(CurationError, match="not all entries"):
        curator.split(pink, [999999])

    barrel, ding = uid_of(conn, "Barrel01"), uid_of(conn, "ding")
    log_id, product = curator.create_product("Tavern kit", [barrel, ding])
    assert "Tavern kit" in names(conn, defs, "is:product")  # live without any files of its own
    assert {c["name"] for c in dossier_detail(conn, defs, product)["children"]} == {"Barrel01", "ding"}
    curator.undo(log_id)
    assert "Tavern kit" not in names(conn, defs, "")
    assert repo.effective_dossier(conn, barrel)["parent_id"] is None


def test_linking_files_survives_rescans(scan, mixed, lib, defs):
    conn, curator = lib
    barrel = uid_of(conn, "Barrel01")
    root = conn.execute("SELECT root_id FROM file WHERE rel_path LIKE '%Barrel01_N.png'").fetchone()[0]
    log_id = curator.link_files(barrel, [(root, "loose/downloads/barrel/barrel01_n.png")], role="texture")
    files = {f["rel_path"]: f["role"] for l in dossier_detail(conn, defs, barrel)["ledgers"]
             for e in l["entries"] for f in e["files"]}
    assert files["Loose/Downloads/barrel/Barrel01_N.png"] == "linked"
    assert "Barrel01" in names(conn, defs, "is:linked")
    scan(mixed)
    assert "Barrel01" in names(conn, defs, "is:linked")
    curator.undo(log_id)
    assert "Barrel01" not in names(conn, defs, "is:linked")
    with pytest.raises(CurationError, match="no file"):
        curator.link_files(barrel, [(root, "nope.png")])


def test_collections(lib, defs):
    conn, curator = lib
    _, cid = curator.create_collection("Lard Lads assets")
    curator.add_to_collection("Lard Lads assets", [uid_of(conn, "donut01"), uid_of(conn, "Lard Lads Donuts")])
    curator.create_collection("Food props", query="tag:food -is:product")
    assert names(conn, defs, 'collection:"Lard Lads assets"') == {"donut01", "Lard Lads Donuts"}
    assert "Donut01_Pink" in names(conn, defs, 'collection:"Food props"')
    counts = {c["name"]: c["count"] for c in list_collections(conn, defs)}
    assert counts["Lard Lads assets"] == 2 and counts["Food props"] >= 3
    with pytest.raises(CurationError, match="saved search"):
        curator.add_to_collection("Food props", [uid_of(conn, "ding")])
    with pytest.raises(CurationError, match="already a collection"):
        curator.create_collection("lard lads ASSETS")
    log_id = curator.delete_collection(cid)
    assert [c["name"] for c in list_collections(conn, defs)] == ["Food props"]
    curator.undo(log_id)
    assert names(conn, defs, 'collection:"Lard Lads assets"') == {"donut01", "Lard Lads Donuts"}


# Suggestions --------------------------------------------------------------------------------------


def test_texture_link_suggestions(lib, defs):
    conn, curator = lib
    links = {s["subject_name"]: s for s in list_suggestions(conn, kind="texture_link")}
    assert {f["channel"] for f in links["Barrel01"]["payload"]["files"]} == {"Normal"}
    # Bethesda layout: meshes/clutter/donut01.nif <-> textures/clutter/donut01_d.dds
    assert [f["rel"] for f in links["donut01"]["payload"]["files"]] == [
        "mods/Lard Lads Donuts/textures/clutter/donut01_d.dds"]
    curator.accept(links["Barrel01"]["id"])
    assert "Barrel01" in names(conn, defs, "is:linked")
    assert [s["subject_name"] for s in list_suggestions(conn, state="accepted")] == ["Barrel01"]


def test_rejected_suggestions_stay_rejected(scan, mixed, lib, defs):
    conn, curator = lib
    variant = list_suggestions(conn, kind="variant_group")
    assert [s["payload"]["variants"] for s in variant] == [
        {uid_of(conn, "Donut01_Blue"): "Blue", uid_of(conn, "Donut01_Pink"): "Pink"}]
    log_id = curator.reject(variant[0]["id"])
    scan(mixed)
    assert list_suggestions(conn, kind="variant_group") == []
    curator.undo(log_id)
    assert len(list_suggestions(conn, kind="variant_group")) == 1


def test_accepting_a_variant_group(lib, defs):
    conn, curator = lib
    [s] = list_suggestions(conn, kind="variant_group")
    log_id = curator.accept(s["id"])
    pink = uid_of(conn, "Donut01_Pink")
    target = s["subject"]
    assert dossier_detail(conn, defs, target)["variants"] == ["Blue", "Pink"]
    assert len({b.uid for b in list_dossiers(conn, defs, query="donut01 type:mesh", group="all").items
                if b.name.startswith("Donut01_")}) == 1
    curator.undo(log_id)
    assert list_suggestions(conn, kind="variant_group")[0]["id"] == s["id"]  # pending again
    assert repo.effective_dossier(conn, pink)["name"] == "Donut01_Pink"


def test_suggestions_go_stale(scan, mixed, lib, defs):
    conn, _ = lib
    (mixed / "Loose" / "Downloads" / "barrel" / "Barrel01_N.png").unlink()
    report = scan(mixed)
    assert report.suggestions["stale"] >= 1
    assert "Barrel01" in [s["subject_name"] for s in list_suggestions(conn, state="stale")]


# Hand-installed Daz content ----------------------------------------------------------------------


def test_unmanifested_daz_products(scan, tmp_path, library):
    lib = copy_fixture("fake_daz_library", tmp_path / "scan" / "Daz")
    product = lib / "People" / "Genesis 9" / "Hair" / "Bob Cut"
    write(product / "Bob Cut.duf", b"{}")
    write(product / "Materials" / "Iray" / "Bob Cut Blonde.duf", b"{}")
    write(lib / "data" / "Vendor" / "Bob Cut" / "Bob Cut.dsf", b"{}")
    write(lib / "Runtime" / "Textures" / "Vendor" / "Bob Cut" / "bob_d.jpg", b"jpg")
    write(lib / "People" / "Genesis 9" / "Stray.duf", b"{}")  # too shallow to be a product
    scan(lib)
    conn = library()
    row = conn.execute("SELECT id, confidence_base FROM dossier WHERE name = 'Bob Cut' AND type_id = 'product'").fetchone()
    assert row["confidence_base"] == 0.6
    files = {r[0] for r in conn.execute(
        "SELECT f.rel_path FROM entry_file ef JOIN entry e ON e.id = ef.entry_id JOIN ledger l ON l.id = e.ledger_id"
        " JOIN file f ON f.id = ef.file_id WHERE l.dossier_id = ?", (row["id"],))}
    assert files == {"People/Genesis 9/Hair/Bob Cut/Bob Cut.duf",
                     "People/Genesis 9/Hair/Bob Cut/Materials/Iray/Bob Cut Blonde.duf",
                     "data/Vendor/Bob Cut/Bob Cut.dsf", "Runtime/Textures/Vendor/Bob Cut/bob_d.jpg"}
    hair = conn.execute("SELECT type_id, parent_id FROM dossier WHERE name = 'Bob Cut' AND type_id != 'product'").fetchone()
    assert (hair["type_id"], hair["parent_id"]) == ("daz_hair", row["id"])


def test_folder_products_use_category_and_vendor_folders(defs):
    from exchange.scanner.layers.daz import _folder_products
    index = LexiconIndex(with_generated(defs, {"authors": [("dm", "dm"), ("Aeon Soul", "AeonSoul")]}))
    products = {p.name: p for p in _folder_products([
        "Animals/AM/Wolf 2/Wolf 2.duf",
        "Animals/AM/Wolf 2/Materials/Eyes/Wolf Eyes Gold.duf",  # Eyes is no part-folder word: folds in
        "Animals/AM/Wolf 2/Poses/Tail/Tail Up.duf",
        "Runtime/Textures/AM/Wolf 2/wolf_d.jpg",  # the product's name finds its data and textures
        "data/AM/Wolf 2/Morphs/Snout.dsf",
        "Runtime/Textures/AM/Eyes/eye_d.jpg",  # unmatched: only product names are used
        "Props/!! Sorted/Stray.duf",  # a sorting folder is never a product...
        "Props/!! Sorted/Barrel/Barrel.duf",  # ...and a category word (barrel) is not a category name
        *[f"data/{v}/Barrel/b.dsf" for v in ("V1", "V2", "V3", "V4")],  # a generic name: not used
        "Vehicles/!!sorted/Sci-Fi/Loose.duf",  # theme folder: never a product
        "Vehicles/!!sorted/Sci-Fi/Star Hopper/Star Hopper.duf",
        "Vehicles/!!sorted/Sci-Fi/Fantasy Props/Old.duf",  # theme + category name
        "Vehicles/!!sorted/Sci-Fi/Anime Girl Outfit/Outfit.duf",  # only contains a theme word
        "People/Genesis 8 Female/Poses/dm/Stray.duf",  # vendor folder: never a product
        "People/Genesis 8 Female/Poses/dm/Dance Poses/Spin.duf",
        "People/Genesis 8 Female/Poses/dm/Dance Poses/Part 2/Leap.duf",
        "Props/AeonSoul/Lamp/Lamp.duf",  # any spelling of a known author
    ], index)}
    assert {name: sorted(p.members) for name, p in products.items()} == {
        "Wolf 2": ["Animals/AM/Wolf 2/Materials/Eyes/Wolf Eyes Gold.duf", "Animals/AM/Wolf 2/Poses/Tail/Tail Up.duf",
                   "Animals/AM/Wolf 2/Wolf 2.duf", "Runtime/Textures/AM/Wolf 2/wolf_d.jpg",
                   "data/AM/Wolf 2/Morphs/Snout.dsf"],
        "Barrel": ["Props/!! Sorted/Barrel/Barrel.duf"],
        "Star Hopper": ["Vehicles/!!sorted/Sci-Fi/Star Hopper/Star Hopper.duf"],
        "Anime Girl Outfit": ["Vehicles/!!sorted/Sci-Fi/Anime Girl Outfit/Outfit.duf"],
        "Dance Poses": ["People/Genesis 8 Female/Poses/dm/Dance Poses/Part 2/Leap.duf",
                        "People/Genesis 8 Female/Poses/dm/Dance Poses/Spin.duf"],
        "Lamp": ["Props/AeonSoul/Lamp/Lamp.duf"],
    }
    assert products["Dance Poses"].fields["author"] == "dm"
    assert products["Lamp"].fields["author"] == "Aeon Soul"
    assert "author" not in products["Barrel"].fields


def test_found_authors_are_tidied_and_filtered(defs):
    from exchange.scanner.layers.base import FileInfo
    from exchange.scanner.layers.daz import ManifestProduct, _found_authors
    manifests = [ManifestProduct("A", {"authors": [" -dragonfly3d- ", "'", "\nRiverSoft Art"]})]
    files = [FileInfo(i, rel, 1, 1, "") for i, rel in enumerate([
        "data/Genesis 8 Female/Morphs/x.dsf", "People/Genesis 8 Female/Poses/p.duf",  # a figure
        "data/Plants/Tree/t.dsf",  # words other lexicons know
        "data/Arki/Hair/h.dsf", "data/cloud/1_2/c.dsf",
        "data/u2Lamp1_707/Lamp/l.dsf", "data/pPlane(11sg000)1/p/p.dsf"])]  # made by Daz imports
    assert _found_authors(manifests, files, LexiconIndex(defs)) == [
        ("Arki", "Arki"), ("RiverSoft Art", "RiverSoft Art"), ("dragonfly3d", "dragonfly3d")]


def test_known_authors_are_found_and_user_edits_win(scan, tmp_path, library, defs):
    lib = copy_fixture("fake_daz_library", tmp_path / "scan" / "Daz")
    write(lib / "data" / "Vendor X" / "Coat" / "Coat.dsf", b"{}")
    write(lib / "People" / "Genesis 9" / "Clothing" / "Vendor X" / "Coat" / "Coat.duf", b"{}")
    write(lib / "People" / "Genesis 9" / "Clothing" / "Vendor X" / "Stray.duf", b"{}")
    scan(lib)
    conn = library()
    known = with_generated(defs, repo.generated_words(conn)).lexicons["authors"]
    assert "Vendor X" in {t.value for t in known.terms}
    coat = conn.execute("SELECT d.id FROM dossier d WHERE d.name = 'Coat' AND d.type_id = 'product'").fetchone()
    assert repo.effective_fields(conn, repo.get_dossier(conn, coat[0])["uid"])["author"] == "Vendor X"
    assert not conn.execute("SELECT 1 FROM dossier WHERE name = 'Vendor X' AND type_id = 'product'").fetchone()

    # Removing a found author excludes it: the next regroup makes Vendor X a product again,
    # rescans never add it back, and undo restores it.
    user = tmp_path / "user"
    curator = Curator(conn, defs, user_dir=user)
    log_id = curator.set_lexicon_word("authors", "Vendor X", "Vendor X", present=False)
    assert "exclude = [\"Vendor X\"]" in (user / "lexicons" / "authors.toml").read_text(encoding="utf-8")
    from exchange.scanner.scan import regroup
    with repo.transaction(conn):
        regroup(conn, defs)
    assert conn.execute("SELECT 1 FROM dossier WHERE name = 'Vendor X' AND type_id = 'product'"
                        " AND EXISTS (SELECT 1 FROM ledger l JOIN entry e ON e.ledger_id = l.id"
                        " WHERE l.dossier_id = dossier.id AND e.status != 'retired')").fetchone()
    assert "Vendor X" not in {t.value for t in with_generated(defs, repo.generated_words(conn)).lexicons["authors"].terms}
    curator.undo(log_id)
    assert "exclude" not in (user / "lexicons" / "authors.toml").read_text(encoding="utf-8")
    assert "Vendor X" in {t.value for t in with_generated(defs, repo.generated_words(conn)).lexicons["authors"].terms}


# CLI ------------------------------------------------------------------------------------------------


def run(capsys, *argv):
    code = main(list(map(str, argv)))
    out = capsys.readouterr()
    return code, out.out, out.err


def test_cli(capsys, mixed, db_path):
    run(capsys, "scan", mixed, "--db", db_path, "--no-enrich")
    code, out, _ = run(capsys, "lexicon", "list", "--db", db_path)
    assert code == 0 and "category" in out and "texture_channel" in out
    code, out, _ = run(capsys, "suggest", "list", "--db", db_path, "--json")
    suggestions = json.loads(out)
    barrel = next(s for s in suggestions if s["subject_name"] == "Barrel01")
    code, out, _ = run(capsys, "suggest", "accept", barrel["id"], "--db", db_path)
    assert code == 0 and "Accepted 1" in out
    code, out, _ = run(capsys, "search", "is:linked", "--db", db_path, "--json")
    uid = json.loads(out)["items"][0]["uid"]
    code, out, _ = run(capsys, "curate", "tag", uid[:10], "--add", "Tavern", "--db", db_path, "--json")
    log_id = json.loads(out)["log_id"]
    code, out, _ = run(capsys, "curate", "set", "notes", "keep the rust", uid[:10], "--db", db_path)
    assert code == 0
    code, out, _ = run(capsys, "show", uid[:10], "--db", db_path)
    assert "notes: keep the rust  (yours)" in out
    code, out, _ = run(capsys, "undo", log_id, "--db", db_path)
    assert code == 0 and "redo with" in out
    code, out, _ = run(capsys, "collection", "create", "Taverns", "--query", "tag:container", "--db", db_path)
    code, out, _ = run(capsys, "collection", "list", "--db", db_path)
    assert "Taverns" in out and "smart: tag:container" in out
    code, out, _ = run(capsys, "history", "--db", db_path)
    assert "accept_texture_link" in out and "undo" in out
    code, out, _ = run(capsys, "classify", "--db", db_path)
    assert code == 0 and "dossiers classified" in out
    code, out, _ = run(capsys, "classify", "--regroup", "--db", db_path)
    assert code == 0 and "roots regrouped" in out
    code, out, _ = run(capsys, "lexicon", "show", "authors", "--db", db_path, "--json")
    assert code == 0 and json.loads(out)["kind"] == "author" and json.loads(out)["terms"]  # found by the scan
    code, _, err = run(capsys, "curate", "merge", "zzzz", uid[:10], "--db", db_path)
    assert code == 2 and "0 dossiers match" in err
