"""The service's jobs API, part 2 (Roadmap phase 6g): requisitions, process packages and their
prerequisites, presets and endpoints, as the PySide6 window's *Requisition to…* dialog, its queue
view and Settings › Processes and Endpoints use them.

- **Planning** only reads: ``/requisitions/plan`` returns what the dialog's plan tree and option
  forms show. ``/requisitions/queue`` plans the same request again on the server and queues it, so
  a client never sends a plan to trust. Options come from the request, over a preset's or those
  last used with each process; queueing remembers them as last used.
- **Running** the queue, and removing a requisition's output (which rescans), are jobs
  (``jobs.py``): worker processes, one writing job at a time.
- **Queue actions** (hold, move, resume, rebuild, check stale) write on the editor's connection and
  wait while a job writes (409).
- **Processes:** trusting a package lets it run its own code; the client asks the user first, with
  what ``trust`` describes. Installing copies a package folder in, untrusted.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException

from exchange.db import repository as repo
from exchange.errors import ExchangeError
from exchange.processes.registry import (
    check_prerequisites,
    describe_trust,
    install,
    load_registry,
    ready,
    set_tool,
    tool_paths,
    trust,
    validate,
)
from exchange.requisitions import lifecycle
from exchange.requisitions.endpoints import EndpointError, default_endpoint
from exchange.requisitions.plan import plan_requisition, queue_plan, routes
from exchange.requisitions.presets import delete_preset, last_used, last_used_params, load_presets, remember, save_preset
from exchange.service import models

MAX_ROUTE_SUBJECTS = 200  # as the window's dialog: routes of at most this many assets and children


class Processes:
    """The process registry, read once and again after installing or trusting a package."""

    def __init__(self) -> None:
        self._registry = None
        self._lock = threading.Lock()

    def registry(self, reload: bool = False):
        with self._lock:
            if reload or self._registry is None:
                self._registry = load_registry()
            return self._registry


def _process_view(package, tools: dict[str, str]) -> dict:
    m = package.manifest
    problems = validate(package) if package.trusted else []
    state = "ready" if package.trusted and not problems and ready(package, tools) else (
        "not trusted" if not package.trusted else "needs setup")
    return {"id": m.id, "name": m.name, "version": m.version, "author": m.author, "description": m.description,
            "builtin": package.builtin, "trusted": package.trusted, "state": state, "path": str(package.path),
            "input_types": list(m.input_types), "input_tags": list(m.input_tags),
            "output_environment": m.output_environment, "output_dossier_type": m.output_dossier_type,
            "prerequisites": [{"id": s.id, "label": s.label, "ok": s.ok, "detail": s.detail,
                               "tool": next((p.tool for p in m.prerequisites if p.id == s.id and p.kind == "tool"), None)}
                              for s in check_prerequisites(package, tools)],
            "problems": problems, "trust": describe_trust(package),
            "parameters": [_parameter(p) for p in m.parameters], "roles": list(m.roles)}


def _parameter(p) -> dict:
    return {"id": p.id, "type": p.type, "default": p.default, "label": p.label or p.id, "help": p.help,
            "choices": list(p.choices), "min": p.min, "max": p.max}


def plan_defaults(registry, preset: str | None) -> dict:
    """The options a plan falls back to: the preset's, or those last used with each process."""
    if preset:
        found = load_presets(registry).get(preset)
        if found is None:
            raise HTTPException(404, f"no preset {preset!r}")
        return found.params()
    return last_used_params(sorted(registry.packages))


def plan_result(plans: list, problems: list[str], registry) -> dict:
    """The ``PlanResult``: the plans, the option forms of their included items, and what is included."""
    names = {p: registry.get(p).manifest.name for plan in plans for i in plan.items for p in i.processes}
    values: dict[str, dict] = {}
    for p in plans:
        for item in p.items:
            if item.include:
                for process, v in item.params.items():
                    values.setdefault(process, v)
    forms = [{"process": process, "name": names[process], "values": v,
              "parameters": [_parameter(x) for x in registry.get(process).manifest.parameters]}
             for process, v in values.items()]
    return {"plans": [{"name": p.name, "environment_id": p.environment_id, "on_collision": p.on_collision,
                       "endpoint": {"folder": p.endpoint.folder, "root": p.endpoint.root,
                                    "visibility": p.endpoint.visibility, "label": p.endpoint.label},
                       "warnings": p.warnings,
                       "items": [{"dossier_uid": i.dossier_uid, "name": i.name, "type_id": i.type_id,
                                  "source_entry_id": i.source_entry_id, "source": i.source, "route": i.route,
                                  "processes": i.processes, "process_names": [names[x] for x in i.processes],
                                  "params": i.params, "include": i.include, "problems": i.problems}
                                 for i in p.items]} for p in plans],
            "problems": problems, "forms": forms,
            "included": sum(1 for p in plans for i in p.items if i.include)}


