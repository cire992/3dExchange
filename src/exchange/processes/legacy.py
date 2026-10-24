"""One-time move of a data folder from before the rename of pipelines to processes (2026-10).

Before the rename, user packages lived in ``<data>/pipelines/<id>/pipeline.toml`` with a
``[pipeline]`` table, and ``<data>/pipelines/trusted.json`` held each trusted package's
fingerprint. The move:

1. converts each package in place: ``pipeline.toml`` becomes ``process.toml`` and its
   ``[pipeline]`` table becomes ``[process]``, and its Python files' imports of
   ``exchange.pipelines`` (the SDK's old name) become ``exchange.processes``; nothing else changes;
2. keeps a package trusted only if it was trusted for exactly its files before the move (its old
   fingerprint matches); its trust is then recorded for the converted files, since the only
   changes are Exchange's own renames. A package changed since it was trusted stays untrusted;
3. renames the folder to ``<data>/processes`` in one step, so another Exchange process sees either
   the old folder or the finished new one.

It is idempotent: an interrupted move picks up where it stopped. Tool paths (``tools.json``),
presets and last-used options are keyed by tool or process id and need no change. The database's
part of the rename is migration ``0007_processes.sql``. Requisition sidecars inside environments
are never rewritten; scans read only their dossiers, names and files.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import tomllib
from pathlib import Path

from exchange.locks import Lock, LockBusy

OLD_FOLDER, NEW_FOLDER = "pipelines", "processes"
OLD_MANIFEST, NEW_MANIFEST = "pipeline.toml", "process.toml"
_TABLE = re.compile(rb"^\[pipeline\][ \t]*(?=\r?\n|$)", re.MULTILINE)
_IMPORT = re.compile(rb"\bexchange\.pipelines\b")


def package_fingerprint(path: Path, manifest_name: str) -> str:
    """The trust fingerprint (registry.fingerprint) of a package whose manifest has this name."""
    digest = hashlib.sha256()
    operations = path / "operations"
    files = [path / manifest_name, *sorted(operations.rglob("*.py"))] if operations.is_dir() else [path / manifest_name]
    for file in files:
        digest.update(file.relative_to(path).as_posix().encode())
        digest.update(file.read_bytes())
    return digest.hexdigest()


def _convert_package(package: Path, trusted: dict[str, str], notes: list[str]) -> None:
    old = package / OLD_MANIFEST
    if not old.is_file():
        return  # already converted (an interrupted move), or not a package
    raw = old.read_bytes()
    try:
        package_id = tomllib.loads(raw.decode("utf-8"))["pipeline"]["id"]
    except (UnicodeDecodeError, tomllib.TOMLDecodeError, KeyError, TypeError):
        package_id = package.name
    was_trusted = trusted.get(package_id) == package_fingerprint(package, OLD_MANIFEST)
    # Its code imported the SDK as exchange.pipelines; that is Exchange's own rename too.
    for source in sorted(package.rglob("*.py")):
        code = source.read_bytes()
        if _IMPORT.search(code):
            source.write_bytes(_IMPORT.sub(b"exchange.processes", code))
    (package / NEW_MANIFEST).write_bytes(_TABLE.sub(b"[process]", raw, count=1))
    old.unlink()
    if was_trusted:
        trusted[package_id] = package_fingerprint(package, NEW_MANIFEST)
        notes.append(f"{package_id}: converted, still trusted")
    else:
        if trusted.pop(package_id, None) is not None:
            notes.append(f"{package_id}: converted; it had changed since it was trusted, so it stays untrusted")
        else:
            notes.append(f"{package_id}: converted (not trusted)")


def migrate_data_folder(data: Path, *, wait: float = 15.0) -> list[str]:
    """Move ``data/pipelines`` to ``data/processes``; returns what happened, one line per package."""
    old, new = data / OLD_FOLDER, data / NEW_FOLDER
    if new.exists() or not old.is_dir():
        return []
    lock = Lock("rename-processes", data / "locks")
    deadline = time.monotonic() + wait
    while True:
        try:
            lock.acquire()
            break
        except LockBusy:
            if time.monotonic() > deadline:
                raise
            time.sleep(0.2)
    try:
        if new.exists() or not old.is_dir():
            return []  # another Exchange process finished it while this one waited
        notes: list[str] = []
        trust_file = old / "trusted.json"
        try:
            trusted = json.loads(trust_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            trusted = {}
        for package in sorted(p for p in old.iterdir() if p.is_dir()):
            _convert_package(package, trusted, notes)
        if trust_file.exists() or trusted:
            trust_file.write_text(json.dumps(trusted, indent=2), encoding="utf-8")
        os.replace(old, new)
        return notes
    finally:
        lock.release()
