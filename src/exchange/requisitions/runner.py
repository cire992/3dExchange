"""Running the queue: requisitions in order, their items one by one, each item's pipelines step by
step.

* **Work folders:** each requisition gets ``work/<uid>/`` in the data folder for intermediates,
  removed once it is fulfilled. A step's result is cached there by (operation, inputs,
  parameters), so an operation shared by several items of a product runs once, and resuming
  after a checkpoint does not redo finished steps.
* **Logs:** one per item in ``logs/<uid>/``, kept.
* **Checkpoints:** a step can pause for the user (``ctx.checkpoint``). The item, then the
  requisition, needs attention; resuming runs that step again with ``ctx.resuming`` true.
* **Writing:** only into the endpoint folder. A file already there is a collision: by default
  the item stops and asks; otherwise it is overwritten (the old file goes to the recycle
  folder), renamed or skipped. Every write is recorded, so the output can be removed cleanly.
* **Chains:** each pipeline's result is written. An intermediate one goes to its own
  environment (G8 in Daz, usable there too), the last one to the requisition's endpoint.
* **Afterwards:** the sidecar manifest is written next to the output, the endpoint folder
  becomes a root of its environment if it is not one yet, and it is rescanned, so the new
  entries show up as requisitioned from their source.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import threading
import traceback
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from exchange.db import open_library
from exchange.db import repository as repo
from exchange.definitions.schema import DefinitionSet
from exchange.errors import ExchangeError
from exchange.locks import Lock
from exchange.paths import data_dir, fold, is_within, rel_under
from exchange.pipelines.manifest import step_params
from exchange.pipelines.operations import Artifact, Checkpoint, Context, OperationError, accepts
from exchange.pipelines.registry import PipelinePackage, Registry, check_prerequisites, ready, resolve_tool
from exchange.requisitions.endpoints import Endpoint, default_endpoint
from exchange.requisitions.sidecars import write_sidecar

Progress = Callable[[dict], None]


class RequisitionError(ExchangeError):
    pass


def work_dir(uid: str) -> Path:
    return data_dir() / "work" / uid


def log_path(uid: str, item_id: int) -> Path:
    return data_dir() / "logs" / uid / f"item-{item_id}.log"


def recycle_path(uid: str, path: Path) -> Path:
    """Where a file Exchange replaces or removes goes: never deleted, only moved here."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    drive_less = Path(*Path(path).resolve().parts[1:])
    return data_dir() / "recycle" / uid / stamp / drive_less


