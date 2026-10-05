"""Logging configuration for the dashboard.

Every module uses :func:`get_logger`.  Repository specific work is logged through
:func:`get_repo_logger`, which injects a ``repo`` field so a failing repository can
be traced without crashing (or spamming) the rest of the application.
"""

from __future__ import annotations

import contextlib
import logging
import logging.handlers
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)-28s %(repo_field)s%(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


class _RepoFilter(logging.Filter):
    """Makes sure every record has a ``repo`` attribute used by the formatter."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003 - stdlib name
        if not hasattr(record, "repo"):
            record.repo = "-"
        return True


class _RepoFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:  # noqa: A003
        repo = getattr(record, "repo", "-")
        record.repo_field = "" if repo in ("-", "", None) else f"[repo={repo}] "
        return super().format(record)


_CONFIGURED = False


def configure_logging(level: str = "INFO", *, log_file: str | os.PathLike[str] | None = None, force: bool = False) -> None:
    """Configure the root logger.  Safe to call more than once."""
    global _CONFIGURED
    if _CONFIGURED and not force:
        logging.getLogger().setLevel(getattr(logging, level.upper(), logging.INFO))
        return

    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
        with contextlib.suppress(Exception):
            handler.close()

    formatter = _RepoFormatter(LOG_FORMAT, datefmt=DATE_FORMAT)
    stream = logging.StreamHandler(stream=sys.stderr)
    stream.setFormatter(formatter)
    stream.addFilter(_RepoFilter())
    root.addHandler(stream)

    if log_file:
        path = Path(log_file).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        rotating = logging.handlers.RotatingFileHandler(path, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
        rotating.setFormatter(formatter)
        rotating.addFilter(_RepoFilter())
        root.addHandler(rotating)

    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Uvicorn / httpx noise is reduced so dashboard logs stay readable.
    for noisy in ("uvicorn.access", "httpx", "httpcore", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    logging.getLogger("uvicorn.error").setLevel(logging.INFO)
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Return a namespaced logger (``app.collectors.git_runner`` etc.)."""
    if not name.startswith("app") and name not in {"__main__"}:
        name = f"app.{name}"
    return logging.getLogger(name)


def get_repo_logger(name: str, repo: Any) -> logging.LoggerAdapter:
    """Return a logger that stamps every record with a repository identifier."""
    if isinstance(repo, str):
        identifier = repo
    elif isinstance(repo, Mapping):
        # Repository rows are plain dicts; never dump the whole row into a log line.
        identifier = repo.get("name") or repo.get("path") or str(repo)
    else:
        identifier = getattr(repo, "name", None) or getattr(repo, "path", None) or str(repo)
    return logging.LoggerAdapter(get_logger(name), {"repo": identifier})
