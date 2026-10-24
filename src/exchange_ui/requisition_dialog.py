"""Requisition to…: plan getting assets into an environment, set the options, queue it.

The plan is a tree: each asset (and, for a product, each child) with an include checkbox, the
process it would go through, the entry it starts from, and any problem. Options are forms
generated from the processes' manifests, filled in from a preset if one is chosen, otherwise from
the options last used with each process. Several selected assets are planned and queued
together, with the same options (batch apply).
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from exchange.errors import ExchangeError
from exchange.requisitions.presets import last_used_params, load_presets, save_preset

COLLISIONS = (("Stop and ask", "ask"), ("Overwrite (old files kept in the recycle folder)", "overwrite"),
              ("Rename the new files", "rename"), ("Skip those files", "skip"))
AUTO = "auto"


def make_editor(parameter, value) -> tuple[QWidget, callable]:
    """An editor for one process option, and a function reading its value."""
    kind = parameter.type
    if kind == "bool":
        box = QCheckBox()
        box.setChecked(bool(value))
        return box, box.isChecked
    if kind == "int":
        box = QSpinBox()
        box.setRange(int(parameter.min if parameter.min is not None else -10**9),
                     int(parameter.max if parameter.max is not None else 10**9))
        box.setValue(int(value))
        return box, box.value
    if kind == "float":
        box = QDoubleSpinBox()
        box.setDecimals(4)
        box.setRange(float(parameter.min if parameter.min is not None else -1e9),
                     float(parameter.max if parameter.max is not None else 1e9))
        box.setValue(float(value))
        return box, box.value
    if kind == "choice":
        box = QComboBox()
        box.addItems(list(parameter.choices))
        box.setCurrentText(str(value))
        return box, box.currentText
    edit = QLineEdit(str(value))
    if kind == "path":
        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        browse = QPushButton("…")
        browse.clicked.connect(lambda: (path := QFileDialog.getOpenFileName(holder)[0]) and edit.setText(path))
        row.addWidget(edit, 1)
        row.addWidget(browse)
        return holder, edit.text
    return edit, edit.text


class RequisitionDialog(QDialog):
    queued = Signal(list, bool)  # requisition ids, run now?

    def __init__(self, window, uids: list[str]) -> None:
        super().__init__(window)
        self.window, self.service, self.uids = window, window.service, list(uids)
        self.plans: list = []
        self.endpoint_folder: str | None = None
        self.excluded: set[str] = set()  # dossiers the user unchecked
        self.editors: dict[tuple[str, str], tuple[QWidget, callable]] = {}
        self.defaults: dict = {}  # a chosen preset's options
        self.setWindowTitle("Requisition to…")
        self.resize(1000, 640)

        names = [self.service.detail(u)["name"] for u in self.uids[:3]]
        title = QLabel(names[0] if len(self.uids) == 1 else f"{len(self.uids)} assets: {', '.join(names)}"
                       + ("…" if len(self.uids) > 3 else ""))
        title.setObjectName("inspectorName")

        form = QFormLayout()
        self.environment = QComboBox()
        for env in self.service.environments():
            self.environment.addItem(env["name"], env["id"])
        self.route = QComboBox()
        self.preset = QComboBox()
        save = QPushButton("Save as preset…")
        save.clicked.connect(self.save_preset)
        presets = QHBoxLayout()
        presets.addWidget(self.preset, 1)
        presets.addWidget(save)
        self.endpoint_label = QLabel()
        self.endpoint_label.setWordWrap(True)
        change, reset = QPushButton("Change…"), QPushButton("Default")
        change.clicked.connect(self._choose_endpoint)
        reset.clicked.connect(lambda: self.set_endpoint(None))
        endpoint = QHBoxLayout()
        endpoint.addWidget(self.endpoint_label, 1)
        endpoint.addWidget(change)
        endpoint.addWidget(reset)
        self.collision = QComboBox()
        for label, value in COLLISIONS:
            self.collision.addItem(label, value)
        form.addRow("To", self.environment)
        form.addRow("Route", self.route)
        form.addRow("Preset", presets)
        form.addRow("Endpoint", endpoint)
        form.addRow("If files exist", self.collision)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Asset", "Process", "From", "Notes"])
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.itemChanged.connect(self._on_check)
        self.options_area = QScrollArea()
        self.options_area.setWidgetResizable(True)
        self.options_body = QWidget()
        self.options_layout = QVBoxLayout(self.options_body)
        self.options_area.setWidget(self.options_body)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.tree)
        splitter.addWidget(self.options_area)
        splitter.setSizes([620, 360])

        self.warnings = QLabel()
        self.warnings.setObjectName("error")
        self.warnings.setWordWrap(True)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        self.add_button = QPushButton("Add to queue")
        self.run_button = QPushButton("Add and run")
        self.run_button.setObjectName("primary")
        self.add_button.clicked.connect(lambda: self.queue(run=False))
        self.run_button.clicked.connect(lambda: self.queue(run=True))
        for b in (cancel, self.add_button, self.run_button):
            buttons.addWidget(b)

        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addLayout(form)
        layout.addWidget(splitter, 1)
        layout.addWidget(self.warnings)
        layout.addLayout(buttons)

        self.timer = QTimer(self, singleShot=True, interval=250)
        self.timer.timeout.connect(lambda: self.isVisible() and self.replan())  # not after it closed
        self.environment.currentIndexChanged.connect(lambda _: self._environment_changed())
        self.route.currentIndexChanged.connect(lambda _: self.replan(keep_options=True))
        self.preset.currentIndexChanged.connect(lambda _: self._preset_changed())
        self.collision.currentIndexChanged.connect(lambda _: self.replan(keep_options=True))
        self._load_presets()
        self._environment_changed()

    def hideEvent(self, event) -> None:
        self.timer.stop()  # a closed dialog does not plan again
        super().hideEvent(event)

    # Choices ----------------------------------------------------------------------------------

    def environment_id(self) -> int | None:
        return self.environment.currentData()

    def set_environment(self, environment_id: int) -> None:
        self.environment.setCurrentIndex(self.environment.findData(environment_id))

    def _environment_changed(self) -> None:
        """Offer the routes the assets (and products' children) have into this environment."""
        env = self.environment_id()
        self.route.blockSignals(True)
        self.route.clear()
        self.route.addItem("Automatic: the best route for each asset", AUTO)
        if env is not None:
            chains: dict[tuple, str] = {}
            subjects = list(self.uids)
            for uid in self.uids[:20]:
                detail = self.service.detail(uid)
                subjects += [c["uid"] for c in (detail or {}).get("children", [])[:50]]
            for uid in subjects[:200]:
                try:
                    for r in self.service.routes(uid, env):
                        names = " → ".join(self.service.registry().get(p).manifest.name for p in r["processes"])
                        chains.setdefault(tuple(r["processes"]), ("Copy: " if r["route"] == "copy" else "") + names)
                except ExchangeError:
                    continue
            for chain, label in chains.items():
                self.route.addItem(label, list(chain))
        self.route.blockSignals(False)
        self.replan()

    def set_route(self, processes: list[str] | None) -> None:
        index = self.route.findData(processes if processes else AUTO)
        if index >= 0:
            self.route.setCurrentIndex(index)

    def _load_presets(self) -> None:
        self.presets = load_presets(self.service.registry())
        self.preset.blockSignals(True)
        self.preset.clear()
        self.preset.addItem("Options last used with each process", None)
        for name in sorted(self.presets, key=str.casefold):
            self.preset.addItem(name, name)
        self.preset.blockSignals(False)

    def set_preset(self, name: str | None) -> None:
        """Choose (or choose again) a preset: its options replace the forms'."""
        index = max(0, self.preset.findData(name))
        if index == self.preset.currentIndex():
            self._preset_changed()  # choosing the same one again still applies it
        else:
            self.preset.setCurrentIndex(index)

    def _preset_changed(self) -> None:
        name = self.preset.currentData()
        self.defaults = self.presets[name].params() if name else {}
        self.replan(keep_options=False)  # the preset's values replace what the forms held

    def _choose_endpoint(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Write the output to", self.endpoint_folder or "")
        if folder:
            self.set_endpoint(folder)

    def set_endpoint(self, folder: str | None) -> None:
        self.endpoint_folder = folder
        self.replan(keep_options=True)

    def options(self) -> dict[str, dict]:
        """The option forms' values, by process."""
        out: dict[str, dict] = {}
        for (process, key), (_, read) in self.editors.items():
            out.setdefault(process, {})[key] = read()
        return out

    def set_option(self, process: str, key: str, value) -> None:
        widget, _ = self.editors[(process, key)]
        target = widget.findChild(QLineEdit) if not isinstance(widget, (QCheckBox, QSpinBox, QDoubleSpinBox,
                                                                       QComboBox, QLineEdit)) else widget
        if isinstance(target, QCheckBox):
            target.setChecked(bool(value))
        elif isinstance(target, (QSpinBox, QDoubleSpinBox)):
            target.setValue(value)
        elif isinstance(target, QComboBox):
            target.setCurrentText(str(value))
        else:
            target.setText(str(value))
        self.replan(keep_options=True)

    # Planning ---------------------------------------------------------------------------------

    def replan(self, keep_options: bool = True) -> None:
        env = self.environment_id()
        self.plans = []
        self._rebuild_forms = not keep_options
        problems = []
        if env is None:
            self._show([], ["Add an environment first."])
            return
        route = self.route.currentData()
        chain = None if route in (None, AUTO) else route
        typed = {f"{p}.{k}": v for p, values in (self.options() if keep_options else {}).items() for k, v in values.items()}
        # A chosen preset's options, otherwise those last used with each process; what the forms
        # hold (typed) wins over both.
        defaults = self.defaults or last_used_params(sorted(self.service.registry().packages))
        for uid in self.uids:
            try:
                plan = self.service.plan(uid, env, processes=chain, params=typed, defaults=defaults,
                                         endpoint_folder=self.endpoint_folder,
                                         on_collision=self.collision.currentData())
            except ExchangeError as exc:
                problems.append(str(exc))
                continue
            for item in plan.items:
                if item.dossier_uid in self.excluded:
                    item.include = False
            self.plans.append(plan)
            problems += plan.warnings
        self._show(self.plans, problems)

    def _show(self, plans: list, problems: list[str]) -> None:
        self.tree.blockSignals(True)
        self.tree.clear()
        for plan in plans:
            top = None
            for n, item in enumerate(plan.items):
                registry = self.service.registry()
                how = " → ".join(registry.get(p).manifest.name for p in item.processes) if item.processes else "—"
                row = QTreeWidgetItem([item.name, how, item.source, "; ".join(item.problems)])
                for column in range(4):
                    row.setToolTip(column, row.text(column))
                row.setData(0, Qt.ItemDataRole.UserRole, item.dossier_uid)
                if item.processes:
                    row.setFlags(row.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    row.setCheckState(0, Qt.CheckState.Checked if item.include else Qt.CheckState.Unchecked)
                else:
                    row.setDisabled(True)
                if n == 0 or top is None:
                    self.tree.addTopLevelItem(row)
                    top = row
                else:
                    top.addChild(row)
            if top is not None:
                top.setExpanded(True)
        self.tree.blockSignals(False)
        self._summary(plans, problems)

    def _summary(self, plans: list, problems: list[str]) -> None:
        """Everything but the tree: option forms, endpoint, warnings, buttons."""
        self._build_options(plans)
        if plans:
            endpoint = plans[0].endpoint
            zwsp = chr(0x200B)  # lets a long path wrap after each separator
            self.endpoint_label.setText(f"{endpoint.label} · {endpoint.visibility}\n"
                                        + endpoint.folder.replace("\\", "\\" + zwsp).replace("/", "/" + zwsp))
            self.endpoint_label.setToolTip(endpoint.folder)
        self.warnings.setText("\n".join(dict.fromkeys(problems)))
        count = sum(1 for p in plans for i in p.items if i.include)
        self.add_button.setEnabled(count > 0)
        self.run_button.setEnabled(count > 0 and not self.window.runner.running)
        self.add_button.setText(f"Add to queue ({count})" if count else "Add to queue")

    def _build_options(self, plans: list) -> None:
        """One form per process in the plan, keeping values the user already set."""
        values: dict[str, dict] = {}
        for plan in plans:
            for item in plan.items:
                if item.include:
                    for process, v in item.params.items():
                        values.setdefault(process, v)
        wanted = [(p, k) for p, v in values.items() for k in v]
        if [k for k in self.editors] == wanted and not getattr(self, "_rebuild_forms", False):
            return  # the same forms: keep them (and their focus)
        while self.options_layout.count():
            widget = self.options_layout.takeAt(0).widget()
            if widget:
                widget.setParent(None)
                widget.deleteLater()
        self.editors = {}
        registry = self.service.registry()
        for process, current in values.items():
            manifest = registry.get(process).manifest
            if not manifest.parameters:
                continue
            group = QGroupBox(manifest.name)
            form = QFormLayout(group)
            for parameter in manifest.parameters:
                editor, read = make_editor(parameter, current.get(parameter.id, parameter.default))
                editor.setToolTip(parameter.help)
                for signal in ("valueChanged", "toggled", "currentIndexChanged", "editingFinished"):
                    if hasattr(editor, signal):
                        getattr(editor, signal).connect(lambda *_: self.timer.start())
                form.addRow(parameter.label or parameter.id, editor)
                self.editors[(process, parameter.id)] = (editor, read)
            self.options_layout.addWidget(group)
        if not self.editors:
            self.options_layout.addWidget(QLabel("These processes have no options."))
        self.options_layout.addStretch(1)

    def _on_check(self, row: QTreeWidgetItem, column: int) -> None:
        uid = row.data(0, Qt.ItemDataRole.UserRole)
        if row.checkState(0) == Qt.CheckState.Checked:
            self.excluded.discard(uid)
        else:
            self.excluded.add(uid)
        for plan in self.plans:
            for item in plan.items:
                if item.dossier_uid == uid:
                    item.include = row.checkState(0) == Qt.CheckState.Checked and bool(item.processes)
        # Not _show: rebuilding the tree here would delete the row whose signal this is.
        self._summary(self.plans, [w for p in self.plans for w in p.warnings])

    # Saving -------------------------------------------------------------------------------------

    def save_preset(self) -> None:
        name = self.window.ask_text("Save as preset", "Preset name (it holds these options for every process):")
        if not name:
            return
        env = next((e for e in self.service.environments() if e["id"] == self.environment_id()), None)
        save_preset(name, self.options(), environment=env["type_id"] if env else None)
        self._load_presets()
        self.set_preset(name)

    def queue(self, run: bool) -> list[int]:
        from exchange_ui.service import EditError

        try:
            ids = self.service.queue(self.plans)
        except EditError as exc:
            self.warnings.setText(str(exc))
            return []
        self.queued.emit(ids, run)
        self.accept()
        return ids
