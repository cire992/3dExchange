"""Qt models over the library: the sidebar tree and the paged browser grid."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import (
    QAbstractListModel,
    QMimeData,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    QRunnable,
    Qt,
    QThreadPool,
    Signal,
)
from PySide6.QtGui import QImage, QStandardItem, QStandardItemModel

from exchange.library.query import Brick
from exchange_ui.service import Filter, LibraryService

# Sidebar roles
KIND = Qt.ItemDataRole.UserRole + 1  # all | environment | container | type | section | group
ENV_ID = Qt.ItemDataRole.UserRole + 2
CONTAINER_ID = Qt.ItemDataRole.UserRole + 3
TYPE_ID = Qt.ItemDataRole.UserRole + 4
COUNT = Qt.ItemDataRole.UserRole + 5
DETAIL = Qt.ItemDataRole.UserRole + 6  # small grey text after the name (e.g. "MO2", "offline")
COLLECTION_UID = Qt.ItemDataRole.UserRole + 7
SMART = Qt.ItemDataRole.UserRole + 8  # a collection that is a saved search

# Drag and drop: dossier uids, one per line.
DOSSIER_MIME = "application/x-exchange-dossiers"

# Browser roles
BRICK = Qt.ItemDataRole.UserRole + 20
THUMBNAIL = Qt.ItemDataRole.UserRole + 21

CONTAINERS_INLINE = 12  # more containers than this are grouped under one node
_LAYER_LABELS = {"skyrim_se": "MO2", "mo2_generic": "MO2"}
_GROUP_LABELS = {"mod": "Mods", "content_pack": "Content packs", "plugin": "Plugins",
                 "folder": "Folders", "content_directory": "Content directories"}


class SidebarModel(QStandardItemModel):
    def __init__(self, service: LibraryService, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.service = service
        self.unidentified = 0
        self.unattached = 0
        self.changed: set[int] = set()  # environments with changes on disk since their last scan
        self._env_details: dict[int, str] = {}

    def env_detail(self, environment_id: int) -> str:
        """The grey text after an environment's name: its layer, status and pending changes."""
        detail = self._env_details.get(environment_id, "")
        if environment_id in self.changed:
            detail = f"{detail} · changes detected".strip(" ·")
        return detail

    def reload(self) -> None:
        data = self.service.sidebar()
        self.clear()
        self.unidentified, self.unattached = data["unidentified_dossiers"], data["unattached_files"]
        root = self.invisibleRootItem()
        root.appendRow(_item("LIBRARY", "section"))
        root.appendRow(_item("All assets", "all", count=data["all"]))
        root.appendRow(_item("Requisitions", "queue", count=self._active_requisitions()))
        root.appendRow(_item("COLLECTIONS", "section"))
        for row in self._collection_rows():
            root.appendRow(row)
        root.appendRow(_item("ENVIRONMENTS", "section"))
        for env in data["environments"]:
            detail = _LAYER_LABELS.get(env["type_id"], "")
            if env["status"] != "online":
                detail = f"{detail} · {env['status']}".strip(" ·")
            self._env_details[env["id"]] = detail
            env_item = _item(env["name"], "environment", count=env["count"], env_id=env["id"],
                             detail=self.env_detail(env["id"]))
            containers = [c for c in env["containers"] if c["count"]]
            if len(containers) > 1:
                parent = env_item
                if len(containers) > CONTAINERS_INLINE:
                    kinds = {c["kind"] for c in containers}
                    label = _GROUP_LABELS.get(kinds.pop(), "Containers") if len(kinds) == 1 else "Containers"
                    parent = _item(label, "environment", count=len(containers), env_id=env["id"])
                    parent.setData("group", KIND)
                    env_item.appendRow(parent)
                for c in containers:
                    parent.appendRow(_item(c["name"], "container", count=c["count"], env_id=env["id"],
                                           container_id=c["id"]))
            for t in sorted(env["types"], key=lambda t: t["name"]):
                env_item.appendRow(_item(t["name"], "type", count=t["count"], env_id=env["id"],
                                         type_id=t["type_id"]))
            root.appendRow(env_item)

    def _active_requisitions(self) -> int:
        try:
            return sum(1 for r in self.service.requisitions() if r["state"] in ("queued", "held", "running",
                                                                              "needs_attention"))
        except Exception:  # an older library without requisitions yet
            return 0

    def reload_queue(self) -> None:
        """Update the Requisitions row's count."""
        for r in range(self.rowCount()):
            index = self.index(r, 0)
            if index.data(KIND) == "queue":
                self.itemFromIndex(index).setData(self._active_requisitions(), COUNT)

    def _collection_rows(self) -> list[QStandardItem]:
        rows = []
        for c in self.service.collections():
            item = _item(c["name"], "collection", count=c["count"], detail="smart" if c["smart"] else "")
            item.setData(c["uid"], COLLECTION_UID)
            item.setData(c["smart"], SMART)
            if c["smart"]:
                item.setToolTip(f"Smart collection: {c['query']}")
            rows.append(item)
        rows.append(_item("New collection…", "new_collection"))
        return rows

    def reload_collections(self) -> None:
        """Rebuild only the collection rows (cheap; the full sidebar counts every environment)."""
        rows = [(self.index(r, 0).data(KIND), self.index(r, 0).data()) for r in range(self.rowCount())]
        start = rows.index(("section", "COLLECTIONS")) + 1
        end = next(r for r in range(start, len(rows)) if rows[r][0] == "section")  # the ENVIRONMENTS header
        self.removeRows(start, end - start)
        for offset, row in enumerate(self._collection_rows()):
            self.insertRow(start + offset, row)


