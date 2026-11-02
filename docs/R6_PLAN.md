# R6: the G8 path, shape

Approved by Luke on 2026-11-02, with every recommended answer. Part of [RESTART_PLAN.md](RESTART_PLAN.md); read [VISION.md](VISION.md) first. R3-R5 built the loop: a claim finds its path and walks it, and the Workspace shows it. R6 builds the first path the loop was made for, so the first proof's claim stops reading "No path yet".

## The goal

After R6, a Genesis 9 character claimed `as g8f_character` in Daz Studio reads **Claim and walk**. Walking it installs a G8F morph with the character's shape into the Exchange Conversions content directory. Dialled to 1 on the regular Genesis 8 Female, it gives that character's shape. Skin comes in R7.

**How "done" is tested:** on a sample library, with scratch data, two G9 characters are walked from the Workspace to Installed: a real character product and a saved one. Luke then loads one of the morphs on the regular G8F in their own Daz Studio and checks it by eye.

## The path

```
 the G9 character                                                        Exchange Conversions
 (a .duf in Daz)                                                         (a content directory)
      │                                                                          ▲
      ▼                                                                          │
 1. Daz: load it on Genesis 9 ─► 2. Blender: Daz Generations ─► 3. Daz: build ─► 4. rewrite ─► 5. install
    write its shape as OBJ          G9 shape → G8F mesh            the morph on    the paths     (the runner)
    (and the stock G8F's)           (headless)                     the Exchange    to the
                                                                   G8F copy;       regular G8F
                                                                   check it
```

One process package, `daz_character_to_g8f`, granting `g8f_character`:

| Step | Runs in | What it does | Known? |
|---|---|---|---|
| 1. Export | Daz Studio | Loads the character on Genesis 9 and writes its shape as an OBJ: base resolution, zero pose, with its morphs dialled as saved. It also writes the stock G8F mesh from the Exchange G8F copy, which Daz Generations needs as its target. | **No: never done.** See decision 1 |
| 2. Convert | Blender, headless | Runs Daz Generations' *Convert Model Shape V3*, from the G9 shape (25,182 vertices) onto the G8F mesh (16,556), keeping vertex order. | The add-on is read, not yet run headless |
| 3. Build | Daz Studio | Applies the verified morph recipe on the Exchange G8F copy (Morph Loader, rigging, ERC Freeze, save). Then it loads the morph at 1 and measures how far it lands from step 2's mesh. | Verified in the 4d spike, 18 s |
| 4. Rewrite | Python | Rewrites `/data/Exchange/Genesis%208/Female/` to the regular G8F's path in the saved files, and moves them to the regular figure's folder. | Verified by hand in the spike |
| 5. Install | the runner | Writes the result into the endpoint, as every process does. | Built |

## What's already there

| R6 needs | Already built | Missing |
|---|---|---|
| Finding the path | Roles in manifests, `find_path` by role and place (R3), `ready` checking file types (R3d-3) | Only Genesis 9 sources: the input can't name a figure generation (decision 9) |
| Daz Studio jobs | `DazBridge`: a separate instance, the settings copied from the main one, Daz's log kept | `-headless`, verified on 2026-10-22 but not used (decision 10) |
| Blender jobs | `BlenderBridge`, headless | Loading an add-on that isn't installed (decision 3) |
| The user's files | Tool prerequisites (`exchange tools set`) | A way to say "this file must be in a Daz content directory" for the Exchange G8F copy (decision 8) |
| The endpoint | Exchange Conversions beside the first library (4a) | Nothing |
| Installed | Sidecars, rescans, R3d-4's joined roots | Nothing, unless a morph's `.dsf` isn't picked up (checked in R6c) |

## How it's built

One PR per chunk, in the core. The shell needs nothing: the Workspace already shows the path, walks it and follows the claim.

1. **R6a: groundwork.** All of it is testable with fakes:
   - `[input] variants` in manifests.
   - `content` prerequisites.
   - `-headless` for Daz.
   - A Daz path rewrite operation (`core.rewrite_daz_paths`), tested against a morph file saved in the spike.
   - This plan.
2. **R6b: the package.** The manifest, the two DazScripts, the Blender script, and the operations that call them. Its tests use fake bridges, as Convert mesh's do. It's built by running each step for real on scratch data (decision 11), so what's merged has already run. `PROCESS_FILES.md` gets the rows the package depends on.
3. **R6c, by hand: the path in the Workspace.** On a sample library with a female G9 character product and a saved G9 character, plus the saved Exchange G9 copy (whose morph should come out near zero, a free sanity check). Each is claimed and walked from the Workspace into a scratch content directory, then Luke loads one on the regular G8F. Written up in `PROGRESS.md`, with timings.

## Decisions (the recommended answers, approved)

