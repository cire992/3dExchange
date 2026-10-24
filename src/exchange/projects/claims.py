"""Gap claims: validation's gaps turned into claim files, without duplicates (Roadmap phase 7b).

One gap claim stays open per piece of work: per target record to mature ("Spec LOT_X"), or per
record whose dossier link broke ("Relink NPC_X's dossier"). Re-running validation:

* opens a claim for new work, with ``triage: new`` so the triage inbox alerts the user;
* adds new needers to an open claim's ``needed_by`` (and raises its required maturity);
* never reopens work whose claim was dropped; a gap that returns after its claim was done opens a
  new claim linked to the old one;
* moves an open claim whose gap is gone to *review*, with a dated note. Done is the user's call.

Exchange edits only claims it created (``source: gap``), and only their ``status``,
``needed_by``, ``gap`` and ``triage`` lines; it then reads the file back to check that nothing else
changed.
"""

from __future__ import annotations

import datetime as dt
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from exchange.locks import Lock, LockBusy
from exchange.projects import frontmatter
from exchange.projects.home import ProjectError, ProjectHome
from exchange.projects.schema import LEVELS
from exchange.projects.validate import Claim, Gap, Report

VERBS = ("Sketch", "Spec", "Stub", "Build", "Polish")  # what reaching each maturity is called
OPEN = ("idea", "open", "claimed")  # validation may move these to review; review waits for the user


def slug(text: str, words: int = 8) -> str:
    """``LOT_SaltRowCantina`` → ``lot-salt-row-cantina``; ``What if the House…`` → ``what-if-the-house``."""
    text = re.sub(r"['’]", "", text)  # "smuggler's" is one word
    text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])|_", " ", text)
    parts = re.findall(r"[a-z0-9]+", text.casefold().encode("ascii", "ignore").decode())
    return "-".join(parts[:words])[:60].strip("-") or "claim"


def new_claim_path(home: ProjectHome, day: dt.date, name: str) -> Path:
    base = f"{day.isoformat()}-{slug(name)}"
    path, n = home.claims_dir / f"{base}.md", 2
    while path.exists():
        path, n = home.claims_dir / f"{base}-{n}.md", n + 1
    return path


def write_new(path: Path, meta: dict, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "x", encoding="utf-8", newline="\n") as f:  # never over an existing file
        f.write(frontmatter.dump(meta, body))


def rewrite(home: ProjectHome, claim: Claim, updates: dict, *, append: str = "") -> None:
    path = home.path / claim.path
    text = path.read_text(encoding="utf-8")
    path.write_bytes(frontmatter.set_keys(text, updates, append=append).encode("utf-8"))


@dataclass
class _Work:
    target: str
    work: str  # "mature" or "relink"
    gaps: list[Gap] = field(default_factory=list)

    @property
    def needers(self) -> list[str]:
        return list(dict.fromkeys(g.needed_by for g in self.gaps))

    @property
    def required(self) -> int:
        return max((g.required or 0) for g in self.gaps)


@dataclass
class SyncResult:
    opened: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    resolved: list[str] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)  # work not reopened because its claim was dropped
    problems: list[str] = field(default_factory=list)

    def to_json(self) -> dict:
        return {"opened": self.opened, "updated": self.updated, "resolved": self.resolved,
                "dropped": self.dropped, "problems": self.problems}


def _work_of(claim: Claim) -> tuple[str, str] | None:
    meta = claim.meta
    if meta.get("source") != "gap" or not isinstance(meta.get("target"), str):
        return None
    gap = meta.get("gap") if isinstance(meta.get("gap"), dict) else {}
    return meta["target"].casefold(), "relink" if gap.get("work") == "relink" else "mature"


def _needed_by(claim: Claim) -> list[str]:
    value = claim.meta.get("needed_by")
    items = value if isinstance(value, list) else [value] if value else []
    return [str(v) for v in items]


def _title(work: _Work) -> str:
    if work.work == "relink":
        return f"Relink {work.target}'s dossier"
    return f"{VERBS[max(work.required, 1)]} {work.target}"


def _body(work: _Work, report: Report) -> str:
    lines = []
    if work.work == "mature":
        target = report.record(work.target)
        if target is None:
            lines.append(f"{work.target} does not exist yet. These records need it at {LEVELS[work.required]} or above:")
        else:
            lines.append(f"{work.target} is a {LEVELS[target.maturity or 0]}. These records need it at "
                         f"{LEVELS[work.required]} or above:")
        lines += [f"- {g.message}" for g in work.gaps]
    else:
        for g in work.gaps:
            lines.append(f"- {g.message}")
            if g.candidates:
                lines.append("  Candidates to relink to:")
                lines += [f"  - {c.get('name', '?')} ({c.get('type', '?')}, {c.get('environment', '?')}): "
                          f"`dossier:{c['uid']}`, {c['why']}" for c in g.candidates]
            else:
                lines.append("  No candidate found in the library.")
    return "\n".join(lines)


def _gap_meta(work: _Work, report: Report) -> dict:
    if work.work == "relink":
        return {"work": "relink", "dossiers": list(dict.fromkeys(g.dossier for g in work.gaps if g.dossier))}
    target = report.record(work.target)
    meta: dict = {"work": "mature", "required": work.required}
    if target is None:
        meta["missing"] = True
    return meta


