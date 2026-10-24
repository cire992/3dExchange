# Exchange: Game Data Model

Draft, 2026-10-24. Developed from "Brainstorming claim types for Unreal project." Settled points are listed under Decisions; everything else is a proposal. Vocabulary changes go through the identity document's amendment log.

## Starting point

The pilot project is a Bethesda-style game built in Unreal. Its world is made of typed records that reference each other: NPCs belong to factions, quests point at NPCs and cells, spells are built from magic effects. Exchange should let Luke think in that record logic, author records from the workspace, and compile them into Unreal.

**Bethesda logic is the thinking model, not the implementation.** Unreal isn't forced to behave like the Creation Engine. Where Unreal does something similar its own way, or better, its way wins:

| Creation Engine idea | Unreal approach |
|---|---|
| BodySlide / Outfit Studio | Mutable (analogous, not the same) |
| Magic effects, spells, enchantments | Gameplay Ability System |
| Keywords | Gameplay Tags |
| AI packages | StateTree or Behavior Trees (proposed) |
| Modular kits snapped by hand | PCG-driven Tilesets |
| Interior cells | Separately streamed levels |
| Exterior worldspaces | World Partition maps, with Level Instances for Lots |

## Decisions

- **2026-10-24: Records and claims are separate.** Records are compiled game data. Claims are work and ideas. Recorded as identity amendment v2.
- **2026-10-24: Editor IDs use Bethesda signatures,** or signature-style codes for project-exclusive record types. The first-pass project-exclusive codes are accepted.
- **2026-10-24: Unreal-native over Creation Engine imitation,** per the table above.
- **2026-10-24: Space is in scope.** Orbital Zones are flyable sandboxes, as in Starfield, Star Wars Galaxies and The Old Republic. Travel between destinations goes through the galaxy map.
- **2026-10-24: Characters are the first record family to prototype (G5).** Routing Daz characters into projects is half the reason Exchange exists.
- **2026-10-24: Cities and wilderness Zones are World Partition maps; Districts are regions within City maps.**
- **2026-10-24: Orbital Zones are galaxy map destinations,** the space counterpart of wilderness Zones.
- **2026-10-24: Gap claims open directly,** and the triage inbox alerts Luke to each one. Other derived claims wait in the inbox as proposals.
- **2026-10-24: Coverage rules live in one file per project.**
- **2026-10-24: The galaxy map is shared.** GMAP, SYST, PLNT and HLAN records own the data (what exists, map coordinates, connections, travel time, unlock and discovery conditions) and compile into Unreal. The in-game galaxy map reads that data; Unreal owns the presentation (art, camera, zoom levels, transitions).
- **2026-10-24: One file per claim,** named by date and slug, with status in the frontmatter. Status changes never move files.
- **2026-10-24: Record schemas live in the Exchange core,** one per signature. Project-exclusive types are defined in the project home's schemas folder.
- **2026-10-24: Dossier IDs must survive rescans.** Records link to assets by dossier ID; this is a requirement to verify before Character Look depends on it. Checked for phase 7: they survive rescans and files that come back, but not moves, renames, automatic duplicate merges or a rebuilt database. Phase 7 keeps a hint per linked dossier and opens a relink claim when one breaks; the scanner-side fixes come before Character Look is used for real (`PROGRESS.md`, *Phase 7*).

## Records and claims

- **Record:** a persistent, typed unit of compiled game data: a Lot, a Faction, a Quest, a Magic Effect. It has a signature, fields, links and a maturity level. In a game project, records are the domains of its structure.
- **Claim:** dated work or an idea against a record. "Block out the Lower Docks." "Give the dockmaster a schedule." "What if the House secretly funds the gang?" Status lives on the claim; maturity lives on the record.
- **Promotion:** an idea claim can be promoted into a new record ("a smuggler's den under the docks" becomes a Lot). The claim stays linked as the record's origin, so nothing is orphaned.

## Progressive formalization

The Dialogue Scene Tool idea (write plain text, then layer data on until it becomes a real scene) generalizes to every record type. Every record starts as prose and accretes structure. One maturity ladder, shared by all types:

| Level | Name | Meaning |
|---|---|---|
| 0 | Sketch | A name and a paragraph of prose. |
| 1 | Spec | Structured fields filled; links to other records resolve. |
| 2 | Stub | Exists in Unreal as a placeholder: graybox, temp mesh, TTS voice. |
| 3 | Built | Final content in engine, functional. |
| 4 | Polished | Reviewed, tuned, signed off by Luke. |

Fast capture creates Level 0 records or idea claims. Maturity shows everywhere as segmented gauges (fits the Feel), so a district can read as 80% specced and 10% built at a glance.

