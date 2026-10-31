"""The service's claims API (R4a, R4b): read, make, preview, close and walk the loop's claims.

A claim is a markdown file (``exchange.claims``). Reading, previewing and planning only read the
library and the files; making and closing write the file, and walking queues a requisition on the
editor's write connection (``claims.walk``), then starts it as a job unless told not to. A preview goes
through ``claims.prepare``, the code a real claim goes through, and writes nothing. A file is
hand-editable, so every response is built key by key from what the file holds: a scalar of the wrong
type reads as text, anything else as null, and extra keys are never returned.

``GET /claims/changes`` tells a client when to list again: a version that grows with every claim made,
closed or walked, every job that ends, and every claim file that changes (``ClaimWatcher``).
"""

from __future__ import annotations

import datetime as dt
from typing import Literal

from fastapi import FastAPI, HTTPException, Query

from exchange import claims
from exchange.errors import ExchangeError
from exchange.processes.registry import tool_paths
from exchange.requisitions import lifecycle
from exchange.requisitions.presets import remember
from exchange.service import models
from exchange.service.jobs import MAX_WAIT
from exchange.service.requisitions import plan_defaults, plan_result

TEXT_KEYS = ("thing", "thing_name", "as", "place", "place_name", "folder", "milestone", "created", "closed")


def _text(value: object) -> str | None:
    """A file's value as text: a string stays, a date is ISO, a number or bool is its text, the rest is null."""
    if isinstance(value, str):
        return value
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    if isinstance(value, (bool, int, float)):
        return str(value)
    return None


def _failure(exc: ExchangeError) -> HTTPException:
    code = 404 if isinstance(exc, claims.ClaimNotFound) else 400 if isinstance(exc, claims.FolderLeavesPlace) else 409
    return HTTPException(code, str(exc))


def _view(data: dict) -> dict:
    """The list shape, from ``claims.describe``."""
    return {"id": data["id"], **{key: _text(data.get(key)) for key in TEXT_KEYS}, "turn": data["turn"],
            "turn_line": data["turn_line"], "already_there": data["already_there"], "path": data["path"]}


