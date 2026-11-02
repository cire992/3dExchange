# R7: the G8 path, skin, and the first proof

Approved by Luke on 2026-11-02, with every recommended answer. Part of [RESTART_PLAN.md](RESTART_PLAN.md); read [VISION.md](VISION.md) first. R6 built the shape: a Genesis 9 character claimed `as g8f_character` walks to a G8F morph. R7 adds the skin and a character preset, so what lands is a usable Genesis 8 Female character, then runs the first proof end to end in the Workspace.

## The goal

After R7, walking a G9 character's claim as `g8f_character` installs three things into Exchange Conversions:

- the morph (R6);
- the character's skin, baked onto G8F's four maps;
- a character preset. Double-clicked with your Genesis 8 Female selected, it dials the morph to 100% and applies the skin.

**The proof:** a G9 character arrives in a watched library while Exchange runs. In the Workspace it is noticed (New), claimed, walked and Installed, with no step outside Exchange. Then you load the preset in Daz Studio and judge it by eye.

## The path

```
 1. Daz: load the character ─► 2. Blender: shape ─► 3. Blender: skin ─► 4. Daz: build ─► 5. rewrite ─► 6. install
    write its shape (OBJ),        (Daz Generations,    (Texture Converter   the morph,      the paths
    the stock G8F's, and          R6)                  G9 → G8F: one bake   apply the       to the
    its skin: which map is                             per channel onto     skin, save      regular G8F
    on which surface (new)                             G8F's 4 tiles; new)  the preset      and the
                                                                            (extended)      textures
```

The same package, `daz_character_to_g8f`, gains one step and extends three:

| Step | Runs in | What changes | Known? |
|---|---|---|---|
| 1. Export | Daz Studio | It also writes `skin.json`: for each skin surface the character sets, each channel's image and value as Daz loaded them (so presets the `.duf` applies count). | Reading channels: yes (4d spike). **Layered images** (a makeup or tattoo layered over the base map): never tried, see decision 3 |
| 3. Bake | Blender, headless | New. It opens the template, puts each channel's five maps (Head, Body, Legs, Arms, Nails) on the G9 surfaces, and bakes onto G8F's tiles 1001-1004. That's one bake per channel. | A headless 1024 px bake worked on 2026-10-22 (9.4 s). 4096 px, and data maps kept linear: **not yet measured** |
| 4. Build | Daz Studio | After the morph, it sets G8F's skin surfaces to PBRSkin with the G9 values and the baked maps, then saves a character preset. | Saving a character preset from a script: **never done**. The fallback is to write the preset's DSON in Python |
| 5. Rewrite | Python | It also points the preset's image paths, saved as work-folder paths, at `/Runtime/Textures/Exchange/<character>/`. | `rewrite_daz_paths` already does this for `/data/` paths |

**What the template is** (read on 2026-11-02, `Texture_Converter_G9 to G8F_V2.02.blend`):

- **The meshes:** a subdivided G9 (`G9F`, five materials on UDIM tiles 1001-1005: Head, Body, Legs, Arms, Nails), a G8F already fitted to it (`G8F`, one material on tiles 1001-1004), and a cage.
- **The bake:** Cycles, *Diffuse* with only the colour pass, from the selection to the active object.

It's shape-independent: the meshes are fitted once, so any G9 skin bakes onto G8F without the character's shape.

**The guide's hand steps** are on its pages 4-5. Nail and genital overlays are blended in by hand in an image editor, and minor touch-ups are needed under the fingernails.

## What's already there

| R7 needs | Already built | Missing |
|---|---|---|
| The template | Tool prerequisites; `ctx.tool()`; extracting an archive once into the data folder (`addon_folder`) | A tool for the template (decision 6) |
| Daz reading and setting materials | The bridge, headless | The skin export, the material set-up and the preset save (steps 1 and 4) |
| Installing the textures | The runner writes the step's output into the endpoint | Nothing: the output just has more files |
| Noticing a new character | The watcher, rescans, the Workspace's New view (R4c, R5) | Nothing. R6c saw a rough edge: *Rescan changed (1)* after a walk (decision 11) |
| Telling you to add Exchange Conversions to Daz | The last log line (R6 decision 7) | The one-time notice R6 put off to R7 (decision 10) |

## How it's built

By hand, one PR per chunk, as in R6. Each Daz and Blender step is built by running it for real on scratch data first.

1. **R7a: the bake (core).**
   - Step 1's `skin.json`.
   - Step 3 and the template's tool.
   - Tests with stand-in bridges, as R6b's.
   - Run for real on Luanne, measuring each channel's time and size.
   - This plan.
2. **R7b: the skin on G8F and the preset (core).** Step 4's material set-up and preset save, and step 5's image paths. A real run on Luanne, then you load the preset once on your G8F, before the Workspace work starts.
3. **R7c: the Workspace for the proof (core and shell).**
   - The core: the content-directory notice's field in the API, and the watcher fix.
   - The shell: the notice, and a claim's detail showing the process's name.
4. **R7d, by hand: the proof.** On a fresh sample library, as decision 12 describes. Written up in `PROGRESS.md` with every step's time. It closes R7 and the restart's roadmap.

## Decisions (each with a recommended answer)

1. **One process, or a second one for the skin?** *Recommended:* the same `daz_character_to_g8f`, so one claim lands the morph, the skin and the preset. `g8f_character` means a character you can use, and a shape alone isn't one (RESTART_PLAN's decision 5). Walking an R6 claim again overwrites its morph and adds the rest.

