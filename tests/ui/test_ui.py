"""The desktop app: models, the main window and background scans."""

from PySide6.QtCore import QModelIndex
from PySide6.QtWidgets import QLabel

from builders import copy_fixture, write
from exchange_ui.models import BRICK, KIND, THUMBNAIL, BrowserModel, SidebarModel
from exchange_ui.service import Filter, LibraryService


def sidebar_rows(model, parent=QModelIndex()):
    return [(model.index(r, 0, parent).data(), model.index(r, 0, parent).data(KIND))
            for r in range(model.rowCount(parent))]


def find(window, kind, text):
    index = window._find_sidebar((kind, text))
    assert index is not None, (kind, text)
    return index


def bricks(window):
    model = window.browser_model
    return [model.index(r, 0).data(BRICK).name for r in range(model.rowCount())]


def select_brick(window, name):
    model = window.browser_model
    row = next(r for r in range(model.rowCount()) if model.index(r, 0).data(BRICK).name == name)
    window.grid.setCurrentIndex(model.index(row, 0))
    return model.index(row, 0)


def test_sidebar_model(service):
    model = SidebarModel(service)
    model.reload()
    rows = sidebar_rows(model)
    assert rows[:3] == [("LIBRARY", "section"), ("All assets", "all"), ("ENVIRONMENTS", "section")]
    envs = {name: model.index(i, 0) for i, (name, kind) in enumerate(rows) if kind == "environment"}
    children = dict(sidebar_rows(model, envs["Daz Studio"]))
    assert children["Daz morph"] == "type"  # one content directory: no container rows
    mo2 = next(i for n, i in envs.items() if n.startswith("Skyrim"))
    assert ("Lard Lads Donuts", "container") in sidebar_rows(model, mo2)
    assert model.unidentified == 1


def test_many_containers_are_grouped(scan, tmp_path, db_path, definitions):
    mo2 = copy_fixture("fake_mo2", tmp_path / "scan" / "MO2")
    for i in range(14):
        write(mo2 / "mods" / f"Mod {i:02d}" / "meshes" / f"thing{i}.nif", b"nif")
    scan(mo2)
    svc = LibraryService(db_path, definitions)
    model = SidebarModel(svc)
    model.reload()
    assert ("Mods", "group") in sidebar_rows(model, model.index(3, 0))
    svc.close()


def test_browser_pages_as_it_scrolls(service, monkeypatch):
    monkeypatch.setattr(BrowserModel, "PAGE", 3)
    model = BrowserModel(service)
    model.set_filter(Filter(group="type"))
    assert model.rowCount() == 3 and model.total > 6
    assert model.canFetchMore()
    model.fetchMore()
    assert model.rowCount() == 6
    while model.canFetchMore():
        model.fetchMore()
    assert model.rowCount() == model.total
    assert len({model.index(r, 0).data(BRICK).uid for r in range(model.rowCount())}) == model.total


def test_thumbnails_load_in_the_background(qtbot, service):
    model = BrowserModel(service)
    model.set_filter(Filter(query="teapot"))
    index = model.index(0, 0)
    with qtbot.waitSignal(model.dataChanged, timeout=5000):
        assert index.data(THUMBNAIL) is None  # requested, not loaded yet
    image = index.data(THUMBNAIL)
    assert image is not None and not image.isNull() and image.width() == 256


def test_bad_search_is_reported_not_raised(qtbot, service):
    model = BrowserModel(service)
    with qtbot.waitSignal(model.error) as blocker:
        model.set_filter(Filter(query="colour:pink"))
    assert "unknown filter" in blocker.args[0]
    assert model.rowCount() == 0


def test_main_window_browsing(window):
    assert window.title.text() == "All assets"
    assert "Marius HD-8K for Genesis 9" in bricks(window)
    assert "Marius Head" not in bricks(window)  # grouped under its product

    window.tree.setCurrentIndex(find(window, "type", "Daz morph"))
    assert window.title.text() == "Daz morph"
    assert window.breadcrumb.text() == "Daz Studio › Dossier type"
    assert sorted(bricks(window)) == ["Marius Body", "Marius Head"]
    assert not any(b.isEnabled() for b in window.group_buttons.buttons())

    select_brick(window, "Marius Head")
    assert window.inspector.name.text() == "Marius Head"
    texts = [w.text() for w in window.inspector.overview.findChildren(QLabel)]
    assert any("Jane Doe" in t and "(from product)" in t for t in texts)

    window.tree.setCurrentIndex(find(window, "all", "All assets"))
    index = select_brick(window, "Marius HD-8K for Genesis 9")
    window._on_double_click(index)  # a product opens to show its contents
    assert window.title.text() == "Marius HD-8K for Genesis 9"
    assert sorted(bricks(window)) == ["Marius Body", "Marius HD-8K", "Marius Head"]


def test_search_and_unidentified(window):
    window.search.setText("donut -is:product")
    window._apply_search()
    assert sorted(bricks(window)) == ["Donut01_Blue", "Donut01_Pink", "donut01", "donut01_pink"]
    window.search.setText("donut status:nope")
    window._apply_search()
    assert window.search_error.isVisibleTo(window) and "unknown status" in window.search_error.text()
    window.search.clear()
    window._apply_search()
    window.unidentified_button.setChecked(True)
    assert window.title.text() == "Unidentified"
    assert bricks(window) == ["props"]
    window.tree.setCurrentIndex(find(window, "environment", "Daz Studio"))
    assert not window.unidentified_button.isChecked()


def test_empty_library(qtbot, tmp_path, definitions):
    from exchange_ui.main_window import MainWindow

    svc = LibraryService(tmp_path / "new" / "library.db", definitions)
    win = MainWindow(svc)
    qtbot.addWidget(win)
    assert win.stack.currentWidget() is win.empty
    assert "No environments yet" in win.empty.text()


def test_primary_path_for_show_in_folder(window, mixed):
    index = select_brick(window, "Loose Boots")
    path = window.primary_path(index)
    assert path.endswith("Loose Boots.duf") and str(mixed) in path


def test_scan_in_background_process(qtbot, tmp_path, definitions, loose_folder):
    from exchange_ui.main_window import MainWindow

    svc = LibraryService(tmp_path / "bg" / "library.db", definitions)
    win = MainWindow(svc)
    qtbot.addWidget(win)
    progress = []
    win.runner.progress.connect(progress.append)
    with qtbot.waitSignal(win.runner.finished, timeout=120_000) as blocker:
        win.scan_folder(loose_folder)
        assert not win.add_button.isEnabled()
    report, error = blocker.args
    assert error == ""
    assert [e["type_id"] for e in report["environments"]] == ["loose_files"]
    assert {p["phase"] for p in progress} == {1, 2, 3}
    assert "Scan finished" in win.status.text()
    assert win.add_button.isEnabled()
    assert "Donut01_Pink" in bricks(win) or win.browser_model.total > 0


def test_scan_errors_are_shown(qtbot, tmp_path, definitions):
    from exchange_ui.main_window import MainWindow

    svc = LibraryService(tmp_path / "err" / "library.db", definitions)
    win = MainWindow(svc)
    qtbot.addWidget(win)
    with qtbot.waitSignal(win.runner.finished, timeout=60_000) as blocker:
        win.scan_folder(tmp_path / "does-not-exist")
    assert "not a folder" in blocker.args[1]
    assert "not a folder" in win.status.text()
