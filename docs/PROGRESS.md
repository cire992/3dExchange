# Exchange: progress and handoff

Last updated 2026-10-28, at the restart (R1). `main` has phases 1-3, 4a-4c (#10-#13), the Daz Studio bridge fixes checked against the real app (#14), the pivot docs (#15), phase 6's core chunks 6a, 6b (via #19), 6e (#23) and 6g (#25, and #26 via #27), scoped file links (#24), phase 7 part 1's core chunks (#20-#22) and the progress doc after 6g (#28). The shell repository has merged 6c, 6d, 6f, 6h, 6i (its #16) and 7c. Phase 6 has 6j left.

Read this first, then `docs/VISION.md` (the brief: what Exchange is for, the one loop, the scope and the decisions), `docs/RESTART_PLAN.md` (the current plan), `docs/DESIGN_SPEC.md` (how the built parts work; use its terms exactly), `docs/PROCESS_FILES.md` (files outside the repository that processes need) and `docs/USEFUL_PATHS.md` (untracked: real asset folders and tools on the dev machine, for testing). Where VISION.md and anything else disagree, VISION.md wins. The [README](../README.md) covers install and usage.

## The restart (2026-10-28)

Exchange is refocused on one loop: **Exchange notices a thing → Luke claims it ("this thing, as this, in that place") → Exchange finds or builds the path → it lands, milestone by milestone.** The scope is asset conversion. The 2026-10-24 design pivot (projects, game data, the Tauri shell) is in `docs/archive/` (identity, overview, game data model) and the spec; VISION.md says what of it stays.

**What changes:**
- **The UI.** The shell's Workspace carries the loop. The PySide6 window gets no new features and is removed at 6j.
- **Game data is frozen.** `exchange.projects` (7a, 7b) and the shell's checkpoint (7c) stay as they are, with their tests; nothing new is built on them. Phase 7 part 2 and the benchmark (phase 9) are cancelled. Its `exchange claims list/ack` moved to `exchange project claims list/ack` in R3.
- **Claims** now mean the loop's claims: intent for one asset, with milestones (Claimed → Acquired → Converted → Installed → In play). They are new work (R3-R5).
- **Agents.** The Chats window stays as it is. Phase 8 shrinks to the second proof: Hand to agent (a brief opened in a chat) and a small Exchange MCP.
- **Vocabulary.** A *process* is one automated chain; a *path* is a claim's whole route.

**What stays:** every decision recorded below still stands unless VISION.md supersedes it. *How we work* is unchanged: plan with open questions and recommended answers, wait for approval, one PR per chunk, check against real data.

**The roadmap** (replaces the phase roadmap; details in `RESTART_PLAN.md`):

| # | Repo | What |
| --- | --- | --- |
| R1 | both | Docs reset: VISION.md and the plan, old docs archived, this file around the loop |
| R2 | both | 6j: parity signed off on a real library, then the PySide6 window removed |
| R3 | core | Claims core: claim files (Markdown + YAML frontmatter), index, path finding by role and place, milestones, `exchange claim` |
| R4 | core | Claims in the service API and the OpenAPI contract |
| R5 | shell | Claims in the Workspace: Claim…, the Claims view, new since last scan |
| R6 | core | The G8 path, shape: `daz_character_to_g8f` (was 4d) |
| R7 | both | The G8 path, skin, and the first proof end to end in the Workspace |
| later | both | The second proof: Hand to agent and the Exchange MCP |

**4d's open question 1 is answered** by the restart: the first cross-figure path is Genesis 9 → Genesis 8 Female, the shape through Daz Generations and the verified morph recipe, the skin through the Texture Converter G9 → G8F template. The Exchange G9 copy is finished (`PROCESS_FILES.md`).

**Between the repositories:** this repository owns the service API and the Exchange MCP; the shell consumes them. The API's schema (`docs/api/openapi.json`) is the contract between the two, and changes to it are noted in both handoff docs.

## R3c: claims on real data (2026-10-31)

Claims work on real content: a real product walked from Claimed to Installed, and so did a real mesh through Blender. The check also found the problems below, and `R3D_PLAN.md` fixes them, one PR each.

**How:** on a sample library, built by `scripts/sample_library.py` (see `AGENTS.md`), not a scan of the real one. A full scan with enrichment ran 1 h 43 min without finishing and was stopped. The sample was three real products with their DIM manifests, a hand-installed character and three files Luke saved: 353 files, 369 MB, scanned with enrichment in 27 s. Claims, database and endpoints all lived in scratch, and the real library and data folder were not touched.

| Claim | Path | Result |
| --- | --- | --- |
| *Pickup Truck 1930* (product) → Daz Studio, a scratch folder | copy | **Installed** in 1.3 s: 6 of 6 items, 39 files, 19 MB |
| Its OBJ, loose → a folder inside the place | Convert mesh | **Installed** in 4.0 s (a 12 MB GLB) |
| Its OBJ, loose → a folder outside the place | Convert mesh | The GLB is right, but the claim stops at Converted (problem 3) |
| *PickUpFAA* (its `daz_prop`) → Daz Studio | Convert mesh | Failed: said `ready`, then "no mesh file" (problem 4) |
| *Krow HD for Genesis 9* as `g8f_character` → Daz Studio | copy | Says "Walk it" (problem 1) |

`claim add`, `list` and `show` each take about 0.6 s, nearly all of it Python starting. A failed run did what the design says: the failure came back as the claim's turn line.

**The problems:**

1. **A role was ignored on a copy route** (`claims.py`, `find_path`). A claim "as `g8f_character`" on a G9 character read `ready` by copy instead of `build`: walking it would have copied a G9 character and called it Installed. This is the first proof's own claim. Fixed in R3d-1: a copy never satisfies a role.
2. **Some saved files aren't noticed** (`scanner/layers/daz.py`). RESTART_PLAN's decision 8 asked this. An installed G9 character is noticed (*Krow*: a product and 11 children), so is a saved subset in a folder of its own (*TFD Dia*), and so is a loose file a type rule matches, such as anything in `People/<figure>/Characters/`. The rest are unattached, including the Exchange copies Luke saved (`People/Genesis 9/Genesis 9 Exchange.duf`, a `character`, and the G8 ones, `scene_subset`). Across the library, no product holds 11,345 `.duf` files: 2,397 become dossiers by a type rule, and of the 8,948 left, 994 are `scene_subset`, 747 `wearable` and 54 `character`, the rest being presets. (This corrects the first write-up, which said everything in `Characters/` was missed and counted 1,380 files.) Fixed in R3d-2: the head of each such `.duf` is read, and a `character`, `wearable` or `scene_subset` becomes a dossier of its own (a new `daz_scene_subset` type for the last); the rest stay unattached. Fixed in R3d-2: a saved file's own `asset_info.type` now makes it a thing. Checked on real files on 2026-10-31: all 8 saved Exchange copies are noticed; a saved character and a saved subset claimed `as g8f_character` read `build`; a saved character with no role walked to Installed in 0.7 s. Across the library it adds 665 dossiers (400 wearables, 222 subsets, 43 characters) and reads the head of 2,737 files, about 3 s on a warm disk and about 17 s by the cold rate.
3. **A folder outside a single-root place never reaches Installed** (`runner.py`, `_rescan`). The endpoint becomes a new environment, so the claim's place never holds the output, and its turn line wrongly says "the place no longer holds what requisition 3 wrote". Daz Studio gathers roots, so it doesn't happen there. Fixed in R3d-4: an endpoint's folder joins the requisition's own environment. A single-root place writes only through its first root, and a folder its layer doesn't read stops at Converted and says so. Checked on real files on 2026-10-31: a mesh claimed for a loose folder and walked to a folder outside it reached Installed in 4.8 s, with no new environment and the folder joined as a root.
4. **`ready` doesn't mean a process can run.** Convert mesh's input is matched by dossier type, and a `daz_prop` matches, but its entry holds a `.cr2`: the OBJ is a support file of the product. So R3_PLAN's check, Convert mesh on a Daz product, can't be done, which is why the OBJ was walked loose. R6's path goes through the Daz Studio bridge, so it doesn't depend on this. Fixed in R3d-3: a process can declare the file types it reads, and `ready` checks them. With no role, a prop claimed for the place that already holds it reads `ready` by copy, which writes a second copy: nothing needs building there. Checked on real files on 2026-10-31: the truck's prop reads `build` as a role and for a place that doesn't hold it, and Krow HD and a saved character read `build` as `g8f_character`.
5. **A product claim said "build" when only its children can travel** (`claims.py`, `find_path`), though the planner plans them. Found while planning the fixes. Fixed in R3d-1: a product with no route of its own takes its children's (route `children`), and with a role, only those that grant it.

## R4d: the claims API by hand (2026-10-31)

R4 is done: everything the CLI does with a claim, a client can do through the API, on real files. R5 can build the Workspace on it with no other core change.

**How:** on the R3c sample library, through a real `exchange serve` on a scratch database, with the data folder and endpoints in scratch. The library and the loose folder were hashed before and after, and neither changed.

| Step | Result |
| --- | --- |
| Scan the sample, then the loose folder, through `/jobs/scan` | 26.7 s for the sample. Nothing was new after the first scan, and the loose mesh was after the second |
| A saved character, previewed and claimed `as g8f_character` for Daz Studio | `build`, "No path yet: a process has to be built". `plan` and `walk` are 409s saying the same |
| The mesh, previewed for its own place | `ready`, and `already_there` true with no folder, false with one. Previews left no file |
| `plan`, with `format` changed to `gltf` | The option form came back, and the chosen value in the item's params |
| `walk` with that option, following `/claims/changes` | Queued and running at once, **Installed** in 4.5 s on the second poll, a `.gltf` and `.bin` in the folder, `gltf` remembered as last used |
| After the walk | `?new=true` unchanged, so Exchange's own output doesn't count. The version stayed still after one more list |
| A hand edit of the claim file | `/claims/changes` answered within a second, through `watchdog` |
| A wrong id, a folder leaving the place, closing twice | 404, 400, 409 |
| `close` with a reason, then Mark all seen | The reason in the notes, and the hand edit kept. `seen` 1, then nothing new |

**A hundred claims:** 102 claims, a mix of Daz Studio and loose, list in about 233 ms, 2.3 ms a claim, down from the 6 ms R4's plan started from. Making one takes 38 ms. So no index (R4's decision 9). This is on the sample's database; the real library is far larger, so measure again if the Claims view feels slow there.

