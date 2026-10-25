"""Running the service: ``exchange serve``.

It binds 127.0.0.1 itself (``--port 0`` picks a free port), starts listening, then prints one JSON
line on stdout for the process that started it:

    {"event": "ready", "url": "http://127.0.0.1:52144", "api": 1, "version": "0.1.0", "token": "…"}

The token is the per-launch secret every ``/api`` request must carry. The desktop shell passes its
own in ``EXCHANGE_SERVICE_TOKEN``; without one, the service makes one and prints it in the ready
line (stdout is the parent's private pipe). With ``--exit-with-stdin`` the service stops when its
stdin closes, so it never outlives the shell that started it.
"""

from __future__ import annotations

import json
import os
import secrets
import socket
import sys
import threading
from pathlib import Path

import uvicorn

from exchange import __version__
from exchange.definitions import DefinitionSet
from exchange.errors import ExchangeError
from exchange.service import API_VERSION
from exchange.service.app import create_app

TOKEN_ENV = "EXCHANGE_SERVICE_TOKEN"
LOOPBACK = "127.0.0.1"


def serve(db_path: Path, *, port: int = 0, definitions: DefinitionSet | None = None, threshold: float,
          exit_with_stdin: bool = False, out=None, definition_dirs: tuple[Path, ...] = ()) -> None:
    out = out or sys.stdout
    given = os.environ.get(TOKEN_ENV, "").strip()
    token = given or secrets.token_urlsafe(32)
    app = create_app(db_path, token=token, definitions=definitions, threshold=threshold,
                     definition_dirs=definition_dirs)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):  # Windows: no other process may share the port
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        sock.bind((LOOPBACK, port))
        sock.listen(128)
    except OSError as exc:
        sock.close()
        raise ExchangeError(f"the service could not listen on {LOOPBACK}:{port}: {exc}") from exc
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", access_log=False, lifespan="off"))
    url = f"http://{LOOPBACK}:{sock.getsockname()[1]}"
    ready = {"event": "ready", "url": url, "api": API_VERSION, "version": __version__}
    if not given:
        ready["token"] = token
    print(json.dumps(ready), file=out, flush=True)
    if exit_with_stdin:
        def watch() -> None:
            for _ in sys.stdin:
                pass
            server.should_exit = True
        threading.Thread(target=watch, name="stdin-watch", daemon=True).start()
    try:
        server.run(sockets=[sock])
    finally:
        app.state.library.close()  # stops running jobs: no worker outlives the service
