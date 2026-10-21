import json

import pytest

from builders import root_report


def dossiers(conn, environment_type):
    """name -> row for every dossier with a live entry in environments of one type."""
    rows = conn.execute(
        "SELECT d.*, p.name AS parent_name, c.rel_path AS container, e.status"
        " FROM dossier d JOIN ledger l ON l.dossier_id = d.id"
        " JOIN environment env ON env.id = l.environment_id"
        " JOIN entry e ON e.ledger_id = l.id JOIN container c ON c.id = e.container_id"
        " LEFT JOIN dossier p ON p.id = d.parent_id"
        " WHERE env.type_id = ? AND e.status != 'retired'",
        (environment_type,),
    ).fetchall()
    return {r["name"]: r for r in rows}


def fields(conn, dossier_id):
    rows = conn.execute("SELECT field, value FROM dossier_field WHERE dossier_id = ?", (dossier_id,))
    return {r["field"]: json.loads(r["value"]) for r in rows}


def entry_files(conn, dossier_id):
    rows = conn.execute(
        "SELECT f.rel_path, ef.role FROM entry_file ef JOIN entry e ON e.id = ef.entry_id"
        " JOIN ledger l ON l.id = e.ledger_id JOIN file f ON f.id = ef.file_id"
        " WHERE l.dossier_id = ?", (dossier_id,))
    return {r["rel_path"]: r["role"] for r in rows}


def test_daz_products_from_manifests(scan, daz_library, library):
    report = scan(daz_library)
    stats = root_report(report, "daz_studio").identification
    assert (stats.containers, stats.products, stats.dossiers) == (1, 2, 7)
    assert stats.unattached_files == 1  # Runtime/Textures/random.png

    conn = library()
    d = dossiers(conn, "daz_studio")
    marius = d["Marius HD-8K for Genesis 9"]
    assert marius["type_id"] == "product"
    assert marius["confidence"] == 0.9
    assert marius["container"] == ""  # container = the content directory
    f = fields(conn, marius["id"])
    assert f["daz_product_token"] == "12345"
    assert f["authors"] == ["Jane Doe", "Daz 3D"]
    assert (f["manifest_files_listed"], f["manifest_files_missing"]) == (10, 1)
    assert f["daz_global_id"].startswith("0f1e2d3c")
    files = entry_files(conn, marius["id"])
    assert files["Runtime/Support/DAZ_3D_12345_Marius_HD-8K_for_Genesis_9.dsx"] == "primary"
    assert files["Runtime/Support/DAZ_3D_12345_Marius_HD-8K_for_Genesis_9.jpg"] == "support"

    # Children come from the manifest's assets, typed by their Daz ContentType.
    head = d["Marius Head"]
    assert (head["type_id"], head["confidence"]) == ("daz_morph", 0.85)
    assert head["parent_name"] == "Marius HD-8K for Genesis 9"
    head_fields = fields(conn, head["id"])
    assert head_fields["variant"] == "genesis_9"  # from the asset's compatibility
    assert head_fields["daz_content_type"] == "Preset/Morph/Apply/Head"
    assert d["Marius HD-8K"]["type_id"] == "daz_character_preset"
    assert "Marius Pose" not in d  # a pose preset stays a file of the product
    assert "FHMMarius" not in d  # morph data (.dsf) is a support file, not a dossier
    assert files["data/DAZ 3D/Genesis 9/Base/Morphs/DAZ 3D/Marius/FHMMarius.dsf"] == "support"

    dress = d["Summer Dress"]
    assert dress["type_id"] == "daz_wearable"
    assert dress["parent_name"] == "Summer Dress for Genesis 8 Female"
    assert fields(conn, dress["id"])["variant"] == "genesis_8"

    boots = d["Loose Boots"]  # installed by hand: no product, but still recognized
    assert boots["parent_id"] is None
    assert boots["type_id"] == "daz_wearable"
    tokens = [r[0] for r in conn.execute(
        "SELECT token FROM dossier_token WHERE dossier_id = ? ORDER BY position", (boots["id"],))]
    assert tokens == ["loose", "boots"]


