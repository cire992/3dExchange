# Exchange: Overview

> **Archived 2026-10-28.** [VISION.md](../VISION.md) replaces this document as the brief. It is kept as reference for what was designed and built.

2026-10-24. The forest view: what Exchange is for and how its parts connect. Read this first. The identity document holds the commitments; the game data model holds the record and claim design.

## In one sentence

Exchange holds the game's design as **records**, tracks the work as **claims**, matches records to the **assets** you own, and delivers both into Unreal, with agents doing much of the work.

## The chain

```
                 Bethesda-style game (the Unreal project)
                      ▲                          ▲
          Compile Process                   Requisitions
      (records → Unreal data)       (assets converted into Unreal)
                      ▲                          ▲
             Project home  ◄──────────►   Asset database
   (records, claims, authoring views)   (dossiers, ledgers, Processes)
                      ▲                          ▲
             Luke and agents                Environments
        (Chats, Exchange MCP)       (Daz, UE projects, MO2, loose files)
```

Read it bottom-up:

1. **Luke and agents** work in the **project home**. Authoring views create and edit records (the game's data); claims track the work on them, many derived automatically.
2. **Environments** feed the **asset database**: scans find assets, dossiers say what they are, ledgers say where they live.
3. **The middle link.** Records attach to assets: a character's Look links to a Daz dossier. Claims are the jobs of finding and bringing those assets in. The Casting Board is where this handoff happens.
4. **Two delivery routes** into the game: the compile Process writes records into Unreal data, and requisitions run Processes that convert assets into the Unreal project.
5. **The game** is the point of all of it.

## How the goals map onto the chain

The design was worked out top-down from the asset side; the goals build bottom-up, which is the right build order.

| Goal | Builds |
|---|---|
| G1 Library online | Asset database, Environments |
| G2 First Process | Processes and requisitions |
| G3 Chats online | Luke and agents (the Chats window) |
| G4 Service and Workspace | The workspace the views live in |
| G5 Project home | Records, claims, authoring views (Characters first) |
| G6 Agents connected | Agents working claims through the Exchange MCP |
| G7 Benchmark | The whole chain at once: a Daz character arrives in the Sirenne project |

## Scope note

The pilot is the Unreal game, but Exchange is also meant to run Bethesda mod projects. The same chain applies, with a mod folder as the endpoint instead of an Unreal project.
