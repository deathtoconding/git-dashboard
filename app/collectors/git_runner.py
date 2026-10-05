"""Safe Git CLI execution (Epic E3-S1).

The Git CLI is the source of truth for this dashboard.  This module wraps
``subprocess`` so that:

* a missing Git installation is detected once and reported cleanly,
* every command has a timeout and cannot hang the application,
* non-zero exit codes are returned as data (never raised),
* no Git command can ever start an interactive prompt or use a pager.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from ..logging_config import get_logger

log = get_logger("collectors.git_runner")

# Field/record separators used when parsing Git output (see app/collectors/parsers.py)
FIELD_SEP = "\x1f"
RECORD_SEP = "\x01"


class GitError(RuntimeError):
    """Base class for Git related failures."""


class GitNotFoundError(GitError):
    """Raised when the configured Git binary cannot be executed."""


@dataclass(slots=True)
class GitResult:
    """Outcome of a single Git command."""

    args: tuple[str, ...]
    code: int
    stdout: str = ""
    stderr: str = ""
    duration_ms: int = 0
    timed_out: bool = False
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.code == 0 and self.error is None and not self.timed_out

    def lines(self) -> list[str]:
        return [line for line in self.stdout.splitlines() if line.strip()]

    def first_line(self) -> str:
        lines = self.lines()
        return lines[0] if lines else ""

    def failure_reason(self) -> str:
        if self.timed_out:
            return f"git {' '.join(self.args)} timed out"
        if self.error:
            return self.error
        from .parsers import clean_git_error

        detail = clean_git_error(self.stderr) or clean_git_error(self.stdout)
        if not detail:
            detail = f"exit code {self.code}"
        return detail[:400]

    def __str__(self) -> str:  # pragma: no cover - debugging helper
        return f"<GitResult {' '.join(self.args)} code={self.code} ok={self.ok}>"


class GitRunner:
    """Executes Git commands safely."""

    def __init__(
        self,
        binary: str = "git",
        *,
        timeout: int = 30,
        env: dict[str, str] | None = None,
        max_output_bytes: int = 64 * 1024 * 1024,
    ) -> None:
        self.binary = binary or "git"
        self.timeout = max(1, int(timeout))
        self.max_output_bytes = max_output_bytes
        self._version: str | None = None
        self._available: bool | None = None
        self._env_overrides = env or {}

    # ------------------------------------------------------------------ helpers
    def resolve_binary(self) -> str | None:
        """Return the executable path for the configured Git binary, if any."""
        candidate = Path(self.binary)
        if candidate.is_absolute() or os.sep in self.binary:
            return str(candidate) if candidate.exists() else None
        return shutil.which(self.binary)

    def environment(self) -> dict[str, str]:
        env = dict(os.environ)
        env.update(
            {
                # Never block on credentials or open a pager / editor.
                "GIT_TERMINAL_PROMPT": "0",
                "GIT_ASKPASS": "echo",
                "GIT_PAGER": "cat",
                "GIT_EDITOR": "true",
                # Read-only usage: avoid touching index/lock files of the scanned repo.
                "GIT_OPTIONAL_LOCKS": "0",
                # Stable, parseable output.
                "LC_ALL": "C.UTF-8",
                "LANG": "C.UTF-8",
            }
        )
        env.update(self._env_overrides)
        return env

    def is_available(self) -> bool:
        if self._available is None:
            resolved = self.resolve_binary()
            if not resolved:
                log.error("git binary %r not found on PATH", self.binary)
                self._available = False
                return False
            result = self.run(["--version"], use_resolved=True)
            if result.ok:
                self._version = result.first_line().replace("git version ", "").strip()
                log.info("git %s detected at %s", self._version, resolved)
                self._available = True
            else:
                log.error("git binary %r is not usable: %s", self.binary, result.failure_reason())
                self._available = False
        return bool(self._available)

    @property
    def version(self) -> str | None:
        if self._version is None and self.is_available():
            pass
        return self._version

    def require_available(self) -> None:
        if not self.is_available():
            raise GitNotFoundError(
                f"Git executable {self.binary!r} was not found or is not executable. "
                "Install Git (https://git-scm.com) or set 'git_binary' in config.json."
            )

    # -------------------------------------------------------------------- run
    def run(
        self,
        args: Sequence[str],
        *,
        cwd: str | Path | None = None,
        timeout: int | None = None,
        check: bool = False,
        use_resolved: bool = False,
    ) -> GitResult:
        """Run ``git <args>`` and capture stdout/stderr/exit code.

        Never raises for a failing Git command: use :meth:`run_or_raise` if the
        caller wants an exception.  A missing binary raises :class:`GitNotFoundError`.
        """
        command: list[str]
        if use_resolved:
            resolved = self.resolve_binary()
            if not resolved:
                raise GitNotFoundError(f"Git executable {self.binary!r} was not found on PATH")
            command = [resolved, *args]
        else:
            if not self.is_available():
                raise GitNotFoundError(f"Git executable {self.binary!r} is not available")
            command = [self.binary, *args]

        working_dir = str(cwd) if cwd is not None else None
        started = time.perf_counter()
        try:
            completed = subprocess.run(  # noqa: S603 - args are controlled by this application
                command,
                cwd=working_dir,
                env=self.environment(),
                stdin=subprocess.DEVNULL,
                capture_output=True,
                timeout=timeout or self.timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            duration = int((time.perf_counter() - started) * 1000)
            log.warning("git %s timed out after %ss in %s", " ".join(args), timeout or self.timeout, working_dir)
            result = GitResult(
                args=tuple(args),
                code=-1,
                stdout=_decode(exc.stdout),
                stderr=_decode(exc.stderr),
                duration_ms=duration,
                timed_out=True,
            )
            if check:
                raise GitError(result.failure_reason()) from exc
            return result
        except FileNotFoundError as exc:
            raise GitNotFoundError(f"Git executable {self.binary!r} was not found: {exc}") from exc
        except OSError as exc:
            duration = int((time.perf_counter() - started) * 1000)
            log.error("git %s failed to start in %s: %s", " ".join(args), working_dir, exc)
            result = GitResult(args=tuple(args), code=-1, duration_ms=duration, error=str(exc))
            if check:
                raise GitError(result.failure_reason()) from exc
            return result

        duration = int((time.perf_counter() - started) * 1000)
        stdout = _decode(completed.stdout, self.max_output_bytes)
        stderr = _decode(completed.stderr)
        result = GitResult(
            args=tuple(args),
            code=completed.returncode,
            stdout=stdout,
            stderr=stderr,
            duration_ms=duration,
        )
        if completed.returncode != 0:
            log.debug("git %s exited with %s: %s", " ".join(args), completed.returncode, result.failure_reason())
            if check:
                raise GitError(result.failure_reason())
        return result

    def run_or_raise(self, args: Sequence[str], **kwargs) -> str:
        """Run a command and return stdout, raising :class:`GitError` on failure."""
        result = self.run(args, **kwargs)
        if not result.ok:
            raise GitError(result.failure_reason())
        return result.stdout


_SEPARATOR_RE = re.compile(r"[\r\n]")


def _decode(raw: bytes | None, limit: int = 0) -> str:
    if not raw:
        return ""
    if limit and len(raw) > limit:
        raw = raw[:limit]
    return raw.decode("utf-8", errors="replace")


def split_records(text: str, separator: str = RECORD_SEP) -> list[str]:
    """Split Git output into per-record chunks (used by the parsers)."""
    return [chunk for chunk in text.split(separator) if chunk.strip()]
