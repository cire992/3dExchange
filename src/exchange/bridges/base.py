"""What every bridge shares: running the app with a timeout, logging it, one job per app."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

from exchange.errors import ExchangeError
from exchange.locks import Lock, LockBusy

LOCK_WAIT = 1.0  # seconds between tries while another job holds the app
LOG_TAIL = 15  # lines of the app's log quoted in an error


def _stop(process: subprocess.Popen) -> None:
    """End an app and anything it started (on Windows, killing only the first process can leave
    its children running)."""
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(process.pid)], capture_output=True)
    if process.poll() is None:
        process.kill()
    process.wait()


class BridgeError(ExchangeError):
    """The app could not do the job: not found, failed, timed out, or the script reported an error."""


class Bridge:
    exit_grace = 2.0  # seconds an app that wrote its result gets to exit by itself before it is closed

    def __init__(self, app: str, executable: Path, workdir: Path, log: Callable[[str], None]) -> None:
        self.app, self.executable, self.workdir, self._log = app, Path(executable), Path(workdir), log
        if not self.executable.is_file():
            raise BridgeError(f"{app} not found at {self.executable}")

    # Running ------------------------------------------------------------------------------------

    def _run_process(self, command: list[str], *, timeout: float, log_name: str, cwd: Path | None = None,
                     done: Callable[[], bool] | None = None) -> int:
        """Run ``command``, its output going to a log in the work folder; returns its exit code.

        ``done`` lets an app that may not exit by itself (Daz Studio) be closed once its result
        is written."""
        self.workdir.mkdir(parents=True, exist_ok=True)
        log_path = self.workdir / log_name
        lock = Lock(f"app-{self.app}")
        waited = 0.0
        while True:
            try:
                lock.acquire()
                break
            except LockBusy:
                if waited == 0:
                    self._log(f"waiting for another {self.app} job to finish")
                if waited >= timeout:
                    raise BridgeError(f"{self.app} stayed busy with another job for {timeout:.0f} s") from None
                time.sleep(LOCK_WAIT)
                waited += LOCK_WAIT
        try:
            self._log(f"running {self.app}")
            started = time.monotonic()
            with log_path.open("w", encoding="utf-8", errors="replace") as out:
                process = subprocess.Popen(command, stdout=out, stderr=subprocess.STDOUT, cwd=cwd,
                                           stdin=subprocess.DEVNULL)
                while True:
                    try:
                        code = process.wait(timeout=0.5)
                        break
                    except subprocess.TimeoutExpired:
                        elapsed = time.monotonic() - started
                        if done is not None and done():
                            try:  # let it finish exiting by itself
                                process.wait(timeout=self.exit_grace)
                            except subprocess.TimeoutExpired:
                                pass
                            if process.poll() is None:
                                self._log(f"{self.app} wrote its result; closing it")
                                _stop(process)
                            code = process.wait()
                            break
                        if elapsed > timeout:
                            _stop(process)
                            raise BridgeError(f"{self.app} did not finish within {timeout:.0f} s"
                                              + self._tail(log_path))
            self._log(f"{self.app} finished in {time.monotonic() - started:.1f} s (exit code {code})")
            return code
        finally:
            lock.release()

    @staticmethod
    def _tail(log_path: Path) -> str:
        try:
            lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return ""
        tail = [line for line in lines if line.strip()][-LOG_TAIL:]
        return ("\n" + "\n".join(tail)) if tail else ""

    def _job_files(self, args: dict) -> tuple[Path, Path]:
        """Write the arguments; returns (arguments file, result file)."""
        self.workdir.mkdir(parents=True, exist_ok=True)
        args_path, result_path = self.workdir / "bridge-args.json", self.workdir / "bridge-result.json"
        result_path.unlink(missing_ok=True)
        args_path.write_text(json.dumps({"args": args, "result": str(result_path), "workdir": str(self.workdir)},
                                        ensure_ascii=False, indent=2), encoding="utf-8")
        return args_path, result_path

    def _read_result(self, result_path: Path, log_name: str, code: int) -> dict:
        if not result_path.is_file():
            raise BridgeError(f"{self.app} wrote no result (exit code {code})" + self._tail(self.workdir / log_name))
        try:
            data = json.loads(result_path.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise BridgeError(f"{self.app} wrote an unreadable result: {exc}") from exc
        if not data.get("ok"):
            raise BridgeError(f"the {self.app} script failed: {data.get('error', 'no reason given')}"
                              + self._tail(self.workdir / log_name))
        return data.get("result") or {}


class CommandBridge(Bridge):
    """A command-line tool: ``run_command(["-f", "BC7", path])`` returns its output."""

    def run_command(self, args: list[str], *, timeout: float = 600, cwd: Path | None = None) -> str:
        log_name = f"{self.app}.log"
        code = self._run_process([str(self.executable), *map(str, args)], timeout=timeout, log_name=log_name, cwd=cwd)
        output = (self.workdir / log_name).read_text(encoding="utf-8", errors="replace")
        if code != 0:
            raise BridgeError(f"{self.app} failed (exit code {code})" + self._tail(self.workdir / log_name))
        return output
