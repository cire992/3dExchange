"""Editing in the main window (Roadmap phase 3b): inspector, bulk edit, collections, drag and drop
menus, suggestions and undo/redo."""

import sqlite3

from PySide6.QtWidgets import QComboBox, QLineEdit, QMenu, QPushButton, QToolButton

from exchange.db import repository as repo
from exchange_ui.models import BRICK, COUNT, KIND
from exchange_ui.service import BUSY

from test_ui import bricks, find, select_brick


def action(menu: QMenu, text: str):
    """The action whose text starts with ``text``, searching submenus too."""
    for a in menu.actions():
        if a.text().startswith(text):
            return a
        if a.menu() is not None and (found := action(a.menu(), text)):
            return found
    return None


def field(window, uid, name):
    return repo.effective_fields(window.service.connection_for_tests(), uid).get(name)


def name_of(window, uid):
    return repo.effective_dossier(window.service.connection_for_tests(), uid)["name"]


def search(window, text):
    window.search.setText(text)
    window._apply_search()


def test_inspector_edits_revert_and_undo(window):
    select_brick(window, "Loose Boots")
    uid = window.inspector.targets[0]
    name = window.inspector.overview.findChild(QLineEdit, "nameEdit")
    name.setText("Cowboy Boots")
    name.editingFinished.emit()
    assert name_of(window, uid) == "Cowboy Boots"
    assert "Cowboy Boots" in bricks(window)
    assert window.inspector.detail["uid"] == uid  # still selected after the reload
    name = window.inspector.overview.findChild(QLineEdit, "nameEdit")
    assert name.property("overridden") is True and "Ctrl+Z" in window.status.text()

    notes = window.inspector.overview.findChild(QLineEdit, "licenseEdit")
    notes.setText("CC-BY 4.0")
    notes.editingFinished.emit()
    assert field(window, uid, "license") == "CC-BY 4.0"

    window.undo()
    assert field(window, uid, "license") is None and "Undid: set license" in window.status.text()
    window.redo()
    assert field(window, uid, "license") == "CC-BY 4.0"

    # The revert button next to an overridden field goes back to the scanned value.
    revert = next(b for b in window.inspector.overview.findChildren(QToolButton, "revert"))
    revert.click()  # the first is the name's
    assert name_of(window, uid) == "Loose Boots"

    # A dossier's history can undo any entry, from any session.
    entry = next(e for e in window.inspector.detail["history"] if e["action"] == "revert_field")
    window._on_history_undo(entry["id"], "reverted name")
    assert name_of(window, uid) == "Cowboy Boots"


def test_tags(window):
    select_brick(window, "Loose Boots")
    uid = window.inspector.targets[0]
    add = window.inspector.overview.findChild(QLineEdit, "addTag")
    add.setText("Western")
    add.returnPressed.emit()
    conn = window.service.connection_for_tests()
    assert "Western" in repo.effective_tags(conn, uid)
    chips = {b.text(): b for b in window.inspector.overview.findChildren(QPushButton) if "×" in b.text()}
    assert chips["Western  ×"].objectName() == "chipUser"
    scanned = next(t for t, b in chips.items() if b.objectName() == "chip")  # a tag the scan found
    chips[scanned].click()  # hides it
    tag = scanned.split("  ")[0]
    assert tag not in repo.effective_tags(conn, uid)
    hidden = next(b for b in window.inspector.overview.findChildren(QPushButton) if b.objectName() == "chipHidden")
    hidden.click()  # shows it again
    assert tag in repo.effective_tags(conn, uid)
    user = next(b for b in window.inspector.overview.findChildren(QPushButton) if b.text() == "Western  ×")
    user.click()
    assert "Western" not in repo.effective_tags(conn, uid)


def test_bulk_edit(window):
    search(window, "donut01")
    model = window.browser_model
    selection = window.grid.selectionModel()
    window.grid.selectAll()
    uids = window.selected_uids()
    assert len(uids) >= 2 and window.inspector.name.text() == f"{len(uids)} assets selected"
    assert not window.inspector.tabs.isTabEnabled(1)
    window.inspector.edited.emit(window.inspector.targets, "license", "Lard Lads internal")
    assert all(field(window, u, "license") == "Lard Lads internal" for u in uids)
    assert sorted(window.selected_uids()) == sorted(uids)  # the selection survives the edit
    window.inspector.tagsChanged.emit(window.inspector.targets, ["Snack"], [])
    conn = window.service.connection_for_tests()
    assert all("Snack" in repo.effective_tags(conn, u) for u in uids)
    window.undo()
    assert not any("Snack" in repo.effective_tags(conn, u) for u in uids)
    assert model.rowCount() and selection is window.grid.selectionModel()


