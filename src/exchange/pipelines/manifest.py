"""Pipeline manifests (``pipeline.toml``), read as strictly as definitions.

A manifest names the pipeline and says what it takes, what it makes, its parameters, its
prerequisites and its steps::

    [pipeline]
    id = "textures_to_dds"            # lower_snake_case
    name = "Textures to DDS"
    version = "1.0.0"
    author = "You"
    format_version = 1

    [input]
    dossier_types = ["texture"]       # a dossier of (a subtype of) one of these; empty: any
    tags = []                         # all of these tags
    environments = []                 # source environment types; empty: any
    artifact = "Images"               # the type of the source files

    [output]
    environment = "same"              # target environment type, or "same" as the source's
    dossier_type = "texture"          # what the result is (for chains)
    folder = "{name}"                 # where in the endpoint the files go
    entry_status = "requisitioned"    # or "copied" for copy pipelines
    roles = []

    [[parameter]]
    id = "size"
    type = "int"                      # str | int | float | bool | choice | path
    default = 2048

    [[prerequisite]]
    id = "texconv"
    kind = "tool"                     # tool (an executable) | file (in the package)
    tool = "texconv"
    paths = ["C:/Tools/texconv.exe"]
    hint = "Download texconv from …"

    [[step]]
    id = "resize"
    operation = "core.resize_images"  # core.<name> or <module>.<name> from operations/<module>.py
    inputs = ["source"]               # "source" or earlier step ids; default: the previous step
    params = { size = "{size}" }      # "{parameter}" refers to a parameter (keeping its type)
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from exchange.definitions.loader import _identifier, _Table
from exchange.errors import DefinitionError

FORMAT_VERSION = 1
PARAMETER_TYPES = ("str", "int", "float", "bool", "choice", "path")
PREREQUISITE_KINDS = ("tool", "file")
ENTRY_STATUSES = ("requisitioned", "copied")
_PY_TYPES = {"str": str, "int": int, "float": (int, float), "bool": bool, "choice": str, "path": str}
_REFERENCE = re.compile(r"^\{(\w+)\}$")


@dataclass(frozen=True)
class Parameter:
    id: str
    type: str
    default: Any
    label: str = ""
    help: str = ""
    choices: tuple[str, ...] = ()
    min: float | None = None
    max: float | None = None

    def check(self, value: Any) -> Any:
        """``value`` as this parameter's type, or a ValueError saying why not."""
        if self.type == "bool" and isinstance(value, str):
            if value.lower() not in ("true", "false", "yes", "no", "1", "0"):
                raise ValueError(f"{self.id} must be true or false")
            value = value.lower() in ("true", "yes", "1")
        elif self.type in ("int", "float") and isinstance(value, str):
            try:
                value = int(value) if self.type == "int" else float(value)
            except ValueError:
                raise ValueError(f"{self.id} must be a number") from None
        if not isinstance(value, _PY_TYPES[self.type]) or (isinstance(value, bool) and self.type != "bool"):
            raise ValueError(f"{self.id} must be {self.type}, got {value!r}")
        if self.type == "choice" and value not in self.choices:
            raise ValueError(f"{self.id} must be one of {', '.join(self.choices)}")
        if self.min is not None and value < self.min or self.max is not None and value > self.max:
            raise ValueError(f"{self.id} must be between {self.min} and {self.max}")
        return value


@dataclass(frozen=True)
class Prerequisite:
    id: str
    kind: str
    label: str
    hint: str = ""
    tool: str = ""  # for kind "tool": the shared tool id (blender, texconv, daz_studio)
    paths: tuple[str, ...] = ()  # tool: likely install paths; file: paths inside the package


@dataclass(frozen=True)
class Step:
    id: str
    operation: str
    inputs: tuple[str, ...]
    params: dict = field(default_factory=dict)


@dataclass(frozen=True)
class PipelineManifest:
    id: str
    name: str
    version: str
    author: str
    description: str
    source: str
    input_types: tuple[str, ...]
    input_tags: tuple[str, ...]
    input_environments: tuple[str, ...]
    input_artifact: str
    output_environment: str
    output_dossier_type: str
    output_folder: str
    entry_status: str
    roles: tuple[str, ...]
    parameters: tuple[Parameter, ...]
    prerequisites: tuple[Prerequisite, ...]
    steps: tuple[Step, ...]

    def parameter(self, parameter_id: str) -> Parameter | None:
        return next((p for p in self.parameters if p.id == parameter_id), None)

    def defaults(self) -> dict[str, Any]:
        return {p.id: p.default for p in self.parameters}

    def resolve(self, values: dict[str, Any]) -> dict[str, Any]:
        """Parameter values: the defaults, overridden and type-checked (ValueError if wrong)."""
        out = self.defaults()
        for key, value in values.items():
            parameter = self.parameter(key)
            if parameter is None:
                raise ValueError(f"{self.id} has no parameter {key!r}")
            out[key] = parameter.check(value)
        return out


