# Exchange — Design Specification

> **Reference since 2026-10-28.** [VISION.md](VISION.md) is the brief: it sets what Exchange is for and what's in scope, and wins where this file disagrees. This file still describes how the built parts work.

Last updated 2026-10-24. This file is the source of truth for how Exchange works. Its companion, [IDENTITY.md](archive/IDENTITY.md) (archived), says what Exchange is for: thesis, pillars, feel, boundaries and goals. When they seem to conflict, identity wins and this file gets fixed.

Exchange is a personal, AI-assisted mission control for building sprawling interactive 3D worlds, in Unreal Engine or by modding Bethesda games. It holds each project's identity, maps the project's growing structure into domains and claims, catalogs every 3D asset Luke owns across every game, engine and content library, and dispatches work to CLI agents and creative tools from one place. Converting assets between environments is a queued, repeatable job.

## Vision and principles

**Thesis:** Exchange takes discrete ideas, assets and processes and harmonizes them into larger compositions: projects.

Exchange began as an asset manager, because dealing with assets is the albatross around every modder's neck. It is now the workspace around those assets. Solo developers wear every hat, and the projects they build sprawl. Exchange's job is not to limit sprawl but to keep it legible: every idea written down, dated and connected; every asset found and matched to the work that needs it; every repetitive task automated or handed to an agent, so the developer's attention stays on design decisions.

The product pillars are in `archive/IDENTITY.md`. The engineering principles below hold across every part of the design.

1. **Asset-centric, not environment-centric.** A dossier describes what an asset *is*. Where it lives is tracked separately, in ledgers.
2. **Read-only until asked.** Scanning never modifies an environment. Exchange writes to environments only through requisitions or explicit user actions, and says so in the UI. Project homes are the one place that Exchange, the user and agents write freely.
3. **The user's work is never lost.** Manual edits to metadata, links and tags form a layer that always survives rescans. Project homes are git-tracked.
4. **Confidence over certainty.** Every automatic identification carries a confidence score. Low-confidence results go to a review queue instead of polluting the library.
5. **Show the plan, then automate.** A requisition shows exactly what will be converted, how and where before it runs.
6. **Incremental everywhere.** Rescans, conversions and rebuilds only touch what changed.
7. **Extensible through data and plugins.** Environments, lexicons and dossier types are data files; processes are plugins. The core never needs editing to support a new game.
8. **Built for AI-assisted authoring.** Most processes will be written with AI help, so the process SDK is small, typed, documented and testable in isolation.
9. **Scripts first, tokens second.** Deterministic automation is the default. Agents fill gaps, repair failing scripts and turn their own successful work into new scripts. Tokens are a finite resource.
10. **Plain files, readable by agents.** Project knowledge lives in text files that the user, git and any agent can read. Databases index those files; they never replace them.
11. **Agents work through Exchange.** Agents read and write project homes, and reach the library and requisition engine through the Exchange MCP. They never write into environments directly.

## Core concepts

Every later section uses these terms exactly as defined here.

**Library**

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
| Role | A process-derived capability: what a dossier can become | Starfield Ingestible candidate |
| Lexicon | An editable word list that turns filename tokens into tags, variants or structure | Food lexicon: donut, apple, bread |

**Processes**

| Term | Definition | Example |
| --- | --- | --- |
| Operation | One atomic, reusable step with typed inputs and outputs | Convert texture to DDS |
| Process | A defined, repeatable chain of operations, usually taking one dossier type to one target (formerly *pipeline*) | G9 Head Morph → Skyrim Head |
| Requisition | One queued run of one or more processes: source, processes, parameters and endpoint; may span a whole product | "Marius → Skyrim NPC" |
| Endpoint | Where a requisition's output is written | New MO2 mod "Exchange – Marius" |

**Projects**

| Term | Definition | Example |
| --- | --- | --- |
| Project | A world being built, in Unreal Engine or as a Bethesda mod; often open-ended | Sirenne (UE) |
| Project home | The project's git-tracked folder of plain files, separate from the Unreal project or mod folders it builds | `Projects/Sirenne/` |
| Identity | A project's premise, pillars, feel and boundaries; changes only through amendments | Sirenne's `IDENTITY.md` |
| Amendment | A dated, reasoned change to an identity, kept in its log | "Shifted from Daz character spaces to a city simulation" |
| Domain | A node in a project's growing structure: a district, faction, character, system or questline; in a game project, a record | `DIST_Docks` |
| Record | A typed unit of compiled game data, named by a signature-prefixed editor ID, with a maturity level instead of a status | `NPC_DockMaster` |
| Maturity | How far a record has come: Sketch, Spec, Stub, Built, Polished (0-4) | Spec |
| Goal | A finite milestone that is either done or not | "Gallery system works" |
| Claim | A dated unit of work or idea, attached to a record or domain and optionally a goal | "Smugglers' market under the east docks" |
| Need | Something a claim requires, often an asset matched against the library | "market stalls kit" |
| Target | An endpoint a project registers: the Unreal project or mod folders its output lands in | `D:/Unreal/Sirenne/Sirenne.uproject` |

**Workspace**

| Term | Definition | Example |
| --- | --- | --- |
| Session | One CLI agent or shell conversation in the Chats window, resumable from history | Claude Code in Sirenne, "Docks lighting" |
| Exchange MCP | The MCP server Exchange gives every session, exposing projects, the library and requisitions as tools | `search_library`, `update_claim` |
| Devlog | The project's dated log of what happened, mostly written automatically | `devlog/2026-10.md` |

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
- **Commands:** launch actions the Workspace offers, such as opening the Unreal editor on a project, starting Daz Studio, or launching a game through MO2. Each command declares its executable, arguments and a safety level (*open* or *run*).
- **Game data tooling (Bethesda):** which tool serializes this game's plugins to text, if any (see Game data).

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

