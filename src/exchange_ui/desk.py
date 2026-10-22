"""The Unidentified desk's panels beside the low-confidence grid: unattached files by folder, and
pending suggestions to accept or reject in batches.

Counting unattached files takes seconds in a big library (1.5M in the real Daz one), so folders
are counted one level at a time, on a background thread with its own read-only connection. The
panels only show and ask; the window makes the edits (and so they are undoable).
"""

from __future__ import annotations

import itertools

from PySide6.QtCore import QModelIndex, QObject, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from exchange.library.desk import unattached_files, unattached_folders
from exchange_ui.inspector import describe_suggestion
from exchange_ui.service import LibraryService

ROOT_ID = Qt.ItemDataRole.UserRole + 40
ENV_ID = Qt.ItemDataRole.UserRole + 41
PATH = Qt.ItemDataRole.UserRole + 42
COUNT = Qt.ItemDataRole.UserRole + 43
STATE = Qt.ItemDataRole.UserRole + 44  # "unloaded" | "loading" | "loaded"; None for leaves
MAX_FILES = 5000  # a product or link from more files than this is surely a whole category, not an asset
PREVIEW = 50


class _Signals(QObject):
    done = Signal(int, object)  # request id, result (or an Exception)


class _Job(QRunnable):
    def __init__(self, service: LibraryService, request: int, fn, signals: _Signals) -> None:
        super().__init__()
        self.service, self.request, self.fn, self.signals = service, request, fn, signals

    def run(self) -> None:
        conn = self.service.reader()
        try:
            result = self.fn(conn)
        except Exception as exc:  # reported in the panel, never raised in a worker thread
            result = exc
        finally:
            conn.close()
        self.signals.done.emit(self.request, result)


