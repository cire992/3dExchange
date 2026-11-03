"""Step 3 of daz_character_to_g8f, inside Blender, with the Texture Converter G9 → G8F template open:
the character's skin maps baked from Genesis 9's UDIM tiles onto Genesis 8 Female's.

args: ``channels`` (one entry per channel: ``name`` for the files, ``data`` when the map isn't a colour,
``format`` (``PNG`` or ``JPEG``), ``size`` (the largest a map may be, 0 for no limit; a map is
as large as its largest source) and ``sources``: for each of
the template's G9 surfaces, a map's path or a flat colour), ``out`` (the folder the maps are written to),
``prefix`` (the files' name before the channel), ``samples``.

The template's G9 and G8F are fitted to each other once, so the bake doesn't need the character's shape:
Cycles bakes the G9's colour onto the G8F, from the selection to the active object through the cage, as
the template's guide does by hand. A data map (roughness, a normal map) is read and written without
colour conversion, so its values pass through unchanged.
"""

import time

import bpy

SURFACES = ("Head", "Body", "Legs", "Arms", "Nails")
TILES = (1001, 1002, 1003, 1004)


def template_objects():
    objects = bpy.data.objects
    names = ("G9F", "G8F", "Cage_G8F")
    materials = [f"{s}_G9" for s in SURFACES]
    if any(n not in objects for n in names) or any(m not in bpy.data.materials for m in materials):
        raise ValueError("this isn't the Texture Converter G9 to G8F template (no G9F, G8F and Cage_G8F "
                         f"with the materials {', '.join(materials)})")
    return objects["G9F"], objects["G8F"], objects["Cage_G8F"]


def image_node(material):
    nodes = [n for n in material.node_tree.nodes if n.type == "TEX_IMAGE"]
    if len(nodes) != 1:
        raise ValueError(f"the template's {material.name} has {len(nodes)} image nodes, not one")
    return nodes[0]


def flat(name, color, data):
    image = bpy.data.images.new(name, 4, 4, alpha=False, is_data=data)
    image.generated_color = (*color, 1.0)
    return image


def source_image(channel, surface, source):
    if isinstance(source, list):
        return flat(f"{channel['name']}_{surface}_flat", source, channel["data"])
    image = bpy.data.images.load(source, check_existing=True)
    image.colorspace_settings.name = "Non-Color" if channel["data"] else "sRGB"
    return image


def use_gpu():
    """The fastest Cycles device there is; factory settings start on the CPU."""
    prefs = bpy.context.preferences.addons["cycles"].preferences
    for kind in ("OPTIX", "CUDA", "HIP", "ONEAPI", "METAL"):
        try:
            prefs.compute_device_type = kind
        except TypeError:
            continue
        devices = [d for d in prefs.get_devices_for_type(kind) if d.type != "CPU"]
        if devices:
            for d in prefs.devices:
                d.use = d in devices
            bpy.context.scene.cycles.device = "GPU"
            return f"{kind} ({', '.join(d.name for d in devices)})"
    bpy.context.scene.cycles.device = "CPU"
    return "CPU"


def bake(channel, g9, g8, cage, out, prefix, samples):
    images = {s: source_image(channel, s, channel["sources"][s]) for s in SURFACES}
    for surface, image in images.items():
        image_node(bpy.data.materials[f"{surface}_G9"]).image = image
    size = max(max(i.size) for i in images.values())
    size = min(size, channel["size"]) if channel["size"] else size
    target = bpy.data.images.new(f"{prefix}_{channel['name']}", size, size, alpha=False, tiled=True,
                                 is_data=channel["data"])
    target.colorspace_settings.name = "Non-Color" if channel["data"] else "sRGB"
    for tile in TILES[1:]:
        target.tiles.new(tile_number=tile)
    with bpy.context.temp_override(edit_image=target):
        for tile in target.tiles:
            target.tiles.active = tile
            bpy.ops.image.tile_fill(color=(0, 0, 0, 1), width=size, height=size, float=False, alpha=False)
    material = g8.data.materials[0]
    node = image_node(material)
    node.image = target
    material.node_tree.nodes.active = node

    bpy.ops.object.select_all(action="DESELECT")
    g9.select_set(True)
    g8.select_set(True)
    bpy.context.view_layer.objects.active = g8
    scene = bpy.context.scene
    scene.cycles.samples = samples
    started = time.time()
    bpy.ops.object.bake(type="DIFFUSE", pass_filter={"COLOR"}, use_selected_to_active=True, use_cage=True,
                        cage_object=cage.name, margin=16, target="IMAGE_TEXTURES", use_clear=False)
    seconds = time.time() - started

    ext = "png" if channel["format"] == "PNG" else "jpg"
    target.filepath_raw = f"{out}/{prefix}_{channel['name']}_<UDIM>.{ext}"
    target.file_format = channel["format"]
    scene.render.image_settings.quality = 95
    target.save(quality=95)
    for image in images.values():
        if image.users == 0 or image.name.endswith("_flat"):
            bpy.data.images.remove(image)
    return {"name": channel["name"], "size": size, "seconds": round(seconds, 1),
            "files": [f"{prefix}_{channel['name']}_{t}.{ext}" for t in TILES]}


def run(args):
    g9, g8, cage = template_objects()
    for obj in (g9, g8, cage):
        obj.hide_set(False)
        obj.hide_render = False
    device = use_gpu()
    baked = [bake(c, g9, g8, cage, args["out"], args["prefix"], args.get("samples", 16)) for c in args["channels"]]
    return {"device": device, "channels": baked}