1. **Which Genesis 9 does step 1 load the character on?** RESTART_PLAN said the Exchange G9 copy. But a character's morphs are saved against the regular figure's path (`/data/DAZ 3D/Genesis 9/...`), so the copy can't see them. Using the copy would mean copying each morph and everything it depends on, rewriting their paths, and adding a content directory for the job. *Recommended:* load the regular Genesis 9 with your own content directories, as Daz always does. That's slower (the spike's G8F took about 110 s with your full morph library), but your add-on cache doesn't change, since the content directories match. A faster copy-based load can come later, once R6c has measured the slow one.

2. **What counts as the shape?** *Recommended:* the character as saved, at base resolution in the zero pose: the morphs it dials, but not expressions or a pose. HD detail is lost, since a G8F morph is base resolution anyway. A character that scales the whole figure keeps its proportions but not its size, and the run's log says so.

3. **How does Blender get Daz Generations?** It's a GPL add-on you own, at `PipelineTools/Blender/Daz Generations/Daz_Generations 1.1.0.zip`. *Recommended:* a tool, `daz_generations`, pointing at that zip (found there by default, set elsewhere with `exchange tools set`). On first use Exchange extracts it into its own data folder (`tools/daz_generations/1.1.0/`, about 370 MB with its database). Blender loads it from there with `--factory-startup`. It's never installed into your Blender, and the zip is only read.

4. **Which conversion?** Daz Generations has V1, V2 and V3, plus a male variant. *Recommended:* a `method` parameter, defaulting to V3 (body regions, eyes and mouth moved as a unit, a 4-vertex weighted average). Its target is female, since the target figure is G8F.

5. **Check the morph before installing it?** *Recommended:* yes, in step 3's Daz run. It loads the built morph at 1 on the copy and compares it with step 2's mesh. Above 0.01 cm, the step fails and says by how much. Below that, the log records the largest difference. A morph that silently fails to load is the failure the spike warned about, and this catches it before it's installed.

6. **Naming and placement.**
   - **The file:** *Recommended:* `data/DAZ 3D/Genesis 8/Female/Morphs/Exchange/<character>/<character>.dsf`.
   - **The dial:** shown in a property group `Morphs/Exchange`, labelled with the character's name.
   - **No new folders:** the output goes at the content directory's root (an empty output folder), so it's where Daz looks.
   - **Walking it again:** overwrites, through the usual collision rule.
   - **The spike's `-0xaaf75b0` suffix** on the saved modifier id gets looked at in R6b. Your scenes would then name a stable id.

7. **Where it installs.** *Recommended:* the Exchange Conversions content directory (RESTART_PLAN's decision 7, already the Daz endpoint's default). The run's last log line says to add that folder once in Daz Studio's Content Directory Manager to see the morph. Exchange doesn't change Daz's settings. A proper one-time notice in the Workspace waits for R7, where the proof runs.

8. **Declaring the Exchange G8F copy.** *Recommended:* a new prerequisite kind, `content`, for files that must be in one of an app's content directories: for Daz Studio, those of its main instance, which jobs get. The copy's `.duf` and its `Genesis8Female.dsf` are declared this way, so a missing copy reads "No path yet" with a reason before anything runs. This is the second kind of file `PROCESS_FILES.md` lists, and R7 needs it too.

9. **Only Genesis 9 sources.** *Recommended:* manifests gain `[input] variants = ["genesis_9"]`, matched against the thing's figure generation (Compatibility for products, the folder for saved files). A G8 or G3 character then reads "No path yet" instead of a path that would fail in Daz. Step 1 also checks the figure it loaded, in case a variant is wrong.

10. **Daz without a window.** *Recommended:* the bridge passes `-headless`, verified on 2026-10-22 (same results, clean exit). Walking a claim then doesn't open a Daz window on your desktop. A `daz_window` setting would bring the window back for debugging; it's not needed now.

11. **Running Daz while you're away.** PROGRESS's rule is to launch Daz only while you're at the computer, because it opened a window and could stop on a prompt. *Recommended:* with `-headless`, R6b's development may run Daz unattended, with two limits. It always uses your own content directories, synced as now, so your add-on cache isn't touched. And it writes only to scratch. I'll say before the first run, and stop if Daz ever asks for anything.

12. **A product with several characters.** Some character products ship several presets (full body, head, body). *Recommended:* as R3d-1 already does, a product claim walks each child that grants the role, giving one morph each. To get just one, claim that child.

13. **Who builds it?** *Recommended:* by hand, one PR per chunk, as R5 was. Every step needs real Daz and Blender runs, which the factory's agents can't do.

## Not in R6

- **Skin:** the Texture Converter bake and a character preset with the morph and the maps (R7).
- **A faster source load:** decision 1's copy-based variant.
- **Male targets, and sources other than G9:** G8.1 and G2 sources become variants of this path later (RESTART_PLAN's decision 6).
- **Any Workspace change.**
