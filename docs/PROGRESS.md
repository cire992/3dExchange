# Exchange: progress and handoff

Last updated 2026-10-21, at the end of the first build session. `main` is at `672b25a` and all 143 tests pass.

Read this first, then `docs/DESIGN_SPEC.md` (the source of truth; use its terms exactly) and
`docs/USEFUL_PATHS.md` (real asset folders and tools on the dev machine, for testing).

## Where we are

**Roadmap phase 1 (Foundations) and phase 2 (Library) are done and merged.** The next step is
phase 3 (Curation); plan it and get approval before building (see "How we work").

| PR | What | State |
| --- | --- | --- |
| #1 | Phase 1: core package, SQLite schema, definition formats, `exchange scan` | merged |
| #2 | 2a: multi-root environments, Unreal, scan phase 3 (enrichment), search, query API, auto-discovery | merged |
| #3 | Daz fixes that missed #2's merge: real DIM manifest format, relocation by folder + filename | merged |
| #4 | 2b: main window (PySide6) | merged |
| #5 | 2c: add-environment wizard | merged |

## How we work

- **Plan, then build.** For each roadmap phase, propose a plan with open questions and a recommended answer for each, then wait for approval. So far the user has approved the recommended answers each time.
- **Ask instead of guessing** when the spec is ambiguous or seems wrong.
- **Pull requests:**
  - One branch and PR per chunk (e.g. 2a/2b/2c); the user reviews and merges.
  - Base the next PR on the previous one when they depend on each other.
  - Don't push more commits to a PR branch after telling the user it's ready: #2 was merged before two fixes landed and needed a follow-up PR (#3).
- **Check against real data.**
  - Read-only scans of the user's real libraries (into a temp database, never into the scanned folder) found real bugs every time.
  - Dry-run detection (`exchange scan PATH --dry-run`) only lists folders.
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
- **PowerShell gotcha:** `Get-Content`/`Set-Content` mangle UTF-8 (they garbled PR descriptions once). Write files from Python, or pass `-Encoding utf8` and read with `-Raw` carefully.

## Decisions made (do not reopen without the user)

Phase 1:
- **Daz containers:** the container is the content directory; products are product dossiers from manifests.
- **MO2 in phase 1:** detection, mod containers, `meta.ini`, and a product per mod.
- **MO2 environment:** one environment per MO2 instance. The profile is configuration, and each mod records which profiles enable it.
- **Lexicons:** the tokenizer runs now; lexicon matching is phase 3.
- **Mesh type:** `mesh` is an abstract type, refined to static or skinned mesh during enrichment.
- **Unidentified threshold:** 0.5.

Phase 2:
- **Daz Studio:** one environment per PC, holding every content directory (including Daz Connect).
- **Dependencies:** Pillow and numpy are core dependencies; PySide6 is the optional `ui` extra.
- **Mesh thumbnails:** a small numpy/Pillow renderer for glTF/GLB/OBJ. Other formats get an icon until the Blender bridge (phase 4).
- **Inspector:** read-only in phase 2; editing comes with curation (phase 3).
- **Exact duplicates:** merged automatically, with *unknown provenance*. Never for dossiers the user has edited.
- **File watcher:** deferred to phase 3. There is a *Rescan changed* button for now.
- **Unreal asset types:** from name prefixes (`SM_`, `SK_`, `T_`, `M_`/`MI_`, `BP_`, `.umap`). `.uasset` class parsing is **not** done (no real files to test against). Embedded thumbnails are found by scanning for PNG/JPEG signatures.
- **Offline roots:** they keep their entries; `rescan` suggests `env forget` after 30 days.
- **Material presets:** stay texture-set dossiers. That's about 83k of 212k dossiers in the real library; the user chose to keep them.

## Architecture in one page