## Claim derivation

Most claims shouldn't have to be typed. Records already say what's missing; Exchange reads that and proposes claims. Four sources:

1. **Ladder.** A record at level N proposes one claim for its next level: a Sketch character proposes "Spec NPC_DockMaster." Only the next step, never the whole ladder at once.
2. **Gaps.** Validation finds a link to a record that doesn't exist or isn't mature enough for what needs it, and opens a claim on that record, linked to the one that needs it. "NPC_DockMaster's schedule points at LOT_SaltRowCantina, still a Sketch → Spec the cantina." Gap claims carry the reason, so the cantina knows who's waiting on it.
3. **Coverage rules.** Per-type expectations written as plain rules in a single coverage rules file in the project home: every District has a vendor; every Faction with ranks has a way to join; every Companion has a personal quest; every Door has two sides. Each broken rule proposes a claim.
4. **Mining.** An agent reads prose bodies and dialogue scripts and flags names, places and items that have no record yet, as idea claims: "Who is 'the Baron' in the dockmaster's profile?" Accepting one promotes it into a Sketch record.

Sources 1 to 3 are deterministic scripts; only mining needs an agent (scripts first). Gap claims open directly, and the triage inbox alerts Luke to each one. Ladder, coverage and mining claims land in the inbox as proposals, marked with their source, where Luke accepts, merges or dismisses them. Dismissals are remembered so the same claim isn't proposed again.

## File shape

One Markdown file per record: YAML frontmatter for fields and links, prose body for everything human-facing. Editor IDs are `SIGNATURE_Name`, so the prefix doubles as the record type. Links are by editor ID, so any agent can follow them with a text search.

```markdown
---
id: NPC_DockMaster
maturity: 1
race: RACE_Human
look: { dossier: <dossier id>, process: daz-g9-to-g8-to-ue }
factions:
  - { faction: FACT_PortAuthority, rank: Harbormaster }
schedule:
  - { hours: 06-18, location: LOT_LowerDocks_Office, package: PACK_Work }
  - { hours: 18-24, location: LOT_SaltRowCantina, package: PACK_Socialize }
---
Prose profile: history, personality, what they want.
```

Claims use the same shape. The filename stem is the claim's ID:

```markdown
---
id: 2026-10-24-spec-salt-row-cantina
status: open
created: 2026-10-24
target: LOT_SaltRowCantina
goal: G5
source: gap
needed_by: NPC_DockMaster
---
The dockmaster's evening schedule points here, but the cantina is still a Sketch.
```

`source` is one of manual, gap, ladder, coverage or mining. `goal` and `needed_by` are optional.

### Signatures

Bethesda signatures where a Creation Engine record fits; project-exclusive codes in the same four-character style otherwise. Signatures for supporting record types are listed with them further down.

| Family | Bethesda | Project-exclusive |
|---|---|---|
| Spatial | CELL (interior cell), DOOR | GMAP galaxy map, REGI region, SYST system, PLNT planet, PPOI planetside POI, CITY, DIST district, NBHD neighborhood, ZONE, ZPOI zone POI, ORBT orbital zone, OPOI orbital POI, LOT_, CHMB chamber, OUTL outlet profile, TILE tileset |
| Factions | FACT | |
| Characters | NPC_, RACE, CLAS, RELA | |
| Quests | QUST | QCHN quest chain, MBRD mission board |
| Dialogue | DIAL, INFO | SCNE scene |
| RPG | SKIL, BSGN, SPEL, ENCH, MGEF, PERK | ATTR attribute, RULE ruleset |
| Items | WEAP, ARMO, ALCH, MISC, KEYM, BOOK, LVLI, CONT | |
| Globals | GLOB, GMST | |

## Project home layout

Confirmed for phase 7 (2026-10-24), with the design spec's marker file and `.exchange/` folder added.

```
<project home>/
  exchange.project.toml  marks the folder: name, kind, targets, created
  IDENTITY.md            premise, pillars, feel, boundaries, amendment log
  goals.md               goals G1… in the frontmatter
  coverage-rules.yaml    one file per project
  schemas/               project-exclusive record types
  records/
    NPC_/NPC_DockMaster.md
    FACT/FACT_PortAuthority.md
    LOT_/LOT_SaltRowCantina.md
  claims/
    2026-10-24-spec-salt-row-cantina.md
  .exchange/             caches (gitignored)
```

- Records are grouped in one folder per signature, so a signature's records can be listed without parsing every file.
- Claims sit in one flat folder; status lives in the frontmatter, so changing status never moves a file or churns git history.
- Domains that aren't records, if a project has any, follow the design spec.
- A signature ending in `_` (`NPC_`, `LOT_`) uses that underscore as the separator: `NPC_DockMaster`, not `NPC__DockMaster`.

