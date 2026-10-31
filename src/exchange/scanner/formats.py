"""Small readers for environment-specific file formats.

* Daz ``.duf``/``.dsf`` files (JSON, often gzip-compressed): the content paths they reference,
  plus geometry and morph statistics (enrichment), and the ``asset_info`` type of a file's head
  (identification).
* Unreal ``.uasset`` files: the editor thumbnail stored inside the package.
"""

from __future__ import annotations

import codecs
import gzip
import io
import json
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from urllib.parse import unquote

MAX_DAZ_JSON_BYTES = 256 * 1024 * 1024
UASSET_MAGIC = b"\xc1\x83\x2a\x9e"

# Extensions a Daz reference can point at.
_DAZ_REF_EXTS = (".dsf", ".duf", ".dsa", ".dse", ".png", ".jpg", ".jpeg", ".tif", ".tiff",
                 ".bmp", ".tga", ".obj", ".hdr", ".exr")
_DAZ_REF = re.compile(r"^/[^#]+?\.(?:" + "|".join(e[1:] for e in _DAZ_REF_EXTS) + r")(?:#.*)?$",
                      re.IGNORECASE)


@dataclass
class DazFileInfo:
    references: list[str] = field(default_factory=list)  # content-relative paths, decoded
    stats: dict = field(default_factory=dict)


def read_daz_file(data: bytes) -> DazFileInfo | None:
    """Parse a .duf/.dsf file's JSON; None if it is not one."""
    if data[:2] == b"\x1f\x8b":
        try:
            data = gzip.GzipFile(fileobj=io.BytesIO(data)).read(MAX_DAZ_JSON_BYTES)
        except (OSError, EOFError):
            return None
    try:
        doc = json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(doc, dict):
        return None
    info = DazFileInfo()
    refs: dict[str, None] = {}
    for text in _strings(doc):
        if _DAZ_REF.match(text):
            refs[unquote(text.split("#", 1)[0]).lstrip("/")] = None
    info.references = list(refs)

    for geo in doc.get("geometry_library", []) or []:
        if isinstance(geo, dict):
            verts = (geo.get("vertices") or {}).get("count")
            polys = (geo.get("polylist") or {}).get("count")
            if isinstance(verts, int):
                info.stats["mesh_vertices"] = info.stats.get("mesh_vertices", 0) + verts
            if isinstance(polys, int):
                info.stats["mesh_polygons"] = info.stats.get("mesh_polygons", 0) + polys
    for mod in doc.get("modifier_library", []) or []:
        if isinstance(mod, dict) and isinstance(mod.get("morph"), dict):
            deltas = (mod["morph"].get("deltas") or {}).get("count")
            if isinstance(deltas, int):
                info.stats["morph_deltas"] = info.stats.get("morph_deltas", 0) + deltas
    return info


def daz_asset_type(head: bytes | None) -> str | None:
    """``asset_info.type`` read from the start of a ``.duf`` (already gunzipped); None if absent.

    The head is usually cut mid-JSON, so this walks the top-level keys and parses only the values
    before ``asset_info`` and ``asset_info`` itself, which must be whole in the head.
    """
    if not head:
        return None
    try:
        text = codecs.getincrementaldecoder("utf-8-sig")().decode(head)  # keeps a cut character back
    except UnicodeDecodeError:
        return None
    decoder, pos = json.JSONDecoder(), 0

    def skip(at: int) -> int:
        while at < len(text) and text[at] in " \t\r\n":
            at += 1
        return at

    try:
        pos = skip(pos)
        if text[pos] != "{":
            return None
        pos = skip(pos + 1)
        while text[pos] != "}":
            key, pos = decoder.raw_decode(text, pos)
            pos = skip(pos)
            if not isinstance(key, str) or text[pos] != ":":
                return None
            value, pos = decoder.raw_decode(text, skip(pos + 1))
            if key == "asset_info":
                kind = value.get("type") if isinstance(value, dict) else None
                return kind if isinstance(kind, str) else None
            pos = skip(pos)
            if text[pos] == ",":
                pos = skip(pos + 1)
            elif text[pos] != "}":
                return None
    except (IndexError, ValueError, RecursionError):  # cut by the head, or not JSON
        return None
    return None


def _strings(value) -> Iterator[str]:
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, str):
            yield item
        elif isinstance(item, dict):
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)


def uasset_thumbnail(data: bytes) -> bytes | None:
    """The first complete PNG or JPEG image stored inside an Unreal package, if any.

    The editor keeps asset thumbnails as compressed images in the package's thumbnail table, so
    finding the image's own signature is independent of the engine's header version.
    """
    if data[:4] != UASSET_MAGIC:
        return None
    start = data.find(b"\x89PNG\r\n\x1a\n")
    if start >= 0:
        end = data.find(b"IEND\xaeB`\x82", start)
        if end >= 0:
            return data[start : end + 8]
    start = data.find(b"\xff\xd8\xff")
    if start >= 0:
        end = data.find(b"\xff\xd9", start + 3)
        if end >= 0:
            return data[start : end + 2]
    return None
