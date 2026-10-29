"""Claims: Luke's decision to get a thing into a place, kept as a markdown file in ``<data>/claims/``.

A claim file is front matter plus free notes. Exchange writes a new file once (mode ``x``), then
rewrites only ``requisitions``, ``milestone`` and ``closed`` in place, so hand edits to the notes, to
any other key and extra keys of your own survive. The milestone is derived from the library on
every read of an open claim; a closed claim keeps the one it had. Claims are read from the folder
each time; the database has no index of them.
"""

from __future__ import annotations

import datetime as dt
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from exchange.errors import ExchangeError
from exchange.paths import data_dir
from exchange.projects import frontmatter

MILESTONES = ("claimed", "acquired", "converted", "installed")  # in order; only the first two are derived so far
OWNED_KEYS = ("requisitions", "milestone", "closed")  # the only keys Exchange rewrites


class ClaimError(ExchangeError):
    """A claim request that cannot be done as asked."""


@dataclass
class Claim:
    id: str  # the file's stem
    path: Path
    meta: dict[str, Any]
    notes: str = ""
    problems: list[str] = field(default_factory=list, repr=False)

    @property
    def milestone(self) -> str | None:
        return self.meta.get("milestone")

    @property
    def closed(self) -> bool:
        return self.meta.get("closed") is not None

    def to_json(self) -> dict:
        return {**self.meta, "id": self.id, "notes": self.notes}


def claims_dir() -> Path:
    return data_dir() / "claims"


def slug(text: str, words: int = 8) -> str:
    """``LOT_SaltRowCantina`` → ``lot-salt-row-cantina``; ``What if the House…`` → ``what-if-the-house``."""
    text = re.sub(r"['’]", "", text)  # "smuggler's" is one word
    text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])|_", " ", text)
    parts = re.findall(r"[a-z0-9]+", text.casefold().encode("ascii", "ignore").decode())
    return "-".join(parts[:words])[:60].strip("-") or "claim"


def _new_path(day: dt.date, name: str) -> Path:
    base = f"{day.isoformat()}-{slug(name)}"
    path, n = claims_dir() / f"{base}.md", 2
    while path.exists():
        path, n = claims_dir() / f"{base}-{n}.md", n + 1
    return path


def _derive(conn: sqlite3.Connection, thing: object) -> str:
    """``acquired`` when the dossier has an entry that is not retired, else ``claimed``."""
    row = conn.execute(
        "SELECT count(*), sum(e.status != 'retired') FROM entry e JOIN ledger l ON l.id = e.ledger_id"
        " JOIN dossier d ON d.id = l.dossier_id WHERE d.uid = ?", (str(thing),)).fetchone()
    return "acquired" if row[1] else "claimed"


def new(conn: sqlite3.Connection, uid: str, env_id: int, *, role: str | None = None,
        folder: str | None = None, note: str = "", today: dt.date | None = None) -> Claim:
    today = today or dt.date.today()
    thing = conn.execute("SELECT uid, name FROM dossier_effective WHERE uid = ?", (uid,)).fetchone()
    if thing is None:
        raise ClaimError(f"no dossier {uid!r} in the library")
    place = conn.execute("SELECT uid, name FROM environment WHERE id = ?", (env_id,)).fetchone()
    if place is None:
        raise ClaimError(f"no environment {env_id} in the library")
    path = _new_path(today, thing["name"])
    meta = {"id": path.stem, "thing": thing["uid"], "thing_name": thing["name"], "as": role,
            "place": place["uid"], "place_name": place["name"], "folder": folder, "requisitions": [],
            "milestone": _derive(conn, thing["uid"]), "created": today, "closed": None}
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(path, "x", encoding="utf-8", newline="\n") as f:  # never over an existing file
            f.write(frontmatter.dump(meta, note))
    except FileExistsError:
        raise ClaimError(f"{path.name} already exists; try again") from None
    return read_one(conn, path.stem)


def _files() -> list[Path]:
    folder = claims_dir()
    return sorted((p for p in folder.glob("*.md") if p.is_file()), key=lambda p: p.name) if folder.is_dir() else []


def _read(conn: sqlite3.Connection, path: Path) -> Claim:
    doc = frontmatter.read(path)
    claim = Claim(path.stem, path, doc.meta, doc.body)
    if not claim.closed:
        derived = _derive(conn, doc.meta.get("thing"))
        if derived != doc.meta.get("milestone"):
            try:
                update(claim, {"milestone": derived})
            except (ClaimError, frontmatter.FrontMatterError, OSError) as exc:
                claim.meta["milestone"] = derived
                claim.problems.append(f"{path.name}: could not update the milestone: {exc}")
    return claim


def read_all(conn: sqlite3.Connection) -> tuple[list[Claim], list[str]]:
    """Every readable claim, and a problem line for each file that is not (or could not be updated)."""
    claims, problems = [], []
    for path in _files():
        try:
            claim = _read(conn, path)
        except (frontmatter.FrontMatterError, OSError, UnicodeDecodeError) as exc:
            problems.append(f"{path.name}: {exc}")
            continue
        claims.append(claim)
        problems += claim.problems
    return claims, problems


def read_one(conn: sqlite3.Connection, id: str) -> Claim:
    for path in _files():  # looked up among the files, never built from the id
        if path.stem == id:
            try:
                return _read(conn, path)
            except (frontmatter.FrontMatterError, OSError, UnicodeDecodeError) as exc:
                raise ClaimError(f"{path.name}: {exc}") from exc
    raise ClaimError(f"no claim {id!r}")


def update(claim: Claim, updates: dict[str, Any], append: str = "") -> None:
    """Rewrite ``requisitions``, ``milestone`` and ``closed`` in the claim's file, nothing else."""
    other = sorted(set(updates) - set(OWNED_KEYS))
    if other:
        raise ClaimError(f"Exchange only changes {', '.join(OWNED_KEYS)}, not {', '.join(other)}")
    text = claim.path.read_text(encoding="utf-8")
    claim.path.write_bytes(frontmatter.set_keys(text, updates, append=append).encode("utf-8"))
    claim.meta.update(updates)
    if append:
        claim.notes = frontmatter.read(claim.path).body


def close(conn: sqlite3.Connection, id: str, reason: str = "", today: dt.date | None = None) -> Claim:
    claim = read_one(conn, id)
    if claim.closed:
        raise ClaimError(f"claim {id} is already closed ({claim.meta['closed']})")
    try:
        update(claim, {"closed": today or dt.date.today()}, append=reason)
    except (frontmatter.FrontMatterError, OSError) as exc:
        raise ClaimError(f"{claim.path.name}: {exc}") from exc
    return claim
