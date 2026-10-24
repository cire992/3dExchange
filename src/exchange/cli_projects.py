"""``exchange project``: create, validate and checkpoint project homes (Roadmap phase 7)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from exchange.projects import git as project_git
from exchange.projects.home import KINDS, find_home, init_home, load_home, read_config, resolve_project, write_config
from exchange.projects.validate import validate_home

COMMANDS = ("project",)


def add_parsers(commands, common: argparse.ArgumentParser) -> None:
    project = commands.add_parser(
        "project", help="project homes: create, validate, checkpoint",
        description="Project homes are git-tracked folders of plain files: identity, goals, records and "
        "claims. Commands use --project (a path, or a name under the projects root), else the project "
        "home holding the current folder, else the default project.")
    actions = project.add_subparsers(dest="action", required=True)

    def chosen(p: argparse.ArgumentParser) -> None:
        p.add_argument("--project", metavar="PATH_OR_NAME",
                       help="the project home (default: the one holding the current folder, else the default)")

    init = actions.add_parser("init", parents=[common], help="create a project home in a new or empty folder")
    init.add_argument("path", type=Path)
    init.add_argument("--name", help="the project's name (default: the folder's)")
    init.add_argument("--kind", choices=KINDS, default="unreal")
    init.add_argument("--no-git", action="store_true", help="do not create the git repository")

    validate = actions.add_parser(
        "validate", parents=[common], help="check every file and link; list errors, warnings and gaps",
        description="Check the project home's files against their formats and record schemas, and resolve "
        "every link (dossier links against the library database, read-only). Exits with 1 when there "
        "are errors.")
    chosen(validate)

    checkpoint = actions.add_parser(
        "checkpoint", parents=[common], help="commit every change in the project home",
        description="Commit every change in the project home (except .exchange/), as before a bypassed "
        "agent session. Never makes an empty commit.")
    chosen(checkpoint)
    checkpoint.add_argument("--for", dest="for_path", type=Path, metavar="PATH",
                            help="the project home holding PATH; prints project null when there is none")
    checkpoint.add_argument("--reason", default="", help="why, for the commit message")

    config = actions.add_parser("config", parents=[common], help="show or set the projects root and default project")
    config.add_argument("--root", help="the folder holding project homes ('' clears it)")
    config.add_argument("--default", help="the default project: a name under the root, or a path ('' clears it)")
    config.add_argument("--git-name", help="the name project homes commit with when git has none ('' clears it)")
    config.add_argument("--git-email", help="the email project homes commit with when git has none ('' clears it)")


def _emit(args, data, text: str) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False, default=str) if args.json else text)


def run(args, definitions) -> int:
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
        if args.json:
            print(json.dumps(report.to_json(), indent=2, ensure_ascii=False, default=str))
        else:
            print(_report_text(report))
        return 1 if report.errors else 0
    raise AssertionError(action)


def _report_text(report) -> str:
    home = report.home
    lines = [f"{home.name} ({home.kind}), {home.path}: {len(report.records)} records, "
             f"{len(report.claims)} claims, {len(report.goals)} goals"]
    for title, items in (("Errors", report.errors), ("Warnings", report.warnings)):
        if items:
            lines.append(f"{title} ({len(items)}):")
            lines += [f"  {f.path}: {f.message}" for f in items]
    if report.gaps:
        lines.append(f"Gaps ({len(report.gaps)}):")
        lines += [f"  {g.target} ← {g.needed_by}: {g.message}" for g in report.gaps]
    if len(lines) == 1:
        lines.append("No problems found.")
    return "\n".join(lines)
