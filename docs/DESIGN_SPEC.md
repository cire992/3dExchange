# Exchange — Design Specification

Last updated 2026-10-21. Exported from the living design doc; the doc is the source of truth when they differ.

Exchange is a desktop application that gives modders and solo developers a god's-eye view of every 3D asset they own, across every game, engine and content library, and turns converting assets between those environments into a queued, repeatable job.

## Vision and principles

Dealing with assets is the albatross around every modder's neck: finding what you own, remembering where it lives, and hand-converting it between formats and engines. Exchange's north star is to remove as much of that friction as possible behind a sleek, easy-to-navigate interface.

1. **Asset-centric, not environment-centric.** A dossier describes what an asset *is*. Where it lives is tracked separately, in ledgers.
2. **Read-only until asked.** Scanning never modifies an environment. Exchange writes only through requisitions or explicit user actions, and says so in the UI.
3. **The user's work is never lost.** Manual edits to metadata, links and tags form a layer that always survives rescans.
4. **Confidence over certainty.** Every automatic identification carries a confidence score. Low-confidence results go to a review queue instead of polluting the library.
5. **Show the plan, then automate.** A requisition shows exactly what will be converted, how and where before it runs.
6. **Incremental everywhere.** Rescans, conversions and rebuilds only touch what changed.
7. **Extensible through data and plugins.** Environments, lexicons and dossier types are data files; pipelines are plugins. The core never needs editing to support a new game.
8. **Built for AI-assisted authoring.** Most users will write pipelines with AI help, so the pipeline SDK is small, typed, documented and testable in isolation.

## Core concepts

Sixteen terms carry the whole design; every later section uses them exactly as defined here.

| Term | Definition | Example |
| --- | --- | --- |
| Environment | An ecosystem where assets exist in a particular format and structure, identified by contents rather than path | Skyrim SE via MO2 profile "Main" |
| Environment definition | The data file describing how to detect, read, organize and write an environment type | `skyrim_se.toml` |
| Variant | A sub-state within an environment that changes compatibility | Daz/Genesis 8, Daz/Genesis 9, Daz/Poser-legacy |
| Organizational layer | The structure an environment groups content by | MO2 mods, Daz product manifests, UE plugins |
| Container | One unit of the organizational layer: a mod, product or project folder | MO2 mod "Test Requisitions" |
| Product | A dossier representing a whole purchasable or downloadable package | "Marius HD-8K for Genesis 9" |
| Dossier | The universal record of what an asset *is*: identity, metadata, tags, variants, dependencies, ledgers | Donut01 |
| Ledger | A dossier's record of its presence in one environment | Donut01's Starfield ledger |
| Entry | One occurrence of the asset inside one container, with provenance | Donut01 in "Lard Lads Donuts", copied from "Test Requisitions" |
| Tag | A descriptive label from lexicons or the user | Food, Pink, Prop |
| Role | A pipeline-derived capability: what a dossier can become | Starfield Ingestible candidate |
| Lexicon | An editable word list that turns filename tokens into tags, variants or structure | Food lexicon: donut, apple, bread |
| Operation | One atomic, reusable step with typed inputs and outputs | Convert texture to DDS |
| Pipeline | A chain of operations taking one dossier type to one target | G9 Head Morph → Skyrim Head |
| Requisition | One conversion job: source, pipelines, parameters and endpoint; may span a whole product | "Marius → Skyrim NPC" |
| Endpoint | Where a requisition's output is written in the target environment | New MO2 mod "Exchange – Marius" |

## Environments

An environment is recognized by what it contains, and Exchange always works through the environment's own organizational layer.

### Environment definitions

Each environment type is a data file, so adding a game means writing a definition, not changing the core. A definition declares:

- **Detection signatures:** marker files and folders, with weights (`.uproject`, `ModOrganizer.ini`, `openmw.cfg`, `AddonPackages/`).
- **Organizational layer:** how containers are found and read.
- **Variant rules:** how to tell Genesis 8 from Genesis 9, or Skyrim LE from SE.
- **Capabilities:** indexable (list contents), readable (extract files), writable (accept requisition output).
- **Compatibility links:** environments that can use this one's content without conversion (OpenMW reads most vanilla Morrowind content; the reverse is not true).
- **Native dossier types:** environment-specific types such as Daz Morph or Skyrim NPC.

