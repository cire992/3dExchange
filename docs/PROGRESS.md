# Exchange: progress and handoff

Last updated 2026-10-21, during Roadmap phase 3. `main` has phases 1 and 2. PR 3a (curation core) is on branch `phase-3a-curation-core`. 164 tests pass.

Read this first, then `docs/DESIGN_SPEC.md` (the source of truth; use its terms exactly) and
`docs/USEFUL_PATHS.md` (real asset folders and tools on the dev machine, for testing). The
[README](../README.md) covers install and usage.

## Where we are

**Roadmap phases 1 (Foundations) and 2 (Library) are merged. Phase 3 (Curation) is in progress,
split into three PRs (3a core, 3b editing in the main window, 3c Unidentified desk + lexicon editor +
file watcher).** The phase 3 plan was approved with all recommended answers (see Decisions).

| PR | What | State |
| --- | --- | --- |
| #1 | Phase 1: core package, SQLite schema, definition formats, `exchange scan` | merged |
| #2 | 2a: multi-root environments, Unreal, scan phase 3 (enrichment), search, query API, auto-discovery | merged |
| #3 | Daz fixes that missed #2's merge: real DIM manifest format, relocation by folder + filename | merged |
| #4 | 2b: main window (PySide6) | merged |
| #5 | 2c: add-environment wizard | merged |
| #6 | This handoff doc | merged |
| 3a | Curation core: lexicons, classification, undoable curation, suggestions, collections, hand-installed Daz products, CLI | branch `phase-3a-curation-core`, PR to open |
| 3b | Editing in the main window: inspector editing + revert markers, bulk edit, drag and drop linking, collections in the sidebar, context-menu actions, Ctrl+Z/Ctrl+Y | next |
| 3c | Unidentified desk (low-confidence dossiers, unattached files by folder, suggestions in batches), lexicon editor, file watcher (`watchdog`) | after 3b |

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
- **Dependencies:** Pillow and numpy are core dependencies; PySide6 is the optional `ui` extra.
- **Mesh thumbnails:** a small numpy/Pillow renderer for glTF/GLB/OBJ. Other formats get an icon until the Blender bridge (phase 4).
- **Inspector:** read-only in phase 2; editing is PR 3b.
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
                         · 0004 library_setting (excluded roots) · 0005 curation
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
  library/               search language (FTS5 + filters), query API (pages, sidebar, detail, collections)
  autodiscover.py        Steam, Epic, Unreal recent projects, Daz registry, MO2 instances
  environments.py        register_root (user's type wins), excluded folders
  cli.py cli_curation.py command line
src/exchange_ui/         PySide6 app: main_window, models (paged browser, sidebar), delegates,
                         inspector, wizard, scanning (scans run as `python -m exchange ... --progress-json`)
tests/                   pytest; fixtures in tests/fixtures/envs; builders.py makes GLB/uasset/PNG/Unreal/
                         Daz Connect content and holds report helpers; tests/ui uses pytest-qt offscreen
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
- **First open:** migrating a 1.6 GB library takes about 17 s, mostly the backup.

**Loose folders** (`Z:\Content Farm\Sketchfab` and `SWBF Model and Textures`), checked in 3a:
- **Tags:** 77% of 4,728 dossiers got one. SWBF's many *Weapon* tags are correct: the folder is mostly weapon sound effects.
- **Texture links:** 62 suggestions. They're correct on the samples checked, including `DwarfHelmet_Base_Color` and PBR sets.
- **Variant groups:** 25 suggestions, e.g. footstep sounds on wood/metal/stone.

**Discovery:** finds the Daz content directories (registry), the global MO2 instances (Skyrim SE at `...\OutlawArcana` via `base_directory`, Morrowind) and many Unreal projects.

**MO2 instances in USEFUL_PATHS.md:** FNV, Morrowind, Oblivion, Starfield and Fallout 4 detect as `mo2_generic` because only Skyrim SE has a definition. Their game definitions are phase 5.

## Known gaps and good next candidates

- **3b and 3c** (see the table above). The core for both is in 3a: `Curator`, `list_suggestions`, `list_collections`, and the extended `dossier_detail`.
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
- **Not used yet:**
  - The chosen MO2 profile is stored but unused.
  - Endpoints and visibility are stored for phase 4.
- **Unreal:** no `.uasset` class detection (types come from name prefixes).
- **Discovery noise:** Steam games without definitions make the wizard's found list long. Consider hiding them behind a toggle.
- **Untracked files:** `docs/USEFUL_PATHS.md` and `KICKOFF_PROMPT.md` are the user's and haven't been committed. `.claude/launch.json` serves `docs/` on port 8765 to view the UI mockup (`docs/Exchange_Main_Window_Add_Environment.html`) in the browser pane.