**First-run auto-discovery** reads files that already know install locations: Steam's `libraryfolders.vdf`, the Epic launcher manifest, Unreal's recent projects, Daz/DIM content directory settings and MO2 instance configs. Exchange presents a checklist of everything it found.

### Endpoints and targets

Every writable environment has at least one endpoint. Endpoints carry a **visibility** of *personal* or *publishable*, used by license checks. Defaults by layer: MO2 creates a new mod per requisition (or appends to a chosen Exchange-managed mod); Daz writes to a dedicated "Exchange Conversions" content directory; Unreal writes to a configurable content folder.

A **target** is an endpoint registered by a project: the Unreal project it builds, or the MO2 mod folders it ships. A target is also an environment (or a container inside one), so it is scanned like any other. That means a project's asset list needs no separate file: it is the ledger entries in its targets plus the needs of its claims.

An endpoint folder outside the environment's roots (a requisition's chosen folder, a claim's absolute folder, or the environment's `endpoint` setting) joins that requisition's environment as a root, whatever its type, instead of becoming a new environment; a folder that is already a root keeps the environment it has. Entries appear only for what that environment's layer indexes, so output outside MO2's `mods/` or Unreal's `Content/` stays on disk with no entry. A claim walked to such a folder, absolute or inside the root, stops at Converted, and its turn line says that the place doesn't read that folder and to choose one it reads. A place of a single-root type writes only through its first root, whatever its status: when that root is offline, writing to the place is refused, and a folder that joined it is never a fallback (a `multi_root` type uses any online root). A joined folder can be forgotten on its own with `exchange env forget <id> --root <folder>`, which removes what was scanned from it and keeps the place, its other roots and the user's edits; it is refused for the first root of a single-root place and for a place's only root (`exchange env forget <id>` removes the place), while any root of a `multi_root` place can go. Adding a folder a place already holds with another type (`exchange env add`, or the register route) is refused unless it is the place's first root or the place is `multi_root`, so a joined folder can't retype its place.

## Scanning and indexing

Scanning runs in three phases so product bricks appear within minutes and detail fills in afterward in the background.

| Phase | What it does | Cost | The user sees |
| --- | --- | --- | --- |
| 1. Discovery | Walk the tree; record path, size, modification time | Fast | File counts, folder structure |
| 2. Identification | Group files into containers, products and dossiers per environment rules; tokenize names against lexicons | Medium | Product bricks, tags, Unidentified count |
| 3. Enrichment | Hashing, mesh fingerprinting, dependency parsing, thumbnail rendering, promo images and author lookup | Slow, background | Thumbnails fill in; duplicates and variants merge |

When a scan finishes, the Workspace shows a **new acquisitions** report: the products and dossiers that are new since the previous scan.

### Product grouping

- **Daz manifests are hints, not truth.** `.dsx` support files seed product membership, then Exchange reconciles against reality: match by expected relative path, then filename + size, then hash. Files found elsewhere are marked *relocated*, not missing, and product identity rests on content, so manually installed products still group.
- **Daz Connect products merge with DIM products** into one product dossier, so a product installed both ways appears once.
- **Saved Daz files** (a character, outfit or scene subset saved from Daz Studio) are in no manifest and in no folder a rule knows. Each `.duf` outside `data/` and `Runtime/` that no product holds and no type rule matches has its head read, the first 64 KB through `readonly`, and its `asset_info.type` decides: `character`, `wearable` and `scene_subset` become a Daz character preset, wearable or scene subset (`asset_types` in `daz_studio.toml`) at confidence 0.6, a dossier of its own with no parent, whose signal names the type read. Any other type, or a file that can't be read, stays unattached. Type rules and products keep winning, so nothing identified before changes.
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
- **Tags and roles:** tags describe (Food, Pink); roles say what the dossier can become, derived from installed processes.
- **Variants:** sibling forms of one asset (Donut01_Pink, Donut01_Blue) held as one dossier.
- **Hierarchy:** product dossiers contain child dossiers (Marius → head morph, body morph, texture sets, eyebrows).
- **Dependencies:** dossiers this one needs (Marius requires Genesis 9 Base).
- **Origin:** original author (Daz PA, mod author) auto-filled when found, source URL, license, and promo images.
- **Acquired:** the date Exchange first found the asset.
- **Ledgers:** one per environment where the asset exists.
- **Relations:** the claims that need or use it, and the projects whose targets hold it (see Relations).

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
| Requisitioned | Produced by a requisition; source, process versions and parameters recorded |
| Copied | Copied from another entry in the same environment by a copy process |
| Unknown provenance | Matched by hash on rescan, not produced by Exchange (e.g. a manual copy) |
| Modified | Files changed after creation; may now be the preferred copy source |
| Stale | Source or process changed since this entry was produced; can be rebuilt |
| Retired | No longer on disk; kept as history |

A dossier remains while any ledger holds a live entry. A dossier with only retired entries is hidden by default but kept.

### Dossier types

Types are data definitions with two scopes:

- **Universal:** static mesh, skinned mesh, texture set, material, skeleton, animation, audio.
- **Environment-specific:** Daz morph, Daz character preset, Daz wearable, Daz scene subset (a bag of things), Skyrim NPC, Starfield Ingestible, Unreal Blueprint actor.

The browser's environment filter shows a given environment's native types plus any dossier with a role there. Type definitions can be extended by the user and by process packages.

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
| Theme | Sci-Fi, Fantasy, Historical | Marks category folders in hand-sorted Daz libraries |
| Known authors | built from manifests and `data/<vendor>/` | Marks vendor folders; products below one get that author |

