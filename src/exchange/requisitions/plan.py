"""Planning a requisition: which processes can turn a dossier into something for an environment,
from which of its entries, and the plan of a whole product.

* A process **matches** a dossier when the dossier's type is (a subtype of) one of its input
  types, it has all the input tags, and the source entry's environment is one it takes. Only
  **ready** processes are offered: trusted, a valid chain, every prerequisite green.
* **Routes:** if the target environment already holds the asset, it can be *copied* from that
  entry (the ``copy_entry`` process) instead of *converted* from another one.
* **Chains:** with no direct process, processes are chained (up to three) when one's output
  (dossier type, environment) is the next one's input, e.g. G2 → G8 → Skyrim. A chain is only
  offered from an entry its first process can read: the entry holds a live file of one of the
  extensions the process declares (none declared: any). Copies and later processes aren't checked.
* A **product** plans each of its children; children with no process are listed, unchecked.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from exchange.db import repository as repo
from exchange.definitions.schema import DefinitionSet
from exchange.errors import ExchangeError
from exchange.processes.registry import ProcessPackage, Registry, ready, tool_paths
from exchange.requisitions.endpoints import Endpoint, default_endpoint

MAX_CHAIN = 3
COPY_PROCESS = "copy_entry"


class PlanError(ExchangeError):
    pass


@dataclass
class PlanItem:
    dossier_uid: str
    name: str
    type_id: str
    source_entry_id: int | None
    source: str  # where the source entry is, in words
    route: str  # convert | copy | none
    processes: list[str]  # the chain, in order
    params: dict[str, dict[str, Any]] = field(default_factory=dict)  # process id -> values
    include: bool = True
    problems: list[str] = field(default_factory=list)


@dataclass
class Plan:
    name: str
    environment_id: int
    endpoint: Endpoint
    items: list[PlanItem]
    on_collision: str = "ask"
    warnings: list[str] = field(default_factory=list)


def _entries(conn: sqlite3.Connection, uid: str) -> list[dict]:
    rows = conn.execute(
        "SELECT e.id, e.status, l.environment_id, v.type_id AS env_type, v.name AS env_name, c.name AS container"
        " FROM dossier d JOIN ledger l ON l.dossier_id = d.id JOIN entry e ON e.ledger_id = l.id"
        " JOIN environment v ON v.id = l.environment_id LEFT JOIN container c ON c.id = e.container_id"
        " WHERE d.uid = ? AND e.status != 'retired' ORDER BY e.status != 'origin', e.id", (uid,))
    return [dict(r) for r in rows]


def matches(package: ProcessPackage, definitions: DefinitionSet, type_id: str, tags: set[str],
            source_env_type: str, target_env_type: str | None, *, check_tags: bool = True) -> bool:
    m = package.manifest
    if m.input_types and not any(type_id in definitions.dossier_types and definitions.is_a(type_id, t)
                                 for t in m.input_types):
        return False
    if check_tags and not {t.casefold() for t in m.input_tags} <= {t.casefold() for t in tags}:
        return False
    if m.input_environments and source_env_type not in m.input_environments:
        return False
    out_env = source_env_type if m.output_environment == "same" else m.output_environment
    return target_env_type is None or out_env == target_env_type


def can_read(conn: sqlite3.Connection, package: ProcessPackage, entry_id: int) -> bool:
    """Whether the entry holds a live file (any role) with one of the extensions the package declares;
    declaring none, any entry. From the manifest and the database alone: no package code runs."""
    extensions = {e.casefold() for e in package.manifest.input_extensions}
    if not extensions:
        return True
    rows = conn.execute("SELECT f.ext FROM entry_file ef JOIN file f ON f.id = ef.file_id"
                        " WHERE ef.entry_id = ? AND f.state = 'present'", (entry_id,))
    return any((ext or "").casefold() in extensions for ext, in rows)


def find_chains(registry: Registry, definitions: DefinitionSet, type_id: str, tags: set[str],
                source_env_type: str, target_env_type: str, tools: dict[str, str] | None = None,
                *, ready_only: bool = True, first: Callable[[ProcessPackage], bool] | None = None) -> list[list[str]]:
    """Ready process chains from (type, environment) to the target environment, shortest first.
    ``ready_only=False`` searches every package, ready or not (from manifests alone). ``first`` says
    whether a package can start a chain (it can read the source entry); a package it refuses is
    skipped, so a longer chain is still found."""
    usable = [p for p in registry.packages.values()
              if p.id != COPY_PROCESS and (not ready_only or ready(p, tools))]
    found: list[list[str]] = []
    frontier: list[tuple[list[str], str, str]] = [([], type_id, source_env_type)]
    for depth in range(MAX_CHAIN):
        next_frontier = []
        for chain, current_type, current_env in frontier:
            for package in usable:
                if package.id in chain or not matches(package, definitions, current_type, tags, current_env, None,
                                                      check_tags=not chain):
                    continue
                if not chain and first is not None and not first(package):
                    continue
                m = package.manifest
                out_env = current_env if m.output_environment == "same" else m.output_environment
                out_type = m.output_dossier_type or current_type
                step = [*chain, package.id]
                if out_env == target_env_type:
                    found.append(step)
                elif depth + 1 < MAX_CHAIN:
                    next_frontier.append((step, out_type, out_env))
        if found:
            return found  # the shortest chains only
        frontier = next_frontier
    return found


def routes(conn: sqlite3.Connection, definitions: DefinitionSet, registry: Registry, uid: str,
           environment_id: int, tools: dict[str, str] | None = None) -> list[dict]:
    """The ways to get a dossier into an environment: [{route, processes, source_entry_id, source}]."""
    dossier = conn.execute("SELECT * FROM dossier_effective WHERE uid = ?", (uid,)).fetchone()
    if dossier is None:
        raise PlanError(f"no dossier {uid}")
    target = repo.get_environment(conn, environment_id)
    if target is None:
        raise PlanError(f"no environment {environment_id}")
    tags = repo.effective_tags(conn, uid)
    tools = tool_paths() if tools is None else tools
    out = []
    for entry in _entries(conn, uid):
        label = f"{entry['env_name']} · {entry['container'] or '(root)'} ({entry['status']})"
        if entry["environment_id"] == environment_id:
            copy = registry.packages.get(COPY_PROCESS)
            if copy is not None and ready(copy, tools):
                out.append({"route": "copy", "processes": [COPY_PROCESS], "source_entry_id": entry["id"],
                            "source": label})
        for chain in find_chains(registry, definitions, dossier["type_id"], tags, entry["env_type"],
                                 target["type_id"], tools,
                                 first=lambda p, entry_id=entry["id"]: can_read(conn, p, entry_id)):
            out.append({"route": "convert", "processes": chain, "source_entry_id": entry["id"], "source": label})
    return out


def grants(registry: Registry, chain: list[str], role: str) -> bool:
    """Whether a chain's last process grants ``role`` (casefolded)."""
    return role in {r.casefold() for r in registry.packages[chain[-1]].manifest.roles}