### Organizational layers

Where a mod manager exists, Exchange works solely through it. Mods are already products, and a requisition endpoint becomes "create a new mod."

| Environment | Organizational layer | Container | Notes |
| --- | --- | --- | --- |
| Bethesda games (Morrowind → Starfield) | MO2 (first), Vortex (later) | Mod folder | MO2 is plain folders + `meta.ini` with Nexus IDs; Vortex keeps state internally and deploys via links |
| Mass Effect LE | ME3Tweaks Mod Manager | Mod | Assets packed in .pcc packages |
| Garry's Mod / Source | Native addons folder | Addon | Workshop .gma archives |
| Daz Studio | Product manifests (hints only) | Product | Users move files; see Scanning |
| Unreal Engine | Project content folders and plugins | Content pack / plugin | Fab packs usually one top-level folder |
| VaM | AddonPackages | .var package | Genesis 2 source for backporting |
| Loose files | Folder heuristics | Folder | Low confidence by default |

### Adding environments

1. **Add a folder** by dragging it in or browsing.
2. **Detect:** signatures are scored and a type is proposed with a confidence level.
3. **Split:** if a path contains several environments, each becomes its own environment; the most specific match wins and leftovers fall through to Loose Files.
4. **Configure:** organizational layer (e.g. which MO2 instance and profile), content directories, endpoints, ignore rules.
5. **Scan.**

**First-run auto-discovery** reads files that already know install locations: Steam's `libraryfolders.vdf`, the Epic launcher manifest, Daz/DIM content directory settings and MO2 instance configs. Exchange presents a checklist of everything it found.

### Endpoints

Every writable environment has at least one endpoint. Endpoints carry a **visibility** of *personal* or *publishable*, used by license checks. Defaults by layer: MO2 creates a new mod per requisition (or appends to a chosen Exchange-managed mod); Daz writes to a dedicated "Exchange Conversions" content directory; Unreal writes to a configurable content folder.

## Scanning and indexing

Scanning runs in three phases so product bricks appear within minutes and detail fills in afterward in the background.

| Phase | What it does | Cost | The user sees |
| --- | --- | --- | --- |
| 1. Discovery | Walk the tree; record path, size, modification time | Fast | File counts, folder structure |
| 2. Identification | Group files into containers, products and dossiers per environment rules; tokenize names against lexicons | Medium | Product bricks, tags, Unidentified count |
| 3. Enrichment | Hashing, mesh fingerprinting, dependency parsing, thumbnail rendering, promo images and author lookup | Slow, background | Thumbnails fill in; duplicates and variants merge |

### Product grouping

- **Daz manifests are hints, not truth.** `.dsx` support files seed product membership, then Exchange reconciles against reality: match by expected relative path, then filename + size, then hash. Files found elsewhere are marked *relocated*, not missing, and product identity rests on content, so manually installed products still group.
- **Daz Connect products merge with DIM products** into one product dossier, so a product installed both ways appears once.
- **Daz dependencies** come from the internal path references inside `.duf` and `.dsf` files. References broken by moved files are flagged; repairing them is a separate opt-in write action.
- **MO2:** each mod folder is a container; `meta.ini` supplies the Nexus mod ID, version and source.
- **Unreal:** content folders and plugins are containers; Fab packs are usually one top-level folder.
- **Loose files:** folder-as-product heuristics at low confidence; doubtful results go to Unidentified.

### Packed archives

BSA/BA2, .pcc, .gma and .var archives are detected and indexed by name and metadata only. Extraction is user-driven: right-click a detected mod or product and choose Extract. Extracted contents are then scanned like any other files.

### Change tracking

- **Incremental rescans** compare modification time and size and re-process only what changed.
- **A file watcher** marks environments "changes detected" instead of rescanning silently; the user chooses when to rescan.
- **Manual copies are detected.** If the user copies an asset between mods by hand, the hash match on rescan adds a new ledger entry with provenance *unknown*.
- **Exchange output is self-identifying.** Every requisition writes a small `.exchange` sidecar manifest into its output, recording dossier IDs and provenance. Rescans recognize Exchange's own output exactly, and the record survives a lost database.

