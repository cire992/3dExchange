from __future__ import annotations

from pathlib import Path

import pytest

from exchange.definitions import DefinitionSet, load_definitions
from exchange.scanner.scan import ScanReport, run_scan

from builders import FIXTURES, copy_fixture  # noqa: F401  (re-exported for tests)


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path_factory, monkeypatch):
    """Keep the user's real library and definitions out of every test."""
    monkeypatch.setenv("EXCHANGE_DATA_DIR", str(tmp_path_factory.mktemp("exchange-data")))


@pytest.fixture(scope="session")
def definitions() -> DefinitionSet:
    return load_definitions(include_user_dir=False)


@pytest.fixture
def db_path(tmp_path) -> Path:
    return tmp_path / "library" / "library.db"


@pytest.fixture
def daz_library(tmp_path) -> Path:
    return copy_fixture("fake_daz_library", tmp_path / "scan" / "My Daz Library")


@pytest.fixture
def mo2_instance(tmp_path) -> Path:
    return copy_fixture("fake_mo2", tmp_path / "scan" / "MO2 Skyrim")


@pytest.fixture
def loose_folder(tmp_path) -> Path:
    return copy_fixture("loose_files", tmp_path / "scan" / "Stuff")


@pytest.fixture
def mixed(tmp_path) -> Path:
    """One folder holding a Daz library, an MO2 instance and loose files side by side."""
    root = tmp_path / "scan" / "Assets"
    copy_fixture("fake_daz_library", root / "Daz Library")
    copy_fixture("fake_mo2", root / "MO2")
    copy_fixture("loose_files", root / "Loose")
    return root


@pytest.fixture
def scan(definitions, db_path):
    def _scan(folder: Path, **kwargs) -> ScanReport:
        return run_scan(folder, db_path=db_path, definitions=definitions, **kwargs)

    return _scan


def env_report(report: ScanReport, type_id: str):
    matches = [e for e in report.environments if e.type_id == type_id]
    assert len(matches) == 1, [e.type_id for e in report.environments]
    return matches[0]


def root_report(report: ScanReport, type_id: str):
    """The report of an environment that has exactly one root."""
    roots = env_report(report, type_id).roots
    assert len(roots) == 1, [r.path for r in roots]
    return roots[0]


@pytest.fixture
def unreal(tmp_path) -> Path:
    from builders import unreal_project

    return unreal_project(tmp_path / "scan" / "MyGame")


@pytest.fixture
def daz_two_dirs(tmp_path) -> Path:
    """A DIM content directory and a Daz Connect one side by side."""
    from builders import daz_connect_library

    root = tmp_path / "scan" / "Daz"
    copy_fixture("fake_daz_library", root / "My Library")
    daz_connect_library(root / "Daz Connect")
    return root


@pytest.fixture
def library(db_path):
    """Open the test library (read-write); closed at teardown."""
    from exchange.db import open_library

    conns = []

    def _open():
        conns.append(open_library(db_path))
        return conns[-1]

    yield _open
    for c in conns:
        c.close()
