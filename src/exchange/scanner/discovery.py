"""Scan phase 1, discovery: walk a folder and record each file's path, size and modification time.

Read-only: only directory listings and ``stat`` results are used. Symbolic links and junctions
are recorded but never followed, so a scan cannot wander outside the folder it was given.
"""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass, field
from pathlib import Path

from exchange.paths import fold, os_path

# Operating-system clutter that is never an asset.
IGNORED_FILE_NAMES = frozenset({"thumbs.db", "desktop.ini", ".ds_store"})
IGNORED_DIR_NAMES = frozenset({".git", "$recycle.bin", "system volume information"})

_LINK_TAGS = frozenset({stat.IO_REPARSE_TAG_SYMLINK, stat.IO_REPARSE_TAG_MOUNT_POINT})


@dataclass(frozen=True)
class DiscoveredFile:
    rel: str  # "/"-separated, relative to the discovery root, original case
    size: int
    mtime_ns: int


@dataclass
class Discovery:
    root: Path
    files: list[DiscoveredFile] = field(default_factory=list)
    dirs: list[str] = field(default_factory=list)  # every walked directory, relative
    links: list[str] = field(default_factory=list)  # symlinks and junctions, not followed
    errors: list[str] = field(default_factory=list)


def _is_link(entry: os.DirEntry[str]) -> bool:
    if entry.is_symlink():
        return True
    # Junctions are not symlinks to Python 3.11; OneDrive placeholders are reparse points too,
    # so only the link tags count.
    tag = getattr(entry.stat(follow_symlinks=False), "st_reparse_tag", 0)
    return tag in _LINK_TAGS


def discover(root: Path) -> Discovery:
    root = root.resolve()
    result = Discovery(root=root)
    stack: list[tuple[str, str]] = [("", os_path(root))]
    while stack:
        rel_dir, dir_path = stack.pop()
        try:
            listing = os.scandir(dir_path)
        except OSError as exc:
            result.errors.append(f"{rel_dir or '.'}: {exc.strerror or exc}")
            continue
        with listing:
            for entry in listing:
                rel = f"{rel_dir}/{entry.name}" if rel_dir else entry.name
                try:
                    if _is_link(entry):
                        result.links.append(rel)
                    elif entry.is_dir(follow_symlinks=False):
                        if fold(entry.name) not in IGNORED_DIR_NAMES:
                            result.dirs.append(rel)
                            stack.append((rel, entry.path))
                    elif fold(entry.name) not in IGNORED_FILE_NAMES:
                        st = entry.stat(follow_symlinks=False)
                        result.files.append(DiscoveredFile(rel, st.st_size, st.st_mtime_ns))
                except OSError as exc:
                    result.errors.append(f"{rel}: {exc.strerror or exc}")
    result.files.sort(key=lambda f: f.rel)
    result.dirs.sort()
    result.links.sort()
    return result
