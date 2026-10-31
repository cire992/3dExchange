"""Operations of a test process that reads a few file types."""

from exchange.processes.operations import operation


@operation("pass_through", inputs=("Files",), output="Files")
def pass_through(ctx, files):
    """Hand the files on unchanged."""
    return files
