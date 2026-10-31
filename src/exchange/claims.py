"""Claims: Luke's decision to get a thing into a place, kept as a markdown file in ``<data>/claims/``.

A claim file is front matter plus free notes. Exchange writes a new file once (mode ``x``), then
rewrites only ``requisitions``, ``milestone`` and ``closed`` in place, so hand edits to the notes, to
any other key and extra keys of your own survive. The milestone is derived from the library on
every read of an open claim; a closed claim keeps the one it had. Claims are read from the folder
each time; the database has no index of them. The service reads on several threads and a read can
save the milestone, so one lock covers reading and rewriting a file, and a rewrite goes through a
temporary file moved over the claim: a reader never sees half a file.

Beyond the file, a claim has a **path** (the processes that take the thing to the place, as the role),
**whose turn** it is (Luke's, Exchange's, or a process nobody has built yet), and it can be **walked**:
the path planned (``plan_path``, which writes nothing) and queued as a requisition whose uid the claim
records. Path and turn are derived on every read and never written.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import json
import os
import re
import sqlite3
import threading
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from exchange.db import repository as repo
from exchange.definitions.schema import DefinitionSet
from exchange.errors import ExchangeError
from exchange.paths import data_dir, fold, is_within
from exchange.processes.registry import ProcessPackage, Registry, check_prerequisites, ready, tool_paths, validate
from exchange.projects import frontmatter
from exchange.requisitions.endpoints import configured_folder, place_root
from exchange.requisitions.plan import (
    Plan,
    PlanError,
    _entries,
    can_read,
    find_chains,
    for_role,
    grants,
    plan_requisition,
    queue_plan,
    routes,
)

MILESTONES = ("claimed", "acquired", "converted", "installed")  # in order, each derived from the library
OWNED_KEYS = ("requisitions", "milestone", "closed")  # the only keys Exchange rewrites
_lock = threading.RLock()  # reading and rewriting a claim file, in this process


class ClaimError(ExchangeError):
    """A claim request that cannot be done as asked."""


class ClaimNotFound(ClaimError):
    """No such claim, dossier or environment."""


class FolderLeavesPlace(ClaimError):
    """A relative folder that does not stay inside the place."""


@dataclass
class Claim:
    id: str  # the file's stem
    path: Path
    meta: dict[str, Any]
    notes: str = ""
    problems: list[str] = field(default_factory=list, repr=False)
    already_there: bool = False  # set by ``describe``: the place already holds the thing

    @property
    def milestone(self) -> str | None:
        return self.meta.get("milestone")

    @property
    def closed(self) -> bool:
        return self.meta.get("closed") is not None

    def to_json(self) -> dict:
        return {**self.meta, "already_there": self.already_there, "id": self.id, "notes": self.notes}


def claims_dir() -> Path:
    return data_dir() / "claims"


def slug(text: str, words: int = 8) -> str:
    """``LOT_SaltRowCantina`` → ``lot-salt-row-cantina``; ``What if the House…`` → ``what-if-the-house``."""
    text = re.sub(r"['’]", "", text)  # "smuggler's" is one word
    text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])|_", " ", text)
    parts = re.findall(r"[a-z0-9]+", text.casefold().encode("ascii", "ignore").decode())
    return "-".join(parts[:words])[:60].strip("-") or "claim"


def _new_path(day: dt.date, name: str) -> Path:
    base = f"{day.isoformat()}-{slug(name)}"
    path, n = claims_dir() / f"{base}.md", 2
    while path.exists():
        path, n = claims_dir() / f"{base}-{n}.md", n + 1
    return path


def _live(conn: sqlite3.Connection, thing: object) -> bool:
    """Whether the dossier has an entry that is not retired."""
    row = conn.execute(
        "SELECT sum(e.status != 'retired') FROM entry e JOIN ledger l ON l.id = e.ledger_id"
        " JOIN dossier d ON d.id = l.dossier_id WHERE d.uid = ?", (str(thing),)).fetchone()
    return bool(row[0])


def resolve_requisitions(conn: sqlite3.Connection, meta: dict[str, Any]) -> list[tuple[Any, sqlite3.Row | None]]:
    """Each uid of the claim's ``requisitions`` with its requisition row, or None when it no longer resolves."""
    uids = meta.get("requisitions")
    uids = uids if isinstance(uids, list) else []
    return [(uid, conn.execute("SELECT id, uid, state, message FROM requisition WHERE uid = ?", (uid,)).fetchone()
             if isinstance(uid, str) else None) for uid in uids]


