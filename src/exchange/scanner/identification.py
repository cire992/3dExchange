"""Scan phase 2, identification, for one root of an environment.

The environment's layer handler names containers and products. The engine then:

* makes a product dossier for each product, and a child dossier for each member file that a
  dossier-type rule recognizes;
* makes a standalone dossier for each recognized file that no product claims (by a type rule, or
  because the layer identified it itself, like a Daz saved character);
* records every dossier's presence as an entry (in a ledger for this environment) with its files;
* retires entries of this root whose files are gone, so history is kept.

Dossiers are matched across rescans by their entry's (container, identity key), so a dossier keeps
its uid, and with it the user's overrides, for as long as its files stay in place. Products that
share a product key (a Daz SKU installed through both DIM and Daz Connect) become one dossier with
an entry per container.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from exchange.db import repository as repo
from exchange.definitions.schema import DefinitionSet, EnvironmentDefinition
from exchange.globs import any_match
from exchange.lexicons import with_generated
from exchange.links import apply_file_links, linked_keys
from exchange.requisitions.sidecars import apply_sidecars, is_sidecar, read_sidecars, sidecar_keys
from exchange.paths import fold, rel_under
from exchange.scanner.layers import HANDLERS
from exchange.scanner.layers.base import ChildSpec, FileInfo, LayerContext
from exchange.scanner.tokenize import tokenize

# Packed archives are indexed by name only; extraction is a user action (Roadmap phase 5).
ARCHIVE_EXTS = frozenset({".bsa", ".ba2", ".pcc", ".gma", ".var"})


@dataclass
class IdentifyStats:
    containers: int = 0
    products: int = 0
    dossiers: int = 0
    below_threshold: int = 0
    unattached_files: int = 0
    ignored_files: int = 0
    archives: int = 0
    retired_entries: int = 0
    layer_config: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


@dataclass
class _Spec:
    key: str
    type_id: str
    name: str
    confidence: float
    signals: list[str]
    container_id: int
    primary: list[FileInfo]
    support: list[FileInfo] = field(default_factory=list)
    fields: dict[str, Any] = field(default_factory=dict)
    parent_id: int | None = None
    product_key: str | None = None


class _Writer:
    """Persists specs for one root and remembers what it touched."""

    def __init__(self, conn: sqlite3.Connection, environment_id: int, handler: str,
                 definitions: DefinitionSet) -> None:
        self.conn, self.environment_id, self.handler = conn, environment_id, handler
        self.definitions = definitions
        self.seen_entries: set[int] = set()
        self.dossiers: set[int] = set()

    def persist(self, spec: _Spec) -> int:
        conn = self.conn
        existing = repo.find_entry(conn, spec.container_id, spec.key)
        values = dict(type_id=spec.type_id, name=spec.name, parent_id=spec.parent_id,
                      confidence=spec.confidence, signals=spec.signals)
        if existing is not None:
            dossier_id, entry_id = existing["dossier_id"], existing["id"]
            if existing["status"] == "retired":
                repo.revive_entry(conn, entry_id, "origin")
            if existing["moved_from"] and repo.has_home_entry(conn, dossier_id):
                # Moved onto this dossier by a merge (the user's, or a duplicate's): the dossier's
                # own entries decide its name and type.
                values = None
            if values is not None:
                self._update(dossier_id, values, own_entry=True)
        else:
            dossier_id = repo.find_product_by_key(conn, self.environment_id, spec.product_key) \
                if spec.product_key else None
            if dossier_id is None:
                dossier_id = repo.create_dossier(conn, **values)
            else:
                self._update(dossier_id, values, own_entry=False)
            ledger_id = repo.ensure_ledger(conn, dossier_id, self.environment_id)
            entry_id = repo.create_entry(conn, ledger_id=ledger_id, container_id=spec.container_id,
                                         identity_key=spec.key)
        repo.replace_entry_files(
            conn, entry_id,
            [(f.id, "primary") for f in spec.primary] + [(f.id, "support") for f in spec.support],
        )
        fields = dict(spec.fields)
        if spec.product_key:
            fields["product_key"] = spec.product_key
        repo.replace_scanned_fields(conn, dossier_id, f"scan:{self.handler}:{spec.container_id}", fields)
        repo.replace_tokens(conn, dossier_id, tokenize(repo.get_dossier(conn, dossier_id)["name"]))
        self.seen_entries.add(entry_id)
        self.dossiers.add(dossier_id)
        return dossier_id

    def _update(self, dossier_id: int, values: dict[str, Any], *, own_entry: bool) -> None:
        current = repo.get_dossier(self.conn, dossier_id)
        if not own_entry and current["confidence"] >= values["confidence"]:
            return  # another container's better identification of the same product wins
        # Enrichment may have refined the type (mesh -> static mesh); keep the refinement.
        if current["type_id"] in self.definitions.dossier_types and \
                self.definitions.is_a(current["type_id"], values["type_id"]):
            values = {**values, "type_id": current["type_id"]}
        repo.update_dossier(self.conn, dossier_id, **values)


def identify_root(
    conn: sqlite3.Connection,
    *,
    environment_id: int,
    root_id: int,
    definition: EnvironmentDefinition,
    definitions: DefinitionSet,
    root: Path,
    files: list[FileInfo],
    user_ignore: tuple[str, ...] = (),
    threshold: float,
) -> IdentifyStats:
    """Run phase 2 for one root. ``files`` are its present files."""
    stats = IdentifyStats()
    ignore = definition.ignore_globs + tuple(user_ignore)
    content = [f for f in files if not any_match(ignore, f.rel) and not is_sidecar(f.rel)]
    # Exchange's own output: files a requisition wrote join their source asset (see sidecars.py).
    sidecars = read_sidecars(root, [f.rel for f in files if is_sidecar(f.rel)])
    output_keys = sidecar_keys(sidecars)
    # Lexicons with the words earlier scans found (known authors), for the layer to group by.
    known = with_generated(definitions, repo.generated_words(conn))
    ctx = LayerContext(root, definition, known, content, files)
    result = HANDLERS[definition.handler](ctx)
    stats.layer_config, stats.warnings = result.layer_config, result.warnings
    repo.replace_generated_words(conn, root_id, result.generated)

    ignored_keys = {fold(r) for r in result.ignored}
    content = [f for f in content if fold(f.rel) not in ignored_keys]
    content_ids = {f.id for f in content}
    ignored_ids = [f.id for f in files if f.id not in content_ids]
    repo.set_file_states(conn, ignored_ids, "ignored")
    stats.ignored_files = len(ignored_ids)
    stats.archives = sum(f.ext in ARCHIVE_EXTS for f in content)
    by_key = {fold(f.rel): f for f in content}

    # Containers, and which container each file is in (the deepest one holding it).
    container_ids: dict[str, int] = {}
    for c in result.containers:
        container_ids[fold(c.rel_path)] = repo.upsert_container(
            conn, environment_id, root_id, rel_path=c.rel_path, rel_key=fold(c.rel_path),
            kind=c.kind, name=c.name, meta=c.meta,
        )
    stats.containers = len(container_ids)
    deepest_first = sorted(container_ids, key=lambda k: (k.count("/"), len(k)), reverse=True)

    def container_of(rel: str) -> str | None:
        key = fold(rel)
        return next((c for c in deepest_first if not c or key.startswith(c + "/")), None)

    file_container = {f.id: container_of(f.rel) for f in content}
    repo.set_file_containers(
        conn, ((container_ids[c] if (c := file_container[f.id]) is not None else None, f.id)
               for f in content))

    def child_spec(f: FileInfo, container_key: str, parent_id: int | None,
                   type_root: str = "") -> _Spec | None:
        rel = (type_root and rel_under(f.rel, type_root)) or \
            (rel_under(f.rel, container_key) if container_key else f.rel)
        match = ctx.match_type(rel)
        if match is None:
            return None
        scale = float(ctx.options.get("child_confidence_scale", 1.0))
        spec = _Spec(
            key=f"file:{fold(rel_under(f.rel, container_key) if container_key else f.rel)}",
            type_id=match.type_id,
            name=display_name(f.rel),
            confidence=round(match.confidence * scale, 4),
            signals=[f"rule {match.type_id}: {match.glob}"],
            container_id=container_ids[container_key],
            primary=[f],
            parent_id=parent_id,
        )
        variant = _dossier_variant(definition, rel)
        if variant:
            spec.fields["variant"] = variant
        return spec

    def given_spec(f: FileInfo, given: ChildSpec, container_key: str, parent_id: int | None) -> _Spec:
        """A dossier for a file the layer identified itself."""
        rel = rel_under(f.rel, container_key) if container_key else f.rel
        spec = _Spec(
            key=f"file:{fold(rel)}", type_id=given.type_id, name=display_name(f.rel),
            confidence=given.confidence, signals=given.signals,
            container_id=container_ids[container_key], primary=[f], parent_id=parent_id,
            fields=dict(given.fields))
        if "variant" not in spec.fields:
            variant = _dossier_variant(definition, rel)
            if variant:
                spec.fields["variant"] = variant
        return spec

    writer = _Writer(conn, environment_id, definition.handler, definitions)
    # Files the user linked onto a dossier belong to it, and so do files a requisition wrote (to
    # the asset it converted); they do not become dossiers of their own.
    outputs = {by_key[k].id for k in output_keys if k in by_key}
    linked = {by_key[k].id for k in linked_keys(conn, root_id) if k in by_key} | outputs
    claimed: set[int] = set(linked)  # files in some entry
    children: set[int] = set()  # files that already became a child dossier

    def count(spec: _Spec) -> None:
        stats.dossiers += 1
        stats.below_threshold += spec.confidence < threshold

    for product in result.products:
        container_key = fold(product.container_rel)
        if container_key not in container_ids:
            stats.warnings.append(f"product {product.name!r} names an unknown container")
            continue
        primary = [by_key[fold(r)] for r in product.primary if fold(r) in by_key]
        members = [by_key[fold(r)] for r in dict.fromkeys(product.members) if fold(r) in by_key]
        if outputs and all(f.id in outputs for f in primary + members):
            continue  # a "product" made only of a requisition's output (e.g. a Daz folder product)
        spec = _Spec(
            key=f"product:{product.identity_key}",
            type_id="product",
            name=product.name,
            confidence=product.confidence,
            signals=product.signals,
            container_id=container_ids[container_key],
            primary=primary,
            support=[m for m in members if m not in primary],
            fields=product.fields,
            product_key=product.product_key,
        )
        product_id = writer.persist(spec)
        stats.products += 1
        count(spec)
        claimed.update(f.id for f in primary + members)
        explicit = {fold(c.rel): c for c in product.children}
        for m in members:
            if m.id in children or m.id in linked:
                continue
            given = explicit.get(fold(m.rel))
            if given is not None:
                child = given_spec(m, given, container_key, product_id)
            elif product.children_only:
                continue
            else:
                child = child_spec(m, container_key, product_id, product.type_root)
            if child is not None:
                writer.persist(child)
                children.add(m.id)
                count(child)

    standalone = {fold(c.rel): c for c in result.standalone}
    for f in content:
        container_key = file_container[f.id]
        if f.id in claimed or container_key is None:
            continue
        spec = child_spec(f, container_key, None)
        if spec is None and fold(f.rel) in standalone:
            spec = given_spec(f, standalone[fold(f.rel)], container_key, None)
        if spec is not None:
            writer.persist(spec)
            claimed.add(f.id)
            count(spec)

    stats.unattached_files = sum(f.id not in claimed for f in content)
    writer.seen_entries |= apply_file_links(conn, root_id)
    if sidecars:
        seen, touched = apply_sidecars(conn, environment_id, sidecars, by_key,
                                       {f.id: container_ids.get(file_container[f.id]) for f in content
                                        if file_container[f.id] is not None},
                                       set(definitions.dossier_types))
        writer.seen_entries |= seen
        writer.dossiers |= touched
    stale = repo.live_entry_ids(conn, root_id) - writer.seen_entries
    repo.retire_entries(conn, stale)
    stats.retired_entries = len(stale)
    repo.index_dossiers(conn, writer.dossiers)
    return stats


def display_name(rel: str) -> str:
    """A file's name without its extension; the whole name for files like ".duf"."""
    filename = rel.rsplit("/", 1)[-1]
    return filename.rsplit(".", 1)[0] or filename


def _dossier_variant(definition: EnvironmentDefinition, rel_in_container: str) -> str | None:
    for variant in definition.variants:
        if variant.level == "dossier" and any_match(variant.globs, rel_in_container):
            return variant.id
    return None
