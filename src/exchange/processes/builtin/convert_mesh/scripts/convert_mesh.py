"""Runs inside Blender (2.83 and newer): import one mesh file, export it in another format."""

import os

import bpy


def _op(new, old):
    """The importer or exporter: Blender 3.x/4.x moved several into wm.*."""
    module, name = new
    if hasattr(getattr(bpy.ops, module), name):
        return getattr(getattr(bpy.ops, module), name)
    module, name = old
    return getattr(getattr(bpy.ops, module), name)


def _import(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".fbx":
        bpy.ops.import_scene.fbx(filepath=path)
    elif ext == ".obj":
        _op(("wm", "obj_import"), ("import_scene", "obj"))(filepath=path)
    elif ext in (".glb", ".gltf"):
        bpy.ops.import_scene.gltf(filepath=path)
    elif ext == ".dae":
        bpy.ops.wm.collada_import(filepath=path)
    elif ext == ".stl":
        _op(("wm", "stl_import"), ("import_mesh", "stl"))(filepath=path)
    elif ext == ".ply":
        _op(("wm", "ply_import"), ("import_mesh", "ply"))(filepath=path)
    else:
        raise ValueError(f"cannot import {ext} files")


def _export(path, fmt):
    if fmt == "glb":
        bpy.ops.export_scene.gltf(filepath=path, export_format="GLB")
    elif fmt == "gltf":
        bpy.ops.export_scene.gltf(filepath=path, export_format="GLTF_SEPARATE")
    elif fmt == "fbx":
        bpy.ops.export_scene.fbx(filepath=path, path_mode="COPY", embed_textures=True)
    elif fmt == "obj":
        _op(("wm", "obj_export"), ("export_scene", "obj"))(filepath=path, path_mode="COPY")
    else:
        raise ValueError(f"cannot export {fmt}")


def _unpack_images(folder):
    """Importers (glTF) pack textures into the file; formats that keep textures beside the mesh
    (OBJ, glTF with separate files) need them on disk, so write each one's original bytes there."""
    for image in bpy.data.images:
        if image.packed_file is None:
            continue
        name = os.path.basename(bpy.path.abspath(image.filepath)) or f"{image.name}.png"
        path = os.path.join(folder, name)
        with open(path, "wb") as f:
            f.write(image.packed_file.data)
        image.filepath = path
        image.unpack(method="REMOVE")


def run(args):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    before = set(os.listdir(os.path.dirname(args["target"]))) if os.path.isdir(os.path.dirname(args["target"])) else set()
    _import(args["source"])
    objects = [o for o in bpy.context.scene.objects]
    if not objects:
        raise ValueError("the file has no objects")
    scale = float(args.get("scale", 1.0))
    if scale != 1.0:
        for obj in objects:
            if obj.parent is None:
                obj.scale = [s * scale for s in obj.scale]
    os.makedirs(os.path.dirname(args["target"]), exist_ok=True)
    if args["format"] in ("obj", "gltf"):
        _unpack_images(os.path.dirname(args["target"]))
    _export(args["target"], args["format"])
    folder = os.path.dirname(args["target"])
    files = [os.path.join(folder, f) for f in sorted(os.listdir(folder)) if f not in before]
    return {"files": files, "objects": len(objects)}