def one_line(message: str | None, rid: int) -> str:
    """A requisition's message as one line: its first non-empty line, pointing at ``requisition show`` for the rest."""
    lines = [line.strip() for line in (message or "").splitlines() if line.strip()]
    if len(lines) > 1:
        return f"{lines[0]} (exchange requisition show {rid})"
    return lines[0] if lines else ""


def _latest(conn: sqlite3.Connection, meta: dict[str, Any]) -> sqlite3.Row | None:
    found = [row for _, row in resolve_requisitions(conn, meta) if row is not None]
    return found[-1] if found else None


def _placed(conn: sqlite3.Connection, dossier_uid: object, place_id: int,
            requisition_ids: list[int] | None = None) -> bool:
    """Whether the dossier has a live entry in the place on an online root (a place holds only what is
    on one), written by one of these requisitions when they are given."""
    only = "" if requisition_ids is None else f" AND e.requisition_id IN ({', '.join('?' * len(requisition_ids))})"
    return conn.execute(
        "SELECT 1 FROM entry e JOIN ledger l ON l.id = e.ledger_id JOIN dossier d ON d.id = l.dossier_id"
        " JOIN container c ON c.id = e.container_id JOIN environment_root r ON r.id = c.root_id"
        f" WHERE r.status = 'online' AND d.uid = ? AND e.status != 'retired' AND l.environment_id = ?{only} LIMIT 1",
        (dossier_uid, place_id, *(requisition_ids or ()))).fetchone() is not None


def _derive(conn: sqlite3.Connection, meta: dict[str, Any]) -> str:
    """The least advanced of the walked subjects (the thing, or a product's children), each
    ``installed`` (its entry sits in the place on an online root, written by one of the claim's
    requisitions: a place holds only what is on an online root), ``converted`` (the latest
    requisition's item is done) or ``acquired``/``claimed`` (the dossier has an entry that is not
    retired, or not)."""
    thing = str(meta.get("thing"))
    base = "acquired" if _live(conn, thing) else "claimed"
    latest = _latest(conn, meta)
    if latest is None:
        return base
    subjects = conn.execute(
        "SELECT i.dossier_uid, i.state FROM requisition_item i WHERE i.requisition_id = ? AND i.include = 1"
        " AND (i.dossier_uid = ? OR i.dossier_uid IN (SELECT c.uid FROM dossier_effective c"
        " JOIN dossier_effective p ON p.id = c.parent_id WHERE p.uid = ?))", (latest["id"], thing, thing)).fetchall()
    if not subjects:
        return base
    place = conn.execute("SELECT id FROM environment WHERE uid = ?", (str(meta.get("place")),)).fetchone()
    ids = [row["id"] for _, row in resolve_requisitions(conn, meta) if row is not None]
    least = len(MILESTONES)
    for subject in subjects:
        installed = place is not None and _placed(conn, subject["dossier_uid"], place["id"], ids)
        milestone = "installed" if installed else "converted" if subject["state"] == "done" else base
        least = min(least, MILESTONES.index(milestone))
    return MILESTONES[least]


def _claim_folder(conn: sqlite3.Connection, definitions: DefinitionSet | None, folder: object, env_id: int,
                  place_name: str) -> str | None:
    """The folder a claim writes to: absolute as is, relative to the root the place writes through
    (``place_root``); None for the default (no folder, a blank one, or that root not online). A relative folder that leaves the
    root, or names a drive, is refused: an absolute one is the user's explicit choice."""
    if not isinstance(folder, str) or not folder.strip():
        return None
    text = folder.strip()
    if Path(text).is_absolute():
        return str(Path(text))
    refusal = FolderLeavesPlace(f"the folder {folder} leaves {place_name}: a relative folder must stay inside the place;"
                         " give an absolute one to write elsewhere")
    if Path(text).drive:
        raise refusal
    root = place_root(conn, definitions, repo.get_environment(conn, env_id))
    if root is None:
        return None
    chosen = configured_folder(text, "", root, {})
    if not is_within(chosen, root):
        raise refusal
    return str(chosen)


