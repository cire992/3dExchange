"""Runs "inside Blender" (in tests: the stand-in, plain Python)."""

from pathlib import Path


def run(args):
    if args["word"] == "boom":
        raise RuntimeError("the script failed on purpose")
    target = Path(args["target"])
    target.write_text(f"{args['word']} from {Path(args['source']).name}", encoding="utf-8")
    return {"files": [str(target)]}