def _item(text: str, kind: str, *, count: int | None = None, env_id: int | None = None,
          container_id: int | None = None, type_id: str | None = None, detail: str = "") -> QStandardItem:
    item = QStandardItem(text)
    item.setEditable(False)
    item.setData(kind, KIND)
    item.setData(env_id, ENV_ID)
    item.setData(container_id, CONTAINER_ID)
    item.setData(type_id, TYPE_ID)
    item.setData(count, COUNT)
    item.setData(detail, DETAIL)
    if kind == "section":
        item.setSelectable(False)
    return item


def filter_for(index: QModelIndex, current: Filter) -> Filter:
    """The browser filter a sidebar selection stands for (search text and grouping kept)."""
    kind = index.data(KIND)
    flt = Filter(query=current.query, group=current.group)
    if kind in ("environment", "group", "container", "type"):
        flt.environment_id = index.data(ENV_ID)
    if kind == "container":
        flt.container_id = index.data(CONTAINER_ID)
    if kind == "type":
        flt.type_id = index.data(TYPE_ID)
    if kind == "collection":
        flt.collection_uid, flt.collection_name = index.data(COLLECTION_UID), index.data()
    return flt


# Browser ------------------------------------------------------------------------------------------


class _ThumbnailSignals(QObject):
    loaded = Signal(str, QImage)


class _ThumbnailJob(QRunnable):
    def __init__(self, path: str, size: int, signals: _ThumbnailSignals) -> None:
        super().__init__()
        self.path, self.size, self.signals = path, size, signals

    def run(self) -> None:
        image = QImage(self.path)
        if not image.isNull():
            image = image.scaled(self.size, self.size, Qt.AspectRatioMode.KeepAspectRatio,
                                 Qt.TransformationMode.SmoothTransformation)
        self.signals.loaded.emit(self.path, image)


