"""Build small but real asset files for tests: GLB/glTF/OBJ meshes, PNGs, Unreal packages."""

from __future__ import annotations

import io
import json
import struct
from pathlib import Path

import numpy as np
from PIL import Image

CUBE_POSITIONS = np.array([[x, y, z] for x in (-0.5, 0.5) for y in (-0.5, 0.5) for z in (-0.5, 0.5)],
                          dtype=np.float32)
CUBE_TRIANGLES = np.array([
    [0, 1, 3], [0, 3, 2], [4, 6, 7], [4, 7, 5], [0, 4, 5], [0, 5, 1],
    [2, 3, 7], [2, 7, 6], [0, 2, 6], [0, 6, 4], [1, 5, 7], [1, 7, 3],
], dtype=np.uint16)


def write(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def gltf_document(*, skinned: bool = False, translation=(0, 0, 0), scale: float = 1.0,
                  uri: str | None = None) -> tuple[dict, bytes]:
    positions = (CUBE_POSITIONS * scale).astype(np.float32).tobytes()
    indices = CUBE_TRIANGLES.tobytes()
    binary = positions + indices
    low, high = (CUBE_POSITIONS * scale).min(axis=0), (CUBE_POSITIONS * scale).max(axis=0)
    doc = {
        "asset": {"version": "2.0"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0, "translation": list(translation)}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1}]}],
        "buffers": [{"byteLength": len(binary), **({"uri": uri} if uri else {})}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": len(positions)},
            {"buffer": 0, "byteOffset": len(positions), "byteLength": len(indices)},
        ],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": 8, "type": "VEC3",
             "min": low.tolist(), "max": high.tolist()},
            {"bufferView": 1, "componentType": 5123, "count": 36, "type": "SCALAR"},
        ],
    }
    if skinned:
        doc["skins"] = [{"joints": [0]}]
    return doc, binary


def glb_bytes(**kwargs) -> bytes:
    doc, binary = gltf_document(**kwargs)
    js = json.dumps(doc).encode()
    js += b" " * (-len(js) % 4)
    binary += b"\0" * (-len(binary) % 4)
    body = struct.pack("<I4s", len(js), b"JSON") + js + struct.pack("<I4s", len(binary), b"BIN\0") + binary
    return struct.pack("<4sII", b"glTF", 2, 12 + len(body)) + body


def obj_bytes() -> bytes:
    lines = [f"v {x} {y} {z}" for x, y, z in CUBE_POSITIONS]
    # Quads with negative (relative) indices and v/vt/vn syntax.
    lines += ["f -8/1/1 -7/1/1 -5/1/1 -6/1/1", "f 5 6 8 7", "f 1 2 6 5"]
    return ("\n".join(lines) + "\n").encode()


def png_bytes(size=(48, 32), color=(30, 160, 90)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


def uasset_bytes(*, thumbnail: bool = True, name: str = "Asset") -> bytes:
    """An Unreal package: the tag, some header noise, and (optionally) an editor thumbnail."""
    header = b"\xc1\x83\x2a\x9e" + struct.pack("<i", -8) + b"\0" * 64 + name.encode() + b"\0" * 32
    thumb = png_bytes((32, 32), (200, 120, 40)) if thumbnail else b""
    return header + struct.pack("<ii", 32, 32) + thumb + b"\0" * 128


def unreal_project(root: Path) -> Path:
    write(root / "MyGame.uproject", json.dumps({"FileVersion": 3, "EngineAssociation": "5.4"}).encode())
    write(root / "Config" / "DefaultEngine.ini", b"[/Script/EngineSettings.GameMapsSettings]\n")
    write(root / "Content" / "MyGame" / "Maps" / "Main.umap", uasset_bytes(thumbnail=False, name="Main"))
    write(root / "Content" / "MyGame" / "BP_Player.uasset", uasset_bytes(name="BP_Player"))
    write(root / "Content" / "MegaPack" / "Meshes" / "SM_Rock.uasset", uasset_bytes(name="SM_Rock"))
    write(root / "Content" / "MegaPack" / "Textures" / "T_Rock_D.uasset", uasset_bytes(name="T_Rock_D"))
    write(root / "Content" / "MegaPack" / "Materials" / "M_Rock.uasset", uasset_bytes(thumbnail=False))
    write(root / "Content" / "Developers" / "me" / "Scratch.uasset", uasset_bytes(thumbnail=False))
    plugin = root / "Plugins" / "CoolTools"
    write(plugin / "CoolTools.uplugin", json.dumps({
        "FriendlyName": "Cool Tools", "VersionName": "2.1", "CreatedBy": "Jane Doe",
        "Description": "Handy robots", "Category": "Art"}).encode())
    write(plugin / "Content" / "SK_Robot.uasset", uasset_bytes(name="SK_Robot"))
    write(plugin / "Resources" / "Icon128.png", png_bytes((128, 128), (10, 10, 200)))
    write(plugin / "Source" / "CoolTools.cpp", b"// code\n")
    write(root / "Intermediate" / "Build" / "junk.obj", b"x" * 100)
    write(root / "Saved" / "Logs" / "MyGame.log", b"log\n")
    return root


def daz_connect_library(root: Path) -> Path:
    """A Daz Connect content directory holding the same product (SKU 12345) as the DIM fixture."""
    product = root / "data" / "cloud" / "1_12345"
    write(product / "People" / "Genesis 9" / "Characters" / "Marius" / "Marius Connect.duf",
          json.dumps({"scene": {"modifiers": [
              {"url": "/data/DAZ%203D/Genesis%209/Base/Morphs/DAZ%203D/Marius/FHMMarius.dsf#x"}]}}).encode())
    write(product / "data" / "DAZ 3D" / "Genesis 9" / "Base" / "Morphs" / "DAZ 3D" / "Marius" / "FCMMarius.dsf",
          json.dumps({"modifier_library": [{"morph": {"deltas": {"count": 1}}}]}).encode())
    write(root / "data" / "cloud" / "readme.txt", b"cloud\n")
    return root
