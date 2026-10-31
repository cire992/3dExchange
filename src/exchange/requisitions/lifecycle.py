"""After queueing: resuming, holding and reordering; removing output; staleness and rebuilding.

* **Resume** a requisition that needs attention (after a checkpoint, or choosing what to do
  about files already at the endpoint); failed items are retried too.
* **Remove** its output: every file it wrote goes to the recycle folder, files it overwrote
  come back, and the endpoint is rescanned so its entries retire.
* **Stale:** a fulfilled requisition whose source files or process versions changed since.
  Its entries are marked stale; **rebuild** queues it again with the current processes,
  overwriting its earlier output (kept in the recycle folder).
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

from exchange.db import repository as repo
from exchange.definitions.schema import DefinitionSet
from exchange.errors import ExchangeError
from exchange.processes.registry import Registry
from exchange.requisitions.runner import _load_state, _save_state, _state_file, recycle, source_fingerprint, work_dir

STATES = ("queued", "held", "running", "needs_attention", "fulfilled", "partially_fulfilled", "failed",
          "stale", "removed", "replaced")


class LifecycleError(ExchangeError):
    pass


def get(conn: sqlite3.Connection, ref: int | str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM requisition WHERE id = ?", (int(ref),)).fetchone() if str(ref).isdigit() else None
    if row is None:
        rows = conn.execute("SELECT * FROM requisition WHERE uid LIKE ?", (f"{ref}%",)).fetchall()
        row = rows[0] if len(rows) == 1 else None
    if row is None:
        raise LifecycleError(f"no requisition {ref}")
    return row


def list_requisitions(conn: sqlite3.Connection, states: tuple[str, ...] = ()) -> list[dict]:
    sql = ("SELECT r.*, (SELECT count(*) FROM requisition_item i WHERE i.requisition_id = r.id AND i.include) AS items,"
           " (SELECT count(*) FROM requisition_item i WHERE i.requisition_id = r.id AND i.state = 'done') AS done,"
           " v.name AS environment FROM requisition r JOIN environment v ON v.id = r.environment_id")
    if states:
        sql += f" WHERE r.state IN ({','.join('?' * len(states))})"
    # Waiting or running first, in queue order; then the finished ones, newest first.
    active = "r.state IN ('queued', 'held', 'running', 'needs_attention')"
    rows = conn.execute(sql + f" ORDER BY NOT {active}, CASE WHEN {active} THEN r.position ELSE -r.id END",
                        states).fetchall()
    return [dict(r) for r in rows]


def detail(conn: sqlite3.Connection, ref: int | str) -> dict:
    req = get(conn, ref)
    items = []
    for i in conn.execute("SELECT * FROM requisition_item WHERE requisition_id = ? ORDER BY id", (req["id"],)):
        name = conn.execute("SELECT name FROM dossier_effective WHERE uid = ?", (i["dossier_uid"],)).fetchone()
        items.append({**dict(i), "name": name[0] if name else i["dossier_uid"],
                      "processes": json.loads(i["processes"]), "params": json.loads(i["params"]),
                      "outputs": json.loads(i["outputs"] or "[]")})
    writes = [dict(w) for w in conn.execute("SELECT * FROM requisition_write WHERE requisition_id = ? ORDER BY id",
                                            (req["id"],))]
    work = work_dir(req["uid"])
    return {**dict(req), "endpoint": json.loads(req["endpoint"]), "items": items, "writes": writes,
            "work_folder": str(work) if work.is_dir() else None}


def resume(conn: sqlite3.Connection, ref: int | str, on_collision: str | None = None) -> None:
    req = get(conn, ref)
    if req["state"] not in ("needs_attention", "failed", "partially_fulfilled", "held", "queued"):
        raise LifecycleError(f"requisition {req['id']} is {req['state']}; there is nothing to resume")
    if on_collision is not None and on_collision not in ("ask", "overwrite", "rename", "skip"):
        raise LifecycleError("on_collision must be ask, overwrite, rename or skip")
    with repo.transaction(conn):
        for item in conn.execute("SELECT id, state FROM requisition_item WHERE requisition_id = ?"
                                 " AND state IN ('needs_attention', 'failed')", (req["id"],)).fetchall():
            if item["state"] == "needs_attention":
                path = _state_file(req["uid"], item["id"])
                state = _load_state(path)
                state["resume"] = True  # the step that paused runs again, knowing the user is done
                _save_state(path, state)
            conn.execute("UPDATE requisition_item SET state = 'queued', message = NULL WHERE id = ?", (item["id"],))
        conn.execute("UPDATE requisition SET state = 'queued', message = NULL, on_collision = COALESCE(?, on_collision)"
                     " WHERE id = ?", (on_collision, req["id"]))


def hold(conn: sqlite3.Connection, ref: int | str, held: bool = True) -> None:
    """Keep a queued requisition from running (or let it run again)."""
    req = get(conn, ref)
    if req["state"] != ("queued" if held else "held"):
        raise LifecycleError(f"requisition {req['id']} is {req['state']}")
    conn.execute("UPDATE requisition SET state = ? WHERE id = ?", ("held" if held else "queued", req["id"]))


def move(conn: sqlite3.Connection, ref: int | str, position: int) -> None:
    """Put a requisition at a place in the queue (1 is first)."""
    req = get(conn, ref)
    order = [r[0] for r in conn.execute("SELECT id FROM requisition WHERE state IN ('queued', 'held') AND id != ?"
                                        " ORDER BY position", (req["id"],))]
    order.insert(max(0, min(position - 1, len(order))), req["id"])
    with repo.transaction(conn):
        for n, rid in enumerate(order, start=1):
            conn.execute("UPDATE requisition SET position = ? WHERE id = ?", (n, rid))


def _roots(conn: sqlite3.Connection, requisition_id: int) -> list[str]:
    roots = []
    for (outputs,) in conn.execute("SELECT outputs FROM requisition_item WHERE requisition_id = ?", (requisition_id,)):
        roots += [o["root"] for o in json.loads(outputs or "[]")]
    return list(dict.fromkeys(roots))


def remove(conn: sqlite3.Connection, db_path: Path, definitions: DefinitionSet, ref: int | str,
           rescan: bool = True) -> int:
    """Take a requisition's output away (to the recycle folder), putting back files it overwrote.
    Returns how many files moved."""
    req = get(conn, ref)
    if req["state"] in ("running",):
        raise LifecycleError(f"requisition {req['id']} is running")
    moved = 0
    writes = conn.execute("SELECT * FROM requisition_write WHERE requisition_id = ? AND removed_at IS NULL"
                          " ORDER BY id DESC", (req["id"],)).fetchall()
    for w in writes:
        path = Path(w["path"])
        if path.exists():
            recycle(req["uid"], path)
            moved += 1
        if w["action"] == "overwritten" and w["recycled_to"] and Path(w["recycled_to"]).exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(w["recycled_to"], path)  # what was there before comes back
        conn.execute("UPDATE requisition_write SET removed_at = ? WHERE id = ?", (repo.now(), w["id"]))
    conn.execute("UPDATE requisition SET state = 'removed', finished_at = ? WHERE id = ?", (repo.now(), req["id"]))
    if rescan:
        from exchange.scanner.scan import run_scan

        for root in _roots(conn, req["id"]):
            if Path(root).is_dir():
                run_scan(Path(root), db_path=db_path, definitions=definitions)
    return moved


def check_stale(conn: sqlite3.Connection, registry: Registry) -> list[tuple[int, str]]:
    """Mark fulfilled requisitions whose sources or processes changed since as stale (and their
    entries). Returns (requisition id, why) for each newly stale one."""
    found = []
    for req in conn.execute("SELECT * FROM requisition WHERE state IN ('fulfilled', 'partially_fulfilled')").fetchall():
        why = None
        for item in conn.execute("SELECT * FROM requisition_item WHERE requisition_id = ? AND state = 'done'",
                                 (req["id"],)):
            for p in json.loads(item["processes"]):
                package = registry.packages.get(p["id"])
                if package is None:
                    why = f"process {p['id']} is no longer installed"
                elif package.manifest.version != p["version"]:
                    why = f"process {p['id']} is now {package.manifest.version} (was {p['version']})"
            if why is None and source_fingerprint(conn, item["source_entry_id"]) != item["source_fingerprint"]:
                name = conn.execute("SELECT name FROM dossier_effective WHERE uid = ?", (item["dossier_uid"],)).fetchone()
                why = f"the source of {name[0] if name else item['dossier_uid']} changed"
            if why:
                break
        if why:
            with repo.transaction(conn):
                conn.execute("UPDATE requisition SET state = 'stale', message = ? WHERE id = ?", (why, req["id"]))
                conn.execute("UPDATE entry SET status = 'stale' WHERE requisition_id = ? AND status != 'retired'",
                             (req["id"],))
            found.append((req["id"], why))
    return found


def rebuild(conn: sqlite3.Connection, registry: Registry, ref: int | str) -> int:
    """Queue a stale (or any fulfilled) requisition again with the current processes, overwriting
    its earlier output. Returns the new requisition's id."""
    req = get(conn, ref)
    if req["state"] not in ("stale", "fulfilled", "partially_fulfilled"):
        raise LifecycleError(f"requisition {req['id']} is {req['state']}; only fulfilled or stale ones are rebuilt")
    with repo.transaction(conn):
        position = conn.execute("SELECT COALESCE(max(position), 0) + 1 FROM requisition").fetchone()[0]
        cur = conn.execute(
            "INSERT INTO requisition (uid, name, state, position, environment_id, endpoint, on_collision, replaces,"
            " created_at) VALUES (?, ?, 'queued', ?, ?, ?, 'overwrite', ?, ?)",
            (repo.new_uid(), req["name"], position, req["environment_id"], req["endpoint"], req["id"], repo.now()))
        new_id = cur.lastrowid
        for item in conn.execute("SELECT * FROM requisition_item WHERE requisition_id = ?", (req["id"],)).fetchall():
            processes = [{"id": p["id"], "version": registry.get(p["id"]).manifest.version}
                         for p in json.loads(item["processes"])]
            conn.execute("INSERT INTO requisition_item (requisition_id, dossier_uid, source_entry_id, processes, params,"
                         " include, state) VALUES (?, ?, ?, ?, ?, ?, ?)",
                         (new_id, item["dossier_uid"], item["source_entry_id"], json.dumps(processes), item["params"],
                          item["include"], "queued" if item["include"] else "skipped"))
        # The old sidecar goes (so the files are read as the new requisition's); its files stay
        # until the new run overwrites them, which keeps the previous versions in the recycle folder.
        for w in conn.execute("SELECT * FROM requisition_write WHERE requisition_id = ? AND removed_at IS NULL",
                              (req["id"],)).fetchall():
            if w["action"] == "sidecar" and Path(w["path"]).exists():
                recycle(req["uid"], Path(w["path"]))
            conn.execute("UPDATE requisition_write SET removed_at = ? WHERE id = ?", (repo.now(), w["id"]))
        conn.execute("UPDATE requisition SET state = 'replaced', message = ? WHERE id = ?",
                     (f"rebuilt as requisition {new_id}", req["id"]))
    return new_id
