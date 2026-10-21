from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from exchange.definitions import DefinitionSet, load_definitions
from exchange.scanner import ScanReport, run_scan

FIXTURES = Path(__file__).parent / "fixtures" / "envs"


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


def copy_fixture(name: str, dest: Path) -> Path:
    shutil.copytree(FIXTURES / name, dest)
    return dest


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
