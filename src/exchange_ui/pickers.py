"""Small dialogs for choosing things: an asset (by searching for it) and entries to split off."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from exchange_ui.service import Filter, LibraryService


class AssetPicker(QDialog):
    """Search the library and pick one asset; ``chosen`` is (uid, name) after OK."""

    def __init__(self, service: LibraryService, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.service = service
        self.chosen: tuple[str, str] | None = None
        self.setWindowTitle(title)
        self.resize(520, 480)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search, e.g. barrel type:mesh")
        self.results = QListWidget()
        self.error = QLabel()
        self.error.setObjectName("error")
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self._accept)
        self.buttons.rejected.connect(self.reject)
        self.results.itemDoubleClicked.connect(lambda _: self._accept())
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(title))
        for widget in (self.search, self.error, self.results, self.buttons):
            layout.addWidget(widget)
        self.timer = QTimer(self, singleShot=True, interval=250)
        self.timer.timeout.connect(self._find)
        self.search.textChanged.connect(lambda _: self.timer.start())
        self._find()

    def _find(self) -> None:
        self.results.clear()
        try:
            page = self.service.page(Filter(query=self.search.text().strip(), group="all"), 0, 100)
        except Exception as exc:  # a search typo
            self.error.setText(str(exc))
            return
        self.error.setText("")
        for brick in page.items:
            item = QListWidgetItem(f"{brick.name}  ·  {brick.type_name}")
            item.setData(Qt.ItemDataRole.UserRole, (brick.uid, brick.name))
            self.results.addItem(item)
        if self.results.count():
            self.results.setCurrentRow(0)

    def _accept(self) -> None:
        item = self.results.currentItem()
        if item is not None:
            self.chosen = item.data(Qt.ItemDataRole.UserRole)
            self.accept()


class EntryPicker(QDialog):
    """Check the entries (places an asset was found) that are really another asset."""

    def __init__(self, detail: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Split {detail['name']}")
        self.resize(520, 420)
        self.list = QListWidget()
        for ledger in detail["ledgers"]:
            for entry in ledger["entries"]:
                if entry["status"] == "retired":
                    continue
                primary = next((f["rel_path"] for f in entry["files"] if f["role"] == "primary"),
                               entry["files"][0]["rel_path"] if entry["files"] else "")
                item = QListWidgetItem(f"{ledger['environment']['name']} · {entry['container'] or '(root)'}\n{primary}")
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Unchecked)
                item.setData(Qt.ItemDataRole.UserRole, entry["id"])
                self.list.addItem(item)
        self.name = QLineEdit(detail["name"])
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Check the entries that are a different asset; they become a new one."))
        layout.addWidget(self.list, 1)
        layout.addWidget(QLabel("Name of the new asset:"))
        layout.addWidget(self.name)
        layout.addWidget(buttons)

    def checked(self) -> list[int]:
        return [self.list.item(r).data(Qt.ItemDataRole.UserRole) for r in range(self.list.count())
                if self.list.item(r).checkState() == Qt.CheckState.Checked]
