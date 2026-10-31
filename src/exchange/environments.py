"""Adding environments the user has reviewed: register roots with a chosen type and settings,
and remember folders the user does not want indexed.

Registering writes only to the library; nothing in the folder is read until it is scanned, and
a registered root keeps its type when it is scanned (the user's choice wins over detection).
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from exchange.db import repository as repo
from exchange.definitions.schema import DefinitionSet
from exchange.errors import ScanError
from exchange.paths import fold

EXCLUDED_ROOTS = "excluded_roots"
VISIBILITIES = ("personal", "publishable")


def register_root(
    conn: sqlite3.Connection,
    definitions: DefinitionSet,
    path: Path,
    type_id: str,
    *,
    name: str | None = None,
    config: Mapping[str, Any] | None = None,
    confidence: float = 0.0,
    signals: list[str] | None = None,
    environment_id: int | None = None,
) -> int:
    """Register ``path`` as a root of an environment of ``type_id``; returns the environment id.

    A root already known keeps its environment. The user's type replaces the place's only for its
    first root or a ``multi_root`` place; another root of a single-root place can't retype it (a
    ``ScanError`` names the place, and nothing is written). The place's own type, and anything else
    registered as before, behave as they always did.
    For multi-root types (Daz Studio) a new root joins the existing environment of that type.
    With ``environment_id``, a new root joins that environment whatever its type; without it
    nothing differs, for every caller.
    ``config`` is merged into the environment's user settings.
    """
    definition = definitions.environments.get(type_id)
    if definition is None:
        raise ScanError(f"unknown environment type {type_id!r}")
    path = Path(path).resolve()
    if not path.is_dir():
        raise ScanError(f"not a folder: {path}")
    if config and config.get("visibility") not in (None, *VISIBILITIES):
        raise ScanError(f"visibility must be one of {', '.join(VISIBILITIES)}")
    key = fold(str(path))
    known = repo.find_root(conn, key)
    if known is not None:
        env_id = known["environment_id"]
        if known["type_id"] != type_id:
            _check_retype(conn, definitions, known)
            conn.execute("UPDATE environment SET type_id = ? WHERE id = ?", (type_id, env_id))
    else:
        if environment_id is not None:
            env_id = environment_id
        else:
            existing = conn.execute("SELECT id FROM environment WHERE type_id = ? ORDER BY id LIMIT 1",
                                    (type_id,)).fetchone() if definition.multi_root else None
            if existing is not None:
                env_id = existing[0]
            else:
                from exchange.scanner.scan import environment_name

                env_id = repo.create_environment(conn, type_id=type_id, name=environment_name(definition, path))
        repo.upsert_root(conn, env_id, path=str(path), root_key=key, variant=None,
                         confidence=confidence, signals=signals or ["added by the user"])
    if name:
        conn.execute("UPDATE environment SET name = ? WHERE id = ?", (name, env_id))
    if config:
        merged = {**repo.user_config(conn, env_id), **{k: v for k, v in config.items() if v is not None}}
        repo.set_user_config(conn, env_id, merged)
    set_excluded(conn, path, False)
    return env_id


def _is_multi_root(definitions: DefinitionSet, type_id: str) -> bool:
    definition = definitions.environments.get(type_id)
    return bool(definition and definition.multi_root)


def _check_retype(conn: sqlite3.Connection, definitions: DefinitionSet, known: sqlite3.Row) -> None:
    """Refuse retyping a place from a root that joined it, unless the place is ``multi_root``."""
    env_id = known["environment_id"]
    if known["id"] == repo.list_roots(conn, env_id)[0]["id"] or _is_multi_root(definitions, known["type_id"]):
        return
    raise ScanError(
        f"{known['path']} is a folder of {repo.get_environment(conn, env_id)['name']}, which is a "
        f"{known['type_id']} place: only its first folder can change the place's type")


def can_forget_root(conn: sqlite3.Connection, definitions: DefinitionSet, root: sqlite3.Row) -> bool:
    """Whether ``root`` (a row from ``list_roots`` or ``find_root``) can be forgotten on its own: its
    place has other roots, and it is not the first root of a single-root place (as ``place_root`` and
    ``scan`` read "first")."""
    roots = repo.list_roots(conn, root["environment_id"])
    return len(roots) > 1 and (roots[0]["id"] != root["id"] or _is_multi_root(definitions, root["type_id"]))


def excluded_roots(conn: sqlite3.Connection) -> list[str]:
    row = conn.execute("SELECT value FROM library_setting WHERE key = ?", (EXCLUDED_ROOTS,)).fetchone()
    return json.loads(row[0]) if row else []


def set_excluded(conn: sqlite3.Connection, path: Path, excluded: bool = True) -> None:
    """Remember (or forget) that scans must skip this folder."""
    path = str(Path(path).resolve())
    current = [p for p in excluded_roots(conn) if fold(p) != fold(path)]
    if excluded:
        current.append(path)
    conn.execute(
        "INSERT INTO library_setting (key, value) VALUES (?, ?)"
        " ON CONFLICT (key) DO UPDATE SET value = excluded.value", (EXCLUDED_ROOTS, json.dumps(sorted(current))))
