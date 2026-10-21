"""Daz Studio: the content directory is the container; DIM support manifests seed products.

Manifests are hints, not truth. This first pass matches manifest paths to files by expected
relative path only; filename + size and hash matching (to find relocated files) come later.

Support manifests live in ``Runtime/Support/*.dsx``. The parser reads what it recognizes and
ignores the rest: ``ProductName``, ``ProductToken``, ``ProductStoreIDX``, ``ProductFileGuid``,
``Artist`` elements, and file paths from ``File`` / ``ContentFile`` elements' ``VALUE``.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from exchange.globs import glob_match
from exchange.paths import fold, normalize_rel
from exchange.scanner.layers.base import ContainerSpec, LayerContext, LayerResult, ProductSpec

_IMAGE_EXTS = (".png", ".jpg", ".jpeg")


def identify(ctx: LayerContext) -> LayerResult:
    result = LayerResult()
    result.containers.append(ContainerSpec("", "content_directory", ctx.root.name))
    by_key = {fold(f.rel): f.rel for f in ctx.files}
    manifest_glob = str(ctx.options.get("manifest_glob", "Runtime/Support/*.dsx"))

    for f in ctx.files:
        if not glob_match(manifest_glob, f.rel):
            continue
        manifest = _parse_manifest(ctx.read_bytes(f.rel))
        if manifest is None:
            result.warnings.append(f"{f.rel}: not a readable Daz manifest, skipped")
            continue
        listed = [normalize_rel(_strip_content_prefix(p)) for p in manifest.pop("files")]
        members = [by_key[fold(p)] for p in dict.fromkeys(listed) if fold(p) in by_key]
        missing = len(set(map(fold, listed))) - len(members)
        stem = f.rel.rsplit(".", 1)[0]
        images = [by_key[k] for ext in _IMAGE_EXTS if (k := fold(stem + ext)) in by_key]
        name = manifest.pop("name", None) or stem.rsplit("/", 1)[-1]
        result.products.append(ProductSpec(
            container_rel="",
            identity_key=f"manifest:{fold(f.rel)}",
            name=name,
            confidence=0.9,
            signals=[f"manifest {f.rel}"],
            fields={**manifest, "manifest_files_listed": len(set(map(fold, listed))),
                    "manifest_files_missing": missing},
            primary=[f.rel],
            members=images + members,
        ))
    return result


def _strip_content_prefix(path: str) -> str:
    path = path.replace("\\", "/").lstrip("/")
    return path[len("Content/"):] if fold(path).startswith("content/") else path


def _parse_manifest(data: bytes | None) -> dict | None:
    if not data:
        return None
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return None
    fields: dict = {"files": []}
    artists: list[str] = []
    simple = {"ProductName": "name", "ProductToken": "daz_product_token",
              "ProductStoreIDX": "daz_store_idx", "ProductFileGuid": "daz_file_guid"}
    for el in root.iter():
        value = el.get("VALUE")
        if value is None:
            continue
        if el.tag in simple:
            fields.setdefault(simple[el.tag], value)
        elif el.tag == "Artist":
            artists.append(value)
        elif el.tag in ("File", "ContentFile"):
            fields["files"].append(value)
    if artists:
        fields["authors"] = artists
    return fields
