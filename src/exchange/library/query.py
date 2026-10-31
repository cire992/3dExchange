"""Read-side API for browsing the library: what the UI (and ``exchange search``/``show``) show.

Everything here reads effective values (user overrides win) and returns plain data, so it can be
tested and used without any UI toolkit.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from exchange.db import repository as repo
from exchange.definitions.schema import DefinitionSet
from exchange.library.new import marker as new_marker
from exchange.library.search import DISMISSED, compile_query

GROUPS = ("product", "type", "all")

# Effective values for filtering and sorting, computed once per query. Sorting through the full
# dossier_effective view (which carries large columns such as signals) is ~10x slower.
EFFECTIVE = ("WITH d AS MATERIALIZED (SELECT id, uid, name, type_id, parent_id, confidence,"
             " name_overridden, type_overridden, parent_overridden FROM dossier_effective)")


@dataclass
class Brick:
    """One tile in the browser."""

    id: int
    uid: str
    name: str
    type_id: str
    type_name: str
    confidence: float
    unidentified: bool
    thumbnail: str | None
    format: str | None  # the primary file's extension, e.g. ".glb"
    environments: list[str] = field(default_factory=list)
    entries: int = 0
    children: int = 0


@dataclass
class Page:
    items: list[Brick]
    total: int
    offset: int


def _type_name(definitions: DefinitionSet, type_id: str) -> str:
    dtype = definitions.dossier_types.get(type_id)
    return dtype.name if dtype else type_id


def list_dossiers(
    conn: sqlite3.Connection,
    definitions: DefinitionSet,
    *,
    query: str = "",
    group: str = "product",
    environment_id: int | None = None,
    container_id: int | None = None,
    type_id: str | None = None,
    parent_uid: str | None = None,
    new: bool = False,
    offset: int = 0,
    limit: int = 200,
    threshold: float = 0.5,
    thumbnail_dir: Path | None = None,
) -> Page:
    if group not in GROUPS:
        raise ValueError(f"group must be one of {GROUPS}")
    where, params = compile_query(query, definitions, threshold=threshold, conn=conn)
    clauses, args = [where], list(params)
    seen_up_to = None
    if new:
        seen_up_to = new_marker(conn)
        if seen_up_to is None:
            return Page([], 0, offset)
        # Two uncorrelated sets: a correlated EXISTS per row is far too slow on a big library.
        written = ("SELECT l.dossier_id FROM ledger l JOIN entry e ON e.ledger_id = l.id"
                   " WHERE e.status != 'retired' AND e.requisition_id IS NULL")
        clauses.append(f"d.id > ? AND (d.id IN ({written}) OR d.id IN"
                       f" (SELECT c.parent_id FROM d c WHERE c.parent_id > ? AND c.id IN ({written})))")
        args.extend([seen_up_to, seen_up_to])
    if parent_uid is not None:
        clauses.append("d.parent_id = (SELECT id FROM dossier WHERE uid = ?)")
        args.append(parent_uid)
    elif group == "product":
        if new:
            clauses.append("(d.parent_id IS NULL OR d.parent_id <= ?)")
            args.append(seen_up_to)
        else:
            clauses.append("d.parent_id IS NULL")
    elif group == "type":
        clauses.append("d.type_id != 'product'")
    if environment_id is not None:
        clauses.append("EXISTS (SELECT 1 FROM ledger l JOIN entry e ON e.ledger_id = l.id"
                       " WHERE l.dossier_id = d.id AND l.environment_id = ? AND e.status != 'retired')")
        args.append(environment_id)
    if container_id is not None:
        clauses.append("EXISTS (SELECT 1 FROM ledger l JOIN entry e ON e.ledger_id = l.id"
                       " WHERE l.dossier_id = d.id AND e.container_id = ? AND e.status != 'retired')")
        args.append(container_id)
    if type_id is not None:
        types = [t for t in definitions.dossier_types if definitions.is_a(t, type_id)] or [type_id]
        clauses.append(f"d.type_id IN ({','.join('?' * len(types))})")
        args.extend(types)
    condition = " AND ".join(clauses)
    order = "d.type_id, lower(d.name), d.id" if group == "type" else "lower(d.name), d.id"
    # Sort and cut the page first; per-row details are then looked up for that page only.
    ranked = conn.execute(
        f"{EFFECTIVE} SELECT d.id, count(*) OVER () FROM d WHERE {condition} ORDER BY {order}"
        f" LIMIT ? OFFSET ?", [*args, limit, offset]).fetchall()
    total = ranked[0][1] if ranked else (
        conn.execute(f"{EFFECTIVE} SELECT count(*) FROM d WHERE {condition}", args).fetchone()[0] if offset else 0)
    ids = [r[0] for r in ranked]
    if not ids:
        return Page([], total, offset)
    rows = conn.execute(
        f"SELECT d.id, d.uid, d.name, d.type_id, d.confidence,"
        f" (SELECT rel_path FROM thumbnail t WHERE t.dossier_id = d.id) AS thumbnail,"
        f" (SELECT f.ext FROM ledger l JOIN entry e ON e.ledger_id = l.id"
        f"   JOIN entry_file ef ON ef.entry_id = e.id AND ef.role = 'primary'"
        f"   JOIN file f ON f.id = ef.file_id WHERE l.dossier_id = d.id AND e.status != 'retired'"
        f"   ORDER BY e.id LIMIT 1) AS format,"
        f" (SELECT group_concat(DISTINCT env.name) FROM ledger l JOIN entry e ON e.ledger_id = l.id"
        f"   JOIN environment env ON env.id = l.environment_id"
        f"   WHERE l.dossier_id = d.id AND e.status != 'retired') AS environments,"
        f" (SELECT count(*) FROM ledger l JOIN entry e ON e.ledger_id = l.id"
        f"   WHERE l.dossier_id = d.id AND e.status != 'retired') AS entries,"
        f" (SELECT count(*) FROM dossier c WHERE c.parent_id = d.id) AS children"
        f" FROM dossier_effective d WHERE d.id IN ({','.join('?' * len(ids))})", ids).fetchall()
    position = {dossier_id: i for i, dossier_id in enumerate(ids)}
    rows = sorted(rows, key=lambda r: position[r["id"]])
    items = [Brick(
        id=r["id"], uid=r["uid"], name=r["name"], type_id=r["type_id"],
        type_name=_type_name(definitions, r["type_id"]), confidence=r["confidence"],
        unidentified=r["confidence"] < threshold,
        thumbnail=str(thumbnail_dir / r["thumbnail"]) if thumbnail_dir and r["thumbnail"] else r["thumbnail"],
        format=r["format"], environments=(r["environments"] or "").split(",") if r["environments"] else [],
        entries=r["entries"], children=r["children"]) for r in rows]
    return Page(items, total, offset)


def sidebar(conn: sqlite3.Connection, definitions: DefinitionSet, *, threshold: float = 0.5) -> dict:
    """Counts for the sidebar: the whole library, each environment's containers and types."""
    live = ("SELECT DISTINCT l.dossier_id, l.environment_id, e.container_id FROM ledger l"
            " JOIN entry e ON e.ledger_id = l.id WHERE e.status != 'retired'")
    out = {
        "all": conn.execute(f"SELECT count(DISTINCT dossier_id) FROM ({live})").fetchone()[0],
        "unidentified_dossiers": conn.execute(
            f"SELECT count(DISTINCT x.dossier_id) FROM ({live}) x JOIN dossier d ON d.id = x.dossier_id"
            f" WHERE d.confidence < ? AND NOT {DISMISSED}", (threshold,)).fetchone()[0],
        # Counted when each root was last scanned; counting live is too slow for big libraries.
        "unattached_files": conn.execute(
            "SELECT COALESCE(sum(s.unattached_files), 0) FROM scan s WHERE s.id IN"
            " (SELECT max(id) FROM scan WHERE finished_at IS NOT NULL GROUP BY root_id)"
            " AND s.root_id IN (SELECT id FROM environment_root WHERE status = 'online')").fetchone()[0],
        "environments": [],
    }
    for env in repo.list_environments(conn):
        roots = repo.list_roots(conn, env["id"])
        statuses = {r["status"] for r in roots}
        containers = conn.execute(
            f"SELECT c.id, c.name, c.kind, count(DISTINCT x.dossier_id) AS count FROM container c"
            f" LEFT JOIN ({live}) x ON x.container_id = c.id WHERE c.environment_id = ?"
            f" GROUP BY c.id ORDER BY lower(c.name)", (env["id"],)).fetchall()
        types = conn.execute(
            f"{EFFECTIVE} SELECT d.type_id, count(DISTINCT d.id) AS count FROM ({live}) x"
            f" JOIN d ON d.id = x.dossier_id WHERE x.environment_id = ?"
            f" GROUP BY d.type_id ORDER BY d.type_id", (env["id"],)).fetchall()
        out["environments"].append({
            "id": env["id"], "name": env["name"], "type_id": env["type_id"],
            "status": "online" if statuses == {"online"} else "offline" if statuses == {"offline"} else "partial",
            "count": conn.execute(f"SELECT count(DISTINCT dossier_id) FROM ({live}) WHERE environment_id = ?",
                                  (env["id"],)).fetchone()[0],
            "roots": [{"id": r["id"], "path": r["path"], "status": r["status"],
                       "offline_since": r["offline_since"]} for r in roots],
            "containers": [dict(c) for c in containers],
            "types": [{"type_id": t["type_id"], "name": _type_name(definitions, t["type_id"]),
                       "count": t["count"]} for t in types],
        })
    return out


