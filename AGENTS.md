# Exchange: agent instructions

Exchange is Luke's personal Windows desktop workspace for 3D modding and solo
game development. It indexes Daz Studio libraries, Unreal projects, Mod
Organizer 2 instances and loose folders into one library of **dossiers** (what
an asset is) with **ledgers** (where it lives), and runs **processes** that
convert assets between those environments as queued **requisitions**.

## Read first

- `docs/PROGRESS.md`: where the project stands, the decisions not to reopen,
  *Architecture in one page*, and *How we work*. Read its architecture
  section before changing code.
- `docs/VISION.md`, when it exists: the brief. It wins over older design docs.
- `docs/DESIGN_SPEC.md` and `docs/PROJECT_HOME.md` for the area you touch.
- `README.md`: what the app does today, from the user's side.

## Layout

```
src/exchange/      the core: scanner, db (SQLite, migrations), library, curation,
                   processes, requisitions, bridges, projects, service (FastAPI).
                   Never imports Qt (a test enforces it).
src/exchange_ui/   the PySide6 window
tests/             pytest; fake environments in tests/fixtures/envs; tests/ui uses pytest-qt
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

There's no dev server. The app is `.venv/Scripts/exchange-app` (or
`python -m exchange_ui`), the CLI `.venv/Scripts/exchange`, and the local
service `exchange serve`.

## Validation

```bash
bash factory/checks.sh
```

It installs the branch's declared dependencies into the venv if any are
missing, byte-compiles `src`, and runs the whole pytest suite with the
offscreen Qt platform. It must exit 0.

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

## Looking at the window

There's no browser page to open. To see a change, build the widget offscreen
against a test library and grab it as a PNG in the system temp folder:

1. Scan a fixture into a temporary database:
   `.venv/Scripts/python -m exchange scan tests/fixtures/envs/loose_files --db "$TMP/look.db"`
   (with `PYTHONPATH=src`, from the worktree).
2. In a script saved under the temp folder, with `QT_QPA_PLATFORM=offscreen`:
   create the app with `exchange_ui.app.make_app([])`, open
   `exchange_ui.service.LibraryService("<db>")`, build
   `exchange_ui.main_window.MainWindow(service)` (or the widget that changed),
   `resize` and `show` it, drive it, call `QApplication.processEvents()`, then
   `widget.grab().save("<temp>/name.png")`.
3. Open the PNG with the Read tool. `tests/ui/conftest.py` shows the same
   setup as fixtures.

## Software factory

`/factory run` builds every open GitHub issue labeled `factory` through
intake → spec → build → gate → review → approve, one PR per issue. State is in
`factory/jobs/` (gitignored); `factory/bin/job` is its only writer. Checks:
`factory/checks.sh`. Dashboard: `cd factory && python -m http.server`, then
open http://localhost:8000/dashboard.html.