## Dossiers

A dossier is one asset's universal record; its ledgers track every place that asset exists, one ledger per environment.

### Structure

- **Identity:** stable ID, name, dossier type, content fingerprint.
- **Metadata:** two layers. *Scanned* values come from files, manifests and lookups; *user* values always win and survive rescans.
- **Tags and roles:** tags describe (Food, Pink); roles say what the dossier can become, derived from installed pipelines.
- **Variants:** sibling forms of one asset (Donut01_Pink, Donut01_Blue) held as one dossier.
- **Hierarchy:** product dossiers contain child dossiers (Marius → head morph, body morph, texture sets, eyebrows).
- **Dependencies:** dossiers this one needs (Marius requires Genesis 9 Base).
- **Origin:** original author (Daz PA, mod author) auto-filled when found, source URL, license, and promo images.
- **Ledgers:** one per environment where the asset exists.

### Ledgers and entries

```
Donut01 (dossier · variants: Pink, Blue)
├─ Loose Files ledger
│   └─ Downloads/props/Donut01_Pink.glb             origin
├─ Starfield ledger
│   ├─ Test Requisitions    requisitioned from Loose Files
│   └─ Lard Lads Donuts     copied from Test Requisitions
└─ Daz Studio ledger
    └─ Exchange Conversions requisitioned from Loose Files
```

Each entry records its container, files, hashes, provenance and status. Any entry can be the source of a later requisition, so a donut already in Starfield can be copied into a new mod instead of converted again.

| Entry status | Meaning |
| --- | --- |
| Origin | Where Exchange first found the asset |
| Requisitioned | Produced by a requisition; source, pipeline versions and parameters recorded |
| Copied | Copied from another entry in the same environment by a copy pipeline |
| Unknown provenance | Matched by hash on rescan, not produced by Exchange (e.g. a manual copy) |
| Modified | Files changed after creation; may now be the preferred copy source |
| Stale | Source or pipeline changed since this entry was produced; can be rebuilt |
| Retired | No longer on disk; kept as history |

A dossier remains while any ledger holds a live entry. A dossier with only retired entries is hidden by default but kept.

### Dossier types

Types are data definitions with two scopes:

- **Universal:** static mesh, skinned mesh, texture set, material, skeleton, animation, audio.
- **Environment-specific:** Daz morph, Daz character preset, Daz wearable, Skyrim NPC, Starfield Ingestible, Unreal Blueprint actor.

The browser's environment filter shows a given environment's native types plus any dossier with a role there. Type definitions can be extended by users and by pipeline packages.

## Classification

Exchange combines several weighted signals into tags, types and variants, each with a confidence score.

### Filename lexicons

Names are tokenized on underscores, spaces, camelCase and digit boundaries (`Donut01_Pink` → `donut | 01 | pink`), then matched against lexicons.

| Lexicon | Example tokens | Drives |
| --- | --- | --- |
| Category | donut, barrel, sword, chair | Tags (Food, Container, Weapon, Furniture) |
| Variant | pink, red, damaged, clean, worn | Variant grouping instead of new dossiers |
| Texture channel | _D, _N, _ORM, BaseColor, Normal, Roughness | Mesh–texture linking |
| Structural | LOD0, UCX_, _col, _collision | LOD and collision detection |
| Index | 01, 02, A, B | Series and variant numbering |
| Ignore | final, new, copy, v2 | Discarded noise words |

Default lexicons ship with Exchange. Users edit them, create their own (e.g. a food list), and can add synonyms and plurals.

### Other signals

- **Folder path:** a parent folder named "Food" or "Props" is strong evidence.
- **Mesh bounds:** a donut is about 10 cm, a barrel about 1 m.
- **Mesh statistics:** poly count, UV sets, presence of a skeleton.
- **Topology fingerprint:** vertex count and order matched against known figures (Genesis 8 Female base, Skyrim vanilla body), so a mystery FBX becomes a recognized export.
- **Source metadata:** Daz manifests, Nexus categories, Fab categories.

### Confidence

Each result shows its confidence and which signals produced it. Results below a configurable threshold go to the Unidentified desk instead of the library. User corrections are recorded and can be fed back into lexicons in one click ("add 'cruller' to Food").

