# Exchange: progress and handoff

Last updated 2026-10-24, during Roadmap phase 6. `main` has phases 1-3, 4a-4c (#10-#13) and the Daz Studio bridge fixes checked against the real app (#14). In review: the pivot docs (#15), a Daz bridge include fix (#16) and 6a, the rename of pipelines to processes, stacked in that order.

Read this first, then `docs/IDENTITY.md` (what Exchange is for), `docs/DESIGN_SPEC.md` (how it
works; the source of truth, use its terms exactly) and `docs/USEFUL_PATHS.md` (real asset
folders and tools on the dev machine, for testing). The [README](../README.md) covers install
and usage.

## Design pivot (2026-10-24)

**Exchange has grown from an asset manager into a personal, AI-assisted project workspace** for
building interactive 3D worlds in Unreal Engine and by modding Bethesda games. Everything built in
phases 1-4 stays and becomes the core of the new design. Read `IDENTITY.md` and the new
`DESIGN_SPEC.md` in full before planning anything.

**What changed:**
- **Projects.** Exchange now manages projects: git-tracked project homes holding an identity,
  domains, goals and claims, plus a devlog, decisions, knowledge and game data. See the spec's
  *Projects* section.
- **Two repositories.** A desktop shell forked from Mr. Mak Workspace (Tauri, HTML frontend, a
  Chats window running CLI agents in real terminals) lives in its own repository and has its own
  handoff doc (path in `USEFUL_PATHS.md`). **This repository stays the Python core** and becomes
  the Exchange service: the core plus a local API for the shell's Workspace window and an
  Exchange MCP server for agent sessions.
- **The PySide6 window stays** as the working UI until the Workspace window reaches library
  parity (roadmap phase 6), then it is removed. Keep it working until then.
- **Vocabulary.** Pipelines are now **processes**, in the code too since 6a (see *Phase 6*).
  Endpoints stay; project targets are a kind of endpoint.
- **Scope.** Plugin records and game data are now in scope for project homes. Exchange is a
  personal tool for the user, Windows only; generality is welcome only when it costs nothing.

**What stays:** every decision recorded below still stands, except where the spec's *Decided*
section (entries dated 2026-10-24) supersedes it. Two supersede older text: the stack now uses
Tauri for the UI (the core stays Python), and the "asset art only" restriction is lifted. The
working method under *How we work* is unchanged: plan each phase with open questions and
recommended answers, wait for approval, one PR per chunk, check against real data.

**The new roadmap** (goal numbers refer to `IDENTITY.md`):

| Phase | What | Repository | Goal |
| --- | --- | --- | --- |
| 1-3 | Foundations, Library, Curation | this one | G1, done |
| 4 | Requisitions v1; first process Daz cross-figure (4d) | this one | G2, in progress |
| 5 | Chats online: the shell fork, sessions, history, per-session bypass | shell | G3 |
| 6 | Service and Workspace: local API, the rename, library view at parity | both | G4 |
| 7 | Project homes: files and index, identity interview, claims, devlog, mission control | both | G5 |
| 8 | Agents connected: Exchange MCP, generated agent files, claim dispatch, skills, drift review | both | G6 |
| 9 | Benchmark: a fresh Sirenne-themed Unreal project run from Exchange, with a Daz → Unreal process | both | G7 |
| 10-11 | Game environments; breadth | this one | |

**Next, in order:**
1. **The rename** is 6a, the first chunk of Roadmap phase 6 (see *Phase 6*).
2. **4d**, once the user answers phase 4 question 1 (what cross-figure converts first, and with
   which tool). It may run alongside 6b-6d, which touch other modules. The user has a Blender
   template scene for these conversions.
3. **Phase 5** is done in the shell repository (its PRs #1, #4, #5, #6).
4. **Phase 6** goes on with 6b (see *Phase 6*). Carried to phase 7, not yet approved:
   **project-home commits**, automatically at bypass-session checkpoints, when a claim reaches
   review or done, and on request.

**Between the repositories:** this repository owns the service API and the Exchange MCP; the
shell consumes them. Until phase 6 the shell's Workspace window is a placeholder, so phase 5 needs
nothing from here. When the API exists, its schema is the contract between the two, and changes
to it are noted in both handoff docs.

## Where we are

**Roadmap phases 1 (Foundations), 2 (Library) and 3 (Curation) are merged. Phase 4 (Requisitions
v1) is in progress, split into four PRs: 4a the requisition engine (core and CLI), 4b bridges
(Blender, Daz Studio, command-line tools), 4c requisitions in the window, 4d the first real
pipeline (Daz cross-figure, G9/G2 → G8).** The phase 4 plan was approved with all recommended
answers (see Decisions).

**Next:**
- **Phase 6, then 4d:** see *Phase 6* below and *Design pivot* above.
- **Stacked PRs next time:** after merging one, change the next PR's base to `main` before merging it (or delete the merged branch, and GitHub moves it). #11 and #12 merged into their base branches and needed #13 to reach `main`.
- **4d** waits for the user's answer to open question 1: what cross-figure converts first, and with which tool.

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
| #15 | The design pivot docs: identity, spec, progress | in review |
| #16 | Daz Studio bridge: the job script is included at the top level, so its functions see its names | in review (stacked on #15) |
| 6a | Phase 6: pipelines renamed processes, with the migration of existing data | in review (stacked on #16) |
| 4d | First process: Daz cross-figure (G9/G2 → G8) | needs the user's answer to open question 1 |

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
  - **A full real scan takes about 10 minutes;** the 3a slowdowns only showed at that size, so run one before a PR that touches scanning.
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
  - The app is `.venv/Scripts/exchange-app` and the CLI is `.venv/Scripts/exchange`.
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
- **Dependencies:** Pillow and numpy are core dependencies; PySide6 and watchdog (3c, the file watcher) are the optional `ui` extra.
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
  cli_requisitions.py    pipelines, tools, requisition, test-pipeline
  bridges/               base (run with timeout and log, one job per app, close the whole process
                         tree), blender (headless wrapper), daz (DazScript wrapper, separate
                         instance), command-line tools; operations reach them via ctx.bridge(app)
  library/               search language (FTS5 + filters), query API (pages, sidebar, detail, collections),
                         desk (unattached files by folder, one level at a time over the (root, rel_key) index)
  autodiscover.py        Steam, Epic, Unreal recent projects, Daz registry, MO2 instances
  environments.py        register_root (user's type wins), excluded folders
  cli.py cli_curation.py command line
src/exchange_ui/         PySide6 app: main_window, models (paged browser, sidebar with collections), delegates,
                         views (grid and sidebar with drag and drop), inspector (editing, bulk edit),
                         service (reads + edits via Curator, session undo/redo), wizard,
                         desk (unattached-files and suggestions panels; counts on worker threads),
                         settings (lexicon editor), settings_pipelines (Pipelines, Endpoints),
                         requisition_dialog (Requisition to…), queue_view (the queue),
                         pickers (asset search, split), watcher (watchdog),
                         scanning (scans, the queue and `classify` run as `python -m exchange ...`)
tests/                   pytest; fixtures in tests/fixtures/envs; builders.py makes GLB/uasset/PNG/Unreal/
                         Daz Connect content and holds report helpers; tests/ui uses pytest-qt offscreen;
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

- **4d** (see the table above) needs the user's answer on what cross-figure converts first.
- **Not done yet in phase 4:**
  - The `new-process` scaffold and the authoring guide (`PROCESS_GUIDE.md`, roadmap phase 11).
  - **Manual checkpoints in the window:** they show as *Needs attention* with the pipeline's message, and Resume continues. There's no button yet to open the work folder in the app at that point.
  - **Queue mode:** the queue only runs when you press Run; there's no "run immediately" setting yet.
  - Parallel command-line operations: the runner does one step at a time.
  - Blender thumbnails for formats the small renderer can't draw.
- **The Daz Studio bridge has run only a trivial job** (version, scene, one file written), not a real conversion. That's for 4d.
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
- **Untracked files:** `docs/USEFUL_PATHS.md` and `KICKOFF_PROMPT.md` are the user's and haven't been committed. `KICKOFF_PROMPT.md` predates the 2026-10-24 pivot; `IDENTITY.md` and `DESIGN_SPEC.md` replace it as the brief. `.claude/launch.json` serves `docs/` on port 8765 to view the UI mockup (`docs/Exchange_Main_Window_Add_Environment.html`) in the browser pane.