2. **Which parts of the character?** *Recommended:* the skin surfaces the character's `.duf` sets on Genesis 9 (Head, Body, Legs, Arms, Fingernails, Toenails). They land on G8F's Face, Lips, Ears, Eye Socket, Torso, Legs, Arms and the nails.
   - **What G8F keeps as stock:** eyes, mouth, eyelashes and eyebrows. On Genesis 9 these are separate figures with their own UVs and presets, and the template doesn't cover them.
   - **Not converted:** the Anatomical Element geograft.
   - **What the run log lists:** each part it left as stock.
   - **For a later path:** eyes are the part most missed, and could be converted then.

3. **Which maps?** *Recommended:* every channel the character maps on those surfaces. For Luanne that's base colour, translucency, roughness, normal and detail normal, so five bakes.
   - **A channel set on some surfaces but not others:** the others bake its flat value.
   - **Data maps** (roughness, normals): baked without colour conversion.
   - **Normal maps:** baked as colour, as the template does. A proper tangent-space bake can come later if seams show.
   - **A layered image:** step 1 asks Daz to flatten it. If Daz can't do that headless, the step fails and names the channel.

4. **Which shader on G8F?** *Recommended:* PBRSkin, Genesis 9's own shader (Daz Studio 4.21 or later; you have 4.24), with the character's values copied over and the baked maps swapped in. That keeps the look closest. Converting to Iray Uber can come later, for older Daz versions or other engines.

5. **Map size and file type.** *Recommended:* the source's size (4096 px for Luanne), and the source's file type for each channel: JPEG at quality 95 for colour maps, PNG where the product used PNG (Luanne's normals).
   - **Disk use:** about 20 images per character. R7a measures it (expected 150-300 MB).
   - **Overriding it:** a `resolution` parameter, for lighter outputs.

6. **How Blender gets the template.** *Recommended:* the same way as Daz Generations: a tool, `texture_converter_g9_g8f`, pointing at your zip (`exchange tools set`). On first use Exchange extracts it into its data folder. Each bake opens that copy and never saves it, and your zip is only read.

7. **The nail and genital overlays.** *Recommended:* not applied. The guide blends them in by hand, with masking and healing, and a script would do it badly. The nails come from the bake as they are, and the log says the overlays weren't used.

8. **What you double-click.** *Recommended:* one character preset, `People/Genesis 8 Female/Exchange/<character>.duf`, using the G9 character's own thumbnail. With your G8F selected, it dials the morph to 100% and applies the skin. Saved by Daz from the Exchange copy, then rewritten to the regular G8F, as the morph is.

9. **Where the textures go.** *Recommended:* `Runtime/Textures/Exchange/<character>/<character>_<channel>_<tile>.<ext>`, beside the morph in Exchange Conversions.

10. **The one-time notice.** *Recommended:* the core reports whether the Daz endpoint's folder is one of Daz's content directories. It reads the registry, as the content prerequisite does, and never writes it. When it isn't, an Installed claim in Daz Studio and the place's panel say:

    > To see these in Daz Studio, add this folder once in its Content Directory Manager

    with *Copy path* and *Show in folder*. The note goes away once the folder is added.

11. **R6c's two rough edges.** *Recommended:* fixed in R7c, since the proof is watched end to end.
    - **The watcher:** it stops counting what Exchange itself just wrote and rescanned, so *Rescan changed* doesn't appear after a walk.
    - **A claim's detail:** it shows the process's name, not its id.

12. **The proof's library and characters.** *Recommended:* a fresh scratch sample, built from `D:\Daz 3D\Studio3\content` with `scripts/sample_library.py`, so the textures come with the product. R6's sample came from `My Library`, which has none of Luanne's textures.
    - **How it's noticed:** with the Workspace running, Luanne's product is copied into the watched sample, as installing a product would add it. Then it appears in New.
    - **A second check, in R7a:** a female G9 character with a different skin set-up (layered makeup, or a non-PBRSkin shader), so step 1 isn't fitted to one product. I'll pick one from your library's list, unless you name one.

13. **Daz and Blender while you're away.** *Recommended:* as R6's decision 11: headless, with your own content directories, writing only to scratch.

## Found in R7a

R7a ran steps 1 and 3 for real on Luanne and on MSO Merida HD (Iray Uber, with a layered makeup preset applied). What it changed in the decisions above:

- **Decision 3, layered images:** solved. Daz flattens a layered image into its temp folder for the renderer (`getTempFilename()`), headless too, and step 1 copies that file out. Merida's blue eye makeup came through to G8F's face.
- **Decision 4, the shader:** Merida's skin is Iray Uber, not PBRSkin, with bump maps instead of normal maps. Copying PBRSkin values doesn't fit her, so R7b keeps **the source's own shader** on G8F (PBRSkin for Luanne, Iray Uber for Merida), with its values and the baked maps. That still keeps the look closest, which was the reason for decision 4.
- **Decision 5, map size:** each map is as large as its largest source, **up to 4096 px** (the `resolution` parameter). Genesis 9's shared detail normal maps are 8192 px: baked at that size, they took 252 s and 95 MB, four times the others, for detail that shared map already holds.
- **Decision 12, the sample's textures:** not needed. Daz jobs use your content directories, so Daz finds a character's textures wherever they are (Luanne's are in `D:\Daz 3D\Studio3\content`), and the sample needs only what is scanned and claimed.

## Not in R7

- **Eyes, mouth, eyelashes and brows from the G9 character.** G8F keeps its own (decision 2).
- **The overlays and the guide's hand touch-ups** (decision 7).
- **Male targets, and sources other than G9.** G8.1F and G2F templates exist (`PROCESS_FILES.md`), so they're the next variants.
- **Things not yet owned, browser tagging, and Hand to agent.** These are the next plan's.
