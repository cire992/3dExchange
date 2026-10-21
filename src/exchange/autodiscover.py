"""First-run auto-discovery: find environments from files and settings that already know where
things are installed. Read-only; nothing is added until the user picks from the list.

Sources:

* Steam: ``libraryfolders.vdf`` and each library's ``appmanifest_*.acf``.
* Epic Games launcher: install manifests (``*.item``).
* Unreal Engine: recently opened projects from the editor's settings.
* Daz Studio: content directories from its registry settings, plus the default public library.
* Mod Organizer 2: instances in ``%LOCALAPPDATA%\\ModOrganizer``.

Each folder found is scored against the environment definitions directly on disk (no full walk),
so the result says which type it would be added as, or that no definition knows it yet.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from exchange.definitions.schema import DefinitionSet, EnvironmentDefinition, Signature
from exchange.globs import glob_match
from exchange.paths import fold, to_path
from exchange.scanner.readonly import ini_value, read_ini, read_text

Registry = Callable[[str], dict[str, str]]  # key path under HKEY_CURRENT_USER -> values


@dataclass
class Found:
    path: str
    name: str
    via: str
    type_id: str | None = None  # the environment definition that matched, if any
    confidence: float = 0.0
    signals: list[str] = field(default_factory=list)
    registered: bool = False


@dataclass
class Places:
    """Where to look. Defaults come from this machine; tests pass their own."""

    local_appdata: Path | None = None
    program_data: Path | None = None
    public: Path | None = None
    registry: Registry | None = None

    @classmethod
    def from_system(cls) -> Places:
        env = os.environ
        return cls(
            local_appdata=Path(env["LOCALAPPDATA"]) if env.get("LOCALAPPDATA") else None,
            program_data=Path(env["PROGRAMDATA"]) if env.get("PROGRAMDATA") else None,
            public=Path(env["PUBLIC"]) if env.get("PUBLIC") else None,
            registry=_windows_registry if os.name == "nt" else None,
        )


def discover_sources(definitions: DefinitionSet, places: Places | None = None,
                     registered_roots: Iterable[str] = ()) -> list[Found]:
    places = places or Places.from_system()
    found: dict[str, Found] = {}
    for item in [*_steam(places), *_epic(places), *_unreal_projects(places), *_daz(places), *_mo2(places)]:
        path = Path(item.path)
        if not path.is_dir() or fold(str(path)) in found:
            continue
        match = score_folder(definitions, path)
        if match is not None:
            definition, score, signals = match
            item.type_id, item.confidence, item.signals = definition.id, score, signals
        found[fold(str(path))] = item
    registered = {fold(r) for r in registered_roots}
    for key, item in found.items():
        item.registered = key in registered
    return sorted(found.values(), key=lambda f: (f.type_id is None, f.via, fold(f.name)))


# Scoring a folder on disk -------------------------------------------------------------------


def score_folder(definitions: DefinitionSet,
                 path: Path) -> tuple[EnvironmentDefinition, float, list[str]] | None:
    """The best-matching definition for ``path`` as an environment root, checking only the
    signature paths themselves (deep globs are skipped)."""
    best = None
    for definition in definitions.environments.values():
        if definition.fallback:
            continue
        total, signals = 0.0, []
        for sig in definition.signatures:
            if _matches_on_disk(sig, path):
                total += sig.weight
                signals.append(sig.describe())
        score = min(round(total, 6), 1.0)
        if score >= definition.min_confidence and (best is None or (score, len(signals)) > (best[1], len(best[2]))):
            best = (definition, score, signals)
    return best


def _matches_on_disk(sig: Signature, root: Path) -> bool:
    try:
        if sig.kind == "glob":
            if "/" in sig.glob:
                return False
            return any(e.is_file() and glob_match(sig.glob, e.name) for e in os.scandir(root))
        target = to_path(root, sig.path)
        if sig.kind == "dir":
            return target.is_dir()
        if sig.kind == "file":
            return target.is_file()
        value = ini_value(read_ini(target), sig.section, sig.key)
        return value is not None and fold(value) == fold(sig.equals)
    except OSError:
        return False


# Sources --------------------------------------------------------------------------------------


def parse_vdf(text: str) -> dict:
    """Valve KeyValues text (libraryfolders.vdf, appmanifest_*.acf) as nested dicts."""
    tokens = re.findall(r'"((?:[^"\\]|\\.)*)"|([{}])', text)
    root: dict = {}
    stack = [root]
    key = None
    for quoted, brace in tokens:
        if brace == "{":
            child: dict = {}
            stack[-1][key if key is not None else ""] = child
            stack.append(child)
            key = None
        elif brace == "}":
            if len(stack) > 1:
                stack.pop()
            key = None
        elif key is None:
            key = quoted.replace("\\\\", "\\")
        else:
            stack[-1][key] = quoted.replace("\\\\", "\\")
            key = None
    return root


def _steam(places: Places) -> list[Found]:
    steam = (places.registry("Software\\Valve\\Steam") if places.registry else {}).get("SteamPath")
    if not steam:
        return []
    text = read_text(Path(steam) / "steamapps" / "libraryfolders.vdf")
    libraries = [Path(steam)]
    if text:
        folders = parse_vdf(text).get("libraryfolders", {})
        libraries += [Path(v["path"]) for v in folders.values() if isinstance(v, dict) and v.get("path")]
    out = []
    for library in dict.fromkeys(libraries):
        apps = library / "steamapps"
        if not apps.is_dir():
            continue
        for manifest in sorted(apps.glob("appmanifest_*.acf")):
            state = parse_vdf(read_text(manifest) or "").get("AppState", {})
            if state.get("installdir"):
                out.append(Found(str(apps / "common" / state["installdir"]),
                                 state.get("name", state["installdir"]), "Steam library"))
    return out


def _epic(places: Places) -> list[Found]:
    if places.program_data is None:
        return []
    folder = places.program_data / "Epic" / "EpicGamesLauncher" / "Data" / "Manifests"
    out = []
    for item in sorted(folder.glob("*.item")) if folder.is_dir() else []:
        try:
            data = json.loads(read_text(item) or "")
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and data.get("InstallLocation"):
            out.append(Found(data["InstallLocation"], data.get("DisplayName") or item.stem, "Epic Games launcher"))
    return out


_UPROJECT = re.compile(r'([A-Za-z]:[\\/][^"\r\n=,()]*?\.uproject)', re.IGNORECASE)


def _unreal_projects(places: Places) -> list[Found]:
    if places.local_appdata is None:
        return []
    base = places.local_appdata / "UnrealEngine"
    out = []
    for ini in sorted(base.glob("*/Saved/Config/*/EditorSettings.ini")) if base.is_dir() else []:
        for match in _UPROJECT.findall(read_text(ini) or ""):
            project = Path(match.replace("/", "\\") if os.name == "nt" else match)
            out.append(Found(str(project.parent), project.stem, "Unreal Engine recent projects"))
    return out


def _daz(places: Places) -> list[Found]:
    out = []
    values = places.registry("Software\\DAZ\\Studio4") if places.registry else {}
    for name, value in sorted(values.items()):
        if "content" in name.lower() and isinstance(value, str) and value:
            out.append(Found(str(Path(value)), Path(value).name, "Daz Studio settings"))
    if places.public is not None:
        default = places.public / "Documents" / "My DAZ 3D Library"
        out.append(Found(str(default), default.name, "Daz Studio default library"))
    return out


def _mo2(places: Places) -> list[Found]:
    if places.local_appdata is None:
        return []
    base = places.local_appdata / "ModOrganizer"
    out = []
    for ini in sorted(base.glob("*/ModOrganizer.ini")) if base.is_dir() else []:
        game = ini_value(read_ini(ini), "General", "gameName")
        name = f"{ini.parent.name}" + (f" ({game})" if game else "")
        out.append(Found(str(ini.parent), name, "Mod Organizer 2 instances"))
    return out


def _windows_registry(key_path: str) -> dict[str, str]:
    import winreg

    values: dict[str, str] = {}
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            i = 0
            while True:
                try:
                    name, value, _ = winreg.EnumValue(key, i)
                except OSError:
                    break
                if isinstance(value, str):
                    values[name] = value
                i += 1
    except OSError:
        pass
    return values
