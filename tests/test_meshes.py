import io
import json

import numpy as np
import pytest
from PIL import Image

from builders import glb_bytes, gltf_document, obj_bytes, write
from exchange.scanner.formats import read_daz_file, uasset_thumbnail
from exchange.scanner.meshes import MeshError, read_mesh
from exchange.scanner.thumbnails import render


def test_glb_with_node_transform(tmp_path):
    mesh = read_mesh(write(tmp_path / "cube.glb", glb_bytes(translation=(10, 0, 0), scale=2.0)))
    stats = mesh.stats()
    assert stats["mesh_vertices"] == 8 and stats["mesh_triangles"] == 12
    assert stats["mesh_bounds"] == [[9.0, -1.0, -1.0], [11.0, 1.0, 1.0]]
    assert stats["mesh_size"] == 2.0
    assert stats["mesh_skinned"] is False
    assert read_mesh(write(tmp_path / "rig.glb", glb_bytes(skinned=True))).skinned


def test_gltf_with_external_buffer(tmp_path):
    doc, binary = gltf_document(uri="cube%20data.bin")
    write(tmp_path / "cube data.bin", binary)
    mesh = read_mesh(write(tmp_path / "cube.gltf", json.dumps(doc).encode()))
    assert len(mesh.triangles) == 12


def test_gltf_buffer_outside_its_folder_is_not_read(tmp_path):
    doc, binary = gltf_document(uri="../secret.bin")
    write(tmp_path / "secret.bin", binary)
    with pytest.raises(MeshError):
        read_mesh(write(tmp_path / "sub" / "cube.gltf", json.dumps(doc).encode()))


def test_obj_quads_and_negative_indices(tmp_path):
    mesh = read_mesh(write(tmp_path / "cube.obj", obj_bytes()))
    assert len(mesh.positions) == 8
    assert len(mesh.triangles) == 6
    assert mesh.triangles.max() < 8


@pytest.mark.parametrize("data", [b"", b"glTF\x02\0\0\0", b"not json", b"v 1 2\n"])
def test_malformed_meshes_raise(tmp_path, data):
    for ext in (".glb", ".gltf", ".obj"):
        with pytest.raises(MeshError):
            read_mesh(write(tmp_path / f"bad{ext}", data))


def test_render_draws_something(tmp_path):
    img = render(read_mesh(write(tmp_path / "cube.glb", glb_bytes())))
    assert img.size == (256, 256) and img.mode == "RGBA"
    alpha = np.asarray(img)[:, :, 3]
    assert 0.1 < (alpha > 0).mean() < 0.9  # the cube covers part of the frame


def test_daz_references_and_stats(tmp_path):
    info = read_daz_file(json.dumps({
        "modifier_library": [{"morph": {"deltas": {"count": 5}}}],
        "geometry_library": [{"vertices": {"count": 4}, "polylist": {"count": 1}}],
        "scene": {"a": "/data/DAZ%203D/x.dsf#node", "b": ["#local", "/Runtime/T/y.JPG", "plain text"]},
    }).encode())
    assert sorted(info.references) == ["Runtime/T/y.JPG", "data/DAZ 3D/x.dsf"]
    assert info.stats == {"mesh_vertices": 4, "mesh_polygons": 1, "morph_deltas": 5}
    assert read_daz_file(b"\x1f\x8bnot gzip") is None
    assert read_daz_file(b"[1, 2]") is None


def test_uasset_thumbnail():
    from builders import uasset_bytes

    png = uasset_thumbnail(uasset_bytes())
    assert png is not None and Image.open(io.BytesIO(png)).size == (32, 32)
    assert uasset_thumbnail(uasset_bytes(thumbnail=False)) is None
    assert uasset_thumbnail(b"\x89PNG not a package") is None
