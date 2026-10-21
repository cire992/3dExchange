import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if os.name == "nt":  # the offscreen platform needs to be told where fonts are
    os.environ.setdefault("QT_QPA_FONTDIR", os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"))


@pytest.fixture
def service(scan, mixed, db_path, definitions):
    from builders import glb_bytes, write
    from exchange_ui.service import LibraryService

    write(mixed / "Loose" / "Downloads" / "props" / "Teapot.glb", glb_bytes())
    scan(mixed, enrich=True)
    svc = LibraryService(db_path, definitions)
    yield svc
    svc.close()


@pytest.fixture
def window(qtbot, service):
    from exchange_ui.app import make_app
    from exchange_ui.main_window import MainWindow

    make_app([])
    win = MainWindow(service)
    qtbot.addWidget(win)
    return win
