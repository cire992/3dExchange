"""Daz saved characters, subsets and wearables: identified by the type their file says it is."""

import dataclasses
import gzip
import json
import os

import pytest

from builders import root_report, write
from exchange.cli import main
from exchange.curation import Curator
from exchange.scanner import readonly
from exchange.scanner.formats import daz_asset_type
from exchange.scanner.layers.base import LayerContext
from exchange.scanner.scan import run_scan

from test_readonly import set_readonly, snapshot

CHARACTER = "People/Genesis 9/Genesis 9 Exchange.duf"


def doc(kind, **extra):
    return json.dumps({"file_version": "0.6.0.0", "asset_info": {"id": "/x.duf", "type": kind}, **extra}).encode()


def put(lib, rel, data, gzipped=False):
    return write(lib.joinpath(*rel.split("/")), gzip.compress(data) if gzipped else data)


def entry(conn, rel):
    """The dossier row and entry key of a file's own (`file:`) entry, or None."""
    return conn.execute(
        "SELECT d.*, e.id AS entry_id, e.identity_key, e.status FROM dossier d"
        " JOIN ledger l ON l.dossier_id = d.id JOIN entry e ON e.ledger_id = l.id"
        " WHERE e.identity_key = ?", (f"file:{rel.casefold()}",)).fetchone()


def fields(conn, dossier_id):
    rows = conn.execute("SELECT field, value FROM dossier_field WHERE dossier_id = ?", (dossier_id,))
    return {r["field"]: json.loads(r["value"]) for r in rows}


def owners(conn, rel):
    """Identity keys of the entries holding a file, with its role."""
    return conn.execute(
        "SELECT e.identity_key, ef.role FROM entry_file ef JOIN entry e ON e.id = ef.entry_id"
        " JOIN file f ON f.id = ef.file_id WHERE f.rel_path = ?", (rel,)).fetchall()


def stats_of(report):
    return root_report(report, "daz_studio").identification


def with_asset_types(definitions, asset_types):
    env = definitions.environments["daz_studio"]
    options = {**env.layer_options, "asset_types": asset_types}
    return dataclasses.replace(definitions, environments={
        **definitions.environments, "daz_studio": dataclasses.replace(env, layer_options=options)})


# read_head ----------------------------------------------------------------------------------------


def test_read_head_plain(tmp_path):
    big = write(tmp_path / "big.bin", os.urandom(200_000))
    assert readonly.read_head(big) == big.read_bytes()[:65_536]
    small = write(tmp_path / "small.bin", b"hello")
    assert readonly.read_head(small) == b"hello"
    assert readonly.read_head(tmp_path / "missing.bin") is None


def test_read_head_gzip(tmp_path):
    small = write(tmp_path / "small.duf", gzip.compress(doc("character")))
    assert readonly.read_head(small) == doc("character")
    padded = doc("character", pad=os.urandom(200_000).hex())
    big = write(tmp_path / "big.duf", gzip.compress(padded))
    assert big.stat().st_size > 128 * 1024
    head = readonly.read_head(big)
    assert 0 < len(head) <= 65_536 and padded.startswith(head)


def test_read_head_corrupt_gzip(tmp_path):
    assert readonly.read_head(write(tmp_path / "bad.duf", b"\x1f\x8b" + b"garbage, not a stream")) is None


# daz_asset_type -----------------------------------------------------------------------------------

FULL = doc("character", scene={"nodes": []})


@pytest.mark.parametrize("head, expected", [
    (FULL, "character"),
    (FULL[:-12], "character"),  # cut mid-JSON after asset_info
    (b"\xef\xbb\xbf" + FULL, "character"),
    ('{"asset_info": {"type": "wearable"}, "label": "é'.encode()[:-1], "wearable"),  # cut inside a character
    (None, None),
    (b"", None),
    (b"not json", None),
    (b"{}", None),
    (b'garbage {"asset_info": {"type": "character"}}', None),
    (b'{"scene": {"asset_info": {"type": "character"}}}', None),
    (b'{"asset_info": "character"}', None),
    (b'{"asset_info": {"type": "charac', None),
    (b'{"asset_info": {"type": 5}}', None),
])
def test_daz_asset_type(head, expected):
    assert daz_asset_type(head) == expected


# Identification -----------------------------------------------------------------------------------


def test_saved_character(scan, library, daz_library):
    put(daz_library, CHARACTER, doc("character"), gzipped=True)
    stats = stats_of(scan(daz_library))
    assert stats.warnings == [] and stats.unattached_files == 1  # random.png only
    conn = library()
    row = entry(conn, CHARACTER)
    assert (row["name"], row["type_id"], row["parent_id"]) == ("Genesis 9 Exchange", "daz_character_preset", None)
    assert row["confidence_base"] == 0.6 and json.loads(row["signals"]) == ["saved file: character"]
    assert fields(conn, row["id"])["variant"] == "genesis_9"
    assert row["identity_key"] == "file:people/genesis 9/genesis 9 exchange.duf"
    assert [tuple(o) for o in owners(conn, CHARACTER)] == [(row["identity_key"], "primary")]