def register(app: FastAPI, library, jobs, api, errors: dict) -> None:
    prefix = app.state.prefix
    refused = {**errors, 409: {"model": models.Problem}}

    def typed(body: models.PlanChoices) -> dict:
        """The options as ``plan_requisition``'s ``params``: ``{"process.option": value}``."""
        return {f"{p}.{k}": v for p, values in body.options.items() for k, v in values.items()}

    def describe(conn, claim: claims.Claim) -> dict:
        return _view(claims.describe(conn, library.definitions, library.processes.registry(), claim, tool_paths()))

    def detail(conn, claim: claims.Claim) -> dict:
        return {**describe(conn, claim), "notes": claim.notes,
                "requisitions": [{"uid": _text(uid), "id": row["id"] if row else None,
                                  "state": row["state"] if row else None, "message": row["message"] if row else None}
                                 for uid, row in claims.resolve_requisitions(conn, claim.meta)]}

    @app.post(prefix + "/claims/preview", response_model=models.ClaimView,
              dependencies=[api], responses=refused, tags=["claims"])
    def preview_claim(body: models.ClaimPreviewRequest) -> dict:
        """The claim these fields would make, with its path and whose turn it is. Writes nothing."""
        conn = library.conn()
        try:
            claim = claims.prepare(conn, body.uid, body.environment, role=body.as_, folder=body.folder,
                                   definitions=library.definitions)
        except claims.ClaimError as exc:
            raise _failure(exc) from exc
        return describe(conn, claim)

    @app.post(prefix + "/claims", response_model=models.ClaimDetail, dependencies=[api], responses=refused,
              tags=["claims"])
    def make_claim(body: models.ClaimRequest) -> dict:
        """Make the claim: a file in the claims folder. Returns it as ``GET /claims/{id}`` does."""
        conn = library.conn()
        try:
            claim = claims.new(conn, body.uid, body.environment, role=body.as_, folder=body.folder, note=body.note,
                               definitions=library.definitions)
        except claims.ClaimError as exc:
            raise _failure(exc) from exc
        library.claim_watcher.bump()
        return detail(conn, claim)

    @app.get(prefix + "/claims", response_model=models.ClaimList, dependencies=[api], responses=refused,
             tags=["claims"])
    def list_claims(
        all: bool = Query(False, description="Closed claims too"),
        turn: Literal["you", "exchange", "build"] | None = Query(
            None, description="Only claims with this turn: you (the user's move), exchange (the latest "
                              "requisition is queued or running), build (a process "
                              "has to be built). A closed claim's turn is none, so it never matches"),
        thing: str | None = Query(None, description="Only claims for this dossier uid"),
    ) -> dict:
        """Claims newest first, and a line for each file that could not be read (never filtered)."""
        conn = library.conn()
        found, problems = claims.read_all(conn)
        views = [describe(conn, claim) for claim in found if all or not claim.closed]
        views = [v for v in views if (turn is None or v["turn"] == turn) and (thing is None or v["thing"] == thing)]
        views.sort(key=lambda v: v["id"], reverse=True)
        views.sort(key=lambda v: (v["created"] is not None, v["created"] or ""), reverse=True)
        return {"claims": views, "problems": problems}

    @app.get(prefix + "/claims/changes", response_model=models.ClaimChanges, dependencies=[api], responses=errors,
             tags=["claims"])
    def claim_changes(since: int | None = Query(None, description="The version you have: wait for a newer one"),
                      wait: float = Query(0, ge=0, le=MAX_WAIT, description="Seconds to wait for a change")) -> dict:
        """Whether claims may have changed since ``version`` ``since``: made, closed or walked through the
        service, a job ended, or a claim file changed (``available`` is false without ``watchdog``: changes
        to the files themselves are not noticed). The first call starts watching the claims folder."""
        library.claim_watcher.start(claims.claims_dir())
        return library.claim_watcher.wait(since, wait)

    @app.get(prefix + "/claims/{id}", response_model=models.ClaimDetail, dependencies=[api], responses=refused,
             tags=["claims"])
    def get_claim(id: str) -> dict:
        """One claim with its notes and the requisitions it recorded."""
        conn = library.conn()
        try:
            return detail(conn, claims.read_one(conn, id))
        except claims.ClaimError as exc:
            raise _failure(exc) from exc

    @app.post(prefix + "/claims/{id}/close", response_model=models.ClaimDetail, dependencies=[api],
              responses=refused, tags=["claims"])
    def close_claim(id: str, body: models.ClaimClose | None = None) -> dict:
        """Close a claim; it keeps its milestone. The reason is added to its notes."""
        conn = library.conn()
        try:
            closed = claims.close(conn, id, (body.reason or "") if body else "")
        except claims.ClaimError as exc:
            raise _failure(exc) from exc
        library.claim_watcher.bump()
        return detail(conn, closed)

    @app.post(prefix + "/claims/{id}/plan", response_model=models.PlanResult, dependencies=[api],
              responses=refused, tags=["claims"])
    def plan_claim(id: str, body: models.PlanChoices) -> dict:
        """Plan the claim's path as ``POST /claims/{id}/walk`` would queue it. Queues nothing; as on any read, a stale milestone may be saved. Options
        are chosen as for ``POST /requisitions/queue``."""
        registry = library.processes.registry()
        defaults = plan_defaults(registry, body.preset)
        try:
            _, plan = claims.plan_path(library.conn(), library.definitions, registry, id, tool_paths(),
                                       params=typed(body), defaults=defaults, on_collision=body.on_collision,
                                       excluded=body.excluded)
        except ExchangeError as exc:
            raise _failure(exc) from exc
        return plan_result([plan], list(dict.fromkeys(plan.warnings)), registry)

    @app.post(prefix + "/claims/{id}/walk", response_model=models.ClaimWalked, dependencies=[api],
              responses={**refused, 503: {"model": models.Problem}}, tags=["claims"])
    def walk_claim(id: str, body: models.ClaimWalkRequest) -> dict:
        """Queue the claim's path as a requisition, remember its options as last used, and (with ``run``)
        start it as a job. If the job could not start, the requisition stays queued and ``problem`` says why."""
        registry = library.processes.registry()
        defaults = plan_defaults(registry, body.preset)
        jobs.refuse_while_writing()

        def queue(curator):
            try:
                return claims.walk(curator.conn, library.definitions, registry, id, tool_paths(), params=typed(body),
                                   defaults=defaults, on_collision=body.on_collision, excluded=body.excluded)
            except ExchangeError as exc:  # the editor's 404s don't know "no claim", and a PlanError is a 409
                raise _failure(exc) from exc

        claim, requisition_id = library.editor.run(queue)
        library.claim_watcher.bump()
        conn = library.conn()
        remember({process: values for item in lifecycle.detail(conn, requisition_id)["items"] if item["include"]
                  for process, values in item["params"].items()})
        job, problem = None, None
        if body.run:
            try:
                job = jobs.start("requisitions", f"Running requisition {requisition_id}",
                                 ["requisition", "run", str(requisition_id)], writes=True).view()
            except HTTPException as exc:
                problem = str(exc.detail)
        shown = detail(conn, claim)
        return {"claim": shown, "job": job, "problem": problem,
                "requisition": next(r for r in shown["requisitions"] if r["id"] == requisition_id)}
