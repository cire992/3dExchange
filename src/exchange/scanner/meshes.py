"""Read mesh geometry from glTF/GLB and OBJ files, for statistics and preview rendering.

Readers return world-space positions and triangle indices. Anything they cannot decode (Draco or
quantized glTF, non-triangle primitives, malformed data) is skipped, never guessed at.
"""

from __future__ import annotations

import base64
import json
import math
import struct
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote

import numpy as np

from exchange.scanner import readonly

MAX_MESH_BYTES = 512 * 1024 * 1024

_COMPONENTS = {5121: np.uint8, 5123: np.uint16, 5125: np.uint32, 5126: np.float32}
_WIDTH = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


class MeshError(ValueError):
    pass


@dataclass
class MeshData:
    positions: np.ndarray  # (n, 3) float32, world space
    triangles: np.ndarray  # (m, 3) int64 indices into positions
    skinned: bool = False

    def stats(self) -> dict:
        if len(self.positions) == 0:
            return {"mesh_vertices": 0, "mesh_triangles": 0, "mesh_skinned": self.skinned}
        low, high = self.positions.min(axis=0), self.positions.max(axis=0)
        return {
            "mesh_vertices": int(len(self.positions)),
            "mesh_triangles": int(len(self.triangles)),
            "mesh_bounds": [[round(float(v), 6) for v in low], [round(float(v), 6) for v in high]],
            "mesh_size": round(float((high - low).max()), 6),
            "mesh_skinned": self.skinned,
        }


def read_mesh(path: Path) -> MeshData:
    ext = path.suffix.lower()
    data = readonly.read_bytes(path, MAX_MESH_BYTES)
    if data is None:
        raise MeshError("cannot read file")
    if ext == ".glb":
        return _read_glb(data, path)
    if ext == ".gltf":
        return _read_gltf(_json(data), None, path)
    if ext == ".obj":
        return _read_obj(data)
    raise MeshError(f"no reader for {ext}")


# glTF -------------------------------------------------------------------------------------------


