"""Finding pipeline packages, trusting them, loading their operations and checking prerequisites.

Packages come from two places: the built-ins shipped with Exchange and the user's
``pipelines/`` folder in the Exchange data folder (one folder per package)::

    glb_to_starfield_ingestible/
    ├─ pipeline.toml        manifest (see manifest.py)
    ├─ operations/          Python operations (<module>.py)
    ├─ templates/ presets/ tests/ README.md

Pipelines run arbitrary code, so a user package must be **trusted** before Exchange imports its
operations or runs it: trusting records a fingerprint of its manifest and code, and any change
to them needs trusting again. Untrusted packages are listed (from their manifest alone) but
never imported.

Tool paths (Blender, texconv, Daz Studio …) are shared by every pipeline that needs the tool:
``tools.json`` in the data folder maps a tool id to the executable.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import re
import shutil
import sys
import types
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

from exchange.errors import DefinitionError, ExchangeError
from exchange.paths import data_dir
from exchange.pipelines.core_ops import CORE_OPERATIONS
from exchange.pipelines.manifest import PipelineManifest, load_manifest
from exchange.pipelines.operations import OperationSpec, accepts


class PipelineError(ExchangeError):
    """A pipeline package cannot be used (untrusted, broken, missing prerequisites)."""


def user_pipelines_dir() -> Path:
    return data_dir() / "pipelines"


def builtin_pipelines_dir() -> Path:
    return Path(str(resources.files("exchange.pipelines").joinpath("builtin")))


@dataclass
class PipelinePackage:
    manifest: PipelineManifest
    path: Path
    builtin: bool
    trusted: bool
    fingerprint: str
    _operations: dict[str, OperationSpec] | None = field(default=None, repr=False)

    @property
    def id(self) -> str:
        return self.manifest.id

    @property
    def apps(self) -> list[str]:
        """External apps its steps drive (known once trusted and loaded)."""
        if not self.trusted:
            return []
        return sorted({spec.app for spec in self.operations().values() if spec.app})

    def operations(self) -> dict[str, OperationSpec]:
        """Its own operations by "<module>.<name>" (imports its code: trusted packages only)."""
        if not self.trusted:
            raise PipelineError(f"pipeline {self.id} is not trusted; trust it first (exchange pipelines trust {self.id})")
        if self._operations is None:
            self._operations = _load_operations(self)
        return self._operations

    def operation(self, name: str) -> OperationSpec:
        if name.startswith("core."):
            spec = CORE_OPERATIONS.get(name[len("core."):])
        else:
            spec = self.operations().get(name)
        if spec is None:
            raise PipelineError(f"pipeline {self.id}: no operation {name!r}")
        return spec


@dataclass
class Registry:
    packages: dict[str, PipelinePackage]
    problems: list[str]  # packages that could not be read, with why

    def get(self, pipeline_id: str) -> PipelinePackage:
        package = self.packages.get(pipeline_id)
        if package is None:
            raise PipelineError(f"no pipeline {pipeline_id!r}")
        return package


def fingerprint(path: Path) -> str:
    """A hash of a package's manifest and code (what trusting it vouches for)."""
    digest = hashlib.sha256()
    files = [path / "pipeline.toml", *sorted((path / "operations").rglob("*.py"))] \
        if (path / "operations").is_dir() else [path / "pipeline.toml"]
    for file in files:
        digest.update(file.relative_to(path).as_posix().encode())
        digest.update(file.read_bytes())
    return digest.hexdigest()


def _trust_file() -> Path:
    return user_pipelines_dir() / "trusted.json"


