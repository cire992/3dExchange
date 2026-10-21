"""The main window: search bar, sidebar, browser grid, inspector and scan status."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import QItemSelectionModel, QModelIndex, QPoint, QProcess, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QMainWindow,
    QMenu,
    QProgressBar,
    QPushButton,
    QSplitter,
    QStackedLayout,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from exchange_ui import theme
from exchange_ui.delegates import BRICK_SIZE, BrickDelegate, SidebarDelegate
from exchange_ui.inspector import Inspector
from exchange_ui.models import BRICK, KIND, BrowserModel, SidebarModel, filter_for
from exchange_ui.scanning import ScanRunner
from exchange_ui.service import Filter, LibraryService
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
        self.tree = QTreeView()
        self.tree.setObjectName("sidebarTree")
        self.tree.setHeaderHidden(True)
        self.tree.setModel(self.sidebar_model)
        self.tree.setItemDelegate(SidebarDelegate(self.tree))
        self.tree.setIndentation(14)
        self.tree.setAnimated(True)
        self.tree.setMouseTracking(True)
        self.tree.selectionModel().currentChanged.connect(self._on_sidebar)
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

        self.grid = QListView()
        self.grid.setViewMode(QListView.ViewMode.IconMode)
        self.grid.setResizeMode(QListView.ResizeMode.Adjust)
        self.grid.setMovement(QListView.Movement.Static)
        self.grid.setUniformItemSizes(True)
        self.grid.setGridSize(BRICK_SIZE)
        self.grid.setMouseTracking(True)
        self.grid.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.grid.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.grid.setModel(self.browser_model)
        self.grid.setItemDelegate(BrickDelegate(self.grid))
        self.grid.selectionModel().currentChanged.connect(self._on_brick)
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
        self.sidebar_model.reload()
        self.tree.expandToDepth(0)
        self.unidentified_button.setText(f"⚠  Unidentified    {self.sidebar_model.unidentified:,}")
        self.unidentified_button.setToolTip(
            f"{self.sidebar_model.unidentified:,} dossiers below the confidence threshold; "
            f"{self.sidebar_model.unattached:,} files belong to no asset yet")
        target = self._find_sidebar(key) if key else None
        target = target or self._find_sidebar(("all", "All assets"))
        if target is not None and not self.unidentified_button.isChecked():
            self.tree.selectionModel().setCurrentIndex(target, QItemSelectionModel.SelectionFlag.ClearAndSelect)
            self.filter = filter_for(target, self.filter)
        self.browser_model.set_filter(self.filter)

    def _find_sidebar(self, key: tuple) -> QModelIndex | None:
        model = self.sidebar_model
        stack = [model.index(r, 0) for r in range(model.rowCount())]
        while stack:
            index = stack.pop(0)
            if (index.data(KIND), index.data(Qt.ItemDataRole.DisplayRole)) == key:
                return index
            stack.extend(model.index(r, 0, index) for r in range(model.rowCount(index)))
        return None

    def _on_sidebar(self, index: QModelIndex, _previous: QModelIndex) -> None:
        if not index.isValid() or index.data(KIND) == "section":
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

    def _on_brick(self, index: QModelIndex, _previous: QModelIndex) -> None:
        brick = index.data(BRICK) if index.isValid() else None
        self.inspector.show_detail(self.service.detail(brick.uid) if brick else None)

    # Context menu -----------------------------------------------------------------------------

    def _context_menu(self, pos: QPoint) -> None:
        index = self.grid.indexAt(pos)
        if not index.isValid():
            return
        self.grid.setCurrentIndex(index)
        menu = QMenu(self)
        menu.addAction("Show in folder", lambda: self._show_in_folder(index))
        menu.addAction("Open in app", lambda: self._open_in_app(index))
        menu.addSeparator()
        for label, phase in (("Requisition to…", 4), ("Copy to…", 5), ("Extract", 5), ("Merge…", 3),
                             ("Add to collection", 3)):
            action = QAction(label, menu)
            action.setEnabled(False)
            action.setToolTip(f"Arrives in Roadmap phase {phase}")
            menu.addAction(action)
        menu.setToolTipsVisible(True)
        menu.exec(self.grid.viewport().mapToGlobal(pos))

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
