"""Copy a few products out of a real Daz library into a small sample library, for checks on real data.

A full scan of a real library takes minutes without enrichment and hours with it, most of it spent on
files the check doesn't care about. ``exchange scan`` on a sample takes seconds and runs the same code
on real files and real DIM manifests. The source is only read, and a requisition walked in the sample
reads the sample's files, so nothing can reach the real library.

    python scripts/sample_library.py SOURCE --list "genesis 9"
    python scripts/sample_library.py SOURCE DEST --product "Racing Bike" --random 5 --dry-run
    python scripts/sample_library.py SOURCE DEST --product "Racing Bike" --file "People/Genesis 9/*.duf"
    exchange scan DEST --db SCRATCH.db

Copying again is cheap: files already in the sample are skipped. Files moved since their product was
installed aren't found: a full scan relocates them by name, which needs the whole library walked, so the
script says how many of each product's files it found, and ``--random`` only takes products still whole.
Add moved files with ``--file``.
"""

from __future__ import annotations

import argparse
import itertools
import random
import shutil
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from exchange.scanner.layers.daz import parse_manifest

MANIFESTS = "Runtime/Support"


class SampleError(Exception):
    pass


@dataclass
class Product:
    name: str
    manifest: str  # relative to the source
    files: list[str]


@dataclass
class Plan:
    files: dict[str, int]  # relative path → size
    missing: list[str]

    @property
    def bytes(self) -> int:
        return sum(self.files.values())


def read_products(source: Path) -> list[Product]:
    """Every product with files in the library's manifests; only that folder is read."""
    found = []
    for path in sorted((source / MANIFESTS).glob("*.dsx")):
        for product in parse_manifest(path.read_bytes()) or []:
            files = list(dict.fromkeys([a.path for a in product.assets] + product.support))
            if files:  # DIM writes empty manifests for local user content
                found.append(Product(product.name, f"{MANIFESTS}/{path.name}", files))
    return found


def whole(source: Path, product: Product) -> bool:
    return all((source / rel).is_file() for rel in product.files)


def choose(products: list[Product], names: list[str], count: int = 0, seed: int = 0,
           keep: Callable[[Product], bool] = lambda p: True) -> list[Product]:
    """The product each name means (an exact name, else the one containing it), plus ``count`` at
    random from those ``keep`` accepts."""
    chosen = []
    for name in names:
        wanted = name.casefold()
        hits = [p for p in products if p.name.casefold() == wanted] or \
               [p for p in products if wanted in p.name.casefold()]
        if len(hits) != 1:
            shown = "".join(f"\n  {p.name}" for p in hits[:10])
            raise SampleError(f"{name!r} matches {len(hits)} products{shown}")
        if hits[0] not in chosen:
            chosen.append(hits[0])
    rest = [p for p in products if p not in chosen]
    random.Random(seed).shuffle(rest)
    return chosen + list(itertools.islice(filter(keep, rest), count))


def plan(source: Path, products: list[Product], patterns: list[str] | tuple[str, ...] = ()) -> Plan:
    """What the sample holds: the products' files and manifests, and whatever ``patterns`` match."""
    files, missing = {}, []
    for product in products:
        for rel in [product.manifest, *product.files]:
            path = source / rel
            if ".." not in rel.split("/") and path.is_file():
                files[rel] = path.stat().st_size
            else:
                missing.append(rel)
    for pattern in patterns:
        hits = [p for p in source.glob(pattern) if p.is_file()]
        if not hits:
            raise SampleError(f"nothing in {source} matches {pattern!r}")
        files.update({p.relative_to(source).as_posix(): p.stat().st_size for p in hits})
    return Plan(files, missing)


def copy(source: Path, dest: Path, files: dict[str, int]) -> int:
    """Copy into ``dest``, keeping the layout; returns how many were copied."""
    copied = 0
    for rel, size in files.items():
        target = dest / rel
        if target.is_file() and target.stat().st_size == size:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / rel, target)
        copied += 1
    return copied


def _size(size: int) -> str:
    return f"{size / 2 ** 30:.2f} GB" if size >= 2 ** 30 else f"{size / 2 ** 20:.1f} MB"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("source", type=Path, help="the Daz content directory (only read)")
    parser.add_argument("dest", type=Path, nargs="?", help="the sample library's folder")
    parser.add_argument("--list", metavar="TEXT", help="list the products with TEXT in their name, then stop")
    parser.add_argument("--product", action="append", default=[], metavar="NAME", help="a product, by name")
    parser.add_argument("--random", type=int, default=0, metavar="N", help="also take N products at random")
    parser.add_argument("--seed", type=int, default=0, help="for --random: the same seed gives the same products")
    parser.add_argument("--file", action="append", default=[], metavar="GLOB",
                        help="files no manifest lists, relative to the source (saved characters, scene subsets)")
    parser.add_argument("--max-gb", type=float, default=5.0, help="refuse a sample bigger than this (default: 5)")
    parser.add_argument("--dry-run", action="store_true", help="say what would be copied, copy nothing")
    args = parser.parse_args(argv)
    try:
        return _run(args, parser)
    except SampleError as exc:
        print(f"sample_library: {exc}", file=sys.stderr)
        return 2


def _run(args, parser) -> int:
    source = args.source.resolve()
    started = time.perf_counter()
    products = read_products(source)
    if args.list is not None:
        for product in products:
            if args.list.casefold() in product.name.casefold():
                print(f"{len(product.files):7} files  {product.name}")
        return 0
    if args.dest is None:
        parser.error("name the sample library's folder (or pass --list)")
    dest = args.dest.resolve()
    if dest == source or dest.is_relative_to(source) or source.is_relative_to(dest):
        raise SampleError("the sample can't be inside the source, or the source inside the sample")
    chosen = choose(products, args.product, args.random, args.seed, lambda p: whole(source, p))
    if not chosen and not args.file:
        raise SampleError("nothing to copy: pass --product, --random or --file")
    planned = plan(source, chosen, args.file)
    for product in chosen:
        found = sum((source / rel).is_file() for rel in product.files)
        print(f"{found:7} of {len(product.files)} files  {product.name}")
    summary = f"{len(chosen)} products, {len(planned.files)} files, {_size(planned.bytes)}"
    if planned.missing:
        summary += f", {len(planned.missing)} listed files missing"
    if planned.bytes > args.max_gb * 2 ** 30:
        raise SampleError(f"{summary}: over the limit of {args.max_gb:g} GB (--max-gb)")
    if args.dry_run:
        print(f"Would copy {summary}")
        return 0
    copied = copy(source, dest, planned.files)
    print(f"{summary} in {dest} ({copied} copied, {time.perf_counter() - started:.1f} s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