def step_params(step: Step, values: dict[str, Any], dossier: dict[str, Any]) -> dict[str, Any]:
    """A step's parameters with ``{parameter}`` references filled in (whole-string references keep
    their type; others are formatted as text, with the dossier's name and variant available)."""
    names = {**{k: v for k, v in dossier.items() if isinstance(v, (str, int, float))}, **values}
    out = {}
    for key, value in step.params.items():
        if isinstance(value, str):
            match = _REFERENCE.match(value)
            if match and match.group(1) in values:
                value = values[match.group(1)]
            else:
                try:
                    value = value.format_map(names)
                except (KeyError, IndexError, ValueError) as exc:
                    raise ValueError(f"step {step.id}: cannot fill in {value!r} ({exc})") from exc
        out[key] = value
    return out


def load_manifest(path: Path) -> PipelineManifest:
    source = str(path)
    try:
        data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise DefinitionError(source, f"invalid TOML: {exc}") from exc
    except (OSError, UnicodeDecodeError) as exc:
        raise DefinitionError(source, f"cannot read: {exc}") from exc
    return parse_manifest(data, source)


def parse_manifest(data: dict, source: str) -> PipelineManifest:
    top = _Table(data, source, "", ["pipeline", "input", "output", "parameter", "prerequisite", "step"])
    p = top.table("pipeline", ["id", "name", "version", "author", "description", "format_version"])
    version = p.get("format_version", int)
    if version != FORMAT_VERSION:
        raise DefinitionError(source, f"unsupported format_version {version} (expected {FORMAT_VERSION})")
    i = top.table("input", ["dossier_types", "tags", "environments", "artifact"])
    o = top.table("output", ["environment", "dossier_type", "folder", "entry_status", "roles"])

    parameters = []
    for t in top.tables("parameter", ["id", "type", "default", "label", "help", "choices", "min", "max"]):
        kind = t.get("type", str, choices=PARAMETER_TYPES)
        choices = t.strings("choices")
        if kind == "choice" and not choices:
            raise DefinitionError(source, f"{t.where}.choices is required for a choice parameter")
        parameter = Parameter(_identifier(t), kind, t.data.get("default"), t.get("label", str, ""),
                              t.get("help", str, ""), choices, t.get("min", (int, float), None),
                              t.get("max", (int, float), None))
        if "default" not in t.data:
            raise DefinitionError(source, f"missing required key {t.where}.default")
        try:
            parameter.check(parameter.default)
        except ValueError as exc:
            raise DefinitionError(source, f"{t.where}.default: {exc}") from None
        parameters.append(parameter)
    ids = [x.id for x in parameters]
    if len(set(ids)) != len(ids):
        raise DefinitionError(source, "two parameters share an id")

    prerequisites = []
    for t in top.tables("prerequisite", ["id", "kind", "label", "hint", "tool", "paths"]):
        kind = t.get("kind", str, choices=PREREQUISITE_KINDS)
        tool = t.get("tool", str, "")
        if kind == "tool" and not tool:
            raise DefinitionError(source, f"{t.where}.tool is required for a tool prerequisite")
        prerequisites.append(Prerequisite(_identifier(t), kind, t.get("label", str, "") or tool or t.data["id"],
                                          t.get("hint", str, ""), tool, t.strings("paths")))

    steps: list[Step] = []
    for t in top.tables("step", ["id", "operation", "inputs", "params"]):
        step_id = _identifier(t)
        if step_id == "source" or any(s.id == step_id for s in steps):
            raise DefinitionError(source, f"{t.where}.id {step_id!r} is taken")
        inputs = t.strings("inputs") or ((steps[-1].id,) if steps else ("source",))
        for name in inputs:
            if name != "source" and not any(s.id == name for s in steps):
                raise DefinitionError(source, f"{t.where}.inputs: {name!r} is not an earlier step")
        operation = t.get("operation", str)
        if "." not in operation:
            raise DefinitionError(source, f"{t.where}.operation must be core.<name> or <module>.<name>")
        steps.append(Step(step_id, operation, tuple(inputs), dict(t.get("params", dict, {}))))
    if not steps:
        raise DefinitionError(source, "a pipeline needs at least one [[step]]")
    for step in steps:
        for key, value in step.params.items():
            match = _REFERENCE.match(value) if isinstance(value, str) else None
            if match and match.group(1) not in ids and match.group(1) not in ("name", "variant", "type_id"):
                raise DefinitionError(source, f"step {step.id}: params.{key} refers to unknown parameter "
                                              f"{match.group(1)!r}")

    return PipelineManifest(
        id=_identifier(p), name=p.get("name", str), version=p.get("version", str), author=p.get("author", str, ""),
        description=p.get("description", str, ""), source=source,
        input_types=i.strings("dossier_types"), input_tags=i.strings("tags"),
        input_environments=i.strings("environments"), input_artifact=i.get("artifact", str, "Files"),
        output_environment=o.get("environment", str), output_dossier_type=o.get("dossier_type", str, ""),
        output_folder=o.get("folder", str, "{name}"),
        entry_status=o.get("entry_status", str, "requisitioned", choices=ENTRY_STATUSES),
        roles=o.strings("roles"), parameters=tuple(parameters), prerequisites=tuple(prerequisites),
        steps=tuple(steps))
