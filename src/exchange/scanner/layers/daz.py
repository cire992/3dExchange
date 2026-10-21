"""Daz Studio: each content directory is a container; products come from two sources.

* **DIM support manifests** (``Runtime/Support/*.dsx``) are hints, not truth. Listed files are
  matched by expected relative path; a listed file that is missing there but whose filename is
  found exactly once elsewhere in the content directory is taken as *relocated*. Hash matching
  comes with scan phase 3.
* **Daz Connect** installs each product into ``data/cloud/<n>_<SKU>/``, laid out like a content
  directory of its own.

Both carry the product's SKU, so a product installed both ways becomes one product dossier.

The manifest parser reads what it recognizes and ignores the rest: ``ProductName``,
``ProductToken``, ``ProductStoreIDX``, ``ProductFileGuid``, ``Artist`` elements, and file paths
from ``File`` / ``ContentFile`` elements' ``VALUE``.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict

from exchange.globs import glob_match
from exchange.paths import fold, normalize_rel
from exchange.scanner.layers.base import (
    ContainerSpec,
    FileInfo,
    LayerContext,
    LayerResult,
    ProductSpec,
)

_IMAGE_EXTS = (".png", ".jpg", ".jpeg")
_CLOUD_FOLDER = re.compile(r"^data/cloud/(\d+_(\d+))(?:/|$)", re.IGNORECASE)


def identify(ctx: LayerContext) -> LayerResult:
    result = LayerResult()
    result.containers.append(ContainerSpec("", "content_directory", ctx.root.name))
    by_key = {fold(f.rel): f.rel for f in ctx.files}
    manifest_glob = str(ctx.options.get("manifest_glob", "Runtime/Support/*.dsx"))

    cloud: dict[str, list[FileInfo]] = defaultdict(list)
    for f in ctx.files:
        match = _CLOUD_FOLDER.match(f.rel)
        if match:
            cloud[f.rel[: match.end(1)]].append(f)

    manifests = [f for f in ctx.files if glob_match(manifest_glob, f.rel)]
    listed_everywhere: set[str] = set()
    parsed: list[tuple[FileInfo, dict, list[str]]] = []
    for f in manifests:
        manifest = _parse_manifest(ctx.read_bytes(f.rel))
        if manifest is None:
            result.warnings.append(f"{f.rel}: not a readable Daz manifest, skipped")
            continue
        listed = list(dict.fromkeys(normalize_rel(_strip_content_prefix(p)) for p in manifest.pop("files")))
        listed_everywhere.update(fold(p) for p in listed)
        parsed.append((f, manifest, listed))

    # Files no manifest lists, by filename, for finding relocated files.
    unlisted_names = Counter(fold(f.rel.rsplit("/", 1)[-1]) for f in ctx.files
                             if fold(f.rel) not in listed_everywhere)
    unlisted_by_name = {fold(f.rel.rsplit("/", 1)[-1]): f.rel for f in ctx.files
                        if fold(f.rel) not in listed_everywhere}

    for f, manifest, listed in parsed:
        members, relocated, missing = [], 0, 0
        for path in listed:
            if fold(path) in by_key:
                members.append(by_key[fold(path)])
                continue
            name = fold(path.rsplit("/", 1)[-1])
            if unlisted_names.get(name) == 1:
                members.append(unlisted_by_name[name])
                relocated += 1
            else:
                missing += 1
        token = manifest.get("daz_product_token")
        result.products.append(ProductSpec(
            container_rel="",
            identity_key=f"manifest:{fold(f.rel)}",
            name=manifest.pop("name", None) or f.rel.rsplit("/", 1)[-1].rsplit(".", 1)[0],
            confidence=0.9,
            signals=[f"manifest {f.rel}"],
            fields={**manifest, "manifest_files_listed": len(listed),
                    "manifest_files_missing": missing, "manifest_files_relocated": relocated},
            primary=[f.rel],
            members=_images_beside(f.rel, by_key) + members,
            product_key=f"daz:{token}" if token else None,
        ))

    for folder, files in sorted(cloud.items()):
        sku = _CLOUD_FOLDER.match(folder).group(2)
        result.products.append(ProductSpec(
            container_rel="",
            identity_key=f"cloud:{fold(folder)}",
            name=f"Daz Connect product {sku}",
            confidence=0.8,
            signals=[f"daz connect folder {folder}"],
            fields={"daz_product_token": sku, "installed_by": "Daz Connect"},
            members=[f.rel for f in files],
            product_key=f"daz:{sku}",
            type_root=folder,
        ))
    return result


def _images_beside(rel: str, by_key: dict[str, str]) -> list[str]:
    stem = rel.rsplit(".", 1)[0]
    return [by_key[k] for ext in _IMAGE_EXTS if (k := fold(stem + ext)) in by_key]


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