def recycle(uid: str, path: Path) -> Path:
    target = recycle_path(uid, path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():  # the same file twice in one second
        target = target.with_name(f"{target.stem}.{datetime.now().microsecond}{target.suffix}")
    shutil.move(str(path), target)
    return target


class _Log:
    def __init__(self, path: Path, progress: Progress | None, base: dict) -> None:
        self.path, self.progress, self.base = path, progress, base
        path.parent.mkdir(parents=True, exist_ok=True)

    def __call__(self, step: str, message: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        with self.path.open("a", encoding="utf-8") as f:
            f.write(f"{stamp} [{step}] {message}\n")
        if self.progress is not None:
            self.progress({**self.base, "step": step, "message": message})


def run_queue(db_path: Path, definitions: DefinitionSet, registry: Registry, *,
              only: list[int] | None = None, progress: Progress | None = None,
              cancel: threading.Event | None = None, tools: dict[str, str] | None = None,
              rescan: bool = True) -> list[int]:
    """Run queued requisitions (all, or ``only`` these) in queue order; returns those run.

    One worker at a time: a second one raises LockBusy."""
    with Lock("queue"):
        conn = open_library(db_path)
        try:
            # A worker that died mid-run left its requisition running: it runs again.
            conn.execute("UPDATE requisition SET state = 'queued' WHERE state = 'running'")
            conn.execute("UPDATE requisition_item SET state = 'queued' WHERE state = 'running'")
            ran: list[int] = []
            while not (cancel is not None and cancel.is_set()):
                queued = [r[0] for r in conn.execute("SELECT id FROM requisition WHERE state = 'queued' ORDER BY position")]
                # Each runs once per call: one that stops again (cancelled) waits for the next run.
                pick = next((i for i in queued if i not in ran and (only is None or i in only)), None)
                if pick is None:
                    break
                req = conn.execute("SELECT * FROM requisition WHERE id = ?", (pick,)).fetchone()
                _run_requisition(conn, Path(db_path), definitions, registry, req, progress, cancel, tools, rescan)
                ran.append(req["id"])
            return ran
        finally:
            conn.close()


def _run_requisition(conn, db_path, definitions, registry, req, progress, cancel, tools, rescan) -> None:
    conn.execute("UPDATE requisition SET state = 'running', started_at = ?, message = NULL WHERE id = ?",
                 (repo.now(), req["id"]))
    items = conn.execute("SELECT * FROM requisition_item WHERE requisition_id = ? AND include = 1"
                         " AND state IN ('queued', 'running') ORDER BY id", (req["id"],)).fetchall()
    wrote = False
    for n, item in enumerate(items, start=1):
        if cancel is not None and cancel.is_set():
            break
        conn.execute("UPDATE requisition_item SET state = 'running', message = NULL WHERE id = ?", (item["id"],))
        name = conn.execute("SELECT name FROM dossier_effective WHERE uid = ?", (item["dossier_uid"],)).fetchone()
        log = _Log(log_path(req["uid"], item["id"]), progress,
                   {"event": "progress", "requisition": req["name"], "item": name[0] if name else item["dossier_uid"],
                    "done": n - 1, "total": len(items)})
        try:
            outcome, detail = _run_item(conn, definitions, registry, req, item, log, tools)
        except (ExchangeError, OSError) as exc:
            outcome, detail = "failed", str(exc)
            log("error", detail)
        except Exception as exc:  # a pipeline's own bug: the item fails, the queue goes on
            outcome, detail = "failed", f"{type(exc).__name__}: {exc}"
            log("error", traceback.format_exc())
        state = {"done": "done", "attention": "needs_attention", "failed": "failed"}[outcome]
        conn.execute("UPDATE requisition_item SET state = ?, message = ? WHERE id = ?",
                     (state, None if outcome == "done" else detail, item["id"]))
        wrote |= outcome == "done"

    states = [r[0] for r in conn.execute("SELECT state FROM requisition_item WHERE requisition_id = ? AND include = 1",
                                         (req["id"],))]
    attention = conn.execute("SELECT message FROM requisition_item WHERE requisition_id = ? AND state = 'needs_attention'"
                             " ORDER BY id LIMIT 1", (req["id"],)).fetchone()
    if attention is not None:
        final, message = "needs_attention", attention[0]
    elif states and all(s == "done" for s in states):
        final, message = "fulfilled", None
    elif "queued" in states:
        final, message = "queued", "stopped before it finished"
    elif "done" in states:
        final, message = "partially_fulfilled", "some items failed; retry them with resume"
    else:
        final, message = "failed", (conn.execute("SELECT message FROM requisition_item WHERE requisition_id = ?"
                                                 " AND state = 'failed' ORDER BY id LIMIT 1", (req["id"],)).fetchone()
                                    or [None])[0]
    if wrote:
        roots = _write_sidecars(conn, req)
        if rescan:
            _rescan(conn, db_path, definitions, roots)
    conn.execute("UPDATE requisition SET state = ?, message = ?, finished_at = ? WHERE id = ?",
                 (final, message, repo.now() if final != "queued" else None, req["id"]))
    if final == "fulfilled":
        shutil.rmtree(work_dir(req["uid"]), ignore_errors=True)


# One item -------------------------------------------------------------------------------------


def _state_file(req_uid: str, item_id: int) -> Path:
    return work_dir(req_uid) / f"item-{item_id}" / "state.json"


def _load_state(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"pipeline": 0, "step": 0, "resume": False, "artifacts": {}, "outputs": []}


def _save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state), encoding="utf-8")


def dossier_info(conn: sqlite3.Connection, uid: str) -> dict:
    row = conn.execute("SELECT uid, name, type_id FROM dossier_effective WHERE uid = ?", (uid,)).fetchone()
    if row is None:
        raise RequisitionError(f"the asset {uid} is no longer in the library")
    fields = repo.effective_fields(conn, uid)
    return {"uid": row["uid"], "name": row["name"], "type_id": row["type_id"],
            "variant": str(fields.get("variant") or ""), "fields": fields}


