"""The Exchange service: the core served over a local HTTP API for the desktop shell (Roadmap phase 6).

Optional: it needs the ``service`` extra (``pip install -e ".[service]"``). ``exchange serve`` runs
it; ``create_app`` builds it for tests and other hosts. The API's schema is committed as
``docs/api/openapi.json`` and is the contract with the shell.
"""

API_VERSION = 1
