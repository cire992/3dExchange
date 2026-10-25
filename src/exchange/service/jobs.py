"""The service's jobs API, part 1 (Roadmap phase 6g): adding and scanning environments, and the
other long jobs the window runs in the background, as the PySide6 window's ``ScanRunner`` does.

A job is a worker process, ``python -m exchange <command> ... --progress-json``, whose JSON lines
become the job's progress and result; the service never scans in its own process. Clients follow a
job by asking for it again with the ``version`` they last saw: the request returns as soon as the
job changes (or after ``wait`` seconds), so progress arrives without polling in a loop.

One job that writes the library (scan, rescan, classify) runs at a time, as in the window; another
is refused (409) until it finishes or is stopped. Detection (``scan --dry-run``) only lists folders
and may run beside it. Stopping kills the process: everything a scan finished before that is saved
(the scanner commits as it goes). While a job writes, edits may find the library busy (503).

Environments are registered and configured here too (not curation: these are not undoable), and
the watcher's change notices are served at ``/changes``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from datetime import datetime, timezone
from itertools import count
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query

from exchange.autodiscover import discover_sources
from exchange.db import repository as repo
from exchange.environments import VISIBILITIES, register_root, set_excluded
from exchange.service import models
from exchange.service.watch import Watcher

TOKEN_ENV = "EXCHANGE_SERVICE_TOKEN"  # the service's secret; never handed to workers
MAX_WAIT = 25  # seconds a request waits for a change (below the shell proxy's timeouts)
KEEP_FINISHED = 20
STOPPED = {"scan": "Stopped; everything finished before that is saved.",
           "rescan": "Stopped; everything finished before that is saved.",
           "classify": "Stopped; the classification was not saved.",
           "detect": "Stopped.",
           "requisitions": "Stopped; the requisition that was running is queued again.",
           "remove": "Stopped; the files moved so far stay in the recycle folder."}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Job:
    def __init__(self, job_id: int, kind: str, label: str, writes: bool, environments: list[int]) -> None:
        self.id, self.kind, self.label, self.writes, self.environments = job_id, kind, label, writes, environments
        self.state = "running"  # running | done | failed | stopped
        self.started_at, self.finished_at = _now(), None
        self.progress: dict | None = None
        self.result: Any = None
        self.error: str | None = None
        self.version = 0
        self.stopping = False
        self.process: subprocess.Popen | None = None

    def view(self, full: bool = True) -> dict:
        scan = self.kind in ("scan", "detect", "rescan")
        out = {"id": self.id, "kind": self.kind, "label": self.label, "state": self.state, "writes": self.writes,
               "environments": self.environments, "started_at": self.started_at,
               "finished_at": self.finished_at, "progress": self.progress, "error": self.error,
               "version": self.version, "report": None, "result": None}
        if full and self.result is not None:
            out["report" if scan else "result"] = self.result
        return out


class Jobs:
    """Worker processes for long jobs, followed by version (see the module's docstring)."""

    def __init__(self, library, on_finished=None) -> None:
        self.library = library
        self.on_finished = on_finished  # called (outside the lock) with each job that ends
        self.version = 0
        self._ids = count(1)
        self._jobs: dict[int, Job] = {}
        self._changed = threading.Condition()
        self._closed = False

    # Starting -----------------------------------------------------------------------------------

    def refuse_while_writing(self) -> None:
        with self._changed:  # reentrant: start() calls it holding the lock
            running = next((j for j in self._jobs.values() if j.writes and j.state == "running"), None)
        if running is not None:
            raise HTTPException(409, f"{running.label} is running; wait for it to finish, or stop it")

    def start(self, kind: str, label: str, args: list[str], *, writes: bool, json_output: bool = False,
              environments: list[int] | None = None) -> Job:
        """Run ``python -m exchange <args>`` as a job; ``json_output`` for commands that print one
        JSON document at the end (``--json``) instead of progress lines."""
        command = self.command(args, json_output)
        env = {k: v for k, v in os.environ.items() if k != TOKEN_ENV}
        env["PYTHONIOENCODING"] = "utf-8"
        with self._changed:
            if self._closed:
                raise HTTPException(503, "The service is stopping")
            if writes:
                self.refuse_while_writing()
            job = Job(next(self._ids), kind, label, writes, environments or [])
            try:
                job.process = subprocess.Popen(
                    command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            except OSError as exc:
                raise HTTPException(500, f"could not start the worker: {exc}") from exc
            self._jobs[job.id] = job
            self._bump(job)
            self._forget_old()
        stderr: list[bytes] = []
        reader = threading.Thread(target=lambda: stderr.append(job.process.stderr.read()),
                                  name=f"job-{job.id}-stderr", daemon=True)
        reader.start()
        threading.Thread(target=self._follow, args=(job, json_output, reader, stderr), name=f"job-{job.id}",
                         daemon=True).start()
        return job

    def command(self, args: list[str], json_output: bool) -> list[str]:
        """The worker's command line: this Python, on this library, with these definitions."""
        library = self.library
        command = [sys.executable, "-m", "exchange", *args, "--db", str(library.db_path),
                   "--threshold", str(library.threshold)]
        for folder in library.definition_dirs:
            command += ["--definitions", str(folder)]
        return [*command, "--json" if json_output else "--progress-json"]

    def _forget_old(self) -> None:
        finished = [j for j in self._jobs.values() if j.state != "running"]
        for job in finished[:-KEEP_FINISHED] if len(finished) > KEEP_FINISHED else []:
            del self._jobs[job.id]

    def _bump(self, job: Job) -> None:  # with the lock held
        job.version += 1
        self.version += 1
        self._changed.notify_all()

    # Following ----------------------------------------------------------------------------------

    def _follow(self, job: Job, json_output: bool, reader: threading.Thread, stderr: list[bytes]) -> None:
        process = job.process
        whole: list[str] = []
        for raw in process.stdout:
            line = raw.decode("utf-8", errors="replace").strip()
            if json_output:
                whole.append(line)
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            with self._changed:
                if event.get("event") == "progress":
                    job.progress = {k: v for k, v in event.items() if k != "event"}
                    self._bump(job)
                elif event.get("event") == "result":
                    job.result = event.get("data")
        code = process.wait()
        reader.join(timeout=5)
        message = (stderr[0] if stderr else b"").decode("utf-8", errors="replace").strip()
        with self._changed:
            if json_output and code == 0:
                try:
                    job.result = json.loads("\n".join(whole))
                except json.JSONDecodeError as exc:
                    job.error = f"unreadable output: {exc}"
            job.finished_at = _now()
            if job.stopping:
                job.state, job.error = "stopped", STOPPED.get(job.kind, "Stopped.")
            elif code != 0 or job.error:
                job.state = "failed"
                job.error = job.error or message.removeprefix("exchange: error: ").strip() or f"exit code {code}"
            else:
                job.state = "done"
            self._bump(job)
        if self.on_finished is not None:
            self.on_finished(job)

    # Reading and stopping -----------------------------------------------------------------------

    def get(self, job_id: int) -> Job:
        with self._changed:
            job = self._jobs.get(job_id)
        if job is None:
            raise HTTPException(404, f"no job {job_id}")
        return job

    def wait_job(self, job_id: int, since: int | None, timeout: float) -> dict:
        job = self.get(job_id)
        with self._changed:
            if since is not None:
                self._changed.wait_for(lambda: job.version != since, timeout)
            return job.view()

    def wait_all(self, since: int | None, timeout: float) -> dict:
        with self._changed:
            if since is not None:
                self._changed.wait_for(lambda: self.version != since, timeout)
            jobs = sorted(self._jobs.values(), key=lambda j: (j.state != "running", -j.id))
            return {"version": self.version, "jobs": [j.view(full=False) for j in jobs]}

    def stop(self, job_id: int) -> dict:
        job = self.get(job_id)
        with self._changed:
            if job.state == "running" and job.process is not None:
                job.stopping = True
                job.process.kill()
            return job.view()

    def close(self) -> None:
        """Stop every running job (the service is stopping)."""
        with self._changed:
            self._closed = True
            running = [j for j in self._jobs.values() if j.state == "running"]
            for job in running:
                job.stopping = True
                if job.process is not None:
                    job.process.kill()
        for job in running:
            if job.process is not None:
                try:
                    job.process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    pass


# Routes -----------------------------------------------------------------------------------------


def _folder(path: str) -> Path:
    folder = Path(path).expanduser()
    if not folder.is_absolute() or not folder.is_dir():
        raise HTTPException(400, f"not a folder: {path}")
    return folder.resolve()


def mo2_profiles(root: str) -> tuple[list[str], str | None]:
    """Profiles of an MO2 instance and the one its ini selects. Reads only folder names and the ini."""
    from exchange.scanner.layers.mo2 import instance_ini
    from exchange.scanner.readonly import ini_value, read_ini

    folder = Path(root) / "profiles"
    try:
        names = sorted(e.name for e in os.scandir(folder) if e.is_dir())
    except OSError:
        names = []
    ini = instance_ini(Path(root))
    selected = ini_value(read_ini(ini), "General", "selected_profile") if ini else None
    return names, selected if selected in names else None


def register(app: FastAPI, library, jobs: Jobs, watcher: Watcher, api, errors: dict) -> None:
    prefix = app.state.prefix
    busy = {**errors, 409: {"model": models.Problem}, 503: {"model": models.Problem}}

    # Jobs ---------------------------------------------------------------------------------------

    @app.get(prefix + "/jobs", response_model=models.JobList, dependencies=[api], responses=errors, tags=["jobs"])
    def list_jobs(since: int | None = Query(None, description="The list's version you have: wait for a newer one"),
                  wait: float = Query(0, ge=0, le=MAX_WAIT, description="Seconds to wait for a change")) -> dict:
        """Running jobs first, then the latest finished ones (without their reports)."""
        return jobs.wait_all(since, wait)

    @app.get(prefix + "/jobs/{job_id}", response_model=models.Job, dependencies=[api], responses=errors, tags=["jobs"])
    def get_job(job_id: int,
                since: int | None = Query(None, description="The job's version you have: wait for a newer one"),
                wait: float = Query(0, ge=0, le=MAX_WAIT, description="Seconds to wait for a change")) -> dict:
        """One job with its latest progress, and its report or result once it has ended."""
        return jobs.wait_job(job_id, since, wait)

    @app.post(prefix + "/jobs/{job_id}/stop", response_model=models.Job, dependencies=[api], responses=errors,
              tags=["jobs"])
    def stop_job(job_id: int) -> dict:
        """Stop a running job (a scan keeps what it finished)."""
        return jobs.stop(job_id)

    @app.post(prefix + "/jobs/scan", response_model=models.Job, dependencies=[api], responses=busy, tags=["jobs"])
    def scan(body: models.FolderJob) -> dict:
        """Detect the environments in a folder, register them and scan them (``exchange scan``)."""
        folder = _folder(body.folder)
        return jobs.start("scan", f"Scanning {folder}", ["scan", str(folder)], writes=True).view()

    @app.post(prefix + "/jobs/detect", response_model=models.Job, dependencies=[api], responses=busy, tags=["jobs"])
    def detect(body: models.FolderJob) -> dict:
        """Which environments a folder holds, without reading any file (``exchange scan --dry-run``);
        nothing is written. The add-environment wizard's second step."""
        folder = _folder(body.folder)
        return jobs.start("detect", f"Detecting environments in {folder}", ["scan", str(folder), "--dry-run"],
                          writes=False).view()

    @app.post(prefix + "/jobs/rescan", response_model=models.Job, dependencies=[api], responses=busy, tags=["jobs"])
    def rescan(body: models.EnvironmentsJob) -> dict:
        """Rescan known environments (all of them without ``environments``)."""
        ids = _known(body.environments)
        args = ["rescan", *(a for i in ids for a in ("--env", str(i)))]
        label = "Rescanning " + (_names(ids) if ids else "every environment")
        return jobs.start("rescan", label, args, writes=True, environments=ids).view()

    @app.post(prefix + "/jobs/classify", response_model=models.Job, dependencies=[api], responses=busy,
              tags=["jobs"])
    def classify(body: models.ClassifyJob) -> dict:
        """Classify the library again with the lexicons as they are now ("Apply to library" after lexicon
        edits); ``regroup`` also regroups hand-installed Daz products (after theme, author or category
        edits; minutes on a big library)."""
        ids = _known(body.environments)
        args = ["classify", *(["--regroup"] if body.regroup else []), *(a for i in ids for a in ("--env", str(i)))]
        label = "Applying lexicon changes" + (" and regrouping Daz products" if body.regroup else "")
        return jobs.start("classify", label, args, writes=True, json_output=True, environments=ids).view()

    def _known(ids: list[int] | None) -> list[int]:
        ids = list(dict.fromkeys(ids or []))
        known = {e["id"] for e in repo.list_environments(library.conn())}
        missing = [i for i in ids if i not in known]
        if missing:
            raise HTTPException(404, f"no environment {', '.join(map(str, missing))}")
        return ids

    def _names(ids: list[int]) -> str:
        names = {e["id"]: e["name"] for e in repo.list_environments(library.conn())}
        return ", ".join(names[i] for i in ids)

    # Environments -------------------------------------------------------------------------------

    @app.get(prefix + "/environment-types", response_model=list[models.EnvironmentType], dependencies=[api],
             responses=errors, tags=["environments"])
    def environment_types() -> list[dict]:
        """The environment definitions an environment can be of, for the add-environment wizard."""
        return [{"id": d.id, "name": d.name, "handler": d.handler, "multi_root": d.multi_root,
                 "fallback": d.fallback, "ignore_globs": list(d.ignore_globs),
                 "variants": [{"id": v.id, "name": v.name} for v in d.variants]}
                for d in sorted(library.definitions.environments.values(), key=lambda d: d.name.casefold())]

    @app.get(prefix + "/environments/discover", response_model=list[models.FoundSource], dependencies=[api],
             responses=errors, tags=["environments"])
    def discover() -> list[dict]:
        """Game, engine and content-library folders found on this PC (Steam, Epic, Unreal projects, Daz,
        MO2). Reads only where they are, never their files."""
        registered = [r["path"] for r in repo.list_roots(library.conn())]
        try:
            found = discover_sources(library.definitions, registered_roots=registered)
        except Exception:  # a convenience, as in the window; adding folders by hand still works
            found = []
        return [{"path": f.path, "name": f.name, "via": f.via, "type_id": f.type_id, "confidence": f.confidence,
                 "signals": list(f.signals), "registered": f.registered} for f in found]

    @app.get(prefix + "/environments/mo2-profiles", response_model=models.Mo2Profiles, dependencies=[api],
             responses=errors, tags=["environments"])
    def get_mo2_profiles(folder: str = Query(description="An MO2 instance folder")) -> dict:
        """An MO2 instance's profiles and the one it has selected (folder names and its ini only)."""
        names, selected = mo2_profiles(folder)
        return {"profiles": names, "selected": selected}

    @app.get(prefix + "/environments/{env_id}", response_model=models.EnvironmentDetail, dependencies=[api],
             responses=errors, tags=["environments"])
    def get_environment(env_id: int) -> dict:
        """One environment with its roots and settings."""
        conn = library.conn()
        env = repo.get_environment(conn, env_id)
        if env is None:
            raise HTTPException(404, f"no environment {env_id}")
        roots = repo.list_roots(conn, env_id)
        statuses = {r["status"] for r in roots}
        return {**{k: env[k] for k in ("id", "uid", "name", "type_id", "added_at", "last_scanned_at")},
                "status": "online" if statuses == {"online"} else "offline" if statuses == {"offline"} else "partial",
                "roots": [{"id": r["id"], "path": r["path"], "status": r["status"], "offline_since": r["offline_since"]}
                          for r in roots],
                "user_config": json.loads(env["user_config"]), "layer_config": json.loads(env["layer_config"])}

    @app.post(prefix + "/environments/register", response_model=models.Registered, dependencies=[api],
              responses=busy, tags=["environments"])
    def register_environments(body: models.RegisterEnvironments) -> dict:
        """Add environments (the wizard's third step): their roots and settings, and the folders never to
        index. Nothing is read from them until they are scanned (``/jobs/rescan`` with the ids)."""
        jobs.refuse_while_writing()
        definitions = library.definitions
        for plan in body.environments:
            if plan.type_id not in definitions.environments:
                raise HTTPException(400, f"unknown environment type {plan.type_id!r}")
            if not plan.roots:
                raise HTTPException(400, f"{plan.name or plan.type_id} has no folders")
            if plan.config.visibility not in (None, *VISIBILITIES):
                raise HTTPException(400, f"visibility must be one of {', '.join(VISIBILITIES)}")
            for root in plan.roots:
                _folder(root.path)

        def write(curator):
            conn = curator.conn
            out = []
            with repo.transaction(conn):
                for plan in body.environments:
                    env_id = None
                    config = plan.config.model_dump(exclude_none=True)
                    for root in sorted(plan.roots, key=lambda r: len(r.path)):
                        env_id = register_root(conn, definitions, Path(root.path), plan.type_id,
                                               name=(plan.name or "").strip() or None, config=config,
                                               confidence=root.confidence, signals=list(root.signals))
                    env = repo.get_environment(conn, env_id)
                    out.append({"id": env_id, "name": env["name"], "type_id": env["type_id"]})
                for path in body.exclude:
                    set_excluded(conn, Path(path))
            return out

        made = library.editor.run(write)
        watch_roots(library, watcher)
        return {"environments": made}

    @app.post(prefix + "/environments/{env_id}/config", response_model=models.ConfigResult, dependencies=[api],
              responses=busy, tags=["environments"])
    def configure(env_id: int, body: models.EnvironmentConfig) -> dict:
        """Change an environment's settings: the fields given replace the ones it has (``exchange env
        config``). Ignore rules apply from the next rescan."""
        jobs.refuse_while_writing()
        if body.visibility not in (None, *VISIBILITIES):
            raise HTTPException(400, f"visibility must be one of {', '.join(VISIBILITIES)}")
        given = body.model_dump(exclude_unset=True)

        def write(curator):
            conn = curator.conn
            env = repo.get_environment(conn, env_id)
            if env is None:
                raise HTTPException(404, f"no environment {env_id}")
            profile = given.get("mo2_profile")
            profiles = json.loads(env["layer_config"]).get("profiles")
            if profile and profiles is not None and profile not in profiles:
                raise HTTPException(400, f"no MO2 profile {profile!r}; known: {', '.join(profiles) or 'none'}")
            config = repo.user_config(conn, env_id)
            for key, value in given.items():
                if value is None or value == []:
                    config.pop(key, None)
                else:
                    config[key] = value
            with repo.transaction(conn):
                repo.set_user_config(conn, env_id, config)
            return {"user_config": config}

        return library.editor.run(write)

    # Change notices -----------------------------------------------------------------------------

    @app.get(prefix + "/changes", response_model=models.Changes, dependencies=[api], responses=errors,
             tags=["environments"])
    def changes(since: int | None = Query(None, description="The version you have: wait for a newer one"),
                wait: float = Query(0, ge=0, le=MAX_WAIT, description="Seconds to wait for a change")) -> dict:
        """Environments whose roots changed since they were last scanned (``available`` is false without
        ``watchdog``). A rescan of an environment clears it."""
        return watcher.wait(since, wait)


def watch_roots(library, watcher: Watcher) -> None:
    """Watch every online root (after environments are added or scanned)."""
    roots = repo.list_roots(library.conn())
    watcher.watch([(r["path"], r["environment_id"]) for r in roots if r["status"] == "online"])


def after_job(library, watcher: Watcher, job: Job) -> None:
    """A scan clears the change notices of what it scanned, and new roots are watched."""
    if job.kind in ("scan", "rescan") and job.state == "done" and isinstance(job.result, dict):
        scanned = {e["id"] for e in job.result.get("environments", []) if e.get("id") is not None}
        watcher.clear(scanned)
    if job.writes:
        watch_roots(library, watcher)

