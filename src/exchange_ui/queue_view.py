"""The requisition queue: what is queued, running, waiting for you or done, and what to do next.

Running happens in a background process (``exchange requisition run``, through the window's
runner), so the window stays responsive; this view lists the requisitions, their items and logs,
and asks the window to act (it makes the changes, and they show here on the next refresh).
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from exchange.requisitions.runner import log_path

STATE_LABELS = {"queued": "Queued", "held": "Held", "running": "Running", "needs_attention": "Needs attention",
                "fulfilled": "Fulfilled", "partially_fulfilled": "Partly fulfilled", "failed": "Failed",
                "stale": "Stale", "removed": "Removed", "replaced": "Replaced"}
ACTIVE = ("queued", "held", "running", "needs_attention")


class QueuePanel(QWidget):
    # What the user asked for; the window does it: (action, requisition id, extra)
    requested = Signal(str, int, object)

    def __init__(self, service, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.service = service
        self.rows: list[dict] = []
        bar = QHBoxLayout()
        self.run_button = QPushButton("Run queue")
        self.run_button.setObjectName("primary")
        self.run_button.clicked.connect(lambda: self.requested.emit("run", 0, None))
        self.buttons: dict[str, QPushButton] = {}
        for action, label, tip in (
                ("hold", "Hold", "Keep it from running"), ("release", "Release", "Let it run again"),
                ("up", "Move up", ""), ("down", "Move down", ""),
                ("rebuild", "Rebuild", "Queue it again with the current pipelines, overwriting its output"),
                ("remove", "Remove output", "Move what it wrote to the recycle folder; put back what it overwrote")):
            button = QPushButton(label)
            button.setToolTip(tip)
            button.clicked.connect(lambda _=False, a=action: self._act(a))
            self.buttons[action] = button
        self.resume_button = QPushButton("Resume ▾")
        self.resume_button.setToolTip("Continue after a checkpoint or a collision; failed items are retried")
        resume_menu = QMenu(self.resume_button)
        resume_menu.addAction("Resume", lambda: self._act("resume", None))
        resume_menu.addSeparator()
        for label, policy in (("Resume, overwriting existing files", "overwrite"),
                              ("Resume, renaming new files", "rename"), ("Resume, skipping existing files", "skip")):
            resume_menu.addAction(label, lambda p=policy: self._act("resume", p))
        self.resume_button.setMenu(resume_menu)
        stale = QPushButton("Check for stale")
        stale.setToolTip("Find fulfilled requisitions whose source or pipeline has changed since")
        stale.clicked.connect(lambda: self.requested.emit("check_stale", 0, None))
        bar.addWidget(self.run_button)
        for button in (self.resume_button, *self.buttons.values()):
            bar.addWidget(button)
        bar.addStretch(1)
        bar.addWidget(stale)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["State", "Requisition", "To", "Done", "Message"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setShowGrid(False)
        self.table.currentCellChanged.connect(lambda *_: self._show_selected())

        self.items = QTableWidget(0, 3)
        self.items.setHorizontalHeaderLabels(["Item", "State", "Message"])
        self.items.verticalHeader().setVisible(False)
        self.items.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.items.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.items.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.items.setShowGrid(False)
        self.items.currentCellChanged.connect(lambda *_: self._show_log())
        self.detail = QLabel()
        self.detail.setObjectName("subtitle")
        self.detail.setWordWrap(True)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("Select an item to see its log.")

        lower = QWidget()
        below = QVBoxLayout(lower)
        below.setContentsMargins(0, 0, 0, 0)
        below.addWidget(self.detail)
        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(self.items)
        split.addWidget(self.log)
        split.setSizes([360, 480])
        below.addWidget(split, 1)
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self.table)
        splitter.addWidget(lower)
        splitter.setSizes([300, 320])
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(bar)
        layout.addWidget(splitter, 1)
        self._update_buttons()

    # Showing ------------------------------------------------------------------------------------

    def reload(self) -> None:
        selected = self.selected_id()
        self.rows = self.service.requisitions()
        self.table.setRowCount(len(self.rows))
        for r, row in enumerate(self.rows):
            cells = [STATE_LABELS.get(row["state"], row["state"]), row["name"], row["environment"],
                     f"{row['done']}/{row['items']}", row["message"] or ""]
            for c, text in enumerate(cells):
                cell = QTableWidgetItem(text)
                cell.setData(Qt.ItemDataRole.UserRole, row["id"])
                if c == 4 and text:
                    cell.setToolTip(text)
                self.table.setItem(r, c, cell)
        again = next((r for r, row in enumerate(self.rows) if row["id"] == selected), 0 if self.rows else -1)
        if again >= 0:
            self.table.selectRow(again)
        self._show_selected()

    def active_count(self) -> int:
        return sum(1 for r in self.rows if r["state"] in ACTIVE)

    def selected_id(self) -> int | None:
        row = self.table.currentRow()
        return self.rows[row]["id"] if 0 <= row < len(self.rows) else None

    def select(self, requisition_id: int) -> None:
        row = next((r for r, x in enumerate(self.rows) if x["id"] == requisition_id), None)
        if row is not None:
            self.table.selectRow(row)

    def _selected(self) -> dict | None:
        rid = self.selected_id()
        return next((r for r in self.rows if r["id"] == rid), None)

    def _show_selected(self) -> None:
        row = self._selected()
        self.items.setRowCount(0)
        self.log.clear()
        self.current = None
        if row is None:
            self.detail.setText("Nothing queued yet. Right-click assets and choose “Requisition to…”.")
            self._update_buttons()
            return
        d = self.service.requisition(row["id"])
        self.current = d
        endpoint = d["endpoint"]
        written = sum(1 for w in d["writes"] if w["action"] != "sidecar" and not w["removed_at"])
        self.detail.setText(f"{d['name']} → {endpoint['label']} ({endpoint['folder']}) · {endpoint['visibility']}"
                            f" · if files exist: {d['on_collision']} · {written} files written")
        self.items.setRowCount(len(d["items"]))
        for r, item in enumerate(d["items"]):
            pipelines = " → ".join(p["id"] for p in item["pipelines"])
            for c, text in enumerate([f"{item['name']} ({pipelines or 'no pipeline'})", item["state"], item["message"] or ""]):
                cell = QTableWidgetItem(text)
                cell.setData(Qt.ItemDataRole.UserRole, item["id"])
                self.items.setItem(r, c, cell)
        if d["items"]:
            self.items.selectRow(0)
        self._update_buttons()

    def _show_log(self) -> None:
        if not getattr(self, "current", None):
            return
        row = self.items.currentRow()
        if not 0 <= row < len(self.current["items"]):
            return
        path = log_path(self.current["uid"], self.current["items"][row]["id"])
        try:
            self.log.setPlainText(path.read_text(encoding="utf-8", errors="replace"))
            self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())
        except OSError:
            self.log.setPlainText("No log yet: this item has not run.")

    def _update_buttons(self, running: bool | None = None) -> None:
        if running is not None:
            self._running = running
        running = getattr(self, "_running", False)
        state = (self._selected() or {}).get("state")
        self.run_button.setEnabled(not running and any(r["state"] == "queued" for r in self.rows))
        self.run_button.setText("Running…" if running else "Run queue")
        enable = {"hold": state == "queued", "release": state == "held", "up": state in ("queued", "held"),
                  "down": state in ("queued", "held"),
                  "rebuild": state in ("stale", "fulfilled", "partially_fulfilled"),
                  "remove": state in ("fulfilled", "partially_fulfilled", "stale", "needs_attention", "failed")}
        for action, button in self.buttons.items():
            button.setEnabled(enable[action] and not running)
        self.resume_button.setEnabled(state in ("needs_attention", "failed", "partially_fulfilled") and not running)

    def set_running(self, running: bool) -> None:
        self._update_buttons(running)

    def _act(self, action: str, extra=None) -> None:
        rid = self.selected_id()
        if rid is None:
            return
        if action in ("up", "down"):
            order = [r["id"] for r in self.rows if r["state"] in ("queued", "held")]
            if rid in order:
                place = order.index(rid) + 1  # 1-based
                self.requested.emit("move", rid, max(1, place - 1) if action == "up" else place + 1)
            return
        self.requested.emit(action, rid, extra)
