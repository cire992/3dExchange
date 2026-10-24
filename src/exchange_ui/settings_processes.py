"""Settings › Processes and Settings › Endpoints.

* **Processes:** every package, with its prerequisites green or red. Here you set a tool's
  path, install a package folder, and trust a package after reading what it runs and where it
  writes. Only trusted packages with every prerequisite green are offered for requisitions.
* **Endpoints:** where each environment's requisitions write (its default, or a folder you
  choose) and whether that is personal or publishable, which drives the license check.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from exchange.errors import ExchangeError
from exchange.processes.registry import (
    check_prerequisites,
    describe_trust,
    install,
    ready,
    set_tool,
    trust,
    validate,
)


def _clear(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget:
            widget.setParent(None)
            widget.deleteLater()
        elif item.layout():
            _clear(item.layout())


class ProcessesPage(QWidget):
    def __init__(self, window, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.window, self.service = window, window.service
        self.list = QListWidget()
        self.list.currentItemChanged.connect(lambda *_: self._show())
        install_button = QPushButton("Install a package…")
        install_button.clicked.connect(self._install)
        left = QWidget()
        side = QVBoxLayout(left)
        side.setContentsMargins(0, 0, 0, 0)
        side.addWidget(self.list, 1)
        side.addWidget(install_button)
        self.body = QWidget()
        self.details = QVBoxLayout(self.body)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.body)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(scroll)
        splitter.setSizes([260, 640])
        self.status = QLabel()
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.addWidget(splitter, 1)
        layout.addWidget(self.status)
        self.reload()

    def reload(self, select: str | None = None) -> None:
        current = select or self.current_id()
        registry = self.service.registry(reload=True)
        self.list.blockSignals(True)
        self.list.clear()
        for package in sorted(registry.packages.values(), key=lambda p: p.manifest.name.casefold()):
            state = "ready" if ready(package) else "not trusted" if not package.trusted else "needs setup"
            item = QListWidgetItem(f"{package.manifest.name}\n{package.manifest.version} · {state}"
                                   + (" · built in" if package.builtin else ""))
            item.setData(Qt.ItemDataRole.UserRole, package.id)
            self.list.addItem(item)
            if package.id == current:
                self.list.setCurrentItem(item)
        if self.list.currentItem() is None and self.list.count():
            self.list.setCurrentRow(0)
        self.list.blockSignals(False)
        if registry.problems:
            self.status.setText("Could not read: " + "; ".join(registry.problems))
        self._show()

    def current_id(self) -> str | None:
        item = self.list.currentItem() if hasattr(self, "list") else None
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def select(self, process_id: str) -> None:
        for r in range(self.list.count()):
            if self.list.item(r).data(Qt.ItemDataRole.UserRole) == process_id:
                self.list.setCurrentRow(r)

    def _show(self) -> None:
        _clear(self.details)
        package = self.service.registry().packages.get(self.current_id())
        if package is None:
            return
        m = package.manifest
        title = QLabel(f"{m.name}  {m.version}")
        title.setObjectName("inspectorName")
        self.details.addWidget(title)
        about = [m.description, f"By {m.author or 'an unnamed author'} · {package.path}",
                 f"Takes {', '.join(m.input_types) or 'any asset'}"
                 + (f" tagged {', '.join(m.input_tags)}" if m.input_tags else "")
                 + f" → {'the same kind of environment' if m.output_environment == 'same' else m.output_environment}",
                 "Steps: " + " → ".join(s.operation for s in m.steps)]
        text = QLabel("\n".join(a for a in about if a))
        text.setObjectName("subtitle")
        text.setWordWrap(True)
        self.details.addWidget(text)

        if not package.trusted:
            warn = QLabel("Not trusted: it will not run until you trust it.\n" + "\n".join(describe_trust(package)))
            warn.setObjectName("warnChip")
            warn.setWordWrap(True)
            self.details.addWidget(warn)
            trust_button = QPushButton("Trust this package…")
            trust_button.setObjectName("primary")
            trust_button.clicked.connect(lambda: self._trust(package.id))
            self.details.addWidget(trust_button, 0, Qt.AlignmentFlag.AlignLeft)

        statuses = check_prerequisites(package)
        heading = QLabel("PREREQUISITES" if statuses else "No prerequisites.")
        heading.setObjectName("sectionLabel" if statuses else "muted")
        self.details.addWidget(heading)
        grid = QGridLayout()
        tools = {p.id: p.tool for p in m.prerequisites if p.kind == "tool"}
        for row, status in enumerate(statuses):
            mark = QLabel("✓" if status.ok else "✗")
            mark.setObjectName("subtitle" if status.ok else "error")
            grid.addWidget(mark, row, 0)
            label = QLabel(f"{status.label}\n{status.detail}")
            label.setWordWrap(True)
            label.setObjectName("subtitle")
            grid.addWidget(label, row, 1)
            if status.id in tools:
                button = QPushButton("Set path…")
                button.clicked.connect(lambda _=False, t=tools[status.id]: self._set_tool(t))
                grid.addWidget(button, row, 2, Qt.AlignmentFlag.AlignTop)
        grid.setColumnStretch(1, 1)
        self.details.addLayout(grid)
        if package.trusted:
            problems = validate(package)
            if problems:
                bad = QLabel("Problems: " + "; ".join(problems))
                bad.setObjectName("error")
                bad.setWordWrap(True)
                self.details.addWidget(bad)
        if m.parameters:
            options = QLabel("Options: " + ", ".join(f"{p.label or p.id} ({p.default!r})" for p in m.parameters))
            options.setObjectName("muted")
            options.setWordWrap(True)
            self.details.addWidget(options)
        self.details.addStretch(1)

    def _set_tool(self, tool: str) -> None:
        path = self.window.ask_file(f"Where is {tool}?")
        if path:
            set_tool(tool, path)
            self.status.setText(f"{tool}: {path}")
            self.reload()

    def _trust(self, process_id: str) -> None:
        package = self.service.registry().get(process_id)
        text = "\n".join(describe_trust(package)) + "\n\nA process runs its own code. Trust it?"
        if self.window.confirm("Trust this process?", text):
            trust(package)
            self.status.setText(f"Trusted {package.manifest.name}")
            self.reload(select=process_id)

    def _install(self) -> None:
        folder = self.window.ask_folder("Choose a process package folder (it holds process.toml)")
        if not folder:
            return
        try:
            package = install(folder)
        except ExchangeError as exc:
            self.status.setText(str(exc))
            return
        self.status.setText(f"Installed {package.manifest.name}; trust it to use it.")
        self.reload(select=package.id)


class EndpointsPage(QWidget):
    def __init__(self, window, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.window, self.service = window, window.service
        self.grid = QGridLayout()
        self.grid.setColumnStretch(1, 1)
        intro = QLabel("Requisitions write only here: never into your existing mods or content folders. "
                       "Publishable endpoints get a warning when content that may not be redistributed goes there.")
        intro.setObjectName("subtitle")
        intro.setWordWrap(True)
        self.status = QLabel()
        self.status.setObjectName("muted")
        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addLayout(self.grid)
        layout.addStretch(1)
        layout.addWidget(self.status)
        self.reload()

    def reload(self) -> None:
        _clear(self.grid)
        self.rows = {}
        for row, env in enumerate(self.service.environments()):
            config = env["user_config"]
            try:
                endpoint = self.service.default_endpoint(env["id"])
                where = f"{endpoint.label}\n{endpoint.folder}"
            except ExchangeError as exc:
                where = str(exc)
            name = QLabel(env["name"])
            place = QLabel(where)
            place.setObjectName("subtitle")
            place.setWordWrap(True)
            visibility = QComboBox()
            visibility.addItems(["personal", "publishable"])
            visibility.setCurrentText(config.get("visibility", "personal"))
            visibility.currentTextChanged.connect(lambda v, e=env["id"]: self._save(e, visibility=v))
            choose = QPushButton("Change…")
            choose.clicked.connect(lambda _=False, e=env["id"]: self._choose(e))
            default = QPushButton("Default")
            default.setEnabled(bool(config.get("endpoint")))
            default.clicked.connect(lambda _=False, e=env["id"]: self._save(e, folder=""))
            buttons = QHBoxLayout()
            buttons.addWidget(visibility)
            buttons.addWidget(choose)
            buttons.addWidget(default)
            self.grid.addWidget(name, row, 0, Qt.AlignmentFlag.AlignTop)
            self.grid.addWidget(place, row, 1)
            self.grid.addLayout(buttons, row, 2, Qt.AlignmentFlag.AlignTop)
            self.rows[env["id"]] = (place, visibility)

    def _choose(self, environment_id: int) -> None:
        folder = self.window.ask_folder("Requisitions for this environment write to")
        if folder:
            self._save(environment_id, folder=folder)

    def _save(self, environment_id: int, folder: str | None = None, visibility: str | None = None) -> None:
        from exchange_ui.service import EditError

        env = next(e for e in self.service.environments() if e["id"] == environment_id)
        try:
            self.service.set_endpoint(environment_id, folder if folder is not None else env["user_config"].get("endpoint"),
                                      visibility)
        except EditError as exc:
            self.status.setText(str(exc))
            return
        self.status.setText(f"Saved for {env['name']}")
        self.reload()
