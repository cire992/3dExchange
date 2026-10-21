"""Daz Studio: each content directory is a container; products come from two sources.

* **DIM install manifests** (``Runtime/Support/*.dsx``, ``<ContentDBInstall>``) are hints, not
  truth. Each ``<Product>`` names the product, its SKU (``ProductToken``), ``GlobalID`` and
  artists, its user-facing ``Assets`` (each with a Daz ``ContentType`` and figure
  ``Compatibility``) and its ``SupportAssets``. Assets whose ContentType maps to a dossier type
  (``content_types`` in the definition) become child dossiers; everything else listed stays a file
  of the product. A listed file missing at its path but whose parent folder and filename are
  found together exactly once elsewhere in the content directory (users reorganize libraries) is
  taken as *relocated*; hash matching comes later.
* **Daz Connect** installs each product into ``data/cloud/<n>_<SKU>/``, laid out like a content
  directory of its own; its files are typed by the dossier-type rules.

Both carry the product's SKU, so a product installed both ways becomes one product dossier.
Empty manifests (DIM writes some for "local user" content) are skipped.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from urllib.parse import unquote

from exchange.globs import glob_match
from exchange.paths import fold, normalize_rel
from exchange.scanner.layers.base import (
    ChildSpec,
    ContainerSpec,
    FileInfo,
    LayerContext,
    LayerResult,
    ProductSpec,
)

_IMAGE_EXTS = (".png", ".jpg", ".jpeg")
_CLOUD_FOLDER = re.compile(r"^data/cloud/(\d+_(\d+))(?:/|$)", re.IGNORECASE)
MANIFEST_CONFIDENCE = 0.9
ASSET_CONFIDENCE = 0.85


@dataclass
class ManifestAsset:
    path: str
    content_type: str = ""
    compatibilities: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)


@dataclass
class ManifestProduct:
    name: str
    fields: dict = field(default_factory=dict)
    assets: list[ManifestAsset] = field(default_factory=list)
    support: list[str] = field(default_factory=list)


def identify(ctx: LayerContext) -> LayerResult:
    result = LayerResult()
    result.containers.append(ContainerSpec("", "content_directory", ctx.root.name))
    by_key = {fold(f.rel): f.rel for f in ctx.files}
    manifest_glob = str(ctx.options.get("manifest_glob", "Runtime/Support/*.dsx"))
    content_types = dict(ctx.options.get("content_types", {}))
    compat_variants = dict(ctx.options.get("compatibility_variants", {}))
    for type_id in set(content_types.values()) - set(ctx.definitions.dossier_types):
        result.warnings.append(f"content_types maps to unknown dossier type {type_id!r}")

    cloud: dict[str, list[FileInfo]] = defaultdict(list)
    for f in ctx.files:
        match = _CLOUD_FOLDER.match(f.rel)
        if match:
            cloud[f.rel[: match.end(1)]].append(f)

    parsed: list[tuple[FileInfo, ManifestProduct]] = []
    listed_everywhere: set[str] = set()
    empty = 0
    for f in ctx.files:
        if not glob_match(manifest_glob, f.rel):
            continue
        if f.size == 0:
            empty += 1
            result.ignored.add(f.rel)
            continue
        products = parse_manifest(ctx.read_bytes(f.rel))
        if products is None:
            result.warnings.append(f"{f.rel}: not a readable Daz manifest, skipped")
            continue
        for product in products:
            parsed.append((f, product))
            listed_everywhere.update(fold(p) for p in _listed(product))
    if empty:
        result.layer_config["empty_manifests"] = empty

    # Files no manifest lists, by folder + filename, for finding relocated files. The folder
    # is part of the key because generic filenames (!Preload.duf) say nothing on their own.
    unlisted = [f.rel for f in ctx.files if fold(f.rel) not in listed_everywhere]
    unlisted_tails = Counter(_tail(r) for r in unlisted)
    unlisted_by_tail = {_tail(r): r for r in unlisted}

    def locate(path: str) -> tuple[str | None, bool]:
        """(root-relative path on disk, relocated?)"""
        for candidate in (path, unquote(path)):
            if fold(candidate) in by_key:
                return by_key[fold(candidate)], False
        tail = _tail(path)
        if "/" in tail and unlisted_tails.get(tail) == 1:
            return unlisted_by_tail[tail], True
        return None, False

    per_manifest = Counter(f.rel for f, _ in parsed)
    for index, (f, product) in enumerate(parsed):
        members, children, relocated, missing = [], [], 0, 0
        for path in _listed(product):
            found, moved = locate(path)
            if found is None:
                missing += 1
                continue
            members.append(found)
            relocated += moved
        for asset in product.assets:
            found, _ = locate(asset.path)
            type_id = _content_type(asset.content_type, content_types)
            if found is None or type_id is None:
                continue
            fields = {"daz_content_type": asset.content_type}
            if asset.compatibilities:
                fields["daz_compatibility"] = asset.compatibilities
                variant = _compat_variant(asset.compatibilities, compat_variants)
                if variant:
                    fields["variant"] = variant
            if asset.categories:
                fields["daz_categories"] = asset.categories
            children.append(ChildSpec(found, type_id, ASSET_CONFIDENCE,
                                      [f"manifest asset: {asset.content_type}"], fields))
        token = product.fields.get("daz_product_token")
        suffix = f"#{index}" if per_manifest[f.rel] > 1 else ""
        result.products.append(ProductSpec(
            container_rel="",
            identity_key=f"manifest:{fold(f.rel)}{suffix}",
            name=product.name or f.rel.rsplit("/", 1)[-1].rsplit(".", 1)[0],
            confidence=MANIFEST_CONFIDENCE,
            signals=[f"manifest {f.rel}"],
            fields={**product.fields, "manifest_files_listed": len(_listed(product)),
                    "manifest_files_missing": missing, "manifest_files_relocated": relocated},
            primary=[f.rel],
            members=_images_beside(f.rel, by_key) + members,
            product_key=f"daz:{token}" if token else None,
            children=children,
            children_only=True,
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


def _tail(rel: str) -> str:
    """The parent folder and filename, folded: ``a/b/Folder/File.duf`` -> ``folder/file.duf``."""
    return fold("/".join(rel.split("/")[-2:]))


def _listed(product: ManifestProduct) -> list[str]:
    return list(dict.fromkeys([a.path for a in product.assets] + product.support))


def _content_type(content_type: str, mapping: dict[str, str]) -> str | None:
    best = None
    for prefix, type_id in mapping.items():
        if content_type == prefix or content_type.startswith(prefix + "/"):
            if best is None or len(prefix) > len(best[0]):
                best = (prefix, type_id)
    return best[1] if best else None


def _compat_variant(compatibilities: list[str], mapping: dict[str, str]) -> str | None:
    for compat in compatibilities:
        base = compat.split("#", 1)[0]
        for prefix, variant in sorted(mapping.items(), key=lambda kv: -len(kv[0])):
            if base == prefix or base.startswith(prefix + "/"):
                return variant
    return None


def _images_beside(rel: str, by_key: dict[str, str]) -> list[str]:
    stem = rel.rsplit(".", 1)[0]
    return [by_key[k] for ext in _IMAGE_EXTS if (k := fold(stem + ext)) in by_key]


def _path(value: str) -> str:
    path = value.replace("\\", "/").lstrip("/")
    if fold(path).startswith("content/"):  # DIM package paths
        path = path[len("Content/"):]
    return normalize_rel(path)


def parse_manifest(data: bytes | None) -> list[ManifestProduct] | None:
    """Products in a DIM install manifest; None if it is not one."""
    if not data:
        return None
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return None
    if root.tag != "ContentDBInstall":
        return None
    products = []
    for el in root.iter("Product"):
        product = ManifestProduct(name=el.get("VALUE", "").strip())
        simple = {"ProductToken": "daz_product_token", "GlobalID": "daz_global_id",
                  "StoreID": "daz_store"}
        for child in el:
            value = child.get("VALUE")
            if child.tag in simple and value:
                product.fields[simple[child.tag]] = value
        artists = [a.get("VALUE") for a in el.iter("Artist") if a.get("VALUE")]
        if artists:
            product.fields["authors"] = artists
        for asset in el.iter("Asset"):
            if not asset.get("VALUE"):
                continue
            ct = asset.find("ContentType")
            product.assets.append(ManifestAsset(
                path=_path(asset.get("VALUE")),
                content_type=ct.get("VALUE", "") if ct is not None else "",
                compatibilities=[c.get("VALUE") for c in asset.iter("Compatibility") if c.get("VALUE")],
                categories=[c.get("VALUE") for c in asset.iter("Category") if c.get("VALUE")],
            ))
        product.support = [_path(s.get("VALUE")) for s in el.iter("SupportAsset") if s.get("VALUE")]
        products.append(product)
    return products
