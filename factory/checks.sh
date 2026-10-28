#!/usr/bin/env bash
# The repo's checks. Exit 0 only when the branch is fit to review.
#
# The gate runs this script from the main checkout with the job's worktree as
# the working directory. Keep it fast, deterministic and non-interactive: no
# watch modes, no prompts, nothing that rewrites files.
#
# Worktrees share the main checkout's .venv (Python 3.12, `pip install -e ".[dev]"`, see AGENTS.md).
# PYTHONPATH=src makes the worktree's own code win over that editable install.
set -euo pipefail

# The venv lives in the main checkout, which owns the repository's .git folder.
MAIN="$(dirname "$(git -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --path-format=absolute --git-common-dir)")"
PYTHON="$MAIN/.venv/Scripts/python.exe"
[ -x "$PYTHON" ] || PYTHON="$MAIN/.venv/bin/python"

export PYTHONPATH=src
export PYTHONUTF8=1
export QT_QPA_PLATFORM=offscreen

# The branch's declared dependencies (not the package itself), so a new dependency is present.
# Once they're installed this is a quick no-op.
REQS="$(mktemp)"
trap 'rm -f "$REQS"' EXIT
"$PYTHON" -c 'import tomllib; p = tomllib.load(open("pyproject.toml", "rb"))["project"]; print("\n".join(p["dependencies"] + p["optional-dependencies"]["dev"]))' > "$REQS"
"$PYTHON" -m pip install -q --disable-pip-version-check -r "$REQS"

"$PYTHON" -m compileall -q src
"$PYTHON" -m pytest -q -p no:cacheprovider
