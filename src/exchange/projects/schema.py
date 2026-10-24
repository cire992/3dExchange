"""Record schemas: one per signature, in a small YAML format.

The core ships a schema for each signature it knows (``exchange/projects/schemas/<SIG>.yaml``); a
project home's ``schemas/`` folder adds project-exclusive signatures, never changing the core's::

    signature: NPC_
    title: Non-player character
    fields:
      race: { type: link, to: [RACE], required_at: spec }
      factions:
        type: list
        of: { type: object, fields: { faction: { type: link, to: [FACT] }, rank: { type: text } } }

Field types: ``text``, ``int``, ``number``, ``bool``, ``date``, ``enum`` (``values``), ``link`` (to
records of the signatures in ``to``), ``dossier`` (a dossier uid), ``process`` (a process id),
``claim`` (a claim id), ``list`` (``of`` one field) and ``object`` (named ``fields``). Any field may
say ``required_at``: the maturity from which it must be filled. A link's ``max_demand`` caps the
maturity it can require of its target (Spec unless set). A schema with a ``template_field`` (an
enum) may restrict fields to some of its values with ``templates``.

Every record also has the common fields ``id``, ``maturity``, ``name``, ``origin`` and ``tags``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from exchange.projects.frontmatter import FrontMatterError, load_yaml

LEVELS = ("Sketch", "Spec", "Stub", "Built", "Polished")
SPEC = 1
SIGNATURE = re.compile(r"^(?:[A-Z]{3}_|[A-Z]{4})$")
EDITOR_ID = re.compile(r"^(?:[A-Z]{3}_|[A-Z]{4}_)[A-Za-z0-9][A-Za-z0-9_]*$")
FIELD_TYPES = ("text", "int", "number", "bool", "date", "enum", "link", "dossier", "process", "claim",
               "list", "object")
_FIELD_KEYS = {"type", "to", "values", "of", "fields", "required_at", "pattern", "max_demand",
               "templates", "description"}
_SCHEMA_KEYS = {"signature", "title", "description", "template_field", "fields"}


class SchemaError(ValueError):
    """A schema file is invalid."""


def signature_of(editor_id: str) -> str | None:
    """``NPC_DockMaster`` → ``NPC_``; ``FACT_PortAuthority`` → ``FACT``; None if not an editor ID."""
    if not EDITOR_ID.match(editor_id):
        return None
    return editor_id[:4]


def maturity_value(value: Any) -> int | None:
    """A maturity level from 0-4 or a level name (any case); None if it is neither."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if 0 <= value < len(LEVELS) else None
    if isinstance(value, str):
        names = [name.casefold() for name in LEVELS]
        if value.strip().casefold() in names:
            return names.index(value.strip().casefold())
        if value.strip().isdigit():
            return maturity_value(int(value.strip()))
    return None


def level_name(level: int) -> str:
    return f"{LEVELS[level]} ({level})"


@dataclass(frozen=True)
class Field:
    name: str
    type: str
    required_at: int | None = None
    to: tuple[str, ...] = ()
    values: tuple[str, ...] = ()
    of: Field | None = None
    fields: dict[str, Field] = field(default_factory=dict)
    pattern: re.Pattern | None = None
    max_demand: int = SPEC
    templates: tuple[str, ...] = ()
    description: str = ""


@dataclass(frozen=True)
class RecordType:
    signature: str
    title: str
    fields: dict[str, Field]
    source: Path | None = None
    builtin: bool = True
    template_field: str | None = None
    description: str = ""


# Fields every record has; schemas cannot redefine them.
COMMON_FIELDS: dict[str, Field] = {
    "id": Field("id", "text"),
    "maturity": Field("maturity", "int"),
    "name": Field("name", "text", description="display name; defaults to the editor ID"),
    "origin": Field("origin", "claim", description="the idea claim this record was promoted from"),
    "tags": Field("tags", "list", of=Field("tags[]", "text")),
}


