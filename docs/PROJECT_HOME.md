# Project home formats

The reference for the files in a project home, as `exchange.projects` reads and validates them
(Roadmap phase 7). The design is in `GAME_DATA_MODEL.md` and the spec's *Projects* section; this
document is the exact format.

## Layout

```
<project home>/
  exchange.project.toml         marks the folder as a project home
  IDENTITY.md                   premise, pillars, feel, boundaries, amendment log
  goals.md                      the goals, in the front matter
  coverage-rules.yaml           per-type expectations (format only so far)
  schemas/<SIG>.yaml            project-exclusive record types
  records/<SIG>/<EDITOR_ID>.md  one file per record
  claims/<date>-<slug>.md       one file per claim, flat
  .gitignore                    holds .exchange/
  .exchange/                    caches (never committed)
```

`exchange project init PATH [--name NAME] [--kind unreal|bethesda]` creates this in a new or empty
folder, runs `git init` and makes the first commit.

Markdown files start with YAML front matter between `---` lines; the rest is the body. A key
repeated in one mapping is an error. Exchange creates files but never rewrites one a person wrote.

## exchange.project.toml

```toml
name = "NJO"
kind = "unreal"        # or "bethesda"
targets = []           # the Unreal project or mod folders it builds (later phases)
created = "2026-10-24"
format = 1
```

## IDENTITY.md

Prose with these `##` sections: Premise, Pillars, Feel, Boundaries, Amendment log. A missing
section is a warning.

## goals.md

```markdown
---
goals:
  - { id: G1, title: Docks playable, status: active, done_when: "The docks can be walked and talked to" }
---
Notes.
```

`id` is `G` and a number, unique. `status` is planned, active, done or dropped.

## Records

`records/NPC_/NPC_DockMaster.md`:

```markdown
---
id: NPC_DockMaster
maturity: 1
race: RACE_Human
look: { dossier: 3f2a…, process: daz-g9-to-g8-to-ue }
factions:
  - { faction: FACT_PortAuthority, rank: Harbormaster }
schedule:
  - { hours: 06-18, location: LOT_LowerDocks_Office, package: PACK_Work }
---
Prose profile.
```

- **Editor ID:** a signature, then a name of letters, digits and `_`:
  `^([A-Z]{3}_|[A-Z]{4}_)[A-Za-z0-9][A-Za-z0-9_]*$`. A signature ending in `_` (`NPC_`, `LOT_`)
  uses that underscore as the separator. IDs are unique ignoring case. The file is named by the ID
  and sits in its signature's folder.
- **Maturity:** 0 Sketch, 1 Spec, 2 Stub, 3 Built, 4 Polished, stored as the number.
- **Common fields:** `id`, `maturity`, `name` (display name), `origin` (the claim the record was
  promoted from), `tags` (a list of text).
- **A signature without a schema** (`PACK`, `CELL`, `DIST` …) may have records: their `id` and
  maturity are checked, and links to them resolve when the file exists.

### Core schemas

| Signature | Fields | Required |
| --- | --- | --- |
| `NPC_` | `race` → RACE; `look` {`dossier`, `process`}; `factions` [{`faction` → FACT, `rank`}]; `kin` [{`npc` → NPC_, `relation`: parent, child, spouse, sibling}]; `schedule` [{`hours` HH-HH, `location` → LOT_/CELL, `package` → PACK}] | `race` from Spec, `look` from Stub |
| `RACE` | `kind`: humanoid, droid, creature, audio_only; `playable` | `kind` from Spec |
| `FACT` | `template` (family, house, clan, tribe, company, guild, team, nation, gang, clique, club, culture); `parent` → FACT; `relations` [{`faction`, `relation`: ally, friend, neutral, enemy, `reaction`}]; by template: `lineage`, `head`, `heir` (lineages), `ranks`, `joining`, `holdings` (companies, guilds, teams), `territory`, `government` (nations), `turf` (gangs, cliques, clubs), `leader`, `customs`, `language` (cultures) | `template` from Spec |
| `LOT_` | `within` → DIST/NBHD/ZPOI/CITY/ZONE; `owner` → FACT/NPC_; `unreal_level` | `within` from Spec |

Fields inside list entries that are marked required (`factions[].faction`, `schedule[].hours` and
`location`, …) are required whenever the entry exists. The schemas are in
`src/exchange/projects/schemas/`.

