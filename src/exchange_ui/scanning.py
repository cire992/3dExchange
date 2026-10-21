"""Run scans in a separate process (``python -m exchange ... --progress-json``) so the window
never freezes, and turn its JSON lines into Qt signals."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, Signal


class ScanRunner(QObject):
    progress = Signal(dict)  # {"phase", "environment", "step", "done", "total"}
    finished = Signal(dict, str)  # (report data or {}, error message or "")
    runningChanged = Signal(bool)

    def __init__(self, db_path: Path, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.db_path = Path(db_path)
        self.process: QProcess | None = None
        self._buffer = b""
        self._result: dict = {}
        self._stopped = False

    @property
    def running(self) -> bool:
        return self.process is not None

    def scan(self, folder: Path) -> None:
        self._start(["scan", str(folder)])

    def rescan(self) -> None:
        self._start(["rescan"])

    def _start(self, args: list[str]) -> None:
        if self.running:
            return
        self._buffer, self._result, self._stopped = b"", {}, False
        process = QProcess(self)
        process.setProgram(sys.executable)
        process.setArguments(["-m", "exchange", *args, "--db", str(self.db_path), "--progress-json"])
        process.readyReadStandardOutput.connect(self._read)
        process.finished.connect(self._done)
        self.process = process
        process.start()
        self.runningChanged.emit(True)

    def stop(self) -> None:
        """Stop the scan. Finished work is saved: the scanner commits as it goes."""
        if self.process is not None:
            self._stopped = True
            self.process.kill()

    def _read(self) -> None:
        self._feed(bytes(self.process.readAllStandardOutput()))

    def _feed(self, data: bytes) -> None:
        self._buffer += data
        *lines, self._buffer = self._buffer.split(b"\n")
        for line in lines:
            try:
                event = json.loads(line.decode("utf-8", errors="replace"))
            except json.JSONDecodeError:
                continue
            if event.get("event") == "progress":
                self.progress.emit(event)
            elif event.get("event") == "result":
                self._result = event.get("data") or {}

    def _done(self, code: int, _status) -> None:
        process, self.process = self.process, None
        self._feed(bytes(process.readAllStandardOutput()) + b"\n")
        error = ""
        if self._stopped:
            error = "Scan stopped; everything finished before that is saved."
        elif code != 0:
            stderr = bytes(process.readAllStandardError()).decode("utf-8", errors="replace").strip()
            error = stderr or f"scan failed (exit code {code})"
            error = error.removeprefix("exchange: error: ")
        process.deleteLater()
        self.runningChanged.emit(False)
        self.finished.emit(self._result, error)
