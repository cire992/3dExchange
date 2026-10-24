"""Mesh conversion in Blender."""

from pathlib import Path

from exchange.processes.operations import OperationError, operation

MESH_EXTS = (".fbx", ".obj", ".glb", ".gltf", ".dae", ".stl", ".ply")
SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "convert_mesh.py"


@operation("convert", inputs=("Files",), output="Files", app="blender")
def convert(ctx, files, format="glb", scale=1.0):
    """Import the asset's mesh into Blender and export it as ``format``."""
    meshes = [(path, rel) for path, rel in zip(files.paths(), files.files) if path.suffix.lower() in MESH_EXTS]
    if not meshes:
        raise OperationError(f"no mesh file to convert (one of {', '.join(MESH_EXTS)})")
    source, rel = meshes[0]
    out = ctx.new_dir("converted")
    target = out.joinpath(*(rel.rsplit(".", 1)[0] + "." + format).split("/"))
    result = ctx.bridge("blender").run(SCRIPT, {"source": str(source), "target": str(target),
                                                "format": format, "scale": scale})
    written = [Path(p) for p in result.get("files", []) if Path(p).is_file()]
    if not written:
        raise OperationError("Blender exported nothing")
    ctx.log(f"{source.name} → {', '.join(p.name for p in written)} ({result.get('objects', '?')} objects)")
    return files.derive(out, [p.relative_to(out).as_posix() for p in written])
