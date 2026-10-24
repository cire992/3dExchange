"""Validating a project home: every file against its format, and every link resolved.

Validation reads the files directly (there is no project index yet) and reports:

* **findings:** errors (the file breaks its format, or claims a maturity its fields do not meet)
  and warnings (unknown fields, links to things that cannot be checked, unfiled ideas);
* **gaps:** links that need work on another record, or a dossier link that broke. A record at Spec
  or above needs each record it links to at no less than the lower of its own maturity and the
  field's cap (``max_demand``, Spec by default); links from Sketch records are not checked. Gap
  claims are opened from these (Roadmap phase 7b).

Dossier links are resolved read-only against the library database, following merges
(``dossier_alias``). Each linked dossier's description (name, type, environment, product key, path,
hash) is kept as a hint in ``.exchange/dossier-hints.json``; when a link breaks, its hint finds the
candidates to relink to.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import sqlite3
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from exchange.errors import LibraryError
from exchange.projects import frontmatter
from exchange.projects.home import MARKER, ProjectHome, manifest_problems
from exchange.projects.schema import (
    COMMON_FIELDS, EDITOR_ID, LEVELS, SIGNATURE, Field, RecordType, level_name, load_schemas, maturity_value,
    signature_of,
)

CLAIM_STATUSES = ("idea", "open", "claimed", "review", "done", "dropped")
CLAIM_SOURCES = ("manual", "gap", "ladder", "coverage", "mining")
CLAIM_ID = re.compile(r"^(\d{4}-\d{2}-\d{2})-[a-z0-9]+(?:-[a-z0-9]+)*$")
CLAIM_KEYS = {"id", "title", "status", "created", "target", "domain", "goal", "source", "needed_by",
              "claimed_by", "triage", "links", "needs", "gap"}
GOAL_ID = re.compile(r"^G\d+$")
GOAL_STATUSES = ("planned", "active", "done", "dropped")
RULE_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
IDENTITY_SECTIONS = ("Premise", "Pillars", "Feel", "Boundaries", "Amendment log")
LINK_PREFIXES = ("claim", "goal", "dossier", "process", "decision", "session", "domain")


@dataclass
class Finding:
    severity: str  # "error" or "warning"
    path: str  # relative to the project home
    message: str
    subject: str | None = None  # the record's editor ID or the claim's ID
    field: str | None = None


@dataclass
class Gap:
    """Work one record needs from another, or a broken dossier link."""

    kind: str  # "missing" or "immature" (a record), "dossier" (a dossier link)
    target: str  # the record the work is on (for a dossier gap, the record holding the link)
    needed_by: str
    field: str
    message: str
    required: int | None = None  # the maturity the target needs
    current: int | None = None  # the target's maturity, when it exists
    dossier: str | None = None
    dossier_state: str | None = None  # "missing" or "retired"
    candidates: list[dict] = field(default_factory=list)  # dossiers that may be the same asset

    @property
    def work(self) -> str:
        """What the gap's claim asks for: "relink" a dossier, or "mature" a record."""
        return "relink" if self.kind == "dossier" else "mature"


@dataclass
class Record:
    id: str
    signature: str
    maturity: int | None
    meta: dict[str, Any]
    body: str
    path: str


@dataclass
class Claim:
    id: str
    meta: dict[str, Any]
    body: str
    path: str


@dataclass
class Report:
    home: ProjectHome
    records: dict[str, Record] = field(default_factory=dict)  # by case-folded editor ID
    claims: dict[str, Claim] = field(default_factory=dict)
    goals: dict[str, dict] = field(default_factory=dict)
    schemas: dict[str, RecordType] = field(default_factory=dict)
    findings: list[Finding] = field(default_factory=list)
    gaps: list[Gap] = field(default_factory=list)
    dossiers_checked: bool = False  # False when there was no library to resolve dossier links in
    dossier_hints: dict[str, dict] = field(default_factory=dict)  # every linked uid's description

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "error"]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "warning"]

    def record(self, editor_id: str) -> Record | None:
        return self.records.get(editor_id.casefold())

    def to_json(self) -> dict:
        return {
            "project": {"path": str(self.home.path), "name": self.home.name, "kind": self.home.kind},
            "counts": {"records": len(self.records), "claims": len(self.claims), "goals": len(self.goals),
                       "errors": len(self.errors), "warnings": len(self.warnings), "gaps": len(self.gaps)},
            "findings": [asdict(f) for f in self.findings],
            "gaps": [asdict(g) for g in self.gaps],
        }


