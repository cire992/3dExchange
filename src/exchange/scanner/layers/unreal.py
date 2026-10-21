"""Unreal Engine project: content packs under ``Content/`` and plugins are containers.

* Each top-level folder under ``Content/`` is a container; it is guessed to be a content pack
  (a product, e.g. from Fab) unless it is the project's own folder or an editor folder.
* Each plugin (a folder holding a ``.uplugin``) is a container and a product described by its
  ``.uplugin`` file. Only its ``Content/`` folder and icon count as content.
* Everything else (Config/, Source/, the .uproject, ...) is project plumbing, not content.

Asset types come from naming conventions (SM_, SK_, T_, M_, BP_ ...) in this pass.
"""

from __future__ import annotations

import json

from exchange.globs import glob_match
from exchange.paths import fold, rel_under
from exchange.scanner.layers.base import ContainerSpec, LayerContext, LayerResult, ProductSpec

_UPLUGIN_FIELDS = {  # .uplugin key -> dossier field
    "VersionName": "version",
    "CreatedBy": "authors",
    "Description": "description",
    "Category": "category",
    "MarketplaceURL": "url",
    "EngineVersion": "engine_version",
}


def identify(ctx: LayerContext) -> LayerResult:
    result = LayerResult()
    uproject = next((f for f in ctx.all_files if glob_match("*.uproject", f.rel)), None)
    project = uproject.rel.rsplit(".", 1)[0] if uproject else ctx.root.name
    result.layer_config = {"project": project}
    if uproject is not None:
        info = _read_json(ctx, uproject.rel)
        if isinstance(info.get("EngineAssociation"), str):
            result.layer_config["engine_association"] = info["EngineAssociation"]

    plugin_dirs = sorted(
        (f.rel.rsplit("/", 1)[0] for f in ctx.files if glob_match("Plugins/**/*.uplugin", f.rel)),
        key=len)
    not_packs = {fold(n) for n in ctx.options.get("not_packs", [])} | {fold(project)}
    project_files: list[str] = []
    packs: dict[str, list[str]] = {}
    plugins: dict[str, list[str]] = {d: [] for d in plugin_dirs}

    for f in ctx.files:
        plugin = next((d for d in reversed(plugin_dirs) if rel_under(f.rel, d) is not None), None)
        if plugin is not None:
            inside = rel_under(f.rel, plugin)
            if fold(inside).startswith("content/") or fold(inside).startswith("resources/") \
                    or glob_match("*.uplugin", inside):
                plugins[plugin].append(f.rel)
            else:
                result.ignored.add(f.rel)
            continue
        inside = rel_under(f.rel, "Content")
        if inside is None:
            result.ignored.add(f.rel)
        elif "/" in inside and fold(inside.split("/", 1)[0]) not in not_packs:
            packs.setdefault(f"Content/{inside.split('/', 1)[0]}", []).append(f.rel)
        else:
            project_files.append(f.rel)

    if project_files:
        result.containers.append(ContainerSpec("Content", "project_content", project))
    for folder, files in sorted(packs.items()):
        name = folder.split("/", 1)[1]
        result.containers.append(ContainerSpec(folder, "content_pack", name))
        result.products.append(ProductSpec(
            container_rel=folder, identity_key=f"pack:{fold(folder)}", name=name,
            confidence=0.55, signals=["top-level Content folder"], members=files))
    for folder, files in plugins.items():
        uplugin = next(r for r in files if glob_match("*.uplugin", rel_under(r, folder)))
        info = _read_json(ctx, uplugin)
        name = info.get("FriendlyName") or folder.rsplit("/", 1)[-1]
        fields = {field: info[key] for key, field in _UPLUGIN_FIELDS.items()
                  if isinstance(info.get(key), (str, int)) and info.get(key) != ""}
        if "authors" in fields:
            fields["authors"] = [fields["authors"]]
        icon = next((r for r in files if fold(rel_under(r, folder)) == "resources/icon128.png"), None)
        if icon:
            fields["preview"] = icon
        result.containers.append(ContainerSpec(folder, "plugin", name, {"uplugin": fields}))
        result.products.append(ProductSpec(
            container_rel=folder, identity_key=f"plugin:{fold(folder)}", name=name,
            confidence=0.9 if info else 0.7, signals=[f"plugin {uplugin}"], fields=fields,
            primary=[uplugin], members=[r for r in files if r != uplugin]))
    return result


def _read_json(ctx: LayerContext, rel: str) -> dict:
    data = ctx.read_bytes(rel)
    try:
        value = json.loads((data or b"").decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}
