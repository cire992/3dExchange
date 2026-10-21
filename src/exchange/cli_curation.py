"""Command line for curation: classify, lexicon, suggest, curate, collection, history, undo."""

from __future__ import annotations

import argparse
import dataclasses
import json
import sqlite3
from pathlib import Path

from exchange.curation import EDITABLE_FIELDS, CurationError, Curator, history
from exchange.db import open_library
from exchange.db import repository as repo
from exchange.paths import fold


def add_parsers(commands, common: argparse.ArgumentParser) -> None:
    classify = commands.add_parser("classify", parents=[common],
                                   help="re-run classification and suggestions (after editing lexicons)")
    classify.add_argument("--env", type=int, action="append", metavar="ID", help="only this environment")

    lexicon = commands.add_parser("lexicon", help="show and edit lexicons")
    lex = lexicon.add_subparsers(dest="lexicon_command", required=True)
    lex.add_parser("list", parents=[common], help="list lexicons")
    show = lex.add_parser("show", parents=[common], help="show one lexicon")
    show.add_argument("id")
    for name, text in (("add", "add a word"), ("remove", "remove a word")):
        p = lex.add_parser(name, parents=[common], help=f"{text} (saved in your definitions folder)")
        p.add_argument("id", help="lexicon id, e.g. category")
        p.add_argument("value", help="what the word means, e.g. Food")
        p.add_argument("word")

    suggest = commands.add_parser("suggest", help="list, accept or reject suggestions")
    sug = suggest.add_subparsers(dest="suggest_command", required=True)
    lst = sug.add_parser("list", parents=[common], help="list suggestions")
    lst.add_argument("--kind", choices=("texture_link", "variant_group", "lexicon_word"))
    lst.add_argument("--state", default="pending", choices=("pending", "accepted", "rejected", "stale"))
    for name in ("accept", "reject"):
        p = sug.add_parser(name, parents=[common], help=f"{name} suggestions")
        p.add_argument("ids", type=int, nargs="+")

    curate = commands.add_parser("curate", help="edit dossiers (every change can be undone)")
    cur = curate.add_subparsers(dest="curate_command", required=True)
    p = cur.add_parser("set", parents=[common], help="set a field (bulk: several uids)")
    p.add_argument("field", choices=EDITABLE_FIELDS)
    p.add_argument("value")
    p.add_argument("uids", nargs="+")
    p = cur.add_parser("revert", parents=[common], help="revert a field to the scanned value")
    p.add_argument("field", choices=EDITABLE_FIELDS)
    p.add_argument("uids", nargs="+")
    p = cur.add_parser("tag", parents=[common], help="add or remove tags")
    p.add_argument("uids", nargs="+")
    p.add_argument("--add", action="append", default=[], metavar="TAG")
    p.add_argument("--remove", action="append", default=[], metavar="TAG")
    p = cur.add_parser("parent", parents=[common], help="put dossiers into a product")
    p.add_argument("uids", nargs="+")
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--to", metavar="PRODUCT_UID")
    group.add_argument("--none", action="store_true", help="take them out of any product")
    p = cur.add_parser("link", parents=[common], help="link files onto a dossier")
    p.add_argument("uid")
    p.add_argument("files", type=Path, nargs="+")
    p.add_argument("--role", default="linked")
    p = cur.add_parser("unlink", parents=[common], help="unlink files")
    p.add_argument("files", type=Path, nargs="+")
    p = cur.add_parser("merge", parents=[common], help="the same asset twice: merge FROM into INTO")
    p.add_argument("source", metavar="FROM")
    p.add_argument("target", metavar="INTO")
    p = cur.add_parser("fold", parents=[common], help="FROM is a variant of INTO")
    p.add_argument("source", metavar="FROM")
    p.add_argument("target", metavar="INTO")
    p.add_argument("--variant", required=True, help="FROM's variant name, e.g. Blue")
    p.add_argument("--as", dest="target_variant", help="INTO's own variant name, e.g. Pink")
    p = cur.add_parser("split", parents=[common], help="entries wrongly grouped become their own dossier")
    p.add_argument("uid")
    p.add_argument("entries", type=int, nargs="+")
    p.add_argument("--name")
    p = cur.add_parser("promote", parents=[common], help="a variant becomes its own dossier")
    p.add_argument("uid")
    p.add_argument("variant")
    p = cur.add_parser("product", parents=[common], help="make a product holding some dossiers")
    p.add_argument("name")
    p.add_argument("uids", nargs="+")

    coll = commands.add_parser("collection", help="manual and smart collections")
    col = coll.add_subparsers(dest="collection_command", required=True)
    col.add_parser("list", parents=[common], help="list collections")
    p = col.add_parser("create", parents=[common], help="create a collection")
    p.add_argument("name")
    p.add_argument("--query", help="make it a smart collection: a saved search")
    for name in ("add", "remove"):
        p = col.add_parser(name, parents=[common], help=f"{name} dossiers")
        p.add_argument("name")
        p.add_argument("uids", nargs="+")
    p = col.add_parser("delete", parents=[common], help="delete a collection (not its dossiers)")
    p.add_argument("name")

    hist = commands.add_parser("history", parents=[common], help="recent curation actions")
    hist.add_argument("--limit", type=int, default=20)
    undo = commands.add_parser("undo", parents=[common], help="undo a curation action (see history)")
    undo.add_argument("id", type=int)


