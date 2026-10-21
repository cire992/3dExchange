import ast
import json
from pathlib import Path

from exchange.cli import main

SRC = Path(__file__).parents[1] / "src" / "exchange"


def test_scan_prints_summary(capsys, mixed, db_path):
    assert main(["scan", str(mixed), "--db", str(db_path), "--no-enrich"]) == 0
    out = capsys.readouterr().out
    assert "(read-only)" in out
    assert "Environments (3)" in out
    assert "Daz Studio  [daz_studio]" in out
    assert "Skyrim Special Edition (MO2)" in out
    assert "unidentified" in out


def test_scan_json(capsys, mixed, db_path):
    assert main(["scan", str(mixed), "--db", str(db_path), "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert {e["type_id"] for e in report["environments"]} == {"daz_studio", "skyrim_se", "loose_files"}
    daz = next(e for e in report["environments"] if e["type_id"] == "daz_studio")
    assert daz["roots"][0]["identification"]["products"] == 2


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


def run(capsys, *argv):
    code = main(list(map(str, argv)))
    out = capsys.readouterr()
    return code, out.out, out.err


def test_progress_json_lines(capsys, mixed, db_path):
    code, out, _ = run(capsys, "scan", mixed, "--db", db_path, "--progress-json")
    assert code == 0
    events = [json.loads(line) for line in out.splitlines()]
    phases = {e["phase"] for e in events if e["event"] == "progress"}
    assert phases == {1, 2, 3}
    assert events[-1]["event"] == "result"
    assert len(events[-1]["data"]["environments"]) == 3


def test_env_commands(capsys, mixed, db_path):
    run(capsys, "scan", mixed, "--db", db_path, "--no-enrich")
    code, out, _ = run(capsys, "env", "list", "--db", db_path, "--json")
    envs = {e["type_id"]: e for e in json.loads(out)}
    mo2 = envs["skyrim_se"]["id"]

    code, out, _ = run(capsys, "env", "show", mo2, "--db", db_path)
    assert "Lard Lads Donuts  [mod]" in out and "selected_profile = Default" in out

    code, out, err = run(capsys, "env", "config", mo2, "--db", db_path, "--profile", "Nope")
    assert code == 2 and "no MO2 profile 'Nope'" in err
    code, out, _ = run(capsys, "env", "config", mo2, "--db", db_path, "--profile", "Default",
                       "--visibility", "publishable", "--ignore-add", "mods/Test Requisitions/**", "--json")
    assert json.loads(out) == {"mo2_profile": "Default", "visibility": "publishable",
                               "ignore": ["mods/Test Requisitions/**"]}

    code, out, _ = run(capsys, "rescan", "--db", db_path, "--env", mo2, "--no-enrich")
    assert code == 0 and "1 products" in out

    code, out, _ = run(capsys, "env", "forget", mo2, "--db", db_path)
    assert code == 1 and "--yes" in out
    code, out, _ = run(capsys, "env", "forget", mo2, "--db", db_path, "--yes")
    assert code == 0 and "Forgot" in out
    code, out, _ = run(capsys, "env", "list", "--db", db_path, "--json")
    assert "skyrim_se" not in {e["type_id"] for e in json.loads(out)}
    code, _, err = run(capsys, "rescan", "--db", db_path, "--env", mo2)
    assert code == 2 and "no environment" in err


def test_search_and_show(capsys, mixed, db_path):
    run(capsys, "scan", mixed, "--db", db_path)
    code, out, _ = run(capsys, "search", "marius type:daz_morph", "--db", db_path, "--json")
    page = json.loads(out)
    assert page["total"] == 2
    uid = page["items"][0]["uid"]
    code, out, _ = run(capsys, "show", uid[:10], "--db", db_path)
    assert code == 0 and "Daz morph" in out and "ledgers (1)" in out and "variant: genesis_9" in out
    code, _, err = run(capsys, "search", "has:candidate", "--db", db_path)
    assert code == 2 and "phase 4" in err
    code, _, err = run(capsys, "show", "zzz", "--db", db_path)
    assert code == 2 and "0 dossiers match" in err


def test_search_without_library(capsys, tmp_path):
    code, _, err = run(capsys, "search", "x", "--db", tmp_path / "none.db")
    assert code == 2 and "no library" in err


def test_discover(capsys, monkeypatch, db_path):
    from exchange import autodiscover

    monkeypatch.setattr(autodiscover.Places, "from_system", classmethod(lambda cls: cls()))
    code, out, _ = run(capsys, "discover", "--db", db_path)
    assert code == 0 and "Nothing found" in out


def test_enrich_command(capsys, loose_folder, db_path):
    run(capsys, "scan", loose_folder, "--db", db_path, "--no-enrich")
    code, out, _ = run(capsys, "enrich", "--db", db_path, "--json")
    stats = json.loads(out)
    assert list(stats.values())[0]["hashed"] == 7