def prepare(conn: sqlite3.Connection, uid: str, env_id: int, *, role: str | None = None,
            folder: str | None = None, today: dt.date | None = None,
            definitions: DefinitionSet | None = None) -> Claim:
    """The claim ``new`` would make, unsaved, with the id and path its file would have. Checks what ``new``
    checks and creates nothing."""
    today = today or dt.date.today()
    thing = conn.execute("SELECT uid, name FROM dossier_effective WHERE uid = ?", (uid,)).fetchone()
    if thing is None:
        raise ClaimNotFound(f"no dossier {uid!r} in the library")
    place = conn.execute("SELECT uid, name FROM environment WHERE id = ?", (env_id,)).fetchone()
    if place is None:
        raise ClaimNotFound(f"no environment {env_id} in the library")
    _claim_folder(conn, definitions, folder, env_id, place["name"])
    path = _new_path(today, thing["name"])
    meta = {"id": path.stem, "thing": thing["uid"], "thing_name": thing["name"], "as": role,
            "place": place["uid"], "place_name": place["name"], "folder": folder, "requisitions": [],
            "milestone": _derive(conn, {"thing": thing["uid"]}), "created": today, "closed": None}
    return Claim(path.stem, path, meta)


def new(conn: sqlite3.Connection, uid: str, env_id: int, *, role: str | None = None,
        folder: str | None = None, note: str = "", today: dt.date | None = None,
        definitions: DefinitionSet | None = None) -> Claim:
    claim = prepare(conn, uid, env_id, role=role, folder=folder, today=today, definitions=definitions)
    path = claim.path
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(path, "x", encoding="utf-8", newline="\n") as f:  # never over an existing file
            f.write(frontmatter.dump(claim.meta, note))
    except FileExistsError:
        raise ClaimError(f"{path.name} already exists; try again") from None
    return read_one(conn, path.stem)


def _files() -> list[Path]:
    folder = claims_dir()
    return sorted((p for p in folder.glob("*.md") if p.is_file()), key=lambda p: p.name) if folder.is_dir() else []


def _read(conn: sqlite3.Connection, path: Path) -> Claim:
    with _lock:  # on Windows a file being read blocks a rewrite's replace, so reads wait for rewrites
        try:
            doc = frontmatter.read(path)
        except (frontmatter.FrontMatterError, UnicodeDecodeError, OSError):
            raise
        except (ValueError, TypeError) as exc:  # YAML the loader builds but Python refuses, e.g. 2026-02-30
            raise frontmatter.FrontMatterError(str(exc)) from exc
        claim = Claim(path.stem, path, doc.meta, doc.body)
        if not claim.closed:
            derived = _derive(conn, doc.meta)
            if derived != doc.meta.get("milestone"):
                try:
                    update(claim, {"milestone": derived})
                except (ClaimError, frontmatter.FrontMatterError, OSError) as exc:
                    claim.meta["milestone"] = derived
                    claim.problems.append(f"{path.name}: could not update the milestone: {exc}")
        return claim


def read_all(conn: sqlite3.Connection) -> tuple[list[Claim], list[str]]:
    """Every readable claim, and a problem line for each file that is not (or could not be updated)."""
    claims, problems = [], []
    for path in _files():
        try:
            claim = _read(conn, path)
        except (frontmatter.FrontMatterError, OSError, UnicodeDecodeError) as exc:
            problems.append(f"{path.name}: {exc}")
            continue
        claims.append(claim)
        problems += claim.problems
    return claims, problems


def read_one(conn: sqlite3.Connection, id: str) -> Claim:
    for path in _files():  # looked up among the files, never built from the id
        if path.stem == id:
            try:
                return _read(conn, path)
            except (frontmatter.FrontMatterError, OSError, UnicodeDecodeError) as exc:
                raise ClaimError(f"{path.name}: {exc}") from exc
    raise ClaimNotFound(f"no claim {id!r}")


def update(claim: Claim, updates: dict[str, Any], append: str = "") -> None:
    """Rewrite ``requisitions``, ``milestone`` and ``closed`` in the claim's file, nothing else. The new
    text goes to a temporary file beside the claim, then over it, so a failed write leaves the old file."""
    other = sorted(set(updates) - set(OWNED_KEYS))
    if other:
        raise ClaimError(f"Exchange only changes {', '.join(OWNED_KEYS)}, not {', '.join(other)}")
    with _lock:
        text = frontmatter.set_keys(claim.path.read_text(encoding="utf-8"), updates, append=append)
        temp = claim.path.with_name(f"{claim.path.name}.{os.getpid()}.tmp")  # never ends in .md
        try:
            temp.write_bytes(text.encode("utf-8"))
            os.replace(temp, claim.path)
        except BaseException:
            with contextlib.suppress(OSError):
                temp.unlink(missing_ok=True)
            raise
        claim.meta.update(updates)
        if append:
            claim.notes = frontmatter.parse(text).body


