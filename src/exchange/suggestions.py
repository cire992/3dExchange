"""Suggestions: links and groupings Exchange proposes and the user accepts or rejects in batches.

* ``texture_link``: images named like a mesh plus a texture channel (``Barrel01_D.png``,
  ``Barrel01_N.png`` beside ``Barrel01.glb``) are proposed as that mesh's textures. Bethesda-style
  layouts are understood too (``meshes/x/donut.nif`` with ``textures/x/donut_d.dds``).
* ``variant_group``: dossiers in one folder whose names differ only by variant words
  (``Donut01_Pink``, ``Donut01_Blue``) are proposed as one dossier with variants.
* ``lexicon_word`` suggestions come from tagging by hand (see ``Curator.tag``).

Each suggestion has a deterministic key, so a rejected one is not proposed again; a pending one
whose grounds disappeared becomes ``stale``. Accepting goes through ``Curator.accept``.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import defaultdict
from collections.abc import Iterable

from exchange.db import repository as repo
from exchange.definitions.schema import DefinitionSet
from exchange.lexicons import LexiconIndex
from exchange.scanner.tokenize import tokenize

MESH_FILE_EXTS = frozenset({".glb", ".gltf", ".fbx", ".obj", ".dae", ".nif", ".blend", ".3ds", ".ply", ".stl"})
IMAGE_EXTS = frozenset({".png", ".jpg", ".jpeg", ".tga", ".bmp", ".dds", ".tif", ".tiff", ".webp", ".exr"})
TEXTURE_DIRS = ("textures", "texture", "tex", "maps", "materials")
GENERATED = ("texture_link", "variant_group")


def _key(kind: str, parts: Iterable[str]) -> str:
    return f"{kind}:" + hashlib.blake2b("|".join(sorted(parts)).encode(), digest_size=8).hexdigest()


def generate(conn: sqlite3.Connection, definitions: DefinitionSet, *,
             environment_ids: Iterable[int]) -> dict[str, int]:
    """Propose links and groupings for some environments. Returns new suggestions by kind."""
    ids = list(environment_ids)
    index = LexiconIndex(definitions)
    proposals: list[tuple[str, str, str, dict, float]] = []  # kind, key, subject, payload, confidence
    proposals += _texture_links(conn, index, ids)
    proposals += _variant_groups(conn, index, ids)

    keys = {p[1] for p in proposals}
    created = defaultdict(int)
    for kind, key, subject, payload, confidence in proposals:
        cur = conn.execute(
            "INSERT OR IGNORE INTO suggestion (kind, key, subject_uid, payload, confidence, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)", (kind, key, subject, repo.to_json(payload), confidence, repo.now()))
        created[kind] += cur.rowcount
    # Pending proposals about these environments whose grounds are gone are stale now.
    marks = ",".join("?" * len(ids))
    pending = conn.execute(
        f"SELECT s.id, s.key FROM suggestion s WHERE s.state = 'pending' AND s.kind IN ('texture_link', 'variant_group')"
        f" AND (s.subject_uid IS NULL OR NOT EXISTS (SELECT 1 FROM dossier d WHERE d.uid = s.subject_uid)"
        f" OR EXISTS (SELECT 1 FROM dossier d JOIN ledger l ON l.dossier_id = d.id"
        f" WHERE d.uid = s.subject_uid AND l.environment_id IN ({marks})))", ids).fetchall()
    stale = [r[0] for r in pending if r[1] not in keys]
    conn.executemany("UPDATE suggestion SET state = 'stale' WHERE id = ?", ((i,) for i in stale))
    return {k: created.get(k, 0) for k in GENERATED} | {"stale": len(stale)}


def _texture_links(conn, index: LexiconIndex, env_ids: list[int]) -> list:
    marks = ",".join("?" * len(env_ids))
    meshes = conn.execute(
        f"SELECT d.uid, f.root_id, f.rel_path, f.rel_key, f.ext FROM dossier d"
        f" JOIN ledger l ON l.dossier_id = d.id JOIN entry e ON e.ledger_id = l.id"
        f" JOIN entry_file ef ON ef.entry_id = e.id AND ef.role = 'primary' JOIN file f ON f.id = ef.file_id"
        f" WHERE l.environment_id IN ({marks}) AND e.status != 'retired' AND f.state = 'present'"
        f" AND d.type_id != 'product'", env_ids).fetchall()
    meshes = [m for m in meshes if m["ext"] in MESH_FILE_EXTS]
    if not meshes:
        return []
    # Images per (root, folder), and which are already somebody's primary file or linked.
    roots = sorted({m["root_id"] for m in meshes})
    images: dict[tuple[int, str], list[sqlite3.Row]] = defaultdict(list)
    for root_id in roots:
        for f in conn.execute(
                "SELECT f.id, f.root_id, f.rel_path, f.rel_key, f.ext FROM file f WHERE f.root_id = ?"
                " AND f.state = 'present' AND NOT EXISTS (SELECT 1 FROM entry_file ef JOIN entry e ON e.id = ef.entry_id"
                " WHERE ef.file_id = f.id AND ef.role IN ('primary', 'linked') AND e.status != 'retired')", (root_id,)):
            if f["ext"] in IMAGE_EXTS:
                folder = f["rel_key"].rsplit("/", 1)[0] if "/" in f["rel_key"] else ""
                images[(root_id, folder)].append(f)

    out = []
    for m in meshes:
        base = _base_tokens(index, m["rel_path"])
        if not base:
            continue
        files = []
        for folder in _texture_folders(m["rel_key"]):
            for img in images.get((m["root_id"], folder), ()):
                channel = _channel(index, img["rel_path"], base)
                if channel:
                    files.append({"root_id": img["root_id"], "rel_key": img["rel_key"],
                                  "rel": img["rel_path"], "channel": channel})
        if files:
            files.sort(key=lambda f: f["rel_key"])
            key = _key("texture_link", [m["uid"], *(f["rel_key"] for f in files)])
            out.append(("texture_link", key, m["uid"],
                        {"mesh": m["rel_path"], "files": files}, 0.8))
    return out


def _base_tokens(index: LexiconIndex, rel: str) -> tuple[str, ...]:
    stem = rel.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    return tuple(index.clean(tokenize(stem)))


def _texture_folders(mesh_rel_key: str) -> list[str]:
    folder = mesh_rel_key.rsplit("/", 1)[0] if "/" in mesh_rel_key else ""
    parent = folder.rsplit("/", 1)[0] if "/" in folder else ""
    out = [folder]
    out += [f"{folder}/{t}".lstrip("/") for t in TEXTURE_DIRS]
    out += [f"{parent}/{t}".lstrip("/") for t in TEXTURE_DIRS]
    parts = folder.split("/")
    if "meshes" in parts:  # Bethesda: <mod>/meshes/a/b.nif <-> <mod>/textures/a/b_d.dds
        i = parts.index("meshes")
        out.append("/".join([*parts[:i], "textures", *parts[i + 1:]]))
    return list(dict.fromkeys(out))


def _channel(index: LexiconIndex, image_rel: str, mesh_base: tuple[str, ...]) -> str | None:
    """The texture channel if the image is ``<mesh name>_<channel>[_<number>]``."""
    tokens = list(_base_tokens(index, image_rel))
    while tokens and tokens[-1].isdigit() and len(tokens) > len(mesh_base) + 1:
        tokens.pop()  # UDIM tile or index after the channel (Marius_Face_D_1001)
    for m in index.match(tokens):
        if m.kind == "texture_channel" and m.start + m.length == len(tokens) \
                and tuple(tokens[: m.start]) == mesh_base:
            return m.value
    return None


def _variant_groups(conn, index: LexiconIndex, env_ids: list[int]) -> list:
    marks = ",".join("?" * len(env_ids))
    rows = conn.execute(
        f"SELECT d.id, d.uid, d.name, d.type_id, e.container_id, f.rel_key FROM dossier_effective d"
        f" JOIN ledger l ON l.dossier_id = d.id JOIN entry e ON e.ledger_id = l.id"
        f" JOIN entry_file ef ON ef.entry_id = e.id AND ef.role = 'primary' JOIN file f ON f.id = ef.file_id"
        f" WHERE l.environment_id IN ({marks}) AND e.status != 'retired' AND e.moved_from IS NULL"
        f" AND d.type_id != 'product' AND NOT EXISTS (SELECT 1 FROM dossier_alias a WHERE a.alias_uid = d.uid)",
        env_ids).fetchall()
    groups: dict[tuple, dict[str, tuple[int, str | None]]] = defaultdict(dict)
    for r in rows:
        tokens = index.clean(tokenize(r["name"]))
        variant_words = []
        drop: set[int] = set()
        for m in index.match(tokens):
            if m.kind == "variant":
                variant_words.append(" ".join(tokens[m.start:m.start + m.length]))
                drop.update(range(m.start, m.start + m.length))
        base = tuple(t for i, t in enumerate(tokens) if i not in drop)
        if not base:
            continue
        folder = r["rel_key"].rsplit("/", 1)[0] if "/" in r["rel_key"] else ""
        key = (r["container_id"], folder, r["type_id"], base)
        groups[key].setdefault(r["uid"], (r["id"], " ".join(variant_words).title() or None))
    out = []
    for (_, _, _, base), members in groups.items():
        if len(members) < 2:
            continue
        named = [uid for uid, (_, v) in members.items() if v]
        if len(named) < len(members) - 1:
            continue  # at most one plain member (the base form); the rest must name a variant
        ordered = sorted(members, key=lambda uid: members[uid][0])
        variants = {uid: members[uid][1] or "Default" for uid in ordered}
        if len(set(variants.values())) < len(variants):
            continue  # two members with the same variant word are not variants of each other
        out.append(("variant_group", _key("variant_group", ordered), ordered[0],
                    {"base": " ".join(base), "members": ordered, "variants": variants}, 0.7))
    return out


def list_suggestions(conn: sqlite3.Connection, *, state: str = "pending", kind: str | None = None,
                     limit: int = 200) -> list[dict]:
    sql = ("SELECT s.*, d.name AS subject_name FROM suggestion s LEFT JOIN dossier_effective d ON d.uid = s.subject_uid"
           " WHERE s.state = ?")
    params: list = [state]
    if kind:
        sql += " AND s.kind = ?"
        params.append(kind)
    rows = conn.execute(sql + " ORDER BY s.id LIMIT ?", [*params, limit]).fetchall()
    return [{"id": r["id"], "kind": r["kind"], "subject": r["subject_uid"], "subject_name": r["subject_name"],
             "confidence": r["confidence"], "state": r["state"], "payload": json.loads(r["payload"])} for r in rows]

