"""The Unidentified desk, the lexicon editor and change detection (Roadmap phase 3c)."""

from PySide6.QtCore import QObject, Signal

from builders import write
from exchange.db import repository as repo
from exchange.definitions import load_definitions
from exchange_ui import main_window
from exchange_ui.desk import COUNT, PATH, STATE
from exchange_ui.models import BRICK, DETAIL, KIND

from test_editing import action, search
from test_ui import bricks, find, select_brick


def wait_loaded(qtbot, panel, item):
    qtbot.waitUntil(lambda: item.data(STATE) == "loaded", timeout=10_000)


def child(item, name):
    return next(item.child(r) for r in range(item.rowCount()) if item.child(r).text() == name)


def open_folder(qtbot, panel, path):
    """Expand the loose-files root down to ``path``; returns (that folder's item, its parent's)."""
    item = next(panel.model.item(r) for r in range(panel.model.rowCount())
                if panel.model.item(r).text().startswith("Loose"))
    parent = None
    for name in path.split("/"):
        panel.tree.expand(item.index())
        wait_loaded(qtbot, panel, item)
        parent, item = item, child(item, name)
    return item, parent


def make_window(qtbot, db_path, definitions):
    from exchange_ui.app import make_app
    from exchange_ui.service import LibraryService

    make_app([])
    win = main_window.MainWindow(LibraryService(db_path, definitions))
    qtbot.addWidget(win)
    return win


def test_unattached_files_by_folder(qtbot, scan, mixed, db_path, definitions, monkeypatch):
    write(mixed / "Loose" / "Junk" / "Cache" / "a.dat", b"x")
    write(mixed / "Loose" / "Junk" / "Cache" / "b.dat", b"x")
    scan(mixed)
    window = make_window(qtbot, db_path, definitions)

    window.unidentified_button.setChecked(True)
    assert window.desk_bar.isVisibleTo(window)
    window.set_desk_mode("files")
    panel = window.unattached_panel
    assert window.stack.currentWidget() is panel and window.title.text() == "Unattached files"
    junk, loose = open_folder(qtbot, panel, "Loose/Junk")
    assert junk.data(COUNT) == 2 and junk.data(PATH) == "Loose/Junk"

    panel.tree.setCurrentIndex(junk.index())
    qtbot.waitUntil(lambda: panel.preview.count() == 2, timeout=10_000)
    assert panel.product_button.isEnabled() and panel.ignore_button.isEnabled()

    monkeypatch.setattr(window, "ask_text", lambda *a, **k: "Junk bundle")
    panel.product_button.click()
    wait_loaded(qtbot, panel, loose)
    assert not any(loose.child(r).text() == "Junk" for r in range(loose.rowCount()))
    window.undo()
    panel.load_roots()
    junk, loose = open_folder(qtbot, panel, "Loose/Junk")

    # Linking a folder's files to an asset (picked by searching).
    panel.tree.setCurrentIndex(junk.index())
    target = window.service.page(main_window.Filter(query="Barrel01", group="all"), 0, 1).items[0]
    monkeypatch.setattr(window, "pick_asset", lambda title: (target.uid, target.name))
    panel.link_button.click()
    files = [f["rel_path"] for l in window.service.detail(target.uid)["ledgers"] for e in l["entries"] for f in e["files"]]
    assert "Loose/Junk/Cache/a.dat" in files
    window.undo()

    # Not assets: ignore the folder, from now on.
    panel.load_roots()
    junk, loose = open_folder(qtbot, panel, "Loose/Junk")
    panel.tree.setCurrentIndex(junk.index())
    panel.ignore_button.click()
    rules = [repo.user_config(window.service.connection_for_tests(), e["id"]).get("ignore")
             for e in window.service.sidebar()["environments"]]
    assert ["Loose/Junk/**"] in rules
    wait_loaded(qtbot, panel, loose)
    assert not any(loose.child(r).text() == "Junk" for r in range(loose.rowCount()))
    panel.wait()
    window.service.close()


def test_suggestions_in_batches(window):
    window.unidentified_button.setChecked(True)
    window.set_desk_mode("suggestions")
    panel = window.suggestions_panel
    assert window.stack.currentWidget() is panel and panel.total >= 2
    assert "Suggestions" in window.desk_buttons.buttons()[2].text()
    panel.all.setChecked(True)
    ids = panel.checked_ids()
    assert len(ids) == panel.total and panel.accept_button.isEnabled()
    panel.table.setCurrentCell(0, 0)  # shows what it is about
    assert window.inspector.detail is not None
    panel.accept_button.click()
    assert panel.total == 0 and "No pending suggestions" in panel.summary.text()
    window.undo()  # one step for the batch
    panel.reload()
    assert panel.total == len(ids)
    panel.table.item(0, 0).setCheckState(main_window.Qt.CheckState.Checked)
    panel.reject_button.click()
    assert panel.total == len(ids) - 1