def dossier_detail(conn: sqlite3.Connection, definitions: DefinitionSet, uid: str, *,
                   threshold: float = 0.5, thumbnail_dir: Path | None = None) -> dict | None:
    """Everything the inspector shows for one dossier."""
    d = repo.effective_dossier(conn, uid)
    if d is None:
        return None
    sources = repo.field_sources(conn, uid)
    parent = conn.execute("SELECT uid, name FROM dossier_effective WHERE id = ?", (d["parent_id"],)).fetchone() \
        if d["parent_id"] else None
    children = conn.execute(
        "SELECT uid, name, type_id FROM dossier_effective WHERE parent_id = ? ORDER BY lower(name)",
        (d["id"],)).fetchall()
    thumb = repo.thumbnail_row(conn, d["id"])

    ledgers = []
    for ledger in conn.execute(
            "SELECT l.id, env.id AS env_id, env.name, env.type_id FROM ledger l"
            " JOIN environment env ON env.id = l.environment_id WHERE l.dossier_id = ? ORDER BY env.name",
            (d["id"],)):
        entries = []
        for e in conn.execute(
                "SELECT e.*, c.name AS container, c.kind, r.path AS root_path,"
                " (SELECT c2.name FROM entry s JOIN container c2 ON c2.id = s.container_id"
                "  WHERE s.id = e.source_entry_id) AS source_container"
                " FROM entry e JOIN container c ON c.id = e.container_id"
                " JOIN environment_root r ON r.id = c.root_id WHERE e.ledger_id = ? ORDER BY e.id",
                (ledger["id"],)):
            files = conn.execute(
                "SELECT f.id, f.root_id AS root, f.rel_key AS key, f.rel_path, f.size, f.hash, f.state, ef.role FROM entry_file ef"
                " JOIN file f ON f.id = ef.file_id WHERE ef.entry_id = ?"
                " ORDER BY ef.role = 'primary' DESC, lower(f.rel_path)", (e["id"],)).fetchall()
            entries.append({
                "id": e["id"], "container": e["container"], "container_kind": e["kind"],
                "status": e["status"], "source_container": e["source_container"],
                "created_at": e["created_at"], "retired_at": e["retired_at"],
                "variant": e["variant"], "moved_from": e["moved_from"],
                "files": [{**dict(f), "path": str(Path(e["root_path"]) / Path(*f["rel_path"].split("/")))}
                          for f in files],
            })
        ledgers.append({"environment": {"id": ledger["env_id"], "name": ledger["name"],
                                        "type_id": ledger["type_id"]}, "entries": entries})

    deps = conn.execute(
        "SELECT x.reference, x.status, t.uid, t.name FROM dossier_dependency x"
        " LEFT JOIN dossier_effective t ON t.id = x.target_dossier_id WHERE x.dossier_id = ?"
        " ORDER BY x.status, x.reference", (d["id"],)).fetchall()
    required_by = conn.execute(
        "SELECT DISTINCT s.uid, s.name FROM dossier_dependency x JOIN dossier_effective s"
        " ON s.id = x.dossier_id WHERE x.target_dossier_id = ? ORDER BY lower(s.name)", (d["id"],)).fetchall()
    history = []
    for h in conn.execute(
            "SELECT * FROM curation_log WHERE json_extract(payload, '$.dossier') = ?"
            " OR EXISTS (SELECT 1 FROM json_each(payload, '$.dossiers') j WHERE j.value = ?) ORDER BY id",
            (uid, uid)):
        payload = json.loads(h["payload"])
        undoable = "inverse" in payload
        for key in ("changes", "inverse"):
            payload.pop(key, None)
        history.append({"id": h["id"], "at": h["at"], "action": h["action"], "payload": payload,
                        "undoable": undoable})
    for ledger in ledgers:
        for e in ledger["entries"]:
            history.append({"at": e["created_at"], "action": "entry_added",
                            "payload": {"environment": ledger["environment"]["name"], "container": e["container"]}})
            if e["retired_at"]:
                history.append({"at": e["retired_at"], "action": "entry_retired",
                                "payload": {"environment": ledger["environment"]["name"], "container": e["container"]}})
    history.sort(key=lambda h: h["at"])

    return {
        "uid": uid,
        "name": d["name"],
        "name_overridden": bool(d["name_overridden"]),
        "type_id": d["type_id"],
        "type_name": _type_name(definitions, d["type_id"]),
        "type_overridden": bool(d["type_overridden"]),
        "confidence": d["confidence"],
        "unidentified": d["confidence"] < threshold,
        "signals": json.loads(d["signals"]),
        "fields": {k: {"value": v, "source": s} for k, (v, s) in sorted(sources.items())
                   if k not in ("references", "enriched_hash", "product_key")},
        "tags": sorted(repo.effective_tags(conn, uid)),
        "variant": sources.get("variant", (None, None))[0],
        "thumbnail": (str(thumbnail_dir / thumb["rel_path"]) if thumbnail_dir else thumb["rel_path"]) if thumb else None,
        "parent": dict(parent) if parent else None,
        "children": [dict(c) for c in children],
        "ledgers": ledgers,
        "dependencies": [{"reference": x["reference"], "status": x["status"],
                          "target": {"uid": x["uid"], "name": x["name"]} if x["uid"] else None} for x in deps],
        "required_by": [dict(r) for r in required_by],
        "history": history,
        # Curation (Roadmap phase 3)
        "variants": sorted({e["variant"] for l in ledgers for e in l["entries"] if e["variant"]}),
        "tag_sources": _tag_sources(conn, d["id"], uid),
        "aliases": [dict(r) for r in conn.execute(
            "SELECT a.alias_uid AS uid, x.name FROM dossier_alias a LEFT JOIN dossier_effective x ON x.uid = a.alias_uid"
            " WHERE a.target_uid = ? ORDER BY a.set_at", (uid,))],
        "suggestions": [{"id": s["id"], "kind": s["kind"], "payload": json.loads(s["payload"])} for s in conn.execute(
            "SELECT * FROM suggestion WHERE subject_uid = ? AND state = 'pending' ORDER BY id", (uid,))],
        "collections": [dict(r) for r in conn.execute(
            "SELECT c.uid, c.name FROM collection_member m JOIN collection c ON c.uid = m.collection_uid"
            " WHERE m.dossier_uid = ? ORDER BY c.name", (uid,))],
    }


