"""Settings › Lexicons: view and edit the word lists that drive tags, variants and grouping.

Edits are curation actions (undoable, Ctrl+Z in the window) that write the user's copy of the
lexicon (``lexicons/<id>.toml`` in their definitions folder). They apply to the next scan, or to the
library at once with "Apply to library", which re-runs classification (and, for theme and author
lexicons, the grouping of hand-installed Daz products) in a background process.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from exchange.definitions.schema import GENERATED_LEXICON_KINDS
from exchange.lexicons import has_word

_ABOUT = {
    "category": "Words that tag an asset when they appear in its name, its folders or its source's categories.",
    "variant": "Words that make two assets variants of one (Donut01_Pink, Donut01_Blue).",
    "texture_channel": "Texture suffixes that link images to a mesh (Barrel01_N.png is Barrel01's normal map).",
    "structural": "LOD and collision meshes, kept out of sight unless you search is:structural.",
    "index": "Words that number a series (Barrel01, Barrel02, Rock_A); numbers always count.",
    "ignore": "Noise dropped from names before matching (Barrel_final_v2 is Barrel).",
    "theme": "Genres and settings people sort content by. A folder named only with these words (or with "
             "category names) is a category folder, never a hand-installed Daz product.",
    "author": "Vendors. Scans add the artists in Daz manifests and the vendor folders under data/. A folder "
              "named after an author is a vendor folder, and the products below it get that author. "
              "Removing a found author keeps scans from adding it back.",
}
REGROUP_KINDS = ("theme", "author")  # these change how hand-installed Daz products are grouped


class SettingsDialog(QDialog):
    applyRequested = Signal(bool)  # regroup Daz products too?

    def __init__(self, window, parent: QWidget | None = None) -> None:
        super().__init__(parent or window)
        self.window = window
        self.service = window.service
        self.setWindowTitle("Settings")
        self.resize(900, 620)
        self.edited_kinds: set[str] = set()

        self.lexicon_list = QListWidget()
        self.lexicon_list.currentItemChanged.connect(lambda *_: self._show())
        self.about = QLabel()
        self.about.setObjectName("subtitle")
        self.about.setWordWrap(True)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Value", "Word", "From"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setShowGrid(False)

        add = QHBoxLayout()
        self.value = QComboBox()
        self.value.setEditable(True)
        self.value.setMinimumWidth(160)
        self.word = QLineEdit()
        self.word.setPlaceholderText("Word or phrase (plurals match by themselves)")
        self.word.returnPressed.connect(self.add_word)
        add_button = QPushButton("Add")
        add_button.clicked.connect(self.add_word)
        self.remove_button = QPushButton("Remove selected")
        self.remove_button.clicked.connect(self.remove_selected)
        add.addWidget(self.value)
        add.addWidget(self.word, 1)
        add.addWidget(add_button)
        add.addWidget(self.remove_button)

        right = QWidget()
        side = QVBoxLayout(right)
        side.setContentsMargins(12, 0, 0, 0)
        side.addWidget(self.about)
        side.addWidget(self.table, 1)
        side.addLayout(add)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.lexicon_list)
        splitter.addWidget(right)
        splitter.setSizes([230, 670])

        lexicons = QWidget()
        page = QVBoxLayout(lexicons)
        page.addWidget(splitter, 1)
        footer = QHBoxLayout()
        self.status = QLabel("Edits apply to the next scan. Ctrl+Z in the main window undoes them.")
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        self.apply_button = QPushButton("Apply to library")
        self.apply_button.setObjectName("primary")
        self.apply_button.setToolTip("Re-tag the library now with your edits (in the background)")
        self.apply_button.clicked.connect(self.apply)
        footer.addWidget(self.status, 1)
        footer.addWidget(self.apply_button)
        page.addLayout(footer)

        tabs = QTabWidget()
        tabs.addTab(lexicons, "Lexicons")
        layout = QVBoxLayout(self)
        layout.addWidget(tabs)
        self.reload()

    # Showing ----------------------------------------------------------------------------------

    def reload(self) -> None:
        current = self.current_id()
        self.lexicons = self.service.lexicons()
        self.lexicon_list.blockSignals(True)
        self.lexicon_list.clear()
        for lex in sorted(self.lexicons.values(), key=lambda l: l.name.casefold()):
            words = sum(len(t.words) for t in lex.terms)
            item = QListWidgetItem(f"{lex.name}\n{lex.kind.replace('_', ' ')} · {words:,} words")
            item.setData(Qt.ItemDataRole.UserRole, lex.id)
            self.lexicon_list.addItem(item)
            if lex.id == current:
                self.lexicon_list.setCurrentItem(item)
        if self.lexicon_list.currentItem() is None and self.lexicon_list.count():
            self.lexicon_list.setCurrentRow(0)
        self.lexicon_list.blockSignals(False)
        self._show()

    def current_id(self) -> str | None:
        item = self.lexicon_list.currentItem() if hasattr(self, "lexicons") else None
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def select(self, lexicon_id: str) -> None:
        for r in range(self.lexicon_list.count()):
            if self.lexicon_list.item(r).data(Qt.ItemDataRole.UserRole) == lexicon_id:
                self.lexicon_list.setCurrentRow(r)
                return

    def _show(self) -> None:
        lex = self.lexicons.get(self.current_id())
        self.table.setRowCount(0)
        if lex is None:
            return
        self.about.setText(f"{_ABOUT.get(lex.kind, '')}\nFrom {lex.source}")
        files = self.service.definitions  # the lexicon files as loaded (without words scans found)
        rows = []
        for term in lex.terms:
            for word in term.words:
                found = lex.kind in GENERATED_LEXICON_KINDS and not has_word(files, lex.id, term.value, word)
                rows.append((term.value, word, "found by scans" if found else "list", True))
            rows += [(term.value, pattern, "pattern (read-only)", False) for pattern in term.patterns]
        self.table.setRowCount(len(rows))
        for r, (value, word, source, editable) in enumerate(rows):
            for c, text in enumerate((value or "—", word, source)):
                cell = QTableWidgetItem(text)
                if not editable:
                    cell.setFlags(cell.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                    cell.setForeground(self.palette().placeholderText())
                cell.setData(Qt.ItemDataRole.UserRole, (value, word) if editable else None)
                self.table.setItem(r, c, cell)
        valued = lex.kind not in ("ignore", "index")
        self.value.setVisible(valued)
        self.value.clear()
        if valued:
            self.value.addItems(sorted({t.value for t in lex.terms}, key=str.casefold))

    # Editing ----------------------------------------------------------------------------------

    def _edit(self, label: str, value: str, word: str, present: bool) -> bool:
        lex_id = self.current_id()
        done = self.window._edit(label, lambda cur: cur.set_lexicon_word(lex_id, value, word, present),
                                 scope="none") is not None
        if done:
            self.edited_kinds.add(self.lexicons[lex_id].kind)
            self.status.setText(f"Done: {label}. Apply to library to re-tag what is already scanned.")
        else:
            self.status.setText(self.window.status.text())
        return done

    def add_word(self) -> None:
        lex = self.lexicons.get(self.current_id())
        word = self.word.text().strip()
        value = self.value.currentText().strip() if self.value.isVisible() else ""
        if lex is None or not word or (self.value.isVisible() and not value):
            self.status.setText("Type a word, and the value it stands for (e.g. Food).")
            return
        if self._edit(f"add “{word}” to {value or lex.name}", value, word, True):
            self.word.clear()
            self.reload()

    def remove_selected(self) -> None:
        pairs = {self.table.item(i.row(), 0).data(Qt.ItemDataRole.UserRole)
                 for i in self.table.selectedIndexes()} - {None}
        for value, word in sorted(pairs):
            if not self._edit(f"remove “{word}”", value, word, False):
                break
        self.reload()

    def apply(self) -> None:
        regroup = bool(self.edited_kinds & set(REGROUP_KINDS))
        self.applyRequested.emit(regroup)
        self.status.setText("Applying in the background" + (" (regrouping Daz products takes minutes on a "
                                                           "big library)" if regroup else "") + "…")
