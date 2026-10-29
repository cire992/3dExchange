"""Command line: scan, rescan, enrich, environments, discovery, search and show.

Curation commands (classify, lexicon, suggest, curate, collection, history, undo) are in
``cli_curation``.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path

from exchange import __version__
from exchange.db import open_library, open_library_readonly
from exchange.db import repository as repo
from exchange.definitions import load_definitions
from exchange.errors import ExchangeError, ScanError
from exchange.paths import default_db_path
from exchange.scanner.scan import DEFAULT_THRESHOLD, ProgressEvent, ScanReport, run_rescan, run_scan

VISIBILITIES = ("personal", "publishable")


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--db", type=Path, default=None,
                        help=f"library database (default: {default_db_path()})")
    common.add_argument("--definitions", type=Path, action="append", default=[], metavar="DIR",
                        help="extra definitions folder (environments/, dossier_types/); repeatable")
    common.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD,
                        help=f"confidence below which dossiers are Unidentified (default: {DEFAULT_THRESHOLD})")
    common.add_argument("--json", action="store_true", help="print JSON instead of text")

    parser = argparse.ArgumentParser(
        prog="exchange", description="Manage 3D assets across game, engine and library environments.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    def scanning(p: argparse.ArgumentParser) -> None:
        p.add_argument("--no-enrich", action="store_true",
                       help="stop after identification (phase 2); skip hashing, thumbnails, ...")
        p.add_argument("--progress-json", action="store_true",
                       help="stream progress as JSON lines on stdout (for the desktop app)")

    scan = commands.add_parser(
        "scan", parents=[common], help="detect environments in a folder and index them (read-only)",
        description="Detect the environments in FOLDER and index them: discovery, identification "
        "and enrichment. The folder is only read, never written to.")
    scan.add_argument("folder", type=Path)
    scan.add_argument("--dry-run", action="store_true",
                      help="detect environments and count files only; write nothing")
    scanning(scan)

    rescan = commands.add_parser("rescan", parents=[common],
                                 help="rescan known environments (only what changed is reprocessed)")
    rescan.add_argument("--env", type=int, action="append", metavar="ID", help="only this environment")
    scanning(rescan)

    enrich = commands.add_parser("enrich", parents=[common], help="run scan phase 3 again")
    enrich.add_argument("--env", type=int, action="append", metavar="ID", help="only this environment")
    enrich.add_argument("--progress-json", action="store_true", help=argparse.SUPPRESS)

    env = commands.add_parser("env", help="list and configure environments")
    env_commands = env.add_subparsers(dest="env_command", required=True)
    env_commands.add_parser("list", parents=[common], help="list environments")
    show_env = env_commands.add_parser("show", parents=[common], help="show one environment")
    show_env.add_argument("id", type=int)
    config = env_commands.add_parser("config", parents=[common], help="change an environment's settings")
    config.add_argument("id", type=int)
    config.add_argument("--ignore-add", action="append", default=[], metavar="GLOB",
                        help="ignore files matching GLOB (relative to each root); repeatable")
    config.add_argument("--ignore-remove", action="append", default=[], metavar="GLOB")
    config.add_argument("--profile", help="MO2 profile to use")
    config.add_argument("--visibility", choices=VISIBILITIES, help="endpoint visibility")
    config.add_argument("--endpoint", help="where requisitions will write (used from Roadmap phase 4)")
    add = env_commands.add_parser(
        "add", parents=[common], help="register a folder as an environment of a given type (nothing is read)")
    add.add_argument("path", type=Path)
    add.add_argument("--type", required=True, metavar="TYPE", help="environment definition id, e.g. daz_studio")
    add.add_argument("--name")
    add.add_argument("--profile", help="MO2 profile to use")
    add.add_argument("--visibility", choices=VISIBILITIES)
    add.add_argument("--ignore-add", action="append", default=[], metavar="GLOB")
    exclude = env_commands.add_parser("exclude", parents=[common], help="never index this folder")
    exclude.add_argument("path", type=Path)
    exclude.add_argument("--undo", action="store_true", help="index it again")
    forget = env_commands.add_parser(
        "forget", parents=[common],
        help="remove an environment from the library (nothing on disk changes)")
    forget.add_argument("id", type=int)
    forget.add_argument("--yes", action="store_true", help="do it; without this, only say what would go")

    from exchange import cli_claims, cli_curation, cli_projects, cli_requisitions, cli_service

    cli_curation.add_parsers(commands, common)
    cli_requisitions.add_parsers(commands, common)
    cli_service.add_parsers(commands, common)
    cli_projects.add_parsers(commands, common)
    cli_claims.add_parsers(commands, common)

    commands.add_parser("discover", parents=[common],
                        help="list environments found on this PC (Steam, Epic, Unreal, Daz, MO2)")

    search = commands.add_parser("search", parents=[common], help="search the library")
    search.add_argument("query", nargs="?", default="")
    search.add_argument("--group", choices=("product", "type", "all"), default="all")
    search.add_argument("--env", type=int, metavar="ID")
    search.add_argument("--limit", type=int, default=50)

    show = commands.add_parser("show", parents=[common], help="show one dossier")
    show.add_argument("uid")
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")  # paths may not fit the console code page
    args = build_parser().parse_args(argv)
    args.db = args.db or default_db_path()
    try:
        definitions = load_definitions(args.definitions)
        from exchange import cli_claims, cli_curation, cli_projects, cli_requisitions, cli_service

        if args.command in cli_curation.COMMANDS:
            return cli_curation.run(args, definitions)
        if args.command in cli_requisitions.COMMANDS:
            return cli_requisitions.run(args, definitions)
        if args.command in cli_service.COMMANDS:
            return cli_service.run(args, definitions)
        if args.command in cli_projects.COMMANDS:
            return cli_projects.run(args, definitions)
        if args.command in cli_claims.COMMANDS:
            return cli_claims.run(args, definitions)
        handler = _HANDLERS[args.command]
        return handler(args, definitions)
    except ExchangeError as exc:
        print(f"exchange: error: {exc}", file=sys.stderr)
        return 2


def _emit(args, data, text: str) -> None:
    if getattr(args, "progress_json", False):
        print(json.dumps({"event": "result", "data": data}, ensure_ascii=False, default=str), flush=True)
    elif args.json:
        print(json.dumps(data, indent=2, ensure_ascii=False, default=str))
    else:
        print(text)


def _progress(args):
    if getattr(args, "progress_json", False):
        def emit(event: ProgressEvent) -> None:
            print(json.dumps({"event": "progress", **dataclasses.asdict(event)}, ensure_ascii=False),
                  flush=True)
        return emit
    if sys.stderr.isatty() and not args.json:
        def show(event: ProgressEvent) -> None:
            count = f" {event.done}/{event.total}" if event.total else ""
            sys.stderr.write(f"\r  phase {event.phase}: {event.environment}: {event.step}{count}\x1b[K")
            sys.stderr.flush()
        return show
    return None


def _done_progress(args) -> None:
    if sys.stderr.isatty() and not args.json and not getattr(args, "progress_json", False):
        sys.stderr.write("\r\x1b[K")


# Commands ---------------------------------------------------------------------------------------


def _scan(args, definitions) -> int:
    report = run_scan(args.folder, db_path=args.db, definitions=definitions, dry_run=args.dry_run,
                      threshold=args.threshold, enrich=not args.no_enrich, progress=_progress(args))
    _done_progress(args)
    _emit(args, dataclasses.asdict(report), format_report(report))
    return 0


def _rescan(args, definitions) -> int:
    report = run_rescan(db_path=args.db, definitions=definitions, environment_ids=args.env,
                        threshold=args.threshold, enrich=not args.no_enrich, progress=_progress(args))
    _done_progress(args)
    _emit(args, dataclasses.asdict(report), format_report(report))
    return 0


def _enrich(args, definitions) -> int:
    from exchange.scanner.enrichment import enrich_environment

    conn = open_library(args.db)
    try:
        envs = repo.list_environments(conn)
        wanted = set(args.env) if args.env else {e["id"] for e in envs}
        missing = wanted - {e["id"] for e in envs}
        if missing:
            raise ScanError(f"no environment with id {', '.join(map(str, sorted(missing)))}")
        results = {}
        for env in envs:
            if env["id"] in wanted:
                stats = enrich_environment(conn, env["id"], definitions=definitions,
                                           db_path=args.db.resolve(), progress=_progress(args),
                                           name=env["name"])
                results[env["name"]] = dataclasses.asdict(stats)
    finally:
        conn.close()
    _done_progress(args)
    _emit(args, results, "\n".join(f"{name}\n  {_enrich_line(s)}" for name, s in results.items()))
    return 0


def _env(args, definitions) -> int:
    conn = open_library(args.db)
    try:
        return _ENV_HANDLERS[args.env_command](args, definitions, conn)
    finally:
        conn.close()


def _env_list(args, definitions, conn) -> int:
    rows = []
    for env in repo.list_environments(conn):
        roots = repo.list_roots(conn, env["id"])
        rows.append({"id": env["id"], "name": env["name"], "type_id": env["type_id"],
                     "roots": [{"path": r["path"], "status": r["status"], "offline_since": r["offline_since"]}
                               for r in roots],
                     "last_scanned_at": env["last_scanned_at"]})
    lines = [f"{r['id']:>3}  {r['name']}  [{r['type_id']}]" + "".join(
        f"\n       {x['path']}" + (f"  (offline since {x['offline_since'][:10]})" if x["status"] == "offline" else "")
        for x in r["roots"]) for r in rows]
    _emit(args, rows, "\n".join(lines) or "No environments yet. Add one with: exchange scan <folder>")
    return 0


def _get_env(conn, env_id: int):
    env = repo.get_environment(conn, env_id)
    if env is None:
        raise ScanError(f"no environment with id {env_id}")
    return env


def _env_show(args, definitions, conn) -> int:
    from exchange.library.query import sidebar

    env = _get_env(conn, args.id)
    info = next(e for e in sidebar(conn, definitions, threshold=args.threshold)["environments"]
                if e["id"] == env["id"])
    data = {**info, "layer_config": json.loads(env["layer_config"]),
            "user_config": json.loads(env["user_config"])}
    lines = [f"{env['name']}  [{env['type_id']}]  {info['count']} dossiers"]
    lines += [f"  root  {r['path']}  ({r['status']})" for r in info["roots"]]
    lines += [f"  settings  {k} = {v}" for k, v in data["user_config"].items()]
    lines += [f"  layer     {k} = {v}" for k, v in data["layer_config"].items()]
    lines += ["  containers"] + [f"    {c['name']}  [{c['kind']}]  {c['count']}" for c in info["containers"]]
    lines += ["  types"] + [f"    {t['name']}  {t['count']}" for t in info["types"]]
    _emit(args, data, "\n".join(lines))
    return 0


def _env_config(args, definitions, conn) -> int:
    env = _get_env(conn, args.id)
    config = repo.user_config(conn, env["id"])
    ignore = list(config.get("ignore", []))
    ignore += [g for g in args.ignore_add if g not in ignore]
    ignore = [g for g in ignore if g not in args.ignore_remove]
    if ignore:
        config["ignore"] = ignore
    else:
        config.pop("ignore", None)
    if args.profile is not None:
        profiles = json.loads(env["layer_config"]).get("profiles")
        if profiles is not None and args.profile not in profiles:
            raise ScanError(f"no MO2 profile {args.profile!r}; known: {', '.join(profiles) or 'none'}")
        config["mo2_profile"] = args.profile
    if args.visibility is not None:
        config["visibility"] = args.visibility
    if args.endpoint is not None:
        config["endpoint"] = args.endpoint
    with repo.transaction(conn):
        repo.set_user_config(conn, env["id"], config)
    note = " (ignore rules apply from the next rescan)" if args.ignore_add or args.ignore_remove else ""
    _emit(args, config, f"{env['name']}: {json.dumps(config, ensure_ascii=False)}{note}")
    return 0


def _env_add(args, definitions, conn) -> int:
    from exchange.environments import register_root

    config = {"mo2_profile": args.profile, "visibility": args.visibility,
              "ignore": args.ignore_add or None}
    with repo.transaction(conn):
        env_id = register_root(conn, definitions, args.path, args.type, name=args.name, config=config)
    env = repo.get_environment(conn, env_id)
    _emit(args, {"id": env_id, "name": env["name"], "type_id": env["type_id"]},
          f"Added {args.path} to {env['name']} [{env['type_id']}] (id {env_id}). "
          f"Scan it with: exchange rescan --env {env_id}")
    return 0


def _env_exclude(args, definitions, conn) -> int:
    from exchange.environments import excluded_roots, set_excluded

    with repo.transaction(conn):
        set_excluded(conn, args.path, not args.undo)
    paths = excluded_roots(conn)
    text = "\n".join(["Excluded folders:", *(f"  {p}" for p in paths)]) if paths else "No folders are excluded."
    _emit(args, paths, text)
    return 0


def _env_forget(args, definitions, conn) -> int:
    env = _get_env(conn, args.id)
    roots = [r["path"] for r in repo.list_roots(conn, env["id"])]
    if not args.yes:
        print(f"Would remove {env['name']} ({', '.join(roots)}) and everything scanned from it from "
              f"the library. Files on disk are not touched; your edits stay in the library. "
              f"Run again with --yes to do it.")
        return 1
    with repo.transaction(conn):
        removed = repo.forget_environment(conn, env["id"])
    _emit(args, {"forgotten": env["id"], "dossiers_removed": removed},
          f"Forgot {env['name']}; {removed} dossiers no longer in any environment were removed.")
    return 0


def _discover(args, definitions) -> int:
    from exchange.autodiscover import discover_sources

    registered = []
    conn = open_library_readonly(args.db)
    if conn is not None:
        registered = [r["path"] for r in repo.list_roots(conn)]
        conn.close()
    found = discover_sources(definitions, registered_roots=registered)
    lines = []
    for f in found:
        kind = f"{f.type_id} {f.confidence:.2f}" if f.type_id else "no definition yet"
        mark = " (already added)" if f.registered else ""
        lines.append(f"  {f.name}  [{kind}]{mark}\n    {f.path}  (via {f.via})")
    _emit(args, [dataclasses.asdict(f) for f in found],
          "\n".join(lines) or "Nothing found. Add folders with: exchange scan <folder>")
    return 0


def _search(args, definitions) -> int:
    from exchange.library.query import list_dossiers
    from exchange.scanner.enrichment import thumbnail_dir

    conn = _read(args.db)
    try:
        page = list_dossiers(conn, definitions, query=args.query, group=args.group,
                             environment_id=args.env, limit=args.limit, threshold=args.threshold,
                             thumbnail_dir=thumbnail_dir(args.db.resolve()))
    finally:
        conn.close()
    lines = [f"{page.total} dossiers" + (f" (showing {len(page.items)})" if page.total > len(page.items) else "")]
    for b in page.items:
        flag = "  ?" if b.unidentified else ""
        lines.append(f"  {b.uid[:12]}  {b.name}  [{b.type_name}]  {', '.join(b.environments)}{flag}")
    _emit(args, dataclasses.asdict(page), "\n".join(lines))
    return 0


def _show(args, definitions) -> int:
    from exchange.library.query import dossier_detail
    from exchange.scanner.enrichment import thumbnail_dir

    conn = _read(args.db)
    try:
        matches = conn.execute("SELECT uid FROM dossier WHERE uid LIKE ?", (args.uid + "%",)).fetchall()
        if len(matches) != 1:
            raise ScanError(f"{len(matches)} dossiers match {args.uid!r}; give more of the uid")
        detail = dossier_detail(conn, definitions, matches[0][0], threshold=args.threshold,
                                thumbnail_dir=thumbnail_dir(args.db.resolve()))
    finally:
        conn.close()
    _emit(args, detail, format_detail(detail))
    return 0


def _read(db: Path):
    conn = open_library_readonly(db)
    if conn is None:
        raise ScanError(f"no library at {db} yet; add one with: exchange scan <folder>")
    return conn


_HANDLERS = {"scan": _scan, "rescan": _rescan, "enrich": _enrich, "env": _env,
             "discover": _discover, "search": _search, "show": _show}
_ENV_HANDLERS = {"list": _env_list, "show": _env_show, "config": _env_config, "add": _env_add,
                 "exclude": _env_exclude, "forget": _env_forget}


# Formatting -------------------------------------------------------------------------------------


def _enrich_line(s: dict) -> str:
    parts = [f"{s['hashed']} hashed", f"{s['thumbnails']} thumbnails"]
    if s["merged"]:
        parts.append(f"{s['merged']} duplicates merged")
    if s["meshes"]:
        parts.append(f"{s['meshes']} meshes measured")
    if s["dependencies"]:
        parts.append(f"{s['dependencies']} dependencies ({s['broken_dependencies']} broken)")
    errors = s["hash_errors"] + s["mesh_errors"] + s["thumbnail_errors"]
    if errors:
        parts.append(f"{errors} files could not be read or decoded")
    return "enriched      " + ", ".join(parts) + (" (cancelled)" if s["cancelled"] else "")


def format_report(report: ScanReport) -> str:
    lines = [f"Scanned {report.folder} (read-only)" if report.folder else "Rescanned known environments (read-only)"]
    lines += [f"  note: {n}" for n in report.notes]
    lines.append("Dry run: nothing written" if report.dry_run else f"Library {report.db_path}")
    lines.append("")
    lines.append(f"Environments ({len(report.environments)})")
    for env in report.environments:
        lines.append(f"  {env.name}  [{env.type_id}" + (", registered" if env.registered else "") + "]")
        for root in env.roots:
            tags = [f"confidence {root.confidence:.2f}"] + ([f"variant {root.variant}"] if root.variant else [])
            lines.append(f"    root          {root.path}  ({', '.join(tags)})")
            if root.status == "offline":
                lines.append(f"      offline for {root.offline_days} days; entries kept")
                continue
            if report.dry_run:
                lines.append(f"      files       {root.files}")
                continue
            stats = root.identification
            lines.append(f"      files       {root.files} ({root.new} new, {root.changed} changed, "
                         f"{root.unchanged} unchanged, {root.gone} gone, {stats.ignored_files} ignored)")
            lines.append(f"      identified  {stats.containers} containers, {stats.products} products, "
                         f"{stats.dossiers} dossiers"
                         + (f", {stats.archives} packed archives" if stats.archives else "")
                         + (f", {stats.retired_entries} entries retired" if stats.retired_entries else ""))
            lines.append(f"      unidentified {stats.below_threshold} below {report.threshold:.2f}, "
                         f"{stats.unattached_files} unattached files")
            lines += [f"      warning: {w}" for w in stats.warnings]
        if env.enrichment is not None:
            lines.append(f"    {_enrich_line(dataclasses.asdict(env.enrichment))}")
    if report.cancelled:
        lines.append("\nCancelled; everything finished before that is saved.")
    if report.links_skipped:
        lines.append(f"\nSkipped {len(report.links_skipped)} links/junctions (not followed)")
    if report.errors:
        lines.append(f"\n{len(report.errors)} paths could not be read:")
        lines += [f"  {e}" for e in report.errors[:20]]
    return "\n".join(lines)


def format_detail(d: dict) -> str:
    lines = [f"{d['name']}" + ("  (renamed)" if d["name_overridden"] else ""),
             f"  {d['type_name']} · confidence {d['confidence']:.2f}" + ("  · Unidentified" if d["unidentified"] else ""),
             f"  uid {d['uid']}"]
    if d["tags"]:
        lines.append(f"  tags  {', '.join(d['tags'])}")
    if d["parent"]:
        lines.append(f"  part of  {d['parent']['name']}")
    for k, v in d["fields"].items():
        lines.append(f"  {k}: {v['value']}" + ("  (yours)" if v["source"] == "user" else ""))
    if d["children"]:
        lines.append(f"  contains ({len(d['children'])})")
        lines += [f"    {c['name']}  [{c['type_id']}]" for c in d["children"]]
    lines.append(f"  ledgers ({len(d['ledgers'])})")
    for ledger in d["ledgers"]:
        lines.append(f"    {ledger['environment']['name']}")
        for e in ledger["entries"]:
            src = f" from {e['source_container']}" if e["source_container"] else ""
            lines.append(f"      {e['container']}  {e['status']}{src}")
            lines += [f"        {f['role']:<8} {f['rel_path']}" for f in e["files"][:5]]
            if len(e["files"]) > 5:
                lines.append(f"        ... and {len(e['files']) - 5} more files")
    if d["dependencies"]:
        broken = sum(x["status"] == "broken" for x in d["dependencies"])
        lines.append(f"  dependencies ({len(d['dependencies'])}, {broken} broken)")
        lines += [f"    {'BROKEN ' if x['status'] == 'broken' else ''}{x['reference']}" for x in d["dependencies"][:10]]
    if d["thumbnail"]:
        lines.append(f"  thumbnail  {d['thumbnail']}")
    return "\n".join(lines)