Default lexicons ship with Exchange. The user edits them, creates new ones (e.g. a food list), and can add synonyms and plurals.

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

## Projects

A project is a world being built. Many projects are open-ended explorations of a setting with no planned end. Exchange is designed to let them sprawl while keeping them legible: identity changes deliberately, structure grows freely, and finite work is tracked as goals and claims.

### Project kinds

| Kind | Targets | Typical processes |
| --- | --- | --- |
| Unreal | One `.uproject` (plus plugins developed alongside it) | Daz character → Unreal, records compiled into Data Assets and DataTables, cook and package |
| Bethesda | One or more MO2 mod folders in one MO2 instance (main plugin plus patches) | Assets into a game, plugin build from `data/`, archive packing |

### Project home

The project home is a git-tracked folder of plain files. It is separate from the Unreal project and mod folders it builds: those are targets, with their own version control (Unreal projects may use Git LFS or Perforce; mod folders live under MO2). The layout follows `archive/GAME_DATA_MODEL.md`:

```
NJO/
├─ exchange.project.toml   name, kind, targets, created, format version
├─ IDENTITY.md             premise, pillars, feel, boundaries, amendment log
├─ goals.md                the project's goals
├─ coverage-rules.yaml     per-type expectations (see Claims)
├─ schemas/                project-exclusive record types, one file per signature
├─ records/                one folder per signature, one file per record
│  ├─ NPC_/NPC_DockMaster.md
│  └─ LOT_/LOT_SaltRowCantina.md
├─ claims/                 one file per claim, flat
└─ .exchange/              caches, session links, receipts (gitignored)
```

Later features add their own folders: `AGENTS.md` and `CLAUDE.md` (generated by Exchange for agent sessions; not edited by hand), `decisions/`, `knowledge/`, `devlog/`, `art/` (concept art with prompts and takes, in Git LFS), `processes/` (project-specific process packages) and `data/` (game data that are not records; see Game data).

Files are the source of truth. Front matter is YAML between `---` lines. Exchange reads the files directly; an index in the library database, for fast queries and backlinks, rebuilt from the files whenever they change, comes with the Workspace's project views. `exchange.project.toml` marks a folder as a project home.

### Identity

`IDENTITY.md` holds the project's premise, pillars, feel and boundaries, as `##` sections, and its amendment log. It is pinned as the header of the project's mission-control view and compiled into the generated `AGENTS.md`/`CLAUDE.md`, so every session in the project starts with it.

Identity changes only through **amendments**: a dated entry in the amendment log saying what changed and why. A project is allowed to change form; the log makes sure it does so on purpose, and that the original intent is never silently lost.

New projects are created through an **identity interview**: an agent asks a few questions at a time, drafts each section, and the user corrects it. Templates seed the interview by kind (Unreal game; Bethesda total conversion, gameplay overhaul, asset pack, patch).

### Domains and records

Domains are the world's structure: districts, factions, characters, systems, questlines. They grow without limit, so sprawl has somewhere to land. **In a game project the domains are records:** typed units of compiled game data, one Markdown file each, named by an editor ID whose signature prefix is the record type (`NPC_DockMaster`, `FACT_PortAuthority`, `LOT_SaltRowCantina`). A signature that ends in `_` uses that underscore as the separator. Records link to each other by editor ID and carry a maturity level (Sketch, Spec, Stub, Built, Polished; stored as 0-4) instead of a status. `archive/GAME_DATA_MODEL.md` holds the record families, the maturity ladder and the authoring views.

```markdown
---
id: NPC_DockMaster
maturity: 1
race: RACE_Human
look: { dossier: <dossier uid>, process: daz-g9-to-g8-to-ue }
factions:
  - { faction: FACT_PortAuthority, rank: Harbormaster }
---
Prose profile: history, personality, what they want.
```

Each signature has a schema: the core ships one per signature, and a project home's `schemas/` defines its project-exclusive types. A schema lists the fields, their types (text, numbers, enums, links to records of named signatures, dossiers, processes, claims, lists, objects) and the maturity at which each must be filled. Validation checks records and claims against the schemas, resolves every link, and opens gap claims (see Claims).

Claims are not stored with records: they stay flat in `claims/` and name their target. Reorganizing the structure therefore never moves claim files.

### Goals

A goal is a finite milestone with a "done when" statement. Projects need not have an end, but goals always do. They are listed in `goals.md`, numbered like the identity's:

```markdown
---
goals:
  - { id: G1, title: Gallery system works, status: active,
      done_when: "Characters can be browsed, posed and screenshotted in-game" }
---
Notes on the goals.
```

`status` is planned, active, done or dropped.

### Claims

A claim is a dated unit of work or idea. It targets a record (or a domain), may serve a goal, and moves through a small set of states:

| Status | Meaning | Set by |
| --- | --- | --- |
| Idea | Captured, not yet concrete enough to work on | Anyone |
| Open | Concrete and ready to be claimed | Anyone |
| Claimed | Someone is working on it: the user, or an agent session | Anyone |
| Review | Work is finished and waiting for the user | Agent, user or validation |
| Done | Accepted | The user only |
| Dropped | Abandoned, kept as history with a reason | The user only |

The file name's stem is the claim's ID, its date and a slug:

```markdown
---
id: 2026-10-24-spec-salt-row-cantina
status: open
created: 2026-10-24
target: LOT_SaltRowCantina
goal: G5
source: gap                  # manual | gap | ladder | coverage | mining
needed_by: [NPC_DockMaster]
claimed_by: ""               # "luke" or a session ID
triage: new
---
The dockmaster's evening schedule points here, but the cantina is still a Sketch.
```

