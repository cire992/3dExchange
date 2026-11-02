"""Step 2 of daz_character_to_g8f, inside Blender: Daz Generations moves the stock Genesis 8 Female
mesh to the character's Genesis 9 shape.

args: ``addon`` (the folder holding the extracted ``Daz_Generations`` package), ``shape`` (the
character, from step 1), ``base`` (the stock G8F), ``out`` (where to write the result) and ``method``
(``v3``, ``v2`` or ``v1``, as the add-on's panel calls its conversions).

The meshes are built straight from the OBJ files, keeping their vertex order and Daz's axes (Y up,
centimetres), which is the frame the add-on's database is in. The result is written with the stock
mesh's faces, so Daz Studio's Morph Loader can read it as a shape of Genesis 8 Female.
"""

import sys
import time

import bpy

METHODS = {"v3": {}, "v2": {"bool_do_avrg": False}, "v1": {"bool_body_regions": False, "bool_do_avrg": False}}


def read_obj(path):
    vertices, faces, face_lines = [], [], []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.startswith("v "):
                vertices.append(tuple(float(x) for x in line.split()[1:4]))
            elif line.startswith("f "):
                faces.append([int(x.split("/")[0]) - 1 for x in line.split()[1:]])
                face_lines.append(line.rstrip("\n"))
    return vertices, faces, face_lines


def mesh_object(name, path):
    vertices, faces, face_lines = read_obj(path)
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices, [], faces)
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj, face_lines


def run(args):
    if args.get("method", "v3") not in METHODS:
        raise ValueError(f"unknown method {args['method']!r} (one of {', '.join(METHODS)})")
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sys.path.insert(0, args["addon"])
    import Daz_Generations
    from Daz_Generations import dazgen_utilities
    from Daz_Generations.ConversionObject import ConversionObj

    Daz_Generations.register()
    primary, _ = mesh_object("Character", args["shape"])
    secondary, face_lines = mesh_object("Genesis8Female", args["base"])
    generations = (dazgen_utilities.get_figure_gen_from_vert_count(primary),
                   dazgen_utilities.get_figure_gen_from_vert_count(secondary))
    if generations != ("G9B", "G8F"):
        raise ValueError(f"expected a Genesis 9 shape and the Genesis 8 Female mesh, got {generations} "
                         f"({len(primary.data.vertices)} and {len(secondary.data.vertices)} vertices)")
    for obj in (primary, secondary):
        obj.select_set(True)
    bpy.context.view_layer.objects.active = secondary
    started = time.time()
    dazgen_utilities.start_movement(ConversionObj(primary_obj=primary, secondary_obj=secondary,
                                                  **METHODS[args.get("method", "v3")]))
    made = [o for o in bpy.data.objects if o.name.endswith("SCALED")]
    if len(made) != 1:
        raise RuntimeError(f"Daz Generations made {len(made)} meshes, not one")
    with open(args["out"], "w", encoding="utf-8") as f:
        f.writelines(f"v {v.co.x} {v.co.y} {v.co.z}\n" for v in made[0].data.vertices)
        f.write("\n".join(face_lines) + "\n")
    return {"vertices": len(made[0].data.vertices), "seconds": round(time.time() - started, 1),
            "rescale": bpy.context.scene.dazgen_tool.Rescale}
