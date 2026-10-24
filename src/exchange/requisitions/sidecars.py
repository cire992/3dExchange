"""Sidecar manifests: what a requisition wrote into a container, written next to it.

Each output container gets ``.exchange/<requisition uid>.json`` listing, per converted asset,
its dossier (uid, name, type), the entry it came from, the processes and options used, and the
files written (relative to the container folder). Scans read them back (``read_sidecars`` and
``apply_sidecars``, called from identification): the files join the source asset's dossier as a
*requisitioned* (or *copied*) entry instead of becoming new dossiers. Because the record lives
on disk, a lost library is rebuilt from sidecars plus a rescan.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from exchange.db import repository as repo
from exchange.globs import glob_match
from exchange.paths import fold

FORMAT = 1
FOLDER = ".exchange"
SIDECAR_GLOB = f"**/{FOLDER}/*.json"


@dataclass
class SidecarOutput:
    index: int
    dossier: str
    name: str
    type_id: str
    status: str
    source_entry: int | None
    rels: list[str]  # root-relative paths of the files written


@dataclass
class Sidecar:
    rel: str  # the sidecar's own root-relative path
    requisition: str  # uid
    outputs: list[SidecarOutput]


def write_sidecar(folder: Path, data: dict) -> Path:
    """Write (or replace) one requisition's sidecar in a container folder."""
    path = Path(folder) / FOLDER / f"{data['requisition']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"format": FORMAT, "kind": "exchange-requisition", **data}, indent=2,
                               ensure_ascii=False), encoding="utf-8")
    return path


def is_sidecar(rel: str) -> bool:
    return glob_match(SIDECAR_GLOB, rel)


def read_sidecars(root: Path, rels: list[str]) -> list[Sidecar]:
    """The sidecars among a root's files (``rels``), with their outputs' root-relative paths.
    Unreadable or foreign files are skipped: a sidecar only ever adds entries."""
    from exchange.scanner.readonly import read_bytes

    found = []
    for rel in rels:
        if not is_sidecar(rel):
            continue
        try:
            data = json.loads((read_bytes(root.joinpath(*rel.split("/"))) or b"").decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            continue
        if not isinstance(data, dict) or data.get("kind") != "exchange-requisition" or data.get("format") != FORMAT:
            continue
        container = rel.rsplit("/", 2)[0] if rel.count("/") >= 2 else ""
        outputs = []
        for index, out in enumerate(data.get("outputs", [])):
            try:
                files = [f"{container}/{f}" if container else f for f in out["files"]]
                outputs.append(SidecarOutput(index, out["dossier"], out.get("name") or "Exchange output",
                                             out.get("type_id") or "product", out.get("status", "requisitioned"),
                                             (out.get("source") or {}).get("entry"), files))
            except (KeyError, TypeError):
                continue
        found.append(Sidecar(rel, str(data.get("requisition", "")), outputs))
    return found


def sidecar_keys(sidecars: list[Sidecar]) -> set[str]:
    """Folded root-relative paths of every file sidecars account for."""
    return {fold(rel) for s in sidecars for o in s.outputs for rel in o.rels}


def apply_sidecars(conn: sqlite3.Connection, environment_id: int, sidecars: list[Sidecar], by_key: dict,
                   container_of: dict[int, int | None], known_types: set[str]) -> tuple[set[int], set[int]]:
    """Make (or keep) one entry per sidecar output on its source dossier. Returns the entry ids
    seen and the dossier ids touched (for the search index).

    ``by_key`` maps folded root-relative paths to files; ``container_of`` maps file ids to
    container ids. A dossier the library no longer has (a lost database) is made again from
    the sidecar, with its original uid.
    """
    seen: set[int] = set()
    dossiers: set[int] = set()
    for sidecar in sidecars:
        row = conn.execute("SELECT id FROM requisition WHERE uid = ?", (sidecar.requisition,)).fetchone()
        requisition_id = row[0] if row else None
        for out in sidecar.outputs:
            files = [by_key[fold(rel)] for rel in out.rels if fold(rel) in by_key]
            if not files:
                continue  # removed from disk: the entry retires like any other
            container_id = container_of.get(files[0].id)
            if container_id is None:
                continue
            dossier_id = _dossier(conn, out, known_types)
            key = f"requisition:{sidecar.requisition}:{out.index}"
            existing = repo.find_entry(conn, container_id, key)
            if existing is None:
                ledger_id = repo.ensure_ledger(conn, dossier_id, environment_id)
                entry_id = repo.create_entry(conn, ledger_id=ledger_id, container_id=container_id,
                                             identity_key=key, status=out.status)
                source = out.source_entry if out.source_entry is not None and conn.execute(
                    "SELECT 1 FROM entry WHERE id = ?", (out.source_entry,)).fetchone() else None
                conn.execute("UPDATE entry SET requisition_id = ?, source_entry_id = ?, moved_from = 'requisition'"
                             " WHERE id = ?", (requisition_id, source, entry_id))
            else:
                entry_id = existing["id"]
                if existing["status"] == "retired":
                    repo.revive_entry(conn, entry_id, out.status)
            repo.replace_entry_files(conn, entry_id, [(f.id, "primary" if i == 0 else "support")
                                                      for i, f in enumerate(files)])
            seen.add(entry_id)
            dossiers.add(dossier_id)
    return seen, dossiers


def _dossier(conn: sqlite3.Connection, out: SidecarOutput, known_types: set[str]) -> int:
    uid = out.dossier
    alias = conn.execute("SELECT target_uid FROM dossier_alias WHERE alias_uid = ?", (uid,)).fetchone()
    if alias is not None:
        uid = alias[0]  # merged into another since
    row = conn.execute("SELECT id FROM dossier WHERE uid = ?", (uid,)).fetchone()
    if row is not None:
        return row[0]
    return repo.create_dossier(conn, type_id=out.type_id if out.type_id in known_types else "product",
                               name=out.name, parent_id=None, confidence=1.0,
                               signals=["Exchange requisition output (sidecar)"], uid=uid)
