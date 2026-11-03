"""A Genesis 9 character's shape as a Genesis 8 Female morph: Daz Studio, Blender, Daz Studio.

Each step writes into its own work folder; nothing is written beside the character's files. The
morph is built on the Exchange G8F copy (see ``docs/PROCESS_FILES.md``), whose figure has a path of
its own, so the user's Genesis 8 Female and Daz Studio's cache for it are never touched; the
process's last step points the morph at the regular figure (``core.rewrite_daz_paths``).
"""

import json
import os
import re
import shutil
import zipfile
from pathlib import Path

from exchange.paths import data_dir
from exchange.processes.operations import OperationError, operation

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
ADDON = "Daz_Generations"
# The template's G9 surfaces, and the character's surfaces each takes its maps from, in order of choice.
TEMPLATE_SURFACES = {"Head": ("Head",), "Body": ("Body",), "Legs": ("Legs",), "Arms": ("Arms",),
                     "Nails": ("Fingernails", "Toenails")}
LOSSLESS = (".png", ".tif", ".tiff")


@operation("export_shape", inputs=("Files",), output="Files", app="daz_studio")
def export_shape(ctx, files, target_figure=""):
    """Write the character's shape and the target figure's stock mesh as OBJ files."""
    characters = [path for path in files.paths() if path.suffix.lower() == ".duf"]
    if len(characters) != 1:
        found = ", ".join(p.name for p in characters) or "none"
        raise OperationError(f"expected one character file (.duf), found {found}")
    out = ctx.new_dir("shapes")
    (out / "layered").mkdir()
    result = ctx.bridge("daz_studio").run(SCRIPTS / "export_shape.dsa", {
        "source": characters[0].as_posix(), "target": target_figure,
        "shape": (out / "character.obj").as_posix(), "base": (out / "target.obj").as_posix(),
        "skin": (out / "skin.json").as_posix(), "layered": (out / "layered").as_posix()})
    for line in result.get("log", []):
        ctx.log(line)
    ctx.log(f"{result.get('figure', '?')}: {result['shape']['vertices']} vertices, {result.get('surfaces', 0)} "
            f"surfaces; the target {result['base']['vertices']}")
    return files.derive(out, ["character.obj", "target.obj", "skin.json"], figure=result.get("figure", ""),
                        skin=(out / "skin.json").as_posix())


@operation("convert_shape", inputs=("Files",), output="Files", app="blender")
def convert_shape(ctx, shapes, method="v3"):
    """Daz Generations: move the target's stock mesh to the character's shape."""
    out = ctx.new_dir("converted")
    character, target = (shapes.root / name for name in ("character.obj", "target.obj"))
    result = ctx.bridge("blender").run(SCRIPTS / "convert_shape.py", {
        "addon": str(extracted(ctx.tool("daz_generations"), "daz_generations", addon_files)),
        "shape": str(character), "base": str(target),
        "out": str(out / "shape.obj"), "method": method})
    ctx.log(f"Daz Generations {method}: {result['vertices']} vertices in {result['seconds']} s "
            f"(rescale {result['rescale']})")
    return shapes.derive(out, ["shape.obj"])


@operation("bake_skin", inputs=("Files",), output="Files", app="blender")
def bake_skin(ctx, shape, resolution=0, samples=16):
    """The Texture Converter template: bake the character's skin maps onto Genesis 8 Female's tiles."""
    skin = json.loads(Path(shape.meta["skin"]).read_text(encoding="utf-8"))
    channels = skin_channels(skin, resolution)
    for line in skin_notes(skin):
        ctx.log(line)
    if not channels:
        raise OperationError(f"{skin.get('figure', 'the character')} has no skin maps to bake")
    out = ctx.new_dir("textures")
    prefix = morph_name(ctx.dossier.get("name") or "Character")
    template = extracted(ctx.tool("texture_converter_g9_g8f"), "texture_converter_g9_g8f", template_files)
    result = ctx.bridge("blender").run(SCRIPTS / "bake_skin.py", {
        "channels": channels, "out": out.as_posix(), "prefix": prefix, "samples": samples},
        template=template)
    ctx.log(f"baked on {result['device']}")
    files = []
    for baked in result["channels"]:
        ctx.log(f"{baked['name']}: {baked['size']} px in {baked['seconds']} s")
        files += baked["files"]
    missing = [f for f in files if not (out / f).is_file()]
    if missing:
        raise OperationError(f"Blender didn't write {', '.join(missing)}")
    return shape.derive(shape.root, shape.files, textures=out.as_posix(), texture_files=files)


@operation("build_morph", inputs=("Files",), output="Files", app="daz_studio")
def build_morph(ctx, shape, figure="", tolerance=0.01):
    """Build the morph on the target figure, check it lands on the shape, and save it with the baked
    skin maps (``Runtime/Textures/Exchange/<character>/``)."""
    label = ctx.dossier.get("name") or "Character"
    name = morph_name(label)
    library = ctx.new_dir("library")
    result = ctx.bridge("daz_studio").run(SCRIPTS / "build_morph.dsa", {
        "figure": figure, "shape": (shape.root / "shape.obj").as_posix(), "morph": name, "label": label,
        "product": folder_name(label), "library": library.as_posix(), "tolerance": tolerance})
    for line in result.get("log", []):
        ctx.log(line)
    ctx.log(f"{name}: at 1 it lands within {result['largest_difference']:.5f} cm of the shape")
    saved = [p for p in library.rglob("*.dsf")]
    if len(saved) != 1:
        raise OperationError(f"Daz Studio saved {len(saved)} morph files, not one")
    stable_id(saved[0], name)
    maps = place_maps(shape, library / "Runtime" / "Textures" / "Exchange" / folder_name(label))
    return shape.derive(library, [p.relative_to(library).as_posix() for p in saved + maps])


