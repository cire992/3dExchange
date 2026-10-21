"""Command line: ``exchange scan <folder>``."""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path

from exchange import __version__
from exchange.definitions import load_definitions
from exchange.errors import ExchangeError
from exchange.paths import default_db_path
from exchange.scanner import DEFAULT_THRESHOLD, ScanReport, run_scan


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="exchange", description="Manage 3D assets across game, engine and library environments."
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    scan = commands.add_parser(
        "scan",
        help="detect environments in a folder and index them (read-only)",
        description="Detect the environments in FOLDER, then run scan phase 1 (discovery) and "
        "phase 2 (identification). The folder is only read, never written to.",
    )
    scan.add_argument("folder", type=Path)
    scan.add_argument("--db", type=Path, default=None,
                      help=f"library database (default: {default_db_path()})")
    scan.add_argument("--dry-run", action="store_true",
                      help="detect environments and count files only; write nothing")
    scan.add_argument("--json", action="store_true", help="print the report as JSON")
    scan.add_argument("--definitions", type=Path, action="append", default=[], metavar="DIR",
                      help="extra definitions folder (environments/, dossier_types/); repeatable")
    scan.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD,
                      help="confidence below which dossiers count as Unidentified "
                      f"(default: {DEFAULT_THRESHOLD})")
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")  # paths may not fit the console code page
    args = build_parser().parse_args(argv)
    try:
        definitions = load_definitions(args.definitions)
        report = run_scan(args.folder, db_path=args.db or default_db_path(),
                          definitions=definitions, dry_run=args.dry_run, threshold=args.threshold)
    except ExchangeError as exc:
        print(f"exchange: error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(dataclasses.asdict(report), indent=2, ensure_ascii=False))
    else:
        print(format_report(report))
    return 0


def format_report(report: ScanReport) -> str:
    lines = [f"Scanned {report.folder} (read-only)"]
    lines += [f"  note: {n}" for n in report.notes]
    lines.append("Dry run: nothing written" if report.dry_run else f"Library {report.db_path}")
    lines.append("")
    lines.append(f"Environments ({len(report.environments)})")
    for env in report.environments:
        tags = [env.type_id] + ([f"variant {env.variant}"] if env.variant else []) + (
            ["registered"] if env.registered else [])
        lines.append(f"  {env.name}  [{', '.join(tags)}]  confidence {env.confidence:.2f}")
        lines.append(f"    root          {env.root}")
        if report.dry_run:
            lines.append(f"    files         {env.files}")
            continue
        stats = env.identification
        lines.append(f"    files         {env.files} ({env.new} new, {env.changed} changed, "
                     f"{env.unchanged} unchanged, {env.gone} gone, {stats.ignored_files} ignored)")
        lines.append(f"    identified    {stats.containers} containers, {stats.products} products, "
                     f"{stats.dossiers} dossiers"
                     + (f", {stats.archives} packed archives" if stats.archives else "")
                     + (f", {stats.retired_entries} entries retired" if stats.retired_entries else ""))
        lines.append(f"    unidentified  {stats.below_threshold} dossiers below "
                     f"{report.threshold:.2f}, {stats.unattached_files} unattached files")
        lines += [f"    warning: {w}" for w in stats.warnings]
    if report.links_skipped:
        lines.append(f"\nSkipped {len(report.links_skipped)} links/junctions (not followed)")
    if report.errors:
        lines.append(f"\n{len(report.errors)} paths could not be read:")
        lines += [f"  {e}" for e in report.errors[:20]]
    return "\n".join(lines)