def test_mo2_mods_are_containers_and_products(scan, mo2_instance, library):
    report = scan(mo2_instance)
    env = root_report(report, "skyrim_se")
    stats = env.identification
    assert (stats.containers, stats.products, stats.dossiers) == (2, 2, 4)
    assert stats.archives == 1
    assert stats.unattached_files == 0
    # downloads/ (ignore glob) plus instance files outside mods/
    assert stats.ignored_files == 5
    assert stats.layer_config["selected_profile"] == "Default"

    conn = library()
    d = dossiers(conn, "skyrim_se")
    lard = d["Lard Lads Donuts"]
    assert lard["container"] == "mods/Lard Lads Donuts"
    assert lard["confidence"] == 0.95
    f = fields(conn, lard["id"])
    assert f["nexus_mod_id"] == 12345
    assert f["version"] == "1.2.0"
    assert f["source"] == "Nexus"
    assert d["Test Requisitions"]["confidence"] == 0.9  # no meta.ini
    assert d["donut01"]["type_id"] == "mesh"  # static vs skinned is decided in phase 3
    assert d["donut01"]["parent_name"] == "Lard Lads Donuts"

    meta = json.loads(conn.execute(
        "SELECT scanned_meta FROM container WHERE name = 'Test Requisitions'").fetchone()[0])
    assert meta["enabled_in"] == {"Default": False}

    states = dict(conn.execute("SELECT rel_path, state FROM file").fetchall())
    assert states["downloads/Lard Lads Donuts-12345-1-2-0.7z"] == "ignored"
    assert states["ModOrganizer.ini"] == "ignored"
    assert states["mods/Lard Lads Donuts/LardLads - Textures.bsa"] == "present"
    assert conn.execute("SELECT is_archive FROM file WHERE ext = '.bsa'").fetchone()[0] == 1


def test_loose_files_use_folder_heuristics(scan, loose_folder, library):
    report = scan(loose_folder)
    stats = root_report(report, "loose_files").identification
    assert stats.products == 1
    assert stats.below_threshold == 1  # the folder-as-product guess goes to review
    assert stats.unattached_files == 2  # Barrel01_N.png, notes.txt

    d = dossiers(library(), "loose_files")
    assert d["props"]["type_id"] == "product"
    assert d["props"]["confidence"] == 0.3
    assert d["Donut01_Pink"]["parent_name"] == "props"
    assert d["Donut01_Pink"]["confidence"] == pytest.approx(0.56)
    assert d["Barrel01"]["parent_id"] is None  # a lone asset needs no product
    assert d["ding"]["type_id"] == "audio"


def test_daz_relocated_files(scan, daz_library, library):
    # The user reorganized the dress into their own folder scheme, and a generic file that the
    # Marius manifest lists (under a different folder) happens to exist once elsewhere.
    old = daz_library / "People" / "Genesis 8 Female" / "Clothing" / "Summer Dress"
    new = daz_library / "People" / "Clothing" / "Summer" / "Summer Dress"
    new.parent.mkdir(parents=True)
    old.rename(new)
    (daz_library / "Runtime" / "Textures" / "Other" / "Marius").mkdir(parents=True)
    (daz_library / "Runtime" / "Textures" / "Other" / "Marius_Body_D_1002.jpg").write_bytes(b"x")

    scan(daz_library)
    conn = library()
    d = dossiers(conn, "daz_studio")
    dress = fields(conn, d["Summer Dress for Genesis 8 Female"]["id"])
    assert (dress["manifest_files_relocated"], dress["manifest_files_missing"]) == (2, 0)
    assert d["Summer Dress"]["type_id"] == "daz_wearable"  # still the product's child, found by folder + name
    assert d["Summer Dress"]["parent_name"] == "Summer Dress for Genesis 8 Female"
    marius = fields(conn, d["Marius HD-8K for Genesis 9"]["id"])
    assert (marius["manifest_files_relocated"], marius["manifest_files_missing"]) == (0, 1)


def test_files_without_a_stem_keep_their_name(scan, tmp_path, library):
    from builders import glb_bytes, write

    write(tmp_path / "scan" / "odd" / ".glb", glb_bytes())
    scan(tmp_path / "scan" / "odd")
    assert library().execute("SELECT name FROM dossier").fetchall()[0][0] == ".glb"
