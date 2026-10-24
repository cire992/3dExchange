"""Operations of the test process."""

import shutil

from exchange.processes.operations import operation


@operation("review", inputs=("Files",), output="Files")
def review(ctx, images, pause=False):
    """Pause for the user to look at the images (a manual checkpoint)."""
    if pause:
        ctx.checkpoint("look at the shrunken images, then resume")
    ctx.log("reviewed")
    return images


@operation("mark", inputs=("Files",), output="Files")
def mark(ctx, images, note="stamped"):
    """Copy the images and add a note file beside them."""
    out = ctx.new_dir("marked")
    for path, rel in zip(images.paths(), images.files):
        target = out.joinpath(*rel.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    (out / "NOTE.txt").write_text(note, encoding="utf-8")
    return images.derive(out, [*images.files, "NOTE.txt"])