def source_artifact(conn: sqlite3.Connection, entry_id: int, artifact_type: str) -> tuple[Artifact, str]:
    """An entry's files as an artifact laid out as in its container, and their fingerprint."""
    rows = conn.execute(
        "SELECT f.rel_path, f.rel_key, f.size, f.mtime_ns, f.hash, f.state, r.path AS root_path,"
        " c.rel_path AS container_rel, e.status FROM entry e JOIN entry_file ef ON ef.entry_id = e.id"
        " JOIN file f ON f.id = ef.file_id JOIN environment_root r ON r.id = f.root_id"
        " LEFT JOIN container c ON c.id = e.container_id WHERE e.id = ? ORDER BY ef.role != 'primary', f.rel_key",
        (entry_id,)).fetchall()
    if not rows:
        raise RequisitionError(f"entry {entry_id} has no files (is it still in the library?)")
    if rows[0]["status"] == "retired":
        raise RequisitionError(f"entry {entry_id} is no longer on disk")
    container = rows[0]["container_rel"] or ""
    base = Path(rows[0]["root_path"]).joinpath(*container.split("/")) if container else Path(rows[0]["root_path"])
    files = []
    for r in rows:
        rel = (rel_under(r["rel_path"], container) if container else r["rel_path"]) or r["rel_path"]
        if not base.joinpath(*rel.split("/")).is_file():
            raise RequisitionError(f"source file missing: {base / rel}")
        files.append(rel)
    digest = hashlib.sha1(json.dumps([[r["rel_key"], r["size"], r["mtime_ns"], r["hash"]] for r in rows]).encode())
    return Artifact(artifact_type, base, files, {"entry": entry_id}), digest.hexdigest()


def source_fingerprint(conn: sqlite3.Connection, entry_id: int) -> str | None:
    try:
        return source_artifact(conn, entry_id, "Files")[1]
    except RequisitionError:
        return None


def _chain(registry: Registry, pipelines: list[dict], tools) -> list[PipelinePackage]:
    chain = []
    for p in pipelines:
        package = registry.get(p["id"])
        if package.manifest.version != p["version"]:
            raise RequisitionError(f"pipeline {package.id} changed from {p['version']} to {package.manifest.version} "
                                   "since this was planned; plan it again")
        if not ready(package, tools):
            red = [s for s in check_prerequisites(package, tools) if not s.ok]
            raise RequisitionError(f"pipeline {package.id} is not ready"
                                   + (f": {red[0].label}: {red[0].detail}" if red else " (not trusted, or its steps are invalid)"))
        chain.append(package)
    return chain


