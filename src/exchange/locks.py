"""Cross-process locks in the data folder: one queue worker at a time, and (with bridges) one job
per heavy external app (one Daz Studio, one Blender).

A lock is a file holding its owner's process id; a lock whose owner is gone is taken over.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from exchange.errors import ExchangeError
from exchange.paths import data_dir


class LockBusy(ExchangeError):
    pass


def _alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
            return code.value == 259  # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)  # (on POSIX, signal 0 only checks)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class Lock:
    def __init__(self, name: str, folder: Path | None = None) -> None:
        self.path = (folder or data_dir() / "locks") / f"{name}.lock"
        self.held = False

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(2):
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                try:
                    owner = int(self.path.read_text().strip() or 0)
                except (OSError, ValueError):
                    owner = 0
                if owner == os.getpid() or _alive(owner):
                    raise LockBusy(f"{self.path.stem} is in use by process {owner}") from None
                self.path.unlink(missing_ok=True)  # its owner is gone
                continue
            with os.fdopen(fd, "w") as f:
                f.write(str(os.getpid()))
            self.held = True
            return
        raise LockBusy(f"could not take the {self.path.stem} lock")

    def release(self) -> None:
        if self.held:
            self.path.unlink(missing_ok=True)
            self.held = False

    def __enter__(self) -> Lock:
        self.acquire()
        return self

    def __exit__(self, *_exc) -> None:
        self.release()
