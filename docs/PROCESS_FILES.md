# Files processes need

These are files outside the repository that processes need on the user's machine. They're third-party or the user's own, so they're never committed or bundled. A process declares them as prerequisites (tool paths), so a missing one is reported before anything runs.

Exchange only reads them. It never edits, moves or deletes them.

Keep this list current: add a row when a process starts depending on a file, and note when it was last checked.

## 4d: character → Genesis 8 Female

### Daz Studio figures (in `D:\Daz 3D\Studio\My Library`)

| What | Files | Made by | Used for | Checked |
| --- | --- | --- | --- | --- |
| **Exchange G8F**: a renamed copy of stock Genesis 8 Female, vendor "Exchange", with no morphs | `People/Genesis 8 Female/Genesis 8 Basic Female Exchange.duf`, `data/Exchange/Genesis 8/Female/Genesis8Female.dsf`, `data/Exchange/Genesis 8/Female/UV Sets/DAZ 3D/Base/Base Female.dsf` | the user, 2026-10-22 | the target figure for building the morph (Morph Loader, rigging, ERC Freeze, save) | 2026-10-22: the same nodes and vertices as stock G8F; loads in 0.3 s |
| **Exchange G9**: the same kind of copy for Genesis 9, vendor "Exchange", with no morphs | `People/Genesis 9/Genesis 9 Exchange.duf`, `data/Exchange/Genesis 9/Base/Genesis9.dsf`, `data/Exchange/Genesis 9/Base/UV Sets/Daz 3D/Base/` (Base Multi UDIM, Base Single UDIM, their OLD versions, Genital Map Bake) | the user, 2026-10-24 | the source figure for exporting a character's shape | 2026-10-28: the files exist, there are no morph files, and the `.duf` names only `/data/Exchange/Genesis%209/` paths. Not yet loaded in Daz Studio. |
| Other Exchange copies (not used by 4d yet) | `People/Genesis/Genesis Exchange.duf`, `People/Genesis 2 Female/Genesis 2 Base Female Exchange.duf`, `People/Genesis 2 Male/Genesis 2 Base Male Exchange.duf`, `People/Genesis 3 Female/Genesis 3 Female Exchange.duf`, `People/Genesis 3 Male/Genesis 3 Male Exchange.duf`, `People/Genesis 8 Male/Genesis 8 Basic Male Exchange.duf`, with their `data/Exchange/...` base figures and UV sets | the user | sources and targets for later cross-figure paths (G1, G2, G3, G8 Male) | 2026-10-28: the files exist, with no morph files. Not yet loaded in Daz Studio. |
| **Regular G8F** | `data/DAZ 3D/Genesis 8/Female/Genesis8Female.dsf` | Daz | where converted morphs are installed. Morphs built on the Exchange copy have `/data/Exchange/Genesis%208/Female/` rewritten to the regular path. | 2026-10-22: a rewritten morph matches a direct build |
| G8F Dev Load (not used now) | `People/Genesis 8 Female/Developer Kit/Genesis 8 Female Dev Load.duf` | Daz | the stock G8F on the regular path. It loads every installed G8F morph (about 110 s per job), and it also applies a third-party mouth morph. | 2026-10-22 |

### Blender tools (in `PipelineTools/Blender`, the user's copies, untracked)

| What | Files | Used for | Notes |
| --- | --- | --- | --- |
| **Daz Generations 1.1.0** (Chokaphi, GPL add-on) | `Daz Generations/Daz_Generations 1.1.0.zip` (includes `conversionDB.db`, 370 MB) | converting a character's shape between G2/G3/G8/G8.1/G9 base meshes | Run headless from the extracted folder, never installed into the user's Blender. Recognises figures by vertex count. Brings its own vertex-order-preserving OBJ importer and exporter (Blender 4 has no legacy OBJ importer). `Tutorial 1.0.pdf` is its guide. |
| **Texture Converter v2.02, G9 → G8F** | `Texture Conversion Template v2/Texture Converter G9 to G8F_V2.02.zip` (`.blend` plus nail overlays) | baking skin maps onto G8F's four UDIM tiles | Checked 2026-10-22: a headless bake in Blender 4.1 took 9.4 s at 1024 px. New tiles need `image.tile_add(fill=True)` and `tile_fill`. |
| **Texture Converter v2.02, G8.1F → G8F** | `Texture Converter G8.1F to G8F_V2.02.zip` | the same, from G8.1F | |
| **Texture Converter v2.02, G2F → G8F** | `Texture Converter G2F to G8F_v2.02.zip` (plus eyesocket and nail overlays) | the same, from G2F | The guide is `Blender texture conversion template_G2F to G8F_GUIDE.pdf`. |
| Templates targeting G2F (later) | `Texture Converter G3F G8F to G2F_v2.02*`, `Texture Converter G9 to G2F_v2.02.zip` | VaM backporting, phase 5 | |
| Texture Conversion Blender v2.01 (not used) | `Texture Conversion Blender/` | | Blender 2.79 only, targeting G2. |

### Applications

| What | Path on the dev machine | Notes |
| --- | --- | --- |
| Daz Studio 4.24 | `C:\Daz 3D\Applications\64-bit\DAZ 3D\DAZStudio4\DAZStudio.exe` | Run as `-instanceName Exchange -noPrompt -noDefaultScene`. `-headless` works (checked 2026-10-22). |
| Blender 4.1 | `C:\Program Files\Blender Foundation\Blender 4.1\blender.exe` | The texture templates need Blender 3.2 or later; Daz Generations needs 3.0 or later. |
