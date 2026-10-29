"""Command line for claims: add, list, show, close (R3a), walk and whose turn (R3b)."""

from __future__ import annotations

import argparse
import sys

from exchange import claims
from exchange.cli_curation import _emit, _uid
from exchange.db import open_library
from exchange.processes.registry import load_registry, tool_paths


def add_parsers(commands, common: argparse.ArgumentParser) -> None:
    claim = commands.add_parser("claim", help="claims: things you mean to get into a place")
    cl = claim.add_subparsers(dest="claim_command", required=True)
    p = cl.add_parser("add", parents=[common], help="claim a dossier for an environment")
    p.add_argument("uid", help="a dossier uid (or the start of one)")
    p.add_argument("--env", type=int, required=True, metavar="ID", help="the place it should end up")
    p.add_argument("--as", dest="role", metavar="ROLE", help="what it is there, e.g. prop")
    p.add_argument("--folder", help="the folder it should land in")
    p.add_argument("--note", default="", help="the claim's first note")
    p = cl.add_parser("list", parents=[common], help="open claims")
    p.add_argument("--all", action="store_true", help="closed claims too")
    p.add_argument("--turn", choices=("you", "exchange", "build"), help="only claims whose turn it is")
    p = cl.add_parser("show", parents=[common], help="one claim: its keys, milestone and notes")
    p.add_argument("id")
    p = cl.add_parser("close", parents=[common], help="close a claim (it keeps its milestone)")
    p.add_argument("id")
    p.add_argument("--reason", default="", help="added to the claim's notes")
    p = cl.add_parser("walk", parents=[common], help="plan and queue the claim's path as a requisition")
    p.add_argument("id")
    p.add_argument("--run", action="store_true", help="then run that requisition")


COMMANDS = ("claim",)


def run(args, definitions) -> int:
    registry = load_registry()
    conn = open_library(args.db)
    try:
        return _COMMANDS[args.claim_command](args, conn, definitions, registry)
    finally:
        conn.close()


def _line(claim: claims.Claim, turn: str) -> str:
    meta = claim.meta
    parts = [claim.id, claim.milestone, turn, meta.get("thing_name"), f"as {meta['as']}" if meta.get("as") else None,
             f"-> {meta.get('place_name')}", f"closed {meta['closed']}" if claim.closed else None]
    return "  ".join(str(p) for p in parts if p)


def _add(args, conn, definitions, registry) -> int:
    claim = claims.new(conn, _uid(conn, args.uid), args.env, role=args.role, folder=args.folder, note=args.note)
    _emit(args, claims.describe(conn, definitions, registry, claim),
          f"Claimed {claim.meta['thing_name']} for {claim.meta['place_name']}: {claim.id} ({claim.milestone})"
          f"\nFile: {claim.path}")
    return 0


def _list(args, conn, definitions, registry) -> int:
    found, problems = claims.read_all(conn)
    tools = tool_paths()
    described = [(c, claims.describe(conn, definitions, registry, c, tools)) for c in found if args.all or not c.closed]
    shown = [(c, d) for c, d in described if not args.turn or d["turn"] == args.turn]
    lines = [_line(c, d["turn"]) for c, d in shown] + [f"problem: {p}" for p in problems]
    _emit(args, {"claims": [d for _, d in shown], "problems": problems}, "\n".join(lines) or "No claims.")
    return 0


def _show(args, conn, definitions, registry) -> int:
    claim = claims.read_one(conn, args.id)
    data = claims.describe(conn, definitions, registry, claim)
    lines = [f"File: {claim.path}"] + [f"{key}: {value}" for key, value in data.items() if key != "notes"]
    for uid, row in claims.resolve_requisitions(conn, claim.meta):
        lines.append(f"{uid}  removed" if row is None else
                     "  ".join(str(p) for p in (uid, row["id"], row["state"], row["message"]) if p))
    _emit(args, data, "\n".join(lines) + ("\n\n" + claim.notes.rstrip("\n") if claim.notes.strip() else ""))
    return 0


def _close(args, conn, definitions, registry) -> int:
    claim = claims.close(conn, args.id, args.reason)
    _emit(args, claims.describe(conn, definitions, registry, claim), f"Closed {claim.id} ({claim.milestone})")
    return 0


def _walk(args, conn, definitions, registry) -> int:
    claim, requisition_id = claims.walk(conn, definitions, registry, args.id)
    if args.run:
        from exchange.requisitions.runner import run_queue

        progress = None
        if not args.json:
            def progress(event: dict) -> None:
                print(f"  {event['requisition']} · {event['item']} · [{event['step']}] {event['message']}",
                      file=sys.stderr, flush=True)
        conn.close()  # the runner opens its own connection
        run_queue(args.db, definitions, registry, only=[requisition_id], progress=progress)
        conn = open_library(args.db)
        claim = claims.read_one(conn, claim.id)
    try:
        row = conn.execute("SELECT id, uid, state, message FROM requisition WHERE id = ?", (requisition_id,)).fetchone()
        data = claims.describe(conn, definitions, registry, claim)
    finally:
        if args.run:
            conn.close()
    text = f"Queued requisition {row['id']} for {claim.id}"
    if args.run:
        text = f"Ran requisition {row['id']} for {claim.id}: {row['state']}" + (f" ({row['message']})" if row["message"] else "")
        text += f"\n{claim.milestone}; turn: {data['turn']}" + (f"  {data['turn_line']}" if data["turn_line"] else "")
    else:
        text += f"; run it with: exchange requisition run {row['id']}"
    _emit(args, {**data, "requisition": {key: row[key] for key in ("id", "uid", "state", "message")}}, text)
    return 0


_COMMANDS = {"add": _add, "list": _list, "show": _show, "close": _close, "walk": _walk}
