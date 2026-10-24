# The Exchange

Exchange is a desktop application that gives modders and solo developers a god's-eye view of every 3D asset they own, across every game, engine and content library, and turns converting assets between those environments into a queued, repeatable job.

It indexes Daz Studio libraries, Unreal Engine projects, Mod Organizer 2 instances and loose folders into one library of **dossiers** (what an asset *is*), each with **ledgers** recording where it lives. **Scanning is strictly read-only:** Exchange never writes to a scanned folder.

> **Status:** Roadmap phases 1 (Foundations), 2 (Library) and 3 (Curation) are done. Phase 4 (Requisitions) is in progress: the engine, the bridges to Blender, Daz Studio and command-line tools, and requisitions in the window are in; the first real process (Daz cross-figure) comes next. See [docs/PROGRESS.md](docs/PROGRESS.md) for details and [docs/DESIGN_SPEC.md](docs/DESIGN_SPEC.md) for the full design.

## What it does today

- **Finds your environments.** It reads Steam, the Epic launcher, Unreal's recent projects, Daz Studio's content directories and MO2 instances. An add-environment wizard splits any folder into the environments inside it.
- **Indexes them in three phases:**
  1. Discovery: files.
  2. Identification:
     - products from Daz manifests and Daz Connect, hand-installed Daz content grouped by folder
     - MO2 mods with their `meta.ini`
     - Unreal content packs and plugins
     - folder guesses for loose files
  3. Enrichment:
     - hashes and duplicate detection
     - glTF/OBJ mesh statistics
     - Daz dependencies, with broken references flagged
     - thumbnails, from previews, Unreal packages, images or a small mesh renderer
- **Classifies with lexicons.** Editable word lists turn names, folders and source categories into tags, variant words and texture channels. LOD and collision meshes are recognized and kept out of the way.
  - Theme words and a list of known authors tell hand-installed Daz products apart from the category and vendor folders you sort them into.
  - Scans fill the author list from manifests and `data/` folders; you can add to it or remove from it.
- **Lets you curate.** Rename, retype, tag, link textures onto meshes, merge, split, fold variants, build products and collections. Every action can be undone, and your edits always survive rescans.
  - **In the window:** edit any field in the inspector; your edits are marked and have a revert button. Select several assets to edit them together.
  - **Drag and drop:** drop assets on a product, on another asset (link its files or merge), or on a collection in the sidebar. Drop scanned files from Explorer onto an asset to link them.
  - **Undo and redo** with Ctrl+Z and Ctrl+Y.
- **Has an Unidentified desk** for sorting what scans couldn't place:
  - **Low confidence:** assets below the confidence threshold, to retype, tag or dismiss as not an asset.
  - **Unattached files:** files no asset holds, folder by folder. Make a product from a folder, link its files to an asset, or ignore it from now on.
  - **Suggestions:** texture links, variant groups and lexicon words, to accept or reject in batches.