- **Derived claims:** most claims are derived from the records (`archive/GAME_DATA_MODEL.md`, *Claim derivation*). **Gap claims** open directly when validation finds a link to a record that does not exist or is not mature enough, or a broken dossier link. One gap claim stays open per target, `needed_by` lists every record waiting on it, and a fixed gap moves its claim to *review*. Ladder, coverage and mining claims wait in the triage inbox as proposals. Coverage rules live in one file per project, `coverage-rules.yaml`.
- **Fast capture:** a capture box in both windows, and `exchange capture` on the command line, turns one line into an *idea* claim or, when the line starts with an editor ID, a Sketch record. In a window it defaults to the record or domain in view. Agents can create claims through the Exchange MCP.
- **Needs:** a claim can list `needs`. An asset need carries a library search query. Exchange shows what matches: dossiers already in a target, dossiers elsewhere with a process that can bring them in, or nothing found.
- **Agent work never self-approves.** Agents move claims as far as *review*. Done is the user's call.

### Relations

Exchange's job is connecting things, so relations are first-class. Records link to records by editor ID and to assets by dossier uid (`{ dossier: … }`), so any agent can follow them with a text search. Claims, goals, decisions, dossiers, processes and sessions are referenced with typed prefixes where a bare ID would be ambiguous (`claim:`, `goal:`, `decision:`, `dossier:`, `process:`, `session:`), in front matter or inline in the body. The index computes backlinks, and every inspector has a **Relations** panel (for records, xEdit's *Referenced by*): a dossier shows the claims and records that want it, a record shows everything that links to it, a decision shows the claims it settled.

### Game data

Game data is in scope. **Records are the source of truth for the game's data;** the compile process turns them into what the engine reads.

- **Unreal:** a compile process reads the record files and writes Data Assets and DataTables through Unreal's editor Python. The project home owns definitions; Unreal owns geometry, placement and presentation (`archive/GAME_DATA_MODEL.md`, *Getting records into Unreal*).
- **Bethesda:** plugins serialized to text in `data/plugins/<plugin>/`, using the serializer the game's environment definition names (Spriggit for the games it supports, tes3conv for Morrowind). A *build plugin* process converts the text back into an ESP/ESM/ESL in the target mod folder. Plugins become diffable, reviewable and editable by agents.

### Devlog and knowledge

- **Devlog:** dated entries in `devlog/YYYY-MM.md`, mostly written automatically from session handoffs, claims reaching review or done, fulfilled requisitions and amendments, plus anything the user adds by hand.
- **Decisions:** one file per decision in `decisions/`, linked to the claims and domains it affects.
- **Knowledge:** free-form notes and research in `knowledge/`, rendered and editable in the Workspace.

## Workspace and agents

Exchange has two desktop windows that minimize independently: **Chats**, where work is handed to CLI agents, and **Workspace**, where the user sees and steers everything else. Chats can stay visible while the Workspace is minimized, beside Blender, Daz Studio or the Unreal editor.

### Chats window

The Chats window comes from the Mr. Mak Workspace fork (see Architecture). It runs each CLI in a real terminal, so agents keep their own logins, subscriptions and features.

