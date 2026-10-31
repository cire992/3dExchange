"""R4d: deleting dossiers frees their ids, so the marker comes down with them."""

from exchange.db import open_library
from exchange.db import repository as repo
from exchange.library.new import mark_seen, marker
from test_new_marker import current, highest, uids


def forget(db_path, type_id):
    conn = open_library(db_path)
    try:
        env = next(e for e in repo.list_environments(conn) if e["type_id"].startswith(type_id))
        with repo.transaction(conn):
            repo.forget_environment(conn, env["id"])
    finally:
        conn.close()


def seen(db_path):
    conn = open_library(db_path)
    try:
        mark_seen(conn)
    finally:
        conn.close()


def bare_dossier(conn):
    return repo.create_dossier(conn, type_id="asset", name="Spare", parent_id=None, confidence=0.5, signals=[])


def test_what_a_scan_finds_after_forgetting_an_environment_is_new(scan, loose_folder, daz_library, mo2_instance,
                                                                  db_path, definitions):
    scan(loose_folder)
    scan(daz_library)
    seen(db_path)
    forget(db_path, "daz")
    assert current(db_path) == highest(db_path)
    scan(mo2_instance)
    assert len(uids(db_path, definitions, group="all")) > 0


def test_deleting_the_highest_dossier_brings_the_marker_down(scan, loose_folder, db_path):
    scan(loose_folder)
    seen_up_to = highest(db_path)
    conn = open_library(db_path)
    try:
        with repo.transaction(conn):
            made = bare_dossier(conn)
            mark_seen(conn)
            repo.delete_dossier(conn, made)
        assert marker(conn) == seen_up_to == highest(db_path)
    finally:
        conn.close()


def test_deleting_a_new_dossier_leaves_the_marker(scan, loose_folder, db_path):
    scan(loose_folder)
    first = current(db_path)
    conn = open_library(db_path)
    try:
        with repo.transaction(conn):
            repo.delete_dossier(conn, bare_dossier(conn))
        assert marker(conn) == first
    finally:
        conn.close()


def test_forgetting_everything_makes_the_next_scan_the_first(scan, loose_folder, mo2_instance, db_path, definitions):
    scan(loose_folder)
    forget(db_path, "loose")
    assert highest(db_path) is None and current(db_path) is None
    scan(mo2_instance)
    assert current(db_path) == highest(db_path) and uids(db_path, definitions, group="all") == []
