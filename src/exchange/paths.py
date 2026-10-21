"""Path helpers shared by the scanner and the library database.

Relative paths inside an environment are stored with "/" separators in their original case.
Matching is case-insensitive everywhere (``fold``), because Windows file systems are.
"""

from __future__ import annotations

import os
from pathlib import Path

APP_DIR_NAME = "Exchange"


def data_dir() -> Path:
    """Where Exchange keeps its database and user definitions."""
    override = os.environ.get("EXCHANGE_DATA_DIR")
    if override:
        return Path(override)
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / APP_DIR_NAME
    return Path.home() / ".exchange"


def default_db_path() -> Path:
    return data_dir() / "library.db"


def user_definitions_dir() -> Path:
    return data_dir() / "definitions"


def fold(text: str) -> str:
    """Case-fold a path or name for comparison."""
    return text.casefold()


def normalize_rel(rel: str) -> str:
    """Normalize a relative path written in a definition or manifest to "a/b/c" form."""
    return "/".join(part for part in rel.replace("\\", "/").split("/") if part and part != ".")


def join_rel(base: str, rel: str) -> str:
    return f"{base}/{rel}" if base and rel else base or rel


def rel_under(rel: str, base: str) -> str | None:
    """``rel`` relative to ``base`` (both "/"-separated), or None if it is not inside it."""
    if not base:
        return rel
    if fold(rel).startswith(fold(base) + "/"):
        return rel[len(base) + 1 :]
    return None


def to_path(root: Path, rel: str) -> Path:
    return root.joinpath(*rel.split("/")) if rel else root


def is_within(child: Path, parent: Path) -> bool:
    """True if ``child`` is ``parent`` or inside it, after resolving both."""
    child, parent = child.resolve(), parent.resolve()
    return child == parent or parent in child.parents


def os_path(path: Path) -> str:
    """String form of an absolute path usable past MAX_PATH (260 characters) on Windows."""
    text = str(path)
    if os.name != "nt" or text.startswith("\\\\?\\"):
        return text
    if text.startswith("\\\\"):
        return "\\\\?\\UNC\\" + text[2:]
    return "\\\\?\\" + text