def _field(name: str, raw: Any, where: str) -> Field:
    if isinstance(raw, str):
        raw = {"type": raw}
    if not isinstance(raw, dict):
        raise SchemaError(f"{where}: the field must be a mapping (or a type name)")
    unknown = set(raw) - _FIELD_KEYS
    if unknown:
        raise SchemaError(f"{where}: unknown keys {', '.join(sorted(unknown))}")
    kind = raw.get("type")
    if kind not in FIELD_TYPES:
        raise SchemaError(f"{where}: type must be one of {', '.join(FIELD_TYPES)}, not {kind!r}")
    required_at = None
    if "required_at" in raw:
        required_at = maturity_value(raw["required_at"])
        if required_at is None:
            raise SchemaError(f"{where}: required_at must be a maturity level (0-4 or a level name)")
    to: tuple[str, ...] = ()
    if kind == "link":
        to = tuple(raw.get("to") or ())
        if not to or not all(isinstance(s, str) and SIGNATURE.match(s) for s in to):
            raise SchemaError(f"{where}: a link needs 'to', a list of signatures such as [RACE] or [NPC_]")
    elif "to" in raw:
        raise SchemaError(f"{where}: only a link has 'to'")
    max_demand = SPEC
    if "max_demand" in raw:
        if kind != "link" or maturity_value(raw["max_demand"]) is None:
            raise SchemaError(f"{where}: max_demand is a maturity level, and only for links")
        max_demand = maturity_value(raw["max_demand"])
    values: tuple[str, ...] = ()
    if kind == "enum":
        values = tuple(str(v) for v in raw.get("values") or ())
        if not values:
            raise SchemaError(f"{where}: an enum needs 'values'")
    elif "values" in raw:
        raise SchemaError(f"{where}: only an enum has 'values'")
    of = None
    if kind == "list":
        if "of" not in raw:
            raise SchemaError(f"{where}: a list needs 'of'")
        of = _field(f"{name}[]", raw["of"], f"{where}.of")
    elif "of" in raw:
        raise SchemaError(f"{where}: only a list has 'of'")
    fields: dict[str, Field] = {}
    if kind == "object":
        sub = raw.get("fields")
        if not isinstance(sub, dict) or not sub:
            raise SchemaError(f"{where}: an object needs 'fields'")
        fields = {str(k): _field(str(k), v, f"{where}.{k}") for k, v in sub.items()}
    elif "fields" in raw:
        raise SchemaError(f"{where}: only an object has 'fields'")
    pattern = None
    if "pattern" in raw:
        if kind != "text":
            raise SchemaError(f"{where}: only text has a 'pattern'")
        try:
            pattern = re.compile(str(raw["pattern"]))
        except re.error as exc:
            raise SchemaError(f"{where}: the pattern is not a valid regular expression: {exc}") from exc
    templates = tuple(str(t) for t in raw.get("templates") or ())
    return Field(name, kind, required_at, to, values, of, fields, pattern, max_demand, templates,
                 str(raw.get("description") or ""))


def parse_schema(text: str, source: Path, *, builtin: bool) -> RecordType:
    try:
        raw = load_yaml(text)
    except FrontMatterError as exc:
        raise SchemaError(f"{source}: {exc}") from exc
    if not isinstance(raw, dict):
        raise SchemaError(f"{source}: a schema is a mapping with 'signature' and 'fields'")
    unknown = set(raw) - _SCHEMA_KEYS
    if unknown:
        raise SchemaError(f"{source}: unknown keys {', '.join(sorted(unknown))}")
    signature = raw.get("signature")
    if not isinstance(signature, str) or not SIGNATURE.match(signature):
        raise SchemaError(f"{source}: 'signature' must be four capitals, or three and '_' (FACT, NPC_)")
    if source.stem != signature:
        raise SchemaError(f"{source}: the file must be named {signature}.yaml")
    fields_raw = raw.get("fields") or {}
    if not isinstance(fields_raw, dict):
        raise SchemaError(f"{source}: 'fields' must be a mapping")
    clash = set(fields_raw) & set(COMMON_FIELDS)
    if clash:
        raise SchemaError(f"{source}: {', '.join(sorted(clash))} are common to every record; leave them out")
    fields = {str(k): _field(str(k), v, f"{source}: {k}") for k, v in fields_raw.items()}
    template_field = raw.get("template_field")
    if template_field is not None:
        if template_field not in fields or fields[template_field].type != "enum":
            raise SchemaError(f"{source}: template_field must name one of its enum fields")
        allowed = set(fields[template_field].values)
        for f in fields.values():
            bad = set(f.templates) - allowed
            if bad:
                raise SchemaError(f"{source}: {f.name}: unknown templates {', '.join(sorted(bad))}")
    elif any(f.templates for f in fields.values()):
        raise SchemaError(f"{source}: 'templates' on a field needs a template_field")
    return RecordType(signature, str(raw.get("title") or signature), fields, source, builtin,
                      template_field, str(raw.get("description") or ""))


def builtin_schemas_dir() -> Path:
    return Path(__file__).parent / "schemas"


def load_builtin_schemas() -> dict[str, RecordType]:
    types = {}
    for path in sorted(builtin_schemas_dir().glob("*.yaml")):
        record_type = parse_schema(path.read_text(encoding="utf-8"), path, builtin=True)
        types[record_type.signature] = record_type
    return types


def load_schemas(project_dir: Path | None = None) -> tuple[dict[str, RecordType], list[tuple[Path, str]]]:
    """The core's schemas plus a project's; the problems with the project's, by file."""
    types = load_builtin_schemas()
    problems: list[tuple[Path, str]] = []
    if project_dir is not None and project_dir.is_dir():
        for path in sorted(project_dir.glob("*.yaml")):
            try:
                record_type = parse_schema(path.read_text(encoding="utf-8"), path, builtin=False)
            except (SchemaError, OSError, UnicodeDecodeError) as exc:
                problems.append((path, str(exc).removeprefix(f"{path}: ")))
                continue
            if record_type.signature in types:
                problems.append((path, f"{record_type.signature} is defined by Exchange itself; a project "
                                       "schema can only add a new signature"))
                continue
            types[record_type.signature] = record_type
    return types, problems
