"""Processes: packages of operations that turn one kind of asset into another (Roadmap phase 4).

``manifest`` reads ``process.toml``; ``operations`` is the API operations are written against;
``core_ops`` holds the operations every process can use; ``registry`` finds, trusts and loads
packages and checks their prerequisites. Requisitions (``exchange.requisitions``) run them.
"""