## Core record families

### Spatial

```
Galaxy Map → Region → System → Planet
   ├─ Planetside POI: a City or a Zone
   │     ├─ City → District → Neighborhood → Lot
   │     └─ Zone → Zone POI → Lot
   └─ Orbital Zone → Orbital POI
Lot → Door → Interior Cell → Chamber → Chamber Outlet
Orbital POI → Door (docking port, airlock) → Interior Cell
```

- **Galaxy Map chain** (Galaxy Map → Region → System → Planet) is an overworld navigation layer, like Mass Effect's galaxy map. The player picks destinations rather than walking it. Destinations are Cities, Zones and Orbital Zones. The records are shared with the in-game map (see Decisions).
- **Orbital Zone** is a flyable sandbox, the space counterpart of a wilderness Zone, picked from the galaxy map. Orbital POIs live in it: over Sirenne, Silnion Station and Goto's yacht.
- **Lot** is where both planetside branches converge; **Door** is where exterior meets interior, the same role as Bethesda's linked door references. A Door record names both sides, and validation flags doors with one side. Docking ports and airlocks play the Door role for orbital POIs, so the interior chain is shared.
- **Outlet Profile** as its own type: opening size, floor height, style family. Tileset pieces and bespoke chambers both declare which profiles they expose, so compatibility is checked instead of remembered.
- **Tileset** as a project record type, because it drives PCG generation in Unreal:
  - **Pieces:** the kit's modules (corridors, junctions, rooms, caps), each linked to the dossier or mesh it uses and tagged with the outlet profiles it exposes.
  - **Rules:** the parameters a PCG graph reads: adjacency, weights, density, style variants, size limits.
  - **Generator:** the Unreal PCG graph the tileset feeds.
  - **Bespoke anchors:** an Interior Cell can mix generated sections with bespoke Chambers. The Chambers are placed at outlets, and the generator fills between them, so shared outlet profiles are what make the seams line up.
  - **Maturity:** Stub means the generator produces a graybox from placeholder pieces. Built means the final meshes are swapped in under the same rules.
- **Unreal mapping:**
  - **City, Zone = World Partition map.**
  - **District = region within a City map.**
  - **Orbital Zone = its own map,** like a Zone.
  - **Lot = Level Instance.**
  - **Neighborhood and Zone POI = arrangements of Lots.** A Zone POI might be a town or a dungeon.
  - **Interior Cell = separately streamed level.**

### Factions

- **One Faction type with a template field**, rather than twelve types. The template sets default fields:
  - Family / House / Clan / Tribe: lineage, head, heir
  - Company / Guild / Team: ranks, joining requirements, holdings
  - Nation: territory (links spatial records), government
  - Gang / Clique / Club: turf, leader
  - Culture: customs, language, links to lore
- **Membership Chart as a typed graph.** Edges:
  - *member-of* (with rank or role)
  - *contains* (nesting: a House contains Clans)
  - *relation* (ally / friend / neutral / enemy, with a reaction value, like Bethesda faction relations)
  - *kinship* (parent, spouse, sibling): a family tree is a Family faction with kinship edges
- Edges are stored on the member's record; charts are rendered views over them, so every relationship is written down in exactly one place.

### Characters

First family to prototype. The brainstorm's sections map closely onto Bethesda's NPC record:

| Section | Bethesda analogue | Notes |
|---|---|---|
| Type and Race | RACE | Race is its own record: humanoid races, droid, creature, audio-only. |
| Character Look | face/body data | Links a Daz dossier and the Process that brings it in. G7 lives here. |
| Character Profile | — | Lore prose in the record body. |
| Gameplay Info | CLAS, stats, spells | Points into RPG ruleset records. |
| Faction Associations | faction list with ranks | Edges, see Factions. |
| Associations / Affinity | RELA (Skyrim) | Per-pair relationship and disposition. |
| Location, Schedule | AI packages | Schedule rows reference Lots, Cells and PACK records. |
| Dialogue, Quests | quest aliases, dialogue | Mostly computed back-links. |

On the Unreal side, Mutable is the likely home for body and outfit variation, filling the role BodySlide and Outfit Studio play for Bethesda games.

Character Look is the strongest bridge between the two halves of Exchange. A claim like "find a look for the dockmaster" is answered by searching dossiers; "bring it in" is a requisition.

### Quests

