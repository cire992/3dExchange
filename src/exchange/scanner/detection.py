"""Detect environments inside a discovered folder and split it between them.

Every environment definition's signatures are scored against candidate roots: directories where
at least one file, dir or ini_value signature matches. A candidate whose summed weight (capped at
1.0) reaches the definition's ``min_confidence`` is an environment. When roots nest, each file
belongs to the deepest (most specific) one; files no environment claims fall through to the
fallback environment (Loose Files) rooted at the scanned folder.

Each detected environment here is one root; the scan groups roots into environments (several Daz
content directories become one Daz Studio environment). Roots the library already knows keep their
environment's type even if detection would now say otherwise.
"""

from __future__ import annotations

import bisect
from collections import defaultdict
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from exchange.definitions.schema import DefinitionSet, EnvironmentDefinition, Signature
from exchange.globs import glob_match
from exchange.paths import fold, join_rel, to_path
from exchange.scanner.discovery import DiscoveredFile, Discovery
from exchange.scanner.readonly import ini_value, read_ini


@dataclass(frozen=True)
class RegisteredEnvironment:
    """A root the library already knows, with its environment's type."""

    root: Path
    type_id: str
    confidence: float


@dataclass
class DetectedEnvironment:
    definition: EnvironmentDefinition
    root_rel: str  # relative to the discovery root, original case ("" = the root itself)
    root: Path
    confidence: float
    signals: list[str]
    variant: str | None = None
    registered: bool = False
    files: list[DiscoveredFile] = field(default_factory=list)  # rel paths relative to ``root``


class TreeIndex:
    """Case-insensitive lookups over a discovery result."""

    def __init__(self, discovery: Discovery) -> None:
        self.root = discovery.root
        self.files = {fold(f.rel): f.rel for f in discovery.files}
        self.dirs = {fold(d): d for d in discovery.dirs}
        self.dirs[""] = ""
        self._sorted_files = sorted(self.files)
        self._files_by_name: dict[str, list[str]] = defaultdict(list)
        self._dirs_by_name: dict[str, list[str]] = defaultdict(list)
        for key in self.files:
            self._files_by_name[key.rsplit("/", 1)[-1]].append(key)
        for key in self.dirs:
            if key:
                self._dirs_by_name[key.rsplit("/", 1)[-1]].append(key)
        self._ini_cache: dict[str, object] = {}

    def anchors(self, path: str, *, is_dir: bool) -> Iterator[str]:
        """Folded roots D such that D/path exists."""
        key = fold(path)
        by_name = self._dirs_by_name if is_dir else self._files_by_name
        for full in by_name.get(key.rsplit("/", 1)[-1], ()):
            if full == key:
                yield ""
            elif full.endswith("/" + key):
                yield full[: -len(key) - 1]

    def glob_anchors(self, pattern: str) -> Iterator[str]:
        """Folded roots D holding a file directly whose name matches ``pattern`` (e.g. *.uproject)."""
        for key in self.files:
            parent, _, name = key.rpartition("/")
            if glob_match(pattern, name):
                yield parent

    def files_under(self, root_key: str) -> Iterator[str]:
        prefix = root_key + "/" if root_key else ""
        i = bisect.bisect_left(self._sorted_files, prefix)
        while i < len(self._sorted_files) and self._sorted_files[i].startswith(prefix):
            yield self._sorted_files[i][len(prefix) :]
            i += 1

    def ini(self, file_key: str):
        if file_key not in self._ini_cache:
            self._ini_cache[file_key] = read_ini(to_path(self.root, self.files[file_key]))
        return self._ini_cache[file_key]

    def matches(self, sig: Signature, root_key: str) -> bool:
        if sig.kind == "glob":
            return any(glob_match(sig.glob, rel) for rel in self.files_under(root_key))
        target = join_rel(root_key, fold(sig.path))
        if sig.kind == "dir":
            return target in self.dirs
        if target not in self.files:
            return False
        if sig.kind == "file":
            return True
        value = ini_value(self.ini(target), sig.section, sig.key)
        return value is not None and fold(value) == fold(sig.equals)

    def score(self, definition: EnvironmentDefinition, root_key: str) -> tuple[float, list[str]]:
        total, signals = 0.0, []
        for sig in definition.signatures:
            if self.matches(sig, root_key):
                total += sig.weight
                signals.append(sig.describe())
        return min(round(total, 6), 1.0), signals


