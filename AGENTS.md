# Exchange: agent instructions

Exchange is Luke's personal Windows desktop workspace for 3D modding and solo
game development. It indexes Daz Studio libraries, Unreal projects, Mod
Organizer 2 instances and loose folders into one library of **dossiers** (what
an asset is) with **ledgers** (where it lives), and runs **processes** that
convert assets between those environments as queued **requisitions**.

## Read first

- `docs/VISION.md`: the brief. It wins over every other doc.
- `docs/PROGRESS.md`: where the project stands, the restart's roadmap, the
  decisions not to reopen, *Architecture in one page*, and *How we work*. Read
  its architecture section before changing code.
- `docs/DESIGN_SPEC.md` for how the built parts work, `docs/PROJECT_HOME.md`
  for the frozen project homes.
- `README.md`: what the app does today, from the user's side.

## Layout

```
src/exchange/      the core: scanner, db (SQLite, migrations), library, curation,
                   processes, requisitions, claims, bridges, projects, service (FastAPI).
                   Never imports Qt (a test enforces it).
tests/             pytest; fake environments in tests/fixtures/envs
docs/              design, progress and the service's OpenAPI contract (docs/api/)
factory/           the software factory (see below)
```

## Setup

Windows, Git Bash, Python 3.11+. The system `python` is 3.10, so everything
runs from the 3.12 venv in the main checkout:

```bash
py -3.12 -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"
```

A fresh worktree needs no setup of its own: run it with the main checkout's
venv and `PYTHONPATH=src`, so the worktree's code wins over the editable
install. `factory/checks.sh` does exactly that.

The CLI is `.venv/Scripts/exchange`, and the local service `exchange serve`
(the shell starts it for the Workspace). The window users work in is the
shell's Workspace, in cire992/Exchange-Shell: a change it needs to show is made
there separately, against this repository's API contract.

## Validation

```bash
bash factory/checks.sh
```

It installs the branch's declared dependencies into the venv if any are
missing, byte-compiles `src`, and runs the whole pytest suite. It must exit 0.

## Conventions

- `pathlib` everywhere; Windows paths are case-insensitive (see
  `exchange/paths.py`, `globs.py`).
- Read and write text as UTF-8 explicitly. PowerShell's `Get-Content` and
  `Set-Content` mangle UTF-8: write files from Python or with the Edit tool.
- **Scanning is strictly read-only.** Scan reads go through
  `src/exchange/scanner/readonly.py`; nothing is ever written into a scanned
  folder.
- **The user's work is never lost.** User edits live in the override layer and
  survive rescans; replaced output goes to the recycle folder, never deleted.
- Minimal dependencies. New behaviour gets pytest tests with the fake
  environment fixtures; never touch the user's real libraries, database or
  Exchange data folder (`EXCHANGE_DATA_DIR` points tests at scratch).
- Comment density and style like the neighbouring code. Short one-line commit
  messages.

## Looking at what users see

Users see this repository through the service API (the Workspace is built on
its contract, `docs/api/openapi.json`) and the CLI. To exercise a change:

- **The API:** in a test, build the app with
  `exchange.service.app.create_app(db, token=..., definitions=...)` and call it
  with FastAPI's `TestClient`, against a library scanned from
  `tests/fixtures/envs` (`tests/test_service.py` and `tests/test_service_edits.py`
  show the setup). To run it for real: `exchange serve --port <port>` with
  `--db` pointing at a scratch database.
- **The contract:** `exchange serve --openapi` prints the schema; the
  committed `docs/api/openapi.json` must match it (a test checks). Adding
  routes or fields is fine; removing or renaming them breaks the shell's
  Workspace, so it must be in the spec and noted in `docs/PROGRESS.md`.
- **The CLI:** run the command on a scratch database scanned from a fixture,
  e.g. `.venv/Scripts/python -m exchange scan tests/fixtures/envs/loose_files --db "$TMP/look.db"`
  (with `PYTHONPATH=src`, from the worktree), then the command being changed.

## Checks on real data

These are done by hand, never by the factory: its agents don't touch real libraries. Don't scan
the whole real Daz library unless the change is to scanning at that scale (3.56M files: about 10
minutes without enrichment, hours with it). Build a sample library in scratch instead: a few real
products with their DIM manifests, scanned in seconds by the same code.

```bash
PYTHONPATH=src .venv/Scripts/python scripts/sample_library.py "<library>" --list "genesis 9"
PYTHONPATH=src .venv/Scripts/python scripts/sample_library.py "<library>" "$TMP/sample" \
    --product "<name>" --random 5 --file "People/Genesis 9/<saved file>.duf"
EXCHANGE_DATA_DIR="$TMP/data" .venv/Scripts/exchange scan "$TMP/sample" --db "$TMP/data/library.db"
```

It says how many of each product's files it found: `--product` takes what's still at the listed
paths, `--random` only whole products, and `--file` adds files that moved or that no manifest lists.
Set `EXCHANGE_DATA_DIR` to scratch too, so claims don't reach the real data folder.

## Software factory

`/factory run` builds every open GitHub issue labeled `factory` through
intake → spec → build → gate → review → approve, one PR per issue. State is in
`factory/jobs/` (gitignored); `factory/bin/job` is its only writer. Checks:
`factory/checks.sh`. Dashboard: `cd factory && python -m http.server`, then
open http://localhost:8000/dashboard.html.