## Curation

Manual curation is unavoidable, so the Unidentified desk is built to feel like sorting, not filling in forms.

- **Linking:** drag textures onto meshes, files onto dossiers, dossiers onto products.
- **Suggestions:** texture-channel and name matches propose links (`Barrel01_D.png` + `Barrel01_N.png` → `Barrel01.glb`), shown as a list the user accepts or rejects in batches.
- **Merge and split:** merge two dossiers that are the same asset (their ledgers combine); split one that wrongly grouped two assets; promote a variant to its own dossier or fold a dossier in as a variant.
- **Metadata editing:** every field in the inspector is editable, including name, type, tags, author, license and notes. Bulk edit applies a change to a whole selection.
- **Override layer:** user edits are stored separately from scanned values and always win, so a rescan never wipes a hand-set name, tag or link. Each overridden field shows a marker and a "revert to scanned" action.
- **Undo:** curation actions are undoable within a session and logged permanently.

## User interface

One main window serves browsing, curating and requisitioning, with setup screens kept in Settings. Visual mockups of the main window and the add-environment flow exist as a separate design canvas.

### Main window

```
┌────────────────────────────────────────────────────────────────────┐
│ [ donut env:starfield tag:food           ]  [Scan ▸]  [Settings]   │
├───────────────┬────────────────────────────────────┬───────────────┤
│ LIBRARY       │  BROWSER                           │ INSPECTOR     │
│  All assets   │  ┌────┐ ┌────┐ ┌┈┈┈┈┐ ┌┈┈┈┈┐       │ Donut01       │
│  Collections  │  │ ▣  │ │ ▣  │ ┊ ▢  ┊ ┊ ▢  ┊       │ Static mesh   │
│ ENVIRONMENTS  │  └────┘ └────┘ └┈┈┈┈┘ └┈┈┈┈┘       │ Food · Pink   │
│ ▾ Starfield   │  entry   entry   candidate candidate│ Ledgers (2)   │
│   Ingestible  │                                    │ Variants (2)  │
│   Static      │  Starfield › Ingestible            │ Requisitions  │
│ ▸ Daz Studio  │  [ ] show candidates               │ Dependencies  │
│ ⚠ Unidentified│                                    │ Origin · Files│
├───────────────┴────────────────────────────────────┴───────────────┤
│ Scan: Daz Main Lib, phase 3 (thumbnails) · Requisitions: 2 queued ▾│
└────────────────────────────────────────────────────────────────────┘
```

- **Sidebar:** the whole library, user collections, then environments › containers or dossier types, and the Unidentified desk with a count.
- **Browser:** grid or list of bricks. Toggles for grouping (by product or by dossier type), scope (one environment or all) and the environment filter.
- **Entries vs candidates:** inside an environment view, solid bricks are existing entries and ghosted bricks are available requisitions, with a "show candidates" toggle.
- **Inspector:** tabs for overview, ledgers (with entries and provenance), variants, requisitions available, dependencies, origin/license, files and history. All fields editable.
- **Bottom bar:** scan status and the requisition queue, expandable into a full queue panel.
- **Context menu on a brick:** Requisition to…, Copy to… (from an existing entry), Extract (packed archives), Open in app, Show in folder, Merge, Add to collection.

### Search

Free text plus filters, all composable and saveable as smart collections:

`donut env:starfield tag:food -tag:damaged type:mesh author:"Jane Doe" status:stale has:candidate`

### Collections

Manual collections ("Lard Lads assets") and smart collections (saved searches). Collections can be requisitioned as a batch.

### Settings

- **Environments:** add, detect, configure organizational layers and endpoints, ignore rules.
- **Pipelines:** installed packages, prerequisite status, presets.
- **Lexicons and dossier types:** edit word lists and type definitions.
- **Online lookups:** per-source toggles (see Online lookups).
- **Storage:** database location, thumbnail cache size, backups.

## Pipelines

Pipelines are plugins: chains of modular operations, packaged with their templates, written mostly in Python and mostly with AI assistance.

### Operations