- **Watches your folders.** An environment whose files change is marked *changes detected*; you rescan when you're ready.
- **Edits lexicons** in Settings (⚙): add or remove words, then apply them to the library.
- **Runs requisitions:** plan getting an asset or a whole product into an environment with a process, queue it, run it.
  - **In the window:** right-click → *Requisition to…* (or the inspector's button) shows the plan, with option forms, presets and the options last used. Select several assets to queue them all.
  - **The queue:** *Requisitions* in the sidebar runs it in the background, holds, reorders and resumes items, shows each item's log, and removes or rebuilds output.
  - **Settings:** *Processes* installs and trusts packages and sets tool paths; *Endpoints* sets where each environment's output goes and whether it's publishable.
  - **Where output goes:** only to an endpoint (a new MO2 mod, an *Exchange Conversions* content directory), with a record of every file written and a `.exchange` sidecar beside the output.
  - **Afterwards:** the output joins the asset's ledgers. Removing it moves the files to a recycle folder. Requisitions whose source or process changed show as stale and can be rebuilt.
  - **Built in:** *Copy to another container*, and *Convert mesh*: FBX, OBJ, glTF, DAE, STL or PLY to GLB, glTF, FBX or OBJ with Blender, which is found automatically.
  - **Bridges:** processes can run steps in Blender (headless) and Daz Studio (a separate instance), one job per app at a time.
- **Suggests links and groupings.** `Barrel01_D.png` + `Barrel01_N.png` → `Barrel01.glb`; `Donut01_Pink` + `Donut01_Blue` → one asset with two variants. You accept or reject them in batches.
- **Lets you browse and search.** A desktop window with a sidebar, a thumbnail grid and an inspector, plus a search language: `donut env:skyrim_se tag:food -is:product`, `type:mesh has:broken`, `collection:"Lard Lads assets"`.

| Environment | Recognized by | Containers |
| --- | --- | --- |
| Daz Studio (all content directories as one environment) | `data/`, `Runtime/Support`, `People/`, `.duf` files | content directories; products from DIM manifests, Daz Connect and folders |
| Skyrim SE via MO2 (other games as generic MO2 for now) | `ModOrganizer.ini` / `ModOrganizer.exe`, including global instances | mod folders |
| Unreal Engine project | `*.uproject` | top-level `Content/` folders (packs) and plugins |
| Loose files | everything else | folders, at low confidence |

## Install

You need Python 3.11 or newer. On Windows, with the Python launcher:

```bash
py -3.12 -m venv .venv
```
```bash
.venv/Scripts/python -m pip install -e ".[ui]"
```

Use `.[dev]` instead of `.[ui]` if you also want the test tools. Add `service` (`.[ui,service]`) for the local API the desktop shell uses.

## Use

Start the desktop app, then click **Add environment**:

```bash
.venv/Scripts/exchange-app
```

Or use the command line. A few examples:

```bash
.venv/Scripts/exchange discover
```
```bash
.venv/Scripts/exchange scan "D:/Daz 3D/My Library"
```
```bash
.venv/Scripts/exchange search "marius type:daz_morph"
```
```bash
.venv/Scripts/exchange suggest list
```
```bash
.venv/Scripts/exchange history
```

| Command | What it does |
| --- | --- |
| `scan FOLDER` | Detect environments in a folder and index them. `--dry-run` only detects; `--no-enrich` stops after identification. |
| `rescan`, `enrich` | Rescan known environments (only changes are reprocessed); re-run enrichment. |
| `env list / show / add / config / exclude / forget` | Manage environments, their settings and excluded folders. |
| `discover` | List environments found on this PC. |
| `search QUERY`, `show UID` | Search the library; show one dossier with its ledgers, files and dependencies. |
| `classify`, `lexicon …` | Re-run classification (`--regroup` also regroups files into products, after editing theme or author lexicons); show and edit lexicons. |
| `suggest list / accept / reject` | Review suggestions. |
| `curate …`, `collection …` | Edit dossiers and collections (`set`, `tag`, `link`, `merge`, `fold`, `split`, `product` …). |
| `history`, `undo ID` | Recent curation actions; undo one (undo an undo to redo). |
| `desk [ROOT [FOLDER]]` | Unattached files by folder; `curate dismiss` and `curate ignore-folder` act on the desk. |
| `processes list / show / check / install / trust`, `tools set` | Process packages, their prerequisites, and where external tools are. |
| `requisition routes / plan / list / show / run / resume / hold / move / remove / check-stale / rebuild` | Plan (`--queue`, `--preset`, `--save-preset`), run and manage requisitions. |
| `presets list / show / delete` | Requisition presets: options for every process of a plan. |
| `test-process FOLDER UID` | Run a process you are writing on one asset, into a temporary folder. |
| `serve` | Serve the library over a local API for the desktop shell (needs the `service` extra; see below). |

Every command takes `--json` for machine-readable output, and `--db PATH` to use another library.

## The local service

The desktop shell (the Exchange Shell repository) reads the library through `exchange serve`, a
local HTTP API (FastAPI and uvicorn, the optional `service` extra):

- **Loopback only:** it listens on `127.0.0.1` (`--port 0`, the default, picks a free port) and
  refuses requests addressed to any other host name.
- **Token:** every `/api` request needs `Authorization: Bearer <token>`. The starting process
  passes it in `EXCHANGE_SERVICE_TOKEN`, or the service makes one.
- **Ready line:** on start it prints one JSON line,
  `{"event": "ready", "url": …, "api": 1, …}`, plus the token when it made it.
- **Lifetime:** with `--exit-with-stdin` it stops when its stdin closes.
- **Read-only (6b):** the sidebar, environments, pages of assets with the search language,
  one asset's detail, its thumbnail, and collections, under `/api/v1/`. `/health` needs no token.
- **Contract:** the schema is committed as [`docs/api/openapi.json`](docs/api/openapi.json);
  regenerate it with `exchange serve --openapi > docs/api/openapi.json` after changing the API
  (a test checks it).

## Where things live

- **Library database** (SQLite): `%LOCALAPPDATA%\Exchange\library.db`. Set `EXCHANGE_DATA_DIR` to put it elsewhere. Exchange backs it up before every schema migration.
- **Thumbnails:** `thumbnails\` beside the database.
- **Your definitions:** `%LOCALAPPDATA%\Exchange\definitions\`, with folders `environments\`, `dossier_types\` and `lexicons\`. A file there replaces the built-in one with the same id, which is how lexicon edits are stored.

## Extending

- **Environments, dossier types and lexicons are TOML data files.** See the built-ins in `src/exchange/definitions/builtin/`. Adding a game is a definition file, not a code change, as long as an existing organizational layer (MO2, Daz, Unreal, folders) fits.
- **Validation is strict.** A typo is reported with its file and key.
- **Processes are packages:** a `process.toml` manifest plus Python operations; see `src/exchange/processes/manifest.py` for the format.
  - **Install and trust:** `exchange processes install FOLDER`, then `exchange processes trust ID` once you've read what it runs.
  - **Test as you write:** `exchange test-process FOLDER UID`.
  - **Data from before the rename** (pipelines became processes in Roadmap phase 6): on first run, `<data>/pipelines/` moves to `<data>/processes/`. Each package's `pipeline.toml` becomes `process.toml`, and its imports of `exchange.pipelines` become `exchange.processes`. A package stays trusted only if it was unchanged since you trusted it. The database migrates after a backup. Sidecars already written into your environments are left as they are; scans read both kinds.

## Develop

```bash
.venv/Scripts/python -m pip install -e ".[dev]"
```
```bash
.venv/Scripts/python -m pytest -q
```

- **Layout:** the core (`src/exchange`) never imports Qt. The desktop app is `src/exchange_ui` (PySide6).
- **Tests:** they use small fake environments in `tests/fixtures/envs` and files built on the fly by `tests/builders.py`. UI tests run offscreen with pytest-qt.
- **More:** see [docs/PROGRESS.md](docs/PROGRESS.md) for the architecture, the decisions made so far and how the project is being built.
