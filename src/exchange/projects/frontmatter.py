"""Markdown files with YAML front matter between ``---`` lines.

Parsing uses PyYAML's safe loader (the C one when available), with one addition: a key repeated in
the same mapping is an error instead of silently keeping the last value.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

_Base = getattr(yaml, "CSafeLoader", yaml.SafeLoader)


class _Loader(_Base):  # type: ignore[misc, valid-type]
    pass


def _mapping(loader: _Loader, node: yaml.MappingNode, deep: bool = False) -> dict:
    seen: set = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in seen:
            raise yaml.constructor.ConstructorError(
                None, None, f"the key {key!r} appears twice", key_node.start_mark)
        seen.add(key)
    return loader.construct_mapping(node, deep=deep)


_Loader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


class FrontMatterError(ValueError):
    """The front matter is missing or is not valid YAML."""


@dataclass
class Document:
    meta: dict[str, Any]
    body: str


def load_yaml(text: str, *, first_line: int = 1) -> Any:
    """Parse YAML; ``first_line`` is the file's line number of the text's first line (for errors)."""
    try:
        return yaml.load(text, Loader=_Loader)  # noqa: S506 (a safe loader)
    except yaml.YAMLError as exc:
        raise FrontMatterError(_yaml_message(exc, first_line)) from exc


def parse(text: str) -> Document:
    """Split ``text`` into its front matter (a mapping) and its body."""
    text = text.lstrip("﻿")
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip() != "---":
        raise FrontMatterError("no front matter: the file must start with a '---' line")
    for end in range(1, len(lines)):
        if lines[end].rstrip() == "---":
            break
    else:
        raise FrontMatterError("the front matter has no closing '---' line")
    meta = load_yaml("".join(lines[1:end]), first_line=2) or {}
    if not isinstance(meta, dict):
        raise FrontMatterError("the front matter must be a mapping of keys to values")
    return Document(meta, "".join(lines[end + 1:]))


def read(path: Path) -> Document:
    return parse(path.read_text(encoding="utf-8"))


def _dump(meta: dict[str, Any]) -> str:
    # One key at a time: PyYAML writes a mapping of plain values as one flow line ({id: x, …}), but
    # front matter reads best as a line per key, with small lists and mappings inline.
    return "".join(yaml.safe_dump({k: v}, sort_keys=False, allow_unicode=True, width=100,
                                  default_flow_style=None if isinstance(v, (list, dict)) and v else False)
                   for k, v in meta.items())


def dump(meta: dict[str, Any], body: str = "") -> str:
    """A new file's text. Exchange writes new files; of files it did not write, it changes nothing."""
    body = body if not body or body.endswith("\n") else body + "\n"
    return f"---\n{_dump(meta)}---\n{body}"


_TOP_KEY = re.compile(r"^([A-Za-z_][\w-]*)\s*:")


def set_keys(text: str, updates: dict[str, Any], *, append: str = "") -> str:
    """``text`` with the top-level keys in ``updates`` rewritten in place (or added at the end of
    the front matter) and ``append`` added to the body. Every other line stays as it was. Used only
    on claims Exchange created; the result is parsed back to make sure nothing else changed."""
    before = parse(text)
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.lstrip("﻿").splitlines(keepends=True)
    end = next(i for i in range(1, len(lines)) if lines[i].rstrip() == "---")
    head = lines[1:end]
    for key, value in updates.items():
        new = [line + newline for line in _dump({key: value}).splitlines()]
        start = next((i for i, line in enumerate(head) if (m := _TOP_KEY.match(line)) and m.group(1) == key), None)
        if start is None:
            head += new
            continue
        stop = start + 1
        while stop < len(head) and (head[stop][:1] in (" ", "\t", "-") or not head[stop].strip()):
            stop += 1
        head[start:stop] = new
    body = "".join(lines[end + 1:])
    if append:
        if body and not body.endswith(("\n", "\r\n")):
            body += newline
        body += newline.join(append.rstrip("\n").split("\n")) + newline
    result = "".join([lines[0], *head, lines[end], body])
    after = parse(result)
    if after.meta != {**before.meta, **updates}:
        raise FrontMatterError("rewriting the front matter would change other keys; the file was left alone")
    return result


def _yaml_message(exc: yaml.YAMLError, first_line: int) -> str:
    mark = getattr(exc, "problem_mark", None)
    problem = getattr(exc, "problem", None) or str(exc)
    return f"line {mark.line + first_line}: {problem}" if mark is not None else problem
