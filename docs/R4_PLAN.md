# R4: claims in the API

Approved by Luke on 2026-10-31, with every recommended answer. Part of [RESTART_PLAN.md](RESTART_PLAN.md); read [VISION.md](VISION.md) first. R3 gave claims a core and a CLI. R4 puts them behind the service, so that R5 can build the Workspace on them without another core change.

## The goal

After R4, everything the CLI does with a claim, a client can do through the API, plus the three things a window needs and a terminal doesn't: seeing the path *before* claiming, choosing a path's options, and being told when a claim moves.

The test of "done" is R5's list in `RESTART_PLAN.md`: Claim… on a card, a Claims view with milestones and whose turn, new since last scan, and a thing's claims in the inspector. Each needs a route here.

## What's already there

Checked on `main` (`59fac5e`).

| R5 needs | Already built | Missing |
|---|---|---|
| Claim… on a card | `claims.new`, `find_path` | A route, and a way to see the path before the file exists |
| The *as* picker | Process manifests' `roles` | `ProcessView` doesn't return them |
| The path's options step | `/requisitions/plan` and its forms; `plan_requisition` takes options | `claims.walk` takes no options, and `/requisitions/plan` doesn't know a claim's role or source |
| Walking | `claims.walk`, `/jobs/requisitions` | A route that does both |
| The Claims view | `claims.read_all`, `describe` | Routes and a typed shape; `path` is a raw dict today |
| Staying current | `/jobs` and `/changes` long-polling (`since`, `wait`) | The same for claims |
| New since last scan | `dossier.created_at`, `library_setting` | The filter and what "new" means |
| The inspector's claims | `describe` | A filter by thing |

## The API

All additive, under `/api/v1`, with the usual token. `docs/api/openapi.json` is regenerated with each chunk. Nothing is renamed or removed.

| Route | What it does |
|---|---|
| `POST /claims/preview` | Takes `{uid, environment, as, folder}`. Returns the path, the turn and `already_there`. Writes nothing |
| `POST /claims` | Makes the claim, with `note` too. Returns it |
| `GET /claims` | Open claims, and `problems` for files that can't be read. Filters: `all`, `turn`, `thing` |
| `GET /claims/{id}` | One claim, with its notes and its requisitions (id, state, message) |
| `POST /claims/{id}/close` | Closes it, with an optional `reason` |
| `POST /claims/{id}/plan` | The plan tree and option forms, in `/requisitions/plan`'s shape, for this claim's path. Writes nothing |
| `POST /claims/{id}/walk` | Takes `{options, preset, excluded, on_collision, run}`. Queues the path and, with `run` (the default), starts the job. Returns the claim, the requisition and the job |
| `GET /claims/changes` | `since` and `wait`, as `/jobs`. Returns a `version` that grows when any claim may have moved |
| `POST /dossiers/new/seen` | Marks everything new as seen |

Two additions to existing routes:

- `GET /dossiers?new=true`: things first seen since the marker (see decision 7).
- `ProcessView` gains `roles`.

### A claim's shape

Fixed, typed fields: `id`, `thing`, `thing_name`, `as`, `place`, `place_name`, `folder`, `milestone`, `created`, `closed`, `turn`, `turn_line`, `already_there`, and a typed `path` (`status`, `route`, `processes`, `process`, `problem`, `source_entry_id`). `notes` and `requisitions` come with `GET /claims/{id}` and the responses that return one claim.

A claim file is hand-editable, so a read must never turn a strange value into a 500. A key of the wrong type reads as null or as text, and a file that can't be parsed goes in `problems`. Your own extra keys stay in the file and aren't returned.

### Errors

404 for a claim, thing or place that doesn't exist. 400 for a folder that leaves the place. 409 for a refusal that depends on state: closed, already running, no path to walk, a job writing. 503 when the library is busy, as other writes do.

## How it's built

The factory builds it, from three issues filed one after the other, each a PR on `main`:

1. **R4a: claims you can read and make.** `preview`, `POST /claims`, `GET /claims`, `GET /claims/{id}`, `close`, the typed shape, `already_there`, `roles` on `ProcessView`, and safe claim writes (decision 2).
2. **R4b: walking.** `claims.walk` gains options, `plan`, `walk`, and `/claims/changes`.
3. **R4c: new since last scan.** The marker, `?new=true` and `/dossiers/new/seen`.

