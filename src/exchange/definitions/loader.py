"""Load environment and dossier-type definitions from TOML files.

Search order: the built-ins shipped with Exchange, then the user's definitions folder, then any
extra folders passed in. Each folder holds ``environments/*.toml`` and ``dossier_types/*.toml``.
A later file with the same ``id`` replaces an earlier one.

Validation is strict (unknown keys are errors) so a typo in a hand- or AI-written definition is
reported with its file and key instead of being silently ignored.
"""

from __future__ import annotations

import tomllib
from collections.abc import Iterable
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Any

from exchange.definitions.schema import (
    CAPABILITIES,
    SIGNATURE_KINDS,
    TYPE_SCOPES,
    VARIANT_LEVELS,
    DefinitionSet,
    DossierTypeDefinition,
    EnvironmentDefinition,
    IdentifyRule,
    Signature,
    Variant,
)
from exchange.errors import DefinitionError
from exchange.paths import normalize_rel, user_definitions_dir

FORMAT_VERSION = 1


def builtin_dir() -> Traversable:
    return resources.files("exchange.definitions").joinpath("builtin")


def load_definitions(
    extra_dirs: Iterable[Path] = (), *, include_user_dir: bool = True
) -> DefinitionSet:
    dirs: list[Traversable | Path] = [builtin_dir()]
    if include_user_dir:
        dirs.append(user_definitions_dir())
    dirs.extend(extra_dirs)

    environments: dict[str, EnvironmentDefinition] = {}
    dossier_types: dict[str, DossierTypeDefinition] = {}
    for base in dirs:
        for item in _toml_files(base, "environments"):
            env = parse_environment(_read_toml(item), str(item))
            environments[env.id] = env
        for item in _toml_files(base, "dossier_types"):
            dtype = parse_dossier_type(_read_toml(item), str(item))
            dossier_types[dtype.id] = dtype

    definitions = DefinitionSet(environments, dossier_types)
    validate(definitions)
    return definitions


def _toml_files(base: Traversable | Path, sub: str) -> list[Traversable | Path]:
    folder = base.joinpath(sub)
    if not folder.is_dir():
        return []
    return sorted((f for f in folder.iterdir() if f.name.endswith(".toml")), key=lambda f: f.name)


