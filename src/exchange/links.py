"""Files the user linked onto dossiers (textures onto a mesh, stray files onto a product).

Links live in the override layer (``override_link`` kind ``file_to_dossier``), keyed by
``root:<root id>:<file rel_key>``, so they survive rescans. Applying them puts each linked file in
the target dossier's entry in the file's container (role ``linked``), creating a link entry when
the dossier has none there.
"""

from __future__ import annotations

import sqlite3

from exchange.db import repository as repo


def link_subject(root_id: int, rel_key: str) -> str:
    return f"root:{root_id}:{rel_key}"


def linked_keys(conn: sqlite3.Connection, root_id: int) -> dict[str, tuple[str, str | None]]:
    """rel_key -> (target dossier uid, role) for the files of one root that the user linked."""
    prefix = f"root:{root_id}:"
    rows = conn.execute(
        "SELECT subject, target_uid, role FROM override_link WHERE kind = 'file_to_dossier'"
        " AND target_uid IS NOT NULL AND substr(subject, 1, ?) = ?", (len(prefix), prefix))
    return {r["subject"][len(prefix):]: (r["target_uid"], r["role"]) for r in rows}


def apply_file_links(conn: sqlite3.Connection, root_id: int) -> set[int]:
    """Make the database match the links for one root; returns the entries holding linked files."""
    root = conn.execute("SELECT environment_id FROM environment_root WHERE id = ?", (root_id,)).fetchone()
    if root is None:
        return set()
    environment_id = root[0]
    conn.execute("DELETE FROM entry_file WHERE role = 'linked' AND file_id IN"
                 " (SELECT id FROM file WHERE root_id = ?)", (root_id,))
    touched: set[int] = set()
    for rel_key, (target_uid, _role) in linked_keys(conn, root_id).items():
        f = conn.execute("SELECT id, container_id FROM file WHERE root_id = ? AND rel_key = ?"
                         " AND state = 'present'", (root_id, rel_key)).fetchone()
        target = conn.execute("SELECT id FROM dossier WHERE uid = ?", (target_uid,)).fetchone()
        if f is None or target is None or f["container_id"] is None:
            continue
        home = conn.execute(
            "SELECT e.id FROM entry e JOIN ledger l ON l.id = e.ledger_id WHERE l.dossier_id = ?"
            " AND e.container_id = ? AND e.status != 'retired' ORDER BY e.id LIMIT 1",
            (target[0], f["container_id"])).fetchone()
        if home is not None:
            entry_id = home[0]
        else:
            key = f"link:{target_uid}"
            existing = repo.find_entry(conn, f["container_id"], key)
            if existing is not None and existing["dossier_id"] == target[0]:
                entry_id = existing["id"]
                if existing["status"] == "retired":
                    repo.revive_entry(conn, entry_id, "origin")
            else:
                ledger_id = repo.ensure_ledger(conn, target[0], environment_id)
                entry_id = repo.create_entry(conn, ledger_id=ledger_id, container_id=f["container_id"],
                                             identity_key=key)
                conn.execute("UPDATE entry SET moved_from = 'link' WHERE id = ?", (entry_id,))
        conn.execute("INSERT OR IGNORE INTO entry_file (entry_id, file_id, role) VALUES (?, ?, 'linked')",
                     (entry_id, f["id"]))
        touched.add(entry_id)
    # Link entries left without files (the user unlinked them) go away; they were the user's own.
    stale = [r[0] for r in conn.execute(
        "SELECT e.id FROM entry e JOIN container c ON c.id = e.container_id WHERE c.root_id = ?"
        " AND e.identity_key LIKE 'link:%' AND NOT EXISTS (SELECT 1 FROM entry_file ef WHERE ef.entry_id = e.id)",
        (root_id,))]
    for entry_id in stale:
        conn.execute("DELETE FROM entry WHERE id = ?", (entry_id,))
    conn.execute("DELETE FROM ledger WHERE NOT EXISTS (SELECT 1 FROM entry e WHERE e.ledger_id = ledger.id)"
                 " AND environment_id = ?", (environment_id,))
    return touched