### Schema format

`schemas/PACK.yaml` in a project home adds a signature (it cannot change the core's):

```yaml
signature: PACK
title: AI package
fields:
  kind: { type: enum, values: [work, sleep, patrol, socialize, guard], required_at: spec }
  location: { type: link, to: [LOT_, CELL], max_demand: stub }
  steps:
    type: list
    of: { type: object, fields: { at: { type: text, pattern: '^\d{2}:\d{2}$' }, do: { type: text } } }
```

| Key | Meaning |
| --- | --- |
| `type` | `text`, `int`, `number`, `bool`, `date`, `enum`, `link`, `dossier`, `process`, `claim`, `list`, `object` |
| `to` | a link's signatures |
| `values` | an enum's values |
| `of` | a list's item field |
| `fields` | an object's fields |
| `required_at` | the maturity from which the field must be filled (a number or level name) |
| `max_demand` | the most maturity a link can require of its target (default Spec) |
| `pattern` | a regular expression text must match |
| `templates` | with the schema's `template_field`, the templates the field belongs to |
| `description` | for people |

## Claims

`claims/2026-10-24-spec-salt-row-cantina.md`:

```markdown
---
id: 2026-10-24-spec-salt-row-cantina
status: open
created: 2026-10-24
target: LOT_SaltRowCantina
goal: G1
source: gap
needed_by: [NPC_DockMaster]
triage: new
---
The dockmaster's evening schedule points here, but the cantina is still a Sketch.
```

| Field | Meaning |
| --- | --- |
| `id` | the file name's stem: the date and a slug of lowercase words |
| `status` | idea, open, claimed, review, done (the user only), dropped (the user only) |
| `created` | the date; it should match the file name |
| `target` | the record's editor ID; it may not exist yet. Without one (or a `domain`) the claim is unfiled |
| `goal` | a goal in `goals.md` |
| `source` | manual (the default), gap, ladder, coverage, mining |
| `needed_by` | the records waiting on this one (an ID or a list) |
| `claimed_by` | `luke` or a session ID, when claimed |
| `triage` | `new` until acknowledged, then `seen` |
| `title`, `links`, `needs`, `domain`, `gap` | an optional title; references (editor IDs, or `claim:`, `goal:`, `dossier:`, `process:`, `decision:`, `session:`, `domain:`); needs, each with a `kind`; the domain, for projects with domains that are not records; details of a gap claim |

## coverage-rules.yaml

```yaml
version: 1
rules:
  - id: district-has-vendor
    for: DIST
    says: Every District has a vendor.
    expect: {}      # reserved for the check language
```

Only the format is checked so far: `id` (lowercase words joined by `-`, unique), `for` (a
signature), `says` (the rule in words) and `expect` (a mapping).

## Validation

`exchange project validate [--project P] [--db LIBRARY] [--json]` exits with 1 when there are
errors.

- **Errors:** the file breaks its format, or a record claims a maturity its fields do not meet.
- **Warnings:** unknown fields, links that cannot be checked (a signature without a schema, an
  unknown process, no library database), a link written in a different case, a merged dossier,
  unfiled claims.
- **Gaps:**
  - **missing or immature:** a record at Spec or above needs each record it links to at no less
    than the lower of its own maturity and the field's `max_demand`. A missing target counts when
    its signature has a schema. Links from Sketch records are not checked.
  - **dossier:** a dossier link whose uid is not in the library, or has only retired entries. Links
    are resolved read-only and follow merges. Checked at every maturity.

Gaps become gap claims (Roadmap phase 7b).

## Choosing a project

Commands use `--project` (a path, or a name under the projects root), else the project home
holding the current folder, else the default. `exchange project config` sets them in
`<data>/projects.toml`:

```toml
root = "E:/Projects/Exchange"
default = "NJO"
git_name = "Luke"
git_email = "luke@example.com"
```

`git_name` and `git_email` are the identity project homes commit with when git has none of its own.
`project init` writes them into the new repository's configuration.

## Checkpoints

`exchange project checkpoint [--project P | --for PATH] [--reason TEXT] [--json]` commits every
change in the project home, except `.exchange/`, as `Checkpoint: <reason>`. It never makes an empty
commit. It refuses a home that is not the top level of its own git repository. With `--for`, a
path outside any project home prints `"project": null` and succeeds, so the shell can ask before
every bypassed session.
