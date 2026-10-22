"""Endpoints: where a requisition writes in the target environment.

Defaults by organizational layer (spec: Environments › Endpoints), always a new or
Exchange-managed container, never an existing one of the user's:

* **Daz Studio:** an "Exchange Conversions" content directory beside the first library. It
  becomes a root of the Daz environment once something is written there. Exchange never edits
  Daz Studio's own settings: adding the folder in Daz's Content Directory Manager is the user's
  one-time step.
* **MO2:** a new mod per requisition, ``mods/Exchange - <name>``.
* **Unreal:** ``Content/Exchange`` in the project.
* **Loose files:** an "Exchange Conversions" folder in the root.

The user can point an environment elsewhere (``endpoint`` in its settings) or pass a folder for
one requisition. An endpoint's **visibility** (personal or publishable) comes from the
environment's settings and drives the license check.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path

from exchange.db import repository as repo
from exchange.definitions.schema import DefinitionSet
from exchange.errors import ExchangeError
from exchange.paths import fold, is_within

CONVERSIONS = "Exchange Conversions"


class EndpointError(ExchangeError):
    pass


@dataclass(frozen=True)
class Endpoint:
    environment_id: int
    folder: str  # the container folder output goes into (absolute)
    root: str  # the environment root it is in (absolute); may not be registered yet
    visibility: str  # personal | publishable
    label: str

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @staticmethod
    def from_json(text: str) -> Endpoint:
        return Endpoint(**json.loads(text))


def _safe_name(name: str) -> str:
    cleaned = "".join("_" if c in '<>:"/\\|?*' or ord(c) < 32 else c for c in name).strip(" .")
    return cleaned or "Requisition"


def default_endpoint(conn: sqlite3.Connection, definitions: DefinitionSet, environment_id: int,
                     name: str, folder: str | Path | None = None) -> Endpoint:
    """The endpoint a requisition named ``name`` writes to in an environment (or ``folder``)."""
    env = repo.get_environment(conn, environment_id)
    if env is None:
        raise EndpointError(f"no environment {environment_id}")
    roots = [r for r in repo.list_roots(conn, environment_id) if r["status"] == "online"]
    if not roots:
        raise EndpointError(f"{env['name']} has no online folder to write to")
    config = json.loads(env["user_config"] or "{}")
    visibility = config.get("visibility", "personal")
    definition = definitions.environments.get(env["type_id"])
    handler = definition.handler if definition else "folder"
    first = Path(roots[0]["path"])

    chosen = folder or config.get("endpoint")
    if chosen:
        target = Path(chosen).resolve()
        root = next((Path(r["path"]) for r in roots if is_within(target, Path(r["path"]))), target)
        return Endpoint(environment_id, str(target), str(root), visibility, f"{target}")

    if handler == "daz":
        target = first.parent / CONVERSIONS
        known = next((Path(r["path"]) for r in roots if fold(str(Path(r["path"]))) == fold(str(target))), None)
        return Endpoint(environment_id, str(target), str(known or target), visibility,
                        f"{CONVERSIONS} content directory")
    if handler == "mo2":
        layer = json.loads(env["layer_config"] or "{}")
        mods = first.joinpath(*str(layer.get("mods_dir", "mods")).split("/"))
        target = mods / f"Exchange - {_safe_name(name)}"
        return Endpoint(environment_id, str(target), str(first), visibility, f"new mod “{target.name}”")
    if handler == "unreal":
        target = first / "Content" / "Exchange"
        return Endpoint(environment_id, str(target), str(first), visibility, "Content/Exchange")
    target = first / CONVERSIONS
    return Endpoint(environment_id, str(target), str(first), visibility, f"{CONVERSIONS} folder")
