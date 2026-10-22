# The Exchange

Exchange is a desktop application that gives modders and solo developers a god's-eye view of every 3D asset they own, across every game, engine and content library, and turns converting assets between those environments into a queued, repeatable job.

It indexes Daz Studio libraries, Unreal Engine projects, Mod Organizer 2 instances and loose folders into one library of **dossiers** (what an asset *is*), each with **ledgers** recording where it lives. **Scanning is strictly read-only:** Exchange never writes to a scanned folder.

> **Status:** Roadmap phases 1 (Foundations) and 2 (Library) are done. Phase 3 (Curation) is in progress. Conversions (requisitions) arrive in phase 4. See [docs/PROGRESS.md](docs/PROGRESS.md) for details and [docs/DESIGN_SPEC.md](docs/DESIGN_SPEC.md) for the full design.

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

Use `.[dev]` instead of `.[ui]` if you also want the test tools.

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

Every command takes `--json` for machine-readable output, and `--db PATH` to use another library.

## Where things live

- **Library database** (SQLite): `%LOCALAPPDATA%\Exchange\library.db`. Set `EXCHANGE_DATA_DIR` to put it elsewhere. Exchange backs it up before every schema migration.
- **Thumbnails:** `thumbnails\` beside the database.
- **Your definitions:** `%LOCALAPPDATA%\Exchange\definitions\`, with folders `environments\`, `dossier_types\` and `lexicons\`. A file there replaces the built-in one with the same id, which is how lexicon edits are stored.

## Extending

- **Environments, dossier types and lexicons are TOML data files.** See the built-ins in `src/exchange/definitions/builtin/`. Adding a game is a definition file, not a code change, as long as an existing organizational layer (MO2, Daz, Unreal, folders) fits.
- **Validation is strict.** A typo is reported with its file and key.

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
