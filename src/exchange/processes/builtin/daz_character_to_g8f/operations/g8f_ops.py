"""A Genesis 9 character's shape as a Genesis 8 Female morph: Daz Studio, Blender, Daz Studio.

Each step writes into its own work folder; nothing is written beside the character's files. The
morph is built on the Exchange G8F copy (see ``docs/PROCESS_FILES.md``), whose figure has a path of
its own, so the user's Genesis 8 Female and Daz Studio's cache for it are never touched; the
process's last step points the morph at the regular figure (``core.rewrite_daz_paths``).
"""

import re
import shutil
import zipfile
from pathlib import Path

from exchange.paths import data_dir
from exchange.processes.operations import OperationError, operation

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
ADDON = "Daz_Generations"


@operation("export_shape", inputs=("Files",), output="Files", app="daz_studio")
def export_shape(ctx, files, target_figure=""):
    """Write the character's shape and the target figure's stock mesh as OBJ files."""
    characters = [path for path in files.paths() if path.suffix.lower() == ".duf"]
    if len(characters) != 1:
        found = ", ".join(p.name for p in characters) or "none"
        raise OperationError(f"expected one character file (.duf), found {found}")
    out = ctx.new_dir("shapes")
    result = ctx.bridge("daz_studio").run(SCRIPTS / "export_shape.dsa", {
        "source": characters[0].as_posix(), "target": target_figure,
        "shape": (out / "character.obj").as_posix(), "base": (out / "target.obj").as_posix()})
    for line in result.get("log", []):
        ctx.log(line)
    ctx.log(f"{result.get('figure', '?')}: {result['shape']['vertices']} vertices; "
            f"the target {result['base']['vertices']}")
    return files.derive(out, ["character.obj", "target.obj"], figure=result.get("figure", ""))


@operation("convert_shape", inputs=("Files",), output="Files", app="blender")
def convert_shape(ctx, shapes, method="v3"):
    """Daz Generations: move the target's stock mesh to the character's shape."""
    out = ctx.new_dir("converted")
    character, target = (shapes.root / name for name in ("character.obj", "target.obj"))
    result = ctx.bridge("blender").run(SCRIPTS / "convert_shape.py", {
        "addon": str(addon_folder(ctx.tool("daz_generations"))), "shape": str(character), "base": str(target),
        "out": str(out / "shape.obj"), "method": method})
    ctx.log(f"Daz Generations {method}: {result['vertices']} vertices in {result['seconds']} s "
            f"(rescale {result['rescale']})")
    return shapes.derive(out, ["shape.obj"])


@operation("build_morph", inputs=("Files",), output="Files", app="daz_studio")
def build_morph(ctx, shape, figure="", tolerance=0.01):
    """Build the morph on the target figure, check it lands on the shape, and save it."""
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
    return shape.derive(library, [p.relative_to(library).as_posix() for p in saved])


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


def addon_folder(archive):
    """The Daz Generations add-on, extracted once from the user's archive into Exchange's data folder
    (``tools/daz_generations/<archive name>``). The archive is only read, and the add-on is never
    installed into the user's Blender: the Blender step imports it from here."""
    archive = Path(archive)
    folder = data_dir() / "tools" / "daz_generations" / archive.stem
    if (folder / ADDON / "__init__.py").is_file():
        return folder
    try:
        with zipfile.ZipFile(archive) as z:
            names = z.namelist()
            if f"{ADDON}/__init__.py" not in names or f"{ADDON}/conversionDB.db" not in names:
                raise OperationError(f"{archive.name} is not the Daz Generations add-on (no {ADDON}/ with its database)")
            partial = folder.with_name(folder.name + ".partial")
            shutil.rmtree(partial, ignore_errors=True)
            z.extractall(partial, [n for n in names if n.startswith(f"{ADDON}/")])
    except zipfile.BadZipFile as exc:
        raise OperationError(f"cannot read {archive}: {exc}") from exc
    partial.rename(folder)
    return folder