An operation is the smallest reusable unit. It declares typed inputs and outputs (e.g. `DazMorph → BlendShape`, `TextureSet(PBR) → TextureSet(DDS)`), its parameters, and which external app it runs in, if any. Typed signatures let Exchange validate chains, reuse a shared step's output across pipelines in one requisition, and cache intermediates.

Core operations ship with Exchange: copy between containers, texture format conversion, image resize, file rename and pack. Other operations ship inside pipeline packages.

### Bridges to external apps

Many operations run inside another application. Exchange provides bridges that launch the app, pass inputs, run a script and collect outputs:

- **Blender:** headless via `blender -b template.blend --python op.py`.
- **Daz Studio:** DazScript run on launch.
- **Unreal Engine:** Python via commandlet or remote execution.
- **Command-line tools:** texconv, archive packers, NIF tooling.

A bridge is a first-class step type, so pipeline authors never hand-roll process management.

### Pipeline packages

```
glb_to_starfield_ingestible/
├─ pipeline.toml        manifest
├─ operations/          Python operations
├─ templates/           .blend files, project templates
├─ presets/             shipped requisition presets
├─ tests/               sample dossiers + expected outputs
└─ README.md
```

The manifest declares name, version, author, input predicate (dossier type + required tags, e.g. static mesh tagged Food), source and target environment variants, operation chain, parameters with defaults, prerequisites, and which roles it grants.

### Prerequisites

Each pipeline has a setup page under Settings › Pipelines listing its prerequisites: external tool paths and versions, templates, plugins (e.g. a Blender add-on). Each shows green or red with a fix hint. A pipeline is selectable only when every prerequisite is green. Setup is one-time, with a cheap recheck on launch (paths and versions still match) to catch tool updates that silently break templates.

### Authoring with AI

Most users will build pipelines with AI help, so the SDK is designed for that:

- **A single authoring guide** (`PIPELINE_GUIDE.md`) covers the manifest schema, operation API, bridge API and two complete worked examples, written to be pasted into an AI conversation as-is.
- **An `exchange new-pipeline` scaffold** generates a working package skeleton from a source type and target.
- **A test harness** (`exchange test-pipeline`) runs a pipeline on sample dossiers in a temporary endpoint, with full logs, so an AI's draft can be checked without touching real environments.
- **Dry runs** show the planned operations and outputs without executing.
- **Trust:** pipelines run arbitrary code, so installing a package shows its author, its bridges and the folders it writes to, and asks for confirmation.

A visual node editor is out of scope for now; typed operations keep that option open. Official pipelines are shared through Exchange's GitHub repository.

## Requisitions

A requisition is one conversion job — source, pipelines, parameters and endpoint — planned visibly, queued, and recorded in the dossier's ledgers when fulfilled.

### Starting a requisition

Right-click a dossier, product or collection and choose **Requisition to…**, or click a candidate brick in an environment view. Only pipelines whose prerequisites are green and whose input predicate matches are offered.

**Source selection.** If the target environment already has an entry for the dossier, the form offers both routes: *Copy from existing entry* (e.g. the pink donut in "Test Requisitions", a fast copy pipeline) or *Convert from source* (the original GLB, a full pipeline). Modified entries are offered too, labelled as such.

**Chains.** When no direct pipeline exists, Exchange can chain pipelines (e.g. G2 → G8 → Skyrim). Intermediate results are saved as real entries by default, so the G8 character is usable in Daz too.

### The plan

A product-level requisition opens as a plan: a tree of the product's child dossiers, each with its assigned pipeline, an include checkbox and its options. For Marius → Skyrim:

| Child dossier | Pipeline | Notes |
| --- | --- | --- |
| Head morph | G9 Head Morph → Skyrim Head | Target body chosen in options |
| Body morph | G9 Body Morph → Skyrim Body | Shares the Daz export step with the head |
| Head texture set | G9 Texture Set → Skyrim Skin | DDS conversion |
| Body texture set | G9 Texture Set → Skyrim Skin | Same pipeline, second instance |
| Eyebrows | G9 Eyebrows → Skyrim Head Part | |

The plan also lists dependencies pulled in as inputs (Genesis 9 Base) and warns when one is missing. Shared operations run once and feed every pipeline that needs them.

### Options and presets

