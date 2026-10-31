# Exchange: Vision

2026-10-28, revised the same day. This is the restart document. When it disagrees with DESIGN_SPEC.md, PROJECT_HOME.md or the archived IDENTITY.md, OVERVIEW.md and GAME_DATA_MODEL.md (in `docs/archive/`), this wins: those are reference material to salvage from, not the plan.

**Revision note.** The first version was checked against a local checkout 21 merged PRs behind GitHub (#15-#27). The real `main` and the shell repository already have the processes rename, the local service, a Workspace window at near parity with the PySide6 one, the Chats window, and a first slice of game data. The loop, the concepts, the milestones and the scope are unchanged. *Where the code stands* and decisions 2, 3 and 5 were revised, and Luke approved the revisions the same day.

## Why Exchange exists

A workspace for building whatever Luke feels like building, in Unreal or by modding Bethesda games. It expands creative options by removing friction and cognitive load: the repetitive, error-prone work that slows a modder or solo developer to a crawl is automated, so attention stays on the ideas.

The core of that is **asset conversion**. Luke owns assets in many places (a Daz library, MO2 mods, Fab packs, Unreal projects), and moving one from where it is to where it is wanted is the biggest drag. Exchange makes that as automatic and simple as possible.

## The one loop

```
Exchange notices it ─┐
                     ├─► a thing ─► a claim ─► path known? ─ yes ─► walk the path ─► landed
Tag it (later) ──────┘                              │                  ▲   │
                                                    no                 │   └─► waiting on you
                                                    └─► build the path ┘        (buy it, decide,
                                                        (saved for reuse)        touch it up)
```

**Every asset Exchange notices can become a claim. A claim is a thing headed for a place. Exchange finds or builds the path there, and shows whose turn it is.**

Every feature has to serve a step of this loop, or it waits.

## Five concepts

| Concept | Meaning | In the code today |
|---|---|---|
| **Thing** | An asset: what it is, where it lives, whether Luke owns it. A thing can be known before it is owned (a Fab pack claimed from its link). | Dossier, with ledgers for where it lives. "Not owned yet" is new. |
| **Place** | Where things live and land: the Daz library, Skyrim or Starfield through MO2, an Unreal project. A **project** (Arkwynn Academy) is just a named set of places plus the claims aimed at them. | Environment, with its endpoint |
| **Claim** | Intent, in one shape: *this thing, as this, in that place.* Ray gun → weapon → Starfield. Claims stay open as long as they need to; nothing is lost. | New. (The project homes' "gap claims" are a different, frozen thing; see decision 5.) |
| **Path** | The full route a claim takes: one or more **processes** (automated chains) plus Luke's own steps (buy it, approve it, touch up the weights). | Process (one automated chain), with chains and manual checkpoints in the requisition engine |
| **Milestone** | How far a claim has walked into its place (below). | Ledger entries record "Installed" |

Running a path is plumbing under the claim; Luke works with claims, not runs. (Code name: requisition.)

## How far a claim walks

Every claim moves through the same milestones, whatever the asset or place:

1. **Claimed:** thing, form and place are named.
2. **Acquired:** the source files are on disk: bought, downloaded or saved.
3. **Converted:** rebuilt in the place's format: a G8 morph, a NIF with DDS textures, an FBX.
4. **Installed:** in the place, in its own container: a new MO2 mod, a Daz content folder, an Unreal content folder.
5. **In play:** wired into the game: a weapon record, an NPC wearing the outfit.

Each path declares the last milestone it reaches, and paths reach further over time. **Today Exchange's reach ends at Installed.** In play is game data, so it is Luke's step for now; that is also where game data can return later, as milestone 5 rather than a separate system.

## Who does each step

Steps run on the cheapest executor that works: a **script** (headless Blender, DazScript, command-line tools), then a **live bridge** to an open app, then an **agent**, then **Luke**. When no path exists, building it is the work: an agent drafts the process with Luke, it is tested, and it is saved, so the next claim of that kind is automatic. Tokens are spent once.

Agents run in the shell's **Chats window**, which already exists (Claude Code, Codex, Kimi and PowerShell tabs, history, the per-chat bypass and its checkpoint). It gets no new features for now. Two small pieces connect it to the loop:

- **Hand to agent:** a button on a claim or a failed step. Exchange writes a brief (the claim, the thing, the place, the failing log, the process files) and opens a chat with it. This covers building a new path and repairing a broken one.
- **Exchange MCP:** a small tool server the agent uses to read the claim and the thing, and to save a finished process back. Exchange records which chat did the work.

## The cases it must handle

- **Nexus follower:** Luke downloads it; Exchange notices it in MO2. Claim: the follower's look, as a G8 character, in Daz. No path yet, so one is built. Walks to Installed.
- **Retro-Future Ray Guns Pack:** noticed on install in Daz. Claim: one gun, as a weapon, in Starfield. Walks to Installed as a new MO2 mod; the weapon record is Luke's step.
- **Luke's own Daz character:** noticed when saved as a scene subset. Claim: the outfit, as clothing, in Arkwynn Academy. Walks to Installed in the project's content folder.
- **Fab animation pack:** claimed from its link. Sits at Claimed, waiting on Luke to buy it.

## Principles

1. **Less to think about.** Exchange shows the next step and whose turn it is. Luke never has to keep the state of a conversion in mind.
2. **Scripts first, tokens second.** Agents fill gaps and turn their work into processes.
3. **Read-only until asked.** Watching and scanning never change a place. Output goes into new containers, never into Luke's existing mods or folders unless chosen, and every write is recorded.
4. **Luke's work is never lost.** Hand edits to things survive rescans; open claims stay open.
5. **Plain files, readable by agents.** Processes, claims and settings are text an agent can read and write.

## Feel

Mission control, built to be stared at all day: a used-future command deck, dark panels, amber and teal readouts, color reserved for meaning. Things are loot: item cards with stats, products read as sets, and each scan ends with a "new acquisitions" report.

## Out for now

- **Game data:** records, compiling, domains, idea claims with no asset, the maturity ladder. The first slice that exists (project homes, record schemas, validation, gap claims, fast capture) is frozen, not extended (decision 5). Returns, if ever, as milestone 5.
- **Project management:** goals, devlogs, drift review, identity interviews, mission control. A project is only a named set of places.
- **New work on the Chats window:** it stays as it is. Only Hand to agent connects to it.
- **Browser tagging:** the most intuitive way in, and the north star for the "notice" step, but not near-term.

## Boundaries

- Not an editor: it drives Daz Studio, Blender, Unreal and the Creation Kit; it doesn't replace them.
- Local, single-user, Windows, on Luke's machine and accounts.

## Where the code stands

Checked 2026-10-28 against GitHub: core `main` at #27, shell `main` at #13, with 6i merged on its way to `main`.

| Loop step | Built | Missing |
|---|---|---|
| Exchange notices it | Scans, rescans, the watcher; the jobs API (6g); environments and scanning in the Workspace (6h) | A "new since last scan" list to claim from |
| A thing | Dossiers, ledgers, curation, the desk, lexicons: in the core, the API (6b, 6e) and the Workspace (6d, 6f) | "Not owned yet" things |
| A claim | Nothing for assets | Everything |
| Path known? / walk the path | Processes (renamed in 6a), the requisition engine and its API (6g, part 2), requisitions in the Workspace (6i), the Blender and Daz bridges, the verified Daz morph recipe | Finding a path by role and place; the G8 process (4d) |
| Build the path | The Chats window | Hand to agent, the Exchange MCP |
| Landed | Requisitioned ledger entries, sidecars | Nothing |

**Off the loop and frozen:** `exchange.projects` (about 1,900 lines: project home formats, record schemas, validation, gap claims, `exchange capture`, `exchange project claims`) and the shell's checkpoint before bypassed chats (7c). They keep their tests and keep working; nothing new is built on them.

## Decisions

Approved by Luke, 2026-10-28. Decisions 2, 3 and 5 were revised the same day against the real code, and approved again.

1. **First proof.** *Decided:* done when Exchange notices a Daz character, Luke claims it "as a G8 character, in the Daz library", and the claim walks Acquired → Converted → Installed with no hand-holding, the window showing each milestone and whose turn it is. The existing morph recipe and Daz bridge nearly cover it. The second proof is the first path built with Hand to agent (the Nexus follower or the ray gun).
2. **The UI.** *Decided (revised):* the shell's Workspace carries the loop. It already has the library, curation, the desk, scanning and requisitions (6i, reaching the shell's `main` with Exchange-Shell#16), with the service API behind it; only the 6j parity sign-off is left. The PySide6 window gets no new features and is removed at parity (6j), as already planned. *(Was: PySide6 carries the loop and the Tauri shell is dropped, decided when the shell looked unstarted.)*
3. **Fresh codebase or prune.** *Decided (revised):* neither. The code is sound and mostly on the loop, so keep it. Freeze what's off the loop (decision 5) rather than deleting it, and spend the effort on the missing pieces: claims and the G8 process. *(Was: a hard prune on a branch, decided when game data looked unbuilt.)*
4. **Where claims live.** *Decided:* one small text file per claim, indexed by the library database, as processes already are. Claims are Luke's intent, so they must survive a lost database and stay readable by agents without the MCP.
5. **The frozen game-data slice.** *Decided:* `exchange.projects` and 7c stay as they are, with their tests, and get no new work. The one change: its `exchange claims` commands move under `exchange project claims`, so "claim" means the loop's claim everywhere else. *(Vocabulary follows the code: "process" for one automated chain, since the rename already landed; "path" for a claim's whole route.)*