```
src/exchange/            core, never imports Qt (a test enforces this)
  paths.py globs.py      case-insensitive path/glob helpers (Windows)
  errors.py
  definitions/           TOML environment + dossier-type definitions, strict loader
    builtin/environments daz_studio, skyrim_se, mo2_generic, unreal_project, loose_files (fallback)
    builtin/dossier_types product, mesh/static/skinned, texture, texture_set, material, skeleton,
                          animation, audio, daz_*, skyrim_npc, unreal_*
  db/                    connection (migrations, backup before migrating, busy_timeout), repository (all SQL)
    migrations/          0001 initial · 0002 roots/deps/thumbnails/FTS · 0003 scan.unattached_files
                         · 0004 library_setting (excluded roots)
  scanner/
    discovery.py         phase 1: walk (never follows links; skips excluded folders)
    detection.py         signature scoring, split into roots, same-type nesting collapsed
    identification.py    phase 2 engine: products, children, entries, retirement, FTS indexing
    layers/              organizational-layer handlers: daz, mo2, unreal, folder
    enrichment.py        phase 3: hashing, duplicate merge, mesh stats, Daz deps, thumbnails
    meshes.py formats.py thumbnails.py tokenize.py readonly.py
    scan.py              run_scan / run_rescan, grouping roots into environments, offline roots
  library/               search language (FTS5 + filters), query API (pages, sidebar, detail)
  autodiscover.py        Steam, Epic, Unreal recent projects, Daz registry, MO2 instances
  environments.py        register_root (user's type wins), excluded folders
  cli.py                 scan · rescan · enrich · env list/show/config/add/exclude/forget · discover · search · show
src/exchange_ui/         PySide6 app: main_window, models (paged browser, sidebar), delegates,
                         inspector, wizard, scanning (scans run as `python -m exchange ... --progress-json`)
tests/                   pytest; fixtures in tests/fixtures/envs; builders.py makes GLB/uasset/PNG/Unreal/
                         Daz Connect content and holds report helpers; tests/ui uses pytest-qt offscreen
```

Key ideas:
- **An environment has roots.** Containers and files belong to a root, and paths are stored relative to it.
- **Override layer:** keyed by dossier uid, with no foreign keys, so scans can't touch it. `dossier_effective` gives the effective values. Repository functions exist (set/revert field, tags, parent), but no UI uses them yet.
- **Identity across rescans:** a dossier is matched by its entry's (container, identity key). Products with the same `product_key` (a Daz SKU) become one dossier with an entry per container.
- **Read-only, enforced by tests:**
  - All file reads go through `scanner/readonly.py`.
  - Thumbnails are written to `thumbnails/` beside the database.
  - Scans refuse a database inside the scanned folder.

## Measured on the real machine

**Daz `My Library`:** 3.56M files and 4,652 manifests.
- **Phases 1-2:** about 7 minutes, giving 4,393 products and about 225k dossiers.
- **Unattached:** 2.4M files belong to no manifest.
- **Missing:** about a third of the files the manifests list are genuinely absent on disk.
- **UI:** a page of 200 takes 0.2-0.7 s, the sidebar 1.7 s (main thread), search about 0.25 s.
- **First open:** migrating a 1.6 GB library takes about 17 s, mostly the backup.

**Discovery:** finds the Daz content directories (registry), the global MO2 instances (Skyrim SE at `...\OutlawArcana` via `base_directory`, Morrowind) and many Unreal projects.

**MO2 instances in USEFUL_PATHS.md:** FNV, Morrowind, Oblivion, Starfield and Fallout 4 detect as `mo2_generic` because only Skyrim SE has a definition. Their game definitions are phase 5.

## Known gaps and good next candidates

- **Phase 3 (Curation), the next phase:**
  - The Unidentified desk.
  - Lexicons (the tokens are already stored, in `dossier_token`).
  - Editing in the inspector (the override layer is ready).
  - Merge/split and collections.
  - The file watcher.
  - Variant grouping (the spec's open question: automatic or suggested?).
  - Linking textures to meshes.
- **Speed:**
  - The sidebar query (1.7 s on the real library) runs on the UI thread. Move it to a worker.
  - Enrichment (hashing) has not been run on the full 3.56M-file library; expect it to be long.
- **Unattached Daz files:** 2.4M in the real library. Grouping manually installed content by content (filename + size, then hash) is spec'd but not built.
- **Unverified:** the Daz Connect folder layout (`data/cloud/<n>_<SKU>/`) hasn't been checked against a real Connect install. Connect products are named "Daz Connect product <SKU>" unless a DIM manifest names them.
- **Not used yet:**
  - The chosen MO2 profile is stored but unused.
  - Endpoints and visibility are stored for phase 4.
- **Unreal:** no `.uasset` class detection (types come from name prefixes).
- **Discovery noise:** Steam games without definitions make the wizard's found list long. Consider hiding them behind a toggle.
- **Untracked files:** `docs/USEFUL_PATHS.md` and `KICKOFF_PROMPT.md` are the user's and haven't been committed. `.claude/launch.json` serves `docs/` on port 8765 to view the UI mockup (`docs/Exchange_Main_Window_Add_Environment.html`) in the browser pane.
