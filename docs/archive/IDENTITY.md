# Exchange: Identity

> **Archived 2026-10-28.** [VISION.md](../VISION.md) replaces this document as the brief. It is kept as reference for what was designed and built.

Version 2, 2026-10-24. This document changes only through amendments, recorded in the log at the bottom.

## Thesis

Exchange takes discrete ideas, assets and processes and harmonizes them into larger compositions: projects.

## Premise

A personal, AI-assisted mission control for building sprawling interactive 3D worlds, in Unreal Engine or by modding Bethesda games. It holds each project's identity, maps its growing structure, catalogs the assets you've collected, and dispatches work to agents and creative tools from one place.

## Audience

Luke. Generalizing for public release is welcome if it costs nothing, never a requirement.

## Pillars

Each pillar is also about relationships: Exchange's job is to connect things.

1. **Facilitate sprawl, keep it legible.** Exchange never asks you to make a world smaller, only to keep it navigable. Ideas are never orphaned: every claim belongs somewhere in the world's structure and links to what it touches.
2. **One interface, many hats.** Design decisions stay with you; dispatching, converting and wrangling software happen from the workspace. Work moves between agents, apps and you without losing its context or history.
3. **Scripts first, tokens second.** Deterministic automation is the default; agents fill gaps and turn their own work into scripts. Processes are reusable links between environments.
4. **Know what you own.** Every asset you've collected is found, profiled and matched to the claims that need it, understood by what it is and where it could go, not by the folder it sits in.
5. **Plain files, readable by agents.** Project knowledge lives in text files that you, git and any agent can read. Every relationship is written down where it can be followed.

## Feel

Mission control, built to be stared at all day: readable first, never drab.

- **Look:** a "used-future command deck." Dark panels, phosphor amber and teal readouts, segmented gauges, the warmth of 70s–80s sci-fi computer displays. An original look inspired by that era, not a copy of any film's UI. Color is reserved for meaning.
- **Assets as loot:** dossiers are item cards with a stats panel (polycount, texture resolution, environments they exist in or convert to). Products read as sets. Scans end with a "new acquisitions" report. Each dossier carries its acquisition date.

## Boundaries

- Not an editor. It drives Unreal Engine, Blender, Daz Studio, the Creation Kit and xEdit; it doesn't replace them.
- Not a team or cloud tool. Local and single-user, on Luke's machine.
- Not a model host. It uses Luke's CLI subscriptions and provider accounts.
- Not general-purpose software. It's tailored to Luke's toolchain first.

## Platform and toolchain

- **OS:** Windows only.
- **Core:** the Python `exchange` package (repository `cire992/3dExchange`).
- **Shell:** Tauri desktop shell with an HTML frontend, forked from Mr. Mak Workspace (Chats window and local service). The fork lives in its own repository.
- **CLI agents:** Claude Code, Codex, Kimi, PowerShell. Permission bypass is a per-session checkbox at launch.
- **Creative apps:** Daz Studio (primary character tool), Blender, Unreal Engine. Bethesda games through Mod Organizer 2.
- **Image generation:** Mr. Mak's concept-art skills. fal.ai (pay per generation) first; a Higgsfield subscription only once it's in weekly use.

## Domains

- Shell and Chats
- Project homes (identity, domains, records, claims)
- Asset database (dossiers, ledgers, curation)
- Processes (requisitions, bridges)
- Exchange MCP
- UI and design

## Goals

Finite milestones, each either done or not.

| # | Goal | Done when | Status |
|---|---|---|---|
| G1 | Library online | Daz library, UE projects, MO2 and loose files scan into dossiers; curation works | Done (repository phases 1–3) |
| G2 | First Process | Daz cross-figure (G9/G2 → G8) runs as a requisition | In progress (4d) |
| G3 | Chats online | The fork runs with tabs for Claude Code, Codex, Kimi and PowerShell, history restore, and the per-session bypass checkbox with a badge on the tab | Done (shell phase 5) |
| G4 | Service and Workspace | The core is served over a local API; the web Workspace browses the library | In progress (phase 6) |
| G5 | Project home | Identity, domain, record and claim files are created and rendered in the Workspace, with fast claim capture | Not started |
| G6 | Agents connected | Through the Exchange MCP, a claim is dispatched to a chat session and returns for review | Not started |
| G7 | Benchmark | A fresh Unreal project themed on Sirenne and the wider Star Wars setting is run from Exchange: its project home and identity exist, claims are dispatched to agents, and at least one Daz character arrives in the project through a Process | Not started |

## Pilot project

A fresh Unreal Engine project themed on Sirenne and Luke's wider Star Wars setting. If Exchange can run that, it can run anything.

## Vocabulary

- **Project:** a git-tracked project home, kept separate from the Unreal project and mod folders it builds.
- **Identity:** a project's premise, pillars, feel and boundaries. Changes only through amendments.
- **Domain:** a node in a project's growing structure: a district, faction, character, system or questline.
- **Record:** a typed unit of compiled game data (a character, faction, quest, lot, magic effect), named by a signature-prefixed editor ID. Records persist and carry a maturity level (sketch → spec → stub → built → polished), not a status. In a game project, the structure's domains are records.
- **Goal:** a finite milestone.
- **Claim:** a dated unit of work or idea, attached to a domain or record and optionally a goal. Status runs idea → open → claimed → review → done. Only Luke marks a claim done. An idea claim can be promoted into a new record and stays linked as its origin.
- **Dossier:** what an asset is. **Ledger:** where it lives.
- **Environment:** an ecosystem where assets exist (Daz library, Unreal project, MO2 instance, loose files).
- **Endpoint:** where Process output goes. A project target is a kind of endpoint.
- **Process:** a defined, repeatable operation, usually a conversion (formerly "pipeline"). **Requisition:** one queued run of a Process.

## Amendment log

- **2026-10-24 (v1):** Exchange broadens from a 3D asset manager into a personal, AI-assisted project workspace. Pipelines are renamed Processes. Endpoints are recontextualized as project targets. Plugin records and game data come into scope for project homes.
- **2026-10-24 (v2):** Records enter the vocabulary as compiled game data, distinct from claims: records carry maturity, claims carry status. Project homes and G5 now include record files. Detail lives in the game data model document.