def for_role(registry: Registry, options: list[dict], role: str | None) -> list[dict]:
    """The routes that give a dossier ``role`` (casefolded): convert chains that grant it, never a
    copy, which leaves the asset what it was. With no role, every route."""
    if role is None:
        return options
    return [o for o in options if o["route"] == "convert" and grants(registry, o["processes"], role)]


def plan_requisition(conn: sqlite3.Connection, definitions: DefinitionSet, registry: Registry, uid: str,
                     environment_id: int, *, processes: list[str] | None = None, source_entry_id: int | None = None,
                     params: dict[str, Any] | None = None, defaults: dict[str, Any] | None = None,
                     endpoint_folder: str | None = None,
                     on_collision: str = "ask", name: str | None = None,
                     tools: dict[str, str] | None = None, role: str | None = None) -> Plan:
    """Plan getting a dossier (or a whole product) into an environment.

    ``processes`` picks a chain (otherwise the first route found, preferring conversion from the
    origin); ``params`` sets options, as ``{"size": 512}`` (any process with that option) or
    ``{"convert_mesh.format": "obj"}``. ``defaults`` (a preset, last-used options) are the same
    shape but lenient: options a process does not have, or values it would reject, are dropped.
    ``role`` (casefolded) keeps only the routes that grant it, for the dossier and each child.
    """
    dossier = conn.execute("SELECT * FROM dossier_effective WHERE uid = ?", (uid,)).fetchone()
    if dossier is None:
        raise PlanError(f"no dossier {uid}")
    if on_collision not in ("ask", "overwrite", "rename", "skip"):
        raise PlanError(f"on_collision must be ask, overwrite, rename or skip")
    name = name or dossier["name"]
    endpoint = default_endpoint(conn, definitions, environment_id, name, endpoint_folder)
    tools = tool_paths() if tools is None else tools
    children = conn.execute("SELECT uid FROM dossier_effective WHERE parent_id = ? ORDER BY lower(name)",
                            (dossier["id"],)).fetchall()
    subjects = [uid] + [c[0] for c in children]
    items = []
    for subject in subjects:
        item = _plan_item(conn, definitions, registry, subject, environment_id, processes,
                          source_entry_id if subject == uid else None, params or {}, tools, defaults or {}, role)
        if subject == uid and children and item.route == "none":
            continue  # a product with no process of its own: its children carry the plan
        items.append(item)
    plan = Plan(name, environment_id, endpoint, items, on_collision)
    if not any(i.include for i in items):
        plan.warnings.append("nothing here can be requisitioned to this environment with the processes that are ready")
    _warnings(conn, plan, subjects)
    return plan


