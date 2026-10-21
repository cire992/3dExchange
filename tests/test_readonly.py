"""Scanning is strictly read-only: nothing in a scanned folder may change."""

import os
import stat
from pathlib import Path

import pytest

from exchange.errors import ScanError

from conftest import FIXTURES


def snapshot(root: Path) -> dict[str, tuple]:
    state = {}
    for dirpath, dirnames, filenames in os.walk(root):
        for name in dirnames + filenames:
            path = Path(dirpath, name)
            st = path.stat()
            state[path.relative_to(root).as_posix()] = (st.st_size, st.st_mtime_ns, st.st_mode)
    return state


def set_readonly(root: Path, readonly: bool) -> None:
    for dirpath, _, filenames in os.walk(root):
        for name in filenames:
            path = Path(dirpath, name)
            mode = path.stat().st_mode
            path.chmod(mode & ~stat.S_IWRITE if readonly else mode | stat.S_IWRITE)


def test_scan_changes_nothing(scan, mixed):
    set_readonly(mixed, True)  # any attempt to open a file for writing now fails loudly
    try:
        before = snapshot(mixed)
        scan(mixed)
        scan(mixed)  # rescans too
        assert snapshot(mixed) == before
    finally:
        set_readonly(mixed, False)


def test_scan_of_committed_fixtures_changes_nothing(scan):
    before = snapshot(FIXTURES)
    scan(FIXTURES)
    assert snapshot(FIXTURES) == before


def test_database_inside_scanned_folder_is_refused(definitions, mixed):
    from exchange.scanner import run_scan

    db = mixed / "Loose" / "library.db"
    with pytest.raises(ScanError, match="inside it"):
        run_scan(mixed, db_path=db, definitions=definitions)
    assert not db.exists()


def test_dry_run_writes_no_database(scan, mixed, db_path):
    report = scan(mixed, dry_run=True)
    assert len(report.environments) == 3
    assert not db_path.exists()
