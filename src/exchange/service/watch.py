"""Change notices for the service (Roadmap phase 6g): which environments' roots changed since they
were last scanned, so the Workspace can say "changes detected" instead of rescanning silently (the
user decides when to rescan). The PySide6 window's ``ChangeWatcher`` without Qt.

Uses ``watchdog`` (the OS's own change notifications: one recursive watch per root on Windows,
however many files it holds). Watching only reads; nothing is written to the roots. Without
``watchdog`` installed the watcher is simply off (``available`` is false).
"""

from __future__ import annotations

import threading
from pathlib import Path

try:
    from watchdog.events import FileSystemEvent, FileSystemEventHandler
    from watchdog.observers import Observer
except ImportError:  # the service works without it; no change notices then
    Observer = None
    FileSystemEventHandler = object
    FileSystemEvent = object


class _Handler(FileSystemEventHandler):
    def __init__(self, watcher: Watcher, environment_id: int) -> None:
        super().__init__()
        self.watcher, self.environment_id = watcher, environment_id

    def on_any_event(self, event: FileSystemEvent) -> None:
        if event.event_type in ("opened", "closed", "closed_no_write"):
            return  # reads (including a scan's own) are not changes
        if event.is_directory and event.event_type == "modified":
            return  # a folder's timestamp; the file events inside say what changed
        self.watcher._notice(self.environment_id)


class Watcher:
    """The environments whose roots changed; ``version`` grows with every change of that set, so a
    client can wait for the next one (``wait``)."""

    def __init__(self) -> None:
        self.available = Observer is not None
        self.version = 0
        self._observer = None
        self._watched: dict[str, int] = {}  # root path -> environment id
        self._noticed: set[int] = set()
        self._changed = threading.Condition()  # the observer thread notices; requests read and clear

    def watch(self, roots: list[tuple[str, int]]) -> None:
        """Watch these (root path, environment id) pairs, replacing what was watched before."""
        wanted = {str(Path(p)): env for p, env in roots if Path(p).is_dir()}
        if not self.available or wanted == self._watched:
            return
        self._stop_observer()
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

    def state(self) -> dict:
        with self._changed:
            return {"available": self.available, "environments": sorted(self._noticed), "version": self.version}

    def wait(self, since: int | None, timeout: float) -> dict:
        """The changed environments, once ``version`` is past ``since`` (or after ``timeout``)."""
        with self._changed:
            if since is not None:
                self._changed.wait_for(lambda: self.version != since, timeout)
        return self.state()

    def clear(self, environment_ids: set[int] | None = None) -> None:
        """Forget changes seen so far (after a rescan), for some environments or all."""
        with self._changed:
            before = set(self._noticed)
            self._noticed = set() if environment_ids is None else self._noticed - environment_ids
            if self._noticed != before:
                self.version += 1
                self._changed.notify_all()

    def stop(self) -> None:
        self._stop_observer()
        self._watched = {}

    def _stop_observer(self) -> None:
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=5)
            self._observer = None

    def _notice(self, environment_id: int) -> None:  # on the observer's thread
        with self._changed:
            if environment_id not in self._noticed:
                self._noticed.add(environment_id)
                self.version += 1
                self._changed.notify_all()
