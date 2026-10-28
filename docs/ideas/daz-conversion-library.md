# Idea: a minimal Daz conversion library for fast figure loads

Status: the target side is adopted, using the user's renamed G8F copy (see "Adopted" below). The source side is not started. Raised 2026-10-22 during the phase 4d spike.

## Problem

Loading Genesis 8 Female in the Exchange Daz instance takes about 90 s, because Daz loads every morph installed for the figure. It scans `data/DAZ 3D/Genesis 8/Female/Morphs/**` in every content directory, and the real library has thousands. Every Daz job in a conversion pays this cost: export, build, verify.

## Concept

Run conversion jobs against a figure that has no extra morphs, and copy in only the morphs a conversion needs.

### Rejected variant: a renamed copy of the figure

Copy the figure to a path of Exchange's own (e.g. `data/Exchange/Genesis 8/Female/...`), so that Daz finds no morphs for it.

- Every morph file names its figure by URL (`/data/DAZ 3D/Genesis 8/Female/Genesis8Female.dsf#...`), and its formulas name other morphs by path.
- Copied morphs would need those URLs rewritten, and the output morph would need rewriting back to the real figure.
- A mistake there gives a morph that silently fails to load.

### Proposed variant: same paths, a separate content library

- **The conversion library:** a folder in Exchange's data folder holding the base figure files at their original relative paths. That's `Genesis8Female.dsf`, its UV sets, and the Dev Load `.duf`, with no `Morphs/`.
- **Per job:** Exchange copies the character's morphs into it, plus their dependency closure (morphs they depend on, correctives, ERC drivers), at their original paths. Enrichment already records Daz dependencies.
- **The instance's content directories:** for the job, they're just the conversion library and the output folder (`Exchange Conversions`), not the user's libraries.
- **Output:** saved morphs already name the real figure by its real path, so they work in the user's library unchanged. Nothing is rewritten.
- **Applies to every figure:** the same approach serves the source figure (G9 export) and the target (G8F build).

## Effects on earlier decisions

- **Phase 4, item 4 (instance settings):** only the update setting (`AutoUpdate`) would still be copied from the main instance. Content directories would be set per job.
- **Read-only:** files are only read from the user's library. The copies stay local in Exchange's data folder and are never distributed.

## Checked in the spike (2026-10-22)

- **What the Dev Load needs:** 6 files, 2.5 MB:
  - `Genesis8Female.dsf`
  - `UV Sets/DAZ 3D/Base/Base Female.dsf`
  - the three `PHMEyelashes*` morphs
  - the Dev Load `.duf`

  No textures were needed for a shape job, and the output was identical to a full-library export.
- **Load time:** 14.8 s for the whole job once the add-on cache matches the bare library, against about 110 s with the full library.
- **Blocker: Daz's add-on cache is shared by all instances.**
  - **Where it lives:** `%APPDATA%\DAZ 3D\dson\cache\data\DAZ 3D\Genesis 8\Female.cache.dsf` (924 MB for the real library). It is keyed by the figure's data path.
  - **What goes wrong:** a job with a different content list rewrites it ("Cache update required, 17479 unused files"). The user's next normal G8F load then rebuilds it, which takes about 5 minutes.
  - **Not a fix:** a separate `APPDATA` for the Daz process doesn't isolate it, because Daz asks Windows for the folder directly.
  - **What the spike did:** it clobbered the cache twice and rebuilt it both times.
- **So the "same paths" variant needs a way to isolate the cache first.** Ideas, none tested:
  - a Daz preference or command-line option for the cache location
  - running the Exchange Daz under its own Windows account
  - the "renamed copy" variant after all: its cache key is a different path, so it never touches the user's cache. That's at the cost of the URL rewriting above.

## Adopted: the user's renamed copy (2026-10-22)

The user added `People/Genesis 8 Female/Genesis 8 Basic Female Exchange.duf`. It's a renamed copy of G8F at `data/Exchange/Genesis 8/Female/`, its own product under the vendor name "Exchange", with no morphs.

- **Same figure:** the same 171 node ids, geometry and 16,556 vertices as the regular G8F. Only the path prefix differs, including its own copy of the base UV set.
- **Fast:** the figure loads in 0.3 s. The whole build job (Morph Loader, rigging, ERC Freeze, save) takes 18 s, against about 110 s on the regular figure.
- **The user's cache is untouched:** the copy has its own data path, so the regular G8F add-on cache was unchanged after the job. Jobs keep the user's normal content directories.
- **A morph built on the copy names the copy:** 1,000 references (the parent geometry and every joint formula) point at `/data/Exchange/Genesis%208/Female/`. After rewriting them to the regular figure's path, it matched a morph built on the regular figure:
  - the same deltas and the same formula outputs
  - joint values within 0.06 cm
- **Why the 0.06 cm:** the differences are all in the mouth and tongue. The regular G8F also loads a third-party morph that seems active by default (`guhzcoituz/Rebecca Chambers/Rebecca Mouth.dsf`). The copy is the true stock baseline.
- **Moving output to the regular figure:** Exchange rewrites the path, which is deterministic and tested against the direct build. Copying the file over unchanged hasn't been tested by Exchange. Doing so would change the regular figure's add-on cache.

## Still to verify

- The source side: the same approach for a G9 copy, plus the dependency closure for a character's morphs (see above).
- Isolating the add-on cache is no longer needed for the target figure.
- Whether the dependency closure from enrichment is complete for character morphs, especially ERC-driven correctives.
- Disk use per job. Hardlinks only work on the same volume (the library is on `D:`, Exchange's data on `C:`), so plain copies may be needed. The library could be cleared after each job, or kept as a cache.