Then **R4d, by hand:** on the sample library, through a real `exchange serve` on a scratch database: claim a saved character and a mesh, preview, plan, walk with an option, follow `/claims/changes` to Installed, close. Measure `GET /claims` with a hundred claims, and write it up in `PROGRESS.md`. The factory's agents never touch real files, so this one is mine.

R4d also fixes R4b's two failures after queueing, by hand, as Luke decided on 2026-10-31. A claim file that can't be rewritten must not leave a queued requisition the claim doesn't know, so a retry can't queue a second one. A failed `remember` must not answer 500 or start no job once the requisition is queued and recorded, and `remember` must write through a temporary file, so a failed write can't wipe the last used options. It also lowers the new marker whenever dossiers are deleted, so forgetting an environment can't hide what the next scan finds.

`docs/PROGRESS.md` and the shell's `EXCHANGE_PROGRESS.md` note the contract change, the second as part of R5.

## Decisions (the recommended answers, approved)

1. **See the path before claiming?** *Recommended:* yes, with `POST /claims/preview`. R5's dialog is "pick *as* and the place, see the path, claim". Without a preview, trying a place would leave a file behind each time. It shares `find_path` and the turn logic with real claims, so it can't disagree with them.

2. **Reading a claim writes its file.** `_read` saves the derived milestone, so in the service a `GET` writes, on several threads at once. A slow race could cost a hand edit, and a reader could catch a half-written file. *Recommended:* keep the behaviour, so the file stays true for agents who read it directly, and make writes safe: one lock around `update`, and writing through a temporary file and `os.replace`. A failed write already becomes a problem line, not a failure. This changes the CLI's writes too, for the better.

3. **Does `walk` also run?** *Recommended:* yes by default (`run: false` to only queue). A queued requisition with nothing running reads as Exchange's turn forever, and a client that dies between two calls would leave exactly that. The Workspace's button means "go".

4. **Options when walking.** The dialog remembers each process's last options, but `claims.walk` uses manifest defaults. *Recommended:* the API walk takes options as `/requisitions/queue` does: request, over preset, over last used, and remembered when queued. `claim walk` in the CLI stays as it is: nobody has asked for options there.

5. **"It's already there."** With no role and no folder, a claim for a place that holds the thing reads `ready` by copy, and walking writes a duplicate. R3D_PLAN left this for R4 and R5. Protected tests pin that path, and changing it would change what a claim *means*. *Recommended:* add `already_there: true` to the claim and the preview, and change nothing else. R5 shows it in the dialog and on the row, and you can still walk. If it reads wrong in use, the milestone rule can follow later, by hand.

6. **Change notices.** *Recommended:* one `version`, long-polled as `/jobs` is. It grows on an API write, when any job ends (scans and runs move milestones), and when a file in the claims folder changes (through the existing `watchdog`), so CLI, agent and hand edits show up too. It says "something may have moved", not what: the client lists again. Without `watchdog`, the first two still work.

7. **What counts as new?** The roadmap says "new since last scan", but every walk rescans its output folder, so a literal last scan would empty the list after each walk. *Recommended:* new means first seen since a marker you move yourself ("Mark all seen"), kept in `library_setting`, needing no migration. It starts at the end of the first scan, so the first library isn't all new. Entries Exchange wrote itself don't count. A new environment added later does flood the list once; "Mark all seen" clears it.

8. **Which edits belong in the API?** *Recommended:* only make and close. Changing a claim's role, place or notes, reopening and deleting all stay with the file, as in R3: it's plain text, and Exchange reads it back. They can be added when the Workspace needs them.

9. **An index table?** R3's decision 1 said to add one if R4's list got slow. Today it's 6 ms a claim on the sample library. *Recommended:* no index. R4d measures it on a hundred claims; the real library's database is much larger, so that number decides.

10. **`claim show`'s raw `path`.** R3D_PLAN said R4 gives it a real shape. *Recommended:* the API does; the CLI's text stays, because a protected test pins it, and `--json` was already fine.

## Not in this

- The Workspace (R5). The shell regenerates its types there.
- The G8 process (R6). Until then no built-in process grants a role, so `roles` is empty and a claim *as* a role reads `build`.
- Hand to agent and a claim's "build the path" button (the second proof).
- Things not owned yet, and claims from a link (VISION's Fab case).
- `exchange claim` CLI changes, beyond safer writes.
- Relinking claims after a rebuilt database.
