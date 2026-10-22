"""Stands in for blender.exe in tests: runs the --python script with this Python (no bpy).

Records its command line in fake_blender_calls.txt beside the arguments file."""

import runpy
import sys
from pathlib import Path

argv = sys.argv[1:]
script = argv[argv.index("--python") + 1]
rest = argv[argv.index("--"):] if "--" in argv else []
Path(rest[1]).with_name("fake_blender_calls.txt").write_text(" ".join(argv), encoding="utf-8")
sys.argv = [script, *rest]
try:
    runpy.run_path(script, run_name="__main__")
except SystemExit as exc:
    sys.exit(exc.code)
