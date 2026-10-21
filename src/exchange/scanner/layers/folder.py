"""Loose files: every folder that directly holds files is a container.

A folder holding several recognizable assets is guessed to be a product, at low confidence.
A folder with a single asset needs no product; that asset stands alone.
"""

from __future__ import annotations

from collections import defaultdict

from exchange.scanner.layers.base import ContainerSpec, LayerContext, LayerResult, ProductSpec


def identify(ctx: LayerContext) -> LayerResult:
    result = LayerResult()
    by_dir: dict[str, list[str]] = defaultdict(list)
    for f in ctx.files:
        by_dir[f.rel.rsplit("/", 1)[0] if "/" in f.rel else ""].append(f.rel)

    product_confidence = float(ctx.options.get("product_confidence", 0.3))
    for folder, rels in sorted(by_dir.items()):
        name = folder.rsplit("/", 1)[-1] if folder else ctx.root.name
        result.containers.append(ContainerSpec(folder, "folder", name))
        assets = [r for r in rels if ctx.match_type(r.rsplit("/", 1)[-1])]
        if len(assets) >= 2:
            result.products.append(ProductSpec(
                container_rel=folder,
                identity_key=f"folder:{folder}",
                name=name,
                confidence=product_confidence,
                signals=[f"folder holds {len(assets)} assets"],
                members=rels,
            ))
    return result
