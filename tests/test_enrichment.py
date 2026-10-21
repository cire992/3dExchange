"""Scan phase 3: hashing, duplicate merging, mesh stats, Daz dependencies and thumbnails."""

import threading

from PIL import Image

from builders import glb_bytes, obj_bytes, png_bytes, write
from conftest import env_report
from exchange.db import repository as repo
from exchange.scanner.enrichment import thumbnail_dir
from test_readonly import snapshot


def dossier(conn, name):
    return conn.execute("SELECT * FROM dossier WHERE name = ?", (name,)).fetchone()


def fields(conn, name):
    return repo.effective_fields(conn, dossier(conn, name)["uid"])


def thumb(conn, db_path, name):
    row = conn.execute("SELECT t.* FROM thumbnail t JOIN dossier d ON d.id = t.dossier_id"
                       " WHERE d.name = ?", (name,)).fetchone()
    return row, (thumbnail_dir(db_path) / row["rel_path"] if row else None)


def test_hashing_is_incremental(scan, loose_folder, library):
    first = env_report(scan(loose_folder, enrich=True), "loose_files").enrichment
    assert first.hashed == 7
    second = env_report(scan(loose_folder, enrich=True), "loose_files").enrichment
    assert second.hashed == 0
    (loose_folder / "notes.txt").write_text("changed notes")
    third = env_report(scan(loose_folder, enrich=True), "loose_files").enrichment
    assert third.hashed == 1
    conn = library()
    assert conn.execute("SELECT count(*) FROM file WHERE hash IS NULL AND state = 'present'").fetchone()[0] == 0


def test_identical_copies_join_one_dossier(scan, tmp_path, library):
    root = tmp_path / "scan" / "Assets"
    write(root / "Downloads" / "Donut01.glb", glb_bytes())
    write(root / "Backup" / "copy of donut.glb", glb_bytes())
    write(root / "Other" / "Barrel.glb", glb_bytes(scale=3.0))
    report = scan(root, enrich=True)
    assert env_report(report, "loose_files").enrichment.merged == 1

    conn = library()
    [kept] = conn.execute("SELECT * FROM dossier WHERE name IN ('Donut01', 'copy of donut')").fetchall()
    statuses = sorted(r["status"] for r in repo.entries_of(conn, kept["id"]))
    assert statuses == ["origin", "unknown"]  # the copy: matched by hash, provenance unknown

    # A rescan keeps the merge and does not let the copy rename the dossier.
    scan(root, enrich=True)
    assert dossier(conn, kept["name"])["uid"] == kept["uid"]
    assert conn.execute("SELECT count(*) FROM dossier WHERE type_id != 'product'").fetchone()[0] == 2


def test_dossiers_with_user_edits_are_not_merged(scan, tmp_path, library):
    root = tmp_path / "scan" / "Assets"
    write(root / "A" / "One.glb", glb_bytes())
    scan(root, enrich=True)
    conn = library()
    uid = dossier(conn, "One")["uid"]
    write(root / "B" / "Two.glb", glb_bytes())
    scan(root)
    two = dossier(conn, "Two")["uid"]
    with repo.transaction(conn):
        repo.set_override_tag(conn, two, "Keep", "add")
    report = scan(root, enrich=True)
    assert env_report(report, "loose_files").enrichment.merged == 0
    assert dossier(conn, "One")["uid"] == uid and dossier(conn, "Two")["uid"] == two


def test_mesh_stats_and_type_refinement(scan, tmp_path, library):
    root = tmp_path / "scan" / "Meshes"
    write(root / "static" / "Crate.glb", glb_bytes(scale=2.0))
    write(root / "rigged" / "Robot.glb", glb_bytes(skinned=True))
    write(root / "obj" / "Box.obj", obj_bytes())
    write(root / "broken" / "Bad.glb", b"glTF nonsense that is long enough to be a file")
    stats = env_report(scan(root, enrich=True), "loose_files").enrichment
    assert (stats.meshes, stats.mesh_errors, stats.refined_types) == (3, 1, 3)

    conn = library()
    assert dossier(conn, "Crate")["type_id"] == "static_mesh"
    assert dossier(conn, "Robot")["type_id"] == "skinned_mesh"
    assert dossier(conn, "Box")["type_id"] == "static_mesh"
    assert dossier(conn, "Bad")["type_id"] == "mesh"
    crate = fields(conn, "Crate")
    assert crate["mesh_triangles"] == 12 and crate["mesh_size"] == 2.0
    assert "mesh_error" in fields(conn, "Bad")

    scan(root)  # identification again: the refined type survives
    assert dossier(conn, "Crate")["type_id"] == "static_mesh"


