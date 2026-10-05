"""Failure-mode tests (E11-S3): the application must never crash on bad input.

Simulated failures: invalid repository, missing Git, corrupted repository,
inaccessible directory, Git timeout, database failure and malformed Git output.
"""

from __future__ import annotations

import os
import sqlite3
import stat
from pathlib import Path

import pytest
from fastapi import Request

from app.collectors.git_runner import GitResult, GitRunner
from app.collectors.parsers import parse_branch_refs, parse_commit_log, parse_status_porcelain
from app.database.connection import Database, DatabaseError
from app.services.repository_service import RepositoryError
from app.services.scan_service import ScanOutcome, is_informational
from tests import helpers
from tests.conftest import requires_git


# ------------------------------------------------------------ invalid repository
def test_registering_an_invalid_repository_raises_a_clear_error(repositories, tmp_path: Path) -> None:
    with pytest.raises(RepositoryError, match="does not exist"):
        repositories.add(str(tmp_path / "not-here"))

    plain = tmp_path / "plain"
    plain.mkdir()
    with pytest.raises(RepositoryError, match="No Git repository"):
        repositories.add(str(plain))


def test_scanning_an_unregistered_repository_reports_failure(scanner) -> None:
    outcome = scanner.scan_repository(12345)
    assert outcome.status == "failed"
    assert "not registered" in (outcome.error or "")


@requires_git
def test_scanning_a_repository_that_disappeared(scanner, store, repo_factory, tmp_path: Path) -> None:
    import shutil

    repo = repo_factory("vanishing", commits=2)
    repository_id = store.upsert_repository({"name": "vanishing", "path": str(repo)})
    shutil.rmtree(repo)

    outcome = scanner.scan_repository(repository_id)
    assert outcome.status == "failed"
    assert "unavailable" in (outcome.error or "").lower()
    assert store.get_repository(repository_id)["state"] == "error"
    run = store.list_scan_runs(repository_id=repository_id)[0]
    assert run["status"] == "failed" and run["error"]


# ------------------------------------------------------------------- missing git
@requires_git
def test_missing_git_binary_is_reported_but_not_fatal(store, settings, repo_factory) -> None:
    broken_settings = settings.with_overrides({"git_binary": "/nonexistent/git-binary"})
    from app.services.scan_service import ScanService

    repo = repo_factory("no-git", commits=2)
    repository_id = store.upsert_repository({"name": "no-git", "path": str(repo)})

    service = ScanService(store, broken_settings)
    available, version = service.git_available()
    assert available is False and version is None

    report = service.scan_all(incremental=True)
    assert report.failed == 1
    assert "was not found" in (report.outcomes[0].error or "")

    single = service.scan_repository(repository_id)
    assert single.status == "failed"
    assert "Git" in (single.error or "")


def test_health_endpoint_reports_missing_git(client) -> None:
    """When Git disappears the dashboard keeps working and says so in /api/health."""
    from app.api import deps

    original = deps.get_services

    # NOTE: `Request` must be annotated with a module-level import; with
    # `from __future__ import annotations` FastAPI resolves annotations from the
    # module globals, and a function-local import would be unreadable there.
    def broken(request: Request):
        services = original(request)
        services.collector.runner._available = False
        services.collector.runner._version = None
        return services

    client.app.dependency_overrides[deps.get_services] = broken
    try:
        body = client.get("/api/health").json()
        assert body["git_available"] is False
        assert body["status"] == "degraded"
        assert any("not available" in warning for warning in body["warnings"])
        # The rest of the dashboard still answers.
        assert client.get("/api/repositories").status_code == 200
    finally:
        client.app.dependency_overrides.clear()


# --------------------------------------------------------- corrupted repository
@requires_git
def test_corrupted_repository_is_handled(scanner, store, tmp_path: Path) -> None:
    corrupt = tmp_path / "repos" / "corrupt"
    (corrupt / ".git").mkdir(parents=True)
    (corrupt / ".git" / "HEAD").write_text("this is not a valid repository\n")
    repository_id = store.upsert_repository({"name": "corrupt", "path": str(corrupt)})

    outcome = scanner.scan_repository(repository_id)
    assert outcome.status in {"completed", "partial"}  # discovered as a repo, but git fails
    assert store.get_repository(repository_id)["state"] in {"unknown", "error", "empty"}
    # Whatever happens, a scan run row exists and the app is still alive.
    assert store.list_scan_runs(repository_id=repository_id)


@requires_git
def test_readonly_repository_is_still_scannable(scanner, store, repo_factory) -> None:
    """Scanning must not require write access to the scanned repository."""
    repo = repo_factory("readonly", commits=3)
    os.chmod(repo / ".git", stat.S_IRUSR | stat.S_IXUSR)
    try:
        repository_id = store.upsert_repository({"name": "readonly", "path": str(repo)})
        outcome = scanner.scan_repository(repository_id)
        assert outcome.status in {"completed", "partial"}
        assert store.count_commits(repository_id) == 3
    finally:
        os.chmod(repo / ".git", stat.S_IRWXU)


