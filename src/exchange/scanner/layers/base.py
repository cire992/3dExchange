"""The contract between the identification engine and organizational-layer handlers.

A handler reads one environment through its organizational layer (MO2 mods, Daz manifests,
plain folders) and says which containers and products exist. The engine then turns that into
dossiers, ledgers and entries, applying dossier-type rules to individual files.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from exchange.definitions.schema import DefinitionSet, EnvironmentDefinition
from exchange.globs import glob_match
from exchange.paths import to_path
from exchange.scanner import readonly


@dataclass(frozen=True)
class FileInfo:
    id: int
    rel: str  # relative to the environment root
    size: int
    mtime_ns: int
    ext: str


@dataclass(frozen=True)
class TypeMatch:
    type_id: str
    confidence: float
    glob: str


@dataclass
class ContainerSpec:
    rel_path: str  # relative to the environment root; "" is the root itself
    kind: str
    name: str
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProductSpec:
    container_rel: str
    identity_key: str  # stable across rescans within the container
    name: str
    confidence: float
    signals: list[str]
    fields: dict[str, Any] = field(default_factory=dict)
    primary: list[str] = field(default_factory=list)  # env-relative paths, e.g. the manifest
    members: list[str] = field(default_factory=list)  # env-relative paths of contained files


@dataclass
class LayerResult:
    containers: list[ContainerSpec] = field(default_factory=list)
    products: list[ProductSpec] = field(default_factory=list)
    ignored: set[str] = field(default_factory=set)  # env-relative paths that are not content
    layer_config: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


class LayerContext:
    def __init__(self, root: Path, definition: EnvironmentDefinition, definitions: DefinitionSet,
                 files: list[FileInfo], all_files: list[FileInfo]) -> None:
        self.root = root
        self.definition = definition
        self.definitions = definitions
        self.files = files  # present files, minus the definition's ignore globs
        self.all_files = all_files  # every present file, for reading layer configuration
        self._env_types = [t for t in definitions.dossier_types.values()
                           if t.environment == definition.id and t.identify]
        self._universal_types = [t for t in definitions.dossier_types.values()
                                 if t.scope == "universal" and t.identify]

    @property
    def options(self) -> Mapping[str, Any]:
        return self.definition.layer_options

    def read_bytes(self, rel: str) -> bytes | None:
        return readonly.read_bytes(to_path(self.root, rel))

    def read_ini(self, rel: str):
        return readonly.read_ini(to_path(self.root, rel))

    def match_type(self, rel_in_container: str) -> TypeMatch | None:
        """Best dossier type for a file. Environment-specific types beat universal ones."""
        for group in (self._env_types, self._universal_types):
            best: TypeMatch | None = None
            for dtype in group:
                for rule in dtype.identify:
                    if (best is None or rule.confidence > best.confidence) and glob_match(
                        rule.glob, rel_in_container
                    ):
                        best = TypeMatch(dtype.id, rule.confidence, rule.glob)
            if best is not None:
                return best
        return None


Handler = Callable[[LayerContext], LayerResult]