def _trusted() -> dict[str, str]:
    try:
        return json.loads(_trust_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def load_registry(extra_dirs: tuple[Path, ...] = (), *, include_user: bool = True) -> Registry:
    """Every pipeline package Exchange can see. A broken package is reported, not raised.

    ``extra_dirs`` hold packages (one folder each) treated like the user's (e.g. tests)."""
    packages: dict[str, PipelinePackage] = {}
    problems: list[str] = []
    trusted = _trusted()
    sources: list[tuple[Path, bool]] = [(builtin_pipelines_dir(), True)]
    if include_user:
        sources.append((user_pipelines_dir(), False))
    sources += [(Path(d), False) for d in extra_dirs]
    for base, builtin in sources:
        if not base.is_dir():
            continue
        for folder in sorted(p for p in base.iterdir() if (p / "pipeline.toml").is_file()):
            try:
                manifest = load_manifest(folder / "pipeline.toml")
                digest = fingerprint(folder)
            except (DefinitionError, OSError) as exc:
                problems.append(str(exc))
                continue
            if manifest.id in packages and packages[manifest.id].builtin and not builtin:
                problems.append(f"{folder}: id {manifest.id!r} is a built-in pipeline's; rename it")
                continue
            packages[manifest.id] = PipelinePackage(manifest, folder, builtin,
                                                    builtin or trusted.get(manifest.id) == digest, digest)
    return Registry(packages, problems)


def trust(package: PipelinePackage) -> None:
    """Trust a package as it is now (its manifest and code)."""
    trusted = _trusted()
    trusted[package.id] = package.fingerprint
    _trust_file().parent.mkdir(parents=True, exist_ok=True)
    _trust_file().write_text(json.dumps(trusted, indent=2), encoding="utf-8")
    package.trusted = True


def install(source: Path) -> PipelinePackage:
    """Copy a package folder into the user's pipelines folder (untrusted until trusted)."""
    source = Path(source).resolve()
    manifest = load_manifest(source / "pipeline.toml")
    target = user_pipelines_dir() / manifest.id
    if target.resolve() == source:
        raise PipelineError(f"{source} is already installed")
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    return PipelinePackage(manifest, target, False, False, fingerprint(target))


def describe_trust(package: PipelinePackage) -> list[str]:
    """What trusting a package lets it do, from its manifest (nothing is imported)."""
    m = package.manifest
    lines = [f"{m.name} {m.version} by {m.author or 'an unnamed author'} ({package.path})"]
    tools = sorted({p.tool for p in m.prerequisites if p.kind == "tool"})
    lines.append(f"Runs: {', '.join(tools) if tools else 'Python only (no external apps)'}")
    lines.append(f"Writes to: the endpoint you choose in the {m.output_environment} environment, "
                 "and its own work folder")
    custom = sorted({s.operation for s in m.steps if not s.operation.startswith("core.")})
    if custom:
        lines.append(f"Its own code: {', '.join(custom)} (from {package.path / 'operations'})")
    return lines


def _load_operations(package: PipelinePackage) -> dict[str, OperationSpec]:
    """Import a trusted package's operations/<module>.py files as one Python package of its own."""
    folder = package.path / "operations"
    found: dict[str, OperationSpec] = {}
    if not folder.is_dir():
        return found
    name = f"exchange_pipeline_{package.id}"
    holder = types.ModuleType(name)
    holder.__path__ = [str(folder)]  # so its modules can import each other
    sys.modules[name] = holder
    for file in sorted(folder.glob("*.py")):
        if file.stem.startswith("_"):
            continue
        try:
            module = importlib.import_module(f"{name}.{file.stem}")
        except Exception as exc:  # their code: report it as theirs
            raise PipelineError(f"pipeline {package.id}: {file.name} failed to load: {exc}") from exc
        for value in vars(module).values():
            spec = getattr(value, "__exchange_operation__", None)
            if isinstance(spec, OperationSpec):
                found[f"{file.stem}.{spec.name}"] = spec
    return found


# Tools and prerequisites --------------------------------------------------------------------


def tools_file() -> Path:
    return data_dir() / "tools.json"


def tool_paths() -> dict[str, str]:
    try:
        return json.loads(tools_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def set_tool(tool: str, path: str | None) -> None:
    tools = tool_paths()
    if path:
        tools[tool] = str(Path(path))
    else:
        tools.pop(tool, None)
    tools_file().parent.mkdir(parents=True, exist_ok=True)
    tools_file().write_text(json.dumps(tools, indent=2), encoding="utf-8")


@dataclass(frozen=True)
class PrerequisiteStatus:
    id: str
    label: str
    ok: bool
    detail: str  # the path found, or how to fix it


def _expand(path: str) -> list[str]:
    """A path, or a glob's matches newest version first ("Blender */blender.exe" finds them all)."""
    if not any(c in path for c in "*?["):
        return [path]
    anchor = Path(path).anchor or "."
    matches = [str(p) for p in Path(anchor).glob(str(Path(path).relative_to(anchor)))]
    natural = lambda s: [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]  # noqa: E731
    return sorted(matches, key=natural, reverse=True)


def resolve_tool(package: PipelinePackage, tool: str, tools: dict[str, str] | None = None) -> str | None:
    """Where a package's tool is: the user's setting first, then the paths its manifest suggests."""
    tools = tool_paths() if tools is None else tools
    candidates = [tools[tool]] if tool in tools else []
    for p in package.manifest.prerequisites:
        if p.kind == "tool" and p.tool == tool:
            candidates += [c for path in p.paths for c in _expand(path)]
    return next((c for c in candidates if Path(c).is_file()), None)


def check_prerequisites(package: PipelinePackage, tools: dict[str, str] | None = None) -> list[PrerequisiteStatus]:
    """Each prerequisite, green or red with a fix hint. Cheap: paths only, nothing is run."""
    tools = tool_paths() if tools is None else tools
    out = []
    for p in package.manifest.prerequisites:
        if p.kind == "tool":
            found = resolve_tool(package, p.tool, tools)
            out.append(PrerequisiteStatus(p.id, p.label, found is not None, found or (
                f"not found; set it with: exchange tools set {p.tool} PATH" + (f" ({p.hint})" if p.hint else ""))))
        else:
            missing = [f for f in p.paths if not (package.path / f).exists()]
            out.append(PrerequisiteStatus(p.id, p.label, not missing,
                                          "present" if not missing else f"missing {', '.join(missing)}"
                                          + (f" ({p.hint})" if p.hint else "")))
    return out


def ready(package: PipelinePackage, tools: dict[str, str] | None = None) -> bool:
    """Trusted, with a valid chain and every prerequisite green: offered for requisitions."""
    return package.trusted and not validate(package) and all(s.ok for s in check_prerequisites(package, tools))


def validate(package: PipelinePackage) -> list[str]:
    """Problems with a trusted package's chain: unknown operations, mismatched artifact types."""
    if not package.trusted:
        return ["not trusted"]
    problems = []
    produced = {"source": package.manifest.input_artifact}
    for step in package.manifest.steps:
        try:
            spec = package.operation(step.operation)
        except PipelineError as exc:
            problems.append(str(exc))
            produced[step.id] = "Files"
            continue
        if len(step.inputs) != len(spec.inputs):
            problems.append(f"step {step.id}: {step.operation} takes {len(spec.inputs)} input(s), "
                            f"given {len(step.inputs)}")
        for wanted, name in zip(spec.inputs, step.inputs):
            if not accepts(wanted, produced[name]):
                problems.append(f"step {step.id}: {step.operation} wants {wanted}, but {name} gives {produced[name]}")
        if spec.app and not any(p.kind == "tool" and p.tool == spec.app for p in package.manifest.prerequisites):
            problems.append(f"step {step.id}: {step.operation} runs in {spec.app}; declare it as a "
                            f"[[prerequisite]] with kind = \"tool\" and tool = \"{spec.app}\"")
        produced[step.id] = spec.output
    return problems
