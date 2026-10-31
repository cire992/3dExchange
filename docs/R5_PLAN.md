# R5: claims in the Workspace

Approved by Luke on 2026-10-31, with every recommended answer. Part of [RESTART_PLAN.md](RESTART_PLAN.md); read [VISION.md](VISION.md) first. R4 put claims behind the service. R5 puts them in the window, so the loop can be run without a terminal.

## The goal

After R5, in the Workspace alone: see what's new, claim it, see the path, walk it, watch the milestones move, and always know whose turn it is.

The test of "done" is one sitting on the sample library, through the real core: a new mesh goes from the New list to Installed, and a saved character claimed `as g8f_character` says a process has to be built. No terminal.

```
 New ──Claim…──► Claim dialog ──Walk──► Claims ──► milestone gauge fills
 (or any card)   as, place, path        (options    whose turn, what to do next
                                         if asked)  Inspector: this thing's claims
```

## What's already there

Checked on `main` in both repositories (core `0f12414`, shell `8a3c7ee`).

| R5 needs | Already built | Missing |
|---|---|---|
| Claim… | The card menu, `dialogs`, `POST /claims/preview`, `POST /claims`, `ProcessView.roles` | The dialog |
| The path's options | `RequisitionDialog`'s plan table and option forms, `POST /claims/{id}/plan`, `POST /claims/{id}/walk` | Those parts out of the dialog, so a walk can use them |
| The Claims view | `Queue`'s list-and-detail layout, `GET /claims`, `GET /claims/{id}`, `POST .../close`, `library-state` chips | The page and the gauge |
| Staying current | `Jobs` already follows `/jobs` and `/changes`; `GET /claims/changes` | The same loop for claims |
| Checkpoints | `POST /requisitions/{id}/resume`, `hold`, the shell's `/reveal` | **The work folder's path: the API doesn't give it.** The one core gap (decision 11) |
| New | `Browser`, `Pages`, `GET /dossiers?new=true`, `POST /dossiers/new/seen` | A view and a Claim button on its cards |
| The inspector | Tabs in `Inspector.tsx`, `GET /claims?thing=` | A Claims section |
| Runs | The Requisitions page | The name, and its place in the sidebar |

The shell's `api.gen.ts` is from before R3, so the first chunk regenerates it. The fake core (`desktop/service/exchange/test/fake-core.mjs`) needs the claims routes for the UI tests.

## How it's built

One PR per chunk, on `main`, in order. The shell has CI; the core's checks are local.

1. **R5a (core, small): the work folder.** `RequisitionDetail` gains `work_folder`, and `PROGRESS.md`'s R4d row reads merged.
2. **R5b: seeing claims.** Regenerated types, `fake-claims.mjs`, `/claims/changes` followed in `Jobs`, the Claims page with the gauge, whose turn and *Waiting on you*, its detail pane with notes, requisitions and Close, and the sidebar item.
3. **R5c: making claims.** The Claim dialog on the card menu and in the inspector, for one thing or several, and the inspector's Claims section.
4. **R5d: walking.** The plan table and forms split out of `RequisitionDialog`, Walk and Walk with options…, then what each turn asks: Release, Resume, Set up a process, Show the work folder. Requisitions becomes Runs.
5. **R5e: New.** The New view, the Claim button on its cards, Mark all seen, and the line after a scan.
6. **R5f, by hand: the whole loop.** The real UI on the real core, on the sample library with scratch data, driven by Playwright with screenshots, so the app you're using isn't restarted. Then you try it in the app when you choose to restart it. Written up in both repositories' progress docs.

Each chunk adds a `*-ui.mjs` test against the fake core, as `requisitions-ui.mjs` does.

## Decisions (the recommended answers, approved)

1. **Who builds it?** RESTART_PLAN's decision 9 said to install the factory in the shell. *Recommended:* change that: build R5 here by hand, one PR per chunk. Installing means a chunk of its own plus reviewers rewritten for a real UI, and after R5 most of the work (R6, R7) is back in the core. This is also the part that needs eyes on it: R4a spent 10 rounds and $18.73 on wording alone. The shell's CI still checks every PR.

2. **Does Requisition to… stay?** *Recommended:* yes, as the second item, under Claim…. A one-off conversion with no claim is still useful, and R5 removes nothing.

3. **Several cards selected?** *Recommended:* Claim… takes them all: one *as* and one place, a table with each thing's path and whose turn, and one button. They become separate claims, each walked on its own. Claiming a pack of twenty one at a time is the kind of friction Exchange exists to remove.

4. **The *as* picker.** No built-in process grants a role until R6, so a plain list would be empty. *Recommended:* a text box suggesting the roles processes grant, blank for no role. A role nobody grants reads "No path yet", which is true, and tells you what to build.

5. **What does Walk do?** *Recommended:* it runs at once with the options last used, and **Walk with options…** opens the step. That follows VISION's "less to think about", and a process's options rarely change. The first time a process is walked its defaults apply, and the claim's result says what happened. On a collision the walk stops and asks, as now.

6. **Claim, then walk?** *Recommended:* the dialog's main button is **Claim and walk** when the path is ready, with **Claim** beside it. When it isn't ready, Claim is the only button, and the dialog says what's missing.

7. **"It's already there."** *Recommended:* the dialog says "This place already holds it: walking writes a second copy", and the main button becomes Claim, so a second copy is never the easy choice. The row shows the same. Walking stays possible, as R4 decided.

8. **In play on the gauge.** The API has four milestones; VISION has five, and In play is your step. *Recommended:* five segments, with In play always hollow and labelled as yours. No new state: it costs nothing now and says where Exchange's reach ends. It can light up when game data returns.

9. **The sidebar.** *Recommended:* **Claims** and **New** go first, above All assets, because they're the loop. Claims counts what's waiting on you, in amber. New counts what's new. **Runs** moves down beside Settings. The Workspace still opens on All assets for now.

10. **New: a page, or a view?** *Recommended:* an ordinary card view, so search, selection and the menu all work, with a Claim button on each card and Mark all seen in the heading. After a scan the status line says "12 new · Show them". VISION's "new acquisitions report" can grow from that later; a popup after every scan would be one more thing to dismiss.

11. **The work folder.** A paused step's files are in `<data>/work/<uid>/`, and no route says so. *Recommended:* R5a adds `work_folder` to `RequisitionDetail`, null once it's gone. It's additive and about three lines. The alternative, dropping the button until R6, would mean coming back to this screen for it.

12. **Editing a claim.** R4 left role, place and notes to the file. *Recommended:* the detail pane shows them read-only, with no button for now. Close takes an optional reason. Reopening stays by hand.

## Not in this

- Hand to agent and a "build the path" button (the second proof). `build` rows say what's missing and offer nothing yet.
- The G8 process (R6). The Workspace will show its roles with no change.
- Things not owned yet, claims from a link, projects, and a real In play.
- Renaming *Requisition to…* or changing what a requisition is. Only the page's name changes.
- The 500s R4a's approver found. A claim file that can't be read shows in the page's problems line.
- Restarting your app. R5f uses its own browser and core; you restart when you choose.