- **Parameter forms** are generated from pipeline manifests and pre-filled from the dossier where possible (name, variant).
- **Presets** are saved at the requisition level, so a "G9 Male → Skyrim (HIMBO)" preset stores options for every child pipeline in the plan.
- **Presets are files,** shareable and shippable inside pipeline packages.
- **Last-used options** are remembered per pipeline even without a preset.
- **Batch apply:** select ten G9 characters, apply a preset, queue all ten.

### Queue and execution

- Requisitions are added to the **queue** and run when the user presses Run (or immediately, if set). The queue can be reordered, paused and left running overnight.
- **Concurrency per resource:** at most one job per heavy external app (one Daz, one Blender instance by default); command-line operations run in parallel.
- Each requisition gets a **working directory** for intermediates, kept until fulfilment (or longer for debugging).
- **Logs** are captured per operation and viewable from the queue.
- **Manual checkpoints:** a pipeline may pause for human work (e.g. open the result in Blender for weight-paint touch-up), then continue when the user clicks Resume.

### Lifecycle

| State | Meaning |
| --- | --- |
| Available | A matching pipeline exists; shown as a candidate |
| Queued | Planned and waiting in the queue |
| Running | Operations executing |
| Needs attention | Paused at a manual checkpoint, or a child failed and needs a decision |
| Fulfilled | Output written; ledger entries and sidecar manifest created |
| Partially fulfilled | Some children succeeded; failed children can be retried alone |
| Failed | Nothing written; logs kept |
| Stale | Fulfilled earlier, but the source, pipeline version or parameters have since changed; "Rebuild stale" re-runs it |

## Output, attribution and data safety

Exchange writes only where the user points it, records what it wrote, and keeps track of whose work went into every output.

### Output

- **New containers by default.** Requisitions write to a new or Exchange-managed container (an MO2 mod, a Daz content directory), never into an existing user mod unless explicitly chosen.
- **Collision handling:** if output files already exist, the user chooses overwrite, rename or skip; the default is to stop and ask.
- **Sidecar manifest:** each output container gets an `.exchange` manifest listing dossier IDs, source entries, pipeline versions and parameters.
- **Asset art only, for now.** Pipelines focus on the art assets themselves; generating plugin records (ESP entries, game data) is deferred.

### Attribution and licensing

- **Original author** (Daz PA, mod author) is filled in automatically when Exchange can locate it from manifests, `meta.ini`/Nexus IDs or store pages, and is editable.
- **License fields:** license type, redistribution allowed (yes/no/unknown), source URL.
- **Endpoint check:** when content marked non-redistributable flows to a *publishable* endpoint, Exchange warns but does not block.
- **Credits file:** a requisition can write a `CREDITS.txt` listing every original author and source used, ready for a mod page.

### Online lookups

Exchange works fully offline; online lookups are optional enrichment that the user turns on source by source.