def close(conn: sqlite3.Connection, id: str, reason: str = "", today: dt.date | None = None) -> Claim:
    with _lock:  # the check and the write together, so two closes can't both succeed
        claim = read_one(conn, id)
        if claim.closed:
            raise ClaimError(f"claim {id} is already closed ({claim.meta['closed']})")
        try:
            update(claim, {"closed": today or dt.date.today()}, append=reason)
        except (frontmatter.FrontMatterError, OSError) as exc:
            raise ClaimError(f"{claim.path.name}: {exc}") from exc
        return claim


# Path, whose turn, walking -------------------------------------------------------------------


def _role(meta: dict[str, Any]) -> str | None:
    return None if meta.get("as") in (None, "") else str(meta["as"]).casefold()


def _setup_problem(package: ProcessPackage, tools: dict[str, str]) -> tuple[str, str]:
    """Why a process is not ready, as the path's problem and as what Luke should do about it."""
    if not package.trusted:
        return "not trusted", "trust it"
    problems = validate(package)
    if problems:
        return problems[0], problems[0]
    red = next(s for s in check_prerequisites(package, tools) if not s.ok)
    return f"{red.label}: {red.detail}", f"fix {red.label} ({red.detail})"


def find_path(conn: sqlite3.Connection, definitions: DefinitionSet, registry: Registry, claim: Claim,
              tools: dict[str, str] | None = None) -> dict:
    """The claim's path: ``ready`` (a route that can be walked now), ``not_ready`` (a chain whose first
    non-ready process is named, with why) or ``none``. A product with no route of its own takes the
    routes of its children (route ``children``), as a requisition plans them. A copy never satisfies
    a role. A chain is only offered from an entry its first process can read (see ``plan.py``), also in
    the look past readiness, so a process that couldn't read the source is never named. Never imports
    an untrusted package's code."""
    tools = tool_paths() if tools is None else tools
    meta = claim.meta
    role = _role(meta)
    thing, place = str(meta.get("thing")), str(meta.get("place"))

    def result(status, route=None, processes=(), process=None, problem=None, source=None) -> dict:
        return {"status": status, "route": route, "processes": list(processes), "process": process,
                "problem": problem, "source_entry_id": source}

    dossier = conn.execute("SELECT id, type_id FROM dossier_effective WHERE uid = ?", (thing,)).fetchone()
    if dossier is None:
        return result("none", problem=f"no dossier {thing} in the library")
    env = conn.execute("SELECT id, name, type_id FROM environment WHERE uid = ?", (place,)).fetchone()
    if env is None:
        return result("none", problem=f"no environment {place} in the library")
    children = conn.execute("SELECT uid, type_id FROM dossier_effective WHERE parent_id = ? ORDER BY lower(name)",
                            (dossier["id"],)).fetchall()
    try:
        kept = for_role(registry, routes(conn, definitions, registry, thing, env["id"], tools), role)
        beneath = [] if kept else [r for child in children for r in for_role(
            registry, routes(conn, definitions, registry, child["uid"], env["id"], tools), role)]
    except PlanError as exc:
        return result("none", problem=str(exc))
    kept.sort(key=lambda r: r["route"] != "convert")  # convert from the source unless it is already there
    if kept:
        return result("ready", kept[0]["route"], kept[0]["processes"], source=kept[0]["source_entry_id"])
    if beneath:
        return result("ready", "children", dict.fromkeys(p for r in beneath for p in r["processes"]))
    best = None  # (chain, route, source entry, first non-ready process): the shortest
    for uid, type_id in [(thing, dossier["type_id"]), *map(tuple, children)]:
        tags = repo.effective_tags(conn, uid)
        for entry in _entries(conn, uid):
            for chain in find_chains(registry, definitions, type_id, tags, entry["env_type"], env["type_id"],
                                     tools, ready_only=False,
                                     first=lambda p, entry_id=entry["id"]: can_read(conn, p, entry_id)):
                if role is not None and not grants(registry, chain, role):
                    continue
                unready = next((p for p in chain if not ready(registry.packages[p], tools)), None)
                if unready is not None and (best is None or len(chain) < len(best[0])):
                    best = (chain, *(("convert", entry["id"]) if uid == thing else ("children", None)), unready)
    if best is not None:
        chain, route, source, unready = best
        return result("not_ready", route, chain, unready, _setup_problem(registry.packages[unready], tools)[0], source)
    return result("none", problem=f"no process takes it to {env['name']}" + (f" as {meta['as']}" if role else ""))


