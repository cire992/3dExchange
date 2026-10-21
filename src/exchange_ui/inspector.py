"""The inspector: everything about the selected dossier. Read-only in Roadmap phase 2; editing
(backed by the override layer) arrives with curation in phase 3."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from exchange_ui import theme

_ORIGIN_FIELDS = (("Author", ("authors", "author")), ("License", ("license",)),
                  ("Source", ("source", "url", "installed_by")), ("Version", ("version",)))
_HIDDEN_FIELDS = {"preview", "variant", "authors", "author", "license", "source", "url", "version",
                  "installed_by", "daz_compatibility", "daz_categories"}


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
        if item.widget():
            item.widget().deleteLater()
        elif item.layout():
            _clear(item.layout())


def _value(value) -> str:
    if isinstance(value, list):
        return ", ".join(map(str, value))
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


class Inspector(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("inspector")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMinimumWidth(300)
        self.detail: dict | None = None
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
        for button in (self.requisition, self.copy):
            button.setEnabled(False)
            button.setToolTip("Requisitions arrive in Roadmap phase 4")
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

    def show_detail(self, detail: dict | None) -> None:
        self.detail = detail
        for layout in (self.overview_layout, self.dependencies_layout, self.history_layout, self.chips):
            _clear(layout)
        self.files.setRowCount(0)
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
        for tag in detail["tags"]:
            self.chips.addWidget(_label(tag, "chip"))
        if detail["unidentified"]:
            self.chips.addWidget(_label(f"Unidentified · {detail['confidence']:.2f}", "warnChip"))
        self.chips.addStretch(1)
        self._fill_overview(detail)
        self._fill_files(detail)
        self._fill_dependencies(detail)
        self._fill_history(detail)

    def _thumbnail(self, path: str | None) -> None:
        image = QImage(path) if path else QImage()
        if image.isNull():
            self.thumb.clear()
            return
        self.thumb.setPixmap(QPixmap.fromImage(image.scaled(
            64, 64, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)))

    def _section(self, layout: QVBoxLayout, title: str) -> None:
        layout.addWidget(_label(title.upper(), "sectionLabel"))

    def _fill_overview(self, d: dict) -> None:
        layout = self.overview_layout
        if d["variant"]:
            self._section(layout, "Variants")
            row = QHBoxLayout()
            row.addWidget(_label(d["variant"].replace("_", " ").title(), "chip"))
            row.addStretch(1)
            layout.addLayout(row)
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
                grid.addWidget(_label(text, "subtitle", wrap=True), i, 0)
                status = _label(entry["status"].replace("unknown", "unknown provenance").capitalize(), "muted")
                grid.addWidget(status, i, 1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
            layout.addWidget(card)

        self._section(layout, "Origin")
        origin = QGridLayout()
        origin.setHorizontalSpacing(12)
        fields, inherited = d["fields"], d.get("parent_fields", {})
        for row, (title, keys) in enumerate(_ORIGIN_FIELDS):
            found = next((fields[k] for k in keys if k in fields), None)
            from_parent = found is None and (found := next((inherited[k] for k in keys if k in inherited), None))
            origin.addWidget(_label(title, "muted"), row, 0)
            text = _value(found["value"]) if found else "Unknown"
            if found and found["source"] == "user":
                text += "  (yours)"
            elif from_parent:
                text += "  (from product)"
            origin.addWidget(_label(text, wrap=True), row, 1)
        origin.setColumnStretch(1, 1)
        layout.addLayout(origin)

        details = {k: v for k, v in fields.items() if k not in _HIDDEN_FIELDS}
        if details or d["signals"]:
            self._section(layout, "Details")
            grid = QGridLayout()
            grid.setHorizontalSpacing(12)
            for row, (key, item) in enumerate(details.items()):
                grid.addWidget(_label(key.replace("_", " "), "muted"), row, 0, Qt.AlignmentFlag.AlignTop)
                grid.addWidget(_label(_value(item["value"]), wrap=True), row, 1)
            row = len(details)
            grid.addWidget(_label("identified by", "muted"), row, 0, Qt.AlignmentFlag.AlignTop)
            grid.addWidget(_label(f"{'; '.join(d['signals'])} ({d['confidence']:.2f})", wrap=True), row, 1)
            grid.setColumnStretch(1, 1)
            layout.addLayout(grid)
        layout.addStretch(1)

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
            p = event["payload"]
            what = {
                "entry_added": f"Found in {p.get('environment')} · {p.get('container')}",
                "entry_retired": f"No longer in {p.get('environment')} · {p.get('container')}",
                "set_field": f"You set {p.get('field')} to {_value(p.get('value'))}",
                "revert_field": f"You reverted {p.get('field')} to the scanned value",
                "add_tag": f"You added tag {p.get('tag')}",
                "remove_tag": f"You removed tag {p.get('tag')}",
                "set_parent": "You moved it to another product",
            }.get(event["action"], event["action"])
            layout.addWidget(_label(f"{what}\n{event['at'][:16].replace('T', ' ')}", "subtitle", wrap=True))
        layout.addStretch(1)


def _size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return str(n)
