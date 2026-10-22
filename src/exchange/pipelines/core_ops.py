"""Core operations shipped with Exchange: copy, select, resize and convert images, rename, pack.

Pipelines name them ``core.<name>``. None of them touch the source files: they read from the
input artifact and write new files into their own work folder (copy passes files through and
lets the requisition writer copy them to the endpoint).
"""

from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

from exchange.globs import any_match
from exchange.pipelines.operations import ANY, Artifact, Context, OperationError, operation

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".tga", ".bmp", ".tif", ".tiff", ".dds", ".webp")
_FORMATS = {"png": ("PNG", ".png"), "jpg": ("JPEG", ".jpg"), "jpeg": ("JPEG", ".jpg"), "tga": ("TGA", ".tga"),
            "bmp": ("BMP", ".bmp"), "dds": ("DDS", ".dds"), "tif": ("TIFF", ".tif"), "webp": ("WEBP", ".webp")}


@operation("copy", inputs=(ANY,), output=ANY)
def copy(ctx: Context, files: Artifact) -> Artifact:
    """Pass files through unchanged (the writer copies them to the endpoint)."""
    ctx.log(f"{len(files.files)} files")
    return files


@operation("select", inputs=(ANY,), output=ANY)
def select(ctx: Context, files: Artifact, include: str = "**", exclude: str = "", type: str = "") -> Artifact:
    """Keep the files matching ``include`` (globs separated by ";") and not ``exclude``."""
    keep = [rel for rel in files.files
            if any_match(_globs(include), rel) and not (exclude and any_match(_globs(exclude), rel))]
    ctx.log(f"kept {len(keep)} of {len(files.files)} files")
    return files.derive(files.root, keep, type=type or None)


def _globs(text: str) -> tuple[str, ...]:
    return tuple(g.strip() for g in text.split(";") if g.strip())


def _open_image(path: Path):
    from PIL import Image

    try:
        image = Image.open(path)
        image.load()
        return image
    except Exception as exc:  # Pillow raises many kinds; the item fails with the reason
        raise OperationError(f"cannot read image {path.name}: {exc}") from exc


@operation("resize_images", inputs=(ANY,), output=ANY)
def resize_images(ctx: Context, images: Artifact, size: int = 1024, only_larger: bool = True) -> Artifact:
    """Scale the images among the files so their longest side is ``size`` pixels (keeping the
    aspect ratio); other files pass through."""
    from PIL import Image

    if size < 1:
        raise OperationError("size must be at least 1")
    out = ctx.new_dir("resized")
    for path, rel in zip(images.paths(), images.files):
        target = out.joinpath(*rel.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix.lower() not in IMAGE_EXTS:
            shutil.copy2(path, target)
            continue
        image = _open_image(path)
        longest = max(image.size)
        if longest > size or not only_larger:
            scale = size / longest
            image = image.resize((max(1, round(image.width * scale)), max(1, round(image.height * scale))),
                                 Image.Resampling.LANCZOS)
        image.save(target, format=_FORMATS.get(path.suffix.lower().lstrip("."), (None,))[0])
        ctx.log(f"{rel}: {image.width}×{image.height}")
    return images.derive(out, images.files)


@operation("convert_images", inputs=(ANY,), output=ANY)
def convert_images(ctx: Context, images: Artifact, format: str = "png", quality: int = 90) -> Artifact:
    """Convert the images among the files to another format (png, jpg, tga, bmp, dds, tif, webp);
    other files pass through. Files that refer to the images by name (materials, OBJ .mtl) are
    not rewritten."""
    wanted = _FORMATS.get(format.lower())
    if wanted is None:
        raise OperationError(f"unknown image format {format!r} (one of {', '.join(sorted(_FORMATS))})")
    pil_format, ext = wanted
    out = ctx.new_dir("converted")
    files = []
    for path, rel in zip(images.paths(), images.files):
        if path.suffix.lower() not in IMAGE_EXTS:
            target = out.joinpath(*rel.split("/"))
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            files.append(rel)
            continue
        image = _open_image(path)
        if pil_format == "JPEG" and image.mode not in ("RGB", "L"):
            image = image.convert("RGB")
        new_rel = rel.rsplit(".", 1)[0] + ext
        target = out.joinpath(*new_rel.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        image.save(target, format=pil_format, **({"quality": quality} if pil_format in ("JPEG", "WEBP") else {}))
        files.append(new_rel)
    ctx.log(f"converted the images to {pil_format}")
    return images.derive(out, files)


@operation("rename", inputs=(ANY,), output=ANY)
def rename(ctx: Context, files: Artifact, pattern: str = "{stem}{ext}") -> Artifact:
    """Rename files: ``{stem}``, ``{ext}``, ``{name}`` (the asset's name), ``{index}``."""
    out = ctx.new_dir("renamed")
    renamed = []
    for index, (path, rel) in enumerate(zip(files.paths(), files.files), start=1):
        folder, _, filename = rel.rpartition("/")
        stem, dot, ext = filename.rpartition(".")
        stem, ext = (stem, dot + ext) if dot else (filename, "")
        try:
            new_name = pattern.format(stem=stem, ext=ext, index=index, name=ctx.dossier.get("name", stem))
        except (KeyError, IndexError, ValueError) as exc:
            raise OperationError(f"bad rename pattern {pattern!r}: {exc}") from exc
        if not new_name or "/" in new_name or "\\" in new_name:
            raise OperationError(f"rename pattern {pattern!r} gives a bad file name {new_name!r}")
        new_rel = f"{folder}/{new_name}" if folder else new_name
        target = out.joinpath(*new_rel.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        renamed.append(new_rel)
    if len(set(renamed)) != len(renamed):
        raise OperationError(f"rename pattern {pattern!r} gives two files the same name")
    return files.derive(out, renamed)


@operation("pack", inputs=(ANY,), output=ANY)
def pack(ctx: Context, files: Artifact, name: str = "{name}.zip") -> Artifact:
    """Pack all files into one zip archive, keeping their folders."""
    archive_name = name.format(name=ctx.dossier.get("name", "files"))
    out = ctx.new_dir("packed")
    with zipfile.ZipFile(out / archive_name, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, rel in zip(files.paths(), files.files):
            archive.write(path, rel)
    ctx.log(f"packed {len(files.files)} files into {archive_name}")
    return files.derive(out, [archive_name], type=ANY)


CORE_OPERATIONS = {f.__exchange_operation__.name: f.__exchange_operation__
                   for f in (copy, select, resize_images, convert_images, rename, pack)}
