"""All SQL for the library database lives here."""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any


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


# Environments -------------------------------------------------------------------------------


def list_environments(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM environment ORDER BY id").fetchall()


def upsert_environment(
    conn: sqlite3.Connection,
    *,
    type_id: str,
    name: str,
    root_path: str,
    root_key: str,
    variant: str | None,
    confidence: float,
    signals: list[str],
) -> sqlite3.Row:
    """Register an environment, or refresh detection results for one already registered.

    An existing environment keeps its type: the user's configuration wins over re-detection.
    """
    row = conn.execute("SELECT id FROM environment WHERE root_key = ?", (root_key,)).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO environment (uid, type_id, name, root_path, root_key, variant,"
            " detection_confidence, detection_signals, added_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (new_uid(), type_id, name, root_path, root_key, variant, confidence,
             to_json(signals), now()),
        )
    else:
        conn.execute(
            "UPDATE environment SET root_path = ?, variant = ?, detection_confidence = ?,"
            " detection_signals = ?, status = 'online' WHERE id = ?",
            (root_path, variant, confidence, to_json(signals), row["id"]),
        )
    return conn.execute("SELECT * FROM environment WHERE root_key = ?", (root_key,)).fetchone()


def finish_environment_scan(
    conn: sqlite3.Connection, environment_id: int, layer_config: Mapping[str, Any]
) -> None:
    conn.execute(
        "UPDATE environment SET layer_config = ?, last_scanned_at = ? WHERE id = ?",
        (to_json(dict(layer_config)), now(), environment_id),
    )


# Scans ------------------------------------------------------------------------------------------


def start_scan(conn: sqlite3.Connection, environment_id: int) -> int:
    cur = conn.execute(
        "INSERT INTO scan (environment_id, started_at) VALUES (?, ?)", (environment_id, now())
    )
    return cur.lastrowid


def finish_scan(
    conn: sqlite3.Connection, scan_id: int, *, phase: int, seen: int, new: int, changed: int,
    gone: int,
) -> None:
    conn.execute(
        "UPDATE scan SET finished_at = ?, phase_reached = ?, files_seen = ?, files_new = ?,"
        " files_changed = ?, files_gone = ? WHERE id = ?",
        (now(), phase, seen, new, changed, gone, scan_id),
    )


# Files ------------------------------------------------------------------------------------------


def load_files(conn: sqlite3.Connection, environment_id: int) -> dict[str, sqlite3.Row]:
    rows = conn.execute("SELECT * FROM file WHERE environment_id = ?", (environment_id,))
    return {row["rel_key"]: row for row in rows}


