from pathlib import Path

from exchange.processes.operations import operation

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "make.py"


@operation("make", inputs=("Files",), output="Files", app="blender")
def make(ctx, files, word="hello"):
    """Ask Blender to write a text file naming the source."""
    out = ctx.new_dir("made")
    result = ctx.bridge("blender").run(SCRIPT, {"word": word, "source": str(files.paths()[0]),
                                                "target": str(out / "made.txt")})
    return files.derive(out, [Path(p).name for p in result["files"]])
