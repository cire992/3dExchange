"""Scan phase 3, enrichment: the slow, background part of a scan. Incremental and cancellable.

Steps, in order, for one environment:

1. **Hashing**: BLAKE2b-128 of every present file without a hash (new or changed files).
2. **Duplicates**: a dossier whose primary file is byte-identical to an older dossier's is a copy.
   Its entries join the older dossier with *unknown provenance* (the spec's "manual copies are
   detected"). Dossiers the user has edited are never merged away.
3. **Meshes**: statistics for glTF/GLB/OBJ files, and the abstract ``mesh`` type refined to static
   or skinned mesh when the file says so.
4. **Dependencies** (Daz): content paths referenced by ``.duf``/``.dsf`` files, resolved against
   every content directory of the environment; unresolved ones are flagged broken.
5. **Thumbnails**: from a preview image (layer-provided or beside the file), an Unreal package's
   embedded thumbnail, the image itself, or a mesh render. Products without one use a child's.

Files are only read. Thumbnails are written to a cache folder beside the library database.
"""

from __future__ import annotations

import hashlib
import sqlite3
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from exchange.db import repository as repo
from exchange.definitions.schema import DefinitionSet
from exchange.paths import fold, is_within, os_path, to_path
from exchange.scanner import readonly, thumbnails
from exchange.scanner.formats import read_daz_file, uasset_thumbnail
from exchange.scanner.meshes import MeshError, finite, read_mesh

HASH_CHUNK = 1024 * 1024
MIN_DUPLICATE_SIZE = 64  # tiny files (empty, placeholder) say nothing about identity
MESH_EXTS = frozenset({".glb", ".gltf", ".obj"})
DAZ_EXTS = frozenset({".duf", ".dsf"})
THUMBNAIL_VERSION = 1  # bump to regenerate every thumbnail
_BATCH = 200


@dataclass
class EnrichStats:
    hashed: int = 0
    hash_errors: int = 0
    merged: int = 0
    meshes: int = 0
    mesh_errors: int = 0
    refined_types: int = 0
    dependencies: int = 0
    broken_dependencies: int = 0
    thumbnails: int = 0
    thumbnail_errors: int = 0
    cancelled: bool = False


def thumbnail_dir(db_path: Path) -> Path:
    return db_path.parent / "thumbnails"


def enrich_environment(
    conn: sqlite3.Connection,
    environment_id: int,
    *,
    definitions: DefinitionSet,
    db_path: Path,
    progress: Callable | None = None,
    cancel=None,
    name: str = "",
) -> EnrichStats:
    from exchange.scanner.scan import ProgressEvent

    stats = EnrichStats()
    env = repo.get_environment(conn, environment_id)
    definition = definitions.environments.get(env["type_id"])
    cache = thumbnail_dir(db_path)
    for root in repo.list_roots(conn, environment_id):
        if is_within(cache, Path(root["path"])):
            raise RuntimeError(f"thumbnail cache {cache} is inside scanned folder {root['path']}")

    def report(step: str, done: int, total: int) -> bool:
        if progress:
            progress(ProgressEvent(3, name or env["name"], step, done, total))
        if cancel is not None and cancel.is_set():
            stats.cancelled = True
        return stats.cancelled

    steps = [
        ("hashing", lambda: _hash_files(conn, environment_id, stats, report)),
        ("duplicates", lambda: _merge_duplicates(conn, stats, report)),
        ("meshes", lambda: _meshes(conn, environment_id, definitions, stats, report)),
        ("dependencies", lambda: _dependencies(conn, environment_id, stats, report)
         if definition is not None and definition.handler == "daz" else None),
        ("thumbnails", lambda: _thumbnails(conn, environment_id, cache, stats, report)),
    ]
    for _, step in steps:
        if stats.cancelled:
            break
        step()
    if not stats.cancelled:
        with repo.transaction(conn):
            repo.mark_scan_phase(conn, environment_id, 3)
    return stats


def _batches(conn: sqlite3.Connection, items: list, step: str, report, work) -> bool:
    """Run ``work(item)`` over items in transactions of _BATCH; False if cancelled."""
    total = len(items)
    for start in range(0, total, _BATCH):
        if report(step, start, total):
            return False
        with repo.transaction(conn):
            for item in items[start : start + _BATCH]:
                work(item)
    report(step, total, total)
    return True