def place_maps(shape, folder):
    """The bake's maps, linked (or copied) into the library's texture folder."""
    if not shape.meta.get("textures"):
        return []
    folder.mkdir(parents=True, exist_ok=True)
    placed = []
    for name in shape.meta["texture_files"]:
        source, target = Path(shape.meta["textures"]) / name, folder / name
        try:
            os.link(source, target)
        except OSError:
            shutil.copy2(source, target)
        placed.append(target)
    return placed


def morph_name(label):
    """A morph's name from the character's: letters and digits only, as Daz node names are safest."""
    name = re.sub(r"[^A-Za-z0-9]+", "", label)
    return name if name and not name[0].isdigit() else f"Exchange{name}"


def folder_name(label):
    """The character's name as a folder."""
    return re.sub(r'[<>:"/\\|?*]+', " ", label).strip(" .") or "Character"


def stable_id(path, name):
    """Daz saves a new morph's id with a random suffix (``Luanne-0xab0df0d``), a new one at each save,
    so a rebuilt morph would break scenes that used the last one. The suffix is dropped."""
    text = path.read_text(encoding="utf-8")
    fixed = re.sub(rf"(?<![\w-]){re.escape(name)}-0x[0-9a-f]+\b", name, text)
    if fixed != text:
        path.write_text(fixed, encoding="utf-8")


def skin_channels(skin, resolution=0):
    """What to bake: each channel mapped on one of the template's surfaces, with each surface's map, or a
    neutral flat colour where that surface has none (the channel's value then does the work on G8F, as
    it did on G9). A layered image is baked from the copy Daz flattened in step 1."""
    surfaces = {}
    for name, sources in TEMPLATE_SURFACES.items():
        found = next((skin["surfaces"][s] for s in sources if s in skin["surfaces"]), None)
        surfaces[name] = {c["name"]: c for c in (found or {}).get("channels", [])}
    channels = {}
    for surface, by_name in surfaces.items():
        for channel in by_name.values():
            texture = channel.get("map")
            if not texture:
                continue
            if not texture.get("file"):
                if texture.get("kind") == "DzLayeredTexture":
                    raise OperationError(f"{surface}'s {channel['label']} is a layered image Daz Studio didn't flatten")
                continue
            channels.setdefault(channel["name"], channel)
    baked = []
    for name, channel in channels.items():
        neutral = [0.5, 0.5, 1.0] if "normal" in name.lower() else [1.0, 1.0, 1.0]
        sources = {surface: ((by_name.get(name) or {}).get("map") or {}).get("file") or neutral
                   for surface, by_name in surfaces.items()}
        lossless = any(Path(s).suffix.lower() in LOSSLESS for s in sources.values() if isinstance(s, str))
        baked.append({"name": re.sub(r"[^A-Za-z0-9]+", "", channel["label"]) or "Map", "channel": name,
                      "data": channel["type"] != "color", "format": "PNG" if lossless else "JPEG",
                      "size": resolution, "sources": sources})
    return baked


def skin_notes(skin):
    """What the bake leaves out, for the run's log."""
    taken = {s for sources in TEMPLATE_SURFACES.values() for s in sources}
    left = sorted(s for s in skin["surfaces"] if s not in taken)
    if left:
        yield f"left as Genesis 8 Female's own: {', '.join(left)}"
    yield "the template's nail overlays aren't applied (its guide blends them in by hand)"


def addon_files(names):
    """Daz Generations' archive: the add-on's folder, with its database."""
    if f"{ADDON}/__init__.py" not in names or f"{ADDON}/conversionDB.db" not in names:
        return None
    return [n for n in names if n.startswith(f"{ADDON}/")]


def template_files(names):
    """A Texture Converter archive: one ``.blend`` at its top, and its overlays."""
    blends = [n for n in names if n.lower().endswith(".blend") and "/" not in n]
    return names if len(blends) == 1 else None


def extracted(archive, tool, wanted):
    """A tool's archive, extracted once into Exchange's data folder (``tools/<tool>/<archive name>``).
    ``wanted`` picks the members to extract from the archive's names, or gives None if it isn't that
    tool's. The archive is only read, and nothing is installed into the user's Blender. Gives the
    extracted ``.blend`` for a template, the folder for anything else."""
    archive = Path(archive)
    folder = data_dir() / "tools" / tool / archive.stem
    if not folder.is_dir():
        try:
            with zipfile.ZipFile(archive) as z:
                members = wanted(z.namelist())
                if not members:
                    raise OperationError(f"{archive.name} isn't the archive {tool} needs")
                partial = folder.with_name(folder.name + ".partial")
                shutil.rmtree(partial, ignore_errors=True)
                z.extractall(partial, members)
        except zipfile.BadZipFile as exc:
            raise OperationError(f"cannot read {archive}: {exc}") from exc
        partial.rename(folder)
    blends = list(folder.glob("*.blend"))
    return blends[0] if len(blends) == 1 else folder