def _run_item(conn, definitions, registry, req, item, log: _Log, tools) -> tuple[str, object]:
    chain = _chain(registry, json.loads(item["pipelines"]), tools)
    params = json.loads(item["params"])
    dossier = dossier_info(conn, item["dossier_uid"])
    source, digest = source_artifact(conn, item["source_entry_id"], chain[0].manifest.input_artifact)
    conn.execute("UPDATE requisition_item SET source_fingerprint = ? WHERE id = ?", (digest, item["id"]))
    endpoint = Endpoint.from_json(req["endpoint"])
    state_path = _state_file(req["uid"], item["id"])
    state = _load_state(state_path)
    current = Artifact.from_json(state["chain"]) if state.get("chain") else source
    log("start", f"{dossier['name']}: {' → '.join(p.id for p in chain)} from entry {item['source_entry_id']}")

    for pi in range(state["pipeline"], len(chain)):
        package = chain[pi]
        manifest = package.manifest
        values = manifest.resolve(params.get(package.id, {}))
        produced = {"source": current}
        start = state["step"] if pi == state["pipeline"] else 0
        for si, step in enumerate(manifest.steps):
            if si < start:
                produced[step.id] = Artifact.from_json(state["artifacts"][f"{pi}.{step.id}"])
                continue
            spec = package.operation(step.operation)
            inputs = [produced[name] for name in step.inputs]
            resuming = bool(state.get("resume")) and pi == state["pipeline"] and si == start
            try:
                result = _run_step(req["uid"], package, step, spec, inputs, step_params(step, values, dossier),
                                   dossier, log, resuming, tools)
            except Checkpoint as cp:
                state.update(pipeline=pi, step=si, resume=False)
                _save_state(state_path, state)
                log(step.id, f"waiting for you: {cp.message}")
                return "attention", cp.message
            produced[step.id] = result
            state["artifacts"][f"{pi}.{step.id}"] = result.to_json()
        current = produced[manifest.steps[-1].id]

        last = pi == len(chain) - 1
        target = endpoint if last else _intermediate_endpoint(conn, definitions, manifest, source, req)
        if target is None:
            log("write", f"{package.id}: no {manifest.output_environment} environment for the intermediate result; "
                         "not saved")
        else:
            folder = _fill(manifest.output_folder, values, dossier)
            written, collisions = _write(conn, req, item["id"], target, current, folder, log)
            if collisions:
                state.update(pipeline=pi, step=len(manifest.steps), resume=False, chain=None)
                _save_state(state_path, state)
                shown = ", ".join(str(c) for c in collisions[:3]) + (" …" if len(collisions) > 3 else "")
                return "attention", (f"{len(collisions)} file(s) already exist at the endpoint ({shown}); "
                                     "resume with overwrite, rename or skip")
            state["outputs"].append({
                "endpoint": target.folder, "root": target.root, "environment_id": target.environment_id,
                "pipeline": package.id, "version": manifest.version, "status": manifest.entry_status,
                "type_id": manifest.output_dossier_type or dossier["type_id"], "files": written})
        state.update(pipeline=pi + 1, step=0, resume=False, chain=current.to_json())
        _save_state(state_path, state)
    conn.execute("UPDATE requisition_item SET outputs = ? WHERE id = ?", (json.dumps(state["outputs"]), item["id"]))
    log("done", f"wrote {sum(len(o['files']) for o in state['outputs'])} files")
    return "done", state["outputs"]


def _fill(template: str, values: dict, dossier: dict) -> str:
    names = {"name": dossier["name"], "variant": dossier["variant"], "type_id": dossier["type_id"], **values}
    try:
        return template.format_map(names).strip("/")
    except (KeyError, ValueError) as exc:
        raise RequisitionError(f"bad output folder {template!r}: {exc}") from exc


def bridges_for(package: PipelinePackage, tools, workdir: Path, log: Callable[[str], None]):
    """What ``ctx.bridge(app)`` returns for a package's step: the bridge to that app, at the path
    its prerequisite resolves to."""
    def get(app: str):
        from exchange.bridges import make_bridge

        path = resolve_tool(package, app, tools)
        if path is None:
            raise OperationError(f"{app} is not set up; set it with: exchange tools set {app} PATH")
        return make_bridge(app, Path(path), workdir / f"bridge-{app}", log)
    return get


def _run_step(req_uid, package, step, spec, inputs, params, dossier, log: _Log, resuming: bool,
              tools=None) -> Artifact:
    key = hashlib.sha1(json.dumps([package.id, package.manifest.version, step.operation,
                                   [a.fingerprint() for a in inputs], params], sort_keys=True, default=str).encode())
    folder = work_dir(req_uid) / "cache" / key.hexdigest()[:20]
    marker = folder / "artifact.json"
    if marker.is_file() and not resuming:
        log(step.id, f"{step.operation}: reused an earlier result")
        return Artifact.from_json(json.loads(marker.read_text(encoding="utf-8")))
    say = lambda message: log(step.id, message)  # noqa: E731
    ctx = Context(folder / "work", dossier, say, resuming=resuming,
                  bridges=bridges_for(package, tools, folder / "work", say))
    log(step.id, f"{step.operation} {params}" if params else step.operation)
    result = spec.func(ctx, *inputs, **params)
    if not isinstance(result, Artifact):
        raise OperationError(f"{step.operation} returned {type(result).__name__}, not an Artifact")
    if not accepts(spec.output, result.type):
        raise OperationError(f"{step.operation} should make {spec.output}, made {result.type}")
    folder.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps(result.to_json()), encoding="utf-8")
    return result


