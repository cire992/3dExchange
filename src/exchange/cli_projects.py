"""Project homes on the command line (Roadmap phase 7): ``exchange project`` (create, validate,
checkpoint, config), ``exchange capture`` and ``exchange claims``."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from exchange.errors import ExchangeError
from exchange.projects import git as project_git
from exchange.projects.capture import capture
from exchange.projects.claims import acknowledge, sync_gap_claims
from exchange.projects.home import KINDS, find_home, init_home, load_home, read_config, resolve_project, write_config
from exchange.projects.schema import maturity_value
from exchange.projects.validate import CLAIM_SOURCES, CLAIM_STATUSES, validate_home, write_hints

COMMANDS = ("project", "capture", "claims")


def _chosen(p: argparse.ArgumentParser) -> None:
    p.add_argument("--project", metavar="PATH_OR_NAME",
                   help="the project home (default: the one holding the current folder, else the default)")


def add_parsers(commands, common: argparse.ArgumentParser) -> None:
    project = commands.add_parser(
        "project", help="project homes: create, validate, checkpoint",
        description="Project homes are git-tracked folders of plain files: identity, goals, records and "
        "claims. Commands use --project (a path, or a name under the projects root), else the project "
        "home holding the current folder, else the default project.")
    actions = project.add_subparsers(dest="action", required=True)

    init = actions.add_parser("init", parents=[common], help="create a project home in a new or empty folder")
    init.add_argument("path", type=Path)
    init.add_argument("--name", help="the project's name (default: the folder's)")
    init.add_argument("--kind", choices=KINDS, default="unreal")
    init.add_argument("--no-git", action="store_true", help="do not create the git repository")

    validate = actions.add_parser(
        "validate", parents=[common], help="check every file and link; open and update gap claims",
        description="Check the project home's files against their formats and record schemas, and resolve "
        "every link (dossier links against the library database, read-only). Gaps open gap claims, "
        "existing ones are updated, and those whose gap is gone move to review. Exits with 1 when "
        "there are errors.")
    _chosen(validate)
    validate.add_argument("--check-only", action="store_true",
                          help="write nothing: no gap claims, no dossier hints")

    checkpoint = actions.add_parser(
        "checkpoint", parents=[common], help="commit every change in the project home",
        description="Commit every change in the project home (except .exchange/), as before a bypassed "
        "agent session. Never makes an empty commit.")
    _chosen(checkpoint)
    checkpoint.add_argument("--for", dest="for_path", type=Path, metavar="PATH",
                            help="the project home holding PATH; prints project null when there is none")
    checkpoint.add_argument("--reason", default="", help="why, for the commit message")

    config = actions.add_parser("config", parents=[common], help="show or set the projects root and default project")
    config.add_argument("--root", help="the folder holding project homes ('' clears it)")
    config.add_argument("--default", help="the default project: a name under the root, or a path ('' clears it)")
    config.add_argument("--git-name", help="the name project homes commit with when git has none ('' clears it)")
    config.add_argument("--git-email", help="the email project homes commit with when git has none ('' clears it)")

    grab = commands.add_parser(
        "capture", parents=[common], help="turn one line into a Sketch record or an idea claim",
        description="A line starting with an editor ID ('NPC_DockMaster: gruff harbormaster…') creates that "
        "record at Sketch, the rest of the line its prose. Any other line creates an idea claim.")
    grab.add_argument("line", nargs="+", help="the text (quote it, or let the words run on)")
    _chosen(grab)
    grab.add_argument("--on", metavar="EDITOR_ID", help="the record an idea claim is about")
    grab.add_argument("--goal", metavar="G1", help="the goal an idea claim serves")
    grab.add_argument("--maturity", default="sketch", help="a new record's maturity (default: sketch)")

    claims = commands.add_parser("claims", help="list claims, or acknowledge new ones")
    claim_actions = claims.add_subparsers(dest="action", required=True)
    listing = claim_actions.add_parser("list", parents=[common], help="list the project's claims")
    _chosen(listing)
    listing.add_argument("--status", choices=CLAIM_STATUSES, action="append")
    listing.add_argument("--source", choices=CLAIM_SOURCES)
    listing.add_argument("--target", metavar="EDITOR_ID")
    listing.add_argument("--new", action="store_true", help="only claims waiting in triage (triage: new)")
    ack = claim_actions.add_parser("ack", parents=[common], help="mark new claims as seen (triage: seen)")
    _chosen(ack)
    ack.add_argument("ids", nargs="*", help="claim IDs (default: with --all, every new one)")
    ack.add_argument("--all", action="store_true", help="every claim waiting in triage")


def _emit(args, data, text: str) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False, default=str) if args.json else text)


def run(args, definitions) -> int:
    if args.command == "capture":
        return _capture(args)
    if args.command == "claims":
        return _claims(args)
    action = args.action
    if action == "init":
        home, warnings = init_home(args.path, name=args.name, kind=args.kind, git=not args.no_git)
        text = f"Created the project home {home.name} ({home.kind}) in {home.path}"
        text += "".join(f"\nwarning: {w}" for w in warnings)
        _emit(args, {"path": str(home.path), "name": home.name, "kind": home.kind, "warnings": warnings}, text)
        return 0
    if action == "config":
        changes = {k: getattr(args, k) for k in ("root", "default", "git_name", "git_email")
                   if getattr(args, k) is not None}
        config = write_config(**changes) if changes else read_config()
        text = "\n".join(f"{k} = {v}" for k, v in sorted(config.items())) or "Nothing is set."
        _emit(args, config, text)
        return 0
    if action == "checkpoint":
        if args.for_path is not None:
            found = find_home(args.for_path)
            if found is None:
                _emit(args, {"project": None, "committed": False},
                      f"{args.for_path} is not in a project home; nothing to do")
                return 0
            home = load_home(found)
        else:
            home = resolve_project(args.project)
        result = project_git.checkpoint(home.path, args.reason)
        data = {"project": str(home.path), "committed": result.committed, "commit": result.commit,
                "changed": result.changed}
        text = (f"Checkpoint {result.commit[:10]} in {home.path}: {result.changed} changed paths"
                if result.committed else f"Nothing to commit in {home.path}"
                + (f" (HEAD {result.commit[:10]})" if result.commit else ""))
        _emit(args, data, text)
        return 0
    if action == "validate":
        home = resolve_project(args.project)
        report = validate_home(home, db_path=args.db)
        synced = None
        if not args.check_only:
            if report.dossiers_checked or report.dossier_hints:
                write_hints(home, report.dossier_hints)
            synced = sync_gap_claims(home, report)
        if args.json:
            print(json.dumps({**report.to_json(), "claims": synced.to_json() if synced else None},
                             indent=2, ensure_ascii=False, default=str))
        else:
            print(_report_text(report, synced))
        return 1 if report.errors else 0
    raise AssertionError(action)


def _report_text(report, synced) -> str:
    home = report.home
    lines = [f"{home.name} ({home.kind}), {home.path}: {len(report.records)} records, "
             f"{len(report.claims)} claims, {len(report.goals)} goals"]
    for title, items in (("Errors", report.errors), ("Warnings", report.warnings)):
        if items:
            lines.append(f"{title} ({len(items)}):")
            lines += [f"  {f.path}: {f.message}" for f in items]
    if report.gaps:
        lines.append(f"Gaps ({len(report.gaps)}):")
        lines += [f"  {g.message}" for g in report.gaps]
    if synced is not None:
        for title, ids in (("Gap claims opened", synced.opened), ("Gap claims updated", synced.updated),
                           ("Gap claims moved to review (their gap is gone)", synced.resolved)):
            if ids:
                lines.append(f"{title} ({len(ids)}):")
                lines += [f"  claims/{i}.md" for i in ids]
        if synced.dropped:
            lines.append(f"Not reopened, their claims were dropped: {', '.join(synced.dropped)}")
        lines += [f"Problem: {p}" for p in synced.problems]
    if len(lines) == 1:
        lines.append("No problems found.")
    return "\n".join(lines)


def _capture(args) -> int:
    home = resolve_project(args.project)
    level = maturity_value(args.maturity)
    if level is None:
        raise ExchangeError(f"{args.maturity!r} is not a maturity (0-4, or sketch, spec, stub, built, polished)")
    made = capture(home, " ".join(args.line), on=args.on, goal=args.goal, maturity=level)
    rel = made.path.relative_to(home.path).as_posix()
    text = f"{'Record' if made.kind == 'record' else 'Idea claim'} {made.id}: {rel}"
    text += "".join(f"\nwarning: {w}" for w in made.warnings)
    _emit(args, {"kind": made.kind, "id": made.id, "path": str(made.path), "warnings": made.warnings}, text)
    return 0


def _claims(args) -> int:
    home = resolve_project(args.project)
    report = validate_home(home, db_path=None, processes=set())
    if args.action == "ack":
        if not args.ids and not args.all:
            raise ExchangeError("name the claims to acknowledge, or pass --all")
        done = acknowledge(home, report, None if args.all and not args.ids else args.ids)
        _emit(args, {"acknowledged": done}, f"Acknowledged {len(done)} claims" if done else "No new claims")
        return 0
    rows = []
    for claim in sorted(report.claims.values(), key=lambda c: c.id):
        meta = claim.meta
        if args.status and meta.get("status") not in args.status:
            continue
        if args.source and meta.get("source", "manual") != args.source:
            continue
        if args.target and str(meta.get("target", "")).casefold() != args.target.casefold():
            continue
        if args.new and meta.get("triage") != "new":
            continue
        title = meta.get("title") or next((line.strip() for line in claim.body.splitlines() if line.strip()), "")
        rows.append({"id": claim.id, "status": meta.get("status"), "source": meta.get("source", "manual"),
                     "target": meta.get("target"), "triage": meta.get("triage"), "title": title})
    text = "\n".join(f"{'* ' if r['triage'] == 'new' else '  '}{r['id']}  {r['status']}  "
                     f"{r['target'] or '(unfiled)'}  {r['title'][:70]}" for r in rows) or "No claims."
    _emit(args, rows, text)
    return 0