def detect(
    discovery: Discovery,
    definitions: DefinitionSet,
    registered: Sequence[RegisteredEnvironment] = (),
) -> list[DetectedEnvironment]:
    """Detect environments and assign every discovered file to exactly one of them."""
    index = TreeIndex(discovery)
    best: dict[str, DetectedEnvironment] = {}

    for definition in definitions.environments.values():
        if definition.fallback:
            continue
        roots: set[str] = set()
        for sig in definition.signatures:
            if sig.kind in ("file", "ini_value"):
                roots.update(index.anchors(sig.path, is_dir=False))
            elif sig.kind == "dir":
                roots.update(index.anchors(sig.path, is_dir=True))
            elif sig.kind == "glob" and "/" not in sig.glob:
                roots.update(index.glob_anchors(sig.glob))
        for root_key in sorted(roots):
            score, signals = index.score(definition, root_key)
            if score < definition.min_confidence:
                continue
            current = best.get(root_key)
            if current is None or (score, len(signals)) > (current.confidence, len(current.signals)):
                best[root_key] = _detected(index, definition, root_key, score, signals)

    for reg in registered:
        try:
            rel = reg.root.relative_to(discovery.root)
        except ValueError:
            continue
        root_key = fold(rel.as_posix()) if rel.parts else ""
        definition = definitions.environments.get(reg.type_id)
        if root_key not in index.dirs or definition is None:
            continue
        if definition.fallback:
            score, signals = reg.confidence, ["registered"]
        else:
            score, signals = index.score(definition, root_key)
        env = _detected(index, definition, root_key, score, signals)
        env.registered = True
        best[root_key] = env

    # A root inside another root of the same type is part of it (a Daz Connect product folder
    # looks like a content directory of its own), unless the library already knows it.
    for root_key, env in list(best.items()):
        if env.registered:
            continue
        outer = [k for k, e in best.items()
                 if e.definition.id == env.definition.id and k != root_key
                 and (k == "" or root_key.startswith(k + "/"))]
        if outer:
            del best[root_key]

    environments = sorted(best.values(), key=lambda e: e.root_rel.count("/") + bool(e.root_rel),
                          reverse=True)
    leftovers = _assign(discovery, environments)
    if leftovers or not environments:
        fallback = definitions.fallback_environment
        env = _detected(index, fallback, "", fallback.min_confidence, [])
        env.files = leftovers
        environments.append(env)

    for env in environments:
        env.variant = _environment_variant(index, env)
    environments.sort(key=lambda e: fold(e.root_rel))
    return environments


def _detected(index: TreeIndex, definition: EnvironmentDefinition, root_key: str, score: float,
              signals: list[str]) -> DetectedEnvironment:
    root_rel = index.dirs[root_key]
    return DetectedEnvironment(definition, root_rel, to_path(index.root, root_rel), score, signals)


def _assign(discovery: Discovery, deepest_first: list[DetectedEnvironment]) -> list[DiscoveredFile]:
    """Give each file to the deepest environment containing it; return the unclaimed files."""
    prefixes = [(fold(e.root_rel) + "/" if e.root_rel else "", e) for e in deepest_first]
    leftovers = []
    for f in discovery.files:
        key = fold(f.rel)
        for prefix, env in prefixes:
            if key.startswith(prefix):
                rel = f.rel[len(prefix) :]
                env.files.append(DiscoveredFile(rel, f.size, f.mtime_ns))
                break
        else:
            leftovers.append(f)
    return leftovers


def _environment_variant(index: TreeIndex, env: DetectedEnvironment) -> str | None:
    root_key = fold(env.root_rel)
    for variant in env.definition.variants:
        if variant.level == "environment" and any(index.matches(s, root_key) for s in variant.match):
            return variant.id
    return None
