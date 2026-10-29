"""Operations of the test process that takes a mesh to Daz Studio."""

from exchange.processes.operations import operation


@operation("pass_through", inputs=("Files",), output="Files")
def pass_through(ctx, files):
    """Hand the files on unchanged."""
    return files
