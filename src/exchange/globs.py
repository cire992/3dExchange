"""Case-insensitive globs over "/"-separated relative paths.

``*`` matches within one path segment, ``?`` one character, and ``**/`` zero or more whole segments.
"""

from __future__ import annotations

import functools
import re


@functools.lru_cache(maxsize=None)
def compile_glob(pattern: str) -> re.Pattern[str]:
    pat = pattern.replace("\\", "/")
    out: list[str] = []
    i = 0
    while i < len(pat):
        if pat.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pat.startswith("**", i):
            out.append(".*")
            i += 2
        elif pat[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pat[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pat[i]))
            i += 1
    return re.compile("".join(out) + r"\Z", re.IGNORECASE | re.DOTALL)


def glob_match(pattern: str, rel: str) -> bool:
    return compile_glob(pattern).match(rel) is not None


def any_match(patterns: tuple[str, ...] | list[str], rel: str) -> bool:
    return any(glob_match(p, rel) for p in patterns)
