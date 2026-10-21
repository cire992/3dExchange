"""Run a scan: discovery, detection and split, then identification for each environment."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from exchange.db import open_library, open_library_readonly
from exchange.db import repository as repo
from exchange.definitions.schema import DefinitionSet
from exchange.errors import LibraryError, ScanError
from exchange.paths import fold, is_within
from exchange.scanner.detection import DetectedEnvironment, RegisteredEnvironment, detect
from exchange.scanner.discovery import discover
from exchange.scanner.identification import ARCHIVE_EXTS, IdentifyStats, identify_environment
from exchange.scanner.layers.base import FileInfo

DEFAULT_THRESHOLD = 0.5  # below this confidence a dossier goes to the Unidentified desk


@dataclass
class EnvironmentReport:
    name: str
    type_id: str
    root: str
    confidence: float
    signals: list[str]
    variant: str | None
    registered: bool
    files: int
    new: int = 0
    changed: int = 0
    unchanged: int = 0
    gone: int = 0
    identification: IdentifyStats | None = None


@dataclass
class ScanReport:
    folder: str
    db_path: str
    dry_run: bool
    threshold: float
    environments: list[EnvironmentReport] = field(default_factory=list)
    links_skipped: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def run_scan(
    folder: Path,
    *,
    db_path: Path,
    definitions: DefinitionSet,
    dry_run: bool = False,
    threshold: float = DEFAULT_THRESHOLD,
) -> ScanReport:
    folder = Path(folder)
    if not folder.is_dir():
        raise ScanError(f"not a folder: {folder}")
    folder = folder.resolve()
    db_path = Path(db_path).resolve()

    _refuse_db_inside(db_path, folder)
    report = ScanReport(str(folder), str(db_path), dry_run, threshold)
    # Read the known environments without writing; the database may not be migrated yet.
    registered: list[RegisteredEnvironment] = []
    try:
        peek = open_library_readonly(db_path)
    except LibraryError:
        if dry_run:
            raise
        peek = None  # an older schema: migrated below, read again after
    if peek is not None:
        registered = _registered(peek)
        peek.close()

    # Scanning inside a known environment rescans that whole environment, so files outside the
    # requested subfolder are not mistaken for deleted ones.
    containing = [r for r in registered if is_within(folder, r.root) and folder != r.root.resolve()]
    if containing:
        outer = min(containing, key=lambda r: len(r.root.parts))
        report.notes.append(f"{folder} is inside the environment at {outer.root}; scanning all of it")
        folder = outer.root.resolve()
        report.folder = str(folder)
        _refuse_db_inside(db_path, folder)

    conn = open_library_readonly(db_path) if dry_run else open_library(db_path)
    if conn is not None:
        registered = _registered(conn)
    try:
        discovery = discover(folder)
        report.links_skipped, report.errors = discovery.links, discovery.errors
        environments = detect(discovery, definitions, registered)
        for env in environments:
            env_report = EnvironmentReport(
                name=_environment_name(env), type_id=env.definition.id, root=str(env.root),
                confidence=env.confidence, signals=env.signals, variant=env.variant,
                registered=env.registered, files=len(env.files),
            )
            if not dry_run:
                _scan_environment(conn, env, env_report, definitions, threshold)
            report.environments.append(env_report)
    finally:
        if conn is not None:
            conn.close()
    return report


def _refuse_db_inside(db_path: Path, folder: Path) -> None:
    if is_within(db_path, folder):
        raise ScanError(
            f"refusing to scan {folder}: the library database {db_path} is inside it, and scans "
            "never write to a scanned folder; choose another location with --db"
        )


def _registered(conn: sqlite3.Connection) -> list[RegisteredEnvironment]:
    return [RegisteredEnvironment(Path(r["root_path"]), r["type_id"], r["detection_confidence"])
            for r in repo.list_environments(conn)]


def _environment_name(env: DetectedEnvironment) -> str:
    return f"{env.definition.name} ({env.root.name or env.root})"


def _scan_environment(conn: sqlite3.Connection, env: DetectedEnvironment, report: EnvironmentReport,
                      definitions: DefinitionSet, threshold: float) -> None:
    with repo.transaction(conn):
        row = repo.upsert_environment(
            conn, type_id=env.definition.id, name=report.name, root_path=str(env.root),
            root_key=fold(str(env.root)), variant=env.variant, confidence=env.confidence,
            signals=env.signals,
        )
        scan_id = repo.start_scan(conn, row["id"])

        # Phase 1: record files and what changed since the last scan.
        known = repo.load_files(conn, row["id"])
        present: list[FileInfo] = []
        for f in env.files:
            key = fold(f.rel)
            ext = "." + f.rel.rsplit(".", 1)[-1].lower() if "." in f.rel.rsplit("/", 1)[-1] else ""
            old = known.pop(key, None)
            if old is None:
                file_id = repo.insert_file(
                    conn, environment_id=row["id"], rel_path=f.rel, rel_key=key, ext=ext,
                    size=f.size, mtime_ns=f.mtime_ns, is_archive=ext in ARCHIVE_EXTS,
                    scan_id=scan_id,
                )
                report.new += 1
            else:
                file_id = old["id"]
                changed = (old["size"], old["mtime_ns"]) != (f.size, f.mtime_ns)
                if old["state"] == "gone":
                    report.new += 1
                elif changed:
                    report.changed += 1
                else:
                    report.unchanged += 1
                repo.update_file_seen(conn, file_id, rel_path=f.rel, size=f.size,
                                      mtime_ns=f.mtime_ns, scan_id=scan_id, changed=changed)
            present.append(FileInfo(file_id, f.rel, f.size, f.mtime_ns, ext))
        vanished = [r["id"] for r in known.values() if r["state"] != "gone"]
        repo.set_file_states(conn, vanished, "gone")
        report.gone = len(vanished)

        # Phase 2: identification.
        stats = identify_environment(
            conn, environment_id=row["id"], definition=env.definition,
            definitions=definitions, root=env.root, files=present, threshold=threshold,
        )
        report.identification = stats
        repo.finish_environment_scan(conn, row["id"], stats.layer_config)
        repo.finish_scan(conn, scan_id, phase=2, seen=len(present), new=report.new,
                         changed=report.changed, gone=report.gone)
