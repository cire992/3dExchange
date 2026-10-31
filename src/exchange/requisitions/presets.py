"""Presets and last-used options for requisitions.

A **preset** holds options for every process a plan uses, so "G9 Male → Skyrim (HIMBO)" sets up
a whole product's plan in one go, and can be applied to many assets at once (batch). Presets are
files, so they can be shared and shipped:

* the user's, in ``<data>/presets/<name>.json``
* a process package's, in its ``presets/*.json``

::

    {"name": "Small JPEG textures", "description": "...", "environment": "loose_files",
     "options": {"convert_mesh": {"format": "glb"}, "stamp_images": {"size": 256}}}

**Last-used options** are remembered per process (``<data>/last_options.json``) whenever a
requisition is queued from the window, and pre-fill the next plan when no preset is chosen.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from exchange.errors import ExchangeError
from exchange.paths import data_dir
from exchange.processes.registry import Registry

_last_lock = threading.Lock()  # remembering, on the service's threads


class PresetError(ExchangeError):
    pass


@dataclass
class Preset:
    name: str
    options: dict[str, dict[str, Any]]  # process id -> option values
    description: str = ""
    environment: str | None = None  # target environment type it was made for, if any
    source: str = ""  # the file
    shipped: bool = False  # from a process package (read-only)
    processes: list[str] = field(default_factory=list)

    def params(self) -> dict[str, Any]:
        """As plan_requisition's ``params``: ``{"process.option": value}``."""
        return {f"{process}.{key}": value for process, values in self.options.items() for key, value in values.items()}


def presets_dir() -> Path:
    return data_dir() / "presets"


def _file_name(name: str) -> str:
    return re.sub(r"[^\w\- ]+", "_", name).strip() or "preset"


def _read(path: Path, shipped: bool) -> Preset | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        options = {str(k): dict(v) for k, v in data["options"].items()}
        return Preset(str(data.get("name") or path.stem), options, str(data.get("description", "")),
                      data.get("environment"), str(path), shipped, list(options))
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None  # not a preset file; left alone


def load_presets(registry: Registry | None = None) -> dict[str, Preset]:
    """Every preset by name: those shipped in process packages, then the user's (which win)."""
    found: dict[str, Preset] = {}
    for package in (registry.packages.values() if registry else []):
        for path in sorted((package.path / "presets").glob("*.json")) if (package.path / "presets").is_dir() else []:
            preset = _read(path, shipped=True)
            if preset:
                found[preset.name] = preset
    folder = presets_dir()
    for path in sorted(folder.glob("*.json")) if folder.is_dir() else []:
        preset = _read(path, shipped=False)
        if preset:
            found[preset.name] = preset
    return found


def save_preset(name: str, options: dict[str, dict[str, Any]], *, description: str = "",
                environment: str | None = None) -> Preset:
    name = name.strip()
    if not name:
        raise PresetError("a preset needs a name")
    path = presets_dir() / f"{_file_name(name)}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"name": name, "description": description, "environment": environment,
            "options": {k: v for k, v in options.items() if v}}
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return _read(path, shipped=False)


def delete_preset(name: str, registry: Registry | None = None) -> None:
    preset = load_presets(registry).get(name)
    if preset is None:
        raise PresetError(f"no preset {name!r}")
    if preset.shipped:
        raise PresetError(f"{name!r} ships with a process package; it cannot be deleted")
    Path(preset.source).unlink()


def _last_file() -> Path:
    return data_dir() / "last_options.json"


def last_used() -> dict[str, dict[str, Any]]:
    try:
        return json.loads(_last_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def remember(options: dict[str, dict[str, Any]]) -> None:
    """Remember these options as each process's last used. A convenience: it runs after a requisition is
    queued, so a write that fails is dropped, and the file keeps what it had."""
    with _last_lock:
        known = last_used()
        known.update({k: v for k, v in options.items() if v})
        temp = _last_file().with_suffix(f".{os.getpid()}.tmp")
        try:
            text = json.dumps(known, indent=2, ensure_ascii=False).encode("utf-8")
            temp.parent.mkdir(parents=True, exist_ok=True)
            temp.write_bytes(text)
            os.replace(temp, _last_file())
        except (OSError, ValueError):
            with contextlib.suppress(OSError):
                temp.unlink(missing_ok=True)


def last_used_params(processes: list[str]) -> dict[str, Any]:
    """The remembered options of some processes, as plan_requisition's ``params``."""
    known = last_used()
    return {f"{p}.{k}": v for p in processes for k, v in known.get(p, {}).items()}
