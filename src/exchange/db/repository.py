"""All SQL for the library database lives here."""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

from exchange.scanner.tokenize import tokenize


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_uid() -> str:
    return uuid.uuid4().hex


def to_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    conn.execute("BEGIN")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def _chunks(ids: Iterable[int], size: int = 500) -> Iterator[list[int]]:
    batch: list[int] = []
    for i in ids:
        batch.append(i)
        if len(batch) == size:
            yield batch
            batch = []
    if batch:
        yield batch


# Environments and roots -------------------------------------------------------------------------


def list_environments(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM environment ORDER BY id").fetchall()


def get_environment(conn: sqlite3.Connection, environment_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM environment WHERE id = ?", (environment_id,)).fetchone()


def list_roots(conn: sqlite3.Connection, environment_id: int | None = None) -> list[sqlite3.Row]:
    sql = ("SELECT r.*, e.type_id, e.name AS environment_name FROM environment_root r"
           " JOIN environment e ON e.id = r.environment_id")
    if environment_id is None:
        return conn.execute(sql + " ORDER BY r.id").fetchall()
    return conn.execute(sql + " WHERE r.environment_id = ? ORDER BY r.id", (environment_id,)).fetchall()


def find_root(conn: sqlite3.Connection, root_key: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT r.*, e.type_id FROM environment_root r JOIN environment e ON e.id = r.environment_id"
        " WHERE r.root_key = ?", (root_key,)).fetchone()


def create_environment(conn: sqlite3.Connection, *, type_id: str, name: str) -> int:
    cur = conn.execute(
        "INSERT INTO environment (uid, type_id, name, added_at) VALUES (?, ?, ?, ?)",
        (new_uid(), type_id, name, now()),
    )
    return cur.lastrowid


def upsert_root(
    conn: sqlite3.Connection, environment_id: int, *, path: str, root_key: str,
    variant: str | None, confidence: float, signals: list[str],
) -> int:
    """Register a root, or refresh its detection results and mark it online."""
    row = conn.execute("SELECT id FROM environment_root WHERE root_key = ?", (root_key,)).fetchone()
    if row is None:
        cur = conn.execute(
            "INSERT INTO environment_root (environment_id, path, root_key, variant,"
            " detection_confidence, detection_signals, added_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (environment_id, path, root_key, variant, confidence, to_json(signals), now()),
        )
        return cur.lastrowid
    conn.execute(
        "UPDATE environment_root SET path = ?, variant = ?, detection_confidence = ?,"
        " detection_signals = ?, status = 'online', offline_since = NULL WHERE id = ?",
        (path, variant, confidence, to_json(signals), row["id"]),
    )
    return row["id"]


def set_root_offline(conn: sqlite3.Connection, root_id: int) -> str:
    """Mark a root offline (entries are kept); returns when it first went offline."""
    conn.execute(
        "UPDATE environment_root SET status = 'offline',"
        " offline_since = COALESCE(offline_since, ?) WHERE id = ?", (now(), root_id))
    return conn.execute(
        "SELECT offline_since FROM environment_root WHERE id = ?", (root_id,)).fetchone()[0]


def finish_root_scan(conn: sqlite3.Connection, root_id: int, environment_id: int,
                     layer_config: Mapping[str, Any]) -> None:
    stamp = now()
    conn.execute("UPDATE environment_root SET last_scanned_at = ? WHERE id = ?", (stamp, root_id))
    conn.execute(
        "UPDATE environment SET layer_config = ?, last_scanned_at = ? WHERE id = ?",
        (to_json(dict(layer_config)), stamp, environment_id),
    )


def user_config(conn: sqlite3.Connection, environment_id: int) -> dict[str, Any]:
    row = conn.execute("SELECT user_config FROM environment WHERE id = ?", (environment_id,)).fetchone()
    return json.loads(row[0]) if row else {}


def set_user_config(conn: sqlite3.Connection, environment_id: int, config: Mapping[str, Any]) -> None:
    conn.execute("UPDATE environment SET user_config = ? WHERE id = ?",
                 (to_json(dict(config)), environment_id))


def forget_environment(conn: sqlite3.Connection, environment_id: int) -> int:
    """Remove an environment and everything scanned from it. Nothing on disk is touched.

    Dossiers left with no ledger anywhere are removed too; the user's overrides are kept (they
    are keyed by uid and never deleted by the library). Returns the number of dossiers removed.
    """
    ledgers = "SELECT id FROM ledger WHERE environment_id = :env"
    entries = f"SELECT id FROM entry WHERE ledger_id IN ({ledgers})"
    files = "SELECT id FROM file WHERE environment_id = :env"
    p = {"env": environment_id}
    conn.execute(f"DELETE FROM entry_file WHERE entry_id IN ({entries}) OR file_id IN ({files})", p)
    conn.execute(f"UPDATE entry SET source_entry_id = NULL WHERE source_entry_id IN ({entries})", p)
    conn.execute(f"DELETE FROM entry WHERE id IN ({entries})", p)
    conn.execute("DELETE FROM ledger WHERE environment_id = :env", p)
    conn.execute(f"UPDATE dossier_dependency SET target_file_id = NULL, status = 'broken'"
                 f" WHERE target_file_id IN ({files})", p)
    conn.execute(f"UPDATE thumbnail SET source_file_id = NULL WHERE source_file_id IN ({files})", p)
    conn.execute("DELETE FROM file WHERE environment_id = :env", p)
    conn.execute("DELETE FROM container WHERE environment_id = :env", p)
    conn.execute("DELETE FROM scan WHERE environment_id = :env", p)
    conn.execute("DELETE FROM lexicon_generated WHERE root_id IN"
                 " (SELECT id FROM environment_root WHERE environment_id = :env)", p)
    conn.execute("DELETE FROM environment_root WHERE environment_id = :env", p)
    conn.execute("DELETE FROM environment WHERE id = :env", p)

    orphans = [r[0] for r in conn.execute(
        "SELECT id FROM dossier d WHERE NOT EXISTS (SELECT 1 FROM ledger l WHERE l.dossier_id = d.id)")]
    for batch in _chunks(orphans):
        marks = ",".join("?" * len(batch))
        conn.execute(f"UPDATE dossier SET parent_id = NULL WHERE parent_id IN ({marks})", batch)
        conn.execute(f"UPDATE dossier_dependency SET target_dossier_id = NULL"
                     f" WHERE target_dossier_id IN ({marks})", batch)
        for table in ("dossier_field", "dossier_tag", "dossier_token", "dossier_dependency", "thumbnail"):
            conn.execute(f"DELETE FROM {table} WHERE dossier_id IN ({marks})", batch)
        conn.execute(f"DELETE FROM dossier_fts WHERE rowid IN ({marks})", batch)
        conn.execute(f"DELETE FROM dossier WHERE id IN ({marks})", batch)
    return len(orphans)


# Scans --------------------------------------------------------------------------------------------


def start_scan(conn: sqlite3.Connection, environment_id: int, root_id: int) -> int:
    cur = conn.execute(
        "INSERT INTO scan (environment_id, root_id, started_at) VALUES (?, ?, ?)",
        (environment_id, root_id, now()),
    )
    return cur.lastrowid


def finish_scan(
    conn: sqlite3.Connection, scan_id: int, *, phase: int, seen: int, new: int, changed: int,
    gone: int, unattached: int = 0,
) -> None:
    conn.execute(
        "UPDATE scan SET finished_at = ?, phase_reached = ?, files_seen = ?, files_new = ?,"
        " files_changed = ?, files_gone = ?, unattached_files = ? WHERE id = ?",
        (now(), phase, seen, new, changed, gone, unattached, scan_id),
    )


def mark_scan_phase(conn: sqlite3.Connection, environment_id: int, phase: int) -> None:
    conn.execute(
        "UPDATE scan SET phase_reached = MAX(phase_reached, ?) WHERE id IN"
        " (SELECT MAX(id) FROM scan WHERE environment_id = ? GROUP BY root_id)",
        (phase, environment_id),
    )


# Files --------------------------------------------------------------------------------------------


def load_files(conn: sqlite3.Connection, root_id: int) -> dict[str, sqlite3.Row]:
    rows = conn.execute("SELECT * FROM file WHERE root_id = ?", (root_id,))
    return {row["rel_key"]: row for row in rows}


def insert_file(
    conn: sqlite3.Connection, *, environment_id: int, root_id: int, rel_path: str, rel_key: str,
    ext: str, size: int, mtime_ns: int, is_archive: bool, scan_id: int,
) -> int:
    cur = conn.execute(
        "INSERT INTO file (environment_id, root_id, rel_path, rel_key, ext, size, mtime_ns,"
        " is_archive, state, first_seen_scan, last_seen_scan)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'present', ?, ?)",
        (environment_id, root_id, rel_path, rel_key, ext, size, mtime_ns, int(is_archive),
         scan_id, scan_id),
    )
    return cur.lastrowid


def update_file_seen(
    conn: sqlite3.Connection, file_id: int, *, rel_path: str, size: int, mtime_ns: int,
    scan_id: int, changed: bool,
) -> None:
    # A changed file loses its hash; scan phase 3 recomputes it.
    conn.execute(
        "UPDATE file SET rel_path = ?, size = ?, mtime_ns = ?, state = 'present',"
        " last_seen_scan = ?, hash = CASE WHEN ? THEN NULL ELSE hash END WHERE id = ?",
        (rel_path, size, mtime_ns, scan_id, int(changed), file_id),
    )


def set_file_states(conn: sqlite3.Connection, file_ids: Iterable[int], state: str) -> None:
    conn.executemany("UPDATE file SET state = ? WHERE id = ?", ((state, i) for i in file_ids))


def set_file_containers(
    conn: sqlite3.Connection, pairs: Iterable[tuple[int | None, int]]
) -> None:
    conn.executemany("UPDATE file SET container_id = ? WHERE id = ?", pairs)


def files_to_hash(conn: sqlite3.Connection, environment_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT f.id, f.rel_path, f.size, r.path AS root_path FROM file f"
        " JOIN environment_root r ON r.id = f.root_id"
        " WHERE f.environment_id = ? AND f.state = 'present' AND f.hash IS NULL"
        " AND r.status = 'online' ORDER BY f.id", (environment_id,)).fetchall()


def set_file_hash(conn: sqlite3.Connection, file_id: int, digest: str) -> None:
    conn.execute("UPDATE file SET hash = ? WHERE id = ?", (digest, file_id))


# Containers ---------------------------------------------------------------------------------------


def upsert_container(
    conn: sqlite3.Connection, environment_id: int, root_id: int, *, rel_path: str, rel_key: str,
    kind: str, name: str, meta: Mapping[str, Any],
) -> int:
    conn.execute(
        "INSERT INTO container (environment_id, root_id, kind, name, rel_path, rel_key, scanned_meta)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)"
        " ON CONFLICT (root_id, rel_key) DO UPDATE SET kind = excluded.kind,"
        " name = excluded.name, rel_path = excluded.rel_path,"
        " scanned_meta = excluded.scanned_meta",
        (environment_id, root_id, kind, name, rel_path, rel_key, to_json(dict(meta))),
    )
    return conn.execute(
        "SELECT id FROM container WHERE root_id = ? AND rel_key = ?", (root_id, rel_key),
    ).fetchone()["id"]


# Dossiers, ledgers and entries --------------------------------------------------------------------


def find_entry(
    conn: sqlite3.Connection, container_id: int, identity_key: str
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT e.id, e.status, e.ledger_id, e.moved_from, l.dossier_id FROM entry e"
        " JOIN ledger l ON l.id = e.ledger_id"
        " WHERE e.container_id = ? AND e.identity_key = ?",
        (container_id, identity_key),
    ).fetchone()


def get_dossier(conn: sqlite3.Connection, dossier_id: int) -> sqlite3.Row:
    return conn.execute("SELECT * FROM dossier WHERE id = ?", (dossier_id,)).fetchone()


def find_product_by_key(conn: sqlite3.Connection, environment_id: int, product_key: str) -> int | None:
    """A product dossier in this environment already claiming ``product_key`` (e.g. a Daz SKU)."""
    row = conn.execute(
        "SELECT f.dossier_id FROM dossier_field f JOIN ledger l ON l.dossier_id = f.dossier_id"
        " WHERE f.field = 'product_key' AND f.value = ? AND l.environment_id = ?"
        " ORDER BY f.dossier_id LIMIT 1", (to_json(product_key), environment_id)).fetchone()
    return row[0] if row else None


def create_dossier(
    conn: sqlite3.Connection, *, type_id: str, name: str, parent_id: int | None,
    confidence: float, signals: list[str], uid: str | None = None,
) -> int:
    stamp = now()
    cur = conn.execute(
        "INSERT INTO dossier (uid, type_id, name, parent_id, confidence, confidence_base, signals,"
        " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (uid or new_uid(), type_id, name, parent_id, confidence, confidence, to_json(signals), stamp, stamp),
    )
    return cur.lastrowid


def update_dossier(
    conn: sqlite3.Connection, dossier_id: int, *, type_id: str, name: str,
    parent_id: int | None, confidence: float, signals: list[str],
) -> None:
    """Refresh the scanned layer of a dossier. Overrides live elsewhere and are untouched.

    ``confidence`` is the identification's own; the classification pass adds evidence on top.
    """
    conn.execute(
        "UPDATE dossier SET type_id = ?, name = ?, parent_id = ?, confidence = ?, confidence_base = ?,"
        " signals = ?, updated_at = ? WHERE id = ?",
        (type_id, name, parent_id, confidence, confidence, to_json(signals), now(), dossier_id),
    )


def set_dossier_type(conn: sqlite3.Connection, dossier_id: int, type_id: str) -> None:
    conn.execute("UPDATE dossier SET type_id = ?, updated_at = ? WHERE id = ?",
                 (type_id, now(), dossier_id))


def ensure_ledger(conn: sqlite3.Connection, dossier_id: int, environment_id: int) -> int:
    conn.execute(
        "INSERT OR IGNORE INTO ledger (dossier_id, environment_id) VALUES (?, ?)",
        (dossier_id, environment_id),
    )
    return conn.execute(
        "SELECT id FROM ledger WHERE dossier_id = ? AND environment_id = ?",
        (dossier_id, environment_id),
    ).fetchone()["id"]


def create_entry(
    conn: sqlite3.Connection, *, ledger_id: int, container_id: int, identity_key: str,
    status: str = "origin",
) -> int:
    cur = conn.execute(
        "INSERT INTO entry (ledger_id, container_id, identity_key, status, created_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (ledger_id, container_id, identity_key, status, now()),
    )
    return cur.lastrowid


def revive_entry(conn: sqlite3.Connection, entry_id: int, status: str) -> None:
    """A retired entry is back on disk."""
    conn.execute("UPDATE entry SET status = ?, retired_at = NULL WHERE id = ?", (status, entry_id))


def replace_entry_files(
    conn: sqlite3.Connection, entry_id: int, files: Iterable[tuple[int, str]]
) -> None:
    conn.execute("DELETE FROM entry_file WHERE entry_id = ?", (entry_id,))
    conn.executemany(
        "INSERT OR IGNORE INTO entry_file (entry_id, file_id, role) VALUES (?, ?, ?)",
        ((entry_id, file_id, role) for file_id, role in files),
    )


def live_entry_ids(conn: sqlite3.Connection, root_id: int) -> set[int]:
    rows = conn.execute(
        "SELECT e.id FROM entry e JOIN container c ON c.id = e.container_id"
        " WHERE c.root_id = ? AND e.status != 'retired'",
        (root_id,),
    )
    return {row["id"] for row in rows}


def retire_entries(conn: sqlite3.Connection, entry_ids: Iterable[int]) -> None:
    stamp = now()
    conn.executemany(
        "UPDATE entry SET status = 'retired', retired_at = ? WHERE id = ?",
        ((stamp, i) for i in entry_ids),
    )


def move_entry(conn: sqlite3.Connection, entry_id: int, ledger_id: int, status: str,
               moved_from: str | None = None) -> None:
    conn.execute("UPDATE entry SET ledger_id = ?, status = ?, moved_from = COALESCE(?, moved_from)"
                 " WHERE id = ?", (ledger_id, status, moved_from, entry_id))


def has_home_entry(conn: sqlite3.Connection, dossier_id: int) -> bool:
    """True if the dossier has an entry of its own (not one moved onto it by a merge or link)."""
    return conn.execute(
        "SELECT EXISTS (SELECT 1 FROM entry e JOIN ledger l ON l.id = e.ledger_id"
        " WHERE l.dossier_id = ? AND e.moved_from IS NULL)", (dossier_id,)).fetchone()[0] == 1


def delete_dossier(conn: sqlite3.Connection, dossier_id: int) -> None:
    """Remove a dossier the scanner made and nobody refers to (e.g. after a duplicate merge)."""
    for table in ("dossier_field", "dossier_tag", "dossier_token", "dossier_dependency", "thumbnail"):
        conn.execute(f"DELETE FROM {table} WHERE dossier_id = ?", (dossier_id,))
    conn.execute("UPDATE dossier_dependency SET target_dossier_id = NULL WHERE target_dossier_id = ?",
                 (dossier_id,))
    conn.execute("DELETE FROM ledger WHERE dossier_id = ? AND NOT EXISTS"
                 " (SELECT 1 FROM entry e WHERE e.ledger_id = ledger.id)", (dossier_id,))
    conn.execute("DELETE FROM dossier_fts WHERE rowid = ?", (dossier_id,))
    conn.execute("DELETE FROM dossier WHERE id = ?", (dossier_id,))


def has_user_work(conn: sqlite3.Connection, uid: str) -> bool:
    """True if the user has overridden or linked this dossier; it must not be merged away."""
    return conn.execute(
        "SELECT EXISTS (SELECT 1 FROM override_field WHERE dossier_uid = :u)"
        " OR EXISTS (SELECT 1 FROM override_tag WHERE dossier_uid = :u)"
        " OR EXISTS (SELECT 1 FROM override_link WHERE subject = :u OR target_uid = :u)",
        {"u": uid}).fetchone()[0] == 1


def replace_scanned_fields(
    conn: sqlite3.Connection, dossier_id: int, source: str, fields: Mapping[str, Any]
) -> None:
    """Replace the fields one source contributed; other sources (e.g. lookups) are kept."""
    conn.execute(
        "DELETE FROM dossier_field WHERE dossier_id = ? AND source = ?", (dossier_id, source)
    )
    stamp = now()
    conn.executemany(
        "INSERT INTO dossier_field (dossier_id, field, value, source, fetched_at)"
        " VALUES (?, ?, ?, ?, ?)",
        ((dossier_id, k, to_json(v), source, stamp) for k, v in fields.items() if v is not None),
    )


def replace_tokens(conn: sqlite3.Connection, dossier_id: int, tokens: list[str]) -> None:
    conn.execute("DELETE FROM dossier_token WHERE dossier_id = ?", (dossier_id,))
    conn.executemany(
        "INSERT INTO dossier_token (dossier_id, position, token) VALUES (?, ?, ?)",
        ((dossier_id, i, t) for i, t in enumerate(tokens)),
    )


def dossier_uid(conn: sqlite3.Connection, dossier_id: int) -> str:
    return conn.execute("SELECT uid FROM dossier WHERE id = ?", (dossier_id,)).fetchone()["uid"]


# Scan phase 3 output ------------------------------------------------------------------------------


def live_primaries(conn: sqlite3.Connection, environment_id: int) -> list[sqlite3.Row]:
    """Primary files of live entries on online roots, ordered by dossier then entry."""
    return conn.execute(
        "SELECT d.id AS dossier_id, d.uid, d.type_id, d.parent_id, e.id AS entry_id,"
        " e.container_id, f.id AS file_id, f.rel_path, f.rel_key, f.root_id, f.ext, f.size,"
        " f.hash, r.path AS root_path"
        " FROM entry e JOIN ledger l ON l.id = e.ledger_id JOIN dossier d ON d.id = l.dossier_id"
        " JOIN entry_file ef ON ef.entry_id = e.id AND ef.role = 'primary'"
        " JOIN file f ON f.id = ef.file_id JOIN environment_root r ON r.id = f.root_id"
        " WHERE l.environment_id = ? AND e.status != 'retired' AND f.state = 'present'"
        " AND r.status = 'online' ORDER BY d.id, e.id, f.id", (environment_id,)).fetchall()


def live_dossier_ids(conn: sqlite3.Connection, environment_id: int) -> list[int]:
    return [r[0] for r in conn.execute(
        "SELECT DISTINCT l.dossier_id FROM ledger l JOIN entry e ON e.ledger_id = l.id"
        " WHERE l.environment_id = ? AND e.status != 'retired' ORDER BY l.dossier_id",
        (environment_id,))]


def present_files(conn: sqlite3.Connection, environment_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT f.id, f.root_id, f.rel_path, f.rel_key, f.ext, f.hash, r.path AS root_path"
        " FROM file f JOIN environment_root r ON r.id = f.root_id"
        " WHERE f.environment_id = ? AND f.state = 'present'", (environment_id,)).fetchall()


def file_owners(conn: sqlite3.Connection, environment_id: int) -> dict[int, int]:
    """file id -> dossier id of a live entry holding it (a primary holder wins)."""
    owners: dict[int, int] = {}
    rows = conn.execute(
        "SELECT ef.file_id, l.dossier_id FROM entry_file ef JOIN entry e ON e.id = ef.entry_id"
        " JOIN ledger l ON l.id = e.ledger_id WHERE l.environment_id = ? AND e.status != 'retired'"
        " ORDER BY ef.role = 'primary' DESC, e.id", (environment_id,))
    for file_id, dossier_id in rows:
        owners.setdefault(file_id, dossier_id)
    return owners


def duplicate_groups(conn: sqlite3.Connection, min_size: int) -> list[sqlite3.Row]:
    """Live non-product entries whose single primary file's hash another dossier shares."""
    return conn.execute(
        "WITH prim AS (SELECT e.id AS entry_id, e.status, l.dossier_id, l.environment_id, f.hash"
        "  FROM entry e JOIN ledger l ON l.id = e.ledger_id JOIN dossier d ON d.id = l.dossier_id"
        "  JOIN entry_file ef ON ef.entry_id = e.id AND ef.role = 'primary'"
        "  JOIN file f ON f.id = ef.file_id"
        "  WHERE e.status != 'retired' AND d.type_id != 'product' AND f.hash IS NOT NULL"
        "  AND f.size >= ? AND (SELECT count(*) FROM entry_file x WHERE x.entry_id = e.id"
        "  AND x.role = 'primary') = 1)"
        " SELECT * FROM prim WHERE hash IN (SELECT hash FROM prim GROUP BY hash"
        "  HAVING count(DISTINCT dossier_id) > 1) ORDER BY hash, dossier_id, entry_id",
        (min_size,)).fetchall()


def entries_of(conn: sqlite3.Connection, dossier_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT e.*, l.environment_id FROM entry e JOIN ledger l ON l.id = e.ledger_id"
        " WHERE l.dossier_id = ?", (dossier_id,)).fetchall()


def has_children(conn: sqlite3.Connection, dossier_id: int) -> bool:
    return conn.execute("SELECT EXISTS (SELECT 1 FROM dossier WHERE parent_id = ?)",
                        (dossier_id,)).fetchone()[0] == 1


def scanned_field(conn: sqlite3.Connection, dossier_id: int, field: str,
                  source: str | None = None) -> Any:
    sql = "SELECT value FROM dossier_field WHERE dossier_id = ? AND field = ?"
    params: tuple = (dossier_id, field)
    if source is not None:
        sql += " AND source = ?"
        params += (source,)
    row = conn.execute(sql + " ORDER BY fetched_at DESC LIMIT 1", params).fetchone()
    return json.loads(row[0]) if row else None


def child_thumbnail(conn: sqlite3.Connection, dossier_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT t.* FROM thumbnail t JOIN dossier d ON d.id = t.dossier_id"
        " WHERE d.parent_id = ? AND t.source_kind != 'child' ORDER BY d.name, d.id LIMIT 1",
        (dossier_id,)).fetchone()



def replace_dependencies(conn: sqlite3.Connection, dossier_id: int,
                         deps: Iterable[tuple[str, int | None, int | None]]) -> None:
    """``deps``: (reference, target file id or None, target dossier id or None)."""
    conn.execute("DELETE FROM dossier_dependency WHERE dossier_id = ?", (dossier_id,))
    conn.executemany(
        "INSERT OR IGNORE INTO dossier_dependency (dossier_id, reference, target_file_id,"
        " target_dossier_id, status) VALUES (?, ?, ?, ?, ?)",
        ((dossier_id, ref, fid, did, "ok" if fid is not None else "broken")
         for ref, fid, did in deps))


def thumbnail_row(conn: sqlite3.Connection, dossier_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM thumbnail WHERE dossier_id = ?", (dossier_id,)).fetchone()


def set_thumbnail(conn: sqlite3.Connection, dossier_id: int, *, rel_path: str, source_kind: str,
                  source_file_id: int | None, source_hash: str | None) -> None:
    conn.execute(
        "INSERT INTO thumbnail (dossier_id, rel_path, source_kind, source_file_id, source_hash,"
        " made_at) VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT (dossier_id) DO UPDATE SET"
        " rel_path = excluded.rel_path, source_kind = excluded.source_kind,"
        " source_file_id = excluded.source_file_id, source_hash = excluded.source_hash,"
        " made_at = excluded.made_at",
        (dossier_id, rel_path, source_kind, source_file_id, source_hash, now()))


# Generated lexicon words --------------------------------------------------------------------------


def generated_words(conn: sqlite3.Connection) -> dict[str, list[tuple[str, str]]]:
    """(value, word) pairs scans found, by lexicon id, for ``lexicons.with_generated``."""
    words: dict[str, list[tuple[str, str]]] = {}
    for row in conn.execute("SELECT DISTINCT lexicon_id, value, word FROM lexicon_generated"
                            " ORDER BY lexicon_id, value, word"):
        words.setdefault(row[0], []).append((row[1], row[2]))
    return words


def replace_generated_words(conn: sqlite3.Connection, root_id: int,
                            words: Mapping[str, Iterable[tuple[str, str]]]) -> None:
    conn.execute("DELETE FROM lexicon_generated WHERE root_id = ?", (root_id,))
    conn.executemany("INSERT OR IGNORE INTO lexicon_generated (lexicon_id, root_id, value, word) VALUES (?, ?, ?, ?)",
                     [(lexicon_id, root_id, value, word) for lexicon_id, pairs in words.items()
                      for value, word in pairs])


# Search index -------------------------------------------------------------------------------------


# dossier_tag_effective, split into its halves for per-row use: SQLite cannot push a correlated
# filter into the view's UNION, so it would build the whole view once per outer query.
# Expects ``t`` (dossier_tag) and ``d`` (a dossier row with uid) in scope.
_TAG_REMOVED = ("EXISTS (SELECT 1 FROM override_tag r WHERE r.dossier_uid = d.uid AND r.tag = t.tag"
                " AND r.action = 'remove')")


def has_tag_sql() -> str:
    """A condition true when dossier ``d`` effectively has the tag given as three ``?`` (any case).

    It starts from the tag (index ``dossier_tag_lower``), not from each dossier: tags are selective.
    """
    return ("((d.id IN (SELECT t.dossier_id FROM dossier_tag t WHERE lower(t.tag) = lower(?))"
            " AND NOT EXISTS (SELECT 1 FROM override_tag r WHERE r.dossier_uid = d.uid"
            " AND lower(r.tag) = lower(?) AND r.action = 'remove'))"
            " OR d.uid IN (SELECT o.dossier_uid FROM override_tag o WHERE o.action = 'add'"
            " AND lower(o.tag) = lower(?)))")


def index_dossiers(conn: sqlite3.Connection, dossier_ids: Iterable[int]) -> None:
    """Refresh the full-text index for some dossiers from their effective values."""
    for batch in _chunks(dossier_ids):
        marks = ",".join("?" * len(batch))
        conn.execute(f"DELETE FROM dossier_fts WHERE rowid IN ({marks})", batch)
        rows = conn.execute(
            f"SELECT d.id, d.name,"
            f" (SELECT group_concat(t.token, ' ') FROM dossier_token t WHERE t.dossier_id = d.id) AS tokens,"
            f" trim(coalesce((SELECT group_concat(t.tag, ' ') FROM dossier_tag t WHERE t.dossier_id = d.id"
            f"   AND NOT {_TAG_REMOVED}), '') || ' ' ||"
            f"  coalesce((SELECT group_concat(o.tag, ' ') FROM override_tag o WHERE o.dossier_uid = d.uid"
            f"   AND o.action = 'add'), '')) AS tags,"
            f" (SELECT group_concat(DISTINCT c.name) FROM ledger l JOIN entry e ON e.ledger_id = l.id"
            f"   JOIN container c ON c.id = e.container_id WHERE l.dossier_id = d.id) AS places"
            f" FROM dossier_effective d WHERE d.id IN ({marks})", batch).fetchall()
        conn.executemany(
            "INSERT INTO dossier_fts (rowid, name, tokens, tags, places) VALUES (?, ?, ?, ?, ?)",
            ((r["id"], r["name"], " ".join(filter(None, [r["tokens"], " ".join(tokenize(r["name"]))])),
              r["tags"] or "", (r["places"] or "").replace(",", " ")) for r in rows))


def _index_uid(conn: sqlite3.Connection, uid: str) -> None:
    row = conn.execute("SELECT id FROM dossier WHERE uid = ?", (uid,)).fetchone()
    if row:
        index_dossiers(conn, [row[0]])


# Override layer -----------------------------------------------------------------------------------


def log_curation(conn: sqlite3.Connection, action: str, payload: Mapping[str, Any]) -> None:
    conn.execute(
        "INSERT INTO curation_log (at, action, payload) VALUES (?, ?, ?)",
        (now(), action, to_json(dict(payload))),
    )


def set_override_field(conn: sqlite3.Connection, uid: str, field: str, value: Any) -> None:
    conn.execute(
        "INSERT INTO override_field (dossier_uid, field, value, set_at) VALUES (?, ?, ?, ?)"
        " ON CONFLICT (dossier_uid, field) DO UPDATE SET value = excluded.value,"
        " set_at = excluded.set_at",
        (uid, field, to_json(value), now()),
    )
    log_curation(conn, "set_field", {"dossier": uid, "field": field, "value": value})
    _index_uid(conn, uid)


def revert_override_field(conn: sqlite3.Connection, uid: str, field: str) -> None:
    """'Revert to scanned': drop the user's value for one field."""
    conn.execute(
        "DELETE FROM override_field WHERE dossier_uid = ? AND field = ?", (uid, field)
    )
    log_curation(conn, "revert_field", {"dossier": uid, "field": field})
    _index_uid(conn, uid)


def set_override_tag(conn: sqlite3.Connection, uid: str, tag: str, action: str) -> None:
    conn.execute(
        "INSERT INTO override_tag (dossier_uid, tag, action, set_at) VALUES (?, ?, ?, ?)"
        " ON CONFLICT (dossier_uid, tag) DO UPDATE SET action = excluded.action,"
        " set_at = excluded.set_at",
        (uid, tag, action, now()),
    )
    log_curation(conn, f"{action}_tag", {"dossier": uid, "tag": tag})
    _index_uid(conn, uid)


def set_override_parent(conn: sqlite3.Connection, uid: str, parent_uid: str | None) -> None:
    conn.execute(
        "INSERT INTO override_link (kind, subject, target_uid, set_at)"
        " VALUES ('dossier_to_parent', ?, ?, ?)"
        " ON CONFLICT (kind, subject) DO UPDATE SET target_uid = excluded.target_uid,"
        " set_at = excluded.set_at",
        (uid, parent_uid, now()),
    )
    log_curation(conn, "set_parent", {"dossier": uid, "parent": parent_uid})


def effective_dossier(conn: sqlite3.Connection, uid: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM dossier_effective WHERE uid = ?", (uid,)).fetchone()


def effective_fields(conn: sqlite3.Connection, uid: str) -> dict[str, Any]:
    """Scanned fields (most recent source wins) overlaid with the user's overrides."""
    return {k: v for k, (v, _) in field_sources(conn, uid).items()}


def field_sources(conn: sqlite3.Connection, uid: str) -> dict[str, tuple[Any, str]]:
    """field -> (effective value, source), where source is "user" for overrides."""
    fields: dict[str, tuple[Any, str]] = {}
    rows = conn.execute(
        "SELECT f.field, f.value, f.source FROM dossier_field f JOIN dossier d ON d.id = f.dossier_id"
        " WHERE d.uid = ? ORDER BY f.fetched_at, f.source",
        (uid,),
    )
    for row in rows:
        fields[row["field"]] = (json.loads(row["value"]), row["source"])
    for row in conn.execute(
        "SELECT field, value FROM override_field WHERE dossier_uid = ?", (uid,)
    ):
        fields[row["field"]] = (json.loads(row["value"]), "user")
    return fields


def effective_tags(conn: sqlite3.Connection, uid: str) -> set[str]:
    rows = conn.execute("SELECT tag FROM dossier_tag_effective WHERE dossier_uid = ?", (uid,))
    return {row["tag"] for row in rows}
