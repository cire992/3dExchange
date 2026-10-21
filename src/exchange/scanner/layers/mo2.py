"""Mod Organizer 2: each folder under ``mods/`` is a container and a product.

``meta.ini`` supplies the Nexus mod ID, version and source. One environment covers the whole
instance; profiles are configuration, so each mod records which profiles enable it.
Everything outside the mods folder (profiles, logs, the instance's own files) is not content.
"""

from __future__ import annotations

from exchange.paths import fold, normalize_rel, rel_under
from exchange.scanner.layers.base import ContainerSpec, LayerContext, LayerResult, ProductSpec
from exchange.scanner.readonly import ini_value

_META_FIELDS = {  # meta.ini [General] key -> dossier field
    "modid": "nexus_mod_id",
    "version": "version",
    "repository": "source",
    "url": "url",
    "installationFile": "installation_file",
    "gameName": "game_name",
}


def identify(ctx: LayerContext) -> LayerResult:
    result = LayerResult()
    instance = ctx.read_ini("ModOrganizer.ini")
    mods_dir = normalize_rel(str(ctx.options.get("mods_dir", "mods")))
    custom = ini_value(instance, "Settings", "mod_directory")
    if custom:
        custom = normalize_rel(custom.replace("%BASE_DIR%", ""))
        if custom != mods_dir:
            result.warnings.append(
                f"ModOrganizer.ini sets mod_directory={custom}; only mods inside the scanned "
                f"folder are indexed, from {mods_dir}/"
            )

    profiles = _read_profiles(ctx)
    selected = ini_value(instance, "General", "selected_profile")
    result.layer_config = {"mods_dir": mods_dir, "selected_profile": selected,
                           "profiles": sorted(profiles)}

    mods: dict[str, list[str]] = {}
    mod_names: dict[str, str] = {}
    for f in ctx.files:
        inside = rel_under(f.rel, mods_dir)
        if inside is None or "/" not in inside:
            result.ignored.add(f.rel)  # instance files, or stray files directly in mods/
            continue
        mod = inside.split("/", 1)[0]
        mod_names.setdefault(fold(mod), mod)
        mods.setdefault(fold(mod), []).append(f.rel)

    for key in sorted(mods):
        name = mod_names[key]
        rel = f"{mods_dir}/{name}"
        meta_rel = next((r for r in mods[key] if fold(r) == fold(f"{rel}/meta.ini")), None)
        meta = _read_meta(ctx, meta_rel) if meta_rel else {}
        enabled = {p: mods_enabled.get(fold(name)) for p, mods_enabled in sorted(profiles.items())}
        result.containers.append(ContainerSpec(rel, "mod", name, {"meta": meta, "enabled_in": enabled}))

        fields = {field: meta.get(key_) for key_, field in _META_FIELDS.items()}
        if fields["nexus_mod_id"] is not None:
            try:
                mod_id = int(fields["nexus_mod_id"])
                fields["nexus_mod_id"] = mod_id if mod_id > 0 else None
            except ValueError:
                fields["nexus_mod_id"] = None
        fields = {k: v for k, v in fields.items() if v not in (None, "")}
        signals = ["mo2 mod folder"] + (["meta.ini"] if meta else [])
        result.products.append(ProductSpec(
            container_rel=rel,
            identity_key=f"mod:{fold(name)}",
            name=name,
            confidence=0.95 if meta else 0.9,
            signals=signals,
            fields=fields,
            primary=[meta_rel] if meta_rel else [],
            members=[r for r in mods[key] if r != meta_rel],
        ))
    return result


def _read_meta(ctx: LayerContext, rel: str) -> dict[str, str]:
    parser = ctx.read_ini(rel)
    if parser is None:
        return {}
    return {key: value for key in _META_FIELDS
            if (value := ini_value(parser, "General", key)) not in (None, "")}


def _read_profiles(ctx: LayerContext) -> dict[str, dict[str, bool]]:
    """profile name -> {folded mod name: enabled} from each profile's modlist.txt."""
    profiles: dict[str, dict[str, bool]] = {}
    for f in ctx.all_files:
        parts = f.rel.split("/")
        if len(parts) == 3 and fold(parts[0]) == "profiles" and fold(parts[2]) == "modlist.txt":
            data = ctx.read_bytes(f.rel) or b""
            states: dict[str, bool] = {}
            for line in data.decode("utf-8-sig", errors="replace").splitlines():
                if line[:1] in ("+", "-"):
                    states[fold(line[1:].strip())] = line[0] == "+"
            profiles[parts[1]] = states
    return profiles
