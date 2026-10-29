# 6j: the parity checklist

R2 of the restart ([RESTART_PLAN.md](RESTART_PLAN.md)). Prepared 2026-10-28 from the PySide6 window's code (`src/exchange_ui/`, core `main` at #29) and the Workspace's (`src/exchange/library/` in the shell, `main` at #17). Luke approved the plan with every recommended answer on 2026-10-28; the checklist below waits for his sign-off on the real library.

## The plan

1. **R2a: close the gaps** below that are marked *fix*: mostly in the shell, plus a small core change (each file in a dossier's detail carries its file ref, for gap 3).
2. **R2b (Luke): the sign-off.** Use the Workspace on the real library and tick each line below. Anything that fails becomes a fix in R2a, or an accepted gap with a reason.
3. **R2c (core, then shell docs): remove the PySide6 window.** `src/exchange_ui/`, `tests/ui/`, the `ui` extra, PySide6 and pytest-qt in `dev`, the `exchange-app` script, the window's sections of the README and PROGRESS. This checklist is ticked there, as the record. The shell's handoff doc says the window is gone.

The CLI stays: anything the window did that the Workspace doesn't can still be done there.

## Gaps: in the window, not in the Workspace

Found by comparing every menu, button, tab, shortcut and drop target in the window with the Workspace's code.

| # | In the window | Recommended | Why |
|---|---|---|---|
| 1 | **Show in folder** on a card | *Fix* | You open assets' folders to work on them in Daz or Blender. The API already returns each file's absolute path. |
| 2 | **Open in app** on a card | *Fix* | Same reason; it opens the asset's main file with its Windows app. |
| 3 | Dropping cards on a card: **Link their files to "…"** (e.g. textures onto a mesh) | *Fix* | The other drop actions (put into product, merge, fold in as a variant) are there; this one is missing. `link-files` takes files by root and key, which details now give. |
| 4 | **Ctrl+F** focuses the search; **F5** rescans | *Fix* | Small. Ctrl+Z and Ctrl+Y are already in. |
| 5 | Dropping **files from Explorer** onto a card links them | *Accept* | The desk's *Link these files to an asset…* does the same for scanned files, which is all the window allowed. |
| 6 | Dropping **a folder** on the add-environment wizard | *Accept* | The wizard has Browse… and the list of what was found on this PC. |
| 7 | **Requisition to…** button in the inspector | *Accept* | It's on the card's menu. In R5, *Claim…* becomes the main action anyway. |

Not gaps:
- The window's *Copy to…* and *Extract* were disabled placeholders.
- "Show candidates" and sorting beyond name and type are missing from both, so they're spec features, not parity.
- The Workspace doesn't notice edits made in the window or the CLI until Refresh. Once the window is gone, only the CLI remains.

## The checklist

Tick each line after doing it in the Workspace on the real library. Don't edit in the window and the Workspace at the same time: they keep separate undo stacks.

### Environments and scanning
- [x] Add environment: the found-on-this-PC list, Browse…, detection with confidence, choosing an MO2 profile, ignore rules
- [x] A scan runs with progress; it continues after closing the wizard; *Review Unidentified* at the end
- [x] Changes detected on an environment, then *Rescan changed*; Stop a running scan
- [x] An environment's settings: ignore rules, MO2 profile, endpoint and visibility

### Browsing
- [x] The sidebar: all assets, collections, environments with their types, Unidentified with its count
- [x] Item cards with thumbnails scroll smoothly through the whole library
- [x] Search with filters (`env:`, `tag:`, `type:`, `-tag:`), and saving a search as a smart collection
- [x] Selection: click, Ctrl+click, Shift+click, Ctrl+A; the keyboard moves through the cards

### The inspector
- [x] Overview: type, tags with where each came from, variants, ledgers with their entries, origin and license
- [x] The Files, Dependencies and History tabs
- [x] Editing name, type, tags and notes; the revert marker (↺) on edited fields
- [x] Bulk edit with several selected: add and remove a tag, *Keep each* value

### Curation
- [x] Card menu: Rename, Add to collection, New collection, Remove from collection
- [x] Put into a new product, Take out of the product
- [x] Merge the others into one, Split…, Make a variant its own asset
- [x] Not an asset, and Count as an asset again
- [x] Drop cards on a product (put into), on a card (merge, fold in as a variant), on a collection in the sidebar
- [x] Undo and Redo, with Ctrl+Z and Ctrl+Y, across several kinds of edit
- [x] Delete a collection

### The Unidentified desk
- [x] Low confidence: retype, tag or dismiss
- [x] Unattached files by folder: expand to count, make a product from a folder, link files to an asset, mark *Not assets*, ignore a folder
- [x] Suggestions: select all shown, accept or reject in batches, Show more

### Lexicons
- [x] Add and remove words, then *Apply to library* in the background

### Requisitions
- [x] *Requisition to…* from a card: the plan, per-process options, presets (save, choose), options last used, the collision policy
- [x] Add to queue, and Add and run
- [x] The queue: run it, hold and release, move up and down, the log of each item
- [x] Resume after a checkpoint or a collision (overwrite, rename, skip)
- [x] Rebuild, Remove output, Check for stale
- [x] Settings › Processes: install a package, trust it, set a tool's path, the prerequisites' state
- [x] Settings › Endpoints: change where each environment's output goes

### After R2a (the gaps marked *fix*)
- [x] Show in folder
- [x] Open in app
- [x] Drop cards on a card: Link their files
- [x] Ctrl+F and F5

### Sign-off
- [x] Every line above works on the real library, or is listed here as an accepted gap with a reason. Signed off by Luke on 2026-10-29.

## Decisions (the recommended answers, approved)

1. **The four fixes before removal?** *Recommended:* yes, in one shell PR (R2a). They're small, and Show in folder and Open in app are part of how you work with Daz and Blender.
2. **The three accepted gaps?** *Recommended:* accept them as listed. Each has another way in the Workspace or is replaced by R5.
3. **When to sign off?** *Recommended:* after R2a merges, in one sitting on the real library, so the ticked list covers the fixes too.
4. **What else goes with the window?** *Recommended:* only the window: `exchange_ui`, its tests, the `ui` extra, PySide6 and pytest-qt, and `exchange-app`. `watchdog` stays, since the service uses it for change notices.
5. **The factory branch.** Its reviewers and `AGENTS.md` describe the PySide6 window. *Recommended:* retarget them in the same core PR as the removal (R2c), so the factory lands describing the code as it will be.