**Fixed by hand here, from the reviews of R4b and R4c:**

1. **A claim that couldn't record its requisition left it queued.** With the file held open, `walk` answered 409 and a retry queued a second one. Now the requisition and the claim file are written together: if the file can't be written, nothing is queued.
2. **A failed `remember` lost the options and answered 500.** It wrote in place, so a value with no UTF-8 emptied `last_options.json`, and `walk` then started no job. It now goes through a temporary file, and a failure is dropped: last used options are a convenience, and the requisition is already queued.
3. **Forgetting an environment hid the next scan from "new".** R4c's marker is a dossier id, and SQLite reuses ids above the highest one left, so the next environment scanned could stay under the marker. Deleting dossiers now brings the marker down with them, and deleting the last one forgets it. This also removes the limit #56 accepted.

**For R5:** `seen` counts every new dossier, while the default list's `total` counts the outermost ones, so they aren't one number. "No marker yet" and "nothing new" look the same. A claim moved by a requisition run from the CLI gets no notice until something next touches the file.

**Left open, set aside by Luke:** the 500s R4a's approver found (a hex integer past 4,300 digits in a claim file, lone surrogates in `note` and `reason`, a NUL in a relative `folder`, an `environment` of `10**30`), and how hand-edited `as` and `folder` behave.

## Where we are