def test_pipeline(conn: sqlite3.Connection, folder: Path, uid: str, out_dir: Path,
                  values: dict | None = None, source_entry_id: int | None = None,
                  log: Callable[[str, str], None] | None = None) -> list[Path]:
    """Run a pipeline package (from its folder, not installed) on one asset into ``out_dir``: the
    test harness. Nothing is written to the library or the asset's environments.

    Testing your own package means running its code, so it is trusted for this run."""
    from exchange.pipelines.manifest import load_manifest
    from exchange.pipelines.registry import fingerprint, validate

    folder = Path(folder).resolve()
    package = PipelinePackage(load_manifest(folder / "pipeline.toml"), folder, False, True, fingerprint(folder))
    problems = validate(package)
    if problems:
        raise RequisitionError("; ".join(problems))
    dossier = dossier_info(conn, uid)
    if source_entry_id is None:
        row = conn.execute("SELECT e.id FROM entry e JOIN ledger l ON l.id = e.ledger_id JOIN dossier d ON d.id = l.dossier_id"
                           " WHERE d.uid = ? AND e.status != 'retired' ORDER BY e.status != 'origin', e.id LIMIT 1",
                           (uid,)).fetchone()
        if row is None:
            raise RequisitionError(f"{dossier['name']} has no entry to start from")
        source_entry_id = row[0]
    manifest = package.manifest
    resolved = manifest.resolve(values or {})
    log = log or (lambda step, message: None)
    produced = {"source": source_artifact(conn, source_entry_id, manifest.input_artifact)[0]}
    work = Path(out_dir) / "_work"
    for step in manifest.steps:
        spec = package.operation(step.operation)
        params = step_params(step, resolved, dossier)
        log(step.id, f"{step.operation} {params}" if params else step.operation)
        say = lambda message, s=step.id: log(s, message)  # noqa: E731
        ctx = Context(work / step.id, dossier, say, resuming=True,
                      bridges=bridges_for(package, None, work / step.id, say))
        result = spec.func(ctx, *[produced[name] for name in step.inputs], **params)
        if not isinstance(result, Artifact) or not accepts(spec.output, result.type):
            raise OperationError(f"{step.operation} should make an Artifact of type {spec.output}")
        produced[step.id] = result
    final = produced[manifest.steps[-1].id]
    target = Path(out_dir) / "output" / _fill(manifest.output_folder, resolved, dossier)
    written = []
    for src, rel in zip(final.paths(), final.files):
        dest = target.joinpath(*rel.split("/"))
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        written.append(dest)
    log("done", f"{len(written)} files in {target}")
    return written


def _intermediate_endpoint(conn, definitions, manifest, source: Artifact, req) -> Endpoint | None:
    """Where an intermediate result of a chain goes: the default endpoint of an environment of
    the pipeline's output type (None if the library has none)."""
    env_type = manifest.output_environment
    if env_type == "same":
        row = conn.execute("SELECT l.environment_id FROM entry e JOIN ledger l ON l.id = e.ledger_id WHERE e.id = ?",
                           (source.meta.get("entry"),)).fetchone()
        env_id = row[0] if row else None
    else:
        row = conn.execute("SELECT id FROM environment WHERE type_id = ? ORDER BY id LIMIT 1", (env_type,)).fetchone()
        env_id = row[0] if row else None
    if env_id is None:
        return None
    return default_endpoint(conn, definitions, env_id, req["name"])


def _free_name(path: Path) -> Path:
    for n in range(2, 10_000):
        candidate = path.with_name(f"{path.stem} ({n}){path.suffix}")
        if not candidate.exists():
            return candidate
    raise RequisitionError(f"no free name for {path}")