- **Quest Chain:** a graph with edge types *prerequisite*, *unlocks*, *branches-to*, *excludes* (mutually exclusive outcomes).
- **Quest:** stages, plus two Bethesda features worth adopting:
  - **Objectives:** what the player sees, separate from stages (internal flags).
  - **Aliases:** named roles filled by a specific reference or by conditions ("the client," "a cave in this region"). Aliases make quests reusable and make radiant quests possible.
- **Radiant Quest:** a quest whose aliases are all filled by conditions at runtime.
- **Mission Board:** its own record: which radiant pool it draws from, which faction it serves, where it stands.

### Dialogue

The Scene Tool as a dialogue-specific maturity ladder:

1. **Script:** plain screenplay text.
2. **Parsed:** lines become nodes with speaker, line, player choices, branch targets.
3. **Logic:** conditions and consequences: quest stage checks and sets, faction reputation, skill checks, affinity.
4. **Audio:** temp TTS per voice type, later recorded VO.
5. **Staging:** shot presets, emotion and gesture tags, lip sync.
6. **In engine:** a playable scene.

The KotOR benchmark is reachable because its scenes rely on a small set of camera presets, talking animations and lip sync. Staging can be defaulted by preset and overridden per line, so the text stays primary. Ink and Yarn Spinner are worth a look for plain-text syntax ideas; a parser script turns the text into data.

### RPG engine

- **Two layers.** The **Ruleset** is one holistic document: formulas, curves, how attributes feed skills, damage and leveling. The **parametrized records** are Skill, Attribute, Class, Birthsign, Ability/Spell, Modifier/Enchantment, Effect/Magic Effect.
- **Composition carries over.** Magic Effects are atoms; Spells and Enchantments bundle effects with magnitude, duration and area. In Unreal this is the Gameplay Ability System's job (effects, abilities, attribute sets, gameplay tags), which the brainstorm's naming already points toward.
- **Interview → Ruleset.** An agent-led interview produces the Ruleset. Records reference named formulas rather than embedding math.
- **Simulator.** A small Python sim runs the Ruleset (level curves, time-to-kill, economy) so balance is checked by numbers. Agents propose changes; the sim judges them.
- **Birthsign** generalizes to a starting choice that grants modifiers: birthsign, background or homeworld.

## Supporting record types

Smaller types the core families lean on. Each row lists the claims it typically generates, which is what makes it worth being a record rather than a field.

### Population and behavior

| Record | Sig | What it holds | Typical claims |
|---|---|---|---|
| Archetype | ARCH | Template for generic NPCs ("Imperial officer," "dock worker"): race pool, outfit pool, class, voice pool. Named characters can inherit from one. | Define archetypes a District's crowd needs |
| Leveled NPC list | LVLN | Weighted pools of archetypes by level or region | Fill spawn pools for a Zone |
| Crowd Profile | CRWD | Ambient population of a District or Zone POI: density by hour, archetype mix, faction mix | Populate a District; tune night density |
| AI Package | PACK | Reusable behaviors (work, sleep, patrol, socialize, guard) that schedules reference | Author a package a schedule asks for |
| Combat Style | CSTY | How an NPC fights: range preference, aggression, ability use | Give a faction's soldiers a style |
| Voice Type | VTYP | A voice shared by many NPCs: temp TTS voice, later a cast actor | Cast a voice; generate temp lines |
| Outfit | OTFT | Mutable outfit configuration, linked to apparel dossiers | Dress an archetype; convert apparel from Daz |
| Companion | COMP | Approval triggers, banter, personal quest, romance flags (KotOR influence, Mass Effect loyalty) | Write banter; build the personal quest |

### Space

| Record | Sig | What it holds | Typical claims |
|---|---|---|---|
| Ship | SHIP | Hull, class, module slots, crew slots, exterior look (dossier), interior (Interior Cell) | Spec a hull; block out its interior |
| Ship Module | SMOD | Weapons, shields, engines, hyperdrive; effects in GAS terms | Balance modules against the Ruleset |
| Hyperlane | HLAN | Galaxy map links between systems: travel time, danger, requirements | Connect a new System to the map |
| Traffic | TRFC | What flies through an Orbital Zone: patrols, freighters, pirates, by faction and time | Populate orbit over Sirenne |

### World rules

| Record | Sig | What it holds | Typical claims |
|---|---|---|---|
| Law Profile | LAWS | What counts as a crime where, bounty values, who enforces, where you're jailed. Imperial space and Hutt space differ. | Assign laws to a Planet or District |
| Condition | CNDT | Named, reusable condition sets shared by dialogue, quests, packages and vendors | Extract a repeated check into a Condition |
| Keyword | KYWD | Tags compiled to Gameplay Tags | Register tags a system needs |
| World Event | EVNT | A change to the world triggered by a quest or time: a District changes hands, a station is destroyed | Define what changes after a quest's ending |

