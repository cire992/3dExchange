"""Watch environment roots for changes, so the window can say "changes detected" instead of
rescanning silently (the user decides when to rescan).

Uses ``watchdog`` (the OS's own change notifications: one recursive watch per root on Windows,
however many files it holds). Watching only reads; nothing is written to the roots. Without
``watchdog`` installed the watcher is simply off.
"""

from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QObject, Signal

try:
    from watchdog.events import FileSystemEvent, FileSystemEventHandler
    from watchdog.observers import Observer
except ImportError:  # the app works without it; no change detection then
    Observer = None
    FileSystemEventHandler = object
    FileSystemEvent = object


class _Handler(FileSystemEventHandler):
    def __init__(self, watcher: ChangeWatcher, environment_id: int) -> None:
        super().__init__()
        self.watcher, self.environment_id = watcher, environment_id

    def on_any_event(self, event: FileSystemEvent) -> None:
        if event.event_type in ("opened", "closed", "closed_no_write"):
            return  # reads (including a scan's own) are not changes
        if event.is_directory and event.event_type == "modified":
            return  # a folder's timestamp; the file events inside say what changed
        self.watcher._notice(self.environment_id)


class ChangeWatcher(QObject):
    """Emits ``changed(environment id)`` the first time a watched root changes; ``clear()`` re-arms."""

    changed = Signal(int)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.available = Observer is not None
        self._observer = None
        self._watched: dict[str, int] = {}  # root path -> environment id
        self._noticed: set[int] = set()
        self._lock = threading.Lock()  # the observer thread notices, the window clears

    @property
    def changed_environments(self) -> set[int]:
        with self._lock:
            return set(self._noticed)

    def watch(self, roots: list[tuple[str, int]]) -> None:
        """Watch these (root path, environment id) pairs, replacing what was watched before."""
        wanted = {str(Path(p)): env for p, env in roots if Path(p).is_dir()}
        if not self.available or wanted == self._watched:
            return
        self.stop()
        self._watched = wanted
        if not wanted:
            return
        observer = Observer()
        for path, env in wanted.items():
            try:
                observer.schedule(_Handler(self, env), path, recursive=True)
            except OSError:
                continue  # unreadable or vanished: nothing to watch there
        observer.daemon = True
        observer.start()
        self._observer = observer

    def clear(self, environment_ids: set[int] | None = None) -> None:
        """Forget changes seen so far (after a rescan), for some environments or all."""
        with self._lock:
            self._noticed = set() if environment_ids is None else self._noticed - environment_ids

    def stop(self) -> None:
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=5)
            self._observer = None
        self._watched = {}

    def _notice(self, environment_id: int) -> None:
        # Called on the observer's thread; the signal is queued to the window's thread.
        with self._lock:
            new = environment_id not in self._noticed
            self._noticed.add(environment_id)
        if new:
            self.changed.emit(environment_id)
