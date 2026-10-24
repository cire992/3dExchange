"""Finding, creating and choosing project homes.

A folder is a project home when it holds ``exchange.project.toml``. Commands pick their project
from ``--project`` (a path, or a name under the projects root), else the project home holding the
current folder, else the default named in ``<data>/projects.toml``::

    root = "E:/Projects/Exchange"
    default = "NJO"
    git_name = "Luke"                  # the identity project homes commit with, when git has
    git_email = "luke@example.com"     # none of its own (this machine sets it per repository)
"""

from __future__ import annotations

import datetime as dt
import json
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from exchange.errors import ExchangeError
from exchange.paths import data_dir

MARKER = "exchange.project.toml"
FORMAT = 1
KINDS = ("unreal", "bethesda")


class ProjectError(ExchangeError):
    """A project home cannot be found, read or created."""


@dataclass
class ProjectHome:
    path: Path
    name: str
    kind: str
    created: str = ""
    targets: list[str] = field(default_factory=list)
    format: int = FORMAT

    @property
    def records_dir(self) -> Path:
        return self.path / "records"

    @property
    def claims_dir(self) -> Path:
        return self.path / "claims"

    @property
    def schemas_dir(self) -> Path:
        return self.path / "schemas"

    @property
    def identity_path(self) -> Path:
        return self.path / "IDENTITY.md"

    @property
    def goals_path(self) -> Path:
        return self.path / "goals.md"

    @property
    def coverage_path(self) -> Path:
        return self.path / "coverage-rules.yaml"

    @property
    def cache_dir(self) -> Path:
        return self.path / ".exchange"


def find_home(start: Path) -> Path | None:
    """The project home holding ``start`` (a file or folder), or None."""
    start = start.resolve()
    for folder in (start, *start.parents):
        if (folder / MARKER).is_file():
            return folder
    return None