def _tag_sources(conn: sqlite3.Connection, dossier_id: int, uid: str) -> list[dict]:
    """Each effective tag with where it came from (scan signals and/or you) and its confidence."""
    tags: dict[str, dict] = {}
    for r in conn.execute("SELECT tag, source, confidence FROM dossier_tag WHERE dossier_id = ?", (dossier_id,)):
        t = tags.setdefault(r["tag"], {"tag": r["tag"], "sources": [], "confidence": 0.0, "user": None})
        t["sources"].append(r["source"])
        t["confidence"] = max(t["confidence"], r["confidence"])
    for r in conn.execute("SELECT tag, action FROM override_tag WHERE dossier_uid = ?", (uid,)):
        t = tags.setdefault(r["tag"], {"tag": r["tag"], "sources": [], "confidence": 1.0, "user": None})
        t["user"] = r["action"]  # "add" or "remove" (a scanned tag the user hid)
    return sorted(tags.values(), key=lambda t: t["tag"].casefold())


def list_collections(conn: sqlite3.Connection, definitions: DefinitionSet, *,
                     threshold: float = 0.5) -> list[dict]:
    """Collections with their member counts (a smart collection counts its search's results)."""
    out = []
    for c in conn.execute("SELECT * FROM collection ORDER BY name COLLATE NOCASE"):
        if c["query"] is None:
            count = conn.execute("SELECT count(*) FROM collection_member WHERE collection_uid = ?",
                                 (c["uid"],)).fetchone()[0]
        else:
            try:
                count = list_dossiers(conn, definitions, query=f"collection:{c['uid']}", group="all",
                                      limit=1, threshold=threshold).total
            except Exception:  # a saved search that no longer compiles (e.g. a removed type)
                count = None
        out.append({"uid": c["uid"], "name": c["name"], "query": c["query"], "smart": c["query"] is not None,
                    "count": count})
    return out
