"""Bridges to external apps: Blender, Daz Studio and command-line tools (Roadmap phase 4b).

An operation that runs in an app declares it (``@operation(..., app="blender")``) and asks its
context for the bridge::

    result = ctx.bridge("blender").run(script, {"source": str(path), "format": "glb"},
                                       template=None)

Every bridge works the same way, so process authors never manage the apps' OS processes themselves:

1. The arguments go to a JSON file in the step's work folder.
2. A small wrapper is generated: Python inside Blender, or DazScript inside Daz Studio. It
   reads the arguments, runs the process's script, and writes the script's result (or its
   error) to a result file.
3. The app runs with that wrapper and a timeout. Its output goes to a log in the work folder.
4. The result comes back as a dict. A missing result, a reported error or a timeout raises
   BridgeError, quoting the end of the log.

Only one job runs per app at a time, across processes (``locks.Lock("app-<tool>")``); a second
job waits for the first. Command-line tools (texconv, packers) run directly, with arguments and
a timeout.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from exchange.bridges.base import Bridge, BridgeError, CommandBridge
from exchange.bridges.blender import BlenderBridge
from exchange.bridges.daz import DazBridge

__all__ = ["Bridge", "BridgeError", "CommandBridge", "BlenderBridge", "DazBridge", "make_bridge"]

KINDS: dict[str, type[Bridge]] = {"blender": BlenderBridge, "daz_studio": DazBridge}


def make_bridge(app: str, executable: Path, workdir: Path, log: Callable[[str], None]) -> Bridge:
    """The bridge for an app (by tool id): Blender and Daz Studio get their own, anything else
    is a command-line tool."""
    return KINDS.get(app, CommandBridge)(app, Path(executable), Path(workdir), log)