def test_not_an_asset_split_fold_and_promote(window, monkeypatch):
    window.unidentified_button.setChecked(True)
    index = select_brick(window, "props")
    action(window.build_context_menu(index), "Not an asset").trigger()
    assert bricks(window) == [] and window.sidebar_model.unidentified == 0
    window.tree.setCurrentIndex(find(window, "all", "All assets"))
    search(window, "is:dismissed")
    index = select_brick(window, "props")
    action(window.build_context_menu(index), "Count as an asset again").trigger()
    assert bricks(window) == []

    search(window, "donut01_ -is:product")
    pink = select_brick(window, "Donut01_Pink").data(BRICK)
    blue = window.browser_model.brick(next(r for r, b in enumerate(window.browser_model.bricks) if b.name == "Donut01_Blue"))
    monkeypatch.setattr(window, "ask_text", lambda *a, **k: "Blue")
    action(window.build_drop_menu(pink, [blue.uid]), "Fold in as a variant").trigger()
    assert window.service.detail(pink.uid)["variants"] == ["Blue"]
    index = select_brick(window, "Donut01_Pink")
    action(window.build_context_menu(index), "Make variant “Blue” its own asset").trigger()
    assert window.service.detail(pink.uid)["variants"] == []

    # Split: the folded entry goes off on its own again.
    window.undo()
    detail = window.service.detail(pink.uid)
    blue_entry = next(e["id"] for l in detail["ledgers"] for e in l["entries"] if e["variant"] == "Blue")
    monkeypatch.setattr(window, "ask_entries", lambda d: ([blue_entry], "Donut01 Blue again"))
    index = select_brick(window, "Donut01_Pink")
    action(window.build_context_menu(index), "Split…").trigger()
    assert "Donut01 Blue again" in {b.name for b in window.service.page(main_window.Filter(query="donut", group="all")).items}


class _FakeJob(QObject):
    finished = Signal(object, str)
    started: list = []

    def __init__(self, args, db_path, parent=None):
        super().__init__(parent)
        self.args = args

    def start(self):
        _FakeJob.started.append(self.args)
        self.finished.emit({"classification": {"tagged": 7}}, "")

    def kill(self):
        pass


def test_lexicon_editor(qtbot, service, monkeypatch, tmp_path):
    from exchange_ui.app import make_app
    from exchange_ui.service import LibraryService

    make_app([])
    svc = LibraryService(service.db_path, load_definitions(include_user_dir=False), user_dir=tmp_path / "user")
    win = main_window.MainWindow(svc)
    qtbot.addWidget(win)
    dialog = win.open_settings("category")
    qtbot.addWidget(dialog)
    assert dialog.current_id() == "category" and dialog.table.rowCount() > 50
    dialog.value.setCurrentText("Food")
    dialog.word.setText("cruller")
    dialog.add_word()
    assert "cruller" in (tmp_path / "user" / "lexicons" / "category.toml").read_text(encoding="utf-8")
    row = next(r for r in range(dialog.table.rowCount()) if dialog.table.item(r, 1).text() == "cruller")
    dialog.table.selectRow(row)
    dialog.remove_selected()
    assert not any(dialog.table.item(r, 1).text() == "cruller" for r in range(dialog.table.rowCount()))
    win.undo()  # lexicon edits are undoable too
    dialog.reload()
    assert any(dialog.table.item(r, 1).text() == "cruller" for r in range(dialog.table.rowCount()))

    # Authors: words scans found are marked, and apply regroups.
    dialog.select("authors")
    found = [dialog.table.item(r, 2).text() for r in range(dialog.table.rowCount())]
    assert found and set(found) == {"found by scans"}
    monkeypatch.setattr(main_window, "CliJob", _FakeJob)
    dialog.apply()
    assert _FakeJob.started[-1] == ["classify"]  # only category words changed
    dialog.value.setCurrentText("Somebody")
    dialog.word.setText("Somebody")
    dialog.add_word()
    dialog.apply()
    assert _FakeJob.started[-1] == ["classify", "--regroup"]
    assert "Lexicons applied · 7 assets tagged" in win.status.text()
    svc.close()


def test_changes_are_detected(qtbot, window, mixed):
    if not window.watcher.available:
        return
    with qtbot.waitSignal(window.watcher.changed, timeout=10_000):
        write(mixed / "Loose" / "new_thing.glb", b"glTF")
    assert window.rescan_button.text() == "Rescan changed (1)"
    env = next(window.sidebar_model.index(r, 0) for r in range(window.sidebar_model.rowCount())
               if window.sidebar_model.index(r, 0).data(KIND) == "environment"
               and window.sidebar_model.index(r, 0).data(main_window.ENV_ID) in window.watcher.changed_environments)
    assert "changes detected" in env.data(DETAIL)
    window.watcher.clear()
    window._changes_shown()
    assert window.rescan_button.text() == "Rescan changed"
    window.watcher.stop()