class BrowserModel(QAbstractListModel):
    """Bricks for the current filter, fetched a page at a time as the view scrolls."""

    PAGE = 200
    THUMB_SIZE = 256
    error = Signal(str)
    totalChanged = Signal(int)

    def __init__(self, service: LibraryService, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.service = service
        self.filter = Filter()
        self.bricks: list[Brick] = []
        self.total = 0
        self._images: dict[str, QImage] = {}
        self._pending: set[str] = set()
        self._rows_by_path: dict[str, list[QPersistentModelIndex]] = {}
        self._signals = _ThumbnailSignals()
        self._signals.loaded.connect(self._on_thumbnail)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(4)

    def set_filter(self, flt: Filter) -> None:
        self.filter = flt
        self.reload()

    def reload(self) -> None:
        self.beginResetModel()
        self.bricks, self.total = [], 0
        try:
            page = self.service.page(self.filter, 0, self.PAGE)
        except Exception as exc:  # a bad query, shown to the user instead of crashing
            self.endResetModel()
            self.totalChanged.emit(0)
            self.error.emit(str(exc))
            return
        self.bricks, self.total = list(page.items), page.total
        self._images = {k: v for k, v in self._images.items() if v is not None}
        self.endResetModel()
        self.totalChanged.emit(self.total)
        self.error.emit("")

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.bricks)

    def canFetchMore(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> bool:
        return not parent.isValid() and len(self.bricks) < self.total

    def fetchMore(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> None:
        page = self.service.page(self.filter, len(self.bricks), self.PAGE)
        if not page.items:
            self.total = len(self.bricks)
            return
        start = len(self.bricks)
        self.beginInsertRows(QModelIndex(), start, start + len(page.items) - 1)
        self.bricks.extend(page.items)
        self.endInsertRows()

    def data(self, index: QModelIndex | QPersistentModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self.bricks):
            return None
        brick = self.bricks[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return brick.name
        if role == BRICK:
            return brick
        if role == Qt.ItemDataRole.ToolTipRole:
            return f"{brick.name}\n{brick.type_name} · {meta_line(brick)}"
        if role == THUMBNAIL:
            return self._thumbnail(brick.thumbnail, index)
        return None

    def _thumbnail(self, path: str | None, index: QModelIndex) -> QImage | None:
        if not path:
            return None
        if path in self._images:
            return self._images[path]
        self._rows_by_path.setdefault(path, []).append(QPersistentModelIndex(index))
        if path not in self._pending and Path(path).is_file():
            self._pending.add(path)
            self.pool.start(_ThumbnailJob(path, self.THUMB_SIZE, self._signals))
        return None

    def _on_thumbnail(self, path: str, image: QImage) -> None:
        self._pending.discard(path)
        self._images[path] = None if image.isNull() else image
        for idx in self._rows_by_path.pop(path, []):
            if idx.isValid():
                self.dataChanged.emit(QModelIndex(idx), QModelIndex(idx), [THUMBNAIL])

    def brick(self, row: int) -> Brick | None:
        return self.bricks[row] if 0 <= row < len(self.bricks) else None

    def flags(self, index: QModelIndex | QPersistentModelIndex) -> Qt.ItemFlag:
        flags = super().flags(index)
        if index.isValid():
            flags |= Qt.ItemFlag.ItemIsDragEnabled | Qt.ItemFlag.ItemIsDropEnabled
        return flags

    def mimeTypes(self) -> list[str]:
        return [DOSSIER_MIME, "text/uri-list"]

    def mimeData(self, indexes) -> QMimeData:
        data = QMimeData()
        uids = [self.bricks[i.row()].uid for i in indexes if i.isValid() and i.row() < len(self.bricks)]
        data.setData(DOSSIER_MIME, "\n".join(dict.fromkeys(uids)).encode())
        return data

    def supportedDragActions(self) -> Qt.DropAction:
        return Qt.DropAction.CopyAction | Qt.DropAction.LinkAction

    def row_of(self, uid: str) -> int | None:
        return next((r for r, b in enumerate(self.bricks) if b.uid == uid), None)


def dropped_uids(mime: QMimeData) -> list[str]:
    if not mime.hasFormat(DOSSIER_MIME):
        return []
    return [u for u in bytes(mime.data(DOSSIER_MIME)).decode().split("\n") if u]


def meta_line(brick: Brick) -> str:
    parts = []
    if brick.children:
        parts.append(f"{brick.children} item{'s' * (brick.children != 1)}")
    if brick.entries:
        parts.append(f"{brick.entries} entr{'ies' if brick.entries != 1 else 'y'}")
    if brick.environments:
        parts.append(", ".join(brick.environments))
    return " · ".join(parts)