def _preset_view(preset) -> dict:
    return {"name": preset.name, "description": preset.description, "environment": preset.environment,
            "shipped": preset.shipped, "processes": preset.processes, "options": preset.options}


def register(app: FastAPI, library, jobs, api, errors: dict) -> None:
    prefix = app.state.prefix
    busy = {**errors, 409: {"model": models.Problem}, 503: {"model": models.Problem}}
    processes = Processes()
    library.processes = processes

    def write(fn):
        """On the editor's write connection, never while a job writes."""
        jobs.refuse_while_writing()
        return library.editor.run(lambda curator: fn(curator.conn))

    def requisition(ref: int) -> None:
        try:
            lifecycle.get(library.conn(), ref)
        except ExchangeError as exc:
            raise HTTPException(404, str(exc)) from exc

    # Processes, tools and presets ----------------------------------------------------------------

    @app.get(prefix + "/processes", response_model=models.ProcessList, dependencies=[api], responses=errors,
             tags=["processes"])
    def list_processes() -> dict:
        """Every process package: trusted or not, its prerequisites (green or red with how to fix them),
        its options, and what trusting it allows. Only ready ones are offered for requisitions."""
        registry, tools = processes.registry(), tool_paths()
        return {"processes": [_process_view(p, tools) for p in
                              sorted(registry.packages.values(), key=lambda p: p.manifest.name.casefold())],
                "problems": list(registry.problems)}

    @app.post(prefix + "/processes/{process_id}/trust", response_model=models.ProcessView, dependencies=[api],
              responses=busy, tags=["processes"])
    def trust_process(process_id: str) -> dict:
        """Trust a package as it is now: it may then run its own code. Ask the user first."""
        package = processes.registry().packages.get(process_id)
        if package is None:
            raise HTTPException(404, f"no process {process_id!r}")
        trust(package)
        return _process_view(processes.registry(reload=True).get(process_id), tool_paths())

    @app.post(prefix + "/processes/install", response_model=models.ProcessView, dependencies=[api],
              responses=busy, tags=["processes"])
    def install_process(body: models.FolderJob) -> dict:
        """Copy a package folder into the user's processes folder; it stays untrusted until trusted."""
        folder = Path(body.folder)
        if not folder.is_absolute() or not folder.is_dir():
            raise HTTPException(400, f"not a folder: {body.folder}")
        try:
            package = install(folder)
        except ExchangeError as exc:
            raise HTTPException(409, str(exc)) from exc
        return _process_view(processes.registry(reload=True).get(package.id), tool_paths())

    @app.get(prefix + "/tools", response_model=dict[str, str], dependencies=[api], responses=errors,
             tags=["processes"])
    def get_tools() -> dict:
        """Where the user said external tools are (Blender, texconv, Daz Studio...)."""
        return tool_paths()

    @app.post(prefix + "/tools", response_model=dict[str, str], dependencies=[api], responses=errors,
              tags=["processes"])
    def set_tool_path(body: models.ToolPath) -> dict:
        """Set a tool's path (null forgets it: manifests' likely paths are tried again)."""
        if body.path is not None and not Path(body.path).is_file():
            raise HTTPException(400, f"not a file: {body.path}")
        set_tool(body.tool, body.path)
        return tool_paths()

    @app.get(prefix + "/presets", response_model=list[models.PresetView], dependencies=[api], responses=errors,
             tags=["processes"])
    def list_presets() -> list[dict]:
        """Saved option sets: those shipped in packages, then the user's."""
        presets = load_presets(processes.registry())
        return [_preset_view(presets[n]) for n in sorted(presets, key=str.casefold)]

    @app.post(prefix + "/presets", response_model=models.PresetView, dependencies=[api], responses=busy,
              tags=["processes"])
    def make_preset(body: models.PresetSave) -> dict:
        """Save options (by process) under a name; a user preset of that name is replaced."""
        try:
            return _preset_view(save_preset(body.name, body.options, description=body.description,
                                            environment=body.environment))
        except ExchangeError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.delete(prefix + "/presets/{name}", response_model=list[models.PresetView], dependencies=[api],
                responses=busy, tags=["processes"])
    def remove_preset(name: str) -> list[dict]:
        try:
            delete_preset(name, processes.registry())
        except ExchangeError as exc:
            raise HTTPException(404 if str(exc).startswith("no preset") else 409, str(exc)) from exc
        return list_presets()

    @app.get(prefix + "/presets/last-used", response_model=dict[str, dict[str, Any]], dependencies=[api],
             responses=errors, tags=["processes"])
    def get_last_used() -> dict:
        """The options last queued with each process."""
        return last_used()

    # Endpoints ----------------------------------------------------------------------------------

    @app.get(prefix + "/endpoints", response_model=list[models.EndpointView], dependencies=[api], responses=errors,
             tags=["processes"])
    def list_endpoints() -> list[dict]:
        """Where requisitions write in each environment (Settings › Endpoints): the folder, whether
        the user chose it, and its visibility. Change them with ``/environments/{id}/config``."""
        conn, out = library.conn(), []
        for env in repo.list_environments(conn):
            config = repo.user_config(conn, env["id"])
            row = {"environment_id": env["id"], "environment": env["name"], "type_id": env["type_id"],
                   "custom": bool(config.get("endpoint")), "visibility": config.get("visibility", "personal"),
                   "folder": None, "label": None, "problem": None}
            try:
                endpoint = default_endpoint(conn, library.definitions, env["id"], "<name>")
                row.update(folder=endpoint.folder, label=endpoint.label)
            except EndpointError as exc:
                row["problem"] = str(exc)
            out.append(row)
        return out

    # Planning and queueing ----------------------------------------------------------------------

    @app.post(prefix + "/requisitions/routes", response_model=list[models.RouteChoice], dependencies=[api],
              responses=errors, tags=["requisitions"])
    def route_choices(body: models.RoutesRequest) -> list[dict]:
        """The chains of processes that take these assets (and products' children) into an
        environment: the dialog's route list (besides Automatic)."""
        conn, registry = library.conn(), processes.registry()
        if repo.get_environment(conn, body.environment) is None:
            raise HTTPException(404, f"no environment {body.environment}")
        subjects = list(body.uids)
        for uid in body.uids[:20]:
            row = conn.execute("SELECT id FROM dossier_effective WHERE uid = ?", (uid,)).fetchone()
            if row is not None:
                subjects += [r[0] for r in conn.execute("SELECT uid FROM dossier_effective WHERE parent_id = ?"
                                                        " ORDER BY lower(name) LIMIT 50", (row[0],))]
        chains: dict[tuple, dict] = {}
        tools = tool_paths()
        for uid in subjects[:MAX_ROUTE_SUBJECTS]:
            try:
                found = routes(conn, library.definitions, registry, uid, body.environment, tools)
            except ExchangeError:
                continue
            for r in found:
                names = " → ".join(registry.get(p).manifest.name for p in r["processes"])
                chains.setdefault(tuple(r["processes"]), {"processes": r["processes"], "route": r["route"],
                                                          "label": ("Copy: " if r["route"] == "copy" else "") + names})
        return list(chains.values())

    def make_plans(body: models.PlanRequest) -> tuple[list, list[str]]:
        conn, registry = library.conn(), processes.registry()
        if repo.get_environment(conn, body.environment) is None:
            raise HTTPException(404, f"no environment {body.environment}")
        defaults = plan_defaults(registry, body.preset)
        typed = {f"{p}.{k}": v for p, values in body.options.items() for k, v in values.items()}
        plans, problems = [], []
        for uid in body.uids:
            try:
                plan = plan_requisition(conn, library.definitions, registry, uid, body.environment,
                                        processes=body.processes or None, params=typed, defaults=defaults,
                                        endpoint_folder=body.endpoint_folder, on_collision=body.on_collision,
                                        name=body.name if len(body.uids) == 1 else None)
            except ExchangeError as exc:
                problems.append(str(exc))
                continue
            for item in plan.items:
                if item.dossier_uid in body.excluded:
                    item.include = False
            plans.append(plan)
            problems += plan.warnings
        return plans, list(dict.fromkeys(problems))

    @app.post(prefix + "/requisitions/plan", response_model=models.PlanResult, dependencies=[api],
              responses=errors, tags=["requisitions"])
    def plan(body: models.PlanRequest) -> dict:
        """Plan getting assets into an environment (nothing is written): per asset, the items (a
        product's children too), each with its process chain, source and problems; the option forms
        for the processes in it; and warnings."""
        plans, problems = make_plans(body)
        return plan_result(plans, problems, processes.registry())

    @app.post(prefix + "/requisitions/queue", response_model=models.Queued, dependencies=[api], responses=busy,
              tags=["requisitions"])
    def queue(body: models.PlanRequest) -> dict:
        """Plan this request again and queue every plan with something included; the options become
        each process's last used. Run them with ``/jobs/requisitions``."""
        plans, _ = make_plans(body)
        plans = [p for p in plans if any(i.include for i in p.items)]
        if not plans:
            raise HTTPException(409, "nothing in this plan is included")
        registry = processes.registry()
        ids = write(lambda conn: [queue_plan(conn, p, registry) for p in plans])
        options: dict = {}
        for p in plans:
            for item in p.items:
                if item.include:
                    options.update(item.params)
        remember(options)
        return {"ids": ids}

    # The queue ----------------------------------------------------------------------------------

    @app.get(prefix + "/requisitions", response_model=list[models.RequisitionRow], dependencies=[api],
             responses=errors, tags=["requisitions"])
    def list_requisitions() -> list[dict]:
        """The queue (waiting or running, in order), then finished requisitions, newest first."""
        return lifecycle.list_requisitions(library.conn())

    @app.get(prefix + "/requisitions/{requisition_id}", response_model=models.RequisitionDetail,
             dependencies=[api], responses=errors, tags=["requisitions"])
    def get_requisition(requisition_id: int) -> dict:
        """One requisition: its items (with outputs) and every file it wrote."""
        requisition(requisition_id)
        return lifecycle.detail(library.conn(), requisition_id)

    @app.post(prefix + "/requisitions/{requisition_id}/hold", response_model=models.RequisitionDetail,
              dependencies=[api], responses=busy, tags=["requisitions"])
    def hold(requisition_id: int, body: models.HoldRequest) -> dict:
        """Keep a queued requisition from running (``held`` false lets it run again)."""
        requisition(requisition_id)
        write(lambda conn: lifecycle.hold(conn, requisition_id, body.held))
        return lifecycle.detail(library.conn(), requisition_id)

    @app.post(prefix + "/requisitions/{requisition_id}/move", response_model=models.RequisitionDetail,
              dependencies=[api], responses=busy, tags=["requisitions"])
    def move(requisition_id: int, body: models.MoveRequest) -> dict:
        """Put a waiting requisition at a place in the queue (1 is first)."""
        requisition(requisition_id)
        write(lambda conn: lifecycle.move(conn, requisition_id, body.position))
        return lifecycle.detail(library.conn(), requisition_id)

    @app.post(prefix + "/requisitions/{requisition_id}/resume", response_model=models.RequisitionDetail,
              dependencies=[api], responses=busy, tags=["requisitions"])
    def resume(requisition_id: int, body: models.ResumeRequest) -> dict:
        """Queue it again after a checkpoint or a collision (with how to settle collisions); failed
        items are retried. Run the queue to continue."""
        requisition(requisition_id)
        write(lambda conn: lifecycle.resume(conn, requisition_id, body.on_collision))
        return lifecycle.detail(library.conn(), requisition_id)

    @app.post(prefix + "/requisitions/{requisition_id}/rebuild", response_model=models.RequisitionDetail,
              dependencies=[api], responses=busy, tags=["requisitions"])
    def rebuild(requisition_id: int) -> dict:
        """Queue a fulfilled or stale requisition again with the current processes, overwriting its
        output; returns the new requisition."""
        requisition(requisition_id)
        registry = processes.registry()
        new_id = write(lambda conn: lifecycle.rebuild(conn, registry, requisition_id))
        return lifecycle.detail(library.conn(), new_id)

    @app.post(prefix + "/requisitions/check-stale", response_model=list[models.StaleRequisition],
              dependencies=[api], responses=busy, tags=["requisitions"])
    def check_stale() -> list[dict]:
        """Mark fulfilled requisitions whose sources or processes changed as stale; the ones newly found."""
        registry = processes.registry()
        return [{"id": i, "why": why} for i, why in write(lambda conn: lifecycle.check_stale(conn, registry))]

    # Jobs ---------------------------------------------------------------------------------------

    @app.post(prefix + "/jobs/requisitions", response_model=models.Job, dependencies=[api], responses=busy,
              tags=["jobs"])
    def run_queue(body: models.RunRequest) -> dict:
        """Run the queue (or some requisitions) in a worker process (``exchange requisition run``)."""
        for i in body.ids or []:
            requisition(i)
        label = "Running the queue" if not body.ids else f"Running requisition{'s' * (len(body.ids) != 1)} " + \
            ", ".join(map(str, body.ids))
        return jobs.start("requisitions", label, ["requisition", "run", *map(str, body.ids or [])], writes=True).view()

    @app.post(prefix + "/jobs/remove-output", response_model=models.Job, dependencies=[api], responses=busy,
              tags=["jobs"])
    def remove_output(body: models.RemoveRequest) -> dict:
        """Move what a requisition wrote to the recycle folder and put back what it overwrote, then
        rescan the folders it wrote to (``exchange requisition remove``)."""
        requisition(body.requisition)
        return jobs.start("remove", f"Removing the output of requisition {body.requisition}",
                          ["requisition", "remove", str(body.requisition)], writes=True, json_output=True).view()