def test_collections(window, monkeypatch):
    monkeypatch.setattr(window, "ask_text", lambda *a, **k: "Lard Lads")
    uid = window.new_collection()
    assert window.title.text() == "Lard Lads" and window.breadcrumb.text() == "Collection"
    assert "This collection is empty" in window.empty.text()

    window.tree.setCurrentIndex(find(window, "all", "All assets"))
    index = select_brick(window, "Loose Boots")
    boots = window.selected_uids()[0]
    action(window.build_context_menu(index), "Lard Lads").trigger()
    window._on_collection_drop(uid, [window.browser_model.brick(0).uid])  # dropped on the sidebar row
    window.tree.setCurrentIndex(find(window, "collection", "Lard Lads"))
    assert "Loose Boots" in bricks(window) and len(bricks(window)) == 2
    assert find(window, "collection", "Lard Lads").data(COUNT) == 2

    # Removing from the collection being viewed, via the context menu.
    index = select_brick(window, "Loose Boots")
    action(window.build_context_menu(index), "Remove from “Lard Lads”").trigger()
    assert "Loose Boots" not in bricks(window)
    window.undo()
    assert "Loose Boots" in bricks(window)

    # The inspector's collection chip removes too; its list adds.
    select_brick(window, "Loose Boots")
    chip = next(b for b in window.inspector.overview.findChildren(QPushButton) if b.text() == "Lard Lads  ×")
    chip.click()
    assert boots not in [b.uid for b in window.browser_model.bricks]

    # A smart collection saves the current search.
    monkeypatch.setattr(window, "ask_text", lambda *a, **k: "Donuts")
    search(window, "donut")
    action(window.build_sidebar_menu(find(window, "collection", "Lard Lads")), "Save this search").trigger()
    smart = find(window, "collection", "Donuts")
    assert smart.data(KIND) == "collection"
    action(window.build_sidebar_menu(smart), "Delete “Donuts”").trigger()
    assert window._find_sidebar(("collection", "Donuts")) is None


def test_products_merge_and_drop_menus(window, monkeypatch):
    search(window, "donut01 -is:product")
    blue = select_brick(window, "Donut01_Blue").data(BRICK)
    pink = window.browser_model.brick(window.browser_model.row_of(
        next(b.uid for b in window.browser_model.bricks if b.name == "Donut01_Pink")))
    monkeypatch.setattr(window, "ask_text", lambda *a, **k: "Donut box")
    window.new_product([blue.uid, pink.uid])
    conn = window.service.connection_for_tests()
    product = conn.execute("SELECT uid FROM dossier_effective WHERE name = 'Donut box'").fetchone()[0]
    assert window.service.detail(blue.uid)["parent"]["uid"] == product
    window.undo()
    assert (window.service.detail(blue.uid)["parent"] or {}).get("uid") != product

    # Dropping one brick on another: link its files, or merge (one undo step each).
    target = window.browser_model.brick(window.browser_model.row_of(pink.uid))
    menu = window.build_drop_menu(target, [blue.uid])
    assert action(menu, "Put") is None  # only a product takes dossiers in
    action(menu, "Merge 1 asset into “Donut01_Pink”").trigger()
    assert conn.execute("SELECT target_uid FROM dossier_alias WHERE alias_uid = ?", (blue.uid,)).fetchone()[0] == pink.uid
    window.undo()
    assert conn.execute("SELECT 1 FROM dossier_alias WHERE alias_uid = ?", (blue.uid,)).fetchone() is None


def test_link_dropped_files_and_accept_suggestion(window, mixed):
    select_brick(window, "Barrel01")
    barrel = window.inspector.detail
    [suggestion] = [s for s in barrel["suggestions"] if s["kind"] == "texture_link"]
    window._on_suggestion(suggestion["id"], True)
    files = {f["rel_path"].rsplit("/", 1)[-1] for l in window.inspector.detail["ledgers"]
             for e in l["entries"] for f in e["files"]}
    assert "Barrel01_N.png" in files

    # Files from Explorer: only scanned ones link.
    target = window.browser_model.brick(window.browser_model.row_of(barrel["uid"]))
    window.link_paths(target, [str(mixed.parent / "elsewhere.png")])
    assert "Only scanned files" in window.status.text()
    loose = next(p for p in (mixed / "Loose").rglob("*.png") if not p.stem.startswith("Barrel01"))
    window.link_paths(target, [str(loose)])
    assert "Done: link files" in window.status.text()


def test_edits_fail_politely_while_a_scan_writes(window, db_path):
    select_brick(window, "Loose Boots")
    blocker = sqlite3.connect(db_path)
    blocker.execute("BEGIN IMMEDIATE")  # what a scan holds while it identifies a root
    try:
        window.inspector.edited.emit(window.inspector.targets, "license", "MIT")
        assert window.status.text() == BUSY and window.status.objectName() == "error"
        assert window.service.undo_stack == []
    finally:
        blocker.rollback()
        blocker.close()
    window.inspector.edited.emit(window.inspector.targets, "license", "MIT")
    assert field(window, window.inspector.targets[0], "license") == "MIT"


def test_type_choices(window):
    select_brick(window, "Loose Boots")
    combo = window.inspector.overview.findChild(QComboBox, "typeEdit")
    mesh = combo.findData("mesh")
    assert mesh >= 0 and combo.currentData() == window.inspector.detail["type_id"]
    combo.activated.emit(mesh)
    assert window.inspector.detail is None or window.inspector.detail["type_id"] == "mesh"
