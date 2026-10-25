"""Files the user linked onto dossiers (textures onto a mesh, stray files onto a product).

Links live in the override layer (``override_link`` kind ``file_to_dossier``), keyed by
``root:<root id>:<file rel_key>``, so they survive rescans. Applying them puts each linked file in
the target dossier's entry in the file's container (role ``linked``), creating a link entry when
the dossier has none there.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable

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


def apply_file_links(conn: sqlite3.Connection, root_id: int, rel_keys: Iterable[str] | None = None) -> set[int]:
    """Make the database match the links for one root, or only for some of its files (the ones a
    curation change names: re-applying a whole root of a million files takes seconds). Returns the
    entries holding the applied linked files."""
    root = conn.execute("SELECT environment_id FROM environment_root WHERE id = ?", (root_id,)).fetchone()
    if root is None:
        return set()
    environment_id = root[0]
    if rel_keys is None:
        conn.execute("DELETE FROM entry_file WHERE role = 'linked' AND file_id IN"
                     " (SELECT id FROM file WHERE root_id = ?)", (root_id,))
        links = linked_keys(conn, root_id)
    else:
        left = set()  # entries the scoped files leave: the only ones that can become stale
        links = {}
        for rel_key in sorted(_with_neighbours(conn, root_id, set(rel_keys))):
            f = conn.execute("SELECT id FROM file WHERE root_id = ? AND rel_key = ?", (root_id, rel_key)).fetchone()
            if f is not None:
                left |= {r[0] for r in conn.execute(
                    "SELECT entry_id FROM entry_file WHERE file_id = ? AND role = 'linked'", (f[0],))}
                conn.execute("DELETE FROM entry_file WHERE file_id = ? AND role = 'linked'", (f[0],))
            link = conn.execute("SELECT target_uid, role FROM override_link WHERE kind = 'file_to_dossier'"
                                " AND subject = ? AND target_uid IS NOT NULL",
                                (link_subject(root_id, rel_key),)).fetchone()
            if link is not None:
                links[rel_key] = (link[0], link[1])
    touched: set[int] = set()
    for rel_key, (target_uid, _role) in links.items():
        f = conn.execute("SELECT id, container_id FROM file WHERE root_id = ? AND rel_key = ?"
                         " AND state = 'present'", (root_id, rel_key)).fetchone()
        target = conn.execute("SELECT id FROM dossier WHERE uid = ?", (target_uid,)).fetchone()
        if f is None or target is None or f["container_id"] is None:
            continue
        # Through the dossier's ledgers: one container can hold every entry of a big root.
        home = conn.execute(
            "SELECT e.id FROM ledger l CROSS JOIN entry e ON e.ledger_id = l.id WHERE l.dossier_id = ?"
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
    if rel_keys is None:
        stale = [r[0] for r in conn.execute(
            "SELECT e.id FROM entry e JOIN container c ON c.id = e.container_id WHERE c.root_id = ?"
            " AND e.identity_key LIKE 'link:%' AND NOT EXISTS (SELECT 1 FROM entry_file ef WHERE ef.entry_id = e.id)",
            (root_id,))]
    else:
        stale = [i for i in left if conn.execute(
            "SELECT 1 FROM entry e WHERE e.id = ? AND e.identity_key LIKE 'link:%'"
            " AND NOT EXISTS (SELECT 1 FROM entry_file ef WHERE ef.entry_id = e.id)", (i,)).fetchone()]
    ledgers = {r[0] for i in stale for r in conn.execute("SELECT ledger_id FROM entry WHERE id = ?", (i,))}
    for entry_id in stale:
        conn.execute("DELETE FROM entry WHERE id = ?", (entry_id,))
    if rel_keys is None:
        conn.execute("DELETE FROM ledger WHERE NOT EXISTS (SELECT 1 FROM entry e WHERE e.ledger_id = ledger.id)"
                     " AND environment_id = ?", (environment_id,))
    else:
        for ledger_id in ledgers:
            conn.execute("DELETE FROM ledger WHERE id = ? AND NOT EXISTS"
                         " (SELECT 1 FROM entry e WHERE e.ledger_id = ?)", (ledger_id, ledger_id))
    return touched


def _with_neighbours(conn: sqlite3.Connection, root_id: int, rel_keys: set[str]) -> set[str]:
    """The files plus the other linked files sharing a home with them (same dossier and container),
    so that a home is chosen for all of them at once, as applying the whole root would."""
    groups = set()
    for rel_key in rel_keys:
        f = conn.execute("SELECT id, container_id FROM file WHERE root_id = ? AND rel_key = ?",
                         (root_id, rel_key)).fetchone()
        if f is None or f["container_id"] is None:
            continue
        dossiers = {r[0] for r in conn.execute(
            "SELECT l.dossier_id FROM entry_file ef JOIN entry e ON e.id = ef.entry_id"
            " JOIN ledger l ON l.id = e.ledger_id WHERE ef.file_id = ? AND ef.role = 'linked'", (f["id"],))}
        dossiers |= {r[0] for r in conn.execute(
            "SELECT d.id FROM override_link o JOIN dossier d ON d.uid = o.target_uid"
            " WHERE o.kind = 'file_to_dossier' AND o.subject = ?", (link_subject(root_id, rel_key),))}
        groups |= {(d, f["container_id"]) for d in dossiers}
    keys = set(rel_keys)
    for dossier_id, container_id in groups:
        keys |= {r[0] for r in conn.execute(
            "SELECT f.rel_key FROM ledger l CROSS JOIN entry e ON e.ledger_id = l.id"
            " JOIN entry_file ef ON ef.entry_id = e.id JOIN file f ON f.id = ef.file_id"
            " WHERE l.dossier_id = ? AND e.container_id = ? AND ef.role = 'linked' AND f.root_id = ?",
            (dossier_id, container_id, root_id))}
    return keys
