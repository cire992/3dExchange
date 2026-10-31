"""What's new: dossiers first seen since a marker the user moves.

The marker is the highest ``dossier.id`` at the end of the library's first scan, kept in
``library_setting``; "Mark all seen" moves it to the highest id now. A dossier is new when its
id is above the marker. SQLite reuses the ids above the highest one left, so deleting dossiers
brings the marker down with them (``after_deleting``).
"""

from __future__ import annotations

import json
import sqlite3

MARKER = "new_marker"


def marker(conn: sqlite3.Connection) -> int | None:
    row = conn.execute("SELECT value FROM library_setting WHERE key = ?", (MARKER,)).fetchone()
    return json.loads(row[0]) if row else None


def _highest(conn: sqlite3.Connection) -> int | None:
    return conn.execute("SELECT max(id) FROM dossier").fetchone()[0]


def _set(conn: sqlite3.Connection, value: int) -> None:
    conn.execute(
        "INSERT INTO library_setting (key, value) VALUES (?, ?)"
        " ON CONFLICT (key) DO UPDATE SET value = excluded.value", (MARKER, json.dumps(value)))


def start_marker(conn: sqlite3.Connection) -> None:
    """Set the marker at the highest dossier id, only when there is none and there are dossiers."""
    highest = _highest(conn)
    if highest is not None and marker(conn) is None:
        _set(conn, highest)


def mark_seen(conn: sqlite3.Connection) -> None:
    """Move an existing marker to the highest dossier id; with no marker (or no dossiers), nothing."""
    highest = _highest(conn)
    if highest is not None and marker(conn) is not None:
        _set(conn, highest)


def after_deleting(conn: sqlite3.Connection) -> None:
    """Bring the marker down to the highest id left, or forget it with the last dossier: the next
    scan of an empty library is a first scan again."""
    current = marker(conn)
    if current is None:
        return
    highest = _highest(conn)
    if highest is None:
        conn.execute("DELETE FROM library_setting WHERE key = ?", (MARKER,))
    elif highest < current:
        _set(conn, highest)