def _uid(conn: sqlite3.Connection, prefix: str) -> str:
    rows = conn.execute("SELECT uid FROM dossier WHERE uid LIKE ?", (prefix + "%",)).fetchall()
    if len(rows) != 1:
        raise CurationError(f"{len(rows)} dossiers match {prefix!r}; give more of the uid")
    return rows[0][0]


def _file(conn: sqlite3.Connection, path: Path) -> tuple[int, str]:
    path = path.resolve()
    for root in repo.list_roots(conn):
        try:
            rel = path.relative_to(Path(root["path"]))
        except ValueError:
            continue
        return root["id"], fold(rel.as_posix())
    raise CurationError(f"{path} is not inside any environment in the library")


def _emit(args, data, text: str) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False, default=str) if args.json else text)


def run(args, definitions) -> int:
    conn = open_library(args.db)
    try:
        return _COMMANDS[args.command](args, definitions, conn, Curator(conn, definitions))
    finally:
        conn.close()


def _classify(args, definitions, conn, curator) -> int:
    from exchange.scanner.classify import classify
    from exchange.suggestions import generate

    ids = args.env or [e["id"] for e in repo.list_environments(conn)]
    with repo.transaction(conn):
        stats = classify(conn, definitions, environment_ids=ids)
        new = generate(conn, definitions, environment_ids=ids)
    data = {"classification": dataclasses.asdict(stats), "suggestions": new}
    _emit(args, data, f"{stats.dossiers} dossiers classified · {stats.tagged} tagged · "
                      f"{stats.structural} structural · {stats.changed_confidence} confidences changed\n"
                      f"new suggestions: {new['texture_link']} texture links, {new['variant_group']} variant "
                      f"groups ({new['stale']} no longer apply)")
    return 0


def _lexicon(args, definitions, conn, curator) -> int:
    lexicons = definitions.lexicons
    if args.lexicon_command == "list":
        rows = [{"id": l.id, "name": l.name, "kind": l.kind, "terms": len(l.terms), "source": l.source}
                for l in lexicons.values()]
        _emit(args, rows, "\n".join(f"  {r['id']:<16} {r['kind']:<16} {r['terms']:>3} terms  {r['name']}" for r in rows))
        return 0
    lexicon = lexicons.get(args.id)
    if lexicon is None:
        raise CurationError(f"no lexicon {args.id!r} (have: {', '.join(lexicons)})")
    if args.lexicon_command == "show":
        data = {"id": lexicon.id, "kind": lexicon.kind, "source": lexicon.source,
                "terms": [{"value": t.value, "words": list(t.words), "patterns": list(t.patterns)} for t in lexicon.terms]}
        _emit(args, data, "\n".join([f"{lexicon.name} [{lexicon.kind}] from {lexicon.source}"] +
                                    [f"  {t.value or '-'}: {', '.join(t.words + t.patterns)}" for t in lexicon.terms]))
        return 0
    log_id = curator.set_lexicon_word(args.id, args.value, args.word, present=args.lexicon_command == "add")
    verb = "Added" if args.lexicon_command == "add" else "Removed"
    _emit(args, {"log_id": log_id}, f"{verb} {args.word!r} ({args.value}) · undo with: exchange undo {log_id}\n"
                                    f"Apply it to the library with: exchange classify")
    return 0


