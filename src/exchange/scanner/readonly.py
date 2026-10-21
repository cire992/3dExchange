"""The only way the scanner reads file contents. Scanning is strictly read-only.

Everything here opens files in binary read mode; nothing in the scanner package may open a file
for writing, create a folder or change attributes inside a scanned folder.
"""

from __future__ import annotations

import configparser
from pathlib import Path

from exchange.paths import os_path

MAX_READ_BYTES = 8 * 1024 * 1024  # manifests and ini files are small; refuse to slurp anything big


def read_bytes(path: Path, limit: int = MAX_READ_BYTES) -> bytes | None:
    """Contents of ``path`` (truncated at ``limit``), or None if it cannot be read."""
    try:
        with open(os_path(path), "rb") as fh:
            return fh.read(limit)
    except OSError:
        return None


def read_text(path: Path, limit: int = MAX_READ_BYTES) -> str | None:
    data = read_bytes(path, limit)
    return None if data is None else data.decode("utf-8-sig", errors="replace")


def read_ini(path: Path) -> configparser.ConfigParser | None:
    """Parse an ini file the way MO2 writes them; None if missing or unparseable.

    Keys are case-insensitive. Quoted values keep their quotes; use ``ini_value`` to read.
    """
    text = read_text(path)
    if text is None:
        return None
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    try:
        parser.read_string(text, source=str(path))
    except configparser.Error:
        return None
    return parser


def ini_value(parser: configparser.ConfigParser | None, section: str, key: str) -> str | None:
    if parser is None:
        return None
    for name in parser.sections():
        if name.casefold() == section.casefold():
            value = parser[name].get(key)
            if value is None:
                return None
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] == '"':
                value = value[1:-1]
            # Qt settings wrap some values: selected_profile=@ByteArray(Default)
            if value.startswith("@ByteArray(") and value.endswith(")"):
                value = value[len("@ByteArray(") : -1]
            return value
    return None
