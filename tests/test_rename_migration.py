"""Moving data from before the rename of pipelines to processes: the database and the data folder."""

import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from exchange.db import open_library
from exchange.db.connection import _migrations
from exchange.processes import legacy, registry

FIXTURES = Path(__file__).parent / "fixtures" / "processes"


def _database_at(path: Path, version: int) -> None:
    conn = sqlite3.connect(path)
    for migration in _migrations():
        if migration.version <= version:
            conn.executescript(f"BEGIN;\n{migration.sql}\nPRAGMA user_version = {migration.version};\nCOMMIT;")
    conn.close()


def test_migration_renames_the_chain_column_and_the_output_keys(tmp_path):
    db = tmp_path / "library.db"
    _database_at(db, 6)
    conn = sqlite3.connect(db)
    conn.execute("INSERT INTO requisition (id, uid, name, state, position, environment_id, endpoint, created_at) "
                 "VALUES (1, 'r1', 'Helmet', 'fulfilled', 1, 1, '{}', '2026-10-24T00:00:00Z')")
    outputs = [{"root": "C:/out", "pipeline": "convert_mesh", "version": "1.0.0", "files": ["a.glb"]},
               {"root": "C:/out", "pipeline": "stamp_images", "version": "1.0.0", "files": ["b.png"]}]
    conn.executemany("INSERT INTO requisition_item (requisition_id, dossier_uid, pipelines, params, state, outputs) "
                     "VALUES (1, ?, ?, ?, ?, ?)", [
                         ("d1", '[{"id": "convert_mesh", "version": "1.0.0"}]', '{"convert_mesh": {"format": "glb"}}', "done", json.dumps(outputs)),
                         ("d2", '[{"id": "stamp_images", "version": "1.0.0"}]', '{"stamp_images": {"size": 8}}', "queued", None),
                     ])
    conn.commit(); conn.close()

    conn = open_library(db)
    columns = [row[1] for row in conn.execute("PRAGMA table_info(requisition_item)")]
    assert "processes" in columns and "pipelines" not in columns
    done, queued = conn.execute("SELECT processes, params, outputs FROM requisition_item ORDER BY id").fetchall()
    assert json.loads(done[0]) == [{"id": "convert_mesh", "version": "1.0.0"}]
    assert json.loads(done[1]) == {"convert_mesh": {"format": "glb"}}
    assert json.loads(done[2]) == [{"root": "C:/out", "process": "convert_mesh", "version": "1.0.0", "files": ["a.glb"]},
                                   {"root": "C:/out", "process": "stamp_images", "version": "1.0.0", "files": ["b.png"]}]
    assert queued[2] is None
    conn.close()
    assert list(tmp_path.glob("library.v6.*.bak.db")), "the database is backed up before migrating"


def _old_package(target: Path, source: Path) -> Path:
    """A package as it was installed before the rename, importing the SDK by its old name."""
    shutil.copytree(source, target)
    manifest = target / "process.toml"
    manifest.with_name("pipeline.toml").write_bytes(manifest.read_bytes().replace(b"[process]", b"[pipeline]", 1))
    manifest.unlink()
    for code in target.rglob("*.py"):
        code.write_bytes(code.read_bytes().replace(b"exchange.processes", b"exchange.pipelines"))
    return target


@pytest.fixture
def old_data(tmp_path, monkeypatch):
    data = tmp_path / "data"
    old = data / "pipelines"
    trusted_pkg = _old_package(old / "stamp_images", FIXTURES / "stamp_images")
    changed_pkg = _old_package(old / "bridge_demo", FIXTURES / "bridge_demo")
    (old / "trusted.json").write_text(json.dumps({
        "stamp_images": legacy.package_fingerprint(trusted_pkg, "pipeline.toml"),
        "bridge_demo": legacy.package_fingerprint(changed_pkg, "pipeline.toml"),
    }))
    # Changed after it was trusted: it must stay untrusted.
    ops = changed_pkg / "operations" / "ops.py"
    ops.write_text(ops.read_text() + "\n# edited after trusting\n")
    (data / "tools.json").write_text(json.dumps({"blender": "C:/Blender/blender.exe"}))
    monkeypatch.setenv("EXCHANGE_DATA_DIR", str(data))
    registry._migrated.clear()
    return data


def test_the_data_folder_moves_once_and_keeps_trust_only_for_unchanged_packages(old_data):
    reg = registry.load_registry()
    assert not (old_data / "pipelines").exists()
    new = old_data / "processes"
    for name in ("stamp_images", "bridge_demo"):
        assert (new / name / "process.toml").is_file() and not (new / name / "pipeline.toml").exists()
        assert (new / name / "process.toml").read_text().count("[process]") == 1
    assert reg.get("stamp_images").trusted
    assert not reg.get("bridge_demo").trusted
    for code in new.rglob("*.py"):
        assert b"exchange.pipelines" not in code.read_bytes(), code
    assert reg.get("stamp_images").operations()  # its code loads under the new SDK name
    assert json.loads((new / "trusted.json").read_text()) == {"stamp_images": registry.fingerprint(new / "stamp_images")}
    assert json.loads((old_data / "tools.json").read_text()) == {"blender": "C:/Blender/blender.exe"}
    # Running again changes nothing.
    assert legacy.migrate_data_folder(old_data) == []


def test_an_interrupted_move_finishes(old_data):
    # One package was converted before the move stopped.
    old = old_data / "pipelines" / "stamp_images"
    trusted = json.loads((old_data / "pipelines" / "trusted.json").read_text())
    for code in old.rglob("*.py"):
        code.write_bytes(code.read_bytes().replace(b"exchange.pipelines", b"exchange.processes"))
    (old / "process.toml").write_bytes((old / "pipeline.toml").read_bytes().replace(b"[pipeline]", b"[process]", 1))
    (old / "pipeline.toml").unlink()
    trusted["stamp_images"] = registry.fingerprint(old)
    (old_data / "pipelines" / "trusted.json").write_text(json.dumps(trusted))
    notes = legacy.migrate_data_folder(old_data)
    assert notes == ["bridge_demo: converted; it had changed since it was trusted, so it stays untrusted"]
    registry._migrated.clear()
    assert registry.load_registry().get("stamp_images").trusted


def test_the_legacy_fingerprint_matches_the_registry(tmp_path):
    package = shutil.copytree(FIXTURES / "bridge_demo", tmp_path / "bridge_demo")
    assert legacy.package_fingerprint(package, "process.toml") == registry.fingerprint(package)


def test_old_packages_are_reported_not_silently_skipped(tmp_path, monkeypatch):
    monkeypatch.setenv("EXCHANGE_DATA_DIR", str(tmp_path / "data"))
    registry._migrated.clear()
    extra = tmp_path / "extra"
    _old_package(extra / "stamp_images", FIXTURES / "stamp_images")
    reg = registry.load_registry((extra,))
    assert "stamp_images" not in reg.packages
    assert any("before pipelines were renamed processes" in problem for problem in reg.problems)
    with pytest.raises(registry.ProcessError, match="rename pipeline.toml to process.toml"):
        registry.install(extra / "stamp_images")
