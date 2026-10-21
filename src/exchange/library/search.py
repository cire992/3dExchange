"""The search language: free text plus composable filters.

    donut env:starfield tag:food -tag:damaged type:mesh author:"Jane Doe" status:stale

* Free text matches names, filename tokens, tags and container names (prefix match per token).
* ``key:value`` filters; values with spaces go in double quotes. ``-`` in front negates a term or
  filter. All terms must hold.
* By default only dossiers with a live entry are shown; ``status:retired`` finds the others.

``compile_query`` turns a query into a SQL condition over ``dossier_effective`` (alias ``d``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from exchange.definitions.schema import DefinitionSet
from exchange.errors import ExchangeError
from exchange.scanner.tokenize import tokenize

ENTRY_STATUSES = ("origin", "requisitioned", "copied", "unknown", "modified", "stale", "retired")
FILTER_KEYS = ("env", "type", "tag", "author", "status", "container", "variant", "is", "has")
_TERM = re.compile(r'(-?)(?:(\w+):)?(?:"([^"]*)"|(\S+))')


class SearchError(ExchangeError):
    pass


@dataclass(frozen=True)
class Term:
    negated: bool
    key: str | None
    value: str


def parse_query(text: str) -> list[Term]:
    terms = []
    for m in _TERM.finditer(text):
        negated, key, quoted, bare = m.groups()
        value = quoted if quoted is not None else bare
        if key is not None and key.lower() not in FILTER_KEYS:
            raise SearchError(f"unknown filter {key}: (filters: {', '.join(FILTER_KEYS)})")
        if value == "" and key is not None:
            raise SearchError(f"{key}: needs a value")
        terms.append(Term(bool(negated), key.lower() if key else None, value))
    return terms


def compile_query(text: str, definitions: DefinitionSet, *,
                  threshold: float = 0.5) -> tuple[str, list]:
    """SQL condition (over ``dossier_effective d``) and its parameters."""
    clauses: list[str] = []
    params: list = []
    wants_retired = False
    for term in parse_query(text):
        sql, args = _clause(term, definitions, threshold)
        if term.key == "status" and term.value.lower() == "retired" and not term.negated:
            wants_retired = True
        clauses.append(f"NOT ({sql})" if term.negated else f"({sql})")
        params.extend(args)
    if not wants_retired:
        clauses.insert(0, _LIVE)
    return " AND ".join(clauses) or "1", params


_LIVE = ("EXISTS (SELECT 1 FROM ledger l JOIN entry e ON e.ledger_id = l.id"
         " WHERE l.dossier_id = d.id AND e.status != 'retired')")


def _entry_exists(condition: str) -> str:
    return ("EXISTS (SELECT 1 FROM ledger l JOIN entry e ON e.ledger_id = l.id"
            " JOIN container c ON c.id = e.container_id JOIN environment env ON env.id = l.environment_id"
            f" WHERE l.dossier_id = d.id AND {condition})")


def _field_like(fields: tuple[str, ...]) -> str:
    marks = ",".join("?" * len(fields))
    return (f"(EXISTS (SELECT 1 FROM dossier_field f WHERE f.dossier_id = d.id AND f.field IN ({marks})"
            f" AND f.value LIKE ? ESCAPE '\\')"
            f" OR EXISTS (SELECT 1 FROM override_field o WHERE o.dossier_uid = d.uid"
            f" AND o.field IN ({marks}) AND o.value LIKE ? ESCAPE '\\'))")


def _like(value: str) -> str:
    return "%" + value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _clause(term: Term, definitions: DefinitionSet, threshold: float) -> tuple[str, list]:
    value, key = term.value, term.key
    if key is None:
        tokens = tokenize(value)
        if not tokens:
            return "1", []
        match = " ".join(f'"{t}"*' for t in tokens)
        return "d.id IN (SELECT rowid FROM dossier_fts WHERE dossier_fts MATCH ?)", [match]
    if key == "env":
        cond = ("(env.type_id = ? OR lower(env.name) LIKE lower(?) ESCAPE '\\'"
                " OR CAST(env.id AS TEXT) = ?) AND e.status != 'retired'")
        return _entry_exists(cond), [value.lower(), _like(value), value]
    if key == "type":
        wanted = value.lower()
        known = [t for t in definitions.dossier_types
                 if t == wanted or definitions.dossier_types[t].name.lower() == wanted]
        if not known:
            raise SearchError(f"unknown dossier type {value!r}")
        types = sorted({t for t in definitions.dossier_types if any(definitions.is_a(t, k) for k in known)})
        return f"d.type_id IN ({','.join('?' * len(types))})", types
    if key == "tag":
        return ("EXISTS (SELECT 1 FROM dossier_tag_effective t WHERE t.dossier_uid = d.uid"
                " AND lower(t.tag) = lower(?))"), [value]
    if key == "author":
        fields = ("authors", "author")
        return _field_like(fields), [*fields, _like(value), *fields, _like(value)]
    if key == "variant":
        fields = ("variant",)
        return _field_like(fields), [*fields, _like(value), *fields, _like(value)]
    if key == "status":
        if value.lower() not in ENTRY_STATUSES:
            raise SearchError(f"unknown status {value!r} (one of {', '.join(ENTRY_STATUSES)})")
        return _entry_exists("e.status = ?"), [value.lower()]
    if key == "container":
        return _entry_exists("lower(c.name) LIKE lower(?) ESCAPE '\\' AND e.status != 'retired'"), [_like(value)]
    if key == "is":
        if value.lower() == "unidentified":
            return "d.confidence < ?", [threshold]
        if value.lower() == "product":
            return "d.type_id = 'product'", []
        if value.lower() == "overridden":
            return "(d.name_overridden OR d.type_overridden OR d.parent_overridden)", []
        raise SearchError(f"unknown is:{value} (is:unidentified, is:product, is:overridden)")
    if key == "has":
        v = value.lower()
        if v == "thumbnail":
            return "EXISTS (SELECT 1 FROM thumbnail t WHERE t.dossier_id = d.id)", []
        if v in ("broken", "broken-dependency"):
            return ("EXISTS (SELECT 1 FROM dossier_dependency x WHERE x.dossier_id = d.id"
                    " AND x.status = 'broken')"), []
        if v == "candidate":
            raise SearchError("has:candidate needs pipelines, which arrive in Roadmap phase 4")
        raise SearchError(f"unknown has:{value} (has:thumbnail, has:broken)")
    raise SearchError(f"unknown filter {key}:")  # parse_query already rejects these
