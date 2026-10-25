"""``exchange serve``: the local API the desktop shell's Workspace window reads (Roadmap phase 6)."""

from __future__ import annotations

import argparse
import json

from exchange.errors import ExchangeError

COMMANDS = ("serve",)


def add_parsers(commands, common: argparse.ArgumentParser) -> None:
    serve = commands.add_parser(
        "serve", parents=[common], help="serve the library over a local API (for the desktop shell)",
        description="Serve the library on 127.0.0.1 for the desktop shell. Prints one JSON 'ready' line "
        "with the URL; every /api request needs the token (EXCHANGE_SERVICE_TOKEN, or the one printed).")
    serve.add_argument("--port", type=int, default=0, help="the port to listen on (default: any free port)")
    serve.add_argument("--exit-with-stdin", action="store_true",
                       help="stop when stdin closes (when started by another process)")
    serve.add_argument("--openapi", action="store_true",
                       help="print the API's OpenAPI schema and exit (docs/api/openapi.json)")


def run(args, definitions) -> int:
    try:
        from exchange.service.server import serve
        from exchange.service.schema import openapi_schema
    except ImportError as exc:
        raise ExchangeError(f"the service needs the 'service' extra (pip install -e \".[service]\"): {exc}") from exc
    if args.openapi:
        print(json.dumps(openapi_schema(), indent=2))
        return 0
    serve(args.db, port=args.port, definitions=definitions, threshold=args.threshold,
          exit_with_stdin=args.exit_with_stdin, definition_dirs=tuple(args.definitions))
    return 0
