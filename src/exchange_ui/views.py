"""The browser grid and sidebar tree, with drag and drop.

Bricks are dragged as dossier uids. Dropping them on a brick asks what to do (put into a
product, link their files, merge); dropping files from Explorer on a brick links those files;
dropping bricks on a manual collection in the sidebar adds them to it.
"""

from __future__ import annotations

from PySide6.QtCore import QModelIndex, Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent
from PySide6.QtWidgets import QAbstractItemView, QListView, QTreeView

from exchange_ui.models import BRICK, COLLECTION_UID, DOSSIER_MIME, KIND, SMART, dropped_uids


class BrickGrid(QListView):
    # target brick, dragged dossier uids, dropped file paths
    dropped = Signal(QModelIndex, list, list)

    def __init__(self) -> None:
        super().__init__()
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.LinkAction)

    def _wanted(self, event: QDragMoveEvent | QDropEvent) -> QModelIndex | None:
        mime = event.mimeData()
        if not (mime.hasFormat(DOSSIER_MIME) or mime.hasUrls()):
            return None
        index = self.indexAt(event.position().toPoint())
        if not index.isValid():
            return None
        if index.data(BRICK).uid in dropped_uids(mime):  # onto itself
            return None
        return index

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        mime = event.mimeData()
        if mime.hasFormat(DOSSIER_MIME) or mime.hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if self._wanted(event) is not None:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        index = self._wanted(event)
        if index is None:
            event.ignore()
            return
        mime = event.mimeData()
        paths = [u.toLocalFile() for u in mime.urls() if u.isLocalFile()] if not mime.hasFormat(DOSSIER_MIME) else []
        event.acceptProposedAction()
        self.dropped.emit(index, dropped_uids(mime), paths)


class SidebarTree(QTreeView):
    droppedOnCollection = Signal(str, list)  # collection uid, dossier uids

    def __init__(self) -> None:
        super().__init__()
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)

    def _collection(self, event: QDragMoveEvent | QDropEvent) -> str | None:
        if not event.mimeData().hasFormat(DOSSIER_MIME):
            return None
        index = self.indexAt(event.position().toPoint())
        if index.isValid() and index.data(KIND) == "collection" and not index.data(SMART):
            return index.data(COLLECTION_UID)
        return None

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasFormat(DOSSIER_MIME):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if self._collection(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        uid = self._collection(event)
        if uid is None:
            event.ignore()
            return
        event.acceptProposedAction()
        self.droppedOnCollection.emit(uid, dropped_uids(event.mimeData()))