class UnattachedPanel(QWidget):
    """Folders holding files no asset has, with what to do about a folder."""

    makeProduct = Signal(int, int, str, int)  # root id, environment id, folder, file count
    linkFolder = Signal(int, str, int)  # root id, folder, file count
    ignoreFolder = Signal(int, str)  # environment id, folder

    def __init__(self, service: LibraryService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.service = service
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(2)
        self._signals = _Signals()
        self._signals.done.connect(self._done)
        self._requests = itertools.count(1)
        self._pending: dict[int, tuple[str, QStandardItem | None]] = {}

        self.model = QStandardItemModel(0, 2, self)
        self.model.setHorizontalHeaderLabels(["Folder", "Files"])
        self.tree = QTreeView()
        self.tree.setModel(self.model)
        self.tree.setUniformRowHeights(True)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tree.expanded.connect(self._expand)
        self.tree.selectionModel().currentChanged.connect(lambda index, _: self._select(index))

        side = QWidget()
        info = QVBoxLayout(side)
        info.setContentsMargins(12, 0, 0, 0)
        self.title = QLabel("Choose a folder")
        self.title.setObjectName("inspectorName")
        self.title.setWordWrap(True)
        self.count = QLabel()
        self.count.setObjectName("subtitle")
        self.count.setWordWrap(True)
        self.preview = QListWidget()
        self.product_button = QPushButton("Make a product from this folder…")
        self.product_button.setObjectName("primary")
        self.link_button = QPushButton("Link these files to an asset…")
        self.ignore_button = QPushButton("Not assets: ignore this folder")
        self.ignore_button.setToolTip("From now on, including at rescans. You can undo it.")
        self.product_button.clicked.connect(lambda: self._act("product"))
        self.link_button.clicked.connect(lambda: self._act("link"))
        self.ignore_button.clicked.connect(lambda: self._act("ignore"))
        info.addWidget(self.title)
        info.addWidget(self.count)
        info.addWidget(self.preview, 1)
        for button in (self.product_button, self.link_button, self.ignore_button):
            info.addWidget(button)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.tree)
        splitter.addWidget(side)
        splitter.setSizes([520, 320])
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(splitter)
        self._select(QModelIndex())

    # Loading ----------------------------------------------------------------------------------

    def load_roots(self) -> None:
        """(Re)build the top level: one row per online root; counted when expanded."""
        self.model.removeRows(0, self.model.rowCount())
        for root in self.service.desk_roots():
            item = self._folder_item(f"{root['environment']} · {root['path']}", root["id"],
                                     root["environment_id"], "", None)
            self.model.appendRow([item, QStandardItem("…")])
        if self.model.rowCount() == 1:
            self.tree.expand(self.model.index(0, 0))
        self._select(QModelIndex())

    @staticmethod
    def _folder_item(text: str, root_id: int, env_id: int, path: str, count: int | None) -> QStandardItem:
        item = QStandardItem(text)
        item.setData(root_id, ROOT_ID)
        item.setData(env_id, ENV_ID)
        item.setData(path, PATH)
        item.setData(count, COUNT)
        item.setData("unloaded", STATE)
        item.appendRow([QStandardItem("Counting…"), QStandardItem("")])  # so it can be expanded
        return item

    def _start(self, kind: str, item: QStandardItem | None, fn) -> None:
        request = next(self._requests)
        self._pending[request] = (kind, item)
        self.pool.start(_Job(self.service, request, fn, self._signals))

    def _expand(self, index: QModelIndex) -> None:
        item = self.model.itemFromIndex(index.siblingAtColumn(0))
        if item is None or item.data(STATE) != "unloaded":
            return
        item.setData("loading", STATE)
        root_id, path = item.data(ROOT_ID), item.data(PATH)
        self._start("folders", item, lambda conn: unattached_folders(conn, root_id, path))

    def _done(self, request: int, result) -> None:
        kind, item = self._pending.pop(request, (None, None))
        if kind == "folders":
            self._fill(item, result)
        elif kind == "preview" and item is self._current():
            self.preview.clear()
            if isinstance(result, Exception):
                self.preview.addItem(f"Could not list the files: {result}")
            else:
                self.preview.addItems([f["rel_path"] for f in result])

    def _fill(self, item: QStandardItem, data) -> None:
        try:
            item.removeRows(0, item.rowCount())
        except RuntimeError:
            return  # the row went away (the panel was reloaded) before the count came back
        if isinstance(data, Exception):
            item.appendRow([QStandardItem(f"Could not count: {data}"), QStandardItem("")])
            return
        item.setData("loaded", STATE)
        item.setData(data["total"], COUNT)
        self._count_cell(item).setText(f"{data['total']:,}")
        for folder in data["folders"]:
            child = self._folder_item(folder["name"], item.data(ROOT_ID), item.data(ENV_ID),
                                      folder["path"], folder["count"])
            item.appendRow([child, QStandardItem(f"{folder['count']:,}")])
        if data["files"]:
            leaf = QStandardItem(f"(files directly in {item.data(PATH) or 'the root'})")
            leaf.setSelectable(False)
            item.appendRow([leaf, QStandardItem(f"{data['files']:,}")])
        if not data["total"]:
            item.appendRow([QStandardItem("Nothing unattached here"), QStandardItem("")])
        if item is self._current():
            self._select(self.tree.currentIndex())

    def _count_cell(self, item: QStandardItem) -> QStandardItem:
        parent = item.parent() or self.model.invisibleRootItem()
        return parent.child(item.row(), 1)

    def reload_folder(self, path: str, root_id: int) -> None:
        """Count a folder's parent again after an edit changed what is unattached there."""
        item = self._find(root_id, path.rsplit("/", 1)[0] if "/" in path else "")
        if item is not None and item.data(STATE) == "loaded":
            item.setData("loading", STATE)
            folder = item.data(PATH)
            self._start("folders", item, lambda conn: unattached_folders(conn, root_id, folder))

    def _find(self, root_id: int, path: str) -> QStandardItem | None:
        stack = [self.model.item(r) for r in range(self.model.rowCount())]
        while stack:
            item = stack.pop()
            if item.data(ROOT_ID) == root_id and item.data(PATH) == path:
                return item
            stack.extend(item.child(r) for r in range(item.rowCount()) if item.child(r).data(STATE))
        return None

    # Selection and actions --------------------------------------------------------------------

    def _current(self) -> QStandardItem | None:
        index = self.tree.currentIndex()
        item = self.model.itemFromIndex(index.siblingAtColumn(0)) if index.isValid() else None
        return item if item is not None and item.data(STATE) else None

    def _select(self, _index: QModelIndex) -> None:
        item = self._current()
        path, count = (item.data(PATH), item.data(COUNT)) if item else ("", None)
        folder = bool(item and path)  # a root itself is not one folder of assets
        self.title.setText(path or (item.text() if item else "Choose a folder"))
        if item is None:
            self.count.setText("Files no asset holds yet, by folder. Expand a folder to count it; "
                               "big libraries take a few seconds.")
        elif count is None:
            self.count.setText("Expand it to count its files.")
        else:
            self.count.setText(f"{count:,} file{'s' * (count != 1)} no asset holds" +
                               (f". More than {MAX_FILES:,}: pick a smaller folder to make a product or link."
                                if count > MAX_FILES else ""))
        self.product_button.setEnabled(folder and count is not None and 0 < count <= MAX_FILES)
        self.link_button.setEnabled(folder and count is not None and 0 < count <= MAX_FILES)
        self.ignore_button.setEnabled(folder)
        self.preview.clear()
        if item is not None and count:
            root_id = item.data(ROOT_ID)
            self._start("preview", item, lambda conn: unattached_files(conn, root_id, path, limit=PREVIEW))

    def selected_folder(self) -> tuple[int, int, str, int] | None:
        """(root id, environment id, folder, file count) of the selected folder."""
        item = self._current()
        if item is None or not item.data(PATH):
            return None
        return item.data(ROOT_ID), item.data(ENV_ID), item.data(PATH), item.data(COUNT) or 0

    def _act(self, what: str) -> None:
        selected = self.selected_folder()
        if selected is None:
            return
        root_id, env_id, path, count = selected
        if what == "product":
            self.makeProduct.emit(root_id, env_id, path, count)
        elif what == "link":
            self.linkFolder.emit(root_id, path, count)
        else:
            self.ignoreFolder.emit(env_id, path)

    def wait(self) -> None:
        """Finish background counts (tests, closing)."""
        self.pool.waitForDone()