def _empty(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


class DossierIndex:
    """Resolves dossier uids against the library, read-only. Without a library nothing is checked."""

    def __init__(self, db_path: Path | None) -> None:
        self.conn: sqlite3.Connection | None = None
        self.problem: str | None = None
        if db_path is None:
            self.problem = "no library database given"
            return
        if not db_path.exists():
            self.problem = f"no library database at {db_path}"
            return
        try:
            from exchange.db import open_library_readonly
            self.conn = open_library_readonly(db_path)
        except LibraryError as exc:
            self.problem = str(exc)

    def resolve(self, uid: str) -> tuple[str, str]:
        """(state, uid): state is "ok", "merged" (uid is where it went), "retired", "missing" or
        "unchecked"."""
        if self.conn is None:
            return "unchecked", uid
        current, merged = uid, False
        for _ in range(16):  # merges chain; a loop would be a bug, not a reason to hang
            row = self.conn.execute("SELECT target_uid FROM dossier_alias WHERE alias_uid = ?", (current,)).fetchone()
            if row is None:
                break
            current, merged = row[0], True
        row = self.conn.execute("SELECT id FROM dossier WHERE uid = ?", (current,)).fetchone()
        if row is None:
            return "missing", current
        entries = self.conn.execute(
            "SELECT count(*), sum(e.status != 'retired') FROM entry e JOIN ledger l ON l.id = e.ledger_id"
            " WHERE l.dossier_id = ?", (row[0],)).fetchone()
        if entries[0] and not entries[1]:
            return "retired", current
        return ("merged" if merged else "ok"), current

    def describe(self, uid: str) -> dict | None:
        """What a dossier is and where it lives, to find it again if its uid stops resolving."""
        if self.conn is None:
            return None
        row = self.conn.execute("SELECT id, name, type_id FROM dossier_effective WHERE uid = ?", (uid,)).fetchone()
        if row is None:
            return None
        hint: dict[str, Any] = {"name": row[1], "type": row[2]}
        key = self.conn.execute("SELECT value FROM dossier_field WHERE dossier_id = ? AND field = 'product_key'",
                                (row[0],)).fetchone()
        if key is not None:
            hint["product_key"] = json.loads(key[0])
        place = self.conn.execute(
            "SELECT env.name, r.path, f.rel_path, f.hash, f.size FROM entry e"
            " JOIN ledger l ON l.id = e.ledger_id JOIN environment env ON env.id = l.environment_id"
            " JOIN entry_file ef ON ef.entry_id = e.id JOIN file f ON f.id = ef.file_id"
            " JOIN environment_root r ON r.id = f.root_id"
            " WHERE l.dossier_id = ? ORDER BY e.status = 'retired', ef.role != 'primary', e.id LIMIT 1",
            (row[0],)).fetchone()
        if place is not None:
            hint.update(environment=place[0], path=str(Path(place[1]) / place[2]), size=place[4])
            if place[3]:
                hint["hash"] = place[3]
        return hint

    def candidates(self, hint: dict, exclude: str, limit: int = 5) -> list[dict]:
        """Live dossiers matching a hint: the same file (hash), product key, or name and type."""
        if self.conn is None or not hint:
            return []
        queries = []
        if hint.get("hash"):
            queries.append(("the same file", "SELECT DISTINCT l.dossier_id FROM file f"
                            " JOIN entry_file ef ON ef.file_id = f.id JOIN entry e ON e.id = ef.entry_id"
                            " JOIN ledger l ON l.id = e.ledger_id WHERE f.hash = ? AND f.state = 'present'",
                            (hint["hash"],)))
        if hint.get("product_key"):
            queries.append(("the same product key", "SELECT dossier_id FROM dossier_field"
                            " WHERE field = 'product_key' AND value = ?", (json.dumps(hint["product_key"]),)))
        if hint.get("name") and hint.get("type"):
            queries.append(("the same name and type", "SELECT id FROM dossier WHERE name = ? COLLATE NOCASE"
                            " AND type_id = ?", (hint["name"], hint["type"])))
        found: dict[str, str] = {}
        for why, sql, args in queries:
            for (dossier_id,) in self.conn.execute(sql, args).fetchall():
                row = self.conn.execute(
                    "SELECT d.uid FROM dossier d WHERE d.id = ? AND NOT EXISTS"
                    " (SELECT 1 FROM dossier_alias a WHERE a.alias_uid = d.uid) AND EXISTS"
                    " (SELECT 1 FROM entry e JOIN ledger l ON l.id = e.ledger_id"
                    "  WHERE l.dossier_id = d.id AND e.status != 'retired')", (dossier_id,)).fetchone()
                if row is not None and row[0] != exclude and row[0] not in found:
                    found[row[0]] = why
        result = []
        for uid, why in list(found.items())[:limit]:
            described = self.describe(uid) or {}
            result.append({"uid": uid, "why": why,
                           **{k: described[k] for k in ("name", "type", "environment", "path") if k in described}})
        return result

    def close(self) -> None:
        if self.conn is not None:
            self.conn.close()


HINTS_FILE = "dossier-hints.json"


def read_hints(home: ProjectHome) -> dict[str, dict]:
    try:
        hints = json.loads((home.cache_dir / HINTS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return hints if isinstance(hints, dict) else {}


def write_hints(home: ProjectHome, hints: dict[str, dict]) -> None:
    """Keep the hints of the dossiers linked now (``.exchange/`` is never committed)."""
    home.cache_dir.mkdir(exist_ok=True)
    path = home.cache_dir / HINTS_FILE
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(hints, indent=1, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    temp.replace(path)


class _Validator:
    def __init__(self, home: ProjectHome, db_path: Path | None, processes: set[str] | None) -> None:
        self.home = home
        self.report = Report(home)
        self.dossiers = DossierIndex(db_path)
        self._processes = processes
        self._dossier_warning = False
        self.report.dossiers_checked = self.dossiers.conn is not None
        self.old_hints = read_hints(home)

    # helpers ----------------------------------------------------------------------------------

    def rel(self, path: Path) -> str:
        try:
            return path.relative_to(self.home.path).as_posix()
        except ValueError:
            return str(path)

    def add(self, severity: str, path: Path | str, message: str, subject: str | None = None,
            field_name: str | None = None) -> None:
        where = path if isinstance(path, str) else self.rel(path)
        self.report.findings.append(Finding(severity, where, message, subject, field_name))

    def processes(self) -> set[str]:
        if self._processes is None:
            from exchange.processes.registry import load_registry
            extra = (self.home.path / "processes",) if (self.home.path / "processes").is_dir() else ()
            self._processes = set(load_registry(extra).packages)
        return self._processes

    def read(self, path: Path, subject: str | None = None) -> frontmatter.Document | None:
        try:
            return frontmatter.read(path)
        except (frontmatter.FrontMatterError, UnicodeDecodeError) as exc:
            self.add("error", path, str(exc), subject)
        except OSError as exc:
            self.add("error", path, f"cannot read the file: {exc}", subject)
        return None

    # the project's own files -------------------------------------------------------------------

    def manifest(self) -> None:
        for problem in manifest_problems(self.home.path):
            self.add("error", MARKER, problem)

    def schemas(self) -> None:
        types, problems = load_schemas(self.home.schemas_dir)
        self.report.schemas = types
        for path, problem in problems:
            self.add("error", path, problem)

    def identity(self) -> None:
        path = self.home.identity_path
        if not path.is_file():
            self.add("warning", "IDENTITY.md", "the project has no IDENTITY.md")
            return
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            self.add("error", path, f"cannot read the file: {exc}")
            return
        headings = {m.group(1).strip().casefold() for m in re.finditer(r"^##\s+(.+?)\s*#*\s*$", text, re.M)}
        for section in IDENTITY_SECTIONS:
            if section.casefold() not in headings:
                self.add("warning", path, f"no '## {section}' section")

    def goals(self) -> None:
        path = self.home.goals_path
        if not path.is_file():
            self.add("warning", "goals.md", "the project has no goals.md")
            return
        doc = self.read(path)
        if doc is None:
            return
        goals = doc.meta.get("goals", [])
        unknown = set(doc.meta) - {"goals"}
        if unknown:
            self.add("warning", path, f"unknown keys: {', '.join(sorted(map(str, unknown)))}")
        if not isinstance(goals, list):
            self.add("error", path, "'goals' must be a list")
            return
        for i, goal in enumerate(goals):
            where = f"goals[{i}]"
            if not isinstance(goal, dict):
                self.add("error", path, f"{where} must be a mapping with id, title, status and done_when")
                continue
            goal_id = goal.get("id")
            if not isinstance(goal_id, str) or not GOAL_ID.match(goal_id):
                self.add("error", path, f"{where}: id must look like G1", field_name=where)
                continue
            if goal_id in self.report.goals:
                self.add("error", path, f"{goal_id} is listed twice", goal_id)
                continue
            self.report.goals[goal_id] = goal
            if not isinstance(goal.get("title"), str) or not goal["title"].strip():
                self.add("error", path, f"{goal_id} has no title", goal_id)
            if goal.get("status") not in GOAL_STATUSES:
                self.add("error", path, f"{goal_id}: status must be one of {', '.join(GOAL_STATUSES)}", goal_id)
            if not isinstance(goal.get("done_when"), str) or not goal["done_when"].strip():
                self.add("warning", path, f"{goal_id} has no done_when", goal_id)
            extra = set(goal) - {"id", "title", "status", "done_when"}
            if extra:
                self.add("warning", path, f"{goal_id}: unknown keys {', '.join(sorted(map(str, extra)))}", goal_id)

    def coverage(self) -> None:
        path = self.home.coverage_path
        if not path.is_file():
            return
        try:
            raw = frontmatter.load_yaml(path.read_text(encoding="utf-8"))
        except (frontmatter.FrontMatterError, OSError, UnicodeDecodeError) as exc:
            self.add("error", path, str(exc))
            return
        raw = raw or {}
        if not isinstance(raw, dict):
            self.add("error", path, "the file must be a mapping with 'version' and 'rules'")
            return
        if raw.get("version") != 1:
            self.add("error", path, "version must be 1")
        rules = raw.get("rules") or []
        if not isinstance(rules, list):
            self.add("error", path, "'rules' must be a list")
            return
        seen: set[str] = set()
        for i, rule in enumerate(rules):
            if not isinstance(rule, dict):
                self.add("error", path, f"rules[{i}] must be a mapping with id, for and says")
                continue
            rule_id = rule.get("id")
            label = rule_id if isinstance(rule_id, str) else f"rules[{i}]"
            if not isinstance(rule_id, str) or not RULE_ID.match(rule_id):
                self.add("error", path, f"{label}: id must be lowercase words joined by '-'")
            elif rule_id in seen:
                self.add("error", path, f"{rule_id} is listed twice")
            else:
                seen.add(rule_id)
            signature = rule.get("for")
            if not isinstance(signature, str) or not SIGNATURE.match(signature):
                self.add("error", path, f"{label}: 'for' must be a signature such as DIST or NPC_")
            elif signature not in self.report.schemas:
                self.add("warning", path, f"{label}: {signature} has no schema yet")
            if not isinstance(rule.get("says"), str) or not rule["says"].strip():
                self.add("error", path, f"{label}: 'says' must state the rule in words")
            if "expect" in rule and not isinstance(rule["expect"], dict):
                self.add("error", path, f"{label}: 'expect' must be a mapping")
            extra = set(rule) - {"id", "for", "says", "expect"}
            if extra:
                self.add("warning", path, f"{label}: unknown keys {', '.join(sorted(map(str, extra)))}")
        extra = set(raw) - {"version", "rules"}
        if extra:
            self.add("warning", path, f"unknown keys: {', '.join(sorted(map(str, extra)))}")

    # records ---------------------------------------------------------------------------------

    def load_records(self) -> None:
        base = self.home.records_dir
        if not base.is_dir():
            return
        no_schema: set[str] = set()
        for entry in sorted(base.iterdir()):
            if entry.is_file():
                if entry.suffix.casefold() == ".md":
                    self.add("warning", entry, "records go in a folder named by their signature (records/NPC_/…)")
                continue
            if not SIGNATURE.match(entry.name):
                self.add("warning", entry, f"{entry.name} is not a signature; its files are not records")
                continue
            for path in sorted(entry.iterdir()):
                if path.is_dir():
                    self.add("warning", path, "records are not nested in folders below their signature's")
                elif path.suffix.casefold() == ".md":
                    self.load_record(path, entry.name)
            if entry.name not in self.report.schemas and any(entry.glob("*.md")):
                no_schema.add(entry.name)
        for signature in sorted(no_schema):
            self.add("warning", f"records/{signature}",
                     f"{signature} has no schema yet: only its records' id and maturity are checked")

    def load_record(self, path: Path, folder: str) -> None:
        doc = self.read(path, path.stem)
        if doc is None:
            return
        record_id = doc.meta.get("id")
        if not isinstance(record_id, str) or not record_id:
            self.add("error", path, "no 'id': a record's id is its editor ID, the same as the file name", path.stem)
            return
        if not EDITOR_ID.match(record_id):
            self.add("error", path, f"{record_id!r} is not an editor ID: a signature then a name, such as "
                     "NPC_DockMaster or FACT_PortAuthority (letters, digits and _)", record_id)
            return
        if record_id != path.stem:
            self.add("error", path, f"the id {record_id} does not match the file name {path.name}", record_id)
            return
        signature = signature_of(record_id)
        if signature != folder:
            self.add("error", path, f"{record_id} is a {signature} record but sits in records/{folder}", record_id)
            return
        key = record_id.casefold()
        if key in self.report.records:
            self.add("error", path, f"{record_id} is also {self.report.records[key].path} (editor IDs ignore case)",
                     record_id)
            return
        raw = doc.meta.get("maturity")
        maturity = raw if isinstance(raw, int) and not isinstance(raw, bool) and 0 <= raw < len(LEVELS) else None
        if raw is None:
            self.add("error", path, "no 'maturity' (0 Sketch, 1 Spec, 2 Stub, 3 Built, 4 Polished)", record_id)
        elif maturity is None:
            named = maturity_value(raw)
            hint = f": use {named} for {LEVELS[named]}" if named is not None else ""
            self.add("error", path, f"maturity must be a number from 0 to 4{hint}", record_id, "maturity")
        self.report.records[key] = Record(record_id, signature, maturity, doc.meta, doc.body, self.rel(path))

    def check_records(self) -> None:
        for record in self.report.records.values():
            record_type = self.report.schemas.get(record.signature)
            fields = dict(COMMON_FIELDS)
            if record_type is not None:
                fields.update(record_type.fields)
                unknown = [k for k in record.meta if k not in fields]
                for key in unknown:
                    self.add("warning", record.path, f"{key} is not a field of {record.signature} records",
                             record.id, str(key))
            template = None
            if record_type is not None and record_type.template_field:
                template = record.meta.get(record_type.template_field)
            maturity = record.maturity if record.maturity is not None else 0
            for name, spec in fields.items():
                if name in ("id", "maturity"):
                    continue
                value = record.meta.get(name)
                if _empty(value):
                    if spec.required_at is not None and maturity >= spec.required_at:
                        self.add("error", record.path, f"{record.id} is marked {level_name(maturity)}, but {name} "
                                 f"is empty (required from {LEVELS[spec.required_at]})", record.id, name)
                    continue
                if spec.templates and isinstance(template, str) and template not in spec.templates:
                    self.add("warning", record.path, f"{name} is not a field of a {template} faction "
                             f"(it belongs to {', '.join(spec.templates)})", record.id, name)
                self.check_value(record, value, spec, name, maturity)

    def check_value(self, record: Record, value: Any, spec: Field, where: str, maturity: int) -> None:
        def wrong(expected: str) -> None:
            self.add("error", record.path, f"{where} should be {expected}, not {value!r}", record.id, where)

        kind = spec.type
        if kind == "text":
            if not isinstance(value, str):
                return wrong("text")
            if spec.pattern is not None and not spec.pattern.search(value):
                self.add("error", record.path, f"{where} {value!r} does not match {spec.pattern.pattern}",
                         record.id, where)
        elif kind == "int":
            if not isinstance(value, int) or isinstance(value, bool):
                wrong("a whole number")
        elif kind == "number":
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                wrong("a number")
        elif kind == "bool":
            if not isinstance(value, bool):
                wrong("true or false")
        elif kind == "date":
            if not isinstance(value, dt.date):
                try:
                    dt.date.fromisoformat(str(value))
                except ValueError:
                    wrong("a date (YYYY-MM-DD)")
        elif kind == "enum":
            if not isinstance(value, str) or value not in spec.values:
                wrong(f"one of {', '.join(spec.values)}")
        elif kind == "link":
            if not isinstance(value, str) or not EDITOR_ID.match(value):
                return wrong("an editor ID such as " + (spec.to[0] if spec.to[0].endswith("_") else spec.to[0] + "_") + "Name")
            self.check_link(record, value, spec, where, maturity)
        elif kind == "dossier":
            if not isinstance(value, str) or not value.strip():
                return wrong("a dossier uid")
            self.check_dossier(record, value.strip(), where)
        elif kind == "process":
            if not isinstance(value, str) or not value.strip():
                return wrong("a process id")
            if value not in self.processes():
                self.add("warning", record.path, f"{where}: there is no process {value!r} yet", record.id, where)
        elif kind == "claim":
            if not isinstance(value, str) or not value.strip():
                return wrong("a claim ID")
            if value not in self.report.claims:
                self.add("warning", record.path, f"{where}: there is no claim {value}", record.id, where)
        elif kind == "list":
            if not isinstance(value, list):
                return wrong("a list")
            assert spec.of is not None
            for i, item in enumerate(value):
                if not _empty(item):
                    self.check_value(record, item, spec.of, f"{where}[{i}]", maturity)
        elif kind == "object":
            if not isinstance(value, dict):
                return wrong("a mapping")
            for key in value:
                if key not in spec.fields:
                    self.add("warning", record.path, f"{where}.{key} is not a field here", record.id, f"{where}.{key}")
            for name, sub in spec.fields.items():
                item = value.get(name)
                if _empty(item):
                    if sub.required_at is not None and maturity >= sub.required_at:
                        self.add("error", record.path, f"{where}.{name} is empty", record.id, f"{where}.{name}")
                    continue
                self.check_value(record, item, sub, f"{where}.{name}", maturity)

    def check_link(self, record: Record, target_id: str, spec: Field, where: str, maturity: int) -> None:
        signature = signature_of(target_id)
        if signature not in spec.to:
            self.add("error", record.path, f"{where} links to {target_id}, a {signature} record; it takes "
                     f"{', '.join(spec.to)}", record.id, where)
            return
        if maturity == 0:
            return  # a Sketch's links are not checked yet
        required = min(maturity, spec.max_demand)
        target = self.report.record(target_id)
        if target is None:
            if signature not in self.report.schemas:
                self.add("warning", record.path, f"{where} links to {target_id}, which has no record yet "
                         f"({signature} has no schema, so no claim is opened)", record.id, where)
                return
            self.report.gaps.append(Gap(
                "missing", target_id, record.id, where,
                f"{record.id} ({LEVELS[maturity]}) links to {target_id} in {where}, which does not exist yet",
                required=required))
            return
        if target.id != target_id:
            self.add("warning", record.path, f"{where} says {target_id}; the record is {target.id}", record.id, where)
        if target.maturity is not None and target.maturity < required:
            self.report.gaps.append(Gap(
                "immature", target.id, record.id, where,
                f"{record.id} ({LEVELS[maturity]}) links to {target.id} in {where}, which is a "
                f"{level_name(target.maturity)}; it needs {level_name(required)}",
                required=required, current=target.maturity))

    def check_dossier(self, record: Record, uid: str, where: str) -> None:
        state, final = self.dossiers.resolve(uid)
        hints = self.report.dossier_hints
        if state == "unchecked":
            if uid in self.old_hints:
                hints[uid] = self.old_hints[uid]
            if not self._dossier_warning:
                self._dossier_warning = True
                self.add("warning", MARKER, f"dossier links are not checked: {self.dossiers.problem}")
            return
        if state in ("ok", "merged"):
            if uid not in hints:
                hints[uid] = self.dossiers.describe(final) or {}
            if state == "merged":
                self.add("warning", record.path, f"{where}: dossier {uid} was merged into {final}; link that instead",
                         record.id, where)
            return
        # Broken: the old hint (or, for a retired dossier, what the library still says) finds candidates.
        if uid not in hints:
            hints[uid] = self.old_hints.get(uid) or self.dossiers.describe(uid) or {}
        why = "is not in the library" if state == "missing" else \
            "has only retired entries in the library (its files are gone or were moved)"
        self.report.gaps.append(Gap(
            "dossier", record.id, record.id, where, f"{record.id}'s {where}: dossier {uid} {why}",
            dossier=uid, dossier_state=state, candidates=self.dossiers.candidates(hints[uid], uid)))

    # claims ----------------------------------------------------------------------------------

    def load_claims(self) -> None:
        base = self.home.claims_dir
        if not base.is_dir():
            return
        for path in sorted(base.iterdir()):
            if path.is_dir():
                self.add("warning", path, "claims are kept flat in claims/; folders are not read")
            elif path.suffix.casefold() == ".md":
                doc = self.read(path, path.stem)
                if doc is not None:
                    self.report.claims[path.stem] = Claim(path.stem, doc.meta, doc.body, self.rel(path))

    def check_claims(self) -> None:
        for claim in self.report.claims.values():
            meta, path, cid = claim.meta, claim.path, claim.id
            match = CLAIM_ID.match(cid)
            if not match:
                self.add("error", path, "a claim's file name is its date and a slug: 2026-10-24-spec-the-cantina.md", cid)
            if meta.get("id") != cid:
                self.add("error", path, f"the id must be the file name's stem, {cid}", cid, "id")
            status = meta.get("status")
            if status not in CLAIM_STATUSES:
                self.add("error", path, f"status must be one of {', '.join(CLAIM_STATUSES)}", cid, "status")
            created = meta.get("created")
            if created is None:
                self.add("error", path, "no 'created' date", cid, "created")
            else:
                try:
                    day = created if isinstance(created, dt.date) else dt.date.fromisoformat(str(created))
                    if match and day.isoformat() != match.group(1):
                        self.add("warning", path, f"created {day.isoformat()} is not the date in the file name", cid, "created")
                except ValueError:
                    self.add("error", path, "created must be a date (YYYY-MM-DD)", cid, "created")
            source = meta.get("source", "manual")
            if source not in CLAIM_SOURCES:
                self.add("error", path, f"source must be one of {', '.join(CLAIM_SOURCES)}", cid, "source")
            target = meta.get("target")
            if _empty(target):
                if _empty(meta.get("domain")):
                    self.add("warning", path, "unfiled: the claim has no target record", cid, "target")
            elif not isinstance(target, str) or not EDITOR_ID.match(target):
                self.add("error", path, "target must be a record's editor ID", cid, "target")
            elif self.report.record(target) is None and source != "gap":
                self.add("warning", path, f"target {target} has no record yet", cid, "target")
            goal = meta.get("goal")
            if not _empty(goal) and goal not in self.report.goals:
                self.add("warning", path, f"goal {goal} is not in goals.md", cid, "goal")
            needed_by = meta.get("needed_by")
            if not _empty(needed_by):
                ids = needed_by if isinstance(needed_by, list) else [needed_by]
                for item in ids:
                    if not isinstance(item, str) or not EDITOR_ID.match(item):
                        self.add("error", path, f"needed_by: {item!r} is not an editor ID", cid, "needed_by")
                    elif self.report.record(item) is None:
                        self.add("warning", path, f"needed_by: {item} has no record", cid, "needed_by")
            if status == "claimed" and _empty(meta.get("claimed_by")):
                self.add("warning", path, "claimed, but claimed_by is empty", cid, "claimed_by")
            if not _empty(meta.get("triage")) and meta.get("triage") not in ("new", "seen"):
                self.add("error", path, "triage is 'new' or 'seen'", cid, "triage")
            self.check_claim_links(claim)
            needs = meta.get("needs")
            if not _empty(needs):
                if not isinstance(needs, list) or not all(isinstance(n, dict) and isinstance(n.get("kind"), str) for n in needs):
                    self.add("error", path, "needs must be a list of mappings, each with a kind", cid, "needs")
            for key in meta:
                if key not in CLAIM_KEYS:
                    self.add("warning", path, f"{key} is not a claim field", cid, str(key))

    def check_claim_links(self, claim: Claim) -> None:
        links = claim.meta.get("links")
        if _empty(links):
            return
        if not isinstance(links, list):
            self.add("error", claim.path, "links must be a list", claim.id, "links")
            return
        for link in links:
            if not isinstance(link, str):
                self.add("error", claim.path, f"links: {link!r} is not a reference", claim.id, "links")
                continue
            prefix, _, rest = link.partition(":")
            if not rest:
                if not EDITOR_ID.match(link):
                    self.add("error", claim.path, f"links: {link!r} is neither an editor ID nor a typed reference "
                             f"({', '.join(p + ':' for p in LINK_PREFIXES)})", claim.id, "links")
                elif self.report.record(link) is None:
                    self.add("warning", claim.path, f"links: {link} has no record", claim.id, "links")
            elif prefix not in LINK_PREFIXES:
                self.add("error", claim.path, f"links: unknown kind of reference {prefix}:", claim.id, "links")
            elif prefix == "claim" and rest not in self.report.claims:
                self.add("warning", claim.path, f"links: there is no claim {rest}", claim.id, "links")
            elif prefix == "goal" and rest not in self.report.goals:
                self.add("warning", claim.path, f"links: goal {rest} is not in goals.md", claim.id, "links")
            elif prefix == "process" and rest not in self.processes():
                self.add("warning", claim.path, f"links: there is no process {rest!r}", claim.id, "links")
            elif prefix == "dossier":
                state, final = self.dossiers.resolve(rest)
                if state in ("missing", "retired"):
                    self.add("warning", claim.path, f"links: dossier {rest} is {'not in the library' if state == 'missing' else 'retired'}",
                             claim.id, "links")
                elif state == "merged":
                    self.add("warning", claim.path, f"links: dossier {rest} was merged into {final}", claim.id, "links")

    def run(self) -> Report:
        try:
            self.manifest()
            self.schemas()
            self.identity()
            self.goals()
            self.coverage()
            self.load_records()
            self.load_claims()  # before the records' fields, which may name claims (origin)
            self.check_records()
            self.check_claims()
        finally:
            self.dossiers.close()
        return self.report


def validate_home(home: ProjectHome, *, db_path: Path | None = None,
                  processes: set[str] | None = None) -> Report:
    """Validate a project home. ``db_path`` is the library database dossier links are resolved
    against; ``processes`` the process ids that exist (default: the process registry's)."""
    return _Validator(home, db_path, processes).run()
