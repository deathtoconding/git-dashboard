"""Logging behaviour: repository context, one-line records, tolerant setup."""

from __future__ import annotations

import logging

import pytest

from app.logging_config import _RepoFilter, _RepoFormatter, configure_logging, get_logger, get_repo_logger


def _formatter() -> _RepoFormatter:
    return _RepoFormatter("%(levelname)s %(repo_field)s%(message)s")


def _record(message: str, **extra: object) -> logging.LogRecord:
    record = logging.LogRecord("app.test", logging.INFO, __file__, 1, message, None, None)
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_records_without_a_repository_have_no_prefix() -> None:
    record = _record("plain message")
    assert _RepoFilter().filter(record) is True
    assert _formatter().format(record) == "INFO plain message"


def test_repo_logger_stamps_the_repository_name() -> None:
    record = _record("scan finished")
    record.repo = "atlas-api"
    assert _formatter().format(record) == "INFO [repo=atlas-api] scan finished"


def test_repo_logger_accepts_strings_rows_and_objects() -> None:
    class Repo:
        name = "object-repo"

    assert get_repo_logger("test", "string-repo").extra["repo"] == "string-repo"
    assert get_repo_logger("test", {"name": "row-repo", "path": "/tmp/row"}).extra["repo"] == "row-repo"
    assert get_repo_logger("test", {"path": "/tmp/only-path"}).extra["repo"] == "/tmp/only-path"
    assert get_repo_logger("test", Repo()).extra["repo"] == "object-repo"


def test_repository_rows_never_leak_into_log_lines(capsys: pytest.CaptureFixture[str]) -> None:
    """A full repository row used to be dumped into the message via str(dict)."""
    configure_logging("INFO", force=True)
    row = {"id": 7, "name": "nebula-web", "path": "/repos/nebula-web", "state": "clean", "total_commits": 42}
    get_repo_logger("test", row).info("scan finished")
    captured = capsys.readouterr().err
    assert "[repo=nebula-web]" in captured
    assert "total_commits" not in captured


def test_configure_logging_is_idempotent_and_tolerates_bad_levels() -> None:
    configure_logging("INFO", force=True)
    handlers = list(logging.getLogger().handlers)
    configure_logging("DEBUG")  # second call must not add handlers
    assert list(logging.getLogger().handlers) == handlers
    configure_logging("not-a-level", force=True)
    assert logging.getLogger().level == logging.INFO
    configure_logging("INFO", force=True)


def test_get_logger_namespaces_modules() -> None:
    assert get_logger("collectors.git_runner").name == "app.collectors.git_runner"
    assert get_logger("app.already.namespaced").name == "app.already.namespaced"
