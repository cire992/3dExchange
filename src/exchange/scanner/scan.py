"""Run scans: discovery, detection and split, identification, then (optionally) enrichment.

An environment has one or more roots. ``run_scan`` scans a folder: every environment root found
in it is registered (several Daz content directories join one Daz Studio environment) and scanned.
``run_rescan`` rescans the roots the library already knows; a root whose folder is missing is
marked offline and its entries are kept.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from exchange.db import open_library, open_library_readonly
from exchange.db import repository as repo
from exchange.definitions.schema import DefinitionSet, EnvironmentDefinition
from exchange.errors import LibraryError, ScanError
from exchange.paths import fold, is_within
from exchange.scanner.detection import DetectedEnvironment, RegisteredEnvironment, detect
from exchange.scanner.discovery import discover
from exchange.scanner.identification import ARCHIVE_EXTS, IdentifyStats, identify_root
from exchange.scanner.layers.base import FileInfo

DEFAULT_THRESHOLD = 0.5  # below this confidence a dossier goes to the Unidentified desk
OFFLINE_PROMPT_DAYS = 30  # an offline root this old is worth asking the user about


@dataclass
class ProgressEvent:
    phase: int  # 1 discovery, 2 identification, 3 enrichment
    environment: str
    step: str  # e.g. "discovery", "hashing", "thumbnails"
    done: int = 0
    total: int = 0


Progress = Callable[[ProgressEvent], None]


class Cancel(Protocol):
    def is_set(self) -> bool: ...


@dataclass
class RootReport:
    path: str
    confidence: float
    signals: list[str]
    variant: str | None
    registered: bool
    status: str = "scanned"  # scanned, detected (dry run), offline
    files: int = 0
    new: int = 0
    changed: int = 0
    unchanged: int = 0
    gone: int = 0
    offline_days: int | None = None
    identification: IdentifyStats | None = None


@dataclass
class EnvironmentReport:
    id: int | None
    name: str
    type_id: str
    roots: list[RootReport] = field(default_factory=list)
    enrichment: object | None = None  # EnrichStats

    @property
    def registered(self) -> bool:
        return any(r.registered for r in self.roots)


@dataclass
class ScanReport:
    folder: str | None
    db_path: str
    dry_run: bool
    threshold: float
    environments: list[EnvironmentReport] = field(default_factory=list)
    links_skipped: list[str] = field(default_factory=list)
    excluded: list[str] = field(default_factory=list)  # folders skipped because the user excluded them
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    cancelled: bool = False
    classification: object | None = None  # ClassifyStats
    suggestions: dict | None = None  # new suggestions by kind


def run_scan(
    folder: Path,
    *,
    db_path: Path,
    definitions: DefinitionSet,
    dry_run: bool = False,
    threshold: float = DEFAULT_THRESHOLD,
    enrich: bool = False,
    progress: Progress | None = None,
    cancel: Cancel | None = None,
) -> ScanReport:
    folder = Path(folder)
    if not folder.is_dir():
        raise ScanError(f"not a folder: {folder}")
    folder = folder.resolve()
    db_path = Path(db_path).resolve()
    _refuse_db_inside(db_path, folder)
    requested = folder
    report = ScanReport(str(folder), str(db_path), dry_run, threshold)

    # Scanning inside a known root rescans that whole root, so files outside the requested
    # subfolder are not mistaken for deleted ones.
    registered = _peek_registered(db_path, dry_run)
    containing = [r for r in registered if is_within(folder, r.root) and folder != r.root.resolve()]
    if containing:
        outer = min(containing, key=lambda r: len(r.root.parts))
        report.notes.append(f"{folder} is inside the environment root {outer.root}; scanning all of it")
        folder = outer.root.resolve()
        report.folder = str(folder)
        _refuse_db_inside(db_path, folder)

    conn = open_library_readonly(db_path) if dry_run else open_library(db_path)
    if conn is not None and not dry_run:
        from exchange.environments import excluded_roots, set_excluded

        if any(fold(p) == fold(str(requested)) for p in excluded_roots(conn)):
            with repo.transaction(conn):
                set_excluded(conn, requested, False)  # scanning it by name means it is wanted again
            report.notes.append(f"{requested} was excluded; it is included again")
    try:
        session = _Session(conn, definitions, report, dry_run, threshold, progress, cancel)
        session.scan_folder(folder)
        if not dry_run and not report.cancelled:
            session.classify()
        if enrich and not dry_run and not report.cancelled:
            session.enrich()
    finally:
        if conn is not None:
            conn.close()
    return report


def run_rescan(
    *,
    db_path: Path,
    definitions: DefinitionSet,
    environment_ids: Iterable[int] | None = None,
    threshold: float = DEFAULT_THRESHOLD,
    enrich: bool = False,
    progress: Progress | None = None,
    cancel: Cancel | None = None,
) -> ScanReport:
    """Rescan known roots (all of them, or those of some environments). Incremental."""
    db_path = Path(db_path).resolve()
    report = ScanReport(None, str(db_path), False, threshold)
    conn = open_library(db_path)
    try:
        wanted = set(environment_ids) if environment_ids is not None else None
        unknown = (wanted or set()) - {e["id"] for e in repo.list_environments(conn)}
        if unknown:
            raise ScanError(f"no environment with id {', '.join(map(str, sorted(unknown)))}")
        session = _Session(conn, definitions, report, False, threshold, progress, cancel)
        for root in repo.list_roots(conn):
            if wanted is not None and root["environment_id"] not in wanted:
                continue
            if report.cancelled:
                break
            path = Path(root["path"])
            if path.is_dir():
                if any(is_within(path, Path(f)) for f in session.scanned_folders):
                    continue  # already covered by an enclosing root scanned above
                session.scan_folder(path)
            else:
                session.mark_offline(root)
        if not report.cancelled:
            session.classify()
        if enrich and not report.cancelled:
            session.enrich()
    finally:
        conn.close()
    return report


def regroup(conn: sqlite3.Connection, definitions: DefinitionSet, *,
            environment_ids: Iterable[int] | None = None, threshold: float = DEFAULT_THRESHOLD) -> int:
    """Re-run identification on the files already recorded, without walking the disk.

    For lexicon edits that change how files group into products (category and vendor folders).
    Roots that are offline are skipped. Returns the number of roots regrouped.
    """
    wanted = set(environment_ids) if environment_ids is not None else None
    count = 0
    for root in repo.list_roots(conn):
        if wanted is not None and root["environment_id"] not in wanted:
            continue
        path = Path(root["path"])
        if not path.is_dir():
            continue  # manifests are read from disk
        env = repo.get_environment(conn, root["environment_id"])
        definition = definitions.environments.get(env["type_id"])
        if definition is None:
            continue
        present = [FileInfo(r["id"], r["rel_path"], r["size"], r["mtime_ns"], r["ext"])
                   for r in repo.load_files(conn, root["id"]).values() if r["state"] != "gone"]
        identify_root(
            conn, environment_id=env["id"], root_id=root["id"], definition=definition,
            definitions=definitions, root=path, files=present,
            user_ignore=tuple(repo.user_config(conn, env["id"]).get("ignore", ())), threshold=threshold)
        count += 1
    return count


def _peek_registered(db_path: Path, dry_run: bool) -> list[RegisteredEnvironment]:
    """Known roots, read without writing (the database may not be migrated yet)."""
    try:
        conn = open_library_readonly(db_path)
    except LibraryError:
        if dry_run:
            raise
        return []  # an older schema: migrated when opened for writing, read again then
    if conn is None:
        return []
    try:
        return _registered(conn)
    finally:
        conn.close()


def _registered(conn: sqlite3.Connection) -> list[RegisteredEnvironment]:
    return [RegisteredEnvironment(Path(r["path"]), r["type_id"], r["detection_confidence"])
            for r in repo.list_roots(conn)]


def _refuse_db_inside(db_path: Path, folder: Path) -> None:
    if is_within(db_path, folder):
        raise ScanError(
            f"refusing to scan {folder}: the library database {db_path} is inside it, and scans "
            "never write to a scanned folder; choose another location with --db"
        )


def environment_name(definition: EnvironmentDefinition, root: Path) -> str:
    if definition.multi_root:
        return definition.name
    return f"{definition.name} ({root.name or root})"


class _Session:
    def __init__(self, conn: sqlite3.Connection | None, definitions: DefinitionSet,
                 report: ScanReport, dry_run: bool, threshold: float,
                 progress: Progress | None, cancel: Cancel | None) -> None:
        self.conn, self.definitions, self.report = conn, definitions, report
        self.dry_run, self.threshold = dry_run, threshold
        self.progress = progress or (lambda event: None)
        self.cancel = cancel
        self.scanned_folders: list[str] = []
        self.scanned_roots: list[int] = []  # classification and suggestions look only at these
        self._envs: dict[object, EnvironmentReport] = {}
        from exchange.environments import excluded_roots

        self.excluded = excluded_roots(conn) if conn is not None else []

    def cancelled(self) -> bool:
        if self.cancel is not None and self.cancel.is_set():
            self.report.cancelled = True
        return self.report.cancelled

    def _env_report(self, key: object, env_id: int | None, name: str, type_id: str) -> EnvironmentReport:
        if key not in self._envs:
            self._envs[key] = EnvironmentReport(env_id, name, type_id)
            self.report.environments.append(self._envs[key])
        return self._envs[key]

    # Phases 1 and 2 ---------------------------------------------------------------------------

    def scan_folder(self, folder: Path) -> None:
        self.scanned_folders.append(str(folder))
        self.progress(ProgressEvent(1, str(folder), "discovery"))
        registered = _registered(self.conn) if self.conn is not None else []
        discovery = discover(folder, self.excluded)
        self.report.links_skipped += [str(folder / l) for l in discovery.links]
        self.report.excluded += [str(folder / x) for x in discovery.excluded]
        self.report.errors += discovery.errors
        for det in detect(discovery, self.definitions, registered):
            if self.cancelled():
                return
            root_report = RootReport(str(det.root), det.confidence, det.signals, det.variant,
                                     det.registered, files=len(det.files))
            if self.dry_run:
                root_report.status = "detected"
                key, env_id, name = self._dry_run_group(det)
                self._env_report(key, env_id, name, det.definition.id).roots.append(root_report)
            else:
                self._scan_root(det, root_report)

    def _dry_run_group(self, det: DetectedEnvironment) -> tuple[object, int | None, str]:
        known = repo.find_root(self.conn, fold(str(det.root))) if self.conn is not None else None
        if known is not None:
            env = repo.get_environment(self.conn, known["environment_id"])
            return env["id"], env["id"], env["name"]
        if det.definition.multi_root:
            return det.definition.id, None, det.definition.name
        return str(det.root), None, environment_name(det.definition, det.root)

    def _environment_for(self, det: DetectedEnvironment) -> sqlite3.Row:
        conn = self.conn
        known = repo.find_root(conn, fold(str(det.root)))
        if known is not None:
            return repo.get_environment(conn, known["environment_id"])
        if det.definition.multi_root:
            row = conn.execute("SELECT * FROM environment WHERE type_id = ? ORDER BY id LIMIT 1",
                               (det.definition.id,)).fetchone()
            if row is not None:
                return row
        env_id = repo.create_environment(conn, type_id=det.definition.id,
                                         name=environment_name(det.definition, det.root))
        return repo.get_environment(conn, env_id)

    def _scan_root(self, det: DetectedEnvironment, report: RootReport) -> None:
        conn = self.conn
        with repo.transaction(conn):
            env = self._environment_for(det)
            definition = self.definitions.environments.get(env["type_id"], det.definition)
            env_report = self._env_report(env["id"], env["id"], env["name"], env["type_id"])
            env_report.roots.append(report)
            root_id = repo.upsert_root(
                conn, env["id"], path=str(det.root), root_key=fold(str(det.root)),
                variant=det.variant, confidence=det.confidence, signals=det.signals)
            self.scanned_roots.append(root_id)
            scan_id = repo.start_scan(conn, env["id"], root_id)
            present = self._sync_files(env["id"], root_id, scan_id, det, report)

            self.progress(ProgressEvent(2, env["name"], "identification"))
            config = repo.user_config(conn, env["id"])
            stats = identify_root(
                conn, environment_id=env["id"], root_id=root_id, definition=definition,
                definitions=self.definitions, root=det.root, files=present,
                user_ignore=tuple(config.get("ignore", ())), threshold=self.threshold,
            )
            report.identification = stats
            repo.finish_root_scan(conn, root_id, env["id"], stats.layer_config)
            repo.finish_scan(conn, scan_id, phase=2, seen=len(present), new=report.new,
                             changed=report.changed, gone=report.gone,
                             unattached=stats.unattached_files)

    def _sync_files(self, environment_id: int, root_id: int, scan_id: int,
                    det: DetectedEnvironment, report: RootReport) -> list[FileInfo]:
        """Phase 1: record files and what changed since the last scan of this root."""
        conn = self.conn
        known = repo.load_files(conn, root_id)
        present: list[FileInfo] = []
        for f in det.files:
            key = fold(f.rel)
            name = f.rel.rsplit("/", 1)[-1]
            ext = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
            old = known.pop(key, None)
            if old is None:
                file_id = repo.insert_file(
                    conn, environment_id=environment_id, root_id=root_id, rel_path=f.rel,
                    rel_key=key, ext=ext, size=f.size, mtime_ns=f.mtime_ns,
                    is_archive=ext in ARCHIVE_EXTS, scan_id=scan_id)
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
        return present

    def mark_offline(self, root: sqlite3.Row) -> None:
        with repo.transaction(self.conn):
            since = repo.set_root_offline(self.conn, root["id"])
        env = repo.get_environment(self.conn, root["environment_id"])
        days = (datetime.now(timezone.utc) - datetime.fromisoformat(since)).days
        env_report = self._env_report(env["id"], env["id"], env["name"], env["type_id"])
        env_report.roots.append(RootReport(
            root["path"], root["detection_confidence"], [], root["variant"], True,
            status="offline", offline_days=days))
        if days >= OFFLINE_PROMPT_DAYS:
            self.report.notes.append(
                f"{root['path']} has been offline for {days} days; if it is gone for good, "
                f"run: exchange env forget {env['id']}")

    # End of phase 2: classification and suggestions ---------------------------------------------

    def classify(self) -> None:
        from exchange.scanner.classify import classify
        from exchange.suggestions import generate

        ids = [e.id for e in self.report.environments
               if e.id is not None and any(r.status == "scanned" for r in e.roots)]
        if not ids:
            return
        self.progress(ProgressEvent(2, "library", "classification"))
        with repo.transaction(self.conn):
            self.report.classification = classify(self.conn, self.definitions, environment_ids=ids,
                                                  root_ids=self.scanned_roots)
            self.report.suggestions = generate(self.conn, self.definitions, environment_ids=ids,
                                               root_ids=self.scanned_roots)

    # Phase 3 ----------------------------------------------------------------------------------

    def enrich(self) -> None:
        from exchange.scanner.enrichment import enrich_environment

        for env_report in self.report.environments:
            if env_report.id is None or self.cancelled():
                continue
            if all(r.status == "offline" for r in env_report.roots):
                continue
            env_report.enrichment = enrich_environment(
                self.conn, env_report.id, definitions=self.definitions,
                db_path=Path(self.report.db_path), progress=self.progress, cancel=self.cancel,
                name=env_report.name)
            if env_report.enrichment.cancelled:
                self.report.cancelled = True