def load_home(path: Path) -> ProjectHome:
    marker = path / MARKER
    try:
        raw = tomllib.loads(marker.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ProjectError(f"{path} is not a project home (it has no {MARKER})") from None
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ProjectError(f"{marker}: {exc}") from exc
    targets = raw.get("targets") or []
    return ProjectHome(path=path.resolve(), name=str(raw.get("name") or path.name),
                       kind=str(raw.get("kind") or "unreal"), created=str(raw.get("created") or ""),
                       targets=[str(t) for t in targets] if isinstance(targets, list) else [],
                       format=int(raw.get("format") or FORMAT))


def manifest_problems(path: Path) -> list[str]:
    """What is wrong with a home's ``exchange.project.toml`` (for validation)."""
    try:
        raw = tomllib.loads((path / MARKER).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        return [str(exc)]
    problems = []
    if not isinstance(raw.get("name"), str) or not raw["name"].strip():
        problems.append("'name' is missing")
    if raw.get("kind") not in KINDS:
        problems.append(f"'kind' must be one of {', '.join(KINDS)}")
    if "targets" in raw and not (isinstance(raw["targets"], list) and all(isinstance(t, str) for t in raw["targets"])):
        problems.append("'targets' must be a list of paths")
    if raw.get("format", FORMAT) != FORMAT:
        problems.append(f"format {raw.get('format')} is not one this Exchange reads ({FORMAT})")
    unknown = set(raw) - {"name", "kind", "targets", "created", "format"}
    if unknown:
        problems.append(f"unknown keys: {', '.join(sorted(unknown))}")
    return problems


# Creating a project home ------------------------------------------------------------------------

IDENTITY_TEMPLATE = """# {name}: Identity

Version 1, {today}. This document changes only through amendments, recorded in the log at the bottom.

## Premise

What the project is, in a paragraph.

## Pillars

1. **A pillar.** What it means for the work.

## Feel

How it should look, sound and play.

## Boundaries

What the project is not.

## Amendment log

- **{today} (v1):** Created.
"""

GOALS_TEMPLATE = """---
goals: []
# - {{ id: G1, title: A first milestone, status: active, done_when: "What is true when it is done" }}
---
Goals are finite milestones, each done or not. Claims name them by ID (`goal: G1`).
"""

COVERAGE_TEMPLATE = """# Per-type expectations, one rule each. Each broken rule will propose a claim.
version: 1
rules: []
# - id: district-has-vendor
#   for: DIST
#   says: Every District has a vendor.
"""


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)  # a TOML basic string


def init_home(path: Path, *, name: str | None = None, kind: str = "unreal", git: bool = True) -> tuple[ProjectHome, list[str]]:
    """Create a project home in ``path`` (new or empty) and, with ``git``, its repository and first
    commit. Returns the home and any warnings (a commit git refused, for instance)."""
    from exchange.projects import git as project_git

    if kind not in KINDS:
        raise ProjectError(f"kind must be one of {', '.join(KINDS)}")
    path = path.resolve()
    if (path / MARKER).exists():
        raise ProjectError(f"{path} is already a project home")
    if path.exists():
        if not path.is_dir():
            raise ProjectError(f"{path} is not a folder")
        if any(p.name != ".git" for p in path.iterdir()):
            raise ProjectError(f"{path} is not empty; a project home starts in a new or empty folder")
    inside = find_home(path.parent) if path.parent != path else None
    if inside is not None:
        raise ProjectError(f"{path} is inside the project home {inside}")
    name = (name or path.name).strip()
    today = dt.date.today().isoformat()
    for folder in ("records", "claims", "schemas"):
        (path / folder).mkdir(parents=True, exist_ok=True)
        (path / folder / ".gitkeep").write_text("", encoding="utf-8")
    (path / MARKER).write_text(
        f"name = {_toml_string(name)}\nkind = {_toml_string(kind)}\ntargets = []\n"
        f"created = {_toml_string(today)}\nformat = {FORMAT}\n", encoding="utf-8", newline="\n")
    (path / "IDENTITY.md").write_text(IDENTITY_TEMPLATE.format(name=name, today=today), encoding="utf-8", newline="\n")
    (path / "goals.md").write_text(GOALS_TEMPLATE, encoding="utf-8", newline="\n")
    (path / "coverage-rules.yaml").write_text(COVERAGE_TEMPLATE, encoding="utf-8", newline="\n")
    (path / ".gitignore").write_text(".exchange/\n", encoding="utf-8", newline="\n")
    warnings: list[str] = []
    if git:
        try:
            project_git.init(path)
            project_git.commit_all(path, f"Project home created by Exchange: {name}")
        except project_git.GitError as exc:
            warnings.append(str(exc))
    return load_home(path), warnings


# Choosing a project ------------------------------------------------------------------------------


CONFIG_KEYS = ("root", "default", "git_name", "git_email")


def config_path() -> Path:
    return data_dir() / "projects.toml"


def read_config() -> dict[str, str]:
    try:
        raw = tomllib.loads(config_path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ProjectError(f"{config_path()}: {exc}") from exc
    return {k: str(v) for k, v in raw.items() if k in CONFIG_KEYS and v}



def write_config(*, root: str | None = None, default: str | None = None, git_name: str | None = None,
                 git_email: str | None = None) -> dict[str, str]:
    """Set the projects root, the default project or the git identity; an empty string clears one."""
    config = read_config()
    for key, value in (("root", root), ("default", default), ("git_name", git_name), ("git_email", git_email)):
        if value is None:
            continue
        if value:
            config[key] = value
        else:
            config.pop(key, None)
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f"{k} = {_toml_string(v)}\n" for k, v in sorted(config.items())),
                    encoding="utf-8", newline="\n")
    return config


def _named(value: str, cwd: Path, config: dict[str, str]) -> Path:
    candidate = Path(value)
    if candidate.is_absolute():
        return candidate
    if "root" in config and (Path(config["root"]) / value / MARKER).is_file():
        return Path(config["root"]) / value
    return cwd / value


def resolve_project(value: str | None = None, cwd: Path | None = None) -> ProjectHome:
    cwd = cwd or Path.cwd()
    config = read_config()
    if value:
        path = _named(value, cwd, config)
        if not (path / MARKER).is_file():
            where = f" or under the projects root {config['root']}" if "root" in config else ""
            raise ProjectError(f"no project home at {path}{where}")
        return load_home(path)
    here = find_home(cwd)
    if here is not None:
        return load_home(here)
    if "default" in config:
        path = _named(config["default"], cwd, config)
        if (path / MARKER).is_file():
            return load_home(path)
        raise ProjectError(f"the default project {config['default']} is not a project home ({path})")
    raise ProjectError("no project: pass --project, run inside a project home, or set a default with "
                       "'exchange project config --default NAME'")