def _read_toml(item: Traversable | Path) -> dict[str, Any]:
    try:
        return tomllib.loads(item.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise DefinitionError(item, f"invalid TOML: {exc}") from exc
    except (OSError, UnicodeDecodeError) as exc:
        raise DefinitionError(item, f"cannot read: {exc}") from exc


# Strict table reading -----------------------------------------------------------------------


class _Table:
    def __init__(self, data: Any, source: str, where: str, allowed: Iterable[str]) -> None:
        if not isinstance(data, dict):
            raise DefinitionError(source, f"{where} must be a table")
        unknown = sorted(set(data) - set(allowed))
        if unknown:
            raise DefinitionError(source, f"unknown key {where}.{unknown[0]}")
        self.data, self.source, self.where = data, source, where

    def get(self, key: str, kind: type | tuple[type, ...], default: Any = ..., *,
            choices: Iterable[Any] | None = None) -> Any:
        if key not in self.data:
            if default is ...:
                raise DefinitionError(self.source, f"missing required key {self.where}.{key}")
            return default
        value = self.data[key]
        # bool is an int subclass; never accept it where a number is wanted.
        if not isinstance(value, kind) or (isinstance(value, bool) and bool not in _as_tuple(kind)):
            raise DefinitionError(
                self.source, f"{self.where}.{key} must be {_kind_name(kind)}, got {value!r}"
            )
        if choices is not None and value not in choices:
            raise DefinitionError(
                self.source, f"{self.where}.{key} must be one of {', '.join(choices)}"
            )
        return value

    def number(self, key: str, default: Any = ..., *, low: float = 0.0, high: float = 1.0) -> float:
        value = float(self.get(key, (int, float), default))
        if not low <= value <= high:
            raise DefinitionError(self.source, f"{self.where}.{key} must be between {low} and {high}")
        return value

    def strings(self, key: str) -> tuple[str, ...]:
        value = self.get(key, list, [])
        if not all(isinstance(v, str) for v in value):
            raise DefinitionError(self.source, f"{self.where}.{key} must be a list of strings")
        return tuple(value)

    def table(self, key: str, allowed: Iterable[str]) -> _Table:
        return _Table(self.data.get(key, {}), self.source, f"{self.where}.{key}".lstrip("."), allowed)

    def tables(self, key: str, allowed: Iterable[str]) -> list[_Table]:
        items = self.get(key, list, [])
        return [_Table(t, self.source, f"{key}[{i}]", allowed) for i, t in enumerate(items)]


def _as_tuple(kind: type | tuple[type, ...]) -> tuple[type, ...]:
    return kind if isinstance(kind, tuple) else (kind,)


def _kind_name(kind: type | tuple[type, ...]) -> str:
    names = {str: "a string", bool: "true or false", int: "a number", float: "a number",
             list: "a list", dict: "a table"}
    return " or ".join(dict.fromkeys(names.get(k, k.__name__) for k in _as_tuple(kind)))


def _identifier(table: _Table, key: str = "id") -> str:
    value = table.get(key, str)
    if not value or not value.replace("_", "").isalnum() or not value.isascii() or value != value.lower():
        raise DefinitionError(
            table.source, f"{table.where}.{key} must be lower_snake_case ASCII, got {value!r}"
        )
    return value


# Environment definitions ------------------------------------------------------------------------


def parse_environment(data: dict[str, Any], source: str) -> EnvironmentDefinition:
    top = _Table(data, source, "", ["environment", "detection", "layer", "ignore",
                                    "capabilities", "variant", "compatibility"])
    env = top.table("environment", ["id", "name", "format_version", "fallback", "multi_root"])
    version = env.get("format_version", int)
    if version != FORMAT_VERSION:
        raise DefinitionError(source, f"unsupported format_version {version} (expected {FORMAT_VERSION})")
    fallback = env.get("fallback", bool, False)

    detection = top.table("detection", ["min_confidence", "signature"])
    signatures = tuple(_signature(t) for t in detection.tables("signature", _SIGNATURE_KEYS))
    if not signatures and not fallback:
        raise DefinitionError(source, "detection.signature: at least one signature is required")

    layer = top.table("layer", ["handler", "options"])
    capabilities = top.table("capabilities", CAPABILITIES)
    compatibility = top.table("compatibility", ["uses_content_from", "native_dossier_types"])

    return EnvironmentDefinition(
        id=_identifier(env),
        name=env.get("name", str),
        source=source,
        handler=layer.get("handler", str),
        signatures=signatures,
        min_confidence=detection.number("min_confidence", 0.5),
        fallback=fallback,
        multi_root=env.get("multi_root", bool, False),
        layer_options=dict(layer.get("options", dict, {})),
        ignore_globs=top.table("ignore", ["globs"]).strings("globs"),
        capabilities={c: capabilities.get(c, bool, False) for c in CAPABILITIES},
        variants=tuple(_variant(t) for t in top.tables("variant", ["id", "name", "level", "match", "globs"])),
        uses_content_from=compatibility.strings("uses_content_from"),
        native_dossier_types=compatibility.strings("native_dossier_types"),
    )


_SIGNATURE_KEYS = ["kind", "weight", "path", "glob", "section", "key", "equals"]


def _signature(t: _Table) -> Signature:
    kind = t.get("kind", str, choices=SIGNATURE_KINDS)
    weight = t.number("weight", 1.0, low=0.0, high=1.0)
    if kind == "glob":
        return Signature(kind, weight, glob=t.get("glob", str))
    path = normalize_rel(t.get("path", str))
    if not path:
        raise DefinitionError(t.source, f"{t.where}.path must not be empty")
    if kind == "ini_value":
        return Signature(kind, weight, path=path, section=t.get("section", str),
                         key=t.get("key", str), equals=t.get("equals", str))
    return Signature(kind, weight, path=path)


def _variant(t: _Table) -> Variant:
    level = t.get("level", str, "environment", choices=VARIANT_LEVELS)
    if level == "environment":
        match = tuple(_signature(_Table(m, t.source, f"{t.where}.match[{i}]", _SIGNATURE_KEYS))
                      for i, m in enumerate(t.get("match", list)))
        return Variant(_identifier(t), t.get("name", str), level, match=match)
    return Variant(_identifier(t), t.get("name", str), level, globs=t.strings("globs"))


# Dossier-type definitions -----------------------------------------------------------------------


def parse_dossier_type(data: dict[str, Any], source: str) -> DossierTypeDefinition:
    top = _Table(data, source, "", ["dossier_type", "identify"])
    dt = top.table("dossier_type", ["id", "name", "format_version", "scope", "environment", "extends"])
    version = dt.get("format_version", int)
    if version != FORMAT_VERSION:
        raise DefinitionError(source, f"unsupported format_version {version} (expected {FORMAT_VERSION})")
    scope = dt.get("scope", str, choices=TYPE_SCOPES)
    environment = dt.get("environment", str, None)
    if (scope == "environment") != (environment is not None):
        raise DefinitionError(
            source, "dossier_type.environment is required for scope = \"environment\" and only then"
        )
    rules: list[IdentifyRule] = []
    for t in top.tables("identify", ["glob", "globs", "confidence", "environment"]):
        confidence = t.number("confidence")
        globs = ([t.get("glob", str)] if "glob" in t.data else []) + list(t.strings("globs"))
        if not globs:
            raise DefinitionError(source, f"{t.where} needs glob or globs")
        rule_env = t.get("environment", str, None) or environment
        rules.extend(IdentifyRule(g, confidence, rule_env) for g in globs)
    return DossierTypeDefinition(
        id=_identifier(dt),
        name=dt.get("name", str),
        source=source,
        scope=scope,
        environment=environment,
        extends=dt.get("extends", str, None),
        identify=tuple(rules),
    )


# Cross-file checks ------------------------------------------------------------------------------


def validate(definitions: DefinitionSet) -> None:
    from exchange.scanner.layers import HANDLERS  # the layer registry is code, not data

    envs, types = definitions.environments, definitions.dossier_types
    fallbacks = [e for e in envs.values() if e.fallback]
    if len(fallbacks) != 1:
        names = ", ".join(e.source for e in fallbacks) or "none found"
        raise DefinitionError("definitions", f"exactly one fallback environment is required ({names})")
    for env in envs.values():
        if env.handler not in HANDLERS:
            raise DefinitionError(
                env.source, f"layer.handler {env.handler!r} is not one of {', '.join(sorted(HANDLERS))}"
            )
        for ref in env.uses_content_from:
            if ref not in envs:
                raise DefinitionError(env.source, f"compatibility.uses_content_from: unknown environment {ref!r}")
        for ref in env.native_dossier_types:
            if ref not in types:
                raise DefinitionError(env.source, f"compatibility.native_dossier_types: unknown dossier type {ref!r}")
    for dtype in types.values():
        if dtype.environment is not None and dtype.environment not in envs:
            raise DefinitionError(dtype.source, f"dossier_type.environment: unknown environment {dtype.environment!r}")
        for rule in dtype.identify:
            if rule.environment is not None and rule.environment not in envs:
                raise DefinitionError(dtype.source, f"identify.environment: unknown environment {rule.environment!r}")
        seen = {dtype.id}
        parent = dtype.extends
        while parent is not None:
            if parent not in types:
                raise DefinitionError(dtype.source, f"dossier_type.extends: unknown dossier type {parent!r}")
            if parent in seen:
                raise DefinitionError(dtype.source, f"dossier_type.extends: cycle through {parent!r}")
            seen.add(parent)
            parent = types[parent].extends
    if "product" not in types:
        raise DefinitionError("definitions", "the built-in 'product' dossier type is missing")