def _options(manifest, process_id: str, given: dict[str, Any]) -> dict[str, Any]:
    own = {k.split(".", 1)[1]: v for k, v in given.items() if k.startswith(f"{process_id}.")}
    shared = {k: v for k, v in given.items() if "." not in k and manifest.parameter(k) is not None}
    return {**shared, **own}


def _lenient(manifest, values: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for key, value in values.items():
        parameter = manifest.parameter(key)
        if parameter is None:
            continue
        try:
            out[key] = parameter.check(value)
        except ValueError:
            continue
    return out


def _plan_item(conn, definitions, registry, uid, environment_id, wanted, source_entry_id, params, tools,
               defaults=None, role=None) -> PlanItem:
    d = conn.execute("SELECT name, type_id FROM dossier_effective WHERE uid = ?", (uid,)).fetchone()
    options = for_role(registry, routes(conn, definitions, registry, uid, environment_id, tools), role)
    if source_entry_id is not None:
        options = [o for o in options if o["source_entry_id"] == source_entry_id]
    if wanted:
        options = [o for o in options if o["processes"] == list(wanted)]
    options.sort(key=lambda o: o["route"] != "convert")  # convert from the source unless asked to copy
    if not options:
        why = "no ready process takes it there" if not wanted else f"{' → '.join(wanted)} does not take it there"
        return PlanItem(uid, d["name"], d["type_id"], None, "", "none", [], include=False, problems=[why])
    chosen = options[0]
    values: dict[str, dict[str, Any]] = {}
    problems = []
    for process_id in chosen["processes"]:
        manifest = registry.get(process_id).manifest
        soft = _lenient(manifest, _options(manifest, process_id, defaults or {}))
        try:
            values[process_id] = manifest.resolve({**soft, **_options(manifest, process_id, params)})
        except ValueError as exc:
            problems.append(str(exc))
    return PlanItem(uid, d["name"], d["type_id"], chosen["source_entry_id"], chosen["source"], chosen["route"],
                    chosen["processes"], values, include=not problems, problems=problems)


def _warnings(conn: sqlite3.Connection, plan: Plan, uids: list[str]) -> None:
    for uid in uids:
        fields = repo.effective_fields(conn, uid)
        name = conn.execute("SELECT name FROM dossier_effective WHERE uid = ?", (uid,)).fetchone()[0]
        if plan.endpoint.visibility == "publishable" and str(fields.get("redistribution", "")).lower() in ("no", "false"):
            plan.warnings.append(f"{name} may not be redistributed, and this endpoint is publishable")
        for ref, in conn.execute(
                "SELECT x.reference FROM dossier_dependency x JOIN dossier d ON d.id = x.dossier_id"
                " WHERE d.uid = ? AND x.status = 'broken'", (uid,)):
            plan.warnings.append(f"{name} needs {ref}, which is missing")


def queue_plan(conn: sqlite3.Connection, plan: Plan, registry: Registry) -> int:
    """Add a plan to the queue; returns the requisition id."""
    included = [i for i in plan.items if i.include]
    if not included:
        raise PlanError("nothing in this plan is included")
    with repo.transaction(conn):
        position = conn.execute("SELECT COALESCE(max(position), 0) + 1 FROM requisition").fetchone()[0]
        cur = conn.execute(
            "INSERT INTO requisition (uid, name, state, position, environment_id, endpoint, on_collision, created_at)"
            " VALUES (?, ?, 'queued', ?, ?, ?, ?, ?)",
            (repo.new_uid(), plan.name, position, plan.environment_id, plan.endpoint.to_json(), plan.on_collision,
             repo.now()))
        requisition_id = cur.lastrowid
        conn.executemany(
            "INSERT INTO requisition_item (requisition_id, dossier_uid, source_entry_id, processes, params, include, state)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(requisition_id, i.dossier_uid, i.source_entry_id,
              json.dumps([{"id": p, "version": registry.get(p).manifest.version} for p in i.processes]),
              json.dumps(i.params), int(i.include), "queued" if i.include else "skipped") for i in plan.items])
    return requisition_id
