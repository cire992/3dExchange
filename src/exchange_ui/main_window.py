"""The main window: search bar, sidebar, browser grid, inspector and scan status.

Edits (inspector, context menus, drag and drop) go through ``LibraryService.edit`` and are
undoable with Ctrl+Z / Ctrl+Y for the session; each is also kept in the dossier's history.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import QItemSelectionModel, QModelIndex, QPoint, QProcess, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QCursor, QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListView,
    QMainWindow,
    QMenu,
    QProgressBar,
    QPushButton,
    QSplitter,
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)

from exchange.library.query import Brick
from exchange_ui import theme
from exchange_ui.delegates import BRICK_SIZE, BrickDelegate, SidebarDelegate
from exchange_ui.inspector import Inspector
from exchange_ui.models import BRICK, COLLECTION_UID, KIND, BrowserModel, SidebarModel, filter_for
from exchange_ui.scanning import ScanRunner
from exchange_ui.service import EditError, Filter, LibraryService
from exchange_ui.views import BrickGrid, SidebarTree
from exchange_ui.wizard import AddEnvironmentsDialog

_PHASES = {1: "Discovery", 2: "Identification", 3: "Enrichment"}
SEARCH_HINT = "Search assets — try  marius type:daz_morph  or  env:skyrim_se -is:product"


class MainWindow(QMainWindow):
    def __init__(self, service: LibraryService, runner: ScanRunner | None = None) -> None:
        super().__init__()
        self.service = service
        self.runner = runner or ScanRunner(service.db_path, self)
        self.setWindowTitle("Exchange")
        self.resize(1440, 900)

        self.sidebar_model = SidebarModel(service, self)
        self.browser_model = BrowserModel(service, self)
        self.filter = Filter()

        central = QWidget()
        central.setObjectName("central")
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._topbar())
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(1)
        splitter.addWidget(self._sidebar())
        splitter.addWidget(self._center())
        self.inspector = Inspector()
        splitter.addWidget(self.inspector)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([250, 830, 360])
        root.addWidget(splitter, 1)
        root.addWidget(self._statusbar())
        self.setCentralWidget(central)

        self.search_timer = QTimer(self, singleShot=True, interval=300)
        self.search_timer.timeout.connect(self._apply_search)
        self.search.textChanged.connect(lambda _: self.search_timer.start())
        QShortcut(QKeySequence.StandardKey.Find, self, activated=self.search.setFocus)
        QShortcut(QKeySequence(Qt.Key.Key_F5), self, activated=self.rescan)
        QShortcut(QKeySequence.StandardKey.Undo, self, activated=self.undo)
        for keys in ("Ctrl+Y", "Ctrl+Shift+Z"):
            QShortcut(QKeySequence(keys), self, activated=self.redo)

        self.inspector.edited.connect(self._on_field_edit)
        self.inspector.tagsChanged.connect(self._on_tags)
        self.inspector.tagReverted.connect(self._on_tag_revert)
        self.inspector.collectionChanged.connect(self._on_collection_member)
        self.inspector.suggestionDecided.connect(self._on_suggestion)
        self.inspector.historyUndo.connect(self._on_history_undo)
        self._set_choices()

        self.browser_model.totalChanged.connect(self._update_header)
        self.browser_model.error.connect(self._show_search_error)
        self.runner.progress.connect(self._on_progress)
        self.runner.finished.connect(self._on_scan_finished)
        self.runner.runningChanged.connect(self._on_running)
        self.refresh()

    # Building ---------------------------------------------------------------------------------

    def _topbar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("topbar")
        bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(10)
        logo = QLabel("⇄")
        logo.setStyleSheet(f"color: {theme.ACCENT}; font-size: 15pt;")
        name = QLabel("Exchange")
        name.setObjectName("appName")
        layout.addWidget(logo)
        layout.addWidget(name)
        layout.addSpacing(30)
        self.search = QLineEdit()
        self.search.setPlaceholderText(SEARCH_HINT)
        self.search.setClearButtonEnabled(True)
        layout.addWidget(self.search, 1)
        layout.addSpacing(16)
        self.add_button = QPushButton("+  Add environment")
        self.add_button.setObjectName("primary")
        self.add_button.setToolTip("Find environments on this PC or in a folder, review them, then scan (read-only)")
        self.add_button.clicked.connect(lambda: self.add_environment())
        self.rescan_button = QPushButton("Rescan changed")
        self.rescan_button.setToolTip("Rescan known environments; only what changed is reprocessed (F5)")
        self.rescan_button.clicked.connect(self.rescan)
        settings = QPushButton("⚙")
        settings.setEnabled(False)
        settings.setToolTip("Settings arrive with the add-environment wizard")
        for button in (self.add_button, self.rescan_button, settings):
            layout.addWidget(button)
        return bar

    def _sidebar(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("sidebar")
        panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        panel.setMinimumWidth(220)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 6, 8, 10)
        self.tree = SidebarTree()
        self.tree.setObjectName("sidebarTree")
        self.tree.setHeaderHidden(True)
        self.tree.setModel(self.sidebar_model)
        self.tree.setItemDelegate(SidebarDelegate(self.tree))
        self.tree.setIndentation(14)
        self.tree.setAnimated(True)
        self.tree.setMouseTracking(True)
        self.tree.selectionModel().currentChanged.connect(self._on_sidebar)
        self.tree.droppedOnCollection.connect(self._on_collection_drop)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(
            lambda pos: self.build_sidebar_menu(self.tree.indexAt(pos)).exec(self.tree.viewport().mapToGlobal(pos)))
        layout.addWidget(self.tree, 1)
        self.unidentified_button = QPushButton("⚠  Unidentified")
        self.unidentified_button.setObjectName("unidentified")
        self.unidentified_button.setCheckable(True)
        self.unidentified_button.toggled.connect(self._on_unidentified)
        layout.addWidget(self.unidentified_button)
        return panel

    def _center(self) -> QWidget:
        center = QWidget()
        layout = QVBoxLayout(center)
        layout.setContentsMargins(18, 14, 10, 0)
        layout.setSpacing(4)
        header = QHBoxLayout()
        titles = QVBoxLayout()
        titles.setSpacing(2)
        self.breadcrumb = QLabel()
        self.breadcrumb.setObjectName("breadcrumb")
        self.title = QLabel("All assets")
        self.title.setObjectName("title")
        self.subtitle = QLabel()
        self.subtitle.setObjectName("subtitle")
        self.search_error = QLabel()
        self.search_error.setObjectName("error")
        self.search_error.hide()
        for widget in (self.breadcrumb, self.title, self.subtitle, self.search_error):
            titles.addWidget(widget)
        header.addLayout(titles, 1)
        self.group_buttons = QButtonGroup(self)
        segments = QHBoxLayout()
        segments.setSpacing(0)
        for label, group in (("By product", "product"), ("By type", "type")):
            button = QPushButton(label)
            button.setObjectName("segment")
            button.setCheckable(True)
            button.setProperty("group", group)
            button.setChecked(group == "product")
            self.group_buttons.addButton(button)
            segments.addWidget(button)
        self.group_buttons.buttonClicked.connect(self._on_group)
        header.addLayout(segments)
        layout.addLayout(header)

        self.grid = BrickGrid()
        self.grid.setViewMode(QListView.ViewMode.IconMode)
        self.grid.setResizeMode(QListView.ResizeMode.Adjust)
        self.grid.setMovement(QListView.Movement.Static)
        self.grid.setUniformItemSizes(True)
        self.grid.setGridSize(BRICK_SIZE)
        self.grid.setMouseTracking(True)
        self.grid.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.grid.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.grid.setModel(self.browser_model)
        self.grid.setItemDelegate(BrickDelegate(self.grid))
        self.grid.selectionModel().selectionChanged.connect(lambda *_: self._on_selection())
        self.grid.dropped.connect(self._on_drop)
        self.grid.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.grid.customContextMenuRequested.connect(self._context_menu)
        self.grid.doubleClicked.connect(self._on_double_click)

        self.empty = QLabel()
        self.empty.setObjectName("subtitle")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setWordWrap(True)
        stack_host = QWidget()
        self.stack = QStackedLayout(stack_host)
        self.stack.addWidget(self.grid)
        self.stack.addWidget(self.empty)
        layout.addSpacing(8)
        layout.addWidget(stack_host, 1)
        return center

    def _statusbar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("statusbar")
        bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(14, 6, 14, 6)
        self.status = QLabel("Scans are read-only: Exchange never changes files in your environments while indexing.")
        self.status.setObjectName("muted")
        self.progress = QProgressBar()
        self.progress.setFixedWidth(180)
        self.progress.setTextVisible(False)
        self.progress.hide()
        self.stop_button = QPushButton("Stop")
        self.stop_button.hide()
        self.stop_button.clicked.connect(self.runner.stop)
        layout.addWidget(self.status, 1)
        layout.addWidget(self.progress)
        layout.addWidget(self.stop_button)
        return bar

    # Data -------------------------------------------------------------------------------------

    def refresh(self) -> None:
        """Reload counts and the current page, keeping the sidebar selection when possible."""
        current = self.tree.currentIndex()
        key = (current.data(KIND), current.data(Qt.ItemDataRole.DisplayRole)) if current.isValid() else None
        selected = self.selected_uids()
        self.sidebar_model.reload()
        self._set_choices()
        self.tree.expandToDepth(0)
        self.unidentified_button.setText(f"⚠  Unidentified    {self.sidebar_model.unidentified:,}")
        self.unidentified_button.setToolTip(
            f"{self.sidebar_model.unidentified:,} dossiers below the confidence threshold; "
            f"{self.sidebar_model.unattached:,} files belong to no asset yet")
        target = self._find_sidebar(key) if key else None
        target = target or self._find_sidebar(("all", "All assets"))
        if target is not None and not self.unidentified_button.isChecked() and not self.filter.parent_uid:
            self.tree.selectionModel().setCurrentIndex(target, QItemSelectionModel.SelectionFlag.ClearAndSelect)
            self.filter = filter_for(target, self.filter)
        self.browser_model.set_filter(self.filter)
        self._select(selected)

    def _set_choices(self) -> None:
        """What the inspector's editors offer: dossier types, tag names, manual collections."""
        defs = self.service.definitions
        self.inspector.types = sorted(((t.id, t.name) for t in defs.dossier_types.values()), key=lambda t: t[1].casefold())
        self.inspector.tag_names = sorted({term.value for lex in defs.lexicons.values() if lex.kind == "category"
                                           for term in lex.terms})
        self.inspector.manual_collections = [(c["uid"], c["name"]) for c in self.service.collections() if not c["smart"]]

    def selected_uids(self) -> list[str]:
        rows = sorted(i.row() for i in self.grid.selectionModel().selectedIndexes())
        return [b.uid for r in rows if (b := self.browser_model.brick(r))]

    def _select(self, uids: list[str]) -> None:
        """Select these dossiers again after a reload (those still on the loaded page)."""
        model, selection = self.browser_model, self.grid.selectionModel()
        rows = [r for uid in uids if (r := model.row_of(uid)) is not None]
        if not rows:
            return
        selection.setCurrentIndex(model.index(rows[0], 0), QItemSelectionModel.SelectionFlag.ClearAndSelect)
        for r in rows[1:]:
            selection.select(model.index(r, 0), QItemSelectionModel.SelectionFlag.Select)

    def _find_sidebar(self, key: tuple) -> QModelIndex | None:
        model = self.sidebar_model
        stack = [model.index(r, 0) for r in range(model.rowCount())]
        while stack:
            index = stack.pop(0)
            if (index.data(KIND), index.data(Qt.ItemDataRole.DisplayRole)) == key:
                return index
            stack.extend(model.index(r, 0, index) for r in range(model.rowCount(index)))
        return None

    def _on_sidebar(self, index: QModelIndex, previous: QModelIndex) -> None:
        if not index.isValid() or index.data(KIND) == "section":
            return
        if index.data(KIND) == "new_collection":
            # Not a view: ask for a name, then show the new collection (or go back).
            back = QModelIndex(previous) if previous.isValid() else None
            QTimer.singleShot(0, lambda: self.new_collection() or (back is not None and self.tree.setCurrentIndex(back)))
            return
        if self.unidentified_button.isChecked():
            self.unidentified_button.blockSignals(True)
            self.unidentified_button.setChecked(False)
            self.unidentified_button.blockSignals(False)
        self.filter = filter_for(index, self.filter)
        self.browser_model.set_filter(self.filter)

    def _on_unidentified(self, checked: bool) -> None:
        if checked:
            self.tree.selectionModel().clearSelection()
        self.filter = Filter(query=self.filter.query, group=self.filter.group, unidentified=checked)
        self.browser_model.set_filter(self.filter)

    def _on_group(self, button: QPushButton) -> None:
        self.filter.group = button.property("group")
        self.browser_model.set_filter(self.filter)

    def _apply_search(self) -> None:
        self.filter.query = self.search.text().strip()
        self.browser_model.set_filter(self.filter)

    def _show_search_error(self, message: str) -> None:
        self.search_error.setText(message)
        self.search_error.setVisible(bool(message))

    def _update_header(self, total: int) -> None:
        index = self.tree.currentIndex()
        if self.filter.parent_uid:
            crumb, title = "Product contents · click the sidebar to go back", self.filter.parent_name
        elif self.filter.collection_uid:
            crumb, title = "Collection", self.filter.collection_name
        elif self.filter.unidentified:
            crumb, title = "Library", "Unidentified"
        elif index.isValid() and index.data(KIND) not in (None, "all", "section"):
            kind = index.data(KIND)
            env = index
            while env.parent().isValid():
                env = env.parent()
            crumb = {"environment": "Environments", "group": env.data(), "container": env.data(),
                     "type": f"{env.data()} › Dossier type"}.get(kind, "")
            title = index.data()
        else:
            crumb, title = "Library", "All assets"
        for button in self.group_buttons.buttons():
            button.setEnabled(self.filter.effective_group() == self.filter.group and not self.filter.parent_uid)
        self.breadcrumb.setText(crumb)
        self.title.setText(title)
        if self.filter.effective_group() == "product" and not self.filter.parent_uid:
            noun = "product or standalone asset" if total == 1 else "products and standalone assets"
        else:
            noun = "asset" if total == 1 else "assets"
        searched = f" matching “{self.filter.query}”" if self.filter.query else ""
        self.subtitle.setText(f"{total:,} {noun}{searched}")
        if total == 0:
            if not self.sidebar_model.service.sidebar()["environments"]:
                self.empty.setText("No environments yet.\n\nClick “Add environment” and choose a folder: a Daz "
                                   "library, an MO2 instance, an Unreal project or any folder of assets.")
            elif self.filter.collection_uid and not self.filter.query:
                self.empty.setText("This collection is empty.\n\nDrag assets onto it in the sidebar, or right-click "
                                   "assets and choose “Add to collection”.")
            else:
                self.empty.setText("Nothing here matches.")
            self.stack.setCurrentWidget(self.empty)
        else:
            self.stack.setCurrentWidget(self.grid)
        self.inspector.show_detail(None)

    def _on_double_click(self, index: QModelIndex) -> None:
        brick = index.data(BRICK)
        if brick is not None and brick.children:
            self.open_product(brick.uid, brick.name)
        else:
            self._open_in_app(index)

    def open_product(self, uid: str, name: str) -> None:
        """Show one product's contents; any sidebar click goes back."""
        self.filter = Filter(query=self.filter.query, group=self.filter.group, parent_uid=uid, parent_name=name)
        self.browser_model.set_filter(self.filter)

    def _on_selection(self) -> None:
        uids = self.selected_uids()
        if len(uids) > 1:
            self.inspector.show_bulk(uids)
        else:
            self.inspector.show_detail(self.service.detail(uids[0]) if uids else None)

    # Context menu -----------------------------------------------------------------------------

    def _context_menu(self, pos: QPoint) -> None:
        index = self.grid.indexAt(pos)
        if not index.isValid():
            return
        if not self.grid.selectionModel().isSelected(index):
            self.grid.setCurrentIndex(index)  # right-click outside the selection selects that brick
        self.build_context_menu(index).exec(self.grid.viewport().mapToGlobal(pos))

    def build_context_menu(self, index: QModelIndex) -> QMenu:
        """Actions for the selected bricks (``index`` is the one right-clicked)."""
        menu = QMenu(self)
        menu.setToolTipsVisible(True)
        clicked: Brick = index.data(BRICK)
        uids = self.selected_uids() or [clicked.uid]
        many = len(uids) > 1
        if not many:
            menu.addAction("Rename…", lambda: self.rename(clicked.uid, clicked.name))
        add = menu.addMenu("Add to collection")
        for c in self.service.collections():
            if not c["smart"]:
                add.addAction(c["name"], lambda cid=c["uid"]: self._edit(
                    "add to collection", lambda cur: cur.add_to_collection(cid, uids), scope="collections"))
        add.addSeparator()
        add.addAction("New collection…", lambda: self.new_collection(members=uids))
        if self.filter.collection_uid and not self._smart(self.filter.collection_uid):
            cid, name = self.filter.collection_uid, self.filter.collection_name
            menu.addAction(f"Remove from “{name}”", lambda: self._edit(
                "remove from collection", lambda cur: cur.remove_from_collection(cid, uids), scope="collections"))
        menu.addAction("Put into a new product…", lambda: self.new_product(uids))
        if self.filter.parent_uid:
            menu.addAction(f"Take out of “{self.filter.parent_name}”", lambda: self._edit(
                "take out of product", lambda cur: cur.set_parent(uids, None), scope="all"))
        if many:
            target = clicked.uid if clicked.uid in uids else uids[0]
            name = clicked.name if clicked.uid in uids else self.browser_model.brick(self.browser_model.row_of(target)).name
            menu.addAction(f"Merge the others into “{name}”", lambda: self.merge([u for u in uids if u != target], target))
        menu.addSeparator()
        menu.addAction("Show in folder", lambda: self._show_in_folder(index))
        menu.addAction("Open in app", lambda: self._open_in_app(index))
        menu.addSeparator()
        for label, phase in (("Requisition to…", 4), ("Copy to…", 5), ("Extract", 5)):
            action = QAction(label, menu)
            action.setEnabled(False)
            action.setToolTip(f"Arrives in Roadmap phase {phase}")
            menu.addAction(action)
        return menu

    def build_sidebar_menu(self, index: QModelIndex) -> QMenu:
        menu = QMenu(self)
        menu.addAction("New collection…", lambda: self.new_collection())
        query = self.search.text().strip()
        save = menu.addAction("Save this search as a smart collection…",
                              lambda: self.new_collection(query=query))
        save.setEnabled(bool(query))
        if index.isValid() and index.data(KIND) == "collection":
            cid, name = index.data(COLLECTION_UID), index.data()
            menu.addSeparator()
            menu.addAction(f"Delete “{name}”", lambda: self._edit(
                f"delete collection {name}", lambda cur: cur.delete_collection(cid), scope="collections"))
        return menu

    # Editing ----------------------------------------------------------------------------------

    def ask_text(self, title: str, label: str, text: str = "") -> str | None:
        """A line of text from the user, or None if cancelled (tests replace this)."""
        value, ok = QInputDialog.getText(self, title, label, text=text)
        return value.strip() if ok and value.strip() else None

    def _say(self, text: str, error: bool = False) -> None:
        self.status.setText(text)
        self.status.setObjectName("error" if error else "muted")
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)

    def _edit(self, label: str, fn, *, scope: str = "detail"):
        """Make an undoable edit, then refresh what it can have changed.

        ``scope``: "detail" (the page and inspector), "collections" (also the sidebar's
        collections) or "all" (also the sidebar counts: merges, products, accepted suggestions).
        Returns the curator's result, or None if the edit failed (the reason is in the status bar).
        """
        try:
            result = self.service.edit(label, fn)
        except EditError as exc:
            self._say(str(exc), error=True)
            return None
        self._say(f"Done: {label} · Ctrl+Z undoes it")
        self._after_edit(scope)
        return result

    def _after_edit(self, scope: str) -> None:
        if scope == "all":
            self.refresh()
            return
        if scope == "collections":
            self._reload_collections()
            self._set_choices()
        selected = self.selected_uids()
        self.browser_model.reload()
        self._select(selected)

    def _reload_collections(self) -> None:
        """Rebuild the sidebar's collection rows without the selection wandering to another row."""
        current = self.tree.currentIndex()
        key = (current.data(KIND), current.data()) if current.isValid() else None
        selection = self.tree.selectionModel()
        selection.blockSignals(True)
        self.sidebar_model.reload_collections()
        again = self._find_sidebar(key) if key else None  # collection names are unique
        if again is not None:
            selection.setCurrentIndex(again, QItemSelectionModel.SelectionFlag.ClearAndSelect)
        selection.blockSignals(False)
        if again is None and key:  # the collection being shown was deleted
            self.tree.setCurrentIndex(self._find_sidebar(("all", "All assets")))

    def undo(self) -> None:
        try:
            label = self.service.undo()
        except EditError as exc:
            self._say(str(exc), error=True)
            return
        self._say(f"Undid: {label} · Ctrl+Y redoes it" if label else "Nothing to undo in this session")
        if label:
            self.refresh()

    def redo(self) -> None:
        try:
            label = self.service.redo()
        except EditError as exc:
            self._say(str(exc), error=True)
            return
        self._say(f"Redid: {label} · Ctrl+Z undoes it" if label else "Nothing to redo")
        if label:
            self.refresh()

    def _smart(self, collection_uid: str) -> bool:
        return any(c["uid"] == collection_uid and c["smart"] for c in self.service.collections())

    def rename(self, uid: str, name: str) -> None:
        new = self.ask_text("Rename", "Name:", name)
        if new and new != name:
            self._edit(f"rename to {new}", lambda cur: cur.set_field(uid, "name", new))

    def new_collection(self, query: str | None = None, members: list[str] | None = None) -> str | None:
        """Ask for a name and make a collection (smart if ``query``); returns its uid."""
        name = self.ask_text("New smart collection" if query else "New collection",
                             f"Name for the saved search “{query}”:" if query else "Name:")
        if not name:
            return None
        result = self._edit(f"new collection {name}", lambda cur: cur.create_collection(name, query),
                            scope="collections")
        if result is None:
            return None
        uid = result[1]
        if members:
            self._edit(f"add to {name}", lambda cur: cur.add_to_collection(uid, members), scope="collections")
            return uid
        index = next((self.sidebar_model.index(r, 0) for r in range(self.sidebar_model.rowCount())
                      if self.sidebar_model.index(r, 0).data(COLLECTION_UID) == uid), None)
        if index is not None:
            self.tree.setCurrentIndex(index)
        return uid

    def new_product(self, uids: list[str]) -> None:
        name = self.ask_text("New product", f"Name for a product holding {len(uids)} asset{'s' * (len(uids) != 1)}:")
        if name:
            self._edit(f"new product {name}", lambda cur: cur.create_product(name, uids), scope="all")

    def merge(self, uids: list[str], target: str) -> None:
        """Merge dossiers into ``target`` (the same asset found more than once); one undo step each."""
        for uid in uids:
            if self._edit("merge", lambda cur, u=uid: cur.merge(u, target), scope="detail") is None:
                break
        self.refresh()

    def _on_field_edit(self, uids: list[str], field: str, value) -> None:
        what = f"revert {field}" if value is None else f"set {field.replace('_id', '')}"
        self._edit(what, lambda cur: cur.set_field(uids, field, value), scope="all" if field == "type_id" else "detail")

    def _on_tags(self, uids: list[str], add: list[str], remove: list[str]) -> None:
        label = " / ".join(filter(None, [add and f"tag {', '.join(add)}", remove and f"remove tag {', '.join(remove)}"]))
        self._edit(label, lambda cur: cur.tag(uids, add, remove))

    def _on_tag_revert(self, uids: list[str], tag: str) -> None:
        self._edit(f"revert tag {tag}", lambda cur: cur.revert_tag(uids[0], tag))

    def _on_collection_member(self, uids: list[str], collection_uid: str, member: bool) -> None:
        self._edit("add to collection" if member else "remove from collection",
                   lambda cur: cur.add_to_collection(collection_uid, uids, member), scope="collections")

    def _on_collection_drop(self, collection_uid: str, uids: list[str]) -> None:
        self._on_collection_member(uids, collection_uid, True)

    def _on_suggestion(self, suggestion_id: int, accept: bool) -> None:
        if accept:
            self._edit("accept suggestion", lambda cur: cur.accept(suggestion_id), scope="all")
        else:
            self._edit("reject suggestion", lambda cur: cur.reject(suggestion_id))

    def _on_history_undo(self, log_id: int, what: str) -> None:
        self._edit(f"undo “{what}”", lambda cur: cur.undo(log_id), scope="all")

    # Drag and drop ----------------------------------------------------------------------------

    def _on_drop(self, index: QModelIndex, uids: list[str], paths: list[str]) -> None:
        target: Brick = index.data(BRICK)
        if paths:
            self.link_paths(target, paths)
        elif uids:
            self.build_drop_menu(target, uids).exec(QCursor.pos())

    def build_drop_menu(self, target: Brick, uids: list[str]) -> QMenu:
        """What dropping bricks on ``target`` can mean."""
        menu = QMenu(self)
        n = f"{len(uids)} asset{'s' * (len(uids) != 1)}"
        if target.type_id == "product":
            menu.addAction(f"Put {n} into “{target.name}”", lambda: self._edit(
                f"put into {target.name}", lambda cur: cur.set_parent(uids, target.uid), scope="all"))
        menu.addAction(f"Link their files to “{target.name}”", lambda: self.link_dossiers(target, uids))
        menu.addAction(f"Merge {n} into “{target.name}” (the same asset)", lambda: self.merge(uids, target.uid))
        menu.addSeparator()
        menu.addAction("Cancel")
        return menu

    def link_dossiers(self, target: Brick, uids: list[str]) -> None:
        """Link the files of dragged dossiers (e.g. textures) onto ``target`` (e.g. a mesh)."""
        files = list(dict.fromkeys(f for uid in uids for f in self.service.files_of(uid)))
        self._edit(f"link files to {target.name}", lambda cur: cur.link_files(target.uid, files), scope="all")

    def link_paths(self, target: Brick, paths: list[str]) -> None:
        """Link files dropped from Explorer; they must be files Exchange has scanned."""
        keys, outside = [], []
        for path in paths:
            key = self.service.file_key(path) if Path(path).is_file() else None
            (keys if key else outside).append(key or Path(path).name)
        if outside:
            self._say(f"Only scanned files can be linked; not in an environment (or a folder): {', '.join(outside)}",
                      error=True)
            return
        self._edit(f"link files to {target.name}", lambda cur: cur.link_files(target.uid, keys), scope="all")

    def primary_path(self, index: QModelIndex) -> str | None:
        brick = index.data(BRICK)
        detail = self.service.detail(brick.uid) if brick else None
        for ledger in (detail or {}).get("ledgers", []):
            for entry in ledger["entries"]:
                if entry["status"] == "retired":
                    continue
                for f in entry["files"]:
                    if f["role"] == "primary" and Path(f["path"]).exists():
                        return f["path"]
                if entry["files"]:
                    return entry["files"][0]["path"]
        return None

    def _show_in_folder(self, index: QModelIndex) -> None:
        path = self.primary_path(index)
        if not path:
            return
        if sys.platform == "win32":
            QProcess.startDetached("explorer.exe", [f"/select,{os.path.normpath(path)}"])
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).parent)))

    def _open_in_app(self, index: QModelIndex) -> None:
        path = self.primary_path(index)
        if path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    # Scanning ---------------------------------------------------------------------------------

    def add_environment(self, places=None) -> AddEnvironmentsDialog:
        """Open the add-environment wizard; a scan it starts continues after it closes."""
        dialog = AddEnvironmentsDialog(self.service, self.runner, self, places=places)
        dialog.reviewUnidentified.connect(lambda: self.unidentified_button.setChecked(True))
        dialog.open()
        return dialog

    def scan_folder(self, folder: Path) -> None:
        self.status.setText(f"Detecting environments in {folder} …")
        self.runner.scan(folder)

    def rescan(self) -> None:
        self.status.setText("Rescanning known environments …")
        self.runner.rescan()

    def _on_running(self, running: bool) -> None:
        self.add_button.setEnabled(not running)
        self.rescan_button.setEnabled(not running)
        self.progress.setVisible(running)
        self.stop_button.setVisible(running)
        self.progress.setRange(0, 0)

    def _on_progress(self, event: dict) -> None:
        phase = event.get("phase", 0)
        done, total = event.get("done", 0), event.get("total", 0)
        count = f" {done:,} / {total:,}" if total else ""
        self.status.setText(f"Scanning {event.get('environment')} · Phase {phase} of 3 · "
                            f"{_PHASES.get(phase, '')} · {event.get('step')}{count}")
        if total:
            self.progress.setRange(0, total)
            self.progress.setValue(done)
        else:
            self.progress.setRange(0, 0)
        if phase == 3 and event.get("step") == "hashing" and done == 0:
            self.refresh()  # identification finished: products can appear now

    def _on_scan_finished(self, report: dict, error: str) -> None:
        envs = report.get("environments", [])
        if error:
            self.status.setText(error)
            self.status.setObjectName("error" if "stopped" not in error else "muted")
        else:
            self.status.setObjectName("muted")
            products = sum((r.get("identification") or {}).get("products", 0)
                           for e in envs for r in e.get("roots", []))
            offline = [r["path"] for e in envs for r in e.get("roots", []) if r.get("status") == "offline"]
            text = f"Scan finished · {len(envs)} environment{'s' * (len(envs) != 1)} · {products:,} products"
            if offline:
                text += f" · {len(offline)} offline"
            notes = report.get("notes") or []
            self.status.setText(" · ".join([text, *notes]))
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)
        self.refresh()

    def closeEvent(self, event) -> None:
        self.search_timer.stop()
        if self.runner.running:
            self.runner.stop()
        super().closeEvent(event)