def test_saved_scene_subset(scan, library, definitions, daz_library):
    rel = "People/Genesis 8 Female/Genesis 8 Basic Female Exchange.duf"
    put(daz_library, rel, doc("scene_subset"))
    scan(daz_library)
    row = entry(library(), rel)
    assert (row["type_id"], row["parent_id"]) == ("daz_scene_subset", None)
    assert json.loads(row["signals"]) == ["saved file: scene_subset"]
    assert fields(library(), row["id"])["variant"] == "genesis_8"
    subset = definitions.dossier_types["daz_scene_subset"]
    assert subset.extends is None and not subset.identify
    assert not definitions.is_a("daz_scene_subset", "mesh")
    assert "daz_scene_subset" in definitions.environments["daz_studio"].native_dossier_types


def test_saved_wearable_and_upper_case_extension(scan, library, daz_library):
    put(daz_library, "Scenes/Coat.duf", doc("wearable"))
    put(daz_library, "Scenes/UPPER.DUF", doc("character"), gzipped=True)
    scan(daz_library)
    coat, upper = entry(library(), "Scenes/Coat.duf"), entry(library(), "Scenes/UPPER.DUF")
    assert (coat["type_id"], coat["parent_id"]) == ("daz_wearable", None)
    assert json.loads(coat["signals"]) == ["saved file: wearable"]
    assert upper["type_id"] == "daz_character_preset"


@pytest.mark.parametrize("name, data, gzipped", ids=lambda v: v if isinstance(v, str) else "", argvalues=[
    ("preset", doc("preset_material"), False),
    ("scene", doc("scene"), True),
    ("no info", b'{"file_version": "0.6.0.0"}', False),
    ("text", b"this is not json at all", False),
    ("late", json.dumps({"pad": "x" * 70_000, "asset_info": {"type": "character"}}).encode(), True),
])
def test_other_files_stay_unattached(scan, library, daz_library, name, data, gzipped):
    rel = f"People/Genesis 9/{name}.duf"
    put(daz_library, rel, data, gzipped)
    stats = stats_of(scan(daz_library))
    assert stats.unattached_files == 2 and stats.warnings == []  # random.png and this file
    conn = library()
    assert entry(conn, rel) is None and owners(conn, rel) == []


def test_data_and_runtime_are_not_read(scan, library, daz_library):
    put(daz_library, "data/Saved/Saved Hero.duf", doc("character"))
    put(daz_library, "Runtime/Libraries/Props/Crate.duf", doc("scene_subset"))
    put(daz_library, "DATA/More/Other.duf", doc("character"), gzipped=True)
    stats = stats_of(scan(daz_library))
    assert stats.unattached_files == 4 and stats.warnings == []
    conn = library()
    for rel in ("data/Saved/Saved Hero.duf", "Runtime/Libraries/Props/Crate.duf", "DATA/More/Other.duf"):
        assert entry(conn, rel) is None and owners(conn, rel) == []


def test_type_rule_wins(scan, library, daz_library):
    rel = "People/Genesis 9/Characters/Rule Wins.duf"
    put(daz_library, rel, doc("wearable"))
    scan(daz_library)
    row = entry(library(), rel)
    assert row["type_id"] == "daz_character_preset"
    assert json.loads(row["signals"]) == ["rule daz_character_preset: People/*/Characters/**/*.duf"]


def test_product_files_get_no_second_dossier(scan, library, daz_library):
    pose, kira = "People/Genesis 9/Poses/Marius/Marius Pose.duf", "People/Genesis 9/Saved/Kira Build/Kira Body.duf"
    put(daz_library, pose, doc("character"))
    put(daz_library, kira, doc("character"), gzipped=True)
    scan(daz_library)
    conn = library()
    assert entry(conn, pose) is None and entry(conn, kira) is None
    assert [o["identity_key"].startswith("product:manifest:") for o in owners(conn, pose)] == [True]
    assert [tuple(o) for o in owners(conn, kira)] == [("product:folder:people/genesis 9/saved/kira build", "support")]


