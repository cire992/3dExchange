"""Command line for claims: add, list, show, close (R3a)."""

from __future__ import annotations

import argparse

from exchange import claims
from exchange.cli_curation import _emit, _uid
from exchange.db import open_library


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
    p = cl.add_parser("show", parents=[common], help="one claim: its keys, milestone and notes")
    p.add_argument("id")
    p = cl.add_parser("close", parents=[common], help="close a claim (it keeps its milestone)")
    p.add_argument("id")
    p.add_argument("--reason", default="", help="added to the claim's notes")


COMMANDS = ("claim",)


def run(args, definitions) -> int:
    conn = open_library(args.db)
    try:
        return _COMMANDS[args.claim_command](args, conn)
    finally:
        conn.close()


def _line(claim: claims.Claim) -> str:
    meta = claim.meta
    parts = [claim.id, claim.milestone, meta.get("thing_name"), f"as {meta['as']}" if meta.get("as") else None,
             f"-> {meta.get('place_name')}", f"closed {meta['closed']}" if claim.closed else None]
    return "  ".join(str(p) for p in parts if p)


def _add(args, conn) -> int:
    claim = claims.new(conn, _uid(conn, args.uid), args.env, role=args.role, folder=args.folder, note=args.note)
    _emit(args, claim.to_json(), f"Claimed {claim.meta['thing_name']} for {claim.meta['place_name']}: "
                                 f"{claim.id} ({claim.milestone})\nFile: {claim.path}")
    return 0


def _list(args, conn) -> int:
    found, problems = claims.read_all(conn)
    shown = [c for c in found if args.all or not c.closed]
    lines = [_line(c) for c in shown] + [f"problem: {p}" for p in problems]
    _emit(args, {"claims": [c.to_json() for c in shown], "problems": problems},
          "\n".join(lines) or "No claims.")
    return 0


def _show(args, conn) -> int:
    claim = claims.read_one(conn, args.id)
    lines = [f"File: {claim.path}"] + [f"{key}: {value}" for key, value in claim.to_json().items() if key != "notes"]
    _emit(args, claim.to_json(), "\n".join(lines) + ("\n\n" + claim.notes.rstrip("\n") if claim.notes.strip() else ""))
    return 0


def _close(args, conn) -> int:
    claim = claims.close(conn, args.id, args.reason)
    _emit(args, claim.to_json(), f"Closed {claim.id} ({claim.milestone})")
    return 0


_COMMANDS = {"add": _add, "list": _list, "show": _show, "close": _close}
