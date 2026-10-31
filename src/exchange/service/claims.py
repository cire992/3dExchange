"""The service's claims API (R4a): read, make, preview and close the loop's claims.

A claim is a markdown file (``exchange.claims``); the routes only read the library and the files. A
preview goes through ``claims.prepare``, the code a real claim goes through, and writes nothing. A
file is hand-editable, so every response is built key by key from what the file holds: a scalar of
the wrong type reads as text, anything else as null, and extra keys are never returned.
"""

from __future__ import annotations

import datetime as dt
from typing import Literal

from fastapi import FastAPI, HTTPException, Query

from exchange import claims
from exchange.processes.registry import tool_paths
from exchange.service import models

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


def _failure(exc: claims.ClaimError) -> HTTPException:
    code = 404 if isinstance(exc, claims.ClaimNotFound) else 400 if isinstance(exc, claims.FolderLeavesPlace) else 409
    return HTTPException(code, str(exc))


def _view(data: dict) -> dict:
    """The list shape, from ``claims.describe``."""
    return {"id": data["id"], **{key: _text(data.get(key)) for key in TEXT_KEYS}, "turn": data["turn"],
            "turn_line": data["turn_line"], "already_there": data["already_there"], "path": data["path"]}


def register(app: FastAPI, library, api, errors: dict) -> None:
    prefix = app.state.prefix
    refused = {**errors, 409: {"model": models.Problem}}

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
        return detail(conn, claim)

    @app.get(prefix + "/claims", response_model=models.ClaimList, dependencies=[api], responses=refused,
             tags=["claims"])
    def list_claims(
        all: bool = Query(False, description="Closed claims too"),
        turn: Literal["you", "exchange", "build"] | None = Query(None, description="Only claims whose turn it is"),
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
            return detail(conn, claims.close(conn, id, (body.reason or "") if body else ""))
        except claims.ClaimError as exc:
            raise _failure(exc) from exc
