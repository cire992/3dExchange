"""R4c: the what's-new marker (core): when a scan sets it, how "new" lists, and what moves it."""

import shutil
import sqlite3

import pytest

from exchange.db import open_library
from exchange.library.new import mark_seen, marker, start_marker
from exchange.library.query import list_dossiers
from exchange.scanner.scan import run_rescan, run_scan


class After:
    """A cancel that is clear for the first ``n`` looks and set afterwards."""

    def __init__(self, n: int) -> None:
        self.left = n

    def is_set(self) -> bool:
        self.left -= 1
        return self.left < 0


def read(db_path, sql="SELECT 1", *args):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(sql, args).fetchall()
    finally:
        conn.close()


def highest(db_path):
    return read(db_path, "SELECT max(id) FROM dossier")[0][0]


def current(db_path):
    conn = open_library(db_path)
    try:
        return marker(conn)
    finally:
        conn.close()


def drop_marker(db_path):
    conn = sqlite3.connect(db_path, isolation_level=None)
    conn.execute("DELETE FROM library_setting WHERE key = 'new_marker'")
    conn.close()


def uids(db_path, definitions, **kwargs):
    conn = open_library(db_path)
    try:
        return [b.uid for b in list_dossiers(conn, definitions, new=True, **kwargs).items]
    finally:
        conn.close()


def test_the_first_scan_sets_the_marker_at_the_highest_id(scan, loose_folder, db_path, definitions):
    scan(loose_folder)
    assert current(db_path) == highest(db_path) > 0
    assert read(db_path, "SELECT value FROM library_setting WHERE key = 'new_marker'")[0][0] == str(highest(db_path))
    for group in ("product", "type", "all"):
        assert uids(db_path, definitions, group=group) == []


def test_a_later_scan_leaves_the_marker_and_lists_what_it_found(scan, loose_folder, mo2_instance, db_path, definitions):
    scan(loose_folder)
    first = current(db_path)
    scan(mo2_instance)
    assert current(db_path) == first < highest(db_path)
    conn = open_library(db_path)
    names = [b.name for b in list_dossiers(conn, definitions, new=True, group="all").items]
    conn.close()
    assert sorted(names) == ["Lard Lads Donuts", "Test Requisitions", "donut01", "donut01_pink"]


def test_an_empty_first_scan_sets_nothing(scan, tmp_path, loose_folder, db_path, definitions):
    empty = tmp_path / "scan" / "Empty"
    empty.mkdir(parents=True)
    scan(empty)
    assert current(db_path) is None
    scan(loose_folder)
    assert current(db_path) == highest(db_path) is not None
    assert uids(db_path, definitions, group="all") == []


def test_a_dry_run_sets_no_marker(scan, loose_folder, db_path):
    scan(loose_folder)
    drop_marker(db_path)
    scan(loose_folder, dry_run=True)
    assert current(db_path) is None and highest(db_path)


def test_a_cancelled_scan_sets_no_marker(mixed, db_path, definitions):
    report = run_scan(mixed, db_path=db_path, definitions=definitions, cancel=After(1))
    assert report.cancelled and highest(db_path) and current(db_path) is None


def test_a_cancelled_rescan_sets_no_marker(scan, loose_folder, db_path, definitions):
    scan(loose_folder)
    drop_marker(db_path)
    report = run_rescan(db_path=db_path, definitions=definitions, cancel=After(0))
    assert report.cancelled and current(db_path) is None


def test_a_library_with_no_marker_lists_nothing_until_its_next_scan(scan, loose_folder, db_path, definitions):
    scan(loose_folder)
    drop_marker(db_path)
    assert uids(db_path, definitions, group="all") == []
    conn = open_library(db_path)
    assert list_dossiers(conn, definitions, new=True).total == 0
    conn.close()
    run_rescan(db_path=db_path, definitions=definitions)
    assert current(db_path) == highest(db_path)
    assert uids(db_path, definitions, group="all") == []


def test_start_marker_only_starts_and_mark_seen_only_moves(scan, loose_folder, mo2_instance, db_path):
    conn = open_library(db_path)
    try:
        start_marker(conn)
        mark_seen(conn)
        assert marker(conn) is None  # no dossiers: nothing to start, nothing to move
        scan(loose_folder)
        first = marker(conn)
        scan(mo2_instance)
        start_marker(conn)
        assert marker(conn) == first  # already started
        mark_seen(conn)
        assert marker(conn) == highest(db_path) > first
        conn.execute("DELETE FROM library_setting WHERE key = 'new_marker'")
        mark_seen(conn)
        assert marker(conn) is None  # nothing to move
        start_marker(conn)
        assert marker(conn) == highest(db_path)
    finally:
        conn.close()


def test_an_emptied_library_keeps_its_marker(scan, loose_folder, db_path):
    scan(loose_folder)
    first = current(db_path)
    conn = sqlite3.connect(db_path, isolation_level=None)
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("DELETE FROM dossier")
    conn.close()
    conn = open_library(db_path)
    try:
        mark_seen(conn)
        start_marker(conn)
        assert marker(conn) == first
    finally:
        conn.close()


def test_a_rescan_finding_nothing_changes_nothing(scan, loose_folder, mo2_instance, db_path, definitions):
    scan(loose_folder)
    scan(mo2_instance)
    before, first = uids(db_path, definitions, group="all"), current(db_path)
    run_rescan(db_path=db_path, definitions=definitions)
    assert uids(db_path, definitions, group="all") == before and len(before) == 4
    assert current(db_path) == first


def test_a_new_child_of_an_old_product_is_listed_with_group_product(scan, mo2_instance, db_path, definitions):
    scan(mo2_instance)
    mods = mo2_instance / "mods" / "Lard Lads Donuts" / "meshes"
    shutil.copy(mods / "clutter" / "donut01.nif", mods / "donut02.nif")
    run_rescan(db_path=db_path, definitions=definitions)
    conn = open_library(db_path)
    try:
        listed = list_dossiers(conn, definitions, new=True)
        assert [b.name for b in listed.items] == ["donut02"] and listed.total == 1
        assert "donut02" not in [b.name for b in list_dossiers(conn, definitions).items]
    finally:
        conn.close()


def test_a_new_thing_whose_files_are_gone_is_not_listed(scan, loose_folder, db_path, definitions):
    scan(loose_folder)
    chime = loose_folder / "sounds" / "chime.wav"
    shutil.copy(loose_folder / "sounds" / "ding.wav", chime)
    run_rescan(db_path=db_path, definitions=definitions)
    # chime, and the "sounds" product it made together with ding
    assert len(uids(db_path, definitions, group="product")) == 1 and len(uids(db_path, definitions, group="all")) == 2
    chime.unlink()
    run_rescan(db_path=db_path, definitions=definitions)
    assert uids(db_path, definitions, group="product") == [] and uids(db_path, definitions, group="all") == []


def test_only_entries_exchange_wrote_do_not_make_a_dossier_new(scan, loose_folder, mo2_instance, db_path, definitions):
    scan(loose_folder)
    scan(mo2_instance)
    assert len(uids(db_path, definitions, group="all")) == 4
    conn = sqlite3.connect(db_path, isolation_level=None)
    conn.execute("UPDATE entry SET requisition_id = 1 WHERE ledger_id IN (SELECT l.id FROM ledger l"
                 " JOIN dossier d ON d.id = l.dossier_id WHERE d.name = 'donut01')")
    conn.close()
    lib = open_library(db_path)
    names = {b.name for b in list_dossiers(lib, definitions, new=True, group="all").items}
    lib.close()
    assert names == {"Lard Lads Donuts", "Test Requisitions", "donut01_pink"}