- **Sessions in tabs:** one click opens Claude Code, Codex, Kimi, PowerShell or another configured CLI, each in its own tab. Tabs can be grouped by project, pinned, renamed and colored.
- **History and restore:** closing a tab archives it; history restores it into the same native conversation, using the CLI's own recorded conversation ID and transcript.
- **Conversation view:** Claude Code and Codex sessions can switch between the raw terminal and a message view with Markdown and images. CLI permission menus appear as buttons.
- **Attachments:** paste images (saved to the project home's `.exchange/attachments/`), and drag and drop files or folders to insert their paths.
- **Permission bypass per session:** the new-session dialog has a *bypass permission prompts* checkbox, off by default. A bypassed tab carries a persistent badge. When a bypassed session starts in a project, Exchange takes a git checkpoint of the project home first. Bypass removes the agent's own prompts and Exchange cannot sandbox it: environments stay protected by the rules in `AGENTS.md`, by working through MO2 rather than a game's `Data` folder, and by the checkpoint.
- **Project-bound sessions:** a session started from a project runs in its project home, reads the generated `AGENTS.md`/`CLAUDE.md` (identity summary, active goals, working rules, skill paths) and gets the Exchange MCP attached.
- **Session presets:** a saved combination of CLI, project, bypass setting, skill and opening brief, such as "Blender cleanup worker".
- **Handoffs:** long sessions offer *summarize and continue*. The handoff opens a fresh session and is also added to the devlog.

### Dispatching claims

Dispatch turns a claim into agent work:

1. The user chooses **Dispatch** on a claim and picks a CLI or session preset.
2. Exchange writes a brief from the claim: intended result, domain and goal context, needs and matched dossiers, related decisions, the skills to use, and acceptance checks.
3. A new session opens in the project home with that brief. The claim becomes *claimed*, with `claimed_by` set to the session.
4. When the agent finishes, it moves the claim to *review* through the Exchange MCP. The claim links to the session, so the user can read exactly what happened.
5. The user marks it *done*, or sends it back with notes.

### Exchange MCP

Every session gets the Exchange MCP, so all CLIs share one interface to the workspace, and agents query instead of crawling folders.

| Tool group | Tools |
| --- | --- |
| Projects | `project_identity`, `list_domains`, `list_goals`, `list_claims`, `get_claim`, `create_claim`, `update_claim` (up to *review*), `append_devlog`, `record_decision` |
| Library | `search_library` (the search language), `dossier_detail`, `match_needs` |
| Processes | `list_processes`, `plan_requisition`, `queue_requisition`, `requisition_status` |
| Data | `read_data`, `write_data` (inside the project home's `data/`) |

Agents can queue requisitions; running the queue follows the user's queue setting, as for any requisition. No MCP tool writes into an environment.

### Skills

Exchange keeps a shared skills library and syncs it into each project home's agent folders (`.agents/skills/` and `.claude/skills/`), as Mr. Mak does. Skills from the fork that Exchange keeps:

- **Concept art:** `image-reference-workflow` (exploration and faithful edits), `character-sheet-pipeline` (modeling sheets and parts), `fal-ai-generation` and `higgsfield-workflow` (providers). fal.ai, billed per generation, is the default; Higgsfield is added if the workflow is in weekly use. Accepted and rejected takes, with prompts and short rejection reasons, go into the project home's `art/` and link to their claim. Job receipts stay in `.exchange/`, out of git.
- **Planning and handoffs:** `plan`, `feature-handoff`.
- **3D and game production:** `3d-production-routing`, `blender-game-animation` and the game workflow skills, adapted to Unreal and Bethesda targets.

Exchange adds its own skills: the identity interview, claim dispatch briefs, process authoring and repair, and the charter (identity) drift review.

### Drift review

A *drift review* process compares recent devlog entries and new claims against the project's identity. It flags claims that contradict the identity or a recorded decision, so the user either amends the identity or reworks the claim. It checks coherence, not size: growth is never flagged by itself. It runs when a goal is completed and on demand.

## User interface

The Workspace window is HTML in the Tauri shell. Its look is a **used-future command deck**: dark panels, phosphor amber and teal readouts, segmented gauges, the warmth of 70s–80s sci-fi computer displays. It is an original look inspired by that era, not a copy of any film's UI. Color is reserved for meaning (status, attention, selection), so the flavor never costs readability. It is an interface to be stared at all day.

The PySide6 window was the working UI until the Workspace window reached library parity; it was removed in R2c.

### Views

- **Mission control** (a project's home view):
  - The identity header: premise and pillars, always visible.
  - Goal progress.
  - Claims by domain, showing where work and ideas are piling up.
  - Live sessions and what they are working on.
  - The requisition queue.
  - Recent devlog entries.
  - The *revisit* list: claims untouched for a long time, shown as a prompt, not a reproach.
  - New acquisitions from the latest scan.
- **Claims:** a board by status, filterable by domain, goal and age, with the capture box at the top.
- **Domains:** the domain tree with claim counts, opening into each domain's notes, claims and assets.
- **Library:** browsing and curating dossiers (below).
- **Knowledge:** Markdown notes, decisions and the devlog, rendered and editable.
- **Queue:** requisitions, their logs and lifecycle.
- **Settings.**

Every view's inspector includes the Relations panel.

### Library view

The library view keeps the layout of the original main window. A visual mockup of it and of the add-environment flow is in `docs/Exchange_Main_Window_Add_Environment.html`.

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
│ ▸ Daz Studio  │  [ ] show candidates               │ Relations     │
│ ⚠ Unidentified│                                    │ Origin · Files│
├───────────────┴────────────────────────────────────┴───────────────┤
│ Scan: Daz Main Lib, phase 3 (thumbnails) · Requisitions: 2 queued ▾│
└────────────────────────────────────────────────────────────────────┘
```

- **Sidebar:** the whole library, collections, then environments › containers or dossier types, and the Unidentified desk with a count.
- **Browser:** a virtualized grid or list of bricks, paged from the query API so libraries of 200k+ dossiers stay fast. Toggles for grouping (by product or by dossier type), scope (one environment or all) and the environment filter.
- **Item cards:** browsing assets should feel like looking over loot. Each brick is an item card; the inspector's overview is its stats panel: type, polycount, texture resolution, environments it exists in, environments it can be converted to, acquisition date. A product reads as a set, showing which of its pieces are present where.
- **Entries vs candidates:** inside an environment view, solid bricks are existing entries and ghosted bricks are available requisitions, with a "show candidates" toggle.
- **Inspector:** tabs for overview, ledgers (with entries and provenance), variants, requisitions available, relations, dependencies, origin/license, files and history. All fields editable.
- **Bottom bar:** scan status and the requisition queue, expandable into the queue view.
- **Context menu on a brick:** Requisition to…, Copy to… (from an existing entry), Use in claim…, Extract (packed archives), Open in app, Show in folder, Merge, Add to collection.

### Search

Free text plus filters, all composable and saveable as smart collections:

`donut env:starfield tag:food -tag:damaged type:mesh author:"Jane Doe" status:stale has:candidate`

Claim needs use the same language.

### Collections

Manual collections ("Lard Lads assets") and smart collections (saved searches). Collections can be requisitioned as a batch.

### Settings

- **Environments:** add, detect, configure organizational layers and endpoints, ignore rules.
- **Projects:** project homes, targets, identity templates.
- **Chats:** configured CLIs, session presets, handoff threshold, terminal appearance.
- **Processes:** installed packages, prerequisite status, presets.
- **Lexicons and dossier types:** edit word lists and type definitions.
- **Online lookups:** per-source toggles (see Online lookups).
- **Storage:** database location, thumbnail cache size, backups.

## Processes

Processes are plugins: chains of modular operations, packaged with their templates, written mostly in Python and mostly with AI assistance. Most processes convert assets between environments; others build a project (cook an Unreal build, build a plugin from `data/`, pack archives) or maintain its knowledge (devlog digest, drift review).

### Operations

An operation is the smallest reusable unit. It declares typed inputs and outputs (e.g. `DazMorph → BlendShape`, `TextureSet(PBR) → TextureSet(DDS)`), its parameters, and which external app it runs in, if any. Typed signatures let Exchange validate chains, reuse a shared step's output across processes in one requisition, and cache intermediates.

Core operations ship with Exchange: copy between containers, texture format conversion, image resize, file rename and pack. Other operations ship inside process packages.

### Executors

Each step names how it runs. Processes prefer the cheapest executor that works, in this order:

| Executor | Runs | Cost |
| --- | --- | --- |
| Script | Headless and deterministic: Blender in background mode, Unreal's commandlet Python, DazScript at launch, command-line tools, xEdit scripts | No tokens |
| Live bridge | Against an app the user already has open, such as Unreal's remote execution or Daz Studio's bridge | No tokens |
| Agent | An agent session using an app's MCP or its own judgement, for steps that cannot be scripted yet | Tokens |
| Manual checkpoint | The user does the work (Creation Kit tasks, weight-paint touch-ups, visual approval), then clicks Resume | User time |

Two loops move work up the table:

- **Crystallize:** when an agent completes a task through an app's MCP, Exchange offers *save as process*, and the agent writes the script version. The tokens are spent once.
- **Repair:** when a script step fails, the user can hand its log and source to an agent session, which proposes a fix to the process instead of doing the task by hand.

### Bridges to external apps

Many operations run inside another application. Exchange provides bridges that launch the app, pass inputs, run a script and collect outputs:

- **Blender:** headless via `blender -b template.blend --python op.py`.
- **Daz Studio:** DazScript run on launch, in a separate instance with settings copied from the main one.
- **Unreal Engine:** Python via commandlet or remote execution.
- **Command-line tools:** texconv, archive packers, NIF tooling, plugin serializers.

A bridge is a first-class step type, so process authors never hand-roll process management. At most one job runs per heavy app at a time.

### Process packages

```
glb_to_starfield_ingestible/
├─ process.toml         manifest
├─ operations/          Python operations
├─ scripts/             scripts run inside apps
├─ templates/           .blend files, project templates
├─ presets/             shipped requisition presets
├─ tests/               sample dossiers + expected outputs
└─ README.md
```

The manifest declares name, version, author, input predicate (dossier type + required tags, e.g. static mesh tagged Food), source and target environment variants, operation chain with each step's executor, parameters with defaults, prerequisites, and which roles it grants. An optional `extensions` list under `[input]` names the file types the process reads, each with a leading dot and compared case-insensitively; empty means any. A chain is offered from a source entry only if that entry holds a live file with one of its first process's extensions; later processes aren't checked, and neither is a copy. The extension is the whole check: no file's contents are read.

Packages live in three places: built into Exchange, installed globally, or in a project home's `processes/` for project-specific work.

### Prerequisites

Each process has a setup page under Settings › Processes listing its prerequisites: external tool paths and versions, templates, plugins (e.g. a Blender add-on). Each shows green or red with a fix hint. A process is selectable only when every prerequisite is green. Setup is one-time, with a cheap recheck on launch (paths and versions still match) to catch tool updates that silently break templates.

### Authoring with AI

Most processes are written with AI help, so the SDK is designed for that:

- **A single authoring guide** (`PROCESS_GUIDE.md`) covers the manifest schema, operation API, bridge API, executors and two complete worked examples. It is also installed as a skill, so any session in Chats can author a process.
- **An `exchange new-process` scaffold** generates a working package skeleton from a source type and target.
- **A test harness** (`exchange test-process`) runs a process on sample dossiers in a temporary endpoint, with full logs, so an agent's draft can be checked without touching real environments.
- **Dry runs** show the planned operations and outputs without executing.
- **Trust:** processes run arbitrary code, so installing a package shows its author, its bridges and the folders it writes to, and asks for confirmation. Processes written by an agent in a project home need the same confirmation before their first run.

A visual node editor is out of scope; typed operations keep that option open.

## Requisitions

A requisition is one run of one or more processes — source, processes, parameters and endpoint — planned visibly, queued, and recorded in the dossier's ledgers when fulfilled. A requisition can be linked to the claim it serves.

### Starting a requisition

Right-click a dossier, product or collection and choose **Requisition to…**, click a candidate brick in an environment view, choose a matched dossier on a claim's need, or let an agent queue one through the Exchange MCP. Only processes whose prerequisites are green and whose input predicate matches are offered.

**Source selection.** If the target environment already has an entry for the dossier, the form offers both routes: *Copy from existing entry* (e.g. the pink donut in "Test Requisitions", a fast copy process) or *Convert from source* (the original GLB, a full process). Modified entries are offered too, labelled as such.

**Chains.** When no direct process exists, Exchange can chain processes (e.g. G2 → G8 → Skyrim). Intermediate results are saved as real entries by default, so the G8 character is usable in Daz too.

**Project targets.** When a requisition starts from a project, the project's targets are offered first as endpoints.

### The plan

A product-level requisition opens as a plan: a tree of the product's child dossiers, each with its assigned process, an include checkbox and its options. For Marius → Skyrim:

| Child dossier | Process | Notes |
| --- | --- | --- |
| Head morph | G9 Head Morph → Skyrim Head | Target body chosen in options |
| Body morph | G9 Body Morph → Skyrim Body | Shares the Daz export step with the head |
| Head texture set | G9 Texture Set → Skyrim Skin | DDS conversion |
| Body texture set | G9 Texture Set → Skyrim Skin | Same process, second instance |
| Eyebrows | G9 Eyebrows → Skyrim Head Part | |

The plan also lists dependencies pulled in as inputs (Genesis 9 Base) and warns when one is missing. Shared operations run once and feed every process that needs them.

### Options and presets

- **Parameter forms** are generated from process manifests and pre-filled from the dossier where possible (name, variant).
- **Presets** are saved at the requisition level, so a "G9 Male → Skyrim (HIMBO)" preset stores options for every child process in the plan.
- **Presets are files,** shareable and shippable inside process packages.
- **Last-used options** are remembered per process even without a preset.
- **Batch apply:** select ten G9 characters, apply a preset, queue all ten.

### Queue and execution

- Requisitions are added to the **queue** and run when the user presses Run (or immediately, if set). The queue can be reordered, paused and left running overnight.
- **Concurrency per resource:** at most one job per heavy external app (one Daz, one Blender instance by default); command-line operations run in parallel.
- Each requisition gets a **working directory** for intermediates, kept until fulfilment (or longer for debugging).
- **Logs** are captured per operation and viewable from the queue.
- **Manual checkpoints:** a process may pause for human work, then continue when the user clicks Resume.

### Lifecycle

| State | Meaning |
| --- | --- |
| Available | A matching process exists; shown as a candidate |
| Queued | Planned and waiting in the queue |
| Running | Operations executing |
| Needs attention | Paused at a manual checkpoint, or a child failed and needs a decision |
| Fulfilled | Output written; ledger entries and sidecar manifest created |
| Partially fulfilled | Some children succeeded; failed children can be retried alone |
| Failed | Nothing written; logs kept |
| Stale | Fulfilled earlier, but the source, process version or parameters have since changed; "Rebuild stale" re-runs it |

Fulfilled and failed requisitions linked to a claim add a line to the project's devlog.

## Output, attribution and data safety

Exchange writes only where the user points it, records what it wrote, and keeps track of whose work went into every output.

### Output

- **New containers by default.** Requisitions write to a new or Exchange-managed container (an MO2 mod, a Daz content directory), never into an existing user mod unless explicitly chosen.
- **Collision handling:** if output files already exist, the user chooses overwrite, rename or skip; the default is to stop and ask.
- **Sidecar manifest:** each output container gets an `.exchange` manifest listing dossier IDs, source entries, process versions and parameters.
- **Game data is in scope.** Processes may build plugins and engine data from a project home's `data/` (see Game data). Plugin records are still not *scanned* into the library as dossiers.

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

Agent sessions and image-generation providers are separate from online lookups: they use the user's own CLI and provider accounts, and only when the user starts them.

### Data safety

- **Scans are read-only,** stated in the UI.
- **Every write to an environment is logged** with the files it created, so an Exchange output can be cleanly removed (moved to a recycle folder, never hard-deleted).
- **Project homes are git-tracked,** with a checkpoint before every bypassed session.
- **Database backups** run automatically before migrations and on a schedule; the database and thumbnail cache are portable.
- **Rebuildable from disk:** sidecar manifests plus a rescan reconstruct ledgers if the database is lost, and project homes rebuild the project index; only curation overrides need the backup.
- **Secrets stay out of git:** provider keys and job receipts live in ignored files, never in project homes' tracked content.

## Architecture

Exchange is a Python core inside a desktop shell forked from [Mr. Mak Workspace](https://github.com/witnesstodark/mr-mak-workspace). The core owns the library, projects and requisitions; the shell owns the windows and the terminal sessions.

```
Desktop shell (Tauri 2, forked from Mr. Mak Workspace; separate repository)
├─ Chats window ──────── CLI sessions in real terminals (xterm.js)
├─ Workspace window ──── mission control, library, claims, queue (HTML)
└─ Shell service (Node) ─ terminals, session history, starts the Exchange service
           │ loopback HTTP + WebSocket, per-launch token
Exchange service (Python, this repository)
├─ API ────────────────── serves the Workspace window
├─ Exchange MCP ───────── tools for CLI sessions
├─ CLI ────────────────── the existing command line
└─ Exchange core
   ├─ Scanner ──────────── detect, scan, classify (reads environments)
   ├─ Library DB ───────── SQLite: dossiers, ledgers, overrides, project index
   ├─ Projects ─────────── project homes: identity, domains, goals, claims, devlog
   ├─ Requisition engine ─ plan, queue, run, write sidecars (writes environments)
   └─ Plugin loader ────── definitions and processes
           │ reads · writes through requisitions · drives through bridges
Environments on disk · project homes · app bridges (Blender, Daz, Unreal, CLI tools)
```

Only the scanner reads environments and only the requisition engine writes to them. Project homes are written by the projects module, the user and agent sessions. Everything external is reached through bridges or loaded as plugins.

### The fork

The shell repository is a fork of Mr. Mak Workspace (MIT license; its license and third-party notices are kept). It keeps:

- the Tauri shell and its two-window model
- the Chats window: terminals, tabs and groups, history and resume, the conversation view, permission-menu buttons, attachments, handoffs, the MCP panel
- the concept-art and production skills listed under Skills

It removes the voice coordinator, mobile access, the persona and its card registry; the Workspace window is rebuilt around the Exchange service. Mr. Mak stays a git upstream while merging is practical: Exchange's additions live in their own folders rather than in edits to upstream files. When the fork diverges far enough, the upstream link is cut deliberately.

### Stack

- **Python 3.11+** for the core, service, MCP server and most processes.
- **Tauri 2** with an HTML frontend (React, TypeScript and Vite, as in the fork) for both windows. This reverses the original decision against Tauri: a two-window workspace with real terminal sessions, available ready-made in the fork, outweighs the cost of a second language. The core stays Python.
- **A Node service** from the fork for terminals and session history. Python's terminal support on Windows is weaker than node-pty's.
- **SQLite** for the library database and the project index, in WAL mode: scans write in a separate process while the service reads.
- **A file watcher** for change detection in environments and project homes.
- **Worker processes** for requisitions, with a lock per external app so only one Daz or Blender job runs at a time.
- **Headless thumbnail rendering** for meshes without previews, via the small numpy/Pillow renderer or Blender for complex formats.
- **Dependencies stay minimal.** The core needs Pillow and numpy. The service and MCP server are optional extras.
- **PySide6** was used until the Workspace window reached library parity; it was removed in R2c.
- **Windows only.**

## Roadmap

The library and the first processes come first, then the workspace around them, proven on a real Unreal project. Goal numbers refer to `archive/IDENTITY.md`.

1. **Foundations** (done): core package, SQLite schema, environment and dossier-type definition formats, command-line scan.
2. **Library** (done): Daz, Unreal, MO2 and Loose Files environments; three-phase scanning; dossiers and ledgers; main window with browser, inspector, search and thumbnails. *G1.*
3. **Curation** (done): Unidentified desk, lexicons, override layer, merge/split, collections, file watcher. *G1.*
4. **Requisitions v1** (in progress): operations, bridges (Blender, Daz Studio, command-line tools), process packages and prerequisites, queue, sidecar manifests, requisitions in the window. First process: Daz cross-figure (G9/G2 → G8), then VaM backporting and DS3 legacy conversion. *G2.*
5. **Chats online:** the shell fork, with sessions for Claude Code, Codex, Kimi and PowerShell, history restore and the per-session bypass checkbox with its tab badge. *G3.*
6. **Service and Workspace:** the local API, the rename to processes, and the Workspace window's library view at parity with the PySide6 window. *G4.*
7. **Project homes:** in two parts. Part 1: the project home's files (identity, goals, records, claims, the coverage rules file), record schemas for `NPC_`, `RACE`, `FACT` and `LOT_`, validation with gap claims, fast capture, and the git checkpoint before bypassed sessions. Part 2, once the Workspace has library parity: the project index, the identity interview, the devlog, mission control, the claims board, and the Card and Table views. *G5.*
8. **Agents connected:** the Exchange MCP, generated agent files, claim dispatch and review, skills sync, drift review. *G6.*
9. **Benchmark:** a fresh Unreal project themed on Sirenne and the wider Star Wars setting, run from Exchange, including a Daz character → Unreal process and records compiled into Unreal. *G7.*
10. **Game environments:** MO2 for all Bethesda games, Garry's Mod, VaM; packed-archive extraction; copy processes; plugin serialization and build processes; first game processes (GLB → Starfield static and ingestible).
11. **Breadth:** Mass Effect LE, Vortex, process guide and scaffold polish, author and promo lookups, credits files.

## Open questions

- **API layer:** the standard library, or a small framework (e.g. FastAPI with uvicorn) as an optional extra? The recommendation is the framework, kept out of the core's dependencies.
- **Daz → Unreal route for the benchmark:** Daz's own Unreal bridge driven as a step, or an FBX export with Blender cleanup as a scripted process?
- **Plugin serializers:** which Bethesda games each serializer covers, especially Fallout 3 and New Vegas.
- **Project-home commits:** besides the checkpoint before a bypassed session (decided), commit when a claim reaches review or done, and on request?
- **Daz cross-figure:** what converts first, and with which tool (open question 1 in PROGRESS.md).

## Decided

- **Intermediates in chains:** when G2 → G8 → Skyrim runs, the G8 result is saved as a real Daz entry by default, so the character is usable in Daz too.
- **Online lookups:** opt-in per source; see Online lookups.
- **Daz Connect content:** cloud-installed products merge with DIM products into one product dossier, so a product installed both ways appears once.
- **Sharing processes:** a dedicated sharing service is deferred. Official processes are shared through Exchange's GitHub repository.
- **Variant grouping:** suggested, accepted or rejected in batches, never automatic.
- **Offline drives:** offline roots keep their entries; a rescan suggests forgetting the environment after 30 days, or just that root (`exchange env forget <id> --root "<path>"`) when it can go alone.

Decided 2026-10-24, with the move to a project workspace:

- **Audience:** Exchange is a personal tool for Luke. Generalizing it is welcome when it costs nothing, never a requirement.
- **Platform:** Windows only.
- **Shell:** fork Mr. Mak Workspace for the shell and Chats window, in a separate repository. The Python core in this repository is kept and becomes the Exchange service.
- **Vocabulary:** pipelines are renamed processes. Endpoints stay; project targets are a kind of endpoint. Units of project work are claims.
- **Open-ended projects:** projects need not have an end point. Goals are finite; identity changes only through amendments; drift review checks coherence, never size.
- **Project homes:** git-tracked and separate from Unreal project and mod folders.
- **Game data:** plugin records and engine data are in scope for project homes, with text in `data/` as the source of truth.
- **Permission bypass:** a per-session checkbox when starting a session, off by default.
- **Image generation:** Mr. Mak's concept-art skills are kept. fal.ai first; Higgsfield once the workflow is in weekly use.
- **Game data model** (`archive/GAME_DATA_MODEL.md`, identity v2): records are separate from claims, and project homes follow its layout, with YAML front matter. Where it and this spec disagree, it wins.
- **Bypass checkpoint:** before each launch of a bypassed session in a project home, resumes included, Exchange commits the home's changes. If that fails the session does not start unless the user chooses to start it without one.
- **Priorities:** the Daz library is the first asset-management priority; Unreal projects are the first project priority, with a fresh Sirenne-themed Unreal project as the benchmark.
