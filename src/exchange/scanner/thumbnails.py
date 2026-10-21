"""Make 256-pixel PNG thumbnails: from images (any format Pillow reads, DDS included) or by
rendering a mesh with a small flat-shaded software renderer.

Thumbnails go into a cache folder beside the library database, never into a scanned folder.
"""

from __future__ import annotations

import io
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, UnidentifiedImageError

from exchange.paths import os_path
from exchange.scanner.meshes import MeshData

SIZE = 256
MAX_RENDER_TRIANGLES = 150_000
IMAGE_EXTS = frozenset({".png", ".jpg", ".jpeg", ".tga", ".bmp", ".dds", ".tif", ".tiff", ".webp"})
_BASE_COLOR = np.array([178, 186, 198], dtype=np.float64)
_LIGHT = np.array([-0.4, 0.7, 0.6]) / np.linalg.norm([-0.4, 0.7, 0.6])

Image.MAX_IMAGE_PIXELS = 300_000_000  # large textures are normal; still refuse absurd ones


class ThumbnailError(ValueError):
    pass


def from_image_bytes(data: bytes) -> Image.Image:
    try:
        with Image.open(io.BytesIO(data)) as img:
            img.load()
            return _fit(img)
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise ThumbnailError(f"cannot decode image: {exc}") from exc


def _fit(img: Image.Image) -> Image.Image:
    img = img.convert("RGBA")
    img.thumbnail((SIZE, SIZE), Image.Resampling.LANCZOS)
    return img


def render(mesh: MeshData) -> Image.Image:
    """Flat-shaded three-quarter view, painter's algorithm, on a transparent background."""
    pos = mesh.positions.astype(np.float64)
    tris = mesh.triangles
    if len(pos) == 0 or len(tris) == 0:
        raise ThumbnailError("mesh has no triangles")
    if len(tris) > MAX_RENDER_TRIANGLES:
        tris = tris[np.linspace(0, len(tris) - 1, MAX_RENDER_TRIANGLES).astype(np.int64)]
    if not np.isfinite(pos).all():
        raise ThumbnailError("mesh has non-finite coordinates")

    yaw, pitch = math.radians(35), math.radians(-25)
    ry = np.array([[math.cos(yaw), 0, math.sin(yaw)], [0, 1, 0], [-math.sin(yaw), 0, math.cos(yaw)]])
    rx = np.array([[1, 0, 0], [0, math.cos(pitch), -math.sin(pitch)], [0, math.sin(pitch), math.cos(pitch)]])
    center = (pos.min(axis=0) + pos.max(axis=0)) / 2
    view = (pos - center) @ (rx @ ry).T
    extent = np.abs(view[:, :2]).max()
    if extent == 0:
        raise ThumbnailError("mesh is degenerate")
    canvas = SIZE * 2  # render large, downsample for anti-aliasing
    scale = canvas * 0.45 / extent
    screen = np.empty((len(view), 2))
    screen[:, 0] = canvas / 2 + view[:, 0] * scale
    screen[:, 1] = canvas / 2 - view[:, 1] * scale

    a, b, c = view[tris[:, 0]], view[tris[:, 1]], view[tris[:, 2]]
    normals = np.cross(b - a, c - a)
    length = np.linalg.norm(normals, axis=1)
    keep = length > 0
    tris, normals, length = tris[keep], normals[keep], length[keep]
    shade = 0.3 + 0.7 * np.abs(normals @ _LIGHT) / length  # double-sided
    depth = view[tris].mean(axis=1)[:, 2]
    order = np.argsort(depth)  # far (negative z) first

    img = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    colors = np.clip(_BASE_COLOR * shade[:, None], 0, 255).astype(np.uint8)
    pts = screen[tris]
    for i in order:
        p = pts[i]
        col = tuple(int(v) for v in colors[i]) + (255,)
        draw.polygon([(p[0, 0], p[0, 1]), (p[1, 0], p[1, 1]), (p[2, 0], p[2, 1])], fill=col)
    return img.resize((SIZE, SIZE), Image.Resampling.LANCZOS)


def save(img: Image.Image, cache_dir: Path, key: str) -> str:
    """Write a thumbnail into the cache; returns its path relative to ``cache_dir``."""
    rel = f"{key[:2]}/{key}.png"
    path = cache_dir / key[:2] / f"{key}.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(os_path(path.resolve()), "PNG", optimize=True)
    return rel
