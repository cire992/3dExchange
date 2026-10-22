"""Curation: the user's changes to the library. Every action can be undone.

An action is a list of state changes, e.g. "the override of field `name` on dossier X becomes
'Cowboy Boots'" or "entry 12 belongs to dossier Y". Before writing, the engine reads each state's
current value, so the action's inverse is known exactly. Both are stored in ``curation_log``
(permanent history); ``undo(log_id)`` applies the inverse as a new logged action, so redo is the
undo of an undo.

User edits live in the override layer (keyed by dossier uid, untouched by scans). Merges, splits and
variant folds also move entries between dossiers; ``entry.moved_from`` tells the next rescan to
leave the receiving dossier's scanned values alone.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from exchange.db import repository as repo
from exchange.definitions.schema import GENERATED_LEXICON_KINDS, DefinitionSet
from exchange.errors import ExchangeError
from exchange.lexicons import LexiconIndex, has_word, set_word, word_state
from exchange.links import apply_file_links
from exchange.scanner.tokenize import tokenize

EDITABLE_FIELDS = ("name", "type_id", "author", "authors", "license", "redistribution", "source", "url",
                   "notes", "version", "description")


class CurationError(ExchangeError):
    pass


Change = tuple[str, tuple, Any]  # (kind, key, new value; None means "absent")


class Curator:
    def __init__(self, conn: sqlite3.Connection, definitions: DefinitionSet | None = None,
                 user_dir: Path | None = None) -> None:
        self.conn = conn
        self.definitions = definitions
        self.user_dir = user_dir

    # Lookups ---------------------------------------------------------------------------------------

    def dossier(self, uid: str) -> sqlite3.Row:
        row = self.conn.execute("SELECT * FROM dossier_effective WHERE uid = ?", (uid,)).fetchone()
        if row is None:
            raise CurationError(f"no dossier {uid}")
        return row

    def _entries(self, uid: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT e.*, l.environment_id FROM entry e JOIN ledger l ON l.id = e.ledger_id"
            " JOIN dossier d ON d.id = l.dossier_id WHERE d.uid = ? ORDER BY e.id", (uid,)).fetchall()

    # Field edits -----------------------------------------------------------------------------------

    def set_field(self, uids: str | Iterable[str], field: str, value: Any) -> int:
        """Set a field on one dossier or (bulk edit) many. ``value=None`` reverts to scanned."""
        uids = [uids] if isinstance(uids, str) else list(uids)
        if field not in EDITABLE_FIELDS:
            raise CurationError(f"{field!r} is not editable (editable: {', '.join(EDITABLE_FIELDS)})")
        if field == "type_id" and value is not None and self.definitions is not None \
                and value not in self.definitions.dossier_types:
            raise CurationError(f"unknown dossier type {value!r}")
        if field == "name" and value is not None and not str(value).strip():
            raise CurationError("a name cannot be empty")
        for uid in uids:
            self.dossier(uid)
        verb = "revert" if value is None else "set"
        return self._run(f"{verb}_field", [("field", (uid, field), value) for uid in uids], uids,
                         {"field": field, "value": value})

    def revert_field(self, uids: str | Iterable[str], field: str) -> int:
        return self.set_field(uids, field, None)

    def tag(self, uids: str | Iterable[str], add: Iterable[str] = (), remove: Iterable[str] = ()) -> int:
        """Add or remove tags on one dossier or many. Removing a scanned tag hides it."""
        uids = [uids] if isinstance(uids, str) else list(uids)
        add = [t.strip() for t in add if t.strip()]
        remove = [t.strip() for t in remove if t.strip()]
        if not add and not remove:
            raise CurationError("nothing to tag")
        changes: list[Change] = []
        for uid in uids:
            self.dossier(uid)
            changes += [("tag", (uid, t), "add") for t in add]
            changes += [("tag", (uid, t), "remove") for t in remove]
        log_id = self._run("tag", changes, uids, {"add": add, "remove": remove})
        if add:
            self._suggest_lexicon_words(uids, add)
        return log_id

    def revert_tag(self, uid: str, tag: str) -> int:
        self.dossier(uid)
        return self._run("revert_tag", [("tag", (uid, tag), None)], [uid], {"tag": tag})

    def set_parent(self, uids: str | Iterable[str], parent_uid: str | None) -> int:
        """Put dossiers into a product (``None`` takes them out of any product)."""
        uids = [uids] if isinstance(uids, str) else list(uids)
        if parent_uid is not None:
            self.dossier(parent_uid)
            if parent_uid in uids:
                raise CurationError("a dossier cannot contain itself")
        for uid in uids:
            self.dossier(uid)
        return self._run("set_parent", [("parent", (uid,), {"target": parent_uid}) for uid in uids],
                         uids, {"parent": parent_uid})

    def revert_parent(self, uid: str) -> int:
        self.dossier(uid)
        return self._run("revert_parent", [("parent", (uid,), None)], [uid], {})

    # Linking files -------------------------------------------------------------------------------

    def link_files(self, uid: str, files: Iterable[tuple[int, str]], role: str = "linked") -> int:
        """Link files, given as (root id, rel_key), onto a dossier."""
        self.dossier(uid)
        files = list(files)
        if not files:
            raise CurationError("no files to link")
        for root_id, rel_key in files:
            if self.conn.execute("SELECT 1 FROM file WHERE root_id = ? AND rel_key = ?",
                                 (root_id, rel_key)).fetchone() is None:
                raise CurationError(f"no file {rel_key} in root {root_id}")
        changes = [("link", (f"root:{r}:{k}",), {"target": uid, "role": role}) for r, k in files]
        return self._run("link_files", changes, [uid], {"files": [k for _, k in files], "role": role})

    def unlink_files(self, files: Iterable[tuple[int, str]]) -> int:
        changes = [("link", (f"root:{r}:{k}",), None) for r, k in files]
        uids = [v["target"] for _, key, _ in changes if (v := self._read("link", key))]
        return self._run("unlink_files", changes, uids, {"files": [k for _, k in files]})

    # Merge, split, variants ------------------------------------------------------------------------

    def merge(self, alias_uid: str, target_uid: str) -> int:
        """The same asset found twice: ``alias_uid``'s entries (and children) join ``target_uid``."""
        return self._merge("merge", alias_uid, target_uid, variant=None, target_variant=None)

    def fold_variant(self, uid: str, into_uid: str, variant: str, target_variant: str | None = None) -> int:
        """``uid`` is a variant of ``into_uid`` (Donut01_Blue of Donut01_Pink): one dossier, two variants."""
        if not variant.strip():
            raise CurationError("a variant needs a name")
        return self._merge("fold_variant", uid, into_uid, variant=variant.strip(), target_variant=target_variant)

    def _merge(self, action: str, alias_uid: str, target_uid: str, *, variant: str | None,
               target_variant: str | None) -> int:
        if alias_uid == target_uid:
            raise CurationError("a dossier cannot be merged into itself")
        self.dossier(alias_uid)
        self.dossier(target_uid)
        changes: list[Change] = []
        for e in self._entries(alias_uid):
            changes.append(("entry", (e["id"],), {"dossier": target_uid, "moved_from": alias_uid,
                                                   "variant": variant if variant is not None else e["variant"]}))
        if target_variant:
            for e in self._entries(target_uid):
                if not e["variant"]:
                    changes.append(("entry", (e["id"],), {"dossier": target_uid, "moved_from": e["moved_from"],
                                                           "variant": target_variant}))
        for child in self.conn.execute("SELECT uid FROM dossier_effective WHERE parent_id ="
                                       " (SELECT id FROM dossier WHERE uid = ?)", (alias_uid,)):
            changes.append(("parent", (child["uid"],), {"target": target_uid}))
        changes.append(("alias", (alias_uid,), target_uid))
        return self._run(action, changes, [target_uid, alias_uid],
                         {"into": target_uid, "from": alias_uid, "variant": variant})

    def split(self, uid: str, entry_ids: Iterable[int], name: str | None = None) -> tuple[int, str]:
        """Entries wrongly grouped into ``uid`` become a dossier of their own. Returns (log id, new uid)."""
        source = self.dossier(uid)
        own = {e["id"]: e for e in self._entries(uid)}
        entry_ids = list(entry_ids)
        if not entry_ids or any(i not in own for i in entry_ids):
            raise CurationError(f"entries {entry_ids} are not all entries of {uid}")
        new_uid = repo.new_uid()
        changes: list[Change] = [("dossier", (new_uid,), {"type_id": source["type_id"],
                                                         "name": name or f"{source['name']} (split)"})]
        changes += [("entry", (i,), {"dossier": new_uid, "moved_from": uid, "variant": own[i]["variant"]})
                    for i in entry_ids]
        return self._run("split", changes, [uid, new_uid], {"new": new_uid, "entries": entry_ids}), new_uid

    def promote_variant(self, uid: str, variant: str) -> tuple[int, str]:
        """A variant becomes its own dossier again."""
        entries = [e["id"] for e in self._entries(uid) if (e["variant"] or "").casefold() == variant.casefold()]
        if not entries:
            raise CurationError(f"{uid} has no variant {variant!r}")
        source = self.dossier(uid)
        return self.split(uid, entries, name=f"{source['name']} {variant}")

    def create_product(self, name: str, child_uids: Iterable[str]) -> tuple[int, str]:
        """A new product (e.g. for loose files that belong together) holding some dossiers."""
        if not name.strip():
            raise CurationError("a product needs a name")
        children = list(child_uids)
        for uid in children:
            self.dossier(uid)
        new_uid = repo.new_uid()
        changes: list[Change] = [("dossier", (new_uid,), {"type_id": "product", "name": name.strip()}),
                                 ("field", (new_uid, "user_created"), True)]
        changes += [("parent", (uid,), {"target": new_uid}) for uid in children]
        return self._run("create_product", changes, [new_uid, *children], {"name": name}), new_uid

    # Collections -----------------------------------------------------------------------------------

    def create_collection(self, name: str, query: str | None = None) -> tuple[int, str]:
        if not name.strip():
            raise CurationError("a collection needs a name")
        if self.conn.execute("SELECT 1 FROM collection WHERE name = ?", (name.strip(),)).fetchone():
            raise CurationError(f"there is already a collection named {name!r}")
        if query is not None and self.definitions is not None:
            from exchange.library.search import compile_query

            compile_query(query, self.definitions, conn=self.conn)  # reject a broken saved search now
        uid = repo.new_uid()
        return self._run("create_collection", [("collection", (uid,), {"name": name.strip(), "query": query})],
                         [], {"collection": uid, "name": name}), uid

    def collection_uid(self, name_or_uid: str) -> str:
        row = self.conn.execute("SELECT uid FROM collection WHERE uid = ? OR name = ?",
                                (name_or_uid, name_or_uid)).fetchone()
        if row is None:
            raise CurationError(f"no collection {name_or_uid!r}")
        return row[0]

    def delete_collection(self, name_or_uid: str) -> int:
        uid = self.collection_uid(name_or_uid)
        members = [r[0] for r in self.conn.execute(
            "SELECT dossier_uid FROM collection_member WHERE collection_uid = ?", (uid,))]
        changes: list[Change] = [("member", (uid, m), None) for m in members]
        changes.append(("collection", (uid,), None))
        return self._run("delete_collection", changes, [], {"collection": uid})

    def add_to_collection(self, name_or_uid: str, uids: Iterable[str], present: bool = True) -> int:
        cid = self.collection_uid(name_or_uid)
        row = self.conn.execute("SELECT query FROM collection WHERE uid = ?", (cid,)).fetchone()
        if row[0] is not None:
            raise CurationError("a smart collection is a saved search; its members follow the search")
        uids = list(uids)
        for uid in uids:
            self.dossier(uid)
        changes = [("member", (cid, uid), True if present else None) for uid in uids]
        return self._run("add_to_collection" if present else "remove_from_collection", changes, uids,
                         {"collection": cid})

    def remove_from_collection(self, name_or_uid: str, uids: Iterable[str]) -> int:
        return self.add_to_collection(name_or_uid, uids, present=False)

    # Lexicons --------------------------------------------------------------------------------------

    def set_lexicon_word(self, lexicon_id: str, value: str, word: str, present: bool = True) -> int:
        """Add (or remove) a lexicon word; written to the user's lexicon file, and undoable."""
        if self.definitions is None or lexicon_id not in self.definitions.lexicons:
            raise CurationError(f"no lexicon {lexicon_id!r}")
        generated = self.definitions.lexicons[lexicon_id].kind in GENERATED_LEXICON_KINDS
        target = True if present else "excluded" if generated else None
        return self._run("lexicon_word", [("lexicon", (lexicon_id, value, word), target)], [],
                         {"lexicon": lexicon_id, "value": value, "word": word, "present": present})

    # Suggestions -----------------------------------------------------------------------------------

    def accept(self, suggestion_id: int) -> int:
        s = self.conn.execute("SELECT * FROM suggestion WHERE id = ?", (suggestion_id,)).fetchone()
        if s is None:
            raise CurationError(f"no suggestion {suggestion_id}")
        if s["state"] != "pending":
            raise CurationError(f"suggestion {suggestion_id} is {s['state']}")
        payload = json.loads(s["payload"])
        changes: list[Change] = []
        dossiers = [s["subject_uid"]] if s["subject_uid"] else []
        if s["kind"] == "texture_link":
            self.dossier(s["subject_uid"])
            changes += [("link", (f"root:{f['root_id']}:{f['rel_key']}",), {"target": s["subject_uid"], "role": "texture"})
                        for f in payload["files"]]
        elif s["kind"] == "variant_group":
            target = s["subject_uid"]
            self.dossier(target)
            for member in payload["members"]:
                if member == target or self.conn.execute("SELECT 1 FROM dossier WHERE uid = ?", (member,)).fetchone() is None:
                    continue
                for e in self._entries(member):
                    changes.append(("entry", (e["id"],), {"dossier": target, "moved_from": member,
                                                           "variant": payload["variants"].get(member)}))
                changes.append(("alias", (member,), target))
                dossiers.append(member)
            for e in self._entries(target):
                if not e["variant"]:
                    changes.append(("entry", (e["id"],), {"dossier": target, "moved_from": e["moved_from"],
                                                           "variant": payload["variants"].get(target)}))
        elif s["kind"] == "lexicon_word":
            if self.definitions is None:
                raise CurationError("accepting a lexicon word needs the definitions")
            changes.append(("lexicon", (payload["lexicon"], payload["value"], payload["word"]), True))
        changes.append(("suggestion", (suggestion_id,), {"state": "accepted", "decided_at": repo.now()}))
        log_id = self._run(f"accept_{s['kind']}", changes, dossiers, {"suggestion": suggestion_id})
        self.conn.execute("UPDATE suggestion SET log_id = ? WHERE id = ?", (log_id, suggestion_id))
        return log_id

    def reject(self, suggestion_ids: int | Iterable[int]) -> int:
        ids = [suggestion_ids] if isinstance(suggestion_ids, int) else list(suggestion_ids)
        for i in ids:
            row = self.conn.execute("SELECT state FROM suggestion WHERE id = ?", (i,)).fetchone()
            if row is None or row[0] != "pending":
                raise CurationError(f"suggestion {i} is not pending")
        return self._run("reject_suggestions", [("suggestion", (i,), {"state": "rejected", "decided_at": repo.now()})
                                                for i in ids], [], {"suggestions": ids})

    def _suggest_lexicon_words(self, uids: list[str], tags: list[str]) -> None:
        """You tagged something by hand: offer its unknown name words for that tag.

        Tagging many at once offers only the words at least two of their names share.
        """
        if self.definitions is None or "category" not in self.definitions.lexicons:
            return
        index = LexiconIndex(self.definitions)
        words: dict[str, list[str]] = {}  # word -> uids whose name has it
        for uid in uids:
            for word in dict.fromkeys(index.clean(tokenize(self.dossier(uid)["name"]))):
                if len(word) >= 3 and not (index.is_index(word) or index.known(word) or word.isdigit()):
                    words.setdefault(word, []).append(uid)
        wanted = 1 if len(uids) == 1 else 2
        with self._transaction():
            for word, found_in in words.items():
                if len(found_in) < wanted:
                    continue
                for tag in tags:
                    if has_word(self.definitions, "category", tag, word):
                        continue
                    payload = {"lexicon": "category", "value": tag, "word": word, "from": found_in[0]}
                    self.conn.execute(
                        "INSERT OR IGNORE INTO suggestion (kind, key, subject_uid, payload, confidence, created_at)"
                        " VALUES ('lexicon_word', ?, ?, ?, 0.5, ?)",
                        (f"lexicon_word:category:{tag.casefold()}:{word}", found_in[0], repo.to_json(payload),
                         repo.now()))

    # Undo ------------------------------------------------------------------------------------------

    def undo(self, log_id: int) -> int:
        row = self.conn.execute("SELECT * FROM curation_log WHERE id = ?", (log_id,)).fetchone()
        if row is None:
            raise CurationError(f"no history entry {log_id}")
        payload = json.loads(row["payload"])
        if "inverse" not in payload:
            raise CurationError(f"history entry {log_id} ({row['action']}) cannot be undone")
        changes = [(kind, tuple(key), value) for kind, key, value in payload["inverse"]]
        return self._run("undo", changes, payload.get("dossiers", []),
                         {"undoes": log_id, "undone_action": row["action"]})

    # Engine ----------------------------------------------------------------------------------------

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        if self.conn.in_transaction:
            yield
        else:
            with repo.transaction(self.conn):
                yield

    def _run(self, action: str, changes: list[Change], dossiers: list[str], details: dict) -> int:
        with self._transaction():
            inverse = []
            roots: set[int] = set()
            touched: set[str] = set(dossiers)
            for kind, key, value in changes:
                inverse.append([kind, list(key), self._read(kind, key)])
                touched |= self._write(kind, key, value, roots)
            for root_id in roots:
                apply_file_links(self.conn, root_id)
            inverse.reverse()
            payload = {"action": action, "dossier": dossiers[0] if dossiers else None,
                       "dossiers": list(dict.fromkeys(dossiers)), **details,
                       "changes": [[k, list(key), v] for k, key, v in changes], "inverse": inverse}
            cur = self.conn.execute("INSERT INTO curation_log (at, action, payload) VALUES (?, ?, ?)",
                                    (repo.now(), action, repo.to_json(payload)))
            ids = [r[0] for uid in touched if uid
                   for r in self.conn.execute("SELECT id FROM dossier WHERE uid = ?", (uid,))]
            repo.index_dossiers(self.conn, ids)
            return cur.lastrowid

    def _read(self, kind: str, key: tuple) -> Any:
        c = self.conn
        if kind == "field":
            row = c.execute("SELECT value FROM override_field WHERE dossier_uid = ? AND field = ?", key).fetchone()
            return json.loads(row[0]) if row else None
        if kind == "tag":
            row = c.execute("SELECT action FROM override_tag WHERE dossier_uid = ? AND tag = ?", key).fetchone()
            return row[0] if row else None
        if kind == "parent":
            row = c.execute("SELECT target_uid FROM override_link WHERE kind = 'dossier_to_parent' AND subject = ?",
                            key).fetchone()
            return {"target": row[0]} if row else None
        if kind == "link":
            row = c.execute("SELECT target_uid, role FROM override_link WHERE kind = 'file_to_dossier'"
                            " AND subject = ?", key).fetchone()
            return {"target": row[0], "role": row[1]} if row and row[0] else None
        if kind == "alias":
            row = c.execute("SELECT target_uid FROM dossier_alias WHERE alias_uid = ?", key).fetchone()
            return row[0] if row else None
        if kind == "entry":
            row = c.execute("SELECT d.uid, e.moved_from, e.variant FROM entry e JOIN ledger l ON l.id = e.ledger_id"
                            " JOIN dossier d ON d.id = l.dossier_id WHERE e.id = ?", key).fetchone()
            if row is None:
                raise CurationError(f"no entry {key[0]}")
            return {"dossier": row[0], "moved_from": row[1], "variant": row[2]}
        if kind == "dossier":
            row = c.execute("SELECT type_id, name FROM dossier WHERE uid = ?", key).fetchone()
            return {"type_id": row[0], "name": row[1]} if row else None
        if kind == "collection":
            row = c.execute("SELECT name, query FROM collection WHERE uid = ?", key).fetchone()
            return {"name": row[0], "query": row[1]} if row else None
        if kind == "member":
            row = c.execute("SELECT 1 FROM collection_member WHERE collection_uid = ? AND dossier_uid = ?", key).fetchone()
            return True if row else None
        if kind == "suggestion":
            row = c.execute("SELECT state, decided_at FROM suggestion WHERE id = ?", key).fetchone()
            return {"state": row[0], "decided_at": row[1]} if row else None
        if kind == "lexicon":
            return word_state(self.definitions, *key)
        raise CurationError(f"unknown state kind {kind!r}")

    def _write(self, kind: str, key: tuple, value: Any, roots: set[int]) -> set[str]:
        """Write one state; returns dossier uids whose search index needs refreshing."""
        c, now = self.conn, repo.now()
        if kind == "field":
            if value is None:
                c.execute("DELETE FROM override_field WHERE dossier_uid = ? AND field = ?", key)
            else:
                c.execute("INSERT INTO override_field (dossier_uid, field, value, set_at) VALUES (?, ?, ?, ?)"
                          " ON CONFLICT (dossier_uid, field) DO UPDATE SET value = excluded.value,"
                          " set_at = excluded.set_at", (*key, repo.to_json(value), now))
            return {key[0]}
        if kind == "tag":
            if value is None:
                c.execute("DELETE FROM override_tag WHERE dossier_uid = ? AND tag = ?", key)
            else:
                c.execute("INSERT INTO override_tag (dossier_uid, tag, action, set_at) VALUES (?, ?, ?, ?)"
                          " ON CONFLICT (dossier_uid, tag) DO UPDATE SET action = excluded.action,"
                          " set_at = excluded.set_at", (*key, value, now))
            return {key[0]}
        if kind in ("parent", "link"):
            link_kind = "dossier_to_parent" if kind == "parent" else "file_to_dossier"
            if kind == "link":
                roots.add(int(key[0].split(":")[1]))
            if value is None:
                c.execute("DELETE FROM override_link WHERE kind = ? AND subject = ?", (link_kind, key[0]))
            else:
                c.execute("INSERT INTO override_link (kind, subject, target_uid, role, set_at) VALUES (?, ?, ?, ?, ?)"
                          " ON CONFLICT (kind, subject) DO UPDATE SET target_uid = excluded.target_uid,"
                          " role = excluded.role, set_at = excluded.set_at",
                          (link_kind, key[0], value["target"], value.get("role"), now))
            return {key[0]} if kind == "parent" else ({value["target"]} if value else set())
        if kind == "alias":
            if value is None:
                c.execute("DELETE FROM dossier_alias WHERE alias_uid = ?", key)
            else:
                c.execute("INSERT INTO dossier_alias (alias_uid, target_uid, set_at) VALUES (?, ?, ?)"
                          " ON CONFLICT (alias_uid) DO UPDATE SET target_uid = excluded.target_uid", (*key, value, now))
            return {key[0]}
        if kind == "entry":
            previous = self._read("entry", key)["dossier"]
            target = c.execute("SELECT id FROM dossier WHERE uid = ?", (value["dossier"],)).fetchone()
            if target is None:
                raise CurationError(f"no dossier {value['dossier']}")
            env = c.execute("SELECT l.environment_id FROM entry e JOIN ledger l ON l.id = e.ledger_id WHERE e.id = ?",
                            key).fetchone()[0]
            ledger_id = repo.ensure_ledger(c, target[0], env)
            c.execute("UPDATE entry SET ledger_id = ?, moved_from = ?, variant = ? WHERE id = ?",
                      (ledger_id, value["moved_from"], value["variant"], key[0]))
            c.execute("DELETE FROM ledger WHERE environment_id = ? AND NOT EXISTS"
                      " (SELECT 1 FROM entry e WHERE e.ledger_id = ledger.id)", (env,))
            return {previous, value["dossier"]}
        if kind == "dossier":
            row = c.execute("SELECT id FROM dossier WHERE uid = ?", key).fetchone()
            if value is None:
                if row is not None:
                    if c.execute("SELECT 1 FROM ledger WHERE dossier_id = ?", (row[0],)).fetchone():
                        raise CurationError("a dossier with entries cannot be removed")
                    c.execute("UPDATE dossier SET parent_id = NULL WHERE parent_id = ?", (row[0],))
                    repo.delete_dossier(c, row[0])
                return set()
            if row is None:
                repo.create_dossier(c, type_id=value["type_id"], name=value["name"], parent_id=None,
                                    confidence=1.0, signals=["created by the user"], uid=key[0])
            else:
                c.execute("UPDATE dossier SET type_id = ?, name = ? WHERE id = ?", (value["type_id"], value["name"], row[0]))
            return {key[0]}
        if kind == "collection":
            if value is None:
                c.execute("DELETE FROM collection WHERE uid = ?", key)
            else:
                c.execute("INSERT INTO collection (uid, name, query, created_at) VALUES (?, ?, ?, ?)"
                          " ON CONFLICT (uid) DO UPDATE SET name = excluded.name, query = excluded.query",
                          (*key, value["name"], value["query"], now))
            return set()
        if kind == "member":
            if value is None:
                c.execute("DELETE FROM collection_member WHERE collection_uid = ? AND dossier_uid = ?", key)
            else:
                c.execute("INSERT OR IGNORE INTO collection_member (collection_uid, dossier_uid, added_at)"
                          " VALUES (?, ?, ?)", (*key, now))
            return set()
        if kind == "suggestion":
            c.execute("UPDATE suggestion SET state = ?, decided_at = ? WHERE id = ?",
                      (value["state"], value["decided_at"], key[0]))
            return set()
        if kind == "lexicon":
            # True: in the user's file; "excluded": removed from a generated lexicon; None: neither.
            set_word(self.definitions, *key, present=value is True, user_dir=self.user_dir,
                     excluded=value == "excluded")
            return set()
        raise CurationError(f"unknown state kind {kind!r}")


def history(conn: sqlite3.Connection, limit: int = 50) -> list[dict]:
    """The latest curation actions, newest first, with whether each can be undone."""
    rows = conn.execute("SELECT * FROM curation_log ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    out = []
    for row in rows:
        payload = json.loads(row["payload"])
        out.append({"id": row["id"], "at": row["at"], "action": row["action"],
                    "undoable": "inverse" in payload,
                    **{k: v for k, v in payload.items() if k not in ("changes", "inverse")}})
    return out
