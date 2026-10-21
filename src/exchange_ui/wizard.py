"""The add-environment wizard: Sources → Review detection → Configure → Scan.

Nothing in a folder is read until the last step. Detection (step 2) only lists folders, in a
separate ``exchange scan --dry-run`` process; registering (step 3) writes to the library only.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from exchange.autodiscover import Found, Places, discover_sources
from exchange.db import open_library
from exchange.db import repository as repo
from exchange.definitions.schema import EnvironmentDefinition
from exchange.environments import register_root, set_excluded
from exchange.paths import fold
from exchange.scanner.layers.mo2 import instance_ini
from exchange.scanner.readonly import ini_value, read_ini
from exchange.scanner.scan import environment_name
from exchange_ui import theme
from exchange_ui.scanning import CliJob, ScanRunner
from exchange_ui.service import LibraryService

STEPS = ("Sources", "Review detection", "Configure", "Scan")
LAYERS = {"mo2": "Mod Organizer 2", "daz": "Daz product manifests", "unreal": "Unreal project content",
          "folder": "Folders"}
LAYER_SHORT = {"mo2": "MO2", "daz": "Manifests", "unreal": "Unreal project", "folder": "Folders"}
ENRICH_STEPS = ("hashing", "duplicates", "meshes", "dependencies", "thumbnails")
STEP_TEXT = {"discovery": "Discovering files", "identification": "Grouping products",
             "hashing": "Hashing", "duplicates": "Finding duplicates", "meshes": "Measuring meshes",
             "dependencies": "Reading dependencies", "thumbnails": "Rendering thumbnails"}


@dataclass
class Candidate:
    """One folder that could become (part of) an environment."""

    path: str
    type_id: str
    confidence: float
    signals: list[str]
    files: int | None
    variant: str | None
    origin: str  # the added folder it was detected in, or how it was found on this PC
    found_on_pc: bool = False
    registered: bool = False
    selected: bool = True
    name: str = ""


@dataclass
class Plan:
    """One environment to add (a Daz Studio environment can hold several roots)."""

    type_id: str
    roots: list[Candidate]
    name: str
    config: dict = field(default_factory=dict)
    env_id: int | None = None


def confidence_tag(value: float) -> tuple[str, str]:
    if value >= 0.8:
        return "High confidence", f"color: #7fd6a0; background: #16281e; border: 1px solid #24432f;"
    if value >= 0.5:
        return "Medium confidence", f"color: {theme.ACCENT_LIGHT}; background: {theme.ACCENT_BG};"
    return "Low confidence", f"color: {theme.WARN_LIGHT}; background: {theme.WARN_BG}; border: 1px solid {theme.WARN_BORDER};"


def _tag(text: str, style: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet(f"{style} border-radius: 8px; padding: 1px 7px; font-size: 7.5pt;")
    return label


class ElidedLabel(QLabel):
    """A single-line label that elides in the middle instead of forcing its width (for paths)."""

    def __init__(self, text: str) -> None:
        super().__init__()
        self._full = text
        self.setToolTip(text)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(60)
        super().setText(text)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        super().setText(self.fontMetrics().elidedText(self._full, Qt.TextElideMode.ElideMiddle, self.width()))


def _mono(text: str) -> QLabel:
    label = ElidedLabel(text)
    label.setFont(theme.mono_font(8))
    label.setStyleSheet(f"color: {theme.TEXT_2};")
    return label


def _muted(text: str, wrap: bool = True) -> QLabel:
    label = QLabel(text)
    label.setObjectName("muted")
    label.setWordWrap(wrap)
    return label


def _section(text: str) -> QLabel:
    label = QLabel(text.upper())
    label.setObjectName("sectionLabel")
    return label


def _scroll(widget: QWidget) -> QScrollArea:
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    area.setWidget(widget)
    return area


def mo2_profiles(root: str) -> tuple[list[str], str | None]:
    """Profiles of an MO2 instance and the one its ini selects. Reads only folder names and the ini."""
    folder = Path(root) / "profiles"
    try:
        names = sorted(e.name for e in os.scandir(folder) if e.is_dir())
    except OSError:
        names = []
    ini = instance_ini(Path(root))
    selected = ini_value(read_ini(ini), "General", "selected_profile") if ini else None
    return names, selected if selected in names else None


# Step 1: sources -----------------------------------------------------------------------------------


class _DiscoverySignals(QObject):
    done = Signal(list)


class _DiscoveryJob(QRunnable):
    def __init__(self, definitions, places: Places | None, registered: list[str],
                 signals: _DiscoverySignals) -> None:
        super().__init__()
        self.definitions, self.places, self.registered, self.signals = definitions, places, registered, signals

    def run(self) -> None:
        try:
            found = discover_sources(self.definitions, self.places, self.registered)
        except Exception:  # discovery is a convenience; never block adding folders by hand
            found = []
        self.signals.done.emit(found)


class DropZone(QFrame):
    dropped = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setAcceptDrops(True)
        self.setStyleSheet(f"QFrame {{ border: 1px dashed {theme.BORDER}; border-radius: 8px; }}")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 24, 16, 24)
        icon = QLabel("＋")
        icon.setStyleSheet(f"border: none; color: {theme.MUTED_2}; font-size: 16pt;")
        text = QLabel("Drop a folder here")
        text.setStyleSheet("border: none;")
        self.browse = QPushButton("Browse…")
        for widget in (icon, text, self.browse):
            layout.addWidget(widget, 0, Qt.AlignmentFlag.AlignHCenter)

    def dragEnterEvent(self, event) -> None:
        if any(Path(u.toLocalFile()).is_dir() for u in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        for url in event.mimeData().urls():
            if Path(url.toLocalFile()).is_dir():
                self.dropped.emit(url.toLocalFile())


class SourcesPage(QWidget):
    changed = Signal()

    def __init__(self, service: LibraryService, places: Places | None) -> None:
        super().__init__()
        self.service = service
        self.found: list[Found] = []
        self.found_boxes: list[tuple[QCheckBox, Found]] = []
        self.folders: list[Path] = []
        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(20)

        left = QVBoxLayout()
        title = QLabel("Found on this PC")
        title.setStyleSheet("font-weight: 600;")
        left.addWidget(title)
        left.addWidget(_muted("From Steam libraries, MO2 instances, Daz content directories, "
                              "Unreal's recent projects and the Epic launcher."))
        self.found_host = QWidget()
        self.found_layout = QVBoxLayout(self.found_host)
        self.found_layout.setContentsMargins(0, 4, 4, 4)
        self.found_layout.setSpacing(6)
        self.found_layout.addWidget(_muted("Looking…"))
        self.found_layout.addStretch(1)
        left.addWidget(_scroll(self.found_host), 1)
        layout.addLayout(left, 3)

        right = QVBoxLayout()
        title = QLabel("Add a folder")
        title.setStyleSheet("font-weight: 600;")
        right.addWidget(title)
        right.addWidget(_muted("Any folder works. If it holds several environments, Exchange splits them for you."))
        self.drop = DropZone()
        self.drop.dropped.connect(lambda p: self.add_folder(Path(p)))
        self.drop.browse.clicked.connect(self._browse)
        right.addWidget(self.drop)
        right.addSpacing(8)
        right.addWidget(_section("Folders added"))
        self.folders_layout = QVBoxLayout()
        self.folders_layout.setSpacing(6)
        right.addLayout(self.folders_layout)
        right.addStretch(1)
        layout.addLayout(right, 2)

        self._signals = _DiscoverySignals()
        self._signals.done.connect(self._on_found)
        # The job runs on a worker thread, so it gets plain data, not the library connection.
        registered = [r["path"] for r in service.roots()]
        QThreadPool.globalInstance().start(_DiscoveryJob(service.definitions, places, registered, self._signals))

    def _browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Add a folder")
        if folder:
            self.add_folder(Path(folder))

    def add_folder(self, path: Path) -> None:
        path = path.resolve()
        if any(fold(str(p)) == fold(str(path)) for p in self.folders):
            return
        self.folders.append(path)
        row = QFrame()
        row.setObjectName("card")
        h = QHBoxLayout(row)
        h.setContentsMargins(10, 6, 6, 6)
        h.addWidget(_mono(str(path)), 1)
        remove = QPushButton("×")
        remove.setFixedWidth(28)
        remove.setToolTip("Remove")
        remove.clicked.connect(lambda: self._remove_folder(path, row))
        h.addWidget(remove)
        self.folders_layout.addWidget(row)
        self.changed.emit()

    def _remove_folder(self, path: Path, row: QWidget) -> None:
        self.folders.remove(path)
        row.deleteLater()
        self.changed.emit()

    def _on_found(self, found: list) -> None:
        self.found = found
        while self.found_layout.count():
            item = self.found_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if not found:
            self.found_layout.addWidget(_muted("Nothing found automatically. Add folders on the right."))
        for f in found:
            row = QFrame()
            row.setObjectName("card")
            grid = QGridLayout(row)
            grid.setContentsMargins(10, 6, 10, 6)
            box = QCheckBox()
            box.setChecked(f.type_id is not None and not f.registered)
            box.setEnabled(f.type_id is not None and not f.registered)
            box.toggled.connect(lambda *_: self.changed.emit())
            definition = self.service.definitions.environments.get(f.type_id or "")
            kind = LAYER_SHORT.get(definition.handler, "") if definition else "no definition yet"
            name = QLabel(f"<b>{f.name}</b> <span style='color:{theme.MUTED}'>· {kind}</span>")
            grid.addWidget(box, 0, 0, 2, 1)
            grid.addWidget(name, 0, 1)
            grid.addWidget(_mono(f.path), 1, 1)
            note = "already added" if f.registered else f.via
            grid.addWidget(_muted(note, wrap=False), 0, 2, 2, 1, Qt.AlignmentFlag.AlignRight)
            grid.setColumnStretch(1, 1)
            self.found_layout.addWidget(row)
            self.found_boxes.append((box, f))
        self.found_layout.addStretch(1)
        self.changed.emit()

    def selected_found(self) -> list[Found]:
        return [f for box, f in self.found_boxes if box.isChecked()]

    def summary(self) -> str:
        n, m = len(self.selected_found()), len(self.folders)
        return f"{n} found environment{'s' * (n != 1)} + {m} folder{'s' * (m != 1)} selected"

    def ready(self) -> bool:
        return bool(self.selected_found() or self.folders)


# Step 2: review detection -----------------------------------------------------------------------


class CandidateRow(QFrame):
    changed = Signal()

    def __init__(self, candidate: Candidate, definitions) -> None:
        super().__init__()
        self.candidate = candidate
        self.setObjectName("card")
        grid = QGridLayout(self)
        grid.setContentsMargins(12, 8, 12, 8)
        grid.setHorizontalSpacing(12)
        self.box = QCheckBox()
        self.box.setChecked(candidate.selected)
        self.box.toggled.connect(self._toggled)
        grid.addWidget(self.box, 0, 0, 3, 1)

        title = QHBoxLayout()
        self.title = QLabel()
        self.title.setStyleSheet("font-weight: 600;")
        title.addWidget(self.title)
        text, style = confidence_tag(candidate.confidence)
        definition = definitions.environments[candidate.type_id]
        if definition.fallback:
            text, style = confidence_tag(0.0)
        title.addWidget(_tag(text, style))
        if candidate.registered:
            title.addWidget(_tag("In library", f"color: {theme.MUTED_2}; background: {theme.CARD};"))
        title.addStretch(1)
        grid.addLayout(title, 0, 1)
        grid.addWidget(_mono(candidate.path), 1, 1)
        if definition.fallback:
            evidence = "No environment signature · unsure groupings go to Unidentified"
        elif candidate.signals:
            evidence = "Matched " + ", ".join(candidate.signals)
        else:
            evidence = f"Found via {candidate.origin}"
        grid.addWidget(_muted(evidence), 2, 1)

        count = QLabel(f"<b>{candidate.files:,}</b><br><span style='color:{theme.MUTED}; font-size:7.5pt'>files</span>"
                       if candidate.files is not None else "")
        count.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        grid.addWidget(count, 0, 2, 3, 1)
        self.type_box = QComboBox()
        self.type_box.setToolTip("Change type")
        for env in sorted(definitions.environments.values(), key=lambda e: (e.fallback, e.name)):
            self.type_box.addItem(env.name, env.id)
        self.type_box.setCurrentIndex(self.type_box.findData(candidate.type_id))
        self.type_box.currentIndexChanged.connect(self._type_changed)
        grid.addWidget(self.type_box, 0, 3, 3, 1, Qt.AlignmentFlag.AlignVCenter)
        grid.setColumnStretch(1, 1)
        self.definitions = definitions
        self._refresh_title()

    def _refresh_title(self) -> None:
        self.title.setText(self.definitions.environments[self.candidate.type_id].name)

    def _toggled(self, on: bool) -> None:
        self.candidate.selected = on
        self.changed.emit()

    def _type_changed(self) -> None:
        self.candidate.type_id = self.type_box.currentData()
        self._refresh_title()
        self.changed.emit()


class ReviewPage(QWidget):
    changed = Signal()

    def __init__(self, service: LibraryService) -> None:
        super().__init__()
        self.service = service
        self.candidates: list[Candidate] = []
        self.jobs: list[CliJob] = []
        self.pending = 0
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 12, 20, 12)
        self.body = QWidget()
        self.layout_ = QVBoxLayout(self.body)
        self.layout_.setContentsMargins(0, 0, 6, 0)
        self.layout_.setSpacing(8)
        outer.addWidget(_scroll(self.body))

    @property
    def busy(self) -> bool:
        return self.pending > 0

    def start(self, folders: list[Path], found: list[Found]) -> None:
        for job in self.jobs:
            job.kill()
        self.jobs, self.candidates, self.pending = [], [], 0
        while self.layout_.count():
            item = self.layout_.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._slots: dict[str, QVBoxLayout] = {}
        for folder in folders:
            box = QVBoxLayout()
            box.addWidget(_muted(f"Detecting environments in {folder} …"))
            holder = QWidget()
            holder.setLayout(box)
            self.layout_.addWidget(holder)
            self._slots[str(folder)] = box
            job = CliJob(["scan", str(folder), "--dry-run"], self.service.db_path, self)
            job.finished.connect(lambda data, error, f=str(folder): self._detected(f, data, error))
            self.jobs.append(job)
            self.pending += 1
            job.start()
        self.found_candidates = [Candidate(
            path=f.path, type_id=f.type_id, confidence=f.confidence, signals=f.signals, files=None,
            variant=None, origin=f.via, found_on_pc=True, registered=f.registered, name=f.name)
            for f in found]
        if self.found_candidates:
            self.layout_.addWidget(_section("Also adding · found on this PC"))
            chips = QHBoxLayout()
            for c in self.found_candidates:
                definition = self.service.definitions.environments[c.type_id]
                chips.addWidget(_tag(f"{c.name} · {LAYER_SHORT.get(definition.handler, '')}",
                                     f"color: {theme.TEXT_2}; background: {theme.CARD}; border: 1px solid {theme.BORDER};"))
            chips.addStretch(1)
            self.layout_.addLayout(chips)
        self.layout_.addStretch(1)
        self.changed.emit()

    def _detected(self, folder: str, data, error: str) -> None:
        self.pending -= 1
        box = self._slots[folder]
        while box.count():
            item = box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if error:
            label = _muted(f"{folder}: {error}")
            label.setObjectName("error")
            box.addWidget(label)
            self.changed.emit()
            return
        rows = [(env, root) for env in data["environments"] for root in env["roots"]]
        header = QHBoxLayout()
        path = _mono(folder)
        path.setStyleSheet(f"color: {theme.TEXT}; font-weight: 600;")
        header.addWidget(path, 1)
        header.addWidget(QLabel(f"<b>holds {len(rows)} environment{'s' * (len(rows) != 1)}</b>"))
        box.addLayout(header)
        box.addWidget(_muted("Each becomes its own environment. Change a type if Exchange guessed wrong; "
                             "untick anything you don't want indexed."))
        for env, root in rows:
            candidate = Candidate(path=root["path"], type_id=env["type_id"], confidence=root["confidence"],
                                  signals=root["signals"], files=root["files"], variant=root["variant"],
                                  origin=folder, registered=root["registered"])
            self.candidates.append(candidate)
            row = CandidateRow(candidate, self.service.definitions)
            row.changed.connect(lambda *_: self.changed.emit())
            box.addWidget(row)
        self.changed.emit()

    def all_candidates(self) -> list[Candidate]:
        return self.candidates + self.found_candidates

    def summary(self) -> str:
        if self.busy:
            return "Detecting… nothing is read until you scan"
        n = len(plans_from(self.all_candidates(), self.service))
        return f"{n} environment{'s' * (n != 1)} to add · nothing is read until you scan"

    def ready(self) -> bool:
        return not self.busy and any(c.selected for c in self.all_candidates())


def plans_from(candidates: list[Candidate], service: LibraryService) -> list[Plan]:
    """Group selected candidates into environments (all Daz roots form one)."""
    plans: list[Plan] = []
    by_type: dict[str, Plan] = {}
    for c in sorted((c for c in candidates if c.selected), key=lambda c: len(c.path)):
        definition = service.definitions.environments[c.type_id]
        known = service.environment_for_root(c.path)
        if definition.multi_root and c.type_id in by_type:
            by_type[c.type_id].roots.append(c)
            continue
        if any(fold(r.path) == fold(c.path) for p in plans for r in p.roots):
            continue  # the same folder picked twice (found on this PC and inside an added folder)
        name = known["name"] if known else environment_name(definition, Path(c.path))
        config = dict(known["user_config"]) if known else {}
        plan = Plan(c.type_id, [c], name, config)
        plans.append(plan)
        if definition.multi_root:
            by_type[c.type_id] = plan
    return plans


# Step 3: configure ---------------------------------------------------------------------------------


class EnvironmentForm(QWidget):
    changed = Signal()

    def __init__(self, plan: Plan, definition: EnvironmentDefinition) -> None:
        super().__init__()
        self.plan, self.definition = plan, definition
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 0, 8, 0)
        layout.setSpacing(6)
        head = QLabel(definition.name)
        head.setStyleSheet("font-size: 12pt; font-weight: 600;")
        layout.addWidget(head)
        layout.addWidget(_muted({
            "mo2": "Exchange reads and writes this game only through MO2, so every mod is a container.",
            "daz": "Every content directory is a container; products come from Daz's install manifests.",
            "unreal": "Content packs under Content/ and plugins are containers.",
            "folder": "No mod manager or manifests here: folders are grouped by guesswork, at low confidence.",
        }.get(definition.handler, "")))

        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(4)
        grid.addWidget(_muted("Name", wrap=False), 0, 0)
        self.name = QLineEdit(plan.name)
        self.name.textChanged.connect(lambda *_: self.changed.emit())
        grid.addWidget(self.name, 1, 0)
        grid.addWidget(_muted("Organizational layer", wrap=False), 0, 1)
        layer = QComboBox()
        layer.addItem(LAYERS.get(definition.handler, definition.handler))
        if definition.handler == "mo2":
            layer.addItem("Vortex (later)")
            layer.model().item(1).setEnabled(False)
        grid.addWidget(layer, 1, 1)
        self.profile: QComboBox | None = None
        if definition.handler == "mo2":
            grid.addWidget(_muted("MO2 profile", wrap=False), 2, 0)
            self.profile = QComboBox()
            profiles, selected = mo2_profiles(plan.roots[0].path)
            self.profile.addItem("Choose a profile…", None)
            for p in profiles:
                self.profile.addItem(p, p)
            current = plan.config.get("mo2_profile") or selected or (profiles[0] if len(profiles) == 1 else None)
            if current in profiles:
                self.profile.setCurrentIndex(self.profile.findData(current))
            self.profile.currentIndexChanged.connect(lambda *_: self.changed.emit())
            grid.addWidget(self.profile, 3, 0)
        variant = next((r.variant for r in plan.roots if r.variant), None)
        names = {v.id: v.name for v in definition.variants}
        grid.addWidget(_muted("Variant", wrap=False), 2, 1)
        grid.addWidget(QLabel(names.get(variant, "Per asset" if definition.handler == "daz" else "—")), 3, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)

        layout.addWidget(_muted("Folders" if len(plan.roots) > 1 else "Folder", wrap=False))
        for root in plan.roots:
            layout.addWidget(_mono(root.path))

        layout.addSpacing(4)
        layout.addWidget(_muted("Endpoint · where requisitions write (used from Roadmap phase 4)", wrap=False))
        self.endpoint_group = QButtonGroup(self)
        self.endpoint_widgets: list[tuple[QRadioButton, str, QLineEdit | None]] = []
        endpoint = plan.config.get("endpoint") if isinstance(plan.config.get("endpoint"), dict) else {}
        options = {
            "mo2": [("new_container", "New mod for each requisition", "Exchange – {dossier}"),
                    ("managed_container", "Add to one Exchange-managed mod", "Exchange Output")],
            "daz": [("content_directory", "Exchange Conversions content directory",
                     str(Path(plan.roots[0].path).parent / "Exchange Conversions"))],
            "unreal": [("content_folder", "Content folder", "Content/Exchange")],
        }.get(definition.handler, [])
        if not options:
            layout.addWidget(_muted("Loose files are read-only to Exchange; requisitions write to another environment."))
        for i, (mode, label, default) in enumerate(options):
            row = QFrame()
            row.setObjectName("card")
            h = QHBoxLayout(row)
            h.setContentsMargins(10, 4, 10, 4)
            radio = QRadioButton(label)
            radio.setChecked(endpoint.get("mode", options[0][0]) == mode)
            edit = QLineEdit(endpoint.get("value", default) if endpoint.get("mode") == mode else default)
            edit.setFont(theme.mono_font(8))
            h.addWidget(radio, 1)
            h.addWidget(edit, 1)
            self.endpoint_group.addButton(radio, i)
            self.endpoint_widgets.append((radio, mode, edit))
            layout.addWidget(row)

        bottom = QGridLayout()
        bottom.setHorizontalSpacing(16)
        bottom.addWidget(_muted("Endpoint visibility", wrap=False), 0, 0)
        vis = QHBoxLayout()
        vis.setSpacing(0)
        self.visibility = QButtonGroup(self)
        for value in ("personal", "publishable"):
            button = QPushButton(value.capitalize())
            button.setObjectName("segment")
            button.setCheckable(True)
            button.setProperty("value", value)
            button.setChecked(plan.config.get("visibility", "personal") == value)
            self.visibility.addButton(button)
            vis.addWidget(button)
        vis.addStretch(1)
        vis_box = QVBoxLayout()
        vis_box.addLayout(vis)
        vis_box.addWidget(_muted("Publishable endpoints warn when content that can't be redistributed flows in."))
        vis_box.addStretch(1)
        bottom.addLayout(vis_box, 1, 0)
        bottom.addWidget(_muted("Ignore rules (one per line)", wrap=False), 0, 1)
        self.ignore = QPlainTextEdit("\n".join(plan.config.get("ignore", [])))
        self.ignore.setFont(theme.mono_font(8))
        self.ignore.setFixedHeight(70)
        self.ignore.setPlaceholderText("e.g. *.bak\nBodySlide/ShapeData/**")
        bottom.addWidget(self.ignore, 1, 1)
        if definition.ignore_globs:
            bottom.addWidget(_muted("Always ignored: " + ", ".join(definition.ignore_globs)), 2, 1)
        bottom.setColumnStretch(0, 1)
        bottom.setColumnStretch(1, 1)
        layout.addLayout(bottom)
        layout.addStretch(1)

    def problem(self) -> str | None:
        if self.profile is not None and self.profile.currentData() is None:
            return "needs a profile"
        if not self.name.text().strip():
            return "needs a name"
        return None

    def apply(self) -> None:
        plan = self.plan
        plan.name = self.name.text().strip()
        if self.profile is not None:
            plan.config["mo2_profile"] = self.profile.currentData()
        for radio, mode, edit in self.endpoint_widgets:
            if radio.isChecked():
                plan.config["endpoint"] = {"mode": mode, "value": edit.text().strip()}
        plan.config["visibility"] = self.visibility.checkedButton().property("value")
        rules = [line.strip() for line in self.ignore.toPlainText().splitlines() if line.strip()]
        if rules:
            plan.config["ignore"] = rules
        else:
            plan.config.pop("ignore", None)


class ConfigurePage(QWidget):
    changed = Signal()

    def __init__(self, service: LibraryService) -> None:
        super().__init__()
        self.service = service
        self.plans: list[Plan] = []
        self.forms: list[EnvironmentForm] = []
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 12, 0)
        self.list = QListWidget()
        self.list.setFixedWidth(230)
        self.list.setWordWrap(True)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setStyleSheet(f"QListWidget {{ background: {theme.PANEL}; border: none; border-right: 1px solid {theme.BORDER}; }}"
                                f" QListWidget::item {{ padding: 8px; }}"
                                f" QListWidget::item:selected {{ background: {theme.ACCENT_BG}; }}")
        self.stack = QStackedWidget()
        self.list.currentRowChanged.connect(self.stack.setCurrentIndex)
        layout.addWidget(self.list)
        layout.addWidget(_scroll(self.stack), 1)

    def set_plans(self, plans: list[Plan]) -> None:
        self.plans = plans
        self.list.clear()
        while self.stack.count():
            widget = self.stack.widget(0)
            self.stack.removeWidget(widget)
            widget.deleteLater()
        self.forms = []
        for plan in plans:
            definition = self.service.definitions.environments[plan.type_id]
            form = EnvironmentForm(plan, definition)
            form.changed.connect(self._refresh)
            self.forms.append(form)
            self.stack.addWidget(form)
            self.list.addItem(QListWidgetItem())
        self._refresh()
        self.list.setCurrentRow(0)

    def _refresh(self) -> None:
        for i, (plan, form) in enumerate(zip(self.plans, self.forms)):
            definition = self.service.definitions.environments[plan.type_id]
            detail = LAYER_SHORT.get(definition.handler, "")
            if len(plan.roots) > 1:
                detail += f" · {len(plan.roots)} folders"
            problem = form.problem()
            status = f"⚠ {problem.capitalize()}" if problem else "Ready"
            self.list.item(i).setText(f"{form.name.text() or plan.name}\n{detail} · {status}")
            self.list.item(i).setForeground(theme.color(theme.WARN_LIGHT if problem else theme.TEXT))
        self.list.doItemsLayout()  # wrapped rows change height with their text
        self.changed.emit()

    def problems(self) -> list[str]:
        return [f"{form.name.text() or plan.name} {problem}" for plan, form in zip(self.plans, self.forms)
                if (problem := form.problem())]

    def summary(self) -> str:
        problems = self.problems()
        ready = len(self.plans) - len(problems)
        text = f"{ready} of {len(self.plans)} ready"
        return text + (f" · {problems[0]}" if problems else "")

    def ready(self) -> bool:
        return bool(self.plans) and not self.problems()

    def apply(self) -> list[Plan]:
        for form in self.forms:
            form.apply()
        return self.plans


# Step 4: scan --------------------------------------------------------------------------------------


class ScanRow:
    def __init__(self, grid: QGridLayout, row: int, plan: Plan, subtitle: str) -> None:
        self.plan = plan
        name = QLabel(f"<b>{plan.name}</b><br><span style='color:{theme.MUTED}; font-size:7.5pt'>{subtitle}</span>")
        grid.addWidget(name, row, 0)
        self.bars = []
        for col in range(3):
            bar = QProgressBar()
            bar.setTextVisible(False)
            bar.setRange(0, 1000)
            bar.setValue(0)
            bar.setFixedHeight(6)
            grid.addWidget(bar, row, col + 1)
            self.bars.append(bar)
        self.status = _muted("Queued")
        grid.addWidget(self.status, row, 4)
        self.phase = 0

    def at(self, phase: int, fraction: float, text: str) -> None:
        if phase < self.phase:
            return
        self.phase = phase
        for i, bar in enumerate(self.bars, start=1):
            bar.setValue(1000 if i < phase else int(fraction * 1000) if i == phase else 0)
        self.status.setText(text)

    def done(self, text: str) -> None:
        self.phase = 4
        for bar in self.bars:
            bar.setValue(1000)
        self.status.setText(text)


class ScanPage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 12, 20, 12)
        note = QLabel("🔒  Scanning is read-only. Exchange never changes files in your environments while indexing.")
        note.setStyleSheet(f"background: {theme.ACCENT_DARK}; border: 1px solid {theme.ACCENT_BG};"
                           f" border-radius: 6px; padding: 8px 12px; color: {theme.TEXT_2};")
        layout.addWidget(note)
        body = QWidget()
        self.grid = QGridLayout(body)
        self.grid.setHorizontalSpacing(14)
        self.grid.setVerticalSpacing(12)
        for col, title in enumerate(("Environment", "1 Discovery", "2 Identification", "3 Enrichment", "Status")):
            self.grid.addWidget(_section(title), 0, col)
        self.grid.setColumnStretch(0, 3)
        for col in (1, 2, 3):
            self.grid.setColumnStretch(col, 2)
        self.grid.setColumnStretch(4, 3)
        layout.addWidget(_scroll(body), 1)
        self.footnote = _muted("Products appear in the library as soon as identification finishes. "
                               "Thumbnails, hashes and duplicate merges fill in during enrichment.")
        layout.addWidget(self.footnote)
        self.rows: list[ScanRow] = []

    def set_plans(self, plans: list[Plan], definitions) -> None:
        for i, plan in enumerate(plans, start=1):
            definition = definitions.environments[plan.type_id]
            subtitle = LAYER_SHORT.get(definition.handler, "")
            if plan.config.get("mo2_profile"):
                subtitle += f" · profile {plan.config['mo2_profile']}"
            self.rows.append(ScanRow(self.grid, i, plan, subtitle))
        self.grid.setRowStretch(len(plans) + 1, 1)

    def row_for(self, event: dict) -> ScanRow | None:
        where = fold(str(event.get("environment", "")))
        for row in self.rows:
            if where == fold(row.plan.name) or any(where == fold(r.path) for r in row.plan.roots):
                return row
        # A folder scan covers environments nested inside it.
        return next((row for row in self.rows if any(fold(r.path).startswith(where + os.sep) for r in row.plan.roots)), None)

    def progress(self, event: dict) -> None:
        row = self.row_for(event)
        if row is None:
            return
        for earlier in self.rows[: self.rows.index(row)]:
            if 0 < earlier.phase < 4:
                earlier.done("Done")
        phase, step = event.get("phase", 1), event.get("step", "")
        done, total = event.get("done", 0), event.get("total", 0)
        fraction = done / total if total else 0.0
        if phase == 3 and step in ENRICH_STEPS:
            fraction = (ENRICH_STEPS.index(step) + fraction) / len(ENRICH_STEPS)
        count = f" · {done:,} / {total:,}" if total else ""
        row.at(phase, fraction, STEP_TEXT.get(step, step) + count)

    def finished(self, report: dict, error: str) -> None:
        dossiers: dict[str, int] = {}
        for env in report.get("environments", []):
            dossiers[fold(env["name"])] = sum((r.get("identification") or {}).get("dossiers", 0) for r in env["roots"])
        for row in self.rows:
            if error and row.phase < 4:
                row.status.setText("Stopped" if "stopped" in error else "Failed")
                continue
            count = dossiers.get(fold(row.plan.name))
            row.done(f"Done · {count:,} dossiers" if count is not None else "Done")


# The dialog ----------------------------------------------------------------------------------------


class AddEnvironmentsDialog(QDialog):
    reviewUnidentified = Signal()

    def __init__(self, service: LibraryService, runner: ScanRunner, parent: QWidget | None = None,
                 places: Places | None = None) -> None:
        super().__init__(parent)
        self.service, self.runner = service, runner
        self.setWindowTitle("Add environments")
        self.setModal(True)
        self.resize(980, 700)
        self.setStyleSheet(f"QDialog {{ background: {theme.SURFACE}; }}")
        self.step = 0
        self.plans: list[Plan] = []
        self.scanning = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        head = QWidget()
        head_layout = QVBoxLayout(head)
        head_layout.setContentsMargins(20, 16, 20, 10)
        top = QHBoxLayout()
        title = QLabel("Add environments")
        title.setStyleSheet("font-size: 13pt; font-weight: 600;")
        top.addWidget(title)
        top.addStretch(1)
        close = QPushButton("×")
        close.setFixedWidth(30)
        close.setToolTip("Close (a running scan continues in the background)")
        close.clicked.connect(self.reject)
        top.addWidget(close)
        head_layout.addLayout(top)
        steps = QHBoxLayout()
        self.step_labels = []
        for i, name in enumerate(STEPS):
            label = QLabel()
            self.step_labels.append(label)
            steps.addWidget(label)
            if i < len(STEPS) - 1:
                steps.addStretch(1)
        head_layout.addLayout(steps)
        layout.addWidget(head)
        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet(f"background: {theme.BORDER};")
        layout.addWidget(line)

        self.pages = QStackedWidget()
        self.sources = SourcesPage(service, places)
        self.review = ReviewPage(service)
        self.configure = ConfigurePage(service)
        self.scan_page = ScanPage()
        for page in (self.sources, self.review, self.configure, self.scan_page):
            self.pages.addWidget(page)
            if hasattr(page, "changed"):
                page.changed.connect(self._update)
        layout.addWidget(self.pages, 1)

        foot = QWidget()
        foot.setObjectName("wizardFoot")
        foot.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        foot.setStyleSheet(f"#wizardFoot {{ background: {theme.PANEL}; border-top: 1px solid {theme.BORDER}; }}")
        foot_layout = QHBoxLayout(foot)
        foot_layout.setContentsMargins(20, 12, 20, 12)
        self.summary = _muted("", wrap=False)
        foot_layout.addWidget(self.summary, 1)
        self.secondary = QPushButton()
        self.secondary.clicked.connect(self._secondary)
        self.primary = QPushButton()
        self.primary.setObjectName("primary")
        self.primary.clicked.connect(self._primary)
        foot_layout.addWidget(self.secondary)
        foot_layout.addWidget(self.primary)
        layout.addWidget(foot)

        runner.progress.connect(self._on_progress)
        runner.finished.connect(self._on_finished)
        self._update()

    # Navigation -------------------------------------------------------------------------------

    def _go(self, step: int) -> None:
        self.step = step
        self.pages.setCurrentIndex(step)
        self._update()

    def _primary(self) -> None:
        if self.step == 0:
            self.review.start(self.sources.folders, self.sources.selected_found())
            self._go(1)
        elif self.step == 1:
            self.configure.set_plans(plans_from(self.review.all_candidates(), self.service))
            self._go(2)
        elif self.step == 2:
            self.add_and_scan()
        else:
            self.accept()

    def _secondary(self) -> None:
        if self.step == 0:
            self.reject()
        elif self.step in (1, 2):
            self._go(self.step - 1)
        else:
            self.reviewUnidentified.emit()
            self.accept()

    def _update(self) -> None:
        for i, (label, name) in enumerate(zip(self.step_labels, STEPS)):
            mark = "✓" if i < self.step else str(i + 1)
            color = theme.ACCENT_LIGHT if i == self.step else theme.MUTED_2
            circle = theme.ACCENT if i == self.step else theme.CARD
            text_color = theme.ACCENT_DARK if i == self.step else theme.MUTED_2
            label.setText(f"<span style='background:{circle}; color:{text_color}; border-radius:9px;'>&nbsp;{mark}&nbsp;</span>"
                          f"&nbsp;<span style='color:{color}; font-weight:{600 if i == self.step else 400}'>{name}</span>")
        page = [self.sources, self.review, self.configure, None][self.step]
        if self.step == 3:
            self.secondary.setText("Review Unidentified")
            self.primary.setText("Continue in background" if self.scanning else "Done")
            self.primary.setEnabled(True)
            return
        self.secondary.setText("Cancel" if self.step == 0 else "Back")
        self.primary.setText(["Detect environments  →", "Configure  →", "Add and scan  →"][self.step])
        ready = page.ready()
        if self.step == 2 and self.runner.running:
            ready = False
            self.summary.setText("Another scan is running; wait for it to finish, then add and scan.")
        else:
            self.summary.setText(page.summary())
        self.primary.setEnabled(ready)

    # Adding -----------------------------------------------------------------------------------

    def add_and_scan(self) -> None:
        plans = self.configure.apply()
        conn = open_library(self.service.db_path)
        try:
            with repo.transaction(conn):
                for plan in plans:
                    for root in sorted(plan.roots, key=lambda r: len(r.path)):
                        plan.env_id = register_root(
                            conn, self.service.definitions, Path(root.path), plan.type_id, name=plan.name,
                            config=plan.config, confidence=root.confidence, signals=root.signals)
                # Unticked folders found inside an added folder are never indexed.
                for c in self.review.candidates:
                    if not c.selected and not c.registered and fold(c.path) != fold(c.origin):
                        set_excluded(conn, Path(c.path))
        finally:
            conn.close()
        self.plans = plans
        self.scan_page.set_plans(plans, self.service.definitions)
        self.scanning = True
        self._go(3)
        self.runner.rescan(sorted({p.env_id for p in plans}))

    def _on_progress(self, event: dict) -> None:
        if self.step == 3:
            self.scan_page.progress(event)
            if event.get("phase") == 3 and event.get("done") == 0:
                self._update_counts()

    def _on_finished(self, report: dict, error: str) -> None:
        if self.step != 3:
            self._update()
            return
        self.scanning = False
        self.scan_page.finished(report, error)
        self._update_counts()
        if error:
            self.summary.setText(error)
        self._update()

    def _update_counts(self) -> None:
        ids = {p.env_id for p in self.plans}
        bar = self.service.sidebar()
        products = sum(t["count"] for e in bar["environments"] if e["id"] in ids
                       for t in e["types"] if t["type_id"] == "product")
        unidentified = bar["unidentified_dossiers"]
        self.summary.setText(f"{products:,} products found so far · "
                             f"<span style='color:{theme.WARN_LIGHT}'>{unidentified:,} sent to Unidentified</span>")
        self.summary.setTextFormat(Qt.TextFormat.RichText)