@pytest.mark.skipif(os.name == "nt" or os.geteuid() == 0, reason="permission tests need a non-root POSIX user")
@requires_git
def test_inaccessible_directory_does_not_crash_the_scan(scanner, store, repo_factory, tmp_path: Path) -> None:
    repo = repo_factory("locked", commits=2)
    repository_id = store.upsert_repository({"name": "locked", "path": str(repo)})
    if os.geteuid() == 0:
        pytest.skip("running as root: permissions are not enforced")
    os.chmod(repo, 0)
    try:
        outcome = scanner.scan_repository(repository_id)
        assert outcome.status == "failed"
        assert outcome.error
    finally:
        os.chmod(repo, stat.S_IRWXU)


# ---------------------------------------------------------------------- timeouts
def test_git_timeout_is_reported_as_a_failure(monkeypatch, store, settings, tmp_path: Path) -> None:
    from app.services.scan_service import ScanService

    repo = tmp_path / "repos" / "timeout"
    repo.mkdir(parents=True)
    (repo / ".git").mkdir()
    repository_id = store.upsert_repository({"name": "timeout", "path": str(repo)})

    service = ScanService(store, settings)
    # Every Git call times out: the scan must degrade to a partial result with
    # clear warnings instead of raising or hanging.
    monkeypatch.setattr(
        service.collector.runner,
        "run",
        lambda *args, **kwargs: GitResult(args=("timed-out",), code=-1, timed_out=True, error="git timed out"),
    )
    monkeypatch.setattr(service.collector.runner, "is_available", lambda: True)
    monkeypatch.setattr(service.collector.runner, "_version", "fake", raising=False)

    outcome = service.scan_repository(repository_id)
    assert outcome.status == "partial"
    assert any("timed out" in warning for warning in outcome.warnings)
    assert not outcome.error


# -------------------------------------------------------------- database failures
def test_database_failure_is_reported_not_raised(monkeypatch, store, settings, repo_factory) -> None:
    from app.services.scan_service import ScanService

    if not helpers.GIT_AVAILABLE:
        pytest.skip("git required")
    repo = repo_factory("db-failure", commits=2)
    repository_id = store.upsert_repository({"name": "db-failure", "path": str(repo)})

    service = ScanService(store, settings)

    def explode(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(type(store), "replace_branches", explode)
    outcome = service.scan_repository(repository_id)
    assert outcome.status == "failed"
    assert "Database error" in (outcome.error or "")
    run = store.list_scan_runs(repository_id=repository_id)[0]
    assert run["status"] == "failed"


def test_unwritable_database_path_reports_clearly(tmp_path: Path) -> None:
    db = Database(tmp_path / "directory-not-file")
    (tmp_path / "directory-not-file").mkdir(parents=True)
    with pytest.raises(DatabaseError):
        db.migrate()


# ------------------------------------------------------------- malformed git output
def test_malformed_git_output_is_ignored_gracefully() -> None:
    assert parse_commit_log("\x01" + "\x1f".join(["junk"] * 3) + "\n\n1\t2\tfile") == ([], {})
    assert parse_commit_log("no separators at all") == ([], {})
    assert parse_branch_refs("\x1f\x1f\x1f") == []
    # Binary / unknown status bytes are tolerated and never produce negative counts.
    counts = parse_status_porcelain("\x00\x01\x02\n???\n")
    assert counts["total"] >= 0
    assert all(value >= 0 for value in counts.values())


@requires_git
def test_truncated_binary_git_output_is_handled(runner: GitRunner, repo_factory) -> None:
    """Non-UTF8 bytes in a commit message must not break parsing."""
    repo = repo_factory("binary-message", commits=2)
    helpers.write(repo, "weird.txt", "content\n")
    helpers.git("add", "-A", cwd=repo)
    # Commit with a raw invalid UTF-8 byte in the subject.
    helpers.git(
        "-c",
        "i18n.commitEncoding=ISO-8859-1",
        "commit",
        "-m",
        "weird \xff subject",
        cwd=repo,
    )
    from app.collectors.commits import collect_commits

    batch = collect_commits(runner, str(repo), history_depth=10)
    assert len(batch.commits) == 3
    assert all(isinstance(commit["subject"], str) for commit in batch.commits)


# -------------------------------------------------------------- helper utilities
def test_is_informational_classification() -> None:
    assert is_informational("HEAD is detached (no branch checked out)")
    assert is_informational("History was capped at 500 commits.")
    assert not is_informational("git log failed: fatal: bad object")


def test_scan_outcome_serialisation() -> None:
    outcome = ScanOutcome(repository_id=1, name="demo", status="partial", warnings=["w"], error="e")
    payload = outcome.to_dict()
    assert payload["name"] == "demo" and payload["warnings"] == ["w"]