# 1. Hashing -------------------------------------------------------------------------------------


def hash_file(path: Path) -> str:
    digest = hashlib.blake2b(digest_size=16)
    with open(os_path(path), "rb") as fh:
        while chunk := fh.read(HASH_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def _hash_files(conn, environment_id, stats, report) -> None:
    rows = repo.files_to_hash(conn, environment_id)

    def work(row) -> None:
        try:
            digest = hash_file(to_path(Path(row["root_path"]), row["rel_path"]))
        except OSError:
            stats.hash_errors += 1
            return
        repo.set_file_hash(conn, row["id"], digest)
        stats.hashed += 1

    _batches(conn, rows, "hashing", report, work)


# 2. Duplicates ----------------------------------------------------------------------------------


def _merge_duplicates(conn, stats, report) -> None:
    report("duplicates", 0, 1)
    groups: dict[str, list] = defaultdict(list)
    for row in repo.duplicate_groups(conn, MIN_DUPLICATE_SIZE):
        groups[row["hash"]].append(row)
    with repo.transaction(conn):
        for rows in groups.values():
            target = min(r["dossier_id"] for r in rows)
            for loser in sorted({r["dossier_id"] for r in rows} - {target}):
                uid = repo.dossier_uid(conn, loser)
                if repo.has_user_work(conn, uid) or repo.has_children(conn, loser):
                    continue  # the user's work is never merged away; curation decides
                for entry in repo.entries_of(conn, loser):
                    ledger_id = repo.ensure_ledger(conn, target, entry["environment_id"])
                    status = "unknown" if entry["status"] == "origin" else entry["status"]
                    repo.move_entry(conn, entry["id"], ledger_id, status, moved_from=uid)
                repo.delete_dossier(conn, loser)
                stats.merged += 1
            repo.index_dossiers(conn, [target])
    report("duplicates", 1, 1)


# 3. Meshes --------------------------------------------------------------------------------------


def _meshes(conn, environment_id, definitions, stats, report) -> None:
    rows = _first_primary_per_dossier(repo.live_primaries(conn, environment_id))
    rows = [r for r in rows if r["ext"] in MESH_EXTS and r["hash"]
            and r["type_id"] in definitions.dossier_types and definitions.is_a(r["type_id"], "mesh")]

    def work(row) -> None:
        if repo.scanned_field(conn, row["dossier_id"], "enriched_hash", "enrich:mesh") == row["hash"]:
            return
        try:
            mesh = read_mesh(to_path(Path(row["root_path"]), row["rel_path"]))
            fields = mesh.stats()
            if not finite(fields):
                raise MeshError("non-finite coordinates")
        except MeshError as exc:
            stats.mesh_errors += 1
            fields = {"mesh_error": str(exc)}
            mesh = None
        fields["enriched_hash"] = row["hash"]
        repo.replace_scanned_fields(conn, row["dossier_id"], "enrich:mesh", fields)
        stats.meshes += mesh is not None
        if mesh is not None and row["type_id"] == "mesh":
            refined = "skinned_mesh" if mesh.skinned else "static_mesh"
            repo.set_dossier_type(conn, row["dossier_id"], refined)
            stats.refined_types += 1

    _batches(conn, rows, "meshes", report, work)


def _first_primary_per_dossier(rows: list) -> list:
    seen: set[int] = set()
    out = []
    for row in rows:
        if row["dossier_id"] not in seen:
            seen.add(row["dossier_id"])
            out.append(row)
    return out


# 4. Daz dependencies ----------------------------------------------------------------------------


def _dependencies(conn, environment_id, stats, report) -> None:
    rows = [r for r in _first_primary_per_dossier(repo.live_primaries(conn, environment_id))
            if r["ext"] in DAZ_EXTS and r["hash"]]
    # Daz paths are relative to any content directory of the environment.
    files = {}
    for f in repo.present_files(conn, environment_id):
        files.setdefault(f["rel_key"], f["id"])
    owners = repo.file_owners(conn, environment_id)

    def work(row) -> None:
        source = "enrich:daz"
        refs = None
        if repo.scanned_field(conn, row["dossier_id"], "enriched_hash", source) == row["hash"]:
            refs = repo.scanned_field(conn, row["dossier_id"], "references", source)
        if refs is None:
            data = readonly.read_bytes(to_path(Path(row["root_path"]), row["rel_path"]),
                                       256 * 1024 * 1024)
            info = read_daz_file(data) if data else None
            refs = [r for r in (info.references if info else []) if fold(r) != row["rel_key"]]
            fields = dict(info.stats) if info else {"daz_parse_error": True}
            fields.update(enriched_hash=row["hash"], references=refs)
            repo.replace_scanned_fields(conn, row["dossier_id"], source, fields)
        deps = []
        for ref in refs:
            file_id = files.get(fold(ref))
            target = owners.get(file_id) if file_id is not None else None
            deps.append((ref, file_id, target if target != row["dossier_id"] else None))
        repo.replace_dependencies(conn, row["dossier_id"], deps)
        stats.dependencies += len(deps)
        stats.broken_dependencies += sum(1 for _, fid, _ in deps if fid is None)

    _batches(conn, rows, "dependencies", report, work)


# 5. Thumbnails ----------------------------------------------------------------------------------


def _thumbnails(conn, environment_id, cache: Path, stats, report) -> None:
    rows = _first_primary_per_dossier(repo.live_primaries(conn, environment_id))
    by_root: dict[int, dict[str, sqlite3.Row]] = defaultdict(dict)
    for f in repo.present_files(conn, environment_id):
        by_root[f["root_id"]][f["rel_key"]] = f

    def work(row) -> None:
        source = _thumbnail_source(conn, row, by_root[row["root_id"]])
        if source is None:
            return
        kind, file_row = source
        source_hash = f"{kind}:{file_row['hash']}:{THUMBNAIL_VERSION}"
        current = repo.thumbnail_row(conn, row["dossier_id"])
        if current is not None and current["source_hash"] == source_hash \
                and (cache / current["rel_path"]).exists():
            return
        try:
            path = to_path(Path(file_row["root_path"]), file_row["rel_path"])
            if kind == "render":
                img = thumbnails.render(read_mesh(path))
            else:
                data = readonly.read_bytes(path, 512 * 1024 * 1024) or b""
                if kind == "embedded":
                    data = uasset_thumbnail(data)
                    if data is None:
                        return  # a package saved without a thumbnail
                img = thumbnails.from_image_bytes(data)
        except (thumbnails.ThumbnailError, MeshError, OSError):
            stats.thumbnail_errors += 1
            return
        key = hashlib.blake2b(source_hash.encode(), digest_size=16).hexdigest()
        rel = thumbnails.save(img, cache, key)
        repo.set_thumbnail(conn, row["dossier_id"], rel_path=rel, source_kind=kind,
                           source_file_id=file_row["id"], source_hash=source_hash)
        stats.thumbnails += 1

    if not _batches(conn, rows, "thumbnails", report, work):
        return
    # Products (and anything else) without a thumbnail of their own borrow a child's.
    with repo.transaction(conn):
        for dossier_id in repo.live_dossier_ids(conn, environment_id):
            current = repo.thumbnail_row(conn, dossier_id)
            if current is not None and current["source_kind"] != "child":
                continue
            child = repo.child_thumbnail(conn, dossier_id)
            if child is not None:
                repo.set_thumbnail(conn, dossier_id, rel_path=child["rel_path"], source_kind="child",
                                   source_file_id=child["source_file_id"],
                                   source_hash=child["source_hash"])


def _thumbnail_source(conn, row, files: dict[str, sqlite3.Row]) -> tuple[str, sqlite3.Row] | None:
    """(kind, file row) of the best thumbnail source for a dossier's primary file."""
    def hashed(key: str) -> sqlite3.Row | None:
        f = files.get(key)
        return f if f is not None and f["hash"] else None

    preview = repo.scanned_field(conn, row["dossier_id"], "preview")
    if isinstance(preview, str) and (f := hashed(fold(preview))) is not None:
        return "preview", f
    rel = row["rel_key"]
    stem = rel.rsplit(".", 1)[0]
    for candidate in (f"{rel}.png", f"{stem}.png", f"{stem}.jpg", f"{stem}.jpeg", f"{stem}.tip.png"):
        if candidate != rel and (f := hashed(candidate)) is not None:
            return "preview", f
    own = hashed(rel)
    if own is None:
        return None
    if row["ext"] == ".uasset":
        return "embedded", own
    if row["ext"] in thumbnails.IMAGE_EXTS:
        return "image", own
    if row["ext"] in MESH_EXTS:
        return "render", own
    return None
