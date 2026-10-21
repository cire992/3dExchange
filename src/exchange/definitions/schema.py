"""In-memory form of environment and dossier-type definitions (see ``loader`` for the files)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

SIGNATURE_KINDS = ("file", "dir", "glob", "ini_value")
VARIANT_LEVELS = ("environment", "dossier")
TYPE_SCOPES = ("universal", "environment")
CAPABILITIES = ("indexable", "readable", "writable")


@dataclass(frozen=True)
class Signature:
    """One detection clue, evaluated relative to a candidate environment root."""

    kind: str
    weight: float
    path: str = ""  # file, dir, ini_value: "/"-separated relative path
    glob: str = ""  # glob: any file under the root matching it
    section: str = ""  # ini_value
    key: str = ""
    equals: str = ""

    def describe(self) -> str:
        if self.kind == "glob":
            return f"glob {self.glob}"
        if self.kind == "ini_value":
            return f"{self.path} [{self.section}] {self.key}={self.equals}"
        return f"{self.kind} {self.path}"


@dataclass(frozen=True)
class Variant:
    id: str
    name: str
    level: str  # "environment": matched once per environment; "dossier": per primary file
    match: tuple[Signature, ...] = ()  # environment level, any match wins
    globs: tuple[str, ...] = ()  # dossier level, relative to the container


@dataclass(frozen=True)
class EnvironmentDefinition:
    id: str
    name: str
    source: str
    handler: str
    signatures: tuple[Signature, ...] = ()
    min_confidence: float = 0.5
    fallback: bool = False  # receives files no other environment claims (Loose Files)
    multi_root: bool = False  # one environment gathers every root of this type (Daz content dirs)
    layer_options: Mapping[str, Any] = field(default_factory=dict)
    ignore_globs: tuple[str, ...] = ()
    capabilities: Mapping[str, bool] = field(default_factory=dict)
    variants: tuple[Variant, ...] = ()
    uses_content_from: tuple[str, ...] = ()
    native_dossier_types: tuple[str, ...] = ()


@dataclass(frozen=True)
class IdentifyRule:
    glob: str  # relative to the container root
    confidence: float
    environment: str | None = None  # only applies in this environment type


@dataclass(frozen=True)
class DossierTypeDefinition:
    id: str
    name: str
    source: str
    scope: str
    environment: str | None = None
    extends: str | None = None
    identify: tuple[IdentifyRule, ...] = ()


@dataclass
class DefinitionSet:
    environments: dict[str, EnvironmentDefinition]
    dossier_types: dict[str, DossierTypeDefinition]

    @property
    def fallback_environment(self) -> EnvironmentDefinition:
        return next(e for e in self.environments.values() if e.fallback)

    def is_a(self, type_id: str, ancestor: str) -> bool:
        current: str | None = type_id
        while current is not None:
            if current == ancestor:
                return True
            current = self.dossier_types[current].extends
        return False
