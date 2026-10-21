"""Classification: lexicons and other signals turn names into tags, variant words and structural
roles, and agreeing evidence raises a dossier's confidence.

Runs at the end of identification and again on its own when a lexicon changes (``exchange
classify``); it only rewrites what it produced itself, so it is cheap and repeatable.

Signals, each recorded as the tag's source with its own confidence:

* ``name``: the dossier's name, tokenized, minus noise words.
* ``folder``: the folders above its primary file ("Food/", "Props/", or a category word).
* ``metadata``: categories the environment supplies (Daz manifest categories).
"""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from exchange.db import repository as repo
from exchange.definitions.schema import DefinitionSet
from exchange.lexicons import LexiconIndex
from exchange.scanner.tokenize import tokenize

SOURCES = ("name", "folder", "metadata")
SIGNAL_CONFIDENCE = {"name": 0.6, "folder": 0.75, "metadata": 0.8}
TAG_BOOST = 0.1  # some category evidence
AGREEMENT_BOOST = 0.05  # two independent signals name the same tag
FOLDER_DEPTH = 4  # how many folders above a file count as evidence
SOURCE = "classify"  # dossier_field source for what this pass writes


@dataclass
class ClassifyStats:
    dossiers: int = 0
    tagged: int = 0
    structural: int = 0
    changed_confidence: int = 0


@dataclass
class Classification:
    tags: dict[tuple[str, str], float]  # (tag, source) -> confidence
    fields: dict[str, object]
    confidence: float


def classify_one(index: LexiconIndex, name: str, rel_path: str | None, categories: Iterable[str],
                 base: float) -> Classification:
    tags: dict[tuple[str, str], float] = {}
    tokens = index.clean(tokenize(name))
    fields: dict[str, object] = {}
    variants: dict[str, str] = {}
    for m in index.match(tokens):
        if m.kind == "category":
            tags[(m.value, "name")] = SIGNAL_CONFIDENCE["name"]
        elif m.kind == "variant":
            variants.setdefault(m.value, m.word)
        elif m.kind == "structural":
            _structural(fields, m.value, tokens, m.start + m.length)
    stem = (rel_path or name).rsplit("/", 1)[-1].rsplit(".", 1)[0]
    for m in index.match_stem(stem):
        if m.kind == "structural":
            _structural(fields, m.value, [], 0)
    if variants:
        fields["variant_words"] = variants

    if rel_path:
        for folder in rel_path.split("/")[:-1][-FOLDER_DEPTH:]:
            _segment(index, folder, "folder", tags)
    for category in categories:
        for segment in str(category).split("/"):
            if segment and segment.lower() != "default":
                _segment(index, segment, "metadata", tags)

    confidence = base
    if tags:
        confidence += TAG_BOOST
        by_tag: dict[str, set[str]] = defaultdict(set)
        for tag, source in tags:
            by_tag[tag].add(source)
        if any(len(sources) > 1 for sources in by_tag.values()):
            confidence += AGREEMENT_BOOST
    return Classification(tags, fields, round(min(confidence, 1.0), 4))


def _segment(index: LexiconIndex, segment: str, source: str, tags: dict) -> None:
    tag = index.tag_names.get(segment.casefold())
    if tag is None and segment.casefold().endswith("s"):
        tag = index.tag_names.get(segment.casefold()[:-1])
    if tag is not None:
        tags[(tag, source)] = SIGNAL_CONFIDENCE[source]
        return
    for m in index.match(index.clean(tokenize(segment))):
        if m.kind == "category":
            tags[(m.value, source)] = round(SIGNAL_CONFIDENCE[source] - 0.1, 2)


def _structural(fields: dict, role: str, tokens: list[str], after: int) -> None:
    if role == "lod":
        if after < len(tokens) and tokens[after].isdigit():
            fields["structural_role"] = "lod"
            fields["lod_level"] = int(tokens[after])
    else:
        fields["structural_role"] = role


def classify(conn: sqlite3.Connection, definitions: DefinitionSet, *,
             environment_ids: Iterable[int] | None = None) -> ClassifyStats:
    """Classify the live dossiers of some environments (all when None)."""
    stats = ClassifyStats()
    index = LexiconIndex(definitions)
    where, params = "", []
    if environment_ids is not None:
        ids = list(environment_ids)
        if not ids:
            return stats
        where = f" AND l.environment_id IN ({','.join('?' * len(ids))})"
        params = ids
    rows = conn.execute(
        "SELECT d.id, d.name, d.confidence, COALESCE(d.confidence_base, d.confidence) AS base,"
        " (SELECT f.rel_path FROM ledger l2 JOIN entry e2 ON e2.ledger_id = l2.id"
        "   JOIN entry_file ef ON ef.entry_id = e2.id AND ef.role = 'primary'"
        "   JOIN file f ON f.id = ef.file_id WHERE l2.dossier_id = d.id AND e2.status != 'retired'"
        "   ORDER BY e2.id LIMIT 1) AS rel_path,"
        " (SELECT group_concat(x.value, char(31)) FROM dossier_field x WHERE x.dossier_id = d.id"
        "   AND x.field = 'daz_categories') AS categories"
        " FROM dossier d WHERE EXISTS (SELECT 1 FROM ledger l JOIN entry e ON e.ledger_id = l.id"
        f"   WHERE l.dossier_id = d.id AND e.status != 'retired'{where})", params).fetchall()

    existing: dict[int, dict[tuple[str, str], float]] = defaultdict(dict)
    marks = ",".join("?" * len(SOURCES))
    for r in conn.execute(f"SELECT dossier_id, tag, source, confidence FROM dossier_tag WHERE source IN ({marks})",
                          SOURCES):
        existing[r[0]][(r[1], r[2])] = r[3]

    changed_tags: list[int] = []
    confidence_updates: list[tuple[float, int]] = []
    for row in rows:
        categories: list[str] = []
        for chunk in (row["categories"] or "").split(chr(31)):
            if chunk:
                value = json.loads(chunk)
                categories.extend(value if isinstance(value, list) else [value])
        result = classify_one(index, row["name"], row["rel_path"], categories, row["base"])
        stats.dossiers += 1
        stats.tagged += bool(result.tags)
        stats.structural += "structural_role" in result.fields
        if result.tags != existing.get(row["id"], {}):
            changed_tags.append(row["id"])
            conn.execute(f"DELETE FROM dossier_tag WHERE dossier_id = ? AND source IN ({marks})",
                         (row["id"], *SOURCES))
            conn.executemany("INSERT INTO dossier_tag (dossier_id, tag, source, confidence) VALUES (?, ?, ?, ?)",
                             [(row["id"], tag, source, conf) for (tag, source), conf in result.tags.items()])
        repo.replace_scanned_fields(conn, row["id"], SOURCE, result.fields)
        if abs(result.confidence - row["confidence"]) > 1e-9:
            confidence_updates.append((result.confidence, row["id"]))
    conn.executemany("UPDATE dossier SET confidence = ? WHERE id = ?", confidence_updates)
    stats.changed_confidence = len(confidence_updates)
    repo.index_dossiers(conn, changed_tags)
    return stats
