"""The Unidentified desk's view of files no asset holds yet ("unattached"), folder by folder.

A big library has millions of them (1.5M in the real Daz library), so they are counted one folder
level at a time, using the (root, rel_key) index: a folder's files are the rel_key range
``prefix/`` to ``prefix0`` ("0" sorts right after "/").
"""

from __future__ import annotations

import sqlite3

from exchange.paths import fold

# A file (aliased f) no live entry holds.
UNATTACHED = ("f.state = 'present' AND NOT EXISTS (SELECT 1 FROM entry_file ef JOIN entry e ON e.id = ef.entry_id"
              " AND e.status != 'retired' WHERE ef.file_id = f.id)")


def key_range(folder_key: str) -> tuple[str, str]:
    """The rel_key range of everything under a folder (folded, no trailing slash; "" is the root)."""
    if not folder_key:
        return "", "\U0010ffff"
    return folder_key + "/", folder_key + "0"


def unattached_roots(conn: sqlite3.Connection) -> list[dict]:
    """Online roots with their environment, for the desk's top level (counts come per folder)."""
    rows = conn.execute(
        "SELECT r.id, r.path, r.environment_id, v.name AS environment FROM environment_root r"
        " JOIN environment v ON v.id = r.environment_id WHERE r.status = 'online' ORDER BY v.name, r.path")
    return [dict(r) for r in rows]


def unattached_folders(conn: sqlite3.Connection, root_id: int, folder: str = "") -> dict:
    """One level of a folder: its subfolders with their unattached-file counts (all levels below),
    and how many unattached files sit directly in it.

    ``folder`` is root-relative with "/" (any case). Subfolders come back as dicts with ``name``
    (as on disk), ``path`` (root-relative) and ``count``, largest first.
    """
    key = fold(folder.strip("/"))
    low, high = key_range(key)
    start = len(low) + 1  # 1-based position of the next segment
    depth = key.count("/") + 1 if key else 0
    rows = conn.execute(
        "SELECT CASE WHEN instr(rest, '/') THEN substr(rest, 1, instr(rest, '/') - 1) ELSE '' END AS k,"
        " count(*), max(rel_path) FROM (SELECT substr(f.rel_key, ?) AS rest, f.rel_path FROM file f"
        f" WHERE f.root_id = ? AND f.rel_key >= ? AND f.rel_key < ? AND {UNATTACHED})"
        " GROUP BY k ORDER BY 2 DESC, k", (start, root_id, low, high)).fetchall()
    folders, direct = [], 0
    for k, count, sample in rows:
        if not k:  # no further "/": a file directly in this folder
            direct += count
            continue
        parts = sample.split("/")
        folders.append({"name": parts[depth], "path": "/".join(parts[: depth + 1]), "count": count})
    return {"folders": folders, "files": direct, "total": direct + sum(f["count"] for f in folders)}


def unattached_files(conn: sqlite3.Connection, root_id: int, folder: str = "",
                     limit: int | None = None) -> list[dict]:
    """Unattached files under a folder (all levels), as dicts with id, rel_path, rel_key, size."""
    low, high = key_range(fold(folder.strip("/")))
    sql = (f"SELECT f.id, f.rel_path, f.rel_key, f.size FROM file f WHERE f.root_id = ? AND f.rel_key >= ?"
           f" AND f.rel_key < ? AND {UNATTACHED} ORDER BY f.rel_key")
    params: list = [root_id, low, high]
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    return [dict(r) for r in conn.execute(sql, params)]