def insert_file(
    conn: sqlite3.Connection, *, environment_id: int, rel_path: str, rel_key: str, ext: str,
    size: int, mtime_ns: int, is_archive: bool, scan_id: int,
) -> int:
    cur = conn.execute(
        "INSERT INTO file (environment_id, rel_path, rel_key, ext, size, mtime_ns, is_archive,"
        " state, first_seen_scan, last_seen_scan) VALUES (?, ?, ?, ?, ?, ?, ?, 'present', ?, ?)",
        (environment_id, rel_path, rel_key, ext, size, mtime_ns, int(is_archive), scan_id,
         scan_id),
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


# Containers -------------------------------------------------------------------------------------


def upsert_container(
    conn: sqlite3.Connection, environment_id: int, *, rel_path: str, rel_key: str, kind: str,
    name: str, meta: Mapping[str, Any],
) -> int:
    conn.execute(
        "INSERT INTO container (environment_id, kind, name, rel_path, rel_key, scanned_meta)"
        " VALUES (?, ?, ?, ?, ?, ?)"
        " ON CONFLICT (environment_id, rel_key) DO UPDATE SET kind = excluded.kind,"
        " name = excluded.name, rel_path = excluded.rel_path,"
        " scanned_meta = excluded.scanned_meta",
        (environment_id, kind, name, rel_path, rel_key, to_json(dict(meta))),
    )
    return conn.execute(
        "SELECT id FROM container WHERE environment_id = ? AND rel_key = ?",
        (environment_id, rel_key),
    ).fetchone()["id"]


# Dossiers, ledgers and entries ------------------------------------------------------------------


def find_entry(
    conn: sqlite3.Connection, container_id: int, identity_key: str
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT e.id, e.status, l.dossier_id FROM entry e JOIN ledger l ON l.id = e.ledger_id"
        " WHERE e.container_id = ? AND e.identity_key = ?",
        (container_id, identity_key),
    ).fetchone()


def create_dossier(
    conn: sqlite3.Connection, *, type_id: str, name: str, parent_id: int | None,
    confidence: float, signals: list[str],
) -> int:
    stamp = now()
    cur = conn.execute(
        "INSERT INTO dossier (uid, type_id, name, parent_id, confidence, signals, created_at,"
        " updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (new_uid(), type_id, name, parent_id, confidence, to_json(signals), stamp, stamp),
    )
    return cur.lastrowid


def update_dossier(
    conn: sqlite3.Connection, dossier_id: int, *, type_id: str, name: str,
    parent_id: int | None, confidence: float, signals: list[str],
) -> None:
    """Refresh the scanned layer of a dossier. Overrides live elsewhere and are untouched."""
    conn.execute(
        "UPDATE dossier SET type_id = ?, name = ?, parent_id = ?, confidence = ?, signals = ?,"
        " updated_at = ? WHERE id = ?",
        (type_id, name, parent_id, confidence, to_json(signals), now(), dossier_id),
    )


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


def revive_entry(conn: sqlite3.Connection, entry_id: int) -> None:
    """A retired entry is back on disk."""
    conn.execute(
        "UPDATE entry SET status = CASE WHEN source_entry_id IS NULL THEN 'origin'"
        " ELSE 'unknown' END, retired_at = NULL WHERE id = ?",
        (entry_id,),
    )


def replace_entry_files(
    conn: sqlite3.Connection, entry_id: int, files: Iterable[tuple[int, str]]
) -> None:
    conn.execute("DELETE FROM entry_file WHERE entry_id = ?", (entry_id,))
    conn.executemany(
        "INSERT OR IGNORE INTO entry_file (entry_id, file_id, role) VALUES (?, ?, ?)",
        ((entry_id, file_id, role) for file_id, role in files),
    )


def live_entry_ids(conn: sqlite3.Connection, environment_id: int) -> set[int]:
    rows = conn.execute(
        "SELECT e.id FROM entry e JOIN ledger l ON l.id = e.ledger_id"
        " WHERE l.environment_id = ? AND e.status != 'retired'",
        (environment_id,),
    )
    return {row["id"] for row in rows}


def retire_entries(conn: sqlite3.Connection, entry_ids: Iterable[int]) -> None:
    stamp = now()
    conn.executemany(
        "UPDATE entry SET status = 'retired', retired_at = ? WHERE id = ?",
        ((stamp, i) for i in entry_ids),
    )


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


# Override layer ---------------------------------------------------------------------------------


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


def revert_override_field(conn: sqlite3.Connection, uid: str, field: str) -> None:
    """'Revert to scanned': drop the user's value for one field."""
    conn.execute(
        "DELETE FROM override_field WHERE dossier_uid = ? AND field = ?", (uid, field)
    )
    log_curation(conn, "revert_field", {"dossier": uid, "field": field})


def set_override_tag(conn: sqlite3.Connection, uid: str, tag: str, action: str) -> None:
    conn.execute(
        "INSERT INTO override_tag (dossier_uid, tag, action, set_at) VALUES (?, ?, ?, ?)"
        " ON CONFLICT (dossier_uid, tag) DO UPDATE SET action = excluded.action,"
        " set_at = excluded.set_at",
        (uid, tag, action, now()),
    )
    log_curation(conn, f"{action}_tag", {"dossier": uid, "tag": tag})


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
    fields: dict[str, Any] = {}
    rows = conn.execute(
        "SELECT f.field, f.value FROM dossier_field f JOIN dossier d ON d.id = f.dossier_id"
        " WHERE d.uid = ? ORDER BY f.fetched_at",
        (uid,),
    )
    for row in rows:
        fields[row["field"]] = json.loads(row["value"])
    for row in conn.execute(
        "SELECT field, value FROM override_field WHERE dossier_uid = ?", (uid,)
    ):
        fields[row["field"]] = json.loads(row["value"])
    return fields


def effective_tags(conn: sqlite3.Connection, uid: str) -> set[str]:
    rows = conn.execute("SELECT tag FROM dossier_tag_effective WHERE dossier_uid = ?", (uid,))
    return {row["tag"] for row in rows}
