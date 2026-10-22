"""The inspector: everything about the selected dossier, editable (Roadmap phase 3).

Edits go to the override layer through the window (see ``MainWindow``): the inspector only emits
what the user changed, together with the dossiers its editors were built for, so a field
committed as the selection moves on still reaches the right dossier. Overridden values carry a
marker and a revert button. With several dossiers selected it shows a bulk editor instead.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QCompleter,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLayout,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QWidgetItem,
)

from exchange_ui import theme

# Editable fields shown under About: (title, field written, fields read in order of preference).
_ABOUT_FIELDS = (("Author", "author", ("author", "authors")), ("License", "license", ("license",)),
                 ("Source", "source", ("source", "url", "installed_by")), ("Version", "version", ("version",)))
_HIDDEN_FIELDS = {"preview", "variant", "authors", "author", "license", "source", "url", "version",
                  "installed_by", "daz_compatibility", "daz_categories", "notes", "name", "type_id",
                  "user_created"}
_TAG_SOURCES = {"name": "its name", "folder": "its folder", "metadata": "source metadata"}


def _breakable(text: str) -> str:
    """Let word wrap break long paths after each separator."""
    zwsp = chr(0x200B)  # zero-width space
    return text.replace("/", "/" + zwsp).replace("\\", "\\" + zwsp)


def _label(text: str = "", name: str = "", wrap: bool = False) -> QLabel:
    label = QLabel(_breakable(text) if wrap else text)
    if name:
        label.setObjectName(name)
    label.setWordWrap(wrap)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return label


def _clear(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget:
            widget.setParent(None)  # gone from the inspector now, not only once deleted
            widget.deleteLater()
        elif item.layout():
            _clear(item.layout())


def _value(value) -> str:
    if isinstance(value, list):
        return ", ".join(map(str, value))
    if isinstance(value, float):
        return f"{value:g}"
    return "" if value is None else str(value)


def _button(text: str, name: str, tooltip: str, slot) -> QPushButton:
    button = QPushButton(text)
    button.setObjectName(name)
    button.setToolTip(tooltip)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.clicked.connect(slot)
    return button


class FlowLayout(QLayout):
    """Lays widgets out in rows, wrapping at the available width (for tag chips)."""

    def __init__(self, spacing: int = 4) -> None:
        super().__init__()
        self._items: list = []
        self._spacing = spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item) -> None:
        self._items.append(item)

    def addWidget(self, widget: QWidget) -> None:
        self.addChildWidget(widget)
        self.addItem(QWidgetItem(widget))

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self) -> Qt.Orientation:
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._arrange(QRect(0, 0, width, 0), move=False)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._arrange(rect, move=True)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        return size

    def _arrange(self, rect: QRect, move: bool) -> int:
        x, y, line = rect.x(), rect.y(), 0
        for item in self._items:
            hint = item.sizeHint()
            if x + hint.width() > rect.right() and line:
                x, y, line = rect.x(), y + line + self._spacing, 0
            if move:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self._spacing
            line = max(line, hint.height())
        return y + line - rect.y()


class _NotesEdit(QPlainTextEdit):
    """Notes, committed when focus leaves (there is no editingFinished for plain text)."""

    committed = Signal(str)

    def focusOutEvent(self, event) -> None:
        super().focusOutEvent(event)
        self.committed.emit(self.toPlainText())


class Inspector(QWidget):
    # Each signal carries the dossier uids the editors were built for.
    edited = Signal(list, str, object)  # uids, field, value (None: back to the scanned value)
    tagsChanged = Signal(list, list, list)  # uids, add, remove
    tagReverted = Signal(list, str)  # uids, tag: drop your add or remove
    collectionChanged = Signal(list, str, bool)  # uids, collection uid, member?
    suggestionDecided = Signal(int, bool)  # suggestion id, accepted?
    historyUndo = Signal(int, str)  # curation log id, what it did
    requisitionRequested = Signal(list)  # uids

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("inspector")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMinimumWidth(300)
        self.detail: dict | None = None
        self.targets: list[str] = []
        # Choices for the editors, set by the window: [(type id, name)], tag names, [(uid, name)].
        self.types: list[tuple[str, str]] = []
        self.tag_names: list[str] = []
        self.manual_collections: list[tuple[str, str]] = []
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 14, 14, 12)
        outer.setSpacing(10)

        header = QHBoxLayout()
        self.thumb = QLabel()
        self.thumb.setFixedSize(64, 64)
        self.thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb.setStyleSheet(f"background: {theme.CARD}; border-radius: 8px;")
        header.addWidget(self.thumb, 0, Qt.AlignmentFlag.AlignTop)
        names = QVBoxLayout()
        names.setSpacing(2)
        self.name = _label("", "inspectorName", wrap=True)
        self.summary = _label("", "subtitle", wrap=True)
        for label in (self.name, self.summary):
            label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            label.setMinimumWidth(150)
        self.chips = QHBoxLayout()
        self.chips.setSpacing(4)
        names.addWidget(self.name)
        names.addWidget(self.summary)
        names.addLayout(self.chips)
        header.addLayout(names, 1)
        outer.addLayout(header)

        self.tabs = QTabWidget()
        self.overview, self.overview_layout = self._scroll_tab("Overview")
        self.files = self._table_tab("Files", ["File", "Role", "Size", "Container"])
        self.dependencies, self.dependencies_layout = self._scroll_tab("Dependencies")
        self.history, self.history_layout = self._scroll_tab("History")
        outer.addWidget(self.tabs, 1)

        actions = QHBoxLayout()
        self.requisition = QPushButton("Requisition to…")
        self.requisition.setObjectName("primary")
        self.copy = QPushButton("Copy to…")
        self.requisition.setToolTip("Plan getting this into an environment, then queue it")
        self.requisition.clicked.connect(lambda: self.targets and self.requisitionRequested.emit(list(self.targets)))
        self.copy.setEnabled(False)
        self.copy.setToolTip("Copying between environments arrives in Roadmap phase 5")
        for button in (self.requisition, self.copy):
            actions.addWidget(button)
        outer.addLayout(actions)
        self.show_detail(None)

    def _scroll_tab(self, title: str) -> tuple[QScrollArea, QVBoxLayout]:
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 10, 4, 10)
        layout.setSpacing(8)
        area.setWidget(body)
        self.tabs.addTab(area, title)
        return area, layout

    def _table_tab(self, title: str, columns: list[str]) -> QTableWidget:
        table = QTableWidget(0, len(columns))
        table.setHorizontalHeaderLabels(columns)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setShowGrid(False)
        self.tabs.addTab(table, title)
        return table

    # Filling ----------------------------------------------------------------------------------

    def _reset(self) -> None:
        for layout in (self.overview_layout, self.dependencies_layout, self.history_layout, self.chips):
            _clear(layout)
        self.files.setRowCount(0)
        for i in range(self.tabs.count()):
            self.tabs.setTabEnabled(i, True)

    def show_detail(self, detail: dict | None) -> None:
        self.detail = detail
        self.targets = [detail["uid"]] if detail else []
        self._reset()
        if detail is None:
            self.name.setText("Nothing selected")
            self.summary.setText("Select an asset to see its ledgers, files and origin.")
            self.thumb.clear()
            self.thumb.hide()
            self.tabs.setEnabled(False)
            return
        self.thumb.show()
        self.tabs.setEnabled(True)
        self.name.setText(detail["name"])
        entries = sum(len(l["entries"]) for l in detail["ledgers"])
        bits = [detail["type_name"]]
        if detail["children"]:
            bits.append(f"{len(detail['children'])} items")
        bits.append(f"{entries} entr{'ies' if entries != 1 else 'y'}")
        self.summary.setText(" · ".join(bits))
        self._thumbnail(detail.get("thumbnail"))
        if detail["unidentified"]:
            self.chips.addWidget(_label(f"Unidentified · {detail['confidence']:.2f}", "warnChip"))
        self.chips.addStretch(1)
        self._fill_overview(detail)
        self._fill_files(detail)
        self._fill_dependencies(detail)
        self._fill_history(detail)

    def show_bulk(self, uids: list[str]) -> None:
        """Edit several dossiers at once: type, origin fields, notes, tags and collections."""
        self.detail = None
        self.targets = list(uids)
        self._reset()
        self.thumb.hide()
        self.tabs.setEnabled(True)
        self.tabs.setCurrentIndex(0)
        for i in range(1, self.tabs.count()):
            self.tabs.setTabEnabled(i, False)
        self.name.setText(f"{len(uids):,} assets selected")
        self.summary.setText("Changes here apply to all of them. Names are edited one at a time.")
        layout = self.overview_layout
        self._section(layout, "About")
        grid = self._grid()
        combo = QComboBox()
        combo.addItem("Keep each type", None)
        for type_id, name in self.types:
            combo.addItem(name, type_id)
        combo.activated.connect(lambda i: combo.itemData(i) and self.edited.emit(self.targets, "type_id", combo.itemData(i)))
        grid.addWidget(_label("Type", "muted"), 0, 0)
        grid.addWidget(combo, 0, 1)
        for row, (title, field, _) in enumerate(_ABOUT_FIELDS + (("Notes", "notes", ("notes",)),), start=1):
            edit = QLineEdit()
            edit.setPlaceholderText("Keep each value · type one and press Enter")
            edit.returnPressed.connect(lambda e=edit, f=field: e.text().strip() and self.edited.emit(
                self.targets, f, e.text().strip()))
            grid.addWidget(_label(title, "muted"), row, 0)
            grid.addWidget(edit, row, 1)
        layout.addLayout(grid)
        self._section(layout, "Tags")
        add, remove = QLineEdit(), QLineEdit()
        add.setPlaceholderText("Add a tag to all…")
        remove.setPlaceholderText("Remove a tag from all…")
        for edit in (add, remove):
            edit.setCompleter(self._tag_completer())
            layout.addWidget(edit)
        add.returnPressed.connect(lambda: add.text().strip() and self.tagsChanged.emit(self.targets, [add.text().strip()], []))
        remove.returnPressed.connect(lambda: remove.text().strip() and self.tagsChanged.emit(self.targets, [], [remove.text().strip()]))
        self._collection_adder(layout, set())
        layout.addStretch(1)

    def _thumbnail(self, path: str | None) -> None:
        image = QImage(path) if path else QImage()
        if image.isNull():
            self.thumb.clear()
            return
        self.thumb.setPixmap(QPixmap.fromImage(image.scaled(
            64, 64, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)))

    def _section(self, layout: QVBoxLayout, title: str) -> None:
        layout.addWidget(_label(title.upper(), "sectionLabel"))

    @staticmethod
    def _grid() -> QGridLayout:
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)
        grid.setColumnStretch(1, 1)
        return grid

    def _tag_completer(self) -> QCompleter:
        completer = QCompleter(self.tag_names, self)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        return completer

    # Overview ---------------------------------------------------------------------------------

    def _fill_overview(self, d: dict) -> None:
        layout = self.overview_layout
        self._fill_about(layout, d)
        self._fill_tags(layout, d)
        self._fill_collections(layout, d)
        self._fill_suggestions(layout, d)
        if d["variants"] or d["variant"]:
            self._section(layout, "Variants")
            row = QHBoxLayout()
            for variant in d["variants"] or [d["variant"]]:
                row.addWidget(_label(variant.replace("_", " ").title(), "chip"))
            row.addStretch(1)
            layout.addLayout(row)
        if d["aliases"]:
            self._section(layout, "Merged into this")
            for alias in d["aliases"]:
                layout.addWidget(_label(alias["name"] or alias["uid"], "muted"))
        if d["parent"]:
            self._section(layout, "Part of")
            layout.addWidget(_label(d["parent"]["name"]))
        if d["children"]:
            self._section(layout, f"Contains ({len(d['children'])})")
            for child in d["children"][:30]:
                layout.addWidget(_label(f"{child['name']}", "muted"))
            if len(d["children"]) > 30:
                layout.addWidget(_label(f"… and {len(d['children']) - 30} more", "muted"))

        self._section(layout, f"Ledgers ({len(d['ledgers'])})")
        for ledger in d["ledgers"]:
            card = QFrame()
            card.setObjectName("card")
            grid = QGridLayout(card)
            grid.setContentsMargins(10, 8, 10, 8)
            grid.setVerticalSpacing(4)
            entries = ledger["entries"]
            grid.addWidget(_label(ledger["environment"]["name"]), 0, 0)
            count = _label(f"{len(entries)} entr{'ies' if len(entries) != 1 else 'y'}", "muted")
            grid.addWidget(count, 0, 1, Qt.AlignmentFlag.AlignRight)
            for i, entry in enumerate(entries, start=1):
                where = entry["container"] or "(root)"
                primary = next((f for f in entry["files"] if f["role"] == "primary"), None)
                text = where if not primary else f"{where}\n{primary['rel_path']}"
                if entry["source_container"]:
                    text += f"\nfrom {entry['source_container']}"
                if entry["variant"]:
                    text += f"\nvariant: {entry['variant']}"
                grid.addWidget(_label(text, "subtitle", wrap=True), i, 0)
                status = _label(entry["status"].replace("unknown", "unknown provenance").capitalize(), "muted")
                grid.addWidget(status, i, 1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
            layout.addWidget(card)

        details = {k: v for k, v in d["fields"].items() if k not in _HIDDEN_FIELDS}
        if details or d["signals"]:
            self._section(layout, "Details")
            grid = self._grid()
            for row, (key, item) in enumerate(details.items()):
                grid.addWidget(_label(key.replace("_", " "), "muted"), row, 0, Qt.AlignmentFlag.AlignTop)
                grid.addWidget(_label(_value(item["value"]), wrap=True), row, 1)
            row = len(details)
            grid.addWidget(_label("identified by", "muted"), row, 0, Qt.AlignmentFlag.AlignTop)
            grid.addWidget(_label(f"{'; '.join(d['signals'])} ({d['confidence']:.2f})", wrap=True), row, 1)
            layout.addLayout(grid)
        layout.addStretch(1)

    def _revert(self, field: str) -> QToolButton:
        button = QToolButton()
        button.setObjectName("revert")
        button.setText("↺")
        button.setToolTip("Your edit. Click to go back to the scanned value.")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(lambda: self.edited.emit(self.targets, field, None))
        return button

    @staticmethod
    def _mark(widget: QWidget, overridden: bool) -> None:
        widget.setProperty("overridden", overridden)
        widget.setToolTip("Your edit; scans never change it" if overridden else "")

    def _fill_about(self, layout: QVBoxLayout, d: dict) -> None:
        self._section(layout, "About")
        grid = self._grid()
        fields, inherited = d["fields"], d.get("parent_fields", {})

        name = QLineEdit(d["name"])
        name.setObjectName("nameEdit")
        self._mark(name, d["name_overridden"])
        name.editingFinished.connect(lambda: self._commit_text("name", name.text(), d["name"]))
        self._row(grid, 0, "Name", name, "name" if d["name_overridden"] else None)

        combo = QComboBox()
        combo.setObjectName("typeEdit")
        choices = self.types if any(t == d["type_id"] for t, _ in self.types) else [*self.types, (d["type_id"], d["type_name"])]
        for type_id, title in choices:
            combo.addItem(title, type_id)
        combo.setCurrentIndex(combo.findData(d["type_id"]))
        self._mark(combo, d["type_overridden"])
        combo.activated.connect(lambda i: combo.itemData(i) != d["type_id"] and self.edited.emit(
            self.targets, "type_id", combo.itemData(i)))
        self._row(grid, 1, "Type", combo, "type_id" if d["type_overridden"] else None)

        for row, (title, field, keys) in enumerate(_ABOUT_FIELDS, start=2):
            mine = next((k for k in keys if k in fields and fields[k]["source"] == "user"), None)
            key = mine or next((k for k in keys if k in fields), None)
            current = _value(fields[key]["value"]) if key else ""
            edit = QLineEdit(current)
            edit.setObjectName(f"{field}Edit")
            parent_value = next((inherited[k]["value"] for k in keys if k in inherited), None)
            edit.setPlaceholderText(f"{_value(parent_value)} (from product)" if parent_value else "Unknown")
            self._mark(edit, mine is not None)
            edit.editingFinished.connect(lambda e=edit, f=mine or field, c=current, m=mine is not None:
                                         self._commit_text(f, e.text(), c, revert_if_empty=m))
            self._row(grid, row, title, edit, mine)

        notes_field = fields.get("notes")
        notes = _NotesEdit(_value(notes_field["value"]) if notes_field else "")
        notes.setObjectName("notesEdit")
        notes.setPlaceholderText("Notes (yours)")
        notes.setFixedHeight(64)
        self._mark(notes, bool(notes_field and notes_field["source"] == "user"))
        original = _value(notes_field["value"]) if notes_field else ""
        notes.committed.connect(lambda text: self._commit_text("notes", text, original, revert_if_empty=True))
        self._row(grid, len(_ABOUT_FIELDS) + 2, "Notes", notes,
                  "notes" if notes_field and notes_field["source"] == "user" else None)
        layout.addLayout(grid)

    def _row(self, grid: QGridLayout, row: int, title: str, editor: QWidget, revert_field: str | None) -> None:
        if isinstance(editor, (QLineEdit, QComboBox)):
            editor.ensurePolished()  # so its height includes the style sheet's padding before layout
            editor.setMinimumHeight(editor.sizeHint().height())
        grid.addWidget(_label(title, "muted"), row, 0, Qt.AlignmentFlag.AlignVCenter)
        grid.addWidget(editor, row, 1)
        if revert_field:
            grid.addWidget(self._revert(revert_field), row, 2, Qt.AlignmentFlag.AlignTop)

    def _commit_text(self, field: str, text: str, original: str, revert_if_empty: bool = False) -> None:
        text = text.strip()
        if text == original.strip():
            return
        if not text:
            if revert_if_empty:
                self.edited.emit(self.targets, field, None)
            return
        self.edited.emit(self.targets, field, text)

    def _fill_tags(self, layout: QVBoxLayout, d: dict) -> None:
        self._section(layout, "Tags")
        holder = QWidget()
        flow = FlowLayout()
        holder.setLayout(flow)
        for t in d["tag_sources"]:
            tag, user = t["tag"], t["user"]
            found = ", ".join(_TAG_SOURCES.get(s, s) for s in t["sources"])
            if user == "remove":
                flow.addWidget(_button(f"{tag}  ↺", "chipHidden",
                                       f"Found from {found}; you hid it. Click to show it again.",
                                       lambda _=False, x=tag: self.tagReverted.emit(self.targets, x)))
            elif user == "add" and not t["sources"]:
                flow.addWidget(_button(f"{tag}  ×", "chipUser", "Yours. Click to remove.",
                                       lambda _=False, x=tag: self.tagReverted.emit(self.targets, x)))
            else:
                flow.addWidget(_button(f"{tag}  ×", "chipUser" if user else "chip",
                                       f"Found from {found} ({t['confidence']:.2f}). Click to hide it.",
                                       lambda _=False, x=tag: self.tagsChanged.emit(self.targets, [], [x])))
        add = QLineEdit()
        add.setObjectName("addTag")
        add.setPlaceholderText("Add a tag…")
        add.setCompleter(self._tag_completer())
        add.returnPressed.connect(lambda: add.text().strip() and self.tagsChanged.emit(self.targets, [add.text().strip()], []))
        layout.addWidget(holder)
        layout.addWidget(add)

    def _fill_collections(self, layout: QVBoxLayout, d: dict) -> None:
        self._section(layout, "Collections")
        holder = QWidget()
        flow = FlowLayout()
        holder.setLayout(flow)
        for c in d["collections"]:
            flow.addWidget(_button(f"{c['name']}  ×", "chip", "Click to remove it from this collection.",
                                   lambda _=False, x=c["uid"]: self.collectionChanged.emit(self.targets, x, False)))
        if d["collections"]:
            layout.addWidget(holder)
        self._collection_adder(layout, {c["uid"] for c in d["collections"]})

    def _collection_adder(self, layout: QVBoxLayout, member_of: set[str]) -> None:
        choices = [(uid, name) for uid, name in self.manual_collections if uid not in member_of]
        if not choices:
            if not self.manual_collections:
                layout.addWidget(_label("Make a collection from the sidebar, then add assets here.", "muted", wrap=True))
            return
        combo = QComboBox()
        combo.setObjectName("addCollection")
        combo.addItem("Add to collection…", None)
        for uid, name in choices:
            combo.addItem(name, uid)
        combo.activated.connect(lambda i: combo.itemData(i) and self.collectionChanged.emit(
            self.targets, combo.itemData(i), True))
        layout.addWidget(combo)

    def _fill_suggestions(self, layout: QVBoxLayout, d: dict) -> None:
        if not d["suggestions"]:
            return
        self._section(layout, f"Suggestions ({len(d['suggestions'])})")
        for s in d["suggestions"]:
            card = QFrame()
            card.setObjectName("card")
            row = QVBoxLayout(card)
            row.setContentsMargins(10, 8, 10, 8)
            row.addWidget(_label(describe_suggestion(s), "subtitle", wrap=True))
            buttons = QHBoxLayout()
            buttons.addStretch(1)
            buttons.addWidget(_button("Reject", "", "Don't suggest this again",
                                      lambda _=False, i=s["id"]: self.suggestionDecided.emit(i, False)))
            buttons.addWidget(_button("Accept", "primary", "Apply it (undoable)",
                                      lambda _=False, i=s["id"]: self.suggestionDecided.emit(i, True)))
            row.addLayout(buttons)
            layout.addWidget(card)

    # Other tabs -------------------------------------------------------------------------------

    def _fill_files(self, d: dict) -> None:
        rows = [(f, e["container"]) for l in d["ledgers"] for e in l["entries"] for f in e["files"]]
        self.files.setRowCount(len(rows))
        for r, (f, container) in enumerate(rows):
            item = QTableWidgetItem(f["rel_path"])
            item.setToolTip(f["path"])
            item.setData(Qt.ItemDataRole.UserRole, f["path"])
            self.files.setItem(r, 0, item)
            self.files.setItem(r, 1, QTableWidgetItem(f["role"]))
            self.files.setItem(r, 2, QTableWidgetItem(_size(f["size"])))
            self.files.setItem(r, 3, QTableWidgetItem(container))

    def _fill_dependencies(self, d: dict) -> None:
        layout = self.dependencies_layout
        deps = d["dependencies"]
        broken = [x for x in deps if x["status"] == "broken"]
        self._section(layout, f"Needs ({len(deps)}, {len(broken)} broken)" if deps else "Needs")
        if not deps:
            layout.addWidget(_label("No dependencies found.", "muted"))
        for dep in sorted(deps, key=lambda x: (x["status"] != "broken", x["reference"])):
            target = dep["target"]["name"] if dep["target"] else None
            text = f"{target}\n{dep['reference']}" if target else dep["reference"]
            label = _label(("Missing: " if dep["status"] == "broken" else "") + text,
                           "error" if dep["status"] == "broken" else "subtitle", wrap=True)
            layout.addWidget(label)
        if d["required_by"]:
            self._section(layout, f"Needed by ({len(d['required_by'])})")
            for r in d["required_by"]:
                layout.addWidget(_label(r["name"], "subtitle"))
        layout.addStretch(1)

    def _fill_history(self, d: dict) -> None:
        layout = self.history_layout
        for event in reversed(d["history"]):
            what = describe_event(event["action"], event["payload"])
            row = QHBoxLayout()
            row.addWidget(_label(f"{what}\n{event['at'][:16].replace('T', ' ')}", "subtitle", wrap=True), 1)
            if event.get("undoable"):
                row.addWidget(_button("Undo", "link", "Undo this (it can be undone in turn)",
                                      lambda _=False, i=event["id"], w=what: self.historyUndo.emit(i, w)),
                              0, Qt.AlignmentFlag.AlignTop)
            layout.addLayout(row)
        layout.addStretch(1)


def describe_event(action: str, p: dict) -> str:
    """One history entry in words."""
    files = p.get("files", [])
    files = len(files) if isinstance(files, list) else files  # a list of files, or a count
    return {
        "entry_added": f"Found in {p.get('environment')} · {p.get('container')}",
        "entry_retired": f"No longer in {p.get('environment')} · {p.get('container')}",
        "set_field": f"You set {p.get('field')} to {_value(p.get('value'))}",
        "revert_field": f"You reverted {p.get('field')} to the scanned value",
        "tag": "You " + " and ".join(filter(None, [
            p.get("add") and f"added tag {', '.join(p['add'])}",
            p.get("remove") and f"removed tag {', '.join(p['remove'])}"])),
        "revert_tag": f"You reverted tag {p.get('tag')}",
        "set_parent": "You moved it into a product" if p.get("parent") else "You took it out of its product",
        "revert_parent": "You reverted its product",
        "link_files": f"You linked {files} file{'s' * (files != 1)}",
        "unlink_files": f"You unlinked {files} file{'s' * (files != 1)}",
        "merge": "You merged assets",
        "fold_variant": f"You folded in variant {p.get('variant')}",
        "split": "You split it",
        "promote_variant": f"You made variant {p.get('variant')} its own asset",
        "create_product": f"You made product {p.get('name')}" + (f" from {files} files" if files else ""),
        "dismiss": "You marked it as not an asset",
        "undismiss": "You counted it as an asset again",
        "add_to_collection": "You added it to a collection",
        "remove_from_collection": "You removed it from a collection",
        "undo": f"You undid: {p.get('undone_action', '').replace('_', ' ')}",
    }.get(action, action.replace("_", " ").capitalize())


def describe_suggestion(s: dict) -> str:
    p = s["payload"]
    if s["kind"] == "texture_link":
        files = p.get("files", [])
        channels = ", ".join(sorted({f.get("channel", "?") for f in files}))
        return f"Link {len(files)} texture{'s' * (len(files) != 1)} ({channels}) found beside this mesh"
    if s["kind"] == "variant_group":
        variants = sorted(set(p.get("variants", {}).values()))
        return f"Group {len(p.get('members', []))} assets as variants: {', '.join(variants)}"
    if s["kind"] == "lexicon_word":
        return f"Add the word “{p.get('word')}” to the {p.get('value')} tag, so it tags assets by itself"
    return s["kind"].replace("_", " ")


def _size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return str(n)
