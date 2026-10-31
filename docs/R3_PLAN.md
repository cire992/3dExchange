# R3: the claims core

Approved by Luke on 2026-10-29, with every recommended answer. Part of [RESTART_PLAN.md](RESTART_PLAN.md); read [VISION.md](VISION.md) first. R3 is the core alone, with a CLI; the API (R4) and the Workspace (R5) come after.

## The goal

A claim is "this thing, as this, in that place" (VISION.md). After R3, Luke can make one from the CLI, see the path Exchange found and whose turn it is, walk it (plan and queue the requisition), and watch it move from Claimed to Installed.

## What's already there

Checked on `main` (`e122e66`).

| Need | Already built | Missing |
|---|---|---|
| A file format Exchange can write and Luke can edit | `projects/frontmatter.py`: strict YAML front matter, and `set_keys`, which edits only the keys Exchange owns | Nothing |
| A place for Exchange's own files | `paths.data_dir()` (with `EXCHANGE_DATA_DIR` for tests) | A `claims/` folder in it |
| Finding a path to a place | `requisitions/plan.py`: `routes()` finds ready chains (up to three processes) from a dossier's entries to an environment, or a copy | Filtering by role; telling "no process at all" from "a process that isn't set up" |
| Roles | Process manifests have `[output] roles` | No built-in process declares one yet (R6's G8 process grants `g8f_character`) |
| Walking the path | `plan_requisition` and `queue_plan`; requisitions have a `uid` | Linking a requisition to its claim |
| Seeing how far it got | Requisition and item states; requisitioned ledger entries carry `requisition_id` (from sidecars, so they survive a lost database) | Deriving a milestone and whose turn from them |

## The design

### The claim file

`<data>/claims/<date>-<slug>.md`, one per claim:

```markdown
---
id: 2026-10-29-dwarf-helmet
thing: 7f3c…                 # dossier uid
thing_name: Dwarf Helmet     # a hint, for reading and for relinking after a rebuilt database
as: null                     # a role, or null for any path to the place
place: env-9a1…              # environment uid
place_name: Starfield
folder: null                 # endpoint folder, or null for the place's default endpoint
requisitions: []             # uids of the requisitions walked for it, newest last
milestone: claimed           # the last one Exchange saw
created: 2026-10-29
closed: null
---
Luke's notes, free text.
```

Luke can edit the notes and any key. Exchange changes only `requisitions`, `milestone` and `closed`, through `set_keys`, and refuses an edit that would change anything else.

### Milestones, derived

| Milestone | When |
|---|---|
| Claimed | The file exists. |
| Acquired | The thing has a live (not retired) entry on disk. Every claim starts here in R3, since things are always scanned dossiers. |
| Converted | A run of the claim's latest requisition finished its item (`done`). |
| Installed | The place's ledger holds a requisitioned entry of the thing from one of the claim's requisitions. |
| In play | Never derived: Luke's step, recorded by closing the claim. |

Today the runner converts and writes in one go, so Converted and Installed arrive together; they come apart when paths have manual steps. For a product, the milestone is that of its least advanced included item.

### Whose turn, derived

| State | Turn | What it says |
|---|---|---|
| Closed | none | |
| The thing has no live entry | you | The source files are gone: rescan or relink |
| No process at all can reach the place (as this role) | build the path | Later: Hand to agent |
| A process could, but isn't ready | you | Set up *process*: trust it, or fix *prerequisite* |
| Ready, not walked yet | you | Walk it |
| Queued or running | Exchange | |
| Needs attention | you | The requisition's message |
| Failed | you | The failure; later: Hand to agent |
| Installed | you | Close it, or take it into play |

### The CLI

```
exchange claim add <dossier uid> --env <id> [--as <role>] [--folder <f>] [--note <text>]
exchange claim list [--all] [--turn you|exchange|build]
exchange claim show <id>        the path, the milestone, whose turn, the requisitions
exchange claim walk <id> [--run]   plan and queue the path's requisition (--run: run the queue now)
exchange claim close <id> [--reason <text>]
```

`--json` on each, and `--env` as the requisition commands take it. `exchange claims list/ack` (the frozen project homes' gap claims) move to `exchange project claims list/ack`.

## How it's built

The factory builds it, from two issues filed one after the other (the second needs the first on `main`):

1. **R3a: claim files and the CLI's bookkeeping.** The file format, reading and writing through `frontmatter.py`, `claim add | list | show | close`, and the milestones Claimed and Acquired.
2. **R3b: paths, walking and progress.** Path finding by role and place (with "not set up" told apart from "no process"), whose turn, `claim walk`, and the milestones Converted and Installed from requisitions and the ledger.

The move of `exchange claims` under `exchange project claims` is done by hand, in its own small PR, because it changes a protected test (`tests/test_gap_claims.py`), which the factory's builders can't touch.

Then **R3c, by hand:** a claim on a real Daz product in a copy of the library, walked with *Convert mesh* to a scratch endpoint, measured, and written up in `PROGRESS.md`. The factory's agents never touch the real library, so this one is mine.

## Decisions (the recommended answers, approved)

1. **An index table in the database?** *Recommended:* not in R3. Claims are few (tens, maybe hundreds), so reading the folder each time is cheap and leaves one source of truth; project homes made the same call in phase 7. Add an index if R4's list gets slow.
2. **Is `as` required?** *Recommended:* optional. With a role, the chain's last process must grant it; without one, any path to the place counts. No built-in process grants a role yet, so R3's real-data check walks a claim without one.
3. **Identity after a rebuilt database.** Dossier and environment uids don't survive one. *Recommended:* store `thing_name` and `place_name` as hints now, and leave relinking for later, as project homes do with their dossier hints.
4. **Claims on products?** *Recommended:* yes. The requisition plans the children, and the claim's milestone is the least advanced included item's.
5. **Converted and Installed together.** *Recommended:* accept it in R3, as above; the derivation already keeps them separate for when paths have manual steps.
6. **What `walk` does.** *Recommended:* plan and queue, like `exchange requisition plan … --queue`; `--run` also runs the queue now. Walking an already-walked claim plans a new requisition and appends it (a rebuild after a failure).
7. **Closing.** *Recommended:* one `close` with an optional reason, for both "in play" and "dropped". The milestone stays as it was, so the file records how far it got.
8. **The old `exchange claims` command.** *Recommended:* remove it, no alias: Luke is the only user, and the frozen slice gets no new work.
9. **The factory.** *Recommended:* file R3a now; file R3b once R3a is merged; concurrency as configured (one issue at a time anyway). Both issues quote this plan's design, so the spec writer builds from it.