def test_user_link_and_requisition_output_keep_precedence(scan, library, definitions, daz_library):
    from exchange.requisitions.sidecars import write_sidecar

    linked = "People/Genesis 9/Linked.duf"
    put(daz_library, linked, b"{}")
    scan(daz_library)
    conn = library()
    target = conn.execute("SELECT uid FROM dossier WHERE name = 'Marius HD-8K for Genesis 9'").fetchone()[0]
    file = conn.execute("SELECT root_id, rel_key FROM file WHERE rel_path = ?", (linked,)).fetchone()
    Curator(conn, definitions).link_files(target, [(file["root_id"], file["rel_key"])])
    put(daz_library, linked, doc("character"))
    scan(daz_library)
    assert entry(conn, linked) is None
    assert conn.execute(
        "SELECT d.uid FROM entry_file ef JOIN entry e ON e.id = ef.entry_id JOIN ledger l ON l.id = e.ledger_id"
        " JOIN dossier d ON d.id = l.dossier_id JOIN file f ON f.id = ef.file_id WHERE f.rel_path = ?",
        (linked,)).fetchone()[0] == target

    output = "People/Genesis 9/Output Hero.duf"
    put(daz_library, output, doc("character"))
    write_sidecar(daz_library / "People" / "Genesis 9", {"requisition": "req-1", "outputs": [
        {"dossier": target, "name": "Marius", "type_id": "product", "files": ["Output Hero.duf"]}]})
    scan(daz_library)
    assert entry(conn, output) is None
    assert [o["identity_key"] for o in owners(conn, output)] == ["requisition:req-1:0"]


def test_large_gzipped_character(scan, library, daz_library):
    rel = "People/Genesis 9/Big Hero.duf"
    path = put(daz_library, rel, gzip.compress(doc("character", pad=os.urandom(200_000).hex())))
    assert path.stat().st_size > 128 * 1024
    scan(daz_library)
    assert entry(library(), rel)["type_id"] == "daz_character_preset"


def test_only_eligible_files_are_read(monkeypatch, definitions, db_path, daz_library):
    eligible = "People/Genesis 9/Genesis 9 Exchange.duf"
    put(daz_library, eligible, doc("character"))
    for rel in ("data/Saved/Saved Hero.duf", "Runtime/Libraries/Props/Crate.duf",
                "People/Genesis 9/Characters/Rule Wins.duf", "People/Genesis 9/Saved/Kira Build/Kira Body.duf"):
        put(daz_library, rel, doc("character"))
    read = []
    original = LayerContext.read_head
    monkeypatch.setattr(LayerContext, "read_head", lambda self, rel: read.append(rel) or original(self, rel))
    run_scan(daz_library, db_path=db_path, definitions=definitions)
    assert read == [eligible]
    read.clear()
    run_scan(daz_library, db_path=db_path, definitions=with_asset_types(definitions, {}))
    assert read == []


def test_ignore_rule_hides_a_saved_file(scan, library, db_path, daz_library):
    put(daz_library, CHARACTER, doc("character"))
    scan(daz_library)
    conn = library()
    env = conn.execute("SELECT id FROM environment").fetchone()[0]
    assert entry(conn, CHARACTER)["status"] != "retired"
    assert main(["env", "config", str(env), "--ignore-add", CHARACTER, "--db", str(db_path)]) == 0
    assert stats_of(scan(daz_library)).retired_entries == 1
    assert entry(conn, CHARACTER)["status"] == "retired"


def test_rescan_keeps_the_dossier(scan, library, daz_library):
    path = put(daz_library, CHARACTER, doc("character"), gzipped=True)
    scan(daz_library)
    conn = library()
    uid = entry(conn, CHARACTER)["uid"]
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))
    scan(daz_library)
    assert entry(conn, CHARACTER)["uid"] == uid

    saved = path.read_bytes()
    path.unlink()
    assert stats_of(scan(daz_library)).retired_entries == 1
    assert entry(conn, CHARACTER)["status"] == "retired"
    path.write_bytes(saved)
    scan(daz_library)
    row = entry(conn, CHARACTER)
    assert (row["uid"], row["status"] != "retired") == (uid, True)


def test_scanning_writes_nothing(scan, daz_library):
    put(daz_library, CHARACTER, doc("character"), gzipped=True)
    put(daz_library, "Scenes/Coat.duf", doc("wearable"))
    set_readonly(daz_library, True)
    try:
        before = snapshot(daz_library)
        scan(daz_library)
        scan(daz_library)
        assert snapshot(daz_library) == before
    finally:
        set_readonly(daz_library, False)


def test_claim_add_reads_acquired(capsys, scan, library, db_path, daz_library):
    put(daz_library, CHARACTER, doc("character"), gzipped=True)
    scan(daz_library)
    conn = library()
    uid, env = entry(conn, CHARACTER)["uid"], conn.execute("SELECT id FROM environment").fetchone()[0]
    capsys.readouterr()
    assert main(["claim", "add", uid, "--env", str(env), "--json", "--db", str(db_path)]) == 0
    assert json.loads(capsys.readouterr().out)["milestone"] == "acquired"


def test_unknown_asset_type_warns(definitions, db_path, daz_library):
    put(daz_library, CHARACTER, doc("character"))
    report = run_scan(daz_library, db_path=db_path, definitions=with_asset_types(definitions, {"character": "ghost"}))
    stats = stats_of(report)
    assert "asset_types maps to unknown dossier type 'ghost'" in stats.warnings
    assert stats.unattached_files == 2
