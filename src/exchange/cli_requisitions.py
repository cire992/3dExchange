"""Command line for pipelines, tools and requisitions (Roadmap phase 4)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from exchange.cli_curation import _emit, _uid
from exchange.db import open_library
from exchange.errors import ExchangeError
from exchange.pipelines.registry import (
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


def add_parsers(commands, common: argparse.ArgumentParser) -> None:
    pipelines = commands.add_parser("pipelines", help="pipeline packages: list, check, install, trust")
    pip = pipelines.add_subparsers(dest="pipelines_command", required=True)
    pip.add_parser("list", parents=[common], help="list pipelines and whether they are ready")
    p = pip.add_parser("show", parents=[common], help="show one pipeline")
    p.add_argument("id")
    pip.add_parser("check", parents=[common], help="check every pipeline's prerequisites")
    p = pip.add_parser("install", parents=[common], help="install a pipeline package folder (then trust it)")
    p.add_argument("folder", type=Path)
    p = pip.add_parser("trust", parents=[common], help="trust an installed pipeline (it runs its own code)")
    p.add_argument("id")

    tools = commands.add_parser("tools", help="where external tools are (Blender, texconv, Daz Studio …)")
    tls = tools.add_subparsers(dest="tools_command", required=True)
    tls.add_parser("list", parents=[common], help="list tool paths")
    p = tls.add_parser("set", parents=[common], help="set a tool's path (no path: forget it)")
    p.add_argument("tool")
    p.add_argument("path", nargs="?")

    req = commands.add_parser("requisition", help="plan, queue and run conversions")
    rq = req.add_subparsers(dest="requisition_command", required=True)
    p = rq.add_parser("routes", parents=[common], help="ways to get an asset into an environment")
    p.add_argument("uid")
    p.add_argument("--env", type=int, required=True, metavar="ID", help="the target environment")
    p = rq.add_parser("plan", parents=[common], help="plan a requisition (and queue it with --queue)")
    p.add_argument("uid", help="an asset or product")
    p.add_argument("--env", type=int, required=True, metavar="ID", help="the target environment")
    p.add_argument("--pipeline", action="append", metavar="ID", help="the pipeline (repeat for a chain)")
    p.add_argument("--source-entry", type=int, metavar="ID", help="convert or copy from this entry")
    p.add_argument("--param", action="append", default=[], metavar="NAME=VALUE",
                   help="an option (NAME or PIPELINE.NAME); repeatable")
    p.add_argument("--endpoint", help="write here instead of the environment's default")
    p.add_argument("--on-collision", choices=("ask", "overwrite", "rename", "skip"), default="ask")
    p.add_argument("--name", help="the requisition's name")
    p.add_argument("--queue", action="store_true", help="add it to the queue")
    p = rq.add_parser("list", parents=[common], help="the queue and finished requisitions")
    p.add_argument("--state", action="append", help="only these states")
    p = rq.add_parser("show", parents=[common], help="one requisition: items, outputs, writes")
    p.add_argument("id")
    p = rq.add_parser("run", parents=[common], help="run the queue (or some requisitions)")
    p.add_argument("ids", nargs="*")
    p.add_argument("--progress-json", action="store_true", help=argparse.SUPPRESS)
    p = rq.add_parser("resume", parents=[common], help="continue after a checkpoint or collision; retry failures")
    p.add_argument("id")
    p.add_argument("--on-collision", choices=("ask", "overwrite", "rename", "skip"))
    for name, text in (("hold", "keep a queued requisition from running"), ("release", "let a held one run")):
        p = rq.add_parser(name, parents=[common], help=text)
        p.add_argument("id")
    p = rq.add_parser("move", parents=[common], help="put a requisition at a place in the queue")
    p.add_argument("id")
    p.add_argument("position", type=int)
    p = rq.add_parser("remove", parents=[common], help="move its output to the recycle folder")
    p.add_argument("id")
    rq.add_parser("check-stale", parents=[common], help="find requisitions whose source or pipeline changed")
    p = rq.add_parser("rebuild", parents=[common], help="queue a stale requisition again")
    p.add_argument("id")

    test = commands.add_parser("test-pipeline", parents=[common],
                               help="run a pipeline folder on one asset into a temporary folder")
    test.add_argument("folder", type=Path)
    test.add_argument("uid")
    test.add_argument("--param", action="append", default=[], metavar="NAME=VALUE")
    test.add_argument("--source-entry", type=int)
    test.add_argument("--out", type=Path, help="where to write (default: a new temporary folder)")


COMMANDS = ("pipelines", "tools", "requisition", "test-pipeline")


def run(args, definitions) -> int:
    handler = {"pipelines": _pipelines, "tools": _tools, "requisition": _requisition,
               "test-pipeline": _test}[args.command]
    return handler(args, definitions)


def _params(pairs: list[str]) -> dict:
    out = {}
    for pair in pairs:
        if "=" not in pair:
            raise ExchangeError(f"--param needs NAME=VALUE, got {pair!r}")
        key, value = pair.split("=", 1)
        out[key.strip()] = value.strip()
    return out


# Pipelines and tools --------------------------------------------------------------------------


def _pipelines(args, definitions) -> int:
    registry = load_registry()
    c = args.pipelines_command
    if c == "list":
        tools = tool_paths()
        rows = [{"id": p.id, "name": p.manifest.name, "version": p.manifest.version, "builtin": p.builtin,
                 "trusted": p.trusted, "ready": ready(p, tools), "path": str(p.path)} for p in registry.packages.values()]
        lines = [f"  {r['id']:<26} {r['version']:<8} {'ready' if r['ready'] else 'untrusted' if not r['trusted'] else 'not ready'}"
                 f"  {r['name']}" for r in rows]
        lines += [f"  problem: {p}" for p in registry.problems]
        _emit(args, {"pipelines": rows, "problems": registry.problems}, "\n".join(lines) or "No pipelines.")
    elif c == "show":
        package = registry.get(args.id)
        m = package.manifest
        status = check_prerequisites(package)
        data = {"id": m.id, "name": m.name, "version": m.version, "author": m.author, "trusted": package.trusted,
                "input": {"dossier_types": m.input_types, "tags": m.input_tags, "environments": m.input_environments,
                          "artifact": m.input_artifact},
                "output": {"environment": m.output_environment, "dossier_type": m.output_dossier_type,
                           "folder": m.output_folder},
                "parameters": [{"id": p.id, "type": p.type, "default": p.default} for p in m.parameters],
                "prerequisites": [s.__dict__ for s in status], "steps": [s.operation for s in m.steps],
                "problems": validate(package)}
        lines = [f"{m.name} {m.version} ({m.id}) by {m.author or '?'}{'' if package.trusted else '  [not trusted]'}",
                 f"  takes {', '.join(m.input_types) or 'any asset'} ({m.input_artifact})"
                 f"{' tagged ' + ', '.join(m.input_tags) if m.input_tags else ''}"
                 f" → {m.output_environment} {m.output_dossier_type}".rstrip(),
                 "  steps: " + " → ".join(s.operation for s in m.steps)]
        lines += [f"  option {p.id} ({p.type}) = {p.default!r}" for p in m.parameters]
        lines += [f"  {'✓' if s.ok else '✗'} {s.label}: {s.detail}" for s in status]
        lines += [f"  problem: {p}" for p in data["problems"] if package.trusted]
        _emit(args, data, "\n".join(lines))
    elif c == "check":
        tools = tool_paths()
        rows = []
        for package in registry.packages.values():
            for s in check_prerequisites(package, tools):
                rows.append({"pipeline": package.id, **s.__dict__})
        _emit(args, rows, "\n".join(f"  {'✓' if r['ok'] else '✗'} {r['pipeline']}: {r['label']} — {r['detail']}"
                                    for r in rows) or "No pipeline has prerequisites.")
    elif c == "install":
        package = install(args.folder)
        lines = ["Installed (not trusted yet):", *[f"  {line}" for line in describe_trust(package)],
                 f"Trust it to run its code: exchange pipelines trust {package.id}"]
        _emit(args, {"id": package.id, "path": str(package.path)}, "\n".join(lines))
    else:
        package = registry.get(args.id)
        trust(package)
        _emit(args, {"id": package.id, "trusted": True},
              "\n".join([f"Trusted {package.id}:", *[f"  {line}" for line in describe_trust(package)]]))
    return 0


def _tools(args, definitions) -> int:
    if args.tools_command == "set":
        if args.path and not Path(args.path).is_file():
            raise ExchangeError(f"not a file: {args.path}")
        set_tool(args.tool, args.path)
    tools = tool_paths()
    _emit(args, tools, "\n".join(f"  {k:<16} {v}" for k, v in sorted(tools.items())) or "No tool paths set.")
    return 0


# Requisitions ---------------------------------------------------------------------------------


def _requisition(args, definitions) -> int:
    from exchange.requisitions import lifecycle
    from exchange.requisitions.plan import plan_requisition, queue_plan, routes
    from exchange.requisitions.runner import run_queue

    registry = load_registry()
    conn = open_library(args.db)
    try:
        c = args.requisition_command
        if c == "routes":
            rows = routes(conn, definitions, registry, _uid(conn, args.uid), args.env)
            _emit(args, rows, "\n".join(f"  {r['route']:<8} {' → '.join(r['pipelines'])}  from {r['source']}"
                                        f" (entry {r['source_entry_id']})" for r in rows)
                  or "No ready pipeline takes it there.")
        elif c == "plan":
            plan = plan_requisition(conn, definitions, registry, _uid(conn, args.uid), args.env,
                                    pipelines=args.pipeline, source_entry_id=args.source_entry,
                                    params=_params(args.param), endpoint_folder=args.endpoint,
                                    on_collision=args.on_collision, name=args.name)
            queued = queue_plan(conn, plan, registry) if args.queue else None
            data = {"name": plan.name, "endpoint": plan.endpoint.__dict__, "warnings": plan.warnings,
                    "items": [i.__dict__ for i in plan.items], "queued": queued}
            lines = [f"{plan.name} → {plan.endpoint.label} ({plan.endpoint.folder}, {plan.endpoint.visibility})"]
            for i in plan.items:
                mark = "[x]" if i.include else "[ ]"
                how = " → ".join(i.pipelines) if i.pipelines else "no pipeline"
                lines.append(f"  {mark} {i.name} ({i.type_id}): {i.route} via {how}"
                             + (f", from {i.source}" if i.source else "")
                             + (f"  {'; '.join(i.problems)}" if i.problems else ""))
                for pipeline, values in i.params.items():
                    if values:
                        lines.append(f"        {pipeline}: " + ", ".join(f"{k}={v!r}" for k, v in values.items()))
            lines += [f"  warning: {w}" for w in plan.warnings]
            lines.append(f"Queued as requisition {queued}; run it with: exchange requisition run" if queued
                         else "Add --queue to queue it.")
            _emit(args, data, "\n".join(lines))
        elif c == "list":
            rows = lifecycle.list_requisitions(conn, tuple(args.state or ()))
            _emit(args, rows, "\n".join(
                f"  {r['id']:>4}  {r['state']:<20} {r['done']}/{r['items']}  {r['name']} → {r['environment']}"
                + (f"  ({r['message']})" if r["message"] else "") for r in rows) or "No requisitions.")
        elif c == "show":
            d = lifecycle.detail(conn, args.id)
            lines = [f"{d['name']} [{d['state']}] → {d['endpoint']['label']} ({d['endpoint']['folder']})"]
            if d["message"]:
                lines.append(f"  {d['message']}")
            for i in d["items"]:
                lines.append(f"  {i['state']:<16} {i['name']}: {' → '.join(p['id'] for p in i['pipelines'])}"
                             + (f"  ({i['message']})" if i["message"] else ""))
                for out in i["outputs"]:
                    lines += [f"      {Path(out['endpoint']).joinpath(*f.split('/'))}" for f in out["files"][:10]]
                    if len(out["files"]) > 10:
                        lines.append(f"      … and {len(out['files']) - 10} more")
            _emit(args, d, "\n".join(lines))
        elif c == "run":
            progress = None
            if args.progress_json:
                def progress(event: dict) -> None:
                    print(json.dumps(event, ensure_ascii=False, default=str), flush=True)
            elif not args.json:
                def progress(event: dict) -> None:
                    print(f"  {event['requisition']} · {event['item']} · [{event['step']}] {event['message']}",
                          file=sys.stderr, flush=True)
            conn.close()  # the runner opens its own connection
            ran = run_queue(args.db, definitions, registry, only=[int(i) for i in args.ids] or None, progress=progress)
            conn = open_library(args.db)
            rows = [lifecycle.detail(conn, i) for i in ran]
            _emit(args, {"ran": [{"id": r["id"], "state": r["state"], "message": r["message"]} for r in rows]},
                  "\n".join(f"  {r['id']:>4}  {r['state']}  {r['name']}" + (f"  ({r['message']})" if r["message"] else "")
                            for r in rows) or "Nothing queued.")
        elif c == "resume":
            lifecycle.resume(conn, args.id, args.on_collision)
            _emit(args, {"id": args.id}, f"Requisition {args.id} is queued again; run it with: exchange requisition run")
        elif c in ("hold", "release"):
            lifecycle.hold(conn, args.id, held=c == "hold")
            _emit(args, {"id": args.id}, f"Requisition {args.id} {'held' if c == 'hold' else 'released'}")
        elif c == "move":
            lifecycle.move(conn, args.id, args.position)
            _emit(args, {"id": args.id}, f"Requisition {args.id} moved to {args.position}")
        elif c == "remove":
            moved = lifecycle.remove(conn, Path(args.db), definitions, args.id)
            _emit(args, {"moved": moved}, f"Moved {moved} files to the recycle folder")
        elif c == "check-stale":
            found = lifecycle.check_stale(conn, registry)
            _emit(args, [{"id": i, "why": w} for i, w in found],
                  "\n".join(f"  {i:>4}  stale: {w}" for i, w in found) or "Nothing is stale.")
        else:
            new_id = lifecycle.rebuild(conn, registry, args.id)
            _emit(args, {"id": new_id}, f"Queued the rebuild as requisition {new_id}")
        return 0
    finally:
        conn.close()


def _test(args, definitions) -> int:
    import tempfile

    from exchange.db import open_library_readonly
    from exchange.requisitions.runner import test_pipeline

    out = args.out or Path(tempfile.mkdtemp(prefix="exchange-test-"))
    conn = open_library_readonly(args.db)
    if conn is None:
        raise ExchangeError(f"no library at {args.db}")
    lines: list[str] = []
    try:
        written = test_pipeline(conn, args.folder, _uid(conn, args.uid), out, _params(args.param), args.source_entry,
                                log=lambda step, message: lines.append(f"  [{step}] {message}"))
    finally:
        conn.close()
    _emit(args, {"out": str(out), "files": [str(p) for p in written]},
          "\n".join([*lines, f"Output in {out / 'output'}"]))
    return 0
