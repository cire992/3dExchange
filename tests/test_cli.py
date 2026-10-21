import ast
import json
from pathlib import Path

from exchange.cli import main

SRC = Path(__file__).parents[1] / "src" / "exchange"


def test_scan_prints_summary(capsys, mixed, db_path):
    assert main(["scan", str(mixed), "--db", str(db_path)]) == 0
    out = capsys.readouterr().out
    assert "(read-only)" in out
    assert "Environments (3)" in out
    assert "Daz Studio content library (Daz Library)" in out
    assert "Skyrim Special Edition (MO2)" in out
    assert "unidentified" in out


def test_scan_json(capsys, mixed, db_path):
    assert main(["scan", str(mixed), "--db", str(db_path), "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert {e["type_id"] for e in report["environments"]} == {"daz_studio", "skyrim_se", "loose_files"}
    daz = next(e for e in report["environments"] if e["type_id"] == "daz_studio")
    assert daz["identification"]["products"] == 2


def test_dry_run(capsys, mixed, db_path):
    assert main(["scan", str(mixed), "--db", str(db_path), "--dry-run"]) == 0
    assert "Dry run: nothing written" in capsys.readouterr().out
    assert not db_path.exists()


def test_errors_exit_2(capsys, tmp_path, mixed):
    assert main(["scan", str(tmp_path / "missing"), "--db", str(tmp_path / "x.db")]) == 2
    assert "not a folder" in capsys.readouterr().err
    assert main(["scan", str(mixed), "--db", str(mixed / "lib.db")]) == 2
    assert "inside it" in capsys.readouterr().err


def test_default_db_uses_data_dir(capsys, monkeypatch, tmp_path, loose_folder):
    monkeypatch.setenv("EXCHANGE_DATA_DIR", str(tmp_path / "data"))
    assert main(["scan", str(loose_folder)]) == 0
    assert (tmp_path / "data" / "library.db").exists()


def test_core_never_imports_a_ui_toolkit():
    banned = {"PySide6", "PyQt5", "PyQt6", "tkinter"}
    for path in SRC.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            assert not {n.split(".")[0] for n in names} & banned, path
