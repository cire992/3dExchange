"""Git for project homes: the repository at creation, and checkpoints.

A checkpoint commits every change in the project home (``.exchange/`` excepted), so a bypassed
agent session can be undone with git. It never makes an empty commit, and refuses a home that is
not its own repository's top level, so a checkpoint never commits another repository's files.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from exchange.errors import ExchangeError

PATHSPEC = (".", ":(exclude).exchange")


class GitError(ExchangeError):
    """Git is missing, or refused (not a repository, no identity configured, ...)."""


def _git(home: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    exe = shutil.which("git")
    if exe is None:
        raise GitError("git is not installed or not on PATH")
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C"}
    result = subprocess.run([exe, "-c", "core.quotepath=false", *args], cwd=home, env=env,
                            capture_output=True, text=True, encoding="utf-8", errors="replace",
                            stdin=subprocess.DEVNULL)
    if check and result.returncode != 0:
        message = (result.stderr or result.stdout).strip().splitlines()
        raise GitError(f"git {args[0]} failed in {home}: {' / '.join(message[-3:]) or f'exit code {result.returncode}'}")
    return result


def _configured(home: Path, key: str) -> str:
    return _git(home, "config", "--get", key, check=False).stdout.strip()


def _identity(home: Path) -> list[str]:
    """``-c`` options giving git the identity in ``projects.toml`` when it has none of its own."""
    from exchange.projects.home import read_config

    config = read_config()
    options = []
    for key, setting in (("user.name", "git_name"), ("user.email", "git_email")):
        if not _configured(home, key) and config.get(setting):
            options += ["-c", f"{key}={config[setting]}"]
    return options


def init(home: Path) -> None:
    """Create the repository, giving it the identity in ``projects.toml`` if git has none."""
    if not (home / ".git").exists():
        _git(home, "init", "-q")
    options = _identity(home)
    for key_value in options[1::2]:
        key, _, value = key_value.partition("=")
        _git(home, "config", key, value)


def _same(a: Path, b: Path) -> bool:
    return os.path.normcase(str(a.resolve())) == os.path.normcase(str(b.resolve()))


def check_repository(home: Path) -> None:
    result = _git(home, "rev-parse", "--show-toplevel", check=False)
    if result.returncode != 0:
        raise GitError(f"{home} is not a git repository. Run 'git init' there (exchange project init "
                       "sets one up), then try again.")
    top = Path(result.stdout.strip())
    if not _same(top, home):
        raise GitError(f"{home} is inside the git repository {top}, not its own; a checkpoint would "
                       "commit that repository's files. Give the project home its own repository.")


def head(home: Path) -> str | None:
    result = _git(home, "rev-parse", "--verify", "-q", "HEAD", check=False)
    return result.stdout.strip() or None


def changes(home: Path) -> list[str]:
    result = _git(home, "status", "--porcelain=v1", "--untracked-files=all", "--", *PATHSPEC)
    return [line for line in result.stdout.splitlines() if line.strip()]


def commit_all(home: Path, message: str) -> str | None:
    """Commit every change; the new commit, or None when nothing changed."""
    if not changes(home):
        return None
    # Naming an ignored folder in a pathspec makes `git add` fail, so exclude .exchange/ only when
    # the home's .gitignore does not already.
    ignored = _git(home, "check-ignore", "-q", ".exchange", check=False).returncode == 0
    _git(home, "add", "-A", "--", *(PATHSPEC[:1] if ignored else PATHSPEC))
    try:
        _git(home, *_identity(home), "commit", "-q", "-m", message)
    except GitError as exc:
        if "Please tell me who you are" in str(exc) or "auto-detect" in str(exc):
            raise GitError(f"git has no identity to commit with in {home}. Set the one project homes use: "
                           "exchange project config --git-name NAME --git-email EMAIL") from exc
        raise
    return head(home)


@dataclass
class Checkpoint:
    home: Path
    committed: bool
    commit: str | None  # the checkpoint's commit, or HEAD when there was nothing to commit
    changed: int


def checkpoint(home: Path, reason: str) -> Checkpoint:
    check_repository(home)
    pending = len(changes(home))
    message = f"Checkpoint: {reason.strip() or 'requested'}"
    made = commit_all(home, message)
    return Checkpoint(home, made is not None, made or head(home), pending)
