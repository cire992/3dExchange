import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

REPO = Path(__file__).parents[1]
BANNED = {"pyside6", "pytest-qt"}


def _import(statement, cwd):
    # -S skips site, so the venv's editable .pth (which may point at another checkout) stays out;
    # PYTHONPATH then reaches only this tree's src.
    env = {**os.environ, "PYTHONPATH": str(REPO / "src")}
    return subprocess.run([sys.executable, "-S", "-c", statement], cwd=cwd, env=env, capture_output=True, text=True)


def test_window_package_is_gone():
    assert not (REPO / "src" / "exchange_ui").exists()
    assert not (REPO / "tests" / "ui").exists()


def test_window_package_is_not_importable_from_this_tree(tmp_path):
    control = _import("import exchange", tmp_path)
    assert control.returncode == 0, control.stderr  # the path setup does reach this tree
    gone = _import("import exchange_ui", tmp_path)
    assert gone.returncode != 0
    assert "ModuleNotFoundError" in gone.stderr


def _name(requirement):
    return re.split(r"[\s\[<>=!~;(]", requirement, maxsplit=1)[0].lower().replace("_", "-")


def test_pyproject_declares_no_qt_and_keeps_watchdog():
    project = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    extras = project["optional-dependencies"]
    assert "ui" not in extras
    for requirements in [project["dependencies"], *extras.values()]:
        assert not {_name(r) for r in requirements} & BANNED
    assert "gui-scripts" not in project
    assert not [s for s in project["scripts"].values() if "exchange_ui" in s]
    assert "watchdog>=4" in extras["service"]
    assert "watchdog>=4" in extras["dev"]