class SuggestionsPanel(QWidget):
    """Pending suggestions as a checklist, accepted or rejected in batches."""

    decided = Signal(list, bool)  # suggestion ids, accepted?
    subjectSelected = Signal(str)  # dossier uid the selected suggestion is about

    PAGE = 300
    _KINDS = (("All suggestions", None), ("Texture links", "texture_link"), ("Variant groups", "variant_group"),
              ("Lexicon words", "lexicon_word"))

    def __init__(self, service: LibraryService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.service = service
        self.rows: list[dict] = []
        self.total = 0
        bar = QHBoxLayout()
        self.kind = QComboBox()
        for label, kind in self._KINDS:
            self.kind.addItem(label, kind)
        self.kind.currentIndexChanged.connect(lambda _: self.reload())
        self.all = QCheckBox("Select all shown")
        self.all.toggled.connect(self._check_all)
        self.summary = QLabel()
        self.summary.setObjectName("subtitle")
        self.reject_button = QPushButton("Reject checked")
        self.accept_button = QPushButton("Accept checked")
        self.accept_button.setObjectName("primary")
        self.reject_button.clicked.connect(lambda: self._decide(False))
        self.accept_button.clicked.connect(lambda: self._decide(True))
        for widget in (self.kind, self.all):
            bar.addWidget(widget)
        bar.addWidget(self.summary, 1)
        bar.addWidget(self.reject_button)
        bar.addWidget(self.accept_button)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Suggestion", "For", "Confidence"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setShowGrid(False)
        self.table.itemChanged.connect(lambda _: self._update_buttons())
        self.table.currentCellChanged.connect(self._on_row)
        self.more = QPushButton("Show more")
        self.more.clicked.connect(self._load_more)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(bar)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.more, 0, Qt.AlignmentFlag.AlignLeft)

    def reload(self) -> None:
        self.rows, self.total = [], 0
        self.table.setRowCount(0)
        self.all.blockSignals(True)
        self.all.setChecked(False)
        self.all.blockSignals(False)
        self._load_more()

    def _load_more(self) -> None:
        rows, self.total = self.service.suggestions(self.kind.currentData(), self.PAGE, len(self.rows))
        self.table.blockSignals(True)
        start = len(self.rows)
        self.rows += rows
        self.table.setRowCount(len(self.rows))
        for r, s in enumerate(rows, start=start):
            what = QTableWidgetItem(describe_suggestion(s))
            what.setFlags(what.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            what.setCheckState(Qt.CheckState.Checked if self.all.isChecked() else Qt.CheckState.Unchecked)
            what.setData(Qt.ItemDataRole.UserRole, s["id"])
            self.table.setItem(r, 0, what)
            self.table.setItem(r, 1, QTableWidgetItem(s["subject_name"] or ""))
            self.table.setItem(r, 2, QTableWidgetItem(f"{s['confidence']:.2f}"))
        self.table.blockSignals(False)
        self.more.setVisible(len(self.rows) < self.total)
        self._update_buttons()

    def checked_ids(self) -> list[int]:
        return [self.table.item(r, 0).data(Qt.ItemDataRole.UserRole) for r in range(self.table.rowCount())
                if self.table.item(r, 0).checkState() == Qt.CheckState.Checked]

    def _check_all(self, checked: bool) -> None:
        self.table.blockSignals(True)
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for r in range(self.table.rowCount()):
            self.table.item(r, 0).setCheckState(state)
        self.table.blockSignals(False)
        self._update_buttons()

    def _update_buttons(self) -> None:
        n = len(self.checked_ids())
        self.summary.setText(f"{self.total:,} pending · {n:,} checked" if self.total else "No pending suggestions.")
        self.accept_button.setEnabled(bool(n))
        self.reject_button.setEnabled(bool(n))

    def _decide(self, accept: bool) -> None:
        ids = self.checked_ids()
        if ids:
            self.decided.emit(ids, accept)

    def _on_row(self, row: int, *_args) -> None:
        if 0 <= row < len(self.rows) and self.rows[row]["subject"]:
            self.subjectSelected.emit(self.rows[row]["subject"])