def _unread_folder(conn: sqlite3.Connection, meta: dict[str, Any], latest: sqlite3.Row) -> tuple[str, str] | None:
    """``(folder, place name)`` when a fulfilled requisition's output was seen by a scan of the place and
    is still there on an online root, yet no entry in the place carries the requisition: the place's
    layer doesn't read that folder. None otherwise (not scanned since, or the output is gone or on an
    offline root)."""
    place = conn.execute("SELECT id, name FROM environment WHERE uid = ?", (str(meta.get("place")),)).fetchone()
    if place is None or latest["state"] != "fulfilled":
        return None
    if conn.execute("SELECT 1 FROM entry e JOIN ledger l ON l.id = e.ledger_id WHERE l.environment_id = ?"
                    " AND e.requisition_id = ? AND e.status != 'retired' LIMIT 1", (place["id"], latest["id"])).fetchone():
        return None
    roots = repo.list_roots(conn, place["id"])
    for write in conn.execute("SELECT path FROM requisition_write WHERE requisition_id = ? AND action != 'sidecar'"
                              " AND removed_at IS NULL", (latest["id"],)):
        path = Path(write["path"]).resolve()
        for root in roots:
            if root["status"] == "online" and is_within(path, Path(root["path"])) and conn.execute(
                    "SELECT 1 FROM file WHERE root_id = ? AND rel_key = ? AND state != 'gone'",
                    (root["id"], fold(path.relative_to(Path(root["path"]).resolve()).as_posix()))).fetchone():
                endpoint = conn.execute("SELECT endpoint FROM requisition WHERE id = ?", (latest["id"],)).fetchone()
                return json.loads(endpoint["endpoint"])["folder"], place["name"]
    return None


def whose_turn(conn: sqlite3.Connection, definitions: DefinitionSet, registry: Registry, claim: Claim,
               path: dict | None = None, tools: dict[str, str] | None = None) -> tuple[str, str]:
    """``(turn, line)`` for an open claim: ``you``, ``exchange``, ``build`` (or ``none`` when closed)."""
    if claim.closed:
        return "none", ""
    if not _live(conn, claim.meta.get("thing")):
        return "you", "The source files are gone: rescan or relink"
    tools = tool_paths() if tools is None else tools
    path = path or find_path(conn, definitions, registry, claim, tools)
    if path["status"] == "none":
        return "build", "No path yet: a process has to be built"
    if path["status"] == "not_ready":
        return "you", f"Set up {path['process']}: {_setup_problem(registry.packages[path['process']], tools)[1]}"
    latest = _latest(conn, claim.meta)
    if latest is None:
        return "you", "Walk it"
    state, rid = latest["state"], latest["id"]
    if state in ("queued", "running"):
        return "exchange", ""
    if state == "held":
        return "you", f"Release requisition {rid}"
    if state == "needs_attention":
        return "you", one_line(latest["message"], rid) or f"Requisition {rid} needs attention"
    if state in ("failed", "partially_fulfilled"):
        return "you", one_line(latest["message"], rid) or f"Requisition {rid} failed"
    if claim.milestone == "installed":
        return "you", "Close it, or take it into play"
    unread = _unread_folder(conn, claim.meta, latest)
    if unread is not None:
        return "you", (f"Requisition {rid} wrote to {unread[0]}, but {unread[1]} doesn't read that folder:"
                       " choose a folder it reads, then walk it again")
    return "you", f"Walk it again: the place no longer holds what requisition {rid} wrote"


def describe(conn: sqlite3.Connection, definitions: DefinitionSet, registry: Registry, claim: Claim,
             tools: dict[str, str] | None = None) -> dict:
    """The claim's JSON object with its path, whose turn it is and whether the place already holds the
    thing. The claim may be unsaved (see ``prepare``)."""
    tools = tool_paths() if tools is None else tools
    path = find_path(conn, definitions, registry, claim, tools)
    turn, line = whose_turn(conn, definitions, registry, claim, path, tools)
    claim.already_there = _already_there(conn, claim.meta)
    return {**claim.to_json(), "path": path, "turn": turn, "turn_line": line}