**Phases 1-3, 4a-4c, phase 6 up to 6i, phase 7 part 1 and R1 are merged.** R2 (6j) is done: R2a (#30) closed the parity gaps `PARITY_CHECKLIST.md` lists, Luke signed the checklist off on 2026-10-29 (R2b), and the PySide6 window is removed in R2c. R3 (claims core) and R4 (claims API, `R4_PLAN.md`) are done; R5, claims in the Workspace, is next.

- **Stacked PRs:** after merging one, change the next PR's base to `main` before merging it (or delete the merged branch, and GitHub moves it). This has gone wrong three times: #11 and #12 needed #13 to reach `main`, #26 needed #27, and the shell's #14 needed its #16. Turning on *Automatically delete head branches* (Settings › General › Pull Requests, in both repositories) makes GitHub retarget them by itself; until then, prefer branching from `main`.

| PR | What | State |
| --- | --- | --- |
| #1 | Phase 1: core package, SQLite schema, definition formats, `exchange scan` | merged |
| #2 | 2a: multi-root environments, Unreal, scan phase 3 (enrichment), search, query API, auto-discovery | merged |
| #3 | Daz fixes that missed #2's merge: real DIM manifest format, relocation by folder + filename | merged |
| #4 | 2b: main window (PySide6) | merged |
| #5 | 2c: add-environment wizard | merged |
| #6 | This handoff doc | merged |
| #7 | 3a: curation core: lexicons, classification, undoable curation, suggestions, collections, hand-installed Daz products, CLI | merged |
| #8 | 3b: editing in the main window: inspector editing + revert markers, bulk edit, drag and drop linking, collections in the sidebar, context-menu actions, Ctrl+Z/Ctrl+Y | merged |
| #9 | 3c: Unidentified desk (low-confidence dossiers, unattached files by folder, suggestions in batches), lexicon editor, file watcher (`watchdog`); split, fold and promote in the window | merged |
| #10 | 4a: requisition engine: pipeline packages (manifest, trust, prerequisites, core operations), planning (routes, chains, product plans), queue and runner (checkpoints, cached steps, collisions), endpoints, sidecars, staleness, removal, CLI, test harness | merged |
| #11 | 4b: bridges: Blender (headless), Daz Studio (DazScript at launch), command-line tools; one job per app; built-in Convert mesh (Blender) | merged (via #13) |
| #12 | 4c: requisitions in the window: Requisition to… (plan tree, option forms, presets, last-used options, batch), the queue view, Settings › Pipelines and Endpoints | merged (via #13) |
| #13 | 4b and 4c onto `main`, with this doc | merged |
| #14 | Daz Studio bridge, checked against the real app: instance settings from the main instance, Daz's log in errors | merged |
| #15 | The design pivot docs: identity, spec, progress | merged |
| #16 | Daz Studio bridge: the job script is included at the top level, so its functions see its names | merged (via #19) |
| #17 | 6a: pipelines renamed processes, with the migration of existing data | merged (via #19) |
| #18 | 6b: `exchange serve` and the read API | merged (via #19) |
| #19 | #16-#18 onto `main` | merged |
| #20 | The game data model: identity v2, overview, game data model; the spec's *Projects* brought in line; the phase 7 plan | merged |
| #21 | 7a: project homes: formats, parser, schemas, validator, `exchange project init/validate/checkpoint/config` | merged |
| #22 | 7b: gap claims, dossier hints and relink candidates, fast capture, `exchange claims list/ack` | merged |
| #23 | 6e: the write API: curation edits, Undo/Redo and history, collections, suggestions, the desk, lexicons | merged |
| #24 | Curation edits apply only the file links they name | merged |
| #25 | 6g, part 1: the jobs API: environments (discover, detect, register, configure), scans and rescans in worker processes with progress, classify, change notices | merged |
| #26 | 6g, part 2: requisitions: planning, the queue and running it, process packages, tools, presets, endpoints; the wizard's endpoint setting read | merged into #25's branch (via #27) |
| #27 | #26 onto `main` | merged |
| #28 | This doc after 6g | merged |
| #29 | R1, the restart: VISION.md and RESTART_PLAN.md, old docs archived, this doc around the loop | merged |
| R2a | 6j's parity gaps (with Exchange-Shell's R2a): each file in a dossier's detail carries `root` and `key`, its file ref, so the Workspace's drop menu can link one asset's files onto another | merged (#30) |
| R2c | 6j's end: the PySide6 window removed (its package and tests, the `ui` extra, the PySide6 and Qt test dependencies, the window's entry point) | merged (#33) |
| R3a | Claims core, part 1: claim files in `<data>/claims/`, Claimed and Acquired, `exchange claim add / list / show / close` (#34) | merged (#35) |
| R3b | Claims core, part 2: claim paths by role and place, whose turn, `exchange claim walk [--run]`, Converted and Installed (#36) | merged (#37) |
| R3 | The frozen slice's `exchange claims list/ack` moved to `exchange project claims list/ack`, no alias; the R3 plan committed | merged (#38) |
| R3c | Claims on real data, `scripts/sample_library.py` | merged (#39) |
| R3d-1 | Claims tell the truth: a copy never satisfies a role, and a product's path includes its children | merged (#40) |
| R3d-2 | Saved characters, subsets and wearables become things: their file says what they are (#41) | merged (#42) |
| R3d-3 | `ready` means a process has a file it can read: an optional `[input] extensions` in process manifests (#43) | merged (#44) |
| R3d-4 | Endpoints stay in their place: a folder outside a place joins it as a root, and a claim's relative folder can't leave it (#45) | merged (#47) |
| R3d-5 | A joined folder can be forgotten on its own (`env forget --root`), and can't retype its place (#48) | merged (#50) |
| R3d-6 | A place holds only what's on an online root: output on an offline or deleted root reads Converted, and Installed again when the root is back (#49) | merged (#51) |
| R4a | Claims in the service API: read, make, close, preview, `already_there`, `ProcessView.roles`, safe claim writes (#52) | merged (#53) |
| R4b | Walk a claim through the API: `plan` and `walk` with options, `excluded` and `on_collision`; `GET /claims/changes` change notices (#54) | merged (#55) |
| R4c | What's new, with a marker you move yourself: `GET /dossiers?new=true`, `POST /dossiers/new/seen` (#56) | merged (#57) |
| R4d | The claims API by hand on the sample library; a claim that can't record its requisition queues nothing, `remember` writes safely, deleting dossiers brings the new marker down; `R4_PLAN.md` | in review |

## Phase 6: Service and Workspace

Approved 2026-10-24 with every recommended answer. Each chunk is one PR in one repository; the
shell's handoff doc is `docs/EXCHANGE_PROGRESS.md` in the shell repository.

| # | Repo | What |
| --- | --- | --- |
| 6a | core | Rename pipelines to processes, with the migration of existing data |
| 6b | core | `exchange serve` (FastAPI, loopback, per-launch token) and the read API: sidebar, paged query and search, dossier detail, collections, thumbnails, environments; the OpenAPI schema committed as the contract |
| 6c | shell | The shell starts the service and proxies it on its own origin; connection status in the Workspace |
| 6d | shell | Library browsing (sidebar, virtualized item cards, search, read-only inspector); meets G4 |
| 6e | core | Write API: curation edits, undo/redo/history, suggestions, desk, lexicons |
| 6f | shell | Curation in the Workspace |
| 6g | core | Jobs API: environments (detect, configure), scans with progress events, watcher notices, requisitions, process prerequisites, endpoints |
| 6h | shell | Environments and scanning |
| 6i | shell | Requisitions, the queue, Settings › Processes and Endpoints |
| 6j | both | Parity checklist signed off by the user on a real library, then the PySide6 window removed |

Decisions:
- **API:** FastAPI with uvicorn as an optional `service` extra; the core keeps its minimal
  dependencies. The schema is committed as `docs/api/openapi.json`; the shell generates
  TypeScript types from it.
- **Transport:** the shell's Node service starts `<core>/.venv/Scripts/python -m exchange serve`
  from a configured core folder and proxies it, so the Workspace keeps one origin and token.
- **Long jobs:** scans and requisition runs stay in worker processes, streaming progress events.
- **Both UIs during the transition:** they may run on the same database; avoid editing in both at
  once (separate undo stacks). The PySide6 window goes in 6j.
- **Work in a separate worktree** of this repository, never in the user's checkout.

### 6a: the rename and the data migration

- **Code:** `exchange.processes` (was `exchange.pipelines`), `ProcessError`, `ProcessManifest`,
  `process.toml` with a `[process]` table, `exchange processes …` and `exchange test-process`,
  `--process`, the window's *Processes* settings, the README and the spec.
- **Database:** migration `0007_processes.sql` renames `requisition_item.pipelines` to
  `processes` and each output's `"pipeline"` key to `"process"`. Option values stay keyed by
  process id. The database is backed up first, as for every migration.
- **Data folder** (`exchange.processes.legacy`, run once by `user_processes_dir()` under a lock):
  each package in `<data>/pipelines/` is converted in place. `pipeline.toml` becomes
  `process.toml` with `[process]`, and imports of `exchange.pipelines` become
  `exchange.processes`. Then the folder is renamed to `<data>/processes/` in one step. A package
  stays trusted only if its old fingerprint matched; its trust is then recorded for the
  converted files. An interrupted move finishes on the next run. `tools.json`, presets and
  `last_options.json` are keyed by tool or process id and do not change.
- **Sidecars** inside environments are never rewritten. New ones say `"processes"`; scans read
  only dossiers, names and files, so both kinds are recognized.
- **Old packages** found later (an extra folder, or `install` of an old folder) are reported with
  what to rename instead of being skipped, and an import of `exchange.pipelines` fails with the
  same hint.
- **No live Exchange data folder exists on the dev machine** (`%LOCALAPPDATA%\Exchange` is
  absent; earlier real-data checks used scratch copies). The migration was checked on a scratch
  data folder built with the pre-rename `main`: two Sketchfab models copied to scratch and
  scanned, a trusted user package, a Blender tool path, a fulfilled Convert mesh requisition
  (Blender 4.1) with a saved preset, and a queued one. On a copy of it the new code moved the
  folder, kept the package trusted with its imports updated, kept tool paths and presets, ran
  the queued requisition to fulfilment, found nothing stale, backed up the database
  (`library.v6.….bak.db`), and recognized both old- and new-format sidecars when rescanning the
  endpoint.

### 6b: the service and its read API

- **`exchange serve`** (`exchange.service`, the optional `service` extra: FastAPI and uvicorn):
  - binds `127.0.0.1` itself (`--port 0` picks a free port) and starts listening, then prints one
    JSON ready line (`event`, `url`, `api`, `version`, and `token` only when it made one)
  - the shell passes its own token in `EXCHANGE_SERVICE_TOKEN`
  - `--exit-with-stdin` stops it when its parent goes away
- **Security:** every `/api` request needs `Authorization: Bearer <token>`. Requests for any host
  name other than `127.0.0.1` or `localhost` get 403 (no DNS rebinding). No CORS, no docs pages,
  no schema route. `/health` needs no token and says nothing about the library.
- **Reading:** one read-only connection per worker thread, like the PySide6 window; the database is
  created or migrated once at start.
- **Routes (`/api/v1`):**
  - `sidebar`, `environments`, `collections`
  - `dossiers`: a page of item cards, with `query` (the search language), `group`, `environment`,
    `container`, `type`, `parent`, `collection`, `unidentified`, `offset`, `limit` ≤ 1000. It applies
    the window's rule: searches, type, collection and Unidentified views list all assets.
  - `dossiers/{uid}`: the inspector's detail with the parent's fields
  - `dossiers/{uid}/thumbnail`: the image from the cache
  - Thumbnails are URLs served by the service, never filesystem paths.
  - A search that does not parse is a 400 with its message.
- **Contract:** `docs/api/openapi.json`, regenerated by `exchange serve --openapi`; a test fails
  when it is out of date. The shell generates its TypeScript types from it (6c).
- **Tests:** `tests/test_service.py` covers the token, the host check, each route against the core's
  own query functions, the committed schema, and `exchange serve` started as the shell will start
  it. The suite is at 222.
- **On the real library** (a read-only scan of `D:\Daz 3D\Studio\My Library` into scratch,
  without enrichment: 3.56M files, 14,497 products, 235,087 dossiers, the same as before):
  - ready in 1.2 s
  - the sidebar 1.8 s
  - a page of 200 0.40 s (the last page 0.44 s)
  - searches 0.36-0.76 s (`tag:food` cold)
  - one asset's detail 0.13 s, environments and collections 0.02 s

  The sidebar is the slow call: the shell should load it once and refresh it when the library
  changes, not on every navigation.

### 6e: the write API

`exchange/service/edits.py`. The routes are in `docs/api/openapi.json`, tagged *editing*.

- **Edits** go through the curation engine, so each is one undoable step in `curation_log`:
  - fields, single or bulk, where a null value reverts; names go one asset at a time
  - tags, and reverting a tag
  - the product (parent), and reverting it
  - merge, fold variant, split, promote variant
  - new products, from assets and/or a desk folder's unattached files
  - linking files, or a desk folder, and unlinking them
  - dismissing assets and ignoring folders
  - collections: create, smart (saved search) or manual; delete; members
  - lexicon words
  - accepting and rejecting suggestions, in one step per batch
- **What every edit returns:** its log id and a label (as the window's Undo menu shows it). Also
  `new_uid` when it made an asset or collection, what to refresh (`none`, `detail`, `collections`,
  `all`, as the window's `_edit` scopes), and this session's Undo and Redo labels.
- **Undo and Redo:**
  - **The session's own stack:** `POST /undo` and `/redo` work on this service session's edits,
    like the window's Ctrl+Z and Ctrl+Y, and `GET /session` says what they would do.
  - **Any history entry:** `POST /history/{id}/undo` undoes one, from any session, and is itself
    undoable. `GET /history` lists the library's edits, newest first.
- **One write connection in one worker thread** (a single-thread pool), so edits never interleave and
  the connection's cache stays warm. It has the window's 1.5 s busy timeout.
- **Errors:**
  - a busy library (a scan holding the write lock) is **503** with the window's message and
    `Retry-After: 2`
  - a refused edit is **409**: merging into itself, a smart collection's members, a duplicate name,
    a search that does not compile, or a desk folder of more than 5,000 unattached files
  - an unknown asset, collection, history entry or lexicon is **404**
- **New reads, for the editors:**
  - `suggestions`: pages, with counts by kind
  - `desk/roots`, `desk/folders` (one level, with counts) and `desk/files`
  - `lexicons`: each term's file words and the words scans found, plus excluded words
  - `choices`: dossier types, category tags and the editable fields
- **Not in 6e:** the shell's proxy still allows GET only. 6f opens it to the editing routes, and
  adds them to its type generator (the generated types already compile against this schema).
- **The PySide6 window and the service** each keep their own Undo stack on the same library (the
  phase 6 decision); avoid editing in both at once.
- **Tests:** `tests/test_service_edits.py` (9 tests) covers:
  - the token on writes
  - fields with Undo, Redo and the session labels, bulk edits, reverts, and refusals
  - tags and products, including reverting a product to the scanned one
  - merge, fold, promote, split and dismiss
  - collections, including undoing a deletion
  - suggestions and history, including undoing an entry by id
  - lexicons and choices
  - the desk: folders, a product from a folder, linking a folder, ignoring one, the 5,000-file limit
  - a library locked by another writer, which answers 503 at once and records nothing

  The suite is at 274.
- **On a copy of the scratch scan of the real library** (235,087 dossiers; the original scan was
  left untouched):

  | Step | Time |
  | --- | --- |
  | Rename | 0.02 s |
  | Undo or redo | 0.02-0.03 s |
  | Tag 200 assets | 0.07 s |
  | Author on 200 assets | 0.03 s |
  | Add 200 to a collection | 0.04 s |
  | Accept 300 variant groups in one step (the window: 1.3 s, 5-8 s cold) | 0.76 s |
  | Undo that batch | 0.16 s |
  | Lexicons (1,167 author terms) | 0.04 s |
  | History | 0.02 s |
  | The desk's top level (1.55M unattached files, as in the window) | 7.5 s |
  | `Runtime/Libraries` | 1.7 s |

  The desk's counts run on the server's thread pool, so other requests are not held up.
- **Edits that link files** (a product from a desk folder, linking or unlinking files, their Undo) took
  3.4-18 s each on that copy: each one re-applied every file link of the root (1.5M files), and found
  each linked file's home entry by scanning the one Daz container's 235k entries. They now apply only
  the files they name, plus the other linked files sharing a home with them, and look homes up
  through the asset's ledgers. Through the service, on a fresh copy (69-file folder):

  | Step | Before | After |
  | --- | --- | --- |
  | New product from the folder | 18.4 s | 0.21 s |
  | Undo it | 6.9 s | 0.12 s |
  | Link the folder to a product | 18.3 s | 0.09 s |
  | Undo it | 3.4 s | 0.04 s |
  | Link 5 files | 4.5 s | 0.08 s |
  | Undo it | 3.5 s | 0.04 s |

### 6g, part 1: jobs and environments

`exchange/service/jobs.py` and `watch.py`. The routes are in `docs/api/openapi.json`, tagged *jobs*
and *environments*. 6g is split in two PRs, along the shell chunks they serve: part 1 is what 6h
(environments and scanning) and the lexicon editor's "Apply to library" need; part 2 brings
requisitions, process prerequisites and endpoints for 6i.

- **Jobs are worker processes** (the phase 6 decision), as the window's `ScanRunner`: `python -m
  exchange <command> --progress-json` with the service's library, threshold and definition folders.
  Its JSON lines become the job's progress and its report. The service's token is not passed on, and
  on Windows the worker opens no console window.
  - `POST /jobs/detect {folder}`: which environments a folder holds (`scan --dry-run`); writes nothing
  - `POST /jobs/scan {folder}`: detect, register and scan a folder (`exchange scan`)
  - `POST /jobs/rescan {environments}`: rescan some environments, or all
  - `POST /jobs/classify {regroup, environments}`: classify again after lexicon edits ("Apply to
    library"); `regroup` also regroups hand-installed Daz products. It prints one JSON result, read
    when it ends.
  - `POST /jobs/{id}/stop`: kills the worker. A scan keeps what it finished (it commits as it goes);
    a classification is not saved (one transaction).
- **Following a job:** `GET /jobs/{id}?since=<version>&wait=<s>` returns as soon as the job's version
  passes `since` (at most 25 s), so progress arrives without a polling loop and without streaming
  through the shell's proxy. `GET /jobs` lists running jobs first, then the 20 latest finished ones,
  with a version of its own. Reports come with the job once it ends: a scan's `ScanReport`, or
  `result` for classify.
- **One writing job at a time** (scan, rescan, classify), as in the window: another writer, registering
  environments or changing their settings answers **409** until it ends or is stopped. Detection only
  lists folders and may run beside it. Edits during a scan may find the library busy (**503**, 6e).
- **Environments** (not curation, so not undoable; written on the editor's write connection):
  - `GET /environment-types`: the definitions, with handler, multi-root, fallback, always-ignored
    globs and variants
  - `GET /environments/discover`: game, engine and content-library folders found on this PC (the
    wizard's first step); a failure lists nothing, as in the window
  - `GET /environments/mo2-profiles?folder=`: an MO2 instance's profiles and the selected one
  - `GET /environments/{id}`: its roots and settings (`user_config`, `layer_config`)
  - `POST /environments/register`: the wizard's third step: environments with their roots and
    settings, and folders never to index (unticked ones inside an added folder). Then
    `/jobs/rescan` scans them.
  - `POST /environments/{id}/config`: change settings (`exchange env config`): ignore rules, MO2
    profile, visibility, endpoint folder. The fields given replace the ones it has; null or an empty
    list removes one; unknown keys are refused (422).
- **Change notices** (`watch.py`, the window's `ChangeWatcher` without Qt): `GET /changes` lists the
  environments whose roots changed since they were last scanned, and waits by version like jobs.
  A rescan clears what it scanned; new roots are watched after each writing job and registration. It
  needs `watchdog`, now in the `service` extra; without it `available` is false.
- **The service stops its jobs** when it stops (`--exit-with-stdin`), so no worker outlives it.
- **Endpoint settings:** the API takes the endpoint as a folder, as the CLI and the window's
  `set_endpoint` write it. The window's add-environment wizard writes `{"mode", "value"}`, which
  requisitions now read too (6g, part 2).
- **Tests:** `tests/test_service_jobs.py` (10; the suite is at 285) covers:
  - the token
  - detect, then register (with settings and an excluded folder), then rescan with progress, the
    report and the sidebar
  - scanning a folder, then classifying
  - bad folders, unknown environments and types, bad settings
  - one writer at a time with detection beside it, waiting without a change, and stopping (with a
    stand-in worker)
  - a failing worker's message
  - closing the service stopping its jobs
  - settings: replace, remove, validate, MO2 profiles
  - environment types and discovery (with a stand-in)
  - change notices, cleared by a rescan
- **Through `exchange serve` on a fresh copy of the scratch scan of the real library** (235,043
  assets). Detection and the rescan read the real Daz folder; they write only to the copy.

  | Step | Time |
  | --- | --- |
  | Environments / environment types | 0.22 s / 0.02 s |
  | Discover this PC (162 places found, 3 matching a Daz type, 2 MO2, 86 Unreal projects) | 1.6 s |
  | Detect the Daz library (`scan --dry-run`, walks 3,558,616 file names) | 272 s |
  | A rescan's first progress line | 0.02 s |
  | Stop the rescan | 0.02 s |
  | Classify (235,043 assets, 219,288 tagged) | 48.5 s |

  While the rescan ran, a second writing job was refused (409) and the sidebar answered in 1.8 s.
  The library read normally after the stop. The scanner's discovery phase reports no counts (0/0),
  so a UI can only say "Discovering files" until phase 2, as the window does.

### 6g, part 2: requisitions

`exchange/service/requisitions.py`. The routes are in `docs/api/openapi.json`, tagged
*requisitions*, *processes* and *jobs*. What 6i (requisitions, the queue, Settings › Processes and
Endpoints) needs, as the window's *Requisition to…* dialog, queue view and settings use it.

- **Planning** only reads:
  - `POST /requisitions/routes {uids, environment}`: the chains that take these assets (and up to
    50 children of each of the first 20 products, 200 in all) there: the dialog's route list
  - `POST /requisitions/plan`: per asset, its items (a product's children too) with their chain
    (ids and names), source, options and problems; the option forms of the processes in it (their
    parameters and the values the plan would use); warnings; how many items are included. Options
    in the request win over a preset's, or over those last used with each process; `excluded`
    leaves items out; `endpoint_folder`, `on_collision` and `name` as in the dialog.
  - `POST /requisitions/queue` takes the same request, plans it again on the server and queues
    every plan with something included (a client never sends a plan to trust). Its options become
    each process's last used.
- **The queue:** `GET /requisitions` (waiting or running in order, then finished, newest first),
  `GET /requisitions/{id}` (items with outputs, every file written), and `hold`, `move`, `resume`
  (with how to settle collisions), `rebuild` and `check-stale`. These write on the editor's
  connection and answer 409 while a job writes, as the window disables them during a run.
- **Jobs:** `POST /jobs/requisitions {ids}` runs the queue (or some requisitions) in a worker; its
  progress says the requisition, item, step and message, and its result what ran. `POST
  /jobs/remove-output {requisition}` moves a requisition's output to the recycle folder, puts
  back what it overwrote, and rescans. Stopping a run queues the running requisition again.
- **Processes:** `GET /processes` (state, prerequisites green or red with how to fix them, chain
  problems, options, and what trusting allows), `POST /processes/install {folder}` (untrusted) and
  `POST /processes/{id}/trust` (the client asks first). `GET`/`POST /tools` set where external
  tools are (a path must be a file; null forgets it).
- **Presets:** list (shipped and the user's), save, delete (not shipped ones), and the options last
  used.
- **Endpoints:** `GET /endpoints`: each environment's output folder, whether the user chose it, its
  visibility, or why it has none (no online folder). Change them with `/environments/{id}/config`.
- **The wizard's endpoint setting:** `requisitions/endpoints.py` now reads the window wizard's
  `{"mode", "value"}` as well as a folder: a Daz content directory, an Unreal content folder
  (relative to the project), one Exchange-managed MO2 mod by name, or a new MO2 mod per requisition
  (the default). A relative folder is relative to the environment's first root. Requisitions into
  environments the wizard added used to fail with a TypeError.
- **Tests:** `tests/test_service_requisitions.py` (7; the suite is at 292) covers:
  - the token
  - processes: install, trust, prerequisites and options; tools; presets
  - endpoints, including a wizard setting
  - the wizard's settings in `configured_folder`
  - routes, plans (options, bad values, excluded items, unknown assets, environments and presets),
    queueing and last-used options, move and hold, a run as a job, check stale, rebuild, and removing
    output as a job (which puts back what a rebuild overwrote)
  - a review checkpoint and resume
  - queue actions refused while a job writes, and a stopped run's message
- **On a copy of the scratch scan of the real library** (planned and queued on the copy only; nothing
  ran, so nothing was written beside the real library):

  | Step | Time |
  | --- | --- |
  | Processes (Convert mesh ready: Blender found) | 0.22 s |
  | Endpoints | < 0.01 s |
  | Routes for 3 Genesis 9 hair products | 0.47 s |
  | Plan them (120 items: copies, and Convert mesh for a beard) | 0.51 s |
  | Queue them | 0.52 s |
  | The queue / hold / check stale | 0.02-0.03 s |

## Phase 7: Project homes, part 1

**Frozen by the restart (2026-10-28):** what's below is built and tested, and stays as it is. Part 2 is cancelled; see *The restart*.

Approved 2026-10-24 with every recommended answer. Goal G5. Phase 6 had not merged past 6c when
this was planned, so the Workspace views (Card and Table for the first four signatures) move to
part 2, and G5 is not met by part 1: its "done when" needs the Workspace.

| # | Repo | What |
| --- | --- | --- |
| docs | core | Identity v2, the overview and the game data model; the spec's *Projects* section brought in line with the game data model; this plan |
| 7a | core | `exchange.projects`: the project home formats, a parser, record schemas for `NPC_`, `RACE`, `FACT` and `LOT_`, the validator; `exchange project init`, `project validate` and `project checkpoint`; `docs/PROJECT_HOME.md` |
| 7b | core | Gap claims opened by validation, fast capture (`exchange capture`), `exchange claims list` and `claims ack`, dossier hints |
| 7c | shell | A git checkpoint of the project home before each bypassed session, through the core's CLI |

**In scope:** the formats (identity, goals, records, claims, the coverage rules file), record
schemas, validation, gap claims, fast capture and the bypass checkpoint. **Out of scope:**
ladder, coverage and mining claims; other signatures; the compile Process; the Casting Board;
any change to the asset database or scanning. Test only against scratch project homes, never
the user's (the project-homes root is in `USEFUL_PATHS.md`).

Decisions:
1. **Dossier IDs** (checked 2026-10-24 on copies of the test fixtures):
   - **They survive:**
     - a plain rescan
     - files that go missing and come back (the entry is retired, then revived)
     - a Daz product reinstalled in another content directory (matched by SKU)
   - **They don't survive:**
     - a moved or renamed file or folder product (new dossiers; the old ones keep only retired entries)
     - a Daz folder product regrouped after a lexicon change
     - the automatic exact-duplicate merge, which deletes the losing dossier without an alias
     - a rebuilt database
     - `env forget`
   - **The user's own merges** keep an alias, but lookups of the old uid return the emptied dossier.
   - **In phase 7 (7b):**
     - the resolver follows `dossier_alias`
     - validation keeps a hint per linked dossier in `.exchange/dossier-hints.json`: name, type, environment, SKU, path and hash
     - a uid that no longer resolves, or has only retired entries, opens a gap claim to relink it, listing candidates found by the hint
   - **Later, in a separate core PR before Character Look is used for real:** duplicate merges record an alias, dossiers that records link to count as user work, and API lookups follow aliases.
   - **With the Casting Board:** move detection during scans.
2. **YAML frontmatter** (the game data model wins over the spec's TOML), parsed with PyYAML
   `safe_load`, a new core dependency. Exchange never rewrites YAML a person wrote. It creates
   new files, and edits only the `needed_by`, `status` and `triage` lines of gap claims it made.
3. **Identity and goals:** `IDENTITY.md` (capitals, as in the spec) and a single `goals.md`
   whose frontmatter lists goals `G1…` with statuses planned, active, done, dropped.
4. **No `domains/` or `data/` in phase 7.** In a game project the records are the domains; `data/`
   stays reserved for data that are not records (Bethesda plugin text, phase 10).
5. **Schemas:** a small YAML format (field types text, int, number, bool, date, enum, link,
   dossier, process, claim, list, object; `required_at` a maturity level), the same in the core
   and in a project home's `schemas/`. A project's schemas add new signatures only; they never
   change the core's.
6. **Gap claims** come only from links:
   - a record link that does not resolve, or whose target is not mature enough
   - a broken dossier link

   Mistakes inside a file are reported, not turned into claims. A record at Spec or above needs
   each record it links to at no less than the lower of its own maturity and the field's cap
   (Spec unless the schema says otherwise). Links from Sketch records are not checked.
7. **No duplicates:**
   - one gap claim per target record while one is not done or dropped; its `needed_by` list grows
   - a dropped gap claim is never reopened
   - a gap that returns after its claim was done opens a new claim linked to the old one
8. **Gaps that get fixed:** validation moves the claim to `review` with a dated note, never to done.
9. **Triage:** gap claims carry `triage: new` until `exchange project claims ack` clears it (until the
   triage inbox view exists).
10. **Fast capture:** `exchange capture "<line>"`. A line starting with an editor ID
    (`NPC_DockMaster: gruff harbormaster…`) creates a Sketch record; any other line creates an
    idea claim, attached with `--on <ID>`. Unattached ideas are allowed and reported as unfiled.
11. **Which project and the checkpoint:**
    - **Which project:** `--project`, else the project home containing the current folder, else the
      default named in `<data>/projects.toml`, which also holds the projects root.
    - **When the checkpoint runs:** before every launch of a bypassed session in a project home,
      resumes included.
    - **What it commits:** all changes, never an empty commit.
    - **If it fails:** the session does not start; the dialog offers **Start without checkpoint**.
      A home that is not a git repository fails with a message saying to set up git
      (`exchange project init` runs `git init`).
12. **Docs:** identity v2, the overview and the game data model live in this repository; the
    shell's handoff doc points here.
13. **Part 2** (after 6d-6j): the identity interview, the devlog, mission control, the claims
    board, the Card and Table views, and the project index.

Smaller choices:
- no project index in the library database yet: validation reads the files each run
- unknown fields are warnings, not errors
- maturity is stored as 0-4; the CLI also accepts the level names
- editor IDs match `^([A-Z]{3}_|[A-Z]{4}_)[A-Za-z0-9][A-Za-z0-9_]*$`: a signature ending in `_` uses that underscore as the separator
- a claim whose date and slug are taken gets `-2`
- an unresolved process link is a warning only (the Daz → Unreal process does not exist yet)
- records of signatures without a schema (`PACK`, `CELL`, `DIST` …) are allowed: their `id` and maturity are checked, and links to them resolve when the file exists

### 7a: formats, schemas and validation

The formats are in `docs/PROJECT_HOME.md`.

- **`exchange.projects`:**
  - **`frontmatter`:** YAML front matter with PyYAML's safe loader (the C one); a repeated key is an error.
  - **`schema`:** the schema format and the core's schemas in `projects/schemas/` (`NPC_`, `RACE`, `FACT`, `LOT_`).
  - **`home`:** finding a home (`exchange.project.toml`), `init_home`, `projects.toml`, `resolve_project`.
  - **`git`:** the repository and checkpoints.
  - **`validate`:** `validate_home()` returns findings (errors, warnings) and gaps.
- **Commands:** `exchange project init PATH`, `project validate`, `project checkpoint [--for PATH]` and `project config`.
- **Not in the plan, needed by checkpoints:** this machine has no global git identity (each
  repository sets its own), so a new project home could not commit. `projects.toml` also holds
  `git_name` and `git_email`: `project init` writes them into the new repository, and commits use
  them when git has none of its own. Without either, the error says how to set them.
- **Checkpoints:**
  - They exclude `.exchange/` even when `.gitignore` does not.
  - They refuse a home that is not its own repository's top level.
  - They never make an empty commit.
- **Tests:** `tests/test_projects.py` (32), all on scratch homes. The suite is at 254.
- **Speed:** 2,001 records validate in about 0.75 s. The first read of freshly written files is
  far slower on the dev machine, about 7 ms per file, which looks like the virus scanner.
- **Dossier links against the real library:** a scratch home linked to 300 random products from
  the scratch scan of the real Daz library (235,087 dossiers), plus 5 uids that do not exist.
  - The 300 real links resolved and the 5 bad ones became dossier gaps.
  - Validation took 0.14 s.

### 7b: gap claims and fast capture

The formats and rules are in `docs/PROJECT_HOME.md` (*Gap claims*, *Triage*, *Fast capture*).

- **`exchange project validate`** now writes, unless `--check-only`:
  - the gap claims (`projects/claims.py`, `sync_gap_claims`)
  - `.exchange/dossier-hints.json`
- **One claim per piece of work.** The key is the target record and the work: maturing a record, or
  relinking its dossier.
  - This refines decision 7, which spoke of one claim per target. A record can need both a relink
    and more maturity, and they are different jobs.
- **Exchange's edits to its own claims** go through `frontmatter.set_keys`, which:
  - rewrites single top-level keys in place
  - appends notes to the body
  - refuses the edit if parsing the result shows any other change
- **Not resolved when unsure:**
  - a claim whose target or needers have errors
  - relink claims, when there is no library to check against
- **Relink candidates** come from the hint, by the same file hash, product key, or name and type,
  among live dossiers that are not merge aliases.
- **`exchange capture`** (`projects/capture.py`) and **`exchange project claims list` / `ack`**.
- **Fixed on the way:** `frontmatter.dump` wrote a mapping holding only plain values as one flow
  line (`{id: NPC_A, maturity: 0}`). It now writes a line per key.
- **Tests:** `tests/test_gap_claims.py` (11). The suite is at 265.
- **Against the scratch scan of the real Daz library** (235,087 dossiers, not enriched, so there
  are no hashes): 20 records linked to uids that do not exist, each with a hint copied from a real
  product.
  - All 20 became relink claims, each listing the right product by its product key.
  - Validation took 3.6 s, about 0.18 s per broken link: finding a product key reads all of
    `dossier_field`, which has no index on values. That is fine for the odd broken link. If many
    links break at once, an index there would be the fix (a database change, so not in phase 7).

## How we work

- **Plan, then build.** For each roadmap phase, propose a plan with open questions and a recommended answer for each, then wait for approval. So far the user has approved the recommended answers each time.
- **Ask instead of guessing** when the spec is ambiguous or seems wrong.
- **Pull requests:**
  - One branch and PR per chunk (e.g. 3a/3b/3c); the user reviews and merges.
  - Base the next PR on the previous one when they depend on each other.
  - Don't push more commits to a PR branch after telling the user it's ready: #2 was merged before two fixes landed and needed a follow-up PR (#3).
- **Check against real data.**
  - Read-only scans of the user's real libraries (into a temp database, never into the scanned folder) found real bugs in every phase.
  - Dry-run detection (`exchange scan PATH --dry-run`) only lists folders.
  - **Requisitions write,** so their real-data checks use:
    - a copy of the scanned database
    - an endpoint in a scratch folder (`--endpoint`), or a copy of the source assets
    - `EXCHANGE_DATA_DIR` pointed at scratch, keeping work folders, logs, locks, tool paths and the trust list out of the user's real Exchange folder

    Nothing in a real environment is written to.
  - **Apps with windows:** Blender runs headless and can be checked any time. Daz Studio opens a window and may stop on a prompt, so it is only launched while the user is at the computer.
  - **A full real scan takes about 10 minutes without enrichment, and hours with it** (R3c: stopped after 1 h 43 min); the 3a slowdowns only showed at that size, so run one (`--no-enrich`) before a PR that touches scanning. For anything else, use a sample library (`AGENTS.md`).
- **Constraints from the kickoff:**
  - Windows and Python 3.11+, using `pathlib`.
  - Scanning is strictly read-only.
  - Minimal dependencies.
  - pytest tests with fake environment fixtures.
- **Dev setup:** the system `python` is 3.10, so use the 3.12 venv:
  ```bash
  py -3.12 -m venv .venv
  ```
  ```bash
  .venv/Scripts/python -m pip install -e ".[dev]"
  ```
  ```bash
  .venv/Scripts/python -m pytest -q
  ```
  - The CLI is `.venv/Scripts/exchange`.
  - `gh` is installed. In Git Bash it may need the PowerShell PATH; it works from PowerShell.
- **Shell gotchas:**
  - PowerShell `Get-Content`/`Set-Content` mangle UTF-8 (they garbled PR descriptions once). Write files from Python.
  - Python one-liners in bash heredocs that contain `\n`/`\u` escapes got mangled. Use the Edit tool for code edits containing escapes.
  - Don't edit the source while a long real-library scan runs: some modules are imported partway through, and one run crashed that way.
  - Bash heredocs holding Python with triple quotes sometimes fail to parse ("unexpected EOF"). Write the script to a file with the Write tool, then run it.

## Decisions made (do not reopen without the user)

Phase 1:
- **Daz containers:** the container is the content directory; products are product dossiers from manifests.
- **MO2 in phase 1:** detection, mod containers, `meta.ini`, and a product per mod.
- **MO2 environment:** one environment per MO2 instance. The profile is configuration, and each mod records which profiles enable it.
- **Lexicons:** the tokenizer runs now; lexicon matching is phase 3 (now done in 3a).
- **Mesh type:** `mesh` is an abstract type, refined to static or skinned mesh during enrichment.
- **Unidentified threshold:** 0.5.

Phase 2:
- **Daz Studio:** one environment per PC, holding every content directory (including Daz Connect).
- **Dependencies:** Pillow and numpy are core dependencies; watchdog (3c, the file watcher) is optional, now in the `service` and `dev` extras (PySide6 was the `ui` extra until R2c).
- **Mesh thumbnails:** a small numpy/Pillow renderer for glTF/GLB/OBJ. Other formats get an icon. The Blender bridge exists since 4b, but thumbnails don't use it yet.
- **Inspector:** read-only in phase 2; editable since PR 3b.
- **Exact duplicates:** merged automatically, with *unknown provenance*. Never for dossiers the user has edited.
- **File watcher:** deferred to phase 3 (PR 3c). There is a *Rescan changed* button for now.
- **Unreal asset types:** from name prefixes (`SM_`, `SK_`, `T_`, `M_`/`MI_`, `BP_`, `.umap`). `.uasset` class parsing is **not** done. Embedded thumbnails are found by scanning for PNG/JPEG signatures.
- **Offline roots:** they keep their entries; `rescan` suggests `env forget` after 30 days.
- **Material presets:** stay texture-set dossiers. That's about 83k of 225k dossiers in the real library; the user chose to keep them.

Phase 3:
1. **Variant grouping** is *suggested*, accepted or rejected in batches, never automatic.
2. **Lexicon edits** are TOML files in the user's definitions folder (`lexicons/<id>.toml`), replacing the built-in of the same id. They can be shared and diffed.
3. **Accepting a texture link** puts the texture files in the mesh's entry (role `linked`, recorded in the override layer). There is no separate texture-set dossier.
4. **File watcher:** `watchdog` (PR 3c).
5. **Hand-installed Daz content** is grouped into products by folder at scan time, at confidence 0.6.
   - **Lexicons, not path rules** (decided 2026-10-21), tell products from the folders people sort them into:
     - A *theme* lexicon (Sci-Fi, Fantasy, Historical ...) and the category names (Props, Vehicles) mark category folders. So do folders starting with `!`.
     - A *known authors* lexicon marks vendor folders. Scans build it from DIM manifest artists and `data/<vendor>/` folders, and you can edit it.
     - Neither kind of folder is ever a product. Products below a vendor folder get that author.
     - Users' `!!sorted` hierarchies are their own categories, and the products inside them are real.
   - Moving re-sorted products back to their manifest paths is a separate library-maintenance tool (it writes), not part of scanning.
6. **Default lexicons:** tight, about 15 tags; tune them against real folders. Mesh-size and topology signals come later.
7. **Bulk edit:** tags, type, author, license, notes, and adding to collections. Names stay single-item.
8. **Undo:** unlimited within a session. The log is permanent but isn't replayed across restarts.
9. **Desk actions (3c, within the approved plan):**
   - *Not an asset* is a user field (`not_an_asset`). Dismissed dossiers leave Unidentified and default views; `is:dismissed` finds them.
   - *Ignore this folder* adds `<folder>/**` to the environment's ignore rules. It is an undoable curation action, and the folder's unattached files leave the desk at once.
   - A folder of more than 5,000 unattached files can't be made into a product or linked: that's a category, not an asset.
   - Accepting a batch of suggestions is one undo step.

Phase 4 (approved 2026-10-22, all recommended answers):
1. **First conversion** (open): what cross-figure converts first (characters, clothing, hair) and with which tool. The recommendation was clothing via Transfer Utility and auto-fit, pending the user's own workflow.
2. **VaM backporting and DS3 legacy conversion** move to phase 5, with the VaM environment.
3. **Daz output:** an `Exchange Conversions` folder beside the library. Exchange never edits the user's Daz Studio settings; adding it in the Content Directory Manager (of the main instance) is the user's one-time step.
4. **Daz Studio window:** accepted during jobs, as a separate instance (`-instanceName Exchange`).
   - **Its settings** (decided 2026-10-22): before each job, Exchange copies the update setting (`AutoUpdate`) and the content, Poser, import and MDL directory lists from the main instance's registry key (`HKCU\Software\DAZ\Studio4`) into the Exchange instance's (`Studio4[Exchange]`). The main key is only read. So a folder added in the main instance reaches jobs too.
5. **Pipelines:** built-ins ship with Exchange; the user's go in `<data>/pipelines/`, trusted before they run.
6. **Types:** operations take and make named artifact types (`Files` accepts any), checked along the chain. Dossier types are unchanged.
7. **Execution:** one worker process runs the queue, reporting progress like scans.
8. **Sidecars:** `.exchange/<requisition>.json` in each output container.
9. **Recycle folder:** Exchange's own, under the data folder; nothing is hard-deleted.
10. **After writing:** only the output's root is rescanned.

## Architecture in one page

```
src/exchange/            core, never imports Qt (a test enforces this)
  paths.py globs.py      case-insensitive path/glob helpers (Windows)
  errors.py
  definitions/           TOML definitions, strict loader (environments, dossier types, lexicons)
    builtin/environments daz_studio, skyrim_se, mo2_generic, unreal_project, loose_files (fallback)
    builtin/dossier_types product, mesh/static/skinned, texture, texture_set, material, skeleton,
                          animation, audio, daz_*, skyrim_npc, unreal_*
    builtin/lexicons     category, variant, texture_channel, structural, index, ignore, theme,
                          authors (generated: scans add words; the user's file adds and excludes)
  db/                    connection (migrations, backup before migrating, busy_timeout), repository
    migrations/          0001 initial · 0002 roots/deps/thumbnails/FTS · 0003 scan.unattached_files
                         · 0004 library_setting (excluded roots) · 0005 curation · 0006 requisitions
  scanner/
    discovery.py         phase 1: walk (never follows links; skips excluded folders)
    detection.py         signature scoring, split into roots, same-type nesting collapsed
    identification.py    phase 2 engine: products, children, entries, links, retirement, FTS
    classify.py          end of phase 2: lexicon/folder/metadata tags, structural roles, confidence
    layers/              organizational-layer handlers: daz (manifests, Connect, folder products),
                         mo2 (incl. global instances), unreal, folder
    enrichment.py        phase 3: hashing, duplicate merge, mesh stats, Daz deps, thumbnails
    meshes.py formats.py thumbnails.py tokenize.py readonly.py
    scan.py              run_scan / run_rescan / regroup, grouping roots into environments, offline roots
  lexicons.py            lexicon matching (tokens, plurals, multi-word) and writing user lexicons
  curation.py            Curator: every user change as logged, undoable state changes
  suggestions.py         texture-link and variant-group proposals; listing
  links.py               applying user file links (override layer) to entries
  locks.py               cross-process locks (one queue worker; one job per external app)
  pipelines/             packages: manifest (pipeline.toml), operations (API), core_ops,
                         registry (find, trust, load, prerequisites, tool paths with globs),
                         builtin/copy_entry, builtin/convert_mesh (Blender)
  requisitions/          plan (routes, chains, product plans, queueing; lenient defaults), presets
                         (files; last-used options), endpoints, runner (queue,
                         work folders, cached steps, checkpoints, writing, sidecars, rescans),
                         sidecars (written and read back by identification), lifecycle (resume,
                         hold, move, remove, stale, rebuild)
  cli_requisitions.py    processes, tools, requisition, test-process
  bridges/               base (run with timeout and log, one job per app, close the whole process
                         tree), blender (headless wrapper), daz (DazScript wrapper, separate
                         instance), command-line tools; operations reach them via ctx.bridge(app)
  library/               search language (FTS5 + filters), query API (pages, sidebar, detail, collections),
                         desk (unattached files by folder, one level at a time over the (root, rel_key) index)
  autodiscover.py        Steam, Epic, Unreal recent projects, Daz registry, MO2 instances
  environments.py        register_root (the user's type wins, except that a root joined to a single-root
                         place can't retype it), can_forget_root (R3d-5), excluded folders
  service/               exchange serve: the local API (FastAPI), its models and OpenAPI schema (6b)
  projects/              project homes: front matter, record schemas (schemas/*.yaml), finding and
                         creating homes, git checkpoints, validation (7a)
  cli.py cli_curation.py command line (also cli_service.py, cli_projects.py)
tests/                   pytest; fixtures in tests/fixtures/envs; builders.py makes GLB/uasset/PNG/Unreal/
                         Daz Connect content and holds report helpers;
                         fixtures/pipelines holds test packages (stamp_images, bridge_demo) and
                         fixtures/fake_apps stand-ins for blender.exe and DAZStudio.exe
```

Key ideas:
- **An environment has roots.** Containers and files belong to a root, and paths are stored relative to it.
- **Identity across rescans:** a dossier is matched by its entry's (container, identity key). Products with the same `product_key` (a Daz SKU) become one dossier with an entry per container.
- **Override layer:** the user's work, keyed by dossier uid, with no foreign keys, so scans never touch it. It covers `override_field`/`_tag`/`_link`, `dossier_alias`, `collection`/`collection_member` and suggestion decisions. `dossier_effective` gives the effective values.
- **Curation engine (`curation.py`):**
  - Every action is a list of state changes (field, tag, parent, link, alias, entry, dossier, collection, member, suggestion, lexicon).
  - The engine reads each state before writing it, so the exact inverse is logged in `curation_log`.
  - `undo(log_id)` applies the inverse as a new action; redo is undo of undo.
- **Merged entries:** `entry.moved_from` marks an entry moved onto another dossier (merge, fold, duplicate, link). A rescan then leaves that dossier's scanned name and type to its own entries.
- **Generated lexicons (authors):**
  - Scans store the words they find in `lexicon_generated`, per root.
  - `lexicons.with_generated()` merges them with the user's lexicon file. Spellings that squash alike (`AeonSoul`, `Aeon Soul`) join one term.
  - The file's `exclude` list holds names the user removed; they are never added back.
  - Lexicon edits apply on the next rescan, or straight away with `exchange classify --regroup`.
- **Editing in the window (3b):**
  - The window reads on a read-only connection. Edits go through `LibraryService.edit()` on a second connection with a 1.5 s busy timeout, so an edit made while a scan holds the write lock fails with a message instead of freezing the window.
  - `edit()` keeps a session undo/redo stack of curation log ids. Redo undoes the undo, as in the core.
  - The inspector's signals carry the dossier uids its editors were built for, so a field committed as the selection moves still edits the right dossier.
- **Requisitions (4a):**
  - **Planning:** a requisition is planned (routes, chains, a product's children), queued, then run by one worker.
  - **Running:** each step's result is cached in the requisition's work folder, so shared steps run once and resuming after a checkpoint redoes nothing.
  - **Writing:** output goes only to the endpoint. Every write is logged in `requisition_write`, and replaced files go to the recycle folder.
- **Sidecars connect output to its source:**
  - **On disk:** `.exchange/<uid>.json` in the output container lists, per asset, its dossier uid, its source entry, the pipelines, the options and the files written.
  - **When scanned:** identification reads sidecars, so the output files join the source dossier as *requisitioned* or *copied* entries (with `requisition_id` and `source_entry_id`) instead of becoming new dossiers. That works after a lost database too.
- **Trust and code:**
  - **Trusting:** a user pipeline's code is imported only once the package is trusted, by a fingerprint of its manifest and code; any change needs trusting again. Built-ins are trusted.
  - **External apps:** operations reach them only through `ctx.bridge(app)`, and every app must be declared as a tool prerequisite.
- **Requisitions in the window (4c):**
  - **Planning:** the dialog plans each selected asset (batch) through the service's read connection, and queues through the write connection.
  - **Options:** forms are generated from the manifests. They're filled from a preset if one is chosen, otherwise from each pipeline's last-used options; both are lenient, dropping options a pipeline no longer has.
  - **Running:** the queue runs in the window's one background runner, so a scan and a queue run never write at once.
  - **Removing output** runs as a background `exchange requisition remove`, since it rescans.
- **Bridges (4b):** every app job is the same shape, so pipelines never manage processes:
  - the arguments go to a JSON file
  - a generated wrapper (Python in Blender, DazScript in Daz Studio) runs the script and writes a result file
  - errors quote the end of the app's log
  - one job per app runs at a time
  - the app's whole process tree is closed afterwards
- **Confidence:** `dossier.confidence_base` is identification's own confidence. Classification adds evidence on top into `dossier.confidence`, so re-classifying never compounds.
- **Read-only, enforced by tests:**
  - All file reads go through `scanner/readonly.py`.
  - Thumbnails and user lexicons are written outside scanned folders.
  - Scans refuse a database inside the scanned folder.

## Measured on the real machine

**Daz `My Library`:** 3.56M files and 4,652 manifests.
- **Phases 1-2:** about 7 minutes, giving 4,393 products and about 225k dossiers.
- **3a scan (without enrichment):** 9.5 minutes in total: discovery 2, identification 6.5, classification and suggestions 1.
  - **Speed fixes:** finding each file's product folder was quadratic (2+ hours, never finished). Refreshing the search index rebuilt the effective-tag view for every batch.
  - **Results:** 14,497 products and 235k dossiers; 93% of dossiers got a tag.
- **Hand-installed products:** about 10,060 folder products.
  - **History:** the first version made 23,888, and 14,788 of those sat inside another product (`Wolf 2/Materials/Eyes`). Folding them in gave 9,991.
  - **Problem then:** category and vendor folders swallowed products, e.g. `poses/dm` (206 folders) and `vehicles/!!sorted/sci-fi` (68).
  - **Now:** lexicons stop that. The largest products are real products and pose packs.
- **Known authors:** 1,316 found. Vendor folders give 3,164 products an author (Zeddicuss, Sue Yee, DAZ Originals, 3DUK ...).
  - **Not found:** `dm` is in neither a manifest nor `data/`, so it has to be added by hand (`exchange lexicon add authors dm dm`).
  - **Noise:** a few `data/` folders are products installed straight into `data/` (`Nyan cat`).
- **Unattached:** 1.55M files belong to no product, down from 2.4M.
  - A product's own name finds its `data/` and `Runtime/` files, but only when that name labels three or fewer folders there.
  - Generic names (`Chest`, `Genesis 3`, `Character`) once pulled hundreds of thousands of unrelated files into one product.
- **Suggestions:** 10,028 variant groups (spot checks: material, color and on/off presets), but only 1 texture link: Daz materials reference their textures from `.duf` files, not by name.
- **Search:** `tag:food` takes 10 ms with the `dossier_tag_lower` index (0.4 s warm, 9.5 s cold without it).
- **Missing:** about a third of the files the manifests list are genuinely absent on disk.
- **UI:** a page of 200 takes 0.2-0.7 s, the sidebar 1.7 s (main thread), search about 0.25 s.
- **Edits (3b, on a copy of the library):** a rename takes 0.2 s, and changing a field, tag or collection on 200 assets takes under 0.1 s. Undo takes 0.1 s, a dossier's detail 0.2 s, a collection's page 0.8 s.
  - Bulk tagging was 2.7 s: its suggestion inserts each committed on their own. They now commit together, and a bulk tag only proposes words shared by at least two of the names.
- **Desk (3c):**
  - **Unattached files:** 1.55M in total. Counting the top level takes about 7 s and `Runtime/Libraries` about 2 s, on a worker thread. 580k of them are Poser content in `Runtime/Libraries` (392k in `Character`).
  - **Suggestions:** a page of 300 loads in 0.01 s. It was 4.6 s, because the name was joined from the effective-dossier view.
  - **Batch accept:** 300 variant groups take 1.3 s to accept and 0.3 s to undo once the cache is warm, and 5-8 s for the first batch after opening.
    - It was 100 s: each moved entry checked all 235k ledgers for emptiness. Now only the ledger it left is checked.
  - **Watcher:** watching `D:\Daz 3D\Studio\My Library` starts at once, and reported no events while idle.
- **First open:** migrating a 1.6 GB library takes about 17 s, mostly the backup.
- **Requisitions (4a, a copy of the library, writing to a scratch folder):** copying a real Daz product ("XI Japanese Racing Bike": 4 children, 18 files) takes 3.3 s, including the rescan.
  - The output keeps its content layout (`data/`, `Runtime/Support/`, `Vehicles/…`). It becomes 5 *copied* entries on the original dossiers, with no new dossiers, even with a copied DIM manifest.
  - It took 92 s at first: the rescan of the new root reclassified and re-suggested the whole Daz environment. Scans now classify and suggest only for the roots they scanned.
- **Blender (4b):** the built-in *Convert mesh* pipeline turned a real Sketchfab glTF (*Dwarf Helmet*, copied to a scratch folder) into FBX, OBJ, glTF and GLB. Blender 4.1 was found by a glob over `Blender */`.
  - **Speed:** about 3 s of Blender per conversion.
  - **Result:** each became a requisitioned entry of the one *Dwarf Helmet* asset.
  - **Fix:** the glTF importer packs textures into the file, so OBJ and separate glTF exports came without them. The script now writes each packed image's original bytes beside the export.
- **The window's requisition flow (4c, on that scratch library):** *Requisition to…* → *Convert mesh* (GLB, scale 0.5) → *Add and run*. The background runner fulfilled it in 5.2 s, and the queue view showed it with its log.
  - **Crash found by the tests:** unchecking a plan row rebuilt the tree inside that row's own change signal, deleting the row Qt was still updating. That was an intermittent access violation; only the summary is rebuilt now.

- **Daz Studio bridge (real Daz Studio 4.24, 2026-10-22):** a trivial DazScript job (report the version and scene, write a file) through `DazBridge`, with `EXCHANGE_DATA_DIR` in scratch.
  - **First two runs failed:** a new `Exchange` instance checks for updates at every start. It found a newer Daz Studio and showed its update dialog despite `-noPrompt` (Daz logs `UpdateDlg displayed while -noPrompt is used`), then quit before running the script, with exit code -1.
  - **Also found:** the instance had found its own content directories, not the user's three (no `Studio3/content`, no `Personal Library`).
  - **Fix:** the bridge copies those settings from the main instance (Decisions, phase 4, item 4), and errors quote Daz's own log (`%APPDATA%\DAZ 3D\Studio4 [Exchange]\log.txt`, copied into the work folder as `daz_studio_log.txt`). The console output was only the content database's `pg_ctl` lines.
  - **Confirmed:** `-instanceName`, `-noPrompt`, `-noDefaultScene`, `include()`, `JSON`, `App.instanceName()` and `App.delayedExit` all work. Arguments with `é` and `✓` arrive intact. The update check reads *Disabled* with `AutoUpdate = 3`.
  - **Timing:** about 22 s per job: 10 s of startup, then the script, then about 8 s for Daz to shut itself down (exit code 0). The bridge used to close it 2 s after the result, mid-shutdown; Daz now gets 15 s (`exit_grace`).
  - **Left running:** Daz's PostgreSQL content database stays up after Daz exits. That's Daz's own behaviour, and it's shared with the user's instance.
  - **Noise in the log:** the user's *Big Bat Send-to-Daz* plugin loads in the Exchange instance too, polling its `cmd.json`. It didn't interfere.

**Loose folders** (`Z:\Content Farm\Sketchfab` and `SWBF Model and Textures`), checked in 3a:
- **Tags:** 77% of 4,728 dossiers got one. SWBF's many *Weapon* tags are correct: the folder is mostly weapon sound effects.
- **Texture links:** 62 suggestions. They're correct on the samples checked, including `DwarfHelmet_Base_Color` and PBR sets.
- **Variant groups:** 25 suggestions, e.g. footstep sounds on wood/metal/stone.

**Discovery:** finds the Daz content directories (registry), the global MO2 instances (Skyrim SE at `...\OutlawArcana` via `base_directory`, Morrowind) and many Unreal projects.

**MO2 instances in USEFUL_PATHS.md:** FNV, Morrowind, Oblivion, Starfield and Fallout 4 detect as `mo2_generic` because only Skyrim SE has a definition. Their game definitions are phase 5.

## Known gaps and good next candidates

- **4d** is now R6 and R7 of the restart: Genesis 9 → Genesis 8 Female (see *The restart*).
- **Not done yet in phase 4:**
  - The `new-process` scaffold and the authoring guide (`PROCESS_GUIDE.md`, roadmap phase 11).
  - **Manual checkpoints in the window:** they show as *Needs attention* with the pipeline's message, and Resume continues. There's no button yet to open the work folder in the app at that point.
  - **Queue mode:** the queue only runs when you press Run; there's no "run immediately" setting yet.
  - Parallel command-line operations: the runner does one step at a time.
  - Blender thumbnails for formats the small renderer can't draw.
- **The Daz Studio bridge has run only a trivial job** (version, scene, one file written), not a real conversion. That's for R6.
- **Rebuilding from sidecars after a lost database** keeps each output with its asset's original uid. The source environment's rescan makes a new uid for the same asset, so the two show as separate assets until merged.
- **Overwriting another requisition's output:** both sidecars list the files, so the asset shows an entry for each until one is removed.
- **Edits run on the UI thread.** Those that change counts (merge, new product, accepted suggestions, retype, undo) reload the sidebar, about 1.7 s on the real library. The first big batch after opening can take several seconds while the database warms up.
- **Settings has only Lexicons.** Dossier types, environments and storage pages are still to come; dossier types are edited as TOML files for now.
- **Known authors from older scans:** a library scanned before the import-folder filter (`data/<asset>_<number>`) keeps those names until its next rescan.
- **Speed:**
  - The sidebar query (1.7 s on the real library) runs on the UI thread. Move it to a worker.
  - Enrichment (hashing) has not been run on the full 3.56M-file library.
  - Classification and suggestions take about 1 minute on 235k dossiers.
  - **Partial scans for development:** a full Daz scan takes about 10 minutes. A proposed fix is a script that builds a small sample library from the real one: every Nth manifest's products plus every Nth hand-installed folder. Small text files would be copied and large binaries written as empty placeholders. Run a full scan before each PR anyway, since both 3a slowdowns only showed at full size.
- **Lexicon tuning:**
  - Expect to keep adjusting the default word lists against real libraries.
  - Vendor folders whose name is in no manifest and no `data/` folder (`dm`) need adding by hand. The lexicon editor (3c) should make that easy.
  - Unattached Daz files (1.55M) are mostly `Runtime/Libraries` (Poser) content and data whose folder names are generic. The Unidentified desk (3c) groups them by folder.
  - Single-letter texture channels (`_D`, `_N`) only count for images whose base name matches a mesh.
- **Unverified:** the Daz Connect folder layout (`data/cloud/<n>_<SKU>/`) hasn't been checked against a real Connect install. Connect products are named "Daz Connect product <SKU>" unless a DIM manifest names them.
- **Not used yet:** the chosen MO2 profile is stored but unused. (Endpoints and visibility are used by requisitions since 4a.)
- **Unreal:** no `.uasset` class detection (types come from name prefixes).
- **Discovery noise:** Steam games without definitions make the wizard's found list long. Consider hiding them behind a toggle.
- **Untracked files:** `docs/USEFUL_PATHS.md` and `KICKOFF_PROMPT.md` are the user's and stay out of git, since this repository is public. `KICKOFF_PROMPT.md` predates both the 2026-10-24 pivot and the restart; `VISION.md` is the brief. `.claude/launch.json` serves `docs/` on port 8765 to view the UI mockup (`docs/Exchange_Main_Window_Add_Environment.html`) in the browser pane.