### Economy and interaction

| Record | Sig | What it holds | Typical claims |
|---|---|---|---|
| Vendor | VEND | Stock lists, faction pricing, restock rules, location | Give a District its vendors |
| Recipe | COBJ | Crafting and upgrade recipes | Add upgrade paths for a weapon line |
| Furniture / Activator | FURN, ACTI | Usable objects: beds, workbenches, chairs, switches | Dress a Lot with interactables |
| Terminal | TERM | Computer interfaces with pages, logs and actions | Write a station's terminal logs |

### Narrative and ambience

| Record | Sig | What it holds | Typical claims |
|---|---|---|---|
| Codex Entry | CDEX | Player-facing lore unlocked by discovery, Mass Effect style | Write the codex entry for a new Faction |
| Rumor | RUMR | Tavern talk pointing at quests and POIs, Morrowind's "latest rumors" | Seed rumors for a new quest |
| Book / Datapad | BOOK | Readable in-world texts | Write the datapads in a derelict |
| Weather, Music, Lighting | WTHR, MUSC, LGTM | Ambience per Region, Planet or Zone | Give a Planet its weather set |

## Authoring views

Different views over the same record files. The five core views:

- **Tree:** spatial hierarchy
- **Graph:** faction charts, quest chains, dialogue branches
- **Table:** an xEdit-style record browser: every record of a signature, its maturity, links and open claims
- **Card:** a single record; frontmatter fields as a form, prose below, plus a **Referenced by** panel (xEdit-style) showing everything that links here and what breaks if it changes
- **Interview:** agent-led sessions for holistic work (the Ruleset, a new Culture)

Specialized views built on them:

**World**
- **Galaxy Map:** author the overworld on a map that looks like the in-game one. Destinations show maturity gauges; hyperlanes draw between systems. Because the in-game map reads the same records, this view doubles as a rough preview of what the player will see.
- **District Board:** a top-down view of a City map with Lots as tiles colored by maturity, using captures read back from Unreal.
- **Coverage Map:** maturity rolled up the spatial tree, so hollow Districts and empty Zones stand out.

**People**
- **Casting Board:** characters and archetypes without Looks on one side, candidate Daz dossiers on the other. Assigning a dossier queues the requisition. This is the asset database and the game data in one view.
- **Schedule Timeline:** 24-hour lanes. By location: who is in the cantina at each hour. By character: where they go all day. Catches empty taverns, double-booked NPCs and Lots nobody visits.
- **Relationship Matrices:** faction × faction reactions; companion approval of each faction and key NPC.

**Story**
- **Quest Flow Board:** the chain graph above, the selected quest's stages as a timeline below, each stage showing what it sets and checks. A dry run steps through stages and reports dead ends: unreachable stages, flags checked but never set, aliases nothing can fill.
- **Topic Matrix:** characters × dialogue topics, Morrowind style. Shows who can talk about what; empty cells that should be filled become claims.
- **Table Read:** play a scene with temp TTS voices straight from the script layer, before any staging exists.
- **Codex Reader:** read the lore as a player would, styled like the in-game codex. A continuity pass in reading form.
- **World Timeline:** history and World Events on one axis, so quest outcomes and lore dates can't contradict each other.

**Systems**
- **Ruleset Workbench:** formulas beside live simulator charts (level curve, time-to-kill, prices).
- **Kit Board:** a Tileset's pieces, an outlet-profile compatibility grid, and generator previews.
- **Economy Table:** items, values, vendors and leveled-list odds side by side.

**Production**
- **Triage Inbox:** alerts for newly opened gap claims, plus proposed ladder, coverage and mining claims waiting to be accepted, merged or dismissed, grouped by source.

For the Characters prototype, the useful subset is Card (with Referenced by), Table, Casting Board and Schedule Timeline.

## Getting records into Unreal

- **Compile Process.** Scripts read record files and write Unreal assets (Data Assets and DataTables via Unreal's Python editor scripting). Deterministic and re-runnable.
- **Source of truth splits by kind.** The project home owns definitions (factions, quests, dialogue, ruleset, galaxy map data). Unreal owns geometry, placement and presentation. Spatial records point at their Unreal level, and a read-back script updates maturity from what actually exists in the project.
- **Validation pass,** like xEdit's error check: broken links, unfilled aliases, one-sided doors, outlets with no matching profile, dialogue conditions pointing at missing stages, unreachable systems on the galaxy map. Its findings open gap claims.

## Open questions

None open right now.