- **Opt-in consent:** all lookups are off by default. First run offers them once, and Settings › Online lookups lists each source with what it fetches and what it sends. Each source has its own toggle, and any environment can be excluded.
- **Network access:** lookups run only during enrichment and only to enabled sources. They send identifiers already in local metadata (a Nexus mod ID, a store product ID), never file contents, folder paths or a list of the user's library. Requests are rate-limited, and results are cached locally with their fetch date and refreshed on demand.
- **Store-site terms:** Exchange uses official APIs where they exist (e.g. the Nexus Mods API with the user's own API key). Where no API exists, it stores the product link and attribution only rather than scraping pages. Fetched promo images are cached for display in Exchange and never written into requisition output.
- **Provenance:** every looked-up field shows its source and date. User edits override looked-up values, as with any scanned value.
- **Offline behaviour:** with lookups off or no connection, everything still works; affected fields read "not looked up".

### Data safety

- **Scans are read-only,** stated in the UI.
- **Every write is logged** with the files it created, so an Exchange output can be cleanly removed (moved to a recycle folder, never hard-deleted).
- **Database backups** run automatically before migrations and on a schedule; the database and thumbnail cache are portable.
- **Rebuildable from disk:** sidecar manifests plus a rescan reconstruct ledgers if the database is lost; only user overrides need the backup.

## Architecture

Exchange is one Python core package with a desktop UI and a command line on top, so pipelines, tests and the app all share the same code.

```
   ┌──────────────────────┐        ┌──────────────────────┐
   │ Desktop UI (PySide6) │        │ Command line         │
   └──────────┬───────────┘        └──────────┬───────────┘
              └──────────── both call ────────┘
┌───────────────────────────────────────────────────────────────┐
│ Exchange core (Python package)                                │
│ ┌──────────┐ ┌──────────────┐ ┌──────────────┐ ┌────────────┐ │
│ │ Scanner  │ │ Library DB   │ │ Requisition  │ │ Plugin     │ │
│ │ detect,  │ │ SQLite:      │ │ engine: plan,│ │ loader:    │ │
│ │ scan,    │ │ dossiers,    │ │ queue, run,  │ │ definitions│ │
│ │ classify │ │ ledgers,     │ │ write        │ │ and        │ │
│ │          │ │ overrides    │ │ sidecars     │ │ pipelines  │ │
│ └────┬─────┘ └──────────────┘ └──┬────────┬──┘ └─────┬──────┘ │
└──────┼───────────────────────────┼────────┼──────────┼────────┘
       │ reads          writes     │        │ drives   │ loads
       ▼                output     ▼        ▼          ▼
┌───────────────────────────────────┐ ┌───────────┐ ┌───────────────────┐
│ Environments on disk              │ │ App       │ │ Plugins and data  │
│ Daz, Unreal, MO2 mods, loose      │ │ bridges   │ │ files: pipeline   │
│ folders                           │ │ Blender,  │ │ packages, env and │
│                                   │ │ Daz, UE,  │ │ type definitions  │
│                                   │ │ CLI tools │ │                   │
└───────────────────────────────────┘ └───────────┘ └───────────────────┘
```

Only the scanner reads environments and only the requisition engine writes to them; everything external is reached through bridges or loaded as plugins.

### Stack

- **Python** for the core, UI and most pipelines. Electron or Tauri were rejected: they add a second language, an IPC bridge and heavier memory use for UI polish alone.
- **PySide6 (Qt)** for the UI; its model/view system virtualizes grids of 100k+ thumbnails, and its LGPL license suits distribution.
- **SQLite** for the library database, with a thumbnail cache on disk.
- **A file watcher** for change detection.
- **Worker processes** for requisitions, with a lock per external app so only one Daz or Blender job runs at a time.
- **Headless thumbnail rendering** for meshes without previews, via a lightweight renderer or Blender for complex formats.
- **A single-folder installer** built with PyInstaller or Nuitka.

## Roadmap

Build the library first and prove requisitions on Daz before touching game environments.

1. **Foundations:** core package, SQLite schema, environment and dossier-type definition formats, command-line scan.
2. **Library:** Daz, Unreal and Loose Files environments; three-phase scanning; dossiers and ledgers; main window with browser, inspector, search and thumbnails.
3. **Curation:** Unidentified desk, lexicons, override layer, merge/split, collections.
4. **Requisitions v1:** operations, Blender bridge, pipeline packages and prerequisites, queue, sidecar manifests. First pipeline: Daz cross-figure (G9/G2 → G8), then VaM backporting and DS3 legacy conversion.
5. **Game environments:** MO2 for Bethesda games, Garry's Mod, VaM; packed-archive extraction; copy pipelines; first game pipelines (GLB → Starfield static and ingestible).
6. **Breadth:** Mass Effect LE, Vortex, authoring guide and scaffold polish, author and promo lookups, credits files.

## Open questions

- **Offline drives:** environments on disconnected drives should show as *offline*, with their entries kept rather than retired. How long before an offline environment prompts the user?
- **Variant grouping:** automatic, or suggested for confirmation?

## Decided

- **Intermediates in chains:** when G2 → G8 → Skyrim runs, the G8 result is saved as a real Daz entry by default, so the character is usable in Daz too.
- **Online lookups:** opt-in per source; see Online lookups.
- **Daz Connect content:** cloud-installed products merge with DIM products into one product dossier, so a product installed both ways appears once.
- **Sharing pipelines:** a dedicated sharing service is deferred. For now, official pipelines are shared through Exchange's GitHub repository.