def test_daz_dependencies(scan, daz_library, library):
    report = scan(daz_library, enrich=True)
    stats = env_report(report, "daz_studio").enrichment
    assert stats.broken_dependencies >= 2  # Genesis 9 base and the boots' geometry are not installed

    conn = library()
    marius = dossier(conn, "Marius HD-8K")
    deps = {r["reference"]: r for r in conn.execute(
        "SELECT x.*, t.name AS target FROM dossier_dependency x LEFT JOIN dossier t ON t.id = x.target_dossier_id"
        " WHERE x.dossier_id = ?", (marius["id"],))}
    morph = deps["data/DAZ 3D/Genesis 9/Base/Morphs/DAZ 3D/Marius/FHMMarius.dsf"]
    assert morph["status"] == "ok" and morph["target"] == "Marius HD-8K for Genesis 9"  # a support file
    texture = deps["Runtime/Textures/DAZ/Characters/Genesis9/Marius/Marius_Face_D_1001.jpg"]
    assert texture["status"] == "ok" and texture["target"] == "Marius HD-8K for Genesis 9"  # a product file
    assert deps["data/DAZ 3D/Genesis 9/Base/Genesis9.dsf"]["status"] == "broken"

    body_refs = fields(conn, "Marius Body")["references"]  # read from a gzip-compressed .duf
    assert body_refs == ["data/DAZ 3D/Genesis 9/Base/Morphs/DAZ 3D/Marius/FBMMarius.dsf"]
    assert fields(conn, "Summer Dress")["references"] == ["data/DAZ 3D/Summer Dress/Summer Dress.dsf"]


def test_dependencies_resolve_across_content_directories(scan, daz_two_dirs, library):
    scan(daz_two_dirs, enrich=True)
    conn = library()
    connect = dossier(conn, "Marius Connect")
    row = conn.execute("SELECT status FROM dossier_dependency WHERE dossier_id = ?", (connect["id"],)).fetchone()
    assert row["status"] == "ok"  # the morph lives in the other content directory


def test_thumbnails(scan, daz_library, tmp_path, db_path, library):
    write(daz_library / "Props" / "Teapot.glb", glb_bytes())
    report = scan(daz_library, enrich=True)
    stats = env_report(report, "daz_studio").enrichment
    assert stats.thumbnails >= 3 and stats.thumbnail_errors == 0

    conn = library()
    row, path = thumb(conn, db_path, "Summer Dress")
    assert row["source_kind"] == "preview" and path.is_file()  # Summer Dress.duf.png beside the file
    assert Image.open(path).size == (64, 48)  # small previews are not enlarged
    row, path = thumb(conn, db_path, "Marius HD-8K for Genesis 9")
    assert row["source_kind"] == "preview"  # the product image beside the manifest
    row, path = thumb(conn, db_path, "Teapot")
    assert row["source_kind"] == "render" and Image.open(path).size == (256, 256)
    row, _ = thumb(conn, db_path, "Summer Dress for Genesis 8 Female")
    assert row["source_kind"] == "child"  # borrowed from its wearable
    assert thumbnail_dir(db_path).parent == db_path.parent

    made = stats.thumbnails
    again = env_report(scan(daz_library, enrich=True), "daz_studio").enrichment
    assert again.thumbnails == 0 < made  # nothing changed, nothing redrawn


def test_unreal_thumbnails(scan, unreal, db_path, library):
    scan(unreal, enrich=True)
    conn = library()
    row, path = thumb(conn, db_path, "SM_Rock")
    assert row["source_kind"] == "embedded" and Image.open(path).size == (32, 32)
    assert thumb(conn, db_path, "M_Rock")[0] is None  # saved without a thumbnail
    row, _ = thumb(conn, db_path, "Cool Tools")
    assert row["source_kind"] == "preview"  # the plugin icon


def test_enrichment_is_read_only(scan, mixed, unreal):
    write(mixed / "Loose" / "Ring.glb", glb_bytes())
    for folder in (mixed, unreal):
        before = snapshot(folder)
        scan(folder, enrich=True)
        assert snapshot(folder) == before


def test_enrichment_can_be_cancelled(scan, mixed, library):
    stop = threading.Event()
    seen = []

    def progress(event):
        seen.append(event)
        if event.phase == 3:
            stop.set()

    report = scan(mixed, enrich=True, progress=progress, cancel=stop)
    assert report.cancelled
    assert any(e.phase == 2 for e in seen)
    conn = library()  # identification results are saved; the library is consistent
    assert conn.execute("SELECT count(*) FROM dossier").fetchone()[0] > 0
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_image_preview_beside_a_mesh(scan, tmp_path, db_path, library):
    root = tmp_path / "scan" / "Kit"
    write(root / "Chair.fbx", b"Kaydara FBX Binary  \0" + b"\0" * 100)
    write(root / "Chair.png", png_bytes((300, 200)))
    scan(root, enrich=True)
    row, path = thumb(library(), db_path, "Chair")
    assert row["source_kind"] == "preview"
    assert Image.open(path).size == (256, 171)
    assert row["source_hash"].startswith("preview:")
