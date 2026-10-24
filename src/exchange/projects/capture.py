"""Fast capture: one line of text becomes a Sketch record or an idea claim (Roadmap phase 7b).

A line that starts with an editor ID (``NPC_DockMaster: gruff harbormaster who…``) creates that
record at Sketch, with the rest of the line as its prose. Any other line creates an idea claim,
attached to a record with ``on``. Unattached ideas are allowed; validation reports them as unfiled.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from pathlib import Path

from exchange.projects.claims import new_claim_path, write_new
from exchange.projects.home import ProjectError, ProjectHome
from exchange.projects.schema import EDITOR_ID, LEVELS, load_schemas, signature_of

_LEADING_ID = re.compile(r"^\s*((?:[A-Z]{3}_|[A-Z]{4}_)[A-Za-z0-9][A-Za-z0-9_]*)(?:\s*[:\-–—]\s*|\s+|$)")
_GOAL = re.compile(r"^G\d+$")


@dataclass
class Captured:
    kind: str  # "record" or "claim"
    id: str
    path: Path
    warnings: list[str] = field(default_factory=list)


def _existing_record(home: ProjectHome, editor_id: str) -> Path | None:
    folder = home.records_dir / signature_of(editor_id)
    if not folder.is_dir():
        return None
    return next((p for p in folder.glob("*.md") if p.stem.casefold() == editor_id.casefold()), None)


def capture(home: ProjectHome, line: str, *, on: str | None = None, goal: str | None = None,
            maturity: int = 0, today: dt.date | None = None) -> Captured:
    text = " ".join(line.split())
    if not text:
        raise ProjectError("nothing to capture: the line is empty")
    today = today or dt.date.today()
    if goal is not None and not _GOAL.match(goal):
        raise ProjectError(f"{goal!r} is not a goal ID such as G1")
    match = _LEADING_ID.match(text)
    if match:
        return _record(home, match.group(1), text[match.end():].strip(), on, goal, maturity)
    return _claim(home, text, on, goal, today)


def _record(home: ProjectHome, editor_id: str, prose: str, on: str | None, goal: str | None,
            maturity: int) -> Captured:
    warnings = []
    found = _existing_record(home, editor_id)
    if found is not None:
        raise ProjectError(f"{found.stem} already exists ({found.relative_to(home.path).as_posix()})")
    signature = signature_of(editor_id)
    types, _ = load_schemas(home.schemas_dir)
    if signature not in types:
        warnings.append(f"{signature} has no schema yet: only the record's id and maturity are checked")
    if on or goal:
        warnings.append("--on and --goal are for idea claims; a record keeps its links in its fields")
    path = home.records_dir / signature / f"{editor_id}.md"
    write_new(path, {"id": editor_id, "maturity": maturity}, prose)
    if maturity:
        warnings.append(f"created at {LEVELS[maturity]}: validation will ask for that level's fields")
    return Captured("record", editor_id, path, warnings)


def _claim(home: ProjectHome, text: str, on: str | None, goal: str | None, today: dt.date) -> Captured:
    warnings = []
    meta: dict = {"id": "", "status": "idea", "created": today.isoformat(), "source": "manual"}
    if on:
        if not EDITOR_ID.match(on):
            raise ProjectError(f"{on!r} is not an editor ID such as NPC_DockMaster")
        if _existing_record(home, on) is None:
            warnings.append(f"{on} has no record yet")
        meta["target"] = on
    else:
        warnings.append("unfiled: attach it to a record with --on, or later in the file (target:)")
    if goal:
        meta["goal"] = goal
    path = new_claim_path(home, today, text)
    meta["id"] = path.stem
    write_new(path, meta, text)
    return Captured("claim", path.stem, path, warnings)