def _suggest(args, definitions, conn, curator) -> int:
    from exchange.suggestions import list_suggestions

    if args.suggest_command == "list":
        rows = list_suggestions(conn, state=args.state, kind=args.kind)
        lines = []
        for s in rows:
            p = s["payload"]
            if s["kind"] == "texture_link":
                what = f"{s['subject_name']}: " + ", ".join(f"{f['channel']} {f['rel'].rsplit('/', 1)[-1]}" for f in p["files"])
            elif s["kind"] == "variant_group":
                what = f"{p['base']}: " + ", ".join(p["variants"].values())
            else:
                what = f"add {p['word']!r} to {p['value']}"
            lines.append(f"  {s['id']:>5}  {s['kind']:<14} {what}")
        _emit(args, rows, "\n".join(lines) or f"No {args.state} suggestions.")
        return 0
    if args.suggest_command == "accept":
        logs = [curator.accept(i) for i in args.ids]
        _emit(args, {"log_ids": logs}, f"Accepted {len(logs)} · undo with: exchange undo <id> ({', '.join(map(str, logs))})")
    else:
        log_id = curator.reject(args.ids)
        _emit(args, {"log_id": log_id}, f"Rejected {len(args.ids)} · undo with: exchange undo {log_id}")
    return 0


def _curate(args, definitions, conn, curator) -> int:
    c = args.curate_command
    uid = lambda p: _uid(conn, p)  # noqa: E731
    new_uid = None
    if c == "set":
        log_id = curator.set_field([uid(u) for u in args.uids], args.field, args.value)
    elif c == "revert":
        log_id = curator.revert_field([uid(u) for u in args.uids], args.field)
    elif c == "tag":
        log_id = curator.tag([uid(u) for u in args.uids], add=args.add, remove=args.remove)
    elif c == "parent":
        log_id = curator.set_parent([uid(u) for u in args.uids], None if args.none else uid(args.to))
    elif c == "link":
        log_id = curator.link_files(uid(args.uid), [_file(conn, f) for f in args.files], role=args.role)
    elif c == "unlink":
        log_id = curator.unlink_files([_file(conn, f) for f in args.files])
    elif c == "merge":
        log_id = curator.merge(uid(args.source), uid(args.target))
    elif c == "fold":
        log_id = curator.fold_variant(uid(args.source), uid(args.target), args.variant, args.target_variant)
    elif c == "split":
        log_id, new_uid = curator.split(uid(args.uid), args.entries, name=args.name)
    elif c == "promote":
        log_id, new_uid = curator.promote_variant(uid(args.uid), args.variant)
    else:
        log_id, new_uid = curator.create_product(args.name, [uid(u) for u in args.uids])
    text = f"Done · undo with: exchange undo {log_id}" + (f"\nNew dossier {new_uid}" if new_uid else "")
    _emit(args, {"log_id": log_id, "new_uid": new_uid}, text)
    return 0


def _collection(args, definitions, conn, curator) -> int:
    from exchange.library.query import list_collections

    c = args.collection_command
    if c == "list":
        rows = list_collections(conn, definitions)
        _emit(args, rows, "\n".join(f"  {r['name']}  ({r['count']}){'  smart: ' + r['query'] if r['smart'] else ''}"
                                    for r in rows) or "No collections yet.")
        return 0
    if c == "create":
        log_id, cid = curator.create_collection(args.name, args.query)
    elif c == "add":
        log_id = curator.add_to_collection(args.name, [_uid(conn, u) for u in args.uids])
    elif c == "remove":
        log_id = curator.remove_from_collection(args.name, [_uid(conn, u) for u in args.uids])
    else:
        log_id = curator.delete_collection(args.name)
    _emit(args, {"log_id": log_id}, f"Done · undo with: exchange undo {log_id}")
    return 0


def _history(args, definitions, conn, curator) -> int:
    rows = history(conn, args.limit)
    _emit(args, rows, "\n".join(f"  {r['id']:>5}  {r['at'][:16].replace('T', ' ')}  {r['action']}"
                                + ("" if r["undoable"] else "  (cannot be undone)") for r in rows) or "No history yet.")
    return 0


def _undo(args, definitions, conn, curator) -> int:
    log_id = curator.undo(args.id)
    _emit(args, {"log_id": log_id}, f"Undone · redo with: exchange undo {log_id}")
    return 0


_COMMANDS = {"classify": _classify, "lexicon": _lexicon, "suggest": _suggest, "curate": _curate,
             "collection": _collection, "history": _history, "undo": _undo}
COMMANDS = tuple(_COMMANDS)