def _json(data: bytes) -> dict:
    try:
        value = json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MeshError(f"bad JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise MeshError("glTF root is not an object")
    return value


def _read_glb(data: bytes, path: Path) -> MeshData:
    if len(data) < 20 or data[:4] != b"glTF":
        raise MeshError("not a GLB file")
    offset, doc, binary = 12, None, None
    while offset + 8 <= len(data):
        length, kind = struct.unpack_from("<I4s", data, offset)
        chunk = data[offset + 8 : offset + 8 + length]
        if kind == b"JSON":
            doc = _json(chunk)
        elif kind == b"BIN\x00" and binary is None:
            binary = chunk
        offset += 8 + length
    if doc is None:
        raise MeshError("GLB has no JSON chunk")
    return _read_gltf(doc, binary, path)


def _read_gltf(doc: dict, glb_binary: bytes | None, path: Path) -> MeshData:
    buffers: list[bytes | None] = []
    for i, buf in enumerate(doc.get("buffers", [])):
        uri = buf.get("uri")
        if uri is None:
            buffers.append(glb_binary if i == 0 else None)
        elif uri.startswith("data:"):
            try:
                buffers.append(base64.b64decode(uri.split(",", 1)[1]))
            except (IndexError, ValueError):
                buffers.append(None)
        else:  # an external .bin beside the file; never one outside its folder
            rel = unquote(uri).replace("\\", "/")
            if ".." in rel.split("/") or ":" in rel or rel.startswith("/"):
                buffers.append(None)
            else:
                buffers.append(readonly.read_bytes(path.parent / rel, MAX_MESH_BYTES))

    def accessor(index: int) -> np.ndarray | None:
        acc = doc["accessors"][index]
        if "sparse" in acc or acc.get("bufferView") is None:
            return None
        dtype = _COMPONENTS.get(acc.get("componentType"))
        width = _WIDTH.get(acc.get("type"))
        if dtype is None or width is None:
            return None
        view = doc["bufferViews"][acc["bufferView"]]
        data = buffers[view.get("buffer", 0)] if view.get("buffer", 0) < len(buffers) else None
        if data is None:
            return None
        item = np.dtype(dtype).itemsize * width
        stride = view.get("byteStride") or item
        start = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
        count = acc["count"]
        if count == 0:
            return np.zeros((0, width), dtype)
        if start + stride * (count - 1) + item > len(data):
            raise MeshError("accessor runs past its buffer")
        arr = np.ndarray((count, width), dtype=dtype, buffer=data, offset=start,
                         strides=(stride, np.dtype(dtype).itemsize))
        return np.array(arr)

    positions: list[np.ndarray] = []
    triangles: list[np.ndarray] = []
    base = 0
    meshes = doc.get("meshes", [])
    for matrix, mesh_index in _mesh_instances(doc):
        if mesh_index >= len(meshes):
            continue
        for prim in meshes[mesh_index].get("primitives", []):
            if prim.get("mode", 4) != 4 or "extensions" in prim:
                continue  # only plain triangle lists; Draco etc. are not decoded
            pos_index = prim.get("attributes", {}).get("POSITION")
            if pos_index is None:
                continue
            pos = accessor(pos_index)
            if pos is None or pos.dtype != np.float32 or pos.shape[1] != 3:
                continue
            if prim.get("indices") is not None:
                idx = accessor(prim["indices"])
                if idx is None:
                    continue
                idx = idx.reshape(-1).astype(np.int64)
            else:
                idx = np.arange(len(pos), dtype=np.int64)
            idx = idx[: len(idx) - len(idx) % 3].reshape(-1, 3)
            if len(idx) and (idx.max() >= len(pos) or idx.min() < 0):
                raise MeshError("index out of range")
            world = pos.astype(np.float64) @ matrix[:3, :3].T + matrix[:3, 3]
            positions.append(world.astype(np.float32))
            triangles.append(idx + base)
            base += len(pos)
    if not positions:
        raise MeshError("no decodable triangle geometry")
    return MeshData(np.concatenate(positions), np.concatenate(triangles), bool(doc.get("skins")))


def _mesh_instances(doc: dict) -> list[tuple[np.ndarray, int]]:
    nodes = doc.get("nodes", [])
    scenes = doc.get("scenes", [])
    if scenes:
        roots = scenes[doc.get("scene", 0) if doc.get("scene", 0) < len(scenes) else 0].get("nodes", [])
    else:
        children = {c for n in nodes for c in n.get("children", [])}
        roots = [i for i in range(len(nodes)) if i not in children]
    out: list[tuple[np.ndarray, int]] = []
    stack = [(i, np.eye(4)) for i in roots]
    seen: set[int] = set()
    while stack:
        index, parent = stack.pop()
        if index in seen or index >= len(nodes):
            continue  # malformed graphs can loop
        seen.add(index)
        node = nodes[index]
        world = parent @ _local_matrix(node)
        if "mesh" in node:
            out.append((world, node["mesh"]))
        stack.extend((c, world) for c in node.get("children", []))
    if not out and not nodes:  # meshes without a node graph
        out = [(np.eye(4), i) for i in range(len(doc.get("meshes", [])))]
    return out


def _local_matrix(node: dict) -> np.ndarray:
    if "matrix" in node and len(node["matrix"]) == 16:
        return np.array(node["matrix"], dtype=np.float64).reshape(4, 4).T  # column-major
    t = np.array(node.get("translation", [0, 0, 0]), dtype=np.float64)
    x, y, z, w = node.get("rotation", [0, 0, 0, 1])
    r = np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])
    s = np.array(node.get("scale", [1, 1, 1]), dtype=np.float64)
    m = np.eye(4)
    m[:3, :3] = r * s
    m[:3, 3] = t
    return m


# OBJ --------------------------------------------------------------------------------------------


def _read_obj(data: bytes) -> MeshData:
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int]] = []
    for raw in data.splitlines():
        if raw.startswith(b"v "):
            parts = raw.split()
            try:
                vertices.append((float(parts[1]), float(parts[2]), float(parts[3])))
            except (IndexError, ValueError):
                raise MeshError("bad vertex line") from None
        elif raw.startswith(b"f "):
            try:
                corners = [int(p.split(b"/", 1)[0]) for p in raw.split()[1:]]
            except ValueError:
                raise MeshError("bad face line") from None
            n = len(vertices)
            corners = [c - 1 if c > 0 else n + c for c in corners]
            faces.extend((corners[0], corners[i], corners[i + 1]) for i in range(1, len(corners) - 1))
    if not vertices:
        raise MeshError("no vertices")
    tris = np.array(faces, dtype=np.int64).reshape(-1, 3)
    if len(tris) and (tris.max() >= len(vertices) or tris.min() < 0):
        raise MeshError("face index out of range")
    return MeshData(np.array(vertices, dtype=np.float32), tris, skinned=False)


def finite(stats: dict) -> bool:
    return all(math.isfinite(v) for pair in stats.get("mesh_bounds", []) for v in pair)
