# Restart plan: from the real code to the first proof

Revised 2026-10-28 and approved by Luke the same day, with every recommended answer. Read [VISION.md](VISION.md) first. The first version of this plan was written against a local checkout 21 merged PRs behind GitHub and is replaced by this one.

## The goal

**First proof (VISION.md, decision 1):** Exchange notices a Daz character, Luke claims it "as a G8 character, in the Daz library", and the claim walks Acquired → Converted → Installed with no hand-holding, the Workspace showing each milestone and whose turn it is.

The second proof (the first path built with Hand to agent, plus the Exchange MCP) is a later plan.

## Where we start

Checked against GitHub on 2026-10-28.

- **Core (`cire992/3dExchange`, `main` at #28):** the library, curation and the desk; processes (renamed from pipelines in 6a) and the requisition engine; the Blender and Daz bridges; the local service with read, write and jobs APIs (6b, 6e, 6g); the PySide6 window; and a first slice of game data (`exchange.projects`, 7a and 7b). About 20,800 lines, 292 tests.
- **Shell (`cire992/Exchange-Shell`, `main` at #16):** the Chats window (phase 5), and the Workspace with library browsing, curation, the desk, environments, scanning and requisitions (6c-6i).
- **Not yet on `main`:** the software factory, on the `factory-install` branch (not pushed).

**Against the loop:** notice, things and walking a path are built in all three layers (core, API, Workspace). The missing pieces are the claim itself, finding a path by role and place, the G8 process, and the agent hand-off.

## How claims fit on the engine

A claim is a small layer over the requisition engine, which becomes plumbing:

```
claim file (intent)               ──►  path = processes found by role + place
<data>/claims/<date>-<slug>.md          │
                                        ▼
                                   requisition (one run of the path)  ──►  ledger entry in the place
```

- **The file holds intent:** the thing (dossier uid), *as* (a role), the place (environment and endpoint), notes, created and closed dates, and the requisitions run for it.
- **Progress is derived, not typed in:**
  - **Acquired:** the thing has a live entry on disk.
  - **Converted:** a requisition for the claim finished its steps.
  - **Installed:** the thing has a requisitioned entry in the place's ledger.
  - The file also records the last milestone it saw, so it reads correctly on its own, and after a lost database the ledgers rebuild it from sidecars.
- **Whose turn is derived too:**
  - No path found → *build the path* (later: Hand to agent).
  - Not acquired, or the run is at a checkpoint → *you*.
  - Queued or running → *Exchange*.
- **"As this" is a role.** Process manifests already declare `[output] roles`; the G8 process grants `g8f_character`. Finding a path means finding processes (or a chain) whose input matches the thing, whose output role matches *as*, and whose target matches the place.

## Pull requests

One branch and PR each, in the repository named. Each is checked against real data as before: a copy of the database, endpoints in scratch, nothing in a real environment written.

### Before R1: land what's open (done 2026-10-28)

3dExchange#28, Exchange-Shell#15 and #16 are merged, and the local core checkout is on `main`.

### R1: Docs reset (core, plus a pointer in the shell)

- `VISION.md` and this plan join the repository as the brief.
- **Archived, not deleted:** `IDENTITY.md`, `OVERVIEW.md` and `GAME_DATA_MODEL.md` move to `docs/archive/`, each with a line on top saying VISION.md replaces it. (`KICKOFF_PROMPT.md` stays out of git: the repository is public.) `DESIGN_SPEC.md` and `PROJECT_HOME.md` stay as reference for what's built.
- **`PROGRESS.md` around the loop:** phase 7 part 2 cancelled; the frozen slice named; the roadmap becomes 6j, claims, the G8 process, then the second proof.
- `PIPELINE_FILES.md` (renamed `PROCESS_FILES.md`, to match the code) and `docs/ideas/` committed.
- **Shell:** `EXCHANGE_PROGRESS.md`'s reading list points at `VISION.md` instead of the archived docs. Docs only.

### R2: 6j, parity and the PySide6 window removed (both, as already planned)

Luke signs off the parity checklist on the real library, then the window, its tests and the `ui` extra go. Done before claims, so nothing new is built twice.

### R3: Claims core (core)

- **The claim file:** Markdown with YAML frontmatter, the format project homes already use, through the existing `projects/frontmatter.py` (strict parse, line-level edits).
- **The index:** a migration with a `claim` table and `claim_requisition`, rebuilt from the files on start and when they change.
- **Path finding:** the planner's routes, filtered by role and by place.
- **Progress:** milestone and whose-turn derivation from ledgers and requisition states.
- **CLI:** `exchange claim add | list | show | walk | close`. `walk` plans and queues the path's requisition.
- **The frozen slice's claims move:** `exchange claims list/ack` become `exchange project claims list/ack`.
- **Tests and real data:** a claim on a real Daz product in a copy of the library, walked with the built-in *Convert mesh* process to a scratch endpoint.

### R4: Claims in the API (core)

Endpoints to create, list, read, walk and close claims, with milestones and whose turn; change notices when they move; `docs/api/openapi.json` updated as the contract.

### R5: Claims in the Workspace (shell)

- **Claim… on an item card** becomes the main action: pick *as* and the place, see the path, claim. 6i's requisition dialog survives as the path's options step.
- **A Claims view:** one row per claim with a segmented milestone gauge and a *whose turn* column; a *Waiting on you* filter; Resume and open-the-work-folder for checkpoints.
- **New since last scan:** a list after each scan, each item with a Claim button.
- **The inspector** shows a thing's claims. The requisitions view becomes *Runs*: secondary, for logs.

### R6: The G8 path, shape (core; can run beside R3-R5)

A process package, `daz_character_to_g8f` (granting role `g8f_character`):

1. **Daz:** load the source character on the Exchange G9 copy; write its shape as OBJ.
2. **Blender, headless:** Daz Generations, G9 → G8F mesh.
3. **Daz:** the verified recipe on the Exchange G8F copy: Morph Loader, adjust rigging, ERC Freeze, save the morph.
4. **Rewrite:** the `/data/Exchange/Genesis%208/Female/` paths to the regular G8F path.
5. **Install:** into the Exchange Conversions content directory (the endpoint).

Prerequisites declared as tools and files and listed in `PROCESS_FILES.md`. Real-data check: a real G9 character from the library, installed into a scratch content directory and loaded on the regular G8F.

### R7: The G8 path, skin, and the proof

- **Skin:** a Blender step bakes the skin maps with the Texture Converter G9 → G8F template. A Daz step saves a character preset: G8F with the morph dialed in and the baked maps applied.
- **The proof, end to end in the Workspace:** noticed → claimed → Acquired → Converted → Installed, with no manual step outside Exchange.
- **Docs:** `PROGRESS.md` records the measurements.

## Decisions (the recommended answers, approved)

1. **6j before claims?** *Recommended:* yes. The Workspace is at parity apart from the sign-off, and removing the PySide6 window first means claims are built once, in the Workspace.
2. **Claim file format.** *Recommended:* Markdown with YAML frontmatter in `<data>/claims/`, named `<date>-<slug>.md`, reusing the project homes' parser and its rule that Exchange edits only its own lines. The earlier plan said TOML before that code was known.
3. **Projects in this plan?** *Recommended:* no. A claim's place is an environment and endpoint. "A project is a named set of places" comes once there are claims to group, and may reuse the frozen project homes' registry (`<data>/projects.toml`).
4. **Things not yet owned (the Fab link)?** *Recommended:* not in this plan. Claims need a dossier for now; link-only things come with the next plan, alongside Hand to agent.
5. **Skin in the first proof?** *Recommended:* yes (R7). A G8 character without its skin isn't usable. Shape lands first in R6 so it can be checked on its own.
6. **Source figure.** *Recommended:* Genesis 9 only, which the Texture Converter and Daz Generations both cover. G8.1 and G2 sources become variants of the same path later. The Exchange G9 copy is finished (`People/Genesis 9/Genesis 9 Exchange.duf`, see `PROCESS_FILES.md`).
7. **Where Installed lands for Daz.** *Recommended:* the Exchange Conversions content directory, a new folder outside Luke's libraries. Exchange shows once how to add it to Daz's content directories and never changes Daz's settings itself.
8. **Does Exchange notice a *saved* character?** A character saved as a scene subset may not become its own dossier today. *Recommended:* R3's real-data check covers both an installed G9 character product and a saved scene subset; if the subset isn't identified, a scanning fix joins R3.
9. **The software factory.** It's installed (unpushed) in the core repository, and its UI reviewers are written for the PySide6 window, which R2 removes. *Recommended:* after R2, retarget the core factory's `ui` surface to the API contract and CLI output, and install the same factory in the shell repository for Workspace work. Use it from R3 on, starting with `concurrency` 1.
10. **Stacked PRs.** They went wrong three times (#11/#12, #26, Exchange-Shell#14). *Recommended:* turn on *Automatically delete head branches* in both repositories (Settings › General › Pull Requests), so GitHub retargets a stacked PR to `main` by itself, as #28 suggests.
