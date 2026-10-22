"""Operations: the smallest reusable steps of a pipeline.

An operation is a Python function taking a context and input artifacts and returning one artifact::

    @operation("resize_images", inputs=("Images",), output="Images")
    def resize_images(ctx, images, size=1024):
        out = ctx.new_dir()
        ...
        return images.derive(out, files, type="Images")

An **artifact** is a typed set of files laid out under a folder (``root`` plus "/"-separated
paths), so a Daz product's ``People/.../Item.duf`` layout survives the whole chain. Types are
names ("Files", "Images", "DazWearable"); "Files" accepts any artifact. Declared types let
Exchange check a pipeline's chain before it runs.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from exchange.errors import ExchangeError

ANY = "Files"


class OperationError(ExchangeError):
    """An operation could not do its work (bad input, a tool failed); the item fails."""


class Checkpoint(Exception):
    """Raised by ``ctx.checkpoint()``: the item waits for the user, then the step runs again."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass
class Artifact:
    type: str
    root: Path
    files: list[str]  # relative to root, "/"-separated
    meta: dict[str, Any] = field(default_factory=dict)

    def paths(self) -> list[Path]:
        return [self.root.joinpath(*rel.split("/")) for rel in self.files]

    def derive(self, root: Path, files: list[str], *, type: str | None = None, **meta: Any) -> Artifact:
        """A new artifact made from this one (keeping its metadata unless replaced)."""
        return Artifact(type or self.type, Path(root), list(files), {**self.meta, **meta})

    def to_json(self) -> dict:
        return {"type": self.type, "root": str(self.root), "files": self.files, "meta": self.meta}

    @staticmethod
    def from_json(data: dict) -> Artifact:
        return Artifact(data["type"], Path(data["root"]), list(data["files"]), dict(data.get("meta", {})))

    def fingerprint(self) -> str:
        """What the files are now (paths, sizes, times), for caching shared steps."""
        parts = [self.type, str(self.root)]
        for path, rel in zip(self.paths(), self.files):
            try:
                stat = path.stat()
                parts.append(f"{rel}:{stat.st_size}:{stat.st_mtime_ns}")
            except OSError:
                parts.append(f"{rel}:missing")
        return json.dumps(parts)


@dataclass(frozen=True)
class OperationSpec:
    name: str
    func: Callable[..., Artifact]
    inputs: tuple[str, ...]
    output: str
    app: str | None = None  # the external app it runs in (a bridge), if any
    description: str = ""


def operation(name: str, *, inputs: tuple[str, ...] = (ANY,), output: str = ANY, app: str | None = None):
    """Declare a function as an operation (name, input and output artifact types, app)."""

    def wrap(func: Callable[..., Artifact]) -> Callable[..., Artifact]:
        func.__exchange_operation__ = OperationSpec(  # type: ignore[attr-defined]
            name, func, tuple(inputs), output, app, (func.__doc__ or "").strip().split("\n")[0])
        return func

    return wrap


def accepts(wanted: str, given: str) -> bool:
    """Whether an operation wanting ``wanted`` can take an artifact of type ``given``."""
    return wanted == ANY or wanted == given


class Context:
    """What an operation gets besides its inputs: a work folder, the dossier, logging, checkpoints."""

    def __init__(self, workdir: Path, dossier: dict, log: Callable[[str], None], *,
                 resuming: bool = False, bridges: Callable[[str], Any] | None = None) -> None:
        self.workdir = Path(workdir)
        self.dossier = dossier  # name, uid, type_id, variant, fields
        self._log = log
        self.resuming = resuming
        self._bridges = bridges

    def new_dir(self, name: str = "out") -> Path:
        path = self.workdir / name
        path.mkdir(parents=True, exist_ok=True)
        return path

    def log(self, message: str) -> None:
        self._log(message)

    def checkpoint(self, message: str) -> None:
        """Pause for the user (e.g. "touch up the weights in Blender, then Resume"). When the
        user resumes, the step runs again and this returns at once."""
        if not self.resuming:
            raise Checkpoint(message)

    def bridge(self, app: str) -> Any:
        """The bridge to an external app (Blender, Daz Studio, a command-line tool)."""
        if self._bridges is None:
            raise OperationError(f"no bridge to {app} is available here")
        return self._bridges(app)