def sync_gap_claims(home: ProjectHome, report: Report, *, today: dt.date | None = None,
                    wait: float = 10.0) -> SyncResult:
    """Open, update and resolve gap claims from ``report`` (a fresh validation of ``home``)."""
    today = today or dt.date.today()
    lock = Lock("gap-claims", home.cache_dir / "locks")
    deadline = time.monotonic() + wait
    while True:
        try:
            lock.acquire()
            break
        except LockBusy:
            if time.monotonic() > deadline:
                raise ProjectError("another validation is writing this project's gap claims; try again") from None
            time.sleep(0.2)
    try:
        return _sync(home, report, today)
    finally:
        lock.release()


def _sync(home: ProjectHome, report: Report, today: dt.date) -> SyncResult:
    result = SyncResult()
    works: dict[tuple[str, str], _Work] = {}
    for gap in report.gaps:
        key = (gap.target.casefold(), gap.work)
        works.setdefault(key, _Work(gap.target, gap.work)).gaps.append(gap)
    existing: dict[tuple[str, str], list[Claim]] = {}
    for claim in sorted(report.claims.values(), key=lambda c: c.id):
        key = _work_of(claim)
        if key is not None:
            existing.setdefault(key, []).append(claim)

    for key, work in works.items():
        claims = existing.get(key, [])
        if any(c.meta.get("status") == "dropped" for c in claims):
            result.dropped.append(work.target)
            continue
        live = [c for c in claims if c.meta.get("status") not in ("done", "dropped")]
        if live:
            claim = live[0]
            needers = _needed_by(claim)
            added = [n for n in work.needers if n.casefold() not in {x.casefold() for x in needers}]
            updates: dict = {}
            notes = []
            if added:
                updates["needed_by"] = needers + added
                notes += [f"- {today.isoformat()}: {g.message}" for g in work.gaps if g.needed_by in added]
            gap_meta = claim.meta.get("gap") if isinstance(claim.meta.get("gap"), dict) else {}
            if work.work == "mature" and work.required > int(gap_meta.get("required") or 0):
                updates["gap"] = {**gap_meta, "required": work.required}
            if work.work == "relink":
                dossiers = list(dict.fromkeys([*(gap_meta.get("dossiers") or []), *_gap_meta(work, report)["dossiers"]]))
                if dossiers != list(gap_meta.get("dossiers") or []):
                    updates["gap"] = {**gap_meta, "dossiers": dossiers}
                    notes += [f"- {today.isoformat()}: {g.message}" for g in work.gaps
                              if g.dossier not in (gap_meta.get("dossiers") or [])]
            if updates:
                try:
                    rewrite(home, claim, updates, append="\n".join(notes))
                    result.updated.append(claim.id)
                except (frontmatter.FrontMatterError, OSError) as exc:
                    result.problems.append(f"{claim.path}: {exc}")
            continue
        meta = {"id": "", "title": _title(work), "status": "open", "created": today.isoformat(),
                "target": work.target, "source": "gap", "needed_by": work.needers,
                "gap": _gap_meta(work, report), "triage": "new"}
        done = [f"claim:{c.id}" for c in claims if c.meta.get("status") == "done"]
        if done:
            meta["links"] = done
        path = new_claim_path(home, today, _title(work))
        meta["id"] = path.stem
        body = _body(work, report)
        if done:
            body += f"\n\nThe gap is back after {', '.join(d.removeprefix('claim:') for d in done)} was done."
        try:
            write_new(path, meta, body)
            result.opened.append(path.stem)
        except OSError as exc:
            result.problems.append(f"{path}: {exc}")

    # Gaps that are gone. A record that failed to load hides its links' gaps, and without the
    # library no dossier link is checked: those claims are left alone rather than resolved.
    unsure = {f.subject.casefold() for f in report.errors if f.subject}
    for key, claims in existing.items():
        if key in works:
            continue
        for claim in claims:
            if claim.meta.get("status") not in OPEN:
                continue
            if key[1] == "relink" and not report.dossiers_checked:
                continue
            if {n.casefold() for n in _needed_by(claim)} & unsure or key[0] in unsure:
                continue
            note = (f"\nResolved by validation on {today.isoformat()}: "
                    + ("the dossier links resolve again." if key[1] == "relink" else
                       "no record needs more of this one now."))
            try:
                rewrite(home, claim, {"status": "review"}, append=note)
                result.resolved.append(claim.id)
            except (frontmatter.FrontMatterError, OSError) as exc:
                result.problems.append(f"{claim.path}: {exc}")
    return result


def acknowledge(home: ProjectHome, report: Report, ids: list[str] | None) -> list[str]:
    """Set ``triage: seen`` on the given claims (all new ones when ``ids`` is None)."""
    chosen = [c for c in report.claims.values() if c.meta.get("triage") == "new"
              and (ids is None or c.id in ids)]
    if ids is not None:
        unknown = sorted(set(ids) - set(report.claims))
        if unknown:
            raise ProjectError(f"no claim {', '.join(unknown)}")
    for claim in chosen:
        rewrite(home, claim, {"triage": "seen"})
    return [c.id for c in chosen]