def _write(conn, req, item_id: int, endpoint: Endpoint, artifact: Artifact, folder: str,
           log: _Log) -> tuple[list[str], list[Path]]:
    """Copy an artifact's files into the endpoint; (written paths relative to the endpoint folder,
    collisions when the policy is to ask)."""
    base = Path(endpoint.folder).resolve()
    target = base.joinpath(*folder.split("/")) if folder else base
    pairs = []
    for src, rel in zip(artifact.paths(), artifact.files):
        dest = target.joinpath(*rel.split("/")).resolve()
        if not is_within(dest, base):
            raise RequisitionError(f"{rel} would be written outside the endpoint {base}")
        if not src.is_file():
            raise RequisitionError(f"{src} is missing (the pipeline did not make it)")
        pairs.append((src, dest))
    policy = req["on_collision"]
    # Files this requisition already wrote (a product and its child share files) are not collisions.
    ours = {fold(r[0]) for r in conn.execute("SELECT path FROM requisition_write WHERE requisition_id = ?"
                                             " AND removed_at IS NULL", (req["id"],))}
    collisions = [dest for _, dest in pairs if dest.exists() and fold(str(dest)) not in ours]
    if collisions and policy == "ask":
        return [], collisions
    written = []
    for src, dest in pairs:
        action, recycled = "created", None
        if fold(str(dest)) in ours:
            written.append(dest.relative_to(base).as_posix())
            continue
        if dest.exists():
            if policy == "skip":
                log("write", f"skipped {dest} (already there)")
                continue
            if policy == "rename":
                dest = _free_name(dest)
            else:
                recycled = str(recycle(req["uid"], dest))
                action = "overwritten"
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        conn.execute("INSERT INTO requisition_write (requisition_id, item_id, path, action, recycled_to, written_at)"
                     " VALUES (?, ?, ?, ?, ?, ?)", (req["id"], item_id, str(dest), action, recycled, repo.now()))
        written.append(dest.relative_to(base).as_posix())
    log("write", f"{len(written)} files into {base}")
    return written, []


def _write_sidecars(conn, req) -> list[tuple[int, str]]:
    """Write the requisition's sidecar in every container it wrote to; returns (environment, root)."""
    by_folder: dict[str, list[dict]] = {}
    roots: dict[str, tuple[int, str]] = {}
    for item in conn.execute("SELECT * FROM requisition_item WHERE requisition_id = ? AND state = 'done'",
                             (req["id"],)):
        d = conn.execute("SELECT name, type_id FROM dossier_effective WHERE uid = ?", (item["dossier_uid"],)).fetchone()
        source = conn.execute(
            "SELECT v.name AS environment, c.name AS container FROM entry e JOIN ledger l ON l.id = e.ledger_id"
            " JOIN environment v ON v.id = l.environment_id LEFT JOIN container c ON c.id = e.container_id"
            " WHERE e.id = ?", (item["source_entry_id"],)).fetchone()
        for out in json.loads(item["outputs"] or "[]"):
            by_folder.setdefault(out["endpoint"], []).append({
                "dossier": item["dossier_uid"], "name": d["name"] if d else "", "type_id": out["type_id"],
                "status": out["status"],
                "source": {"entry": item["source_entry_id"], **(dict(source) if source else {})},
                "pipelines": [{"id": out["pipeline"], "version": out["version"]}],
                "params": json.loads(item["params"]).get(out["pipeline"], {}), "files": out["files"]})
            roots[out["endpoint"]] = (out["environment_id"], out["root"])
    for folder, outputs in by_folder.items():
        path = write_sidecar(Path(folder), {"requisition": req["uid"], "name": req["name"],
                                            "written_at": repo.now(), "outputs": outputs})
        if not conn.execute("SELECT 1 FROM requisition_write WHERE requisition_id = ? AND path = ?",
                            (req["id"], str(path))).fetchone():
            conn.execute("INSERT INTO requisition_write (requisition_id, path, action, written_at) VALUES (?, ?, 'sidecar', ?)",
                         (req["id"], str(path), repo.now()))
    return list(dict.fromkeys(roots.values()))


def _rescan(conn, db_path: Path, definitions: DefinitionSet, roots: list[tuple[int, str]]) -> None:
    """Make each endpoint's root a root of its environment (if new) and rescan it, so the output
    becomes entries (read back from the sidecars)."""
    from exchange.environments import register_root
    from exchange.scanner.scan import run_scan

    for environment_id, root in roots:
        if repo.find_root(conn, fold(str(Path(root).resolve()))) is None:
            env = repo.get_environment(conn, environment_id)
            with repo.transaction(conn):
                register_root(conn, definitions, Path(root), env["type_id"])
        run_scan(Path(root), db_path=db_path, definitions=definitions)