def _already_there(conn: sqlite3.Connection, meta: dict[str, Any]) -> bool:
    """Whether a claim with no role, folder or requisitions asks for what the place already holds: the
    thing has a live entry in it on an online root. It is only said; the path and the turn don't change."""
    folder = meta.get("folder")
    if _role(meta) is not None or (isinstance(folder, str) and folder.strip()) or resolve_requisitions(conn, meta):
        return False
    place = conn.execute("SELECT id FROM environment WHERE uid = ?", (str(meta.get("place")),)).fetchone()
    return place is not None and _placed(conn, str(meta.get("thing")), place["id"])


def _endpoint_folder(conn: sqlite3.Connection, definitions: DefinitionSet, meta: dict[str, Any],
                     env_id: int) -> str | None:
    """The claim's folder (see ``_claim_folder``); None for the default."""
    place = conn.execute("SELECT name FROM environment WHERE id = ?", (env_id,)).fetchone()
    return _claim_folder(conn, definitions, meta.get("folder"), env_id, place["name"])


def plan_path(conn: sqlite3.Connection, definitions: DefinitionSet, registry: Registry, id: str,
              tools: dict[str, str] | None = None, *, params: dict[str, Any] | None = None,
              defaults: dict[str, Any] | None = None, on_collision: str = "ask",
              excluded: Iterable[str] = ()) -> tuple[Claim, Plan]:
    """The claim and the plan for its path, as ``walk`` queues it; writes nothing. Refuses a closed claim,
    a path that isn't ready and a requisition still waiting or running. ``params`` are typed option values
    (``process.option``), ``defaults`` the ones they fall back to; ``excluded`` are dossier uids left out."""
    claim = read_one(conn, id)
    if claim.closed:
        raise ClaimError(f"claim {id} is closed")
    tools = tool_paths() if tools is None else tools
    path = find_path(conn, definitions, registry, claim, tools)
    if path["status"] != "ready":
        raise ClaimError(whose_turn(conn, definitions, registry, claim, path, tools)[1])
    latest = _latest(conn, claim.meta)
    if latest is not None and latest["state"] in ("queued", "running"):
        raise ClaimError(f"requisition {latest['id']} is {latest['state']}; it is Exchange's turn")
    if latest is not None and latest["state"] == "held":
        raise ClaimError(f"Release requisition {latest['id']}")
    env_id = conn.execute("SELECT id FROM environment WHERE uid = ?", (str(claim.meta.get("place")),)).fetchone()[0]
    processes = None if path["route"] == "children" else path["processes"]  # each child takes its own route
    plan = plan_requisition(conn, definitions, registry, str(claim.meta["thing"]), env_id, processes=processes,
                            params=params, defaults=defaults, on_collision=on_collision,
                            source_entry_id=path["source_entry_id"], role=_role(claim.meta),
                            endpoint_folder=_endpoint_folder(conn, definitions, claim.meta, env_id), tools=tools)
    left_out = set(excluded)
    for item in plan.items:
        if item.dossier_uid in left_out:
            item.include = False
    return claim, plan


def walk(conn: sqlite3.Connection, definitions: DefinitionSet, registry: Registry, id: str,
         tools: dict[str, str] | None = None, *, params: dict[str, Any] | None = None,
         defaults: dict[str, Any] | None = None, on_collision: str = "ask",
         excluded: Iterable[str] = ()) -> tuple[Claim, int]:
    """Plan and queue the claim's path as a requisition and record its uid; returns the claim and the
    requisition's id. Running it is the caller's."""
    claim, plan = plan_path(conn, definitions, registry, id, tools, params=params, defaults=defaults,
                            on_collision=on_collision, excluded=excluded)
    if not any(item.include for item in plan.items):
        raise ClaimError("nothing in this plan is included")
    requisition_id = queue_plan(conn, plan, registry)
    uid = conn.execute("SELECT uid FROM requisition WHERE id = ?", (requisition_id,)).fetchone()[0]
    existing = claim.meta.get("requisitions")
    try:
        update(claim, {"requisitions": [*(existing if isinstance(existing, list) else []), uid]})
    except (frontmatter.FrontMatterError, OSError) as exc:
        raise ClaimError(f"{claim.path.name}: {exc} (requisition {requisition_id} is queued, not recorded)") from exc
    return read_one(conn, id), requisition_id
