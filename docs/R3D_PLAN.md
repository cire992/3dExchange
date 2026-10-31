# R3d: fixing what R3c found

Approved by Luke on 2026-10-31, with every recommended answer. Part of [RESTART_PLAN.md](RESTART_PLAN.md), following [R3_PLAN.md](R3_PLAN.md). R3 isn't finished until these land: R3c showed that claims work on real content, and found five problems, two of them in the way of the first proof.

## The goal

The first proof's claim tells the truth. After this, "this G9 character, as a G8 character, in Daz Studio" says **a process has to be built**, on a product or on a character Luke saved. Every other claim's `ready` means it can run, and a claim that landed says Installed.

## A correction first

`PROGRESS.md`'s R3c section overstates problem 2. It says anything saved to `People/<figure>/Characters/` goes unnoticed, and counts 1,380 skipped files. Both are wrong: a loose file matching a type rule becomes a dossier of its own (`identification.py`, the last loop), and `People/*/Characters/**/*.duf` is such a rule. R3d-1 corrects the write-up with the numbers below.

## The problems

| # | Problem | Where | Blocks the first proof? |
|---|---|---|---|
| 1 | A copy route satisfies a role, so a G9 character "as `g8f_character`" reads `ready` | `claims.py`, `find_path` | **Yes** |
| 2 | Characters and scene subsets saved outside a typed folder get no dossier | `scanner/layers/daz.py` | **Yes**, for saved characters |
| 3 | An endpoint outside a single-root place becomes a new environment, so the claim stops at Converted with a false message | `runner.py`, `_rescan` | No |
| 4 | `ready` doesn't mean a process can run: a `daz_prop` matches Convert mesh but holds a `.cr2` | `plan.py`, `routes` | No |
| 5 | A product claim says "build" when only its children can travel, though the planner plans them | `claims.py`, `find_path` | **Yes**, for products (*Krow HD* is one) |

Problem 5 is new since R3c. A probe confirmed it: *Marius* claimed for a place only its child character can reach reads `none`, while `plan_requisition` plans that child.

**Problem 2, measured.** The real Daz layer, run over the whole library's file list, without a database (about 3 minutes):

| `.duf` files no product holds | 11,345 |
|---|---|
| Already dossiers, by a type rule (1,422 character presets, 891 hair, 45 wearables, 39 props) | 2,397 |
| Unattached | 8,948 |
| ...of which material, pose, shape and other presets, which should stay unattached | about 7,100 |
| ...of which `scene_subset` | 994 |
| ...of which `wearable` | 747 |
| ...of which `character` | 54 |

Many of those 1,795 sit in `data/` and `Runtime/` (466 subsets in `Runtime/Libraries/Props` alone), which aren't folders people browse. Luke's Exchange copies are among the rest.

## The fixes

### R3d-1, by hand: claims tell the truth (problems 1 and 5)

- **A copy never satisfies a role.** With `as` set, only a convert chain whose last process grants the role counts. No chain: `none`, the turn is `build`.
- **A product's path includes its children.** When the product itself has no route, `find_path` looks at its children, and the claim is `ready` if any can travel: route `children`, listing the processes. With `as` set, only children whose chain grants the role count, so `plan_requisition` gets a `role` option. The milestone already follows the least advanced included item.
- **Docs:** the correction above, and the problems' state in `PROGRESS.md`.

By hand because it changes `test_the_role_filter_keeps_one_chain_and_drops_another`, a protected test that pins the wrong behaviour.

### R3d-2, by the factory: saved files are noticed (problem 2)

- The Daz layer reads the `asset_info.type` of each `.duf` no product holds, outside `data/` and `Runtime/`, and no type rule matches: only the head of the file, through `readonly`.
- A new layer option maps those types to dossier types: `character` → `daz_character_preset`, `wearable` → `daz_wearable`, `scene_subset` → a new `daz_scene_subset`. Each becomes a dossier of its own, at the same confidence as the type rules (0.6).
- Then, by hand: the sample library, and the Daz layer over the whole file list, to measure the dossiers added and the time. No full scan.

### R3d-3, by the factory: `ready` means it can run (problem 4)

- A new optional `[input] extensions` in process manifests. `routes` keeps a chain only if the source entry holds such a file; only the first process of a chain is checked. Convert mesh declares its seven.
- The same filter on `find_path`'s look past readiness, so the prop claim reads `none` ("a process has to be built"), which is true: getting a mesh out of a Daz prop needs Daz Studio. This also fixes *Requisition to…*, which has the same fault.

### R3d-4, by the factory: endpoints stay in their place (problem 3)

- `_rescan` joins the endpoint's root to the requisition's own environment, instead of letting `register_root` make a new one. The claim then reaches Installed, and no stray environment appears.
- A claim's relative `folder` that leaves the place's root (`..`, a drive prefix) is refused. The R3b review flagged this for closing before R4 exposes claims.

## How it's built

In that order, one PR each: the blockers first. Each factory issue is filed once the one before is merged, as R3a and R3b were. After R3d-2 I re-run R3c's claims on the sample library. R3 is done when *Krow HD* and a saved character both read `build` as `g8f_character`, the truck's prop reads `build`, and the mesh reaches Installed through a folder outside the place.

## Decisions (with recommended answers)

1. **Does a copy ever satisfy a role?** *Recommended:* no. Roles come from a process's output, and entries don't record them, so a copy can't show it has one. A claim on something already right drops `as`.
2. **A scene subset's dossier type.** A subset is a bag: a character with its outfit, or a set of props. *Recommended:* a new `daz_scene_subset`, not `daz_character_preset`, because the file doesn't say what it holds without reading all of it. R6's process can take both types. The alternative is parsing every subset to tell them apart, which R3 doesn't need.
3. **Which saved types count?** *Recommended:* `character`, `scene_subset` and `wearable`. `scene` stays out, since a whole scene isn't one asset; presets stay out, as they have no thing of their own.
4. **Which folders?** *Recommended:* everywhere but `data/` and `Runtime/`, as the folder-product rule already does. It leaves out the 466 subsets in `Runtime/Libraries/Props`, which Daz users don't browse as content.
5. **Reading files during identification.** Reading 8,948 heads took 57 s on a cold disk, and it would run on every full scan. *Recommended:* accept it for the smaller set decision 4 leaves, about a third of them, and measure in the real-data check. Add a cache only if the measurement says so.
6. **Luke's Exchange copies become things.** They're process files, and they'd show in the library like anything else. *Recommended:* accept it. They're real assets, and `exchange env config --ignore-add` hides them if they get in the way.
7. **A folder outside a single-root place.** *Recommended:* the output joins the place, as above. The alternative, refusing such folders, would also have to catch an environment's own endpoint setting, and leaves the stray environment problem.
8. **The factory's `job merge` refusal.** Auto mode refused it on two of the first four jobs. *Recommended:* leave it. The permission is yours to change, and a refused job waits with its PR open for you to merge, which `job queue` now notices.

## Not in this

- Claiming the outfit out of a saved character (anecdote 3 in VISION.md): that needs a subset split into its parts, and a process to do it. R3d-2 only makes the subset a thing.
- `claim show` printing `path:` as a raw dict: R4's API is where this gets its real shape.
- The first-time scan of the real library into Exchange's default database, which is empty today. That's Luke's to run, before R7.
