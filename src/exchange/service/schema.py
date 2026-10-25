"""The API's OpenAPI schema, as committed in ``docs/api/openapi.json`` (the contract with the shell).

``exchange serve --openapi`` prints it; a test fails when the committed copy is out of date.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from exchange.service.app import create_app


def openapi_schema() -> dict:
    """The schema of the app as it would be served (built against a throwaway empty library)."""
    with tempfile.TemporaryDirectory() as folder:
        app = create_app(Path(folder) / "library.db", token="schema", watch=False)
        schema = app.openapi()
        app.state.library.close()
    schema["components"]["securitySchemes"] = {"token": {"type": "http", "scheme": "bearer",
                                                          "description": "The service's per-launch token"}}
    for path, operations in schema["paths"].items():
        if path.startswith("/api/"):
            for operation in operations.values():
                operation["security"] = [{"token": []}]
    return schema
