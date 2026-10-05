"""Scanning: collect Git data, persist it and derive health (Epic E9, E4, E10).

Design rules that matter for reliability:

* every repository scan runs in its own try/except - one broken repository never
  prevents the others from being scanned (E9-S2 acceptance criteria),
* every scan is recorded in ``scan_runs`` (E4-S4) with status
  ``running | completed | failed | partial`` (E9-S4),
* commits are inserted with ``INSERT OR IGNORE`` on ``(repository_id, sha)`` so
  repeated scans never duplicate rows (E4-S3),
* incremental scans only walk commits that are not reachable from the previously
  stored HEAD (E9-S3).
"""

from __future__ import annotations

import contextlib
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..analyzers.branch_health import classify_branches
from ..analyzers.health import repository_health
from ..collectors.collector import GitCollector
from ..collectors.discovery import inspect_path
from ..collectors.git_runner import GitError, GitNotFoundError
from ..config import Settings
from ..database.connection import utc_now
from ..database.store import Store
from ..logging_config import get_logger, get_repo_logger

log = get_logger("services.scan")

MAX_FILE_CHANGE_BACKFILL = 150

# Warnings that describe a legitimate repository state rather than missing data.
# They are surfaced in the UI but do not turn a scan into a "partial" scan.
INFORMATIONAL_WARNINGS = (
    "HEAD is detached",
    "History was capped",
)


def is_informational(warning: str) -> bool:
    """True when a warning reports a repository state, not a collection failure."""
    return warning.startswith(INFORMATIONAL_WARNINGS)


@dataclass(slots=True)
class ScanOutcome:
    """Result of scanning a single repository."""

    repository_id: int | None
    name: str
    status: str = "completed"  # completed | partial | failed
    path: str | None = None
    scan_id: int | None = None
    commits_added: int = 0
    records_processed: int = 0
    branches: int = 0
    contributors: int = 0
    incremental: bool = False
    duration_ms: int = 0
    warnings: list[str] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "repository_id": self.repository_id,
            "name": self.name,
            "path": self.path,
            "status": self.status,
            "scan_id": self.scan_id,
            "commits_added": self.commits_added,
            "records_processed": self.records_processed,
            "branches": self.branches,
            "contributors": self.contributors,
            "incremental": self.incremental,
            "duration_ms": self.duration_ms,
            "warnings": self.warnings,
            "error": self.error,
        }


@dataclass(slots=True)
class ScanReport:
    """Aggregate result of a scan over many repositories."""

    kind: str = "full"
    outcomes: list[ScanOutcome] = field(default_factory=list)
    discovered: int = 0
    registered: int = 0
    started_at: str = field(default_factory=utc_now)
    finished_at: str | None = None
    duration_ms: int = 0

    @property
    def scanned(self) -> int:
        return len([outcome for outcome in self.outcomes if outcome.status != "failed"])

    @property
    def failed(self) -> int:
        return len([outcome for outcome in self.outcomes if outcome.status == "failed"])

    @property
    def commits_added(self) -> int:
        return sum(outcome.commits_added for outcome in self.outcomes)

    @property
    def records_processed(self) -> int:
        return sum(outcome.records_processed for outcome in self.outcomes)

    @property
    def status(self) -> str:
        if not self.outcomes:
            return "completed"
        if self.failed and self.scanned:
            return "partial"
        if self.failed:
            return "failed"
        return "completed"

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": self.duration_ms,
            "scanned": self.scanned,
            "failed": self.failed,
            "total": len(self.outcomes),
            "commits_added": self.commits_added,
            "records_processed": self.records_processed,
            "discovered": self.discovered,
            "registered": self.registered,
            "repositories": [outcome.to_dict() for outcome in self.outcomes],
        }


class ScanService:
    """Orchestrates collection, persistence and analysis for repositories."""

    def __init__(
        self,
        store: Store,
        settings: Settings,
        *,
        collector: GitCollector | None = None,
    ) -> None:
        self.store = store
        self.settings = settings
        self.collector = collector or GitCollector(
            history_depth=settings.history_depth,
        )
        self.collector.runner.timeout = settings.git_timeout_seconds
        self.collector.runner.binary = settings.git_binary

    # ------------------------------------------------------------------ helpers
    def git_available(self) -> tuple[bool, str | None]:
        return self.collector.check_git()

    def _since_sha(self, repository: dict[str, Any], *, incremental: bool, full_history: bool) -> str | None:
        if not incremental or full_history:
            return None
        if not repository.get("last_scanned_at"):
            return None
        head = repository.get("head_commit")
        if not head:
            return None
        check = self.collector.runner.run(["cat-file", "-e", f"{head}^{{commit}}"], cwd=repository["path"])
        if not check.ok:
            log.info("stored HEAD %s no longer exists in %s; performing a full walk", head, repository["path"])
            return None
        return head

    # ------------------------------------------------------------- single scan
    def scan_repository(
        self,
        repository_id: int,
        *,
        incremental: bool = True,
        full_history: bool = False,
        include_branches: bool = True,
        kind: str | None = None,
    ) -> ScanOutcome:
        """Scan exactly one repository and persist the results."""
        repository = self.store.get_repository(repository_id)
        if not repository:
            return ScanOutcome(
                repository_id=repository_id,
                name=f"#{repository_id}",
                status="failed",
                error=f"Repository {repository_id} is not registered",
            )

        repo_log = get_repo_logger("services.scan", repository)
        scan_id = self.store.start_scan_run(kind or ("incremental" if incremental else "single"), repository_id)
        outcome = ScanOutcome(repository_id=repository_id, name=repository["name"], path=repository["path"], scan_id=scan_id)
        started = time.perf_counter()
        path = Path(repository["path"])

        try:
            self.collector.require_git()
        except GitNotFoundError as exc:
            return self._fail(outcome, str(exc), started, repo_log)

        # --- validate the repository still exists and is still a Git repo ----
        discovered = inspect_path(path)
        if discovered.error:
            return self._fail(outcome, f"Repository unavailable: {discovered.error}", started, repo_log)
        if not path.exists():
            return self._fail(outcome, f"Path no longer exists: {path}", started, repo_log)

        try:
            since_sha = self._since_sha(repository, incremental=incremental, full_history=full_history)
            collection = self.collector.collect(
                path,
                since_sha=since_sha,
                include_branches=include_branches,
            )
        except GitError as exc:
            return self._fail(outcome, f"Git error: {exc}", started, repo_log)
        except Exception as exc:  # noqa: BLE001 - a single repo must never break a scan
            repo_log.exception("unexpected failure while collecting %s", path)
            return self._fail(outcome, f"Unexpected error: {exc}", started, repo_log)

        outcome.incremental = collection.incremental
        outcome.warnings.extend(collection.warnings)

        state = collection.state
        previous = repository

        branches = classify_branches(
            collection.branches,
            inactive_days=self.settings.inactive_branch_days,
            stale_days=self.settings.stale_branch_days,
        )

        processable = list(collection.commits)
        row = state.to_row()
        row["path_key"] = previous["path_key"]
        row["branch_count"] = len([branch for branch in branches if not branch.get("is_remote")])
        row["last_scanned_at"] = utc_now()
        row["last_error"] = None  # a successful scan clears the previous error
        # Preserve a user supplied display name; a renamed folder updates it automatically.
        if previous.get("name") and previous["name"] != Path(previous["path"]).name:
            row["name"] = previous["name"]

        inserted_shas: list[str] = []
        try:
            with self.store.db.transaction() as conn:
                repository_id = self.store.upsert_repository(row, conn=conn)
                stored_commits = self.store.count_commits(repository_id, conn=conn)
                if state.total_commits < stored_commits:
                    # `rev-list --count` can under-report in shallow clones; trust the store.
                    conn.execute(
                        "UPDATE repositories SET total_commits = ?, first_commit_at = COALESCE(first_commit_at, ?) WHERE id = ?",
                        (
                            stored_commits,
                            (self.store.first_and_last_commit(repository_id, conn=conn)[0] or {}).get("authored_at"),
                            repository_id,
                        ),
                    )
                self.store.replace_branches(repository_id, branches, conn=conn)
                inserted_shas = self.store.insert_commits(repository_id, processable, conn=conn)
                fresh = set(inserted_shas)
                for sha, changes in collection.file_changes.items():
                    # Skip re-writing file rows that are already stored and complete.
                    if sha in fresh or not self.store.list_file_changes(repository_id, sha, conn=conn):
                        self.store.replace_file_changes(repository_id, sha, changes, conn=conn)
                contributors = self.store.author_aggregates(repository_id, conn=conn)
                self.store.replace_contributors(repository_id, contributors, conn=conn)
                self.store.finish_scan_run(
                    scan_id,
                    status="completed",
                    records_processed=len(processable) + len(branches),
                    commits_added=len(inserted_shas),
                    repositories_scanned=1,
                    duration_ms=int((time.perf_counter() - started) * 1000),
                    conn=conn,
                )
        except Exception as exc:  # noqa: BLE001 - database failure must be reported, not fatal
            repo_log.exception("failed to persist scan results for %s", path)
            return self._fail(outcome, f"Database error: {exc}", started, repo_log)

        outcome.commits_added = len(inserted_shas)
        outcome.records_processed = len(processable) + len(branches)
        outcome.branches = len(branches)
        outcome.contributors = len(contributors)
        outcome.duration_ms = int((time.perf_counter() - started) * 1000)

        # Bounded backfill for commits stored without file details (older scans / capped walks).
        self._backfill_file_changes(repository_id, path, repo_log)

        # Health is derived from the freshly stored data and cached on the row so
        # the dashboard overview stays fast even with hundreds of repositories.
        self._refresh_health(repository_id)

        if any(not is_informational(warning) for warning in outcome.warnings):
            outcome.status = "partial"
        if collection.commit_batch.truncated:
            outcome.warnings.append(
                f"History was capped at {self.settings.history_depth} commits. "
                "Increase 'history_depth' in config.json for a deeper history."
            )
        repo_log.info(
            "scan %s: %s commits added (%s processed) in %sms",
            outcome.status,
            outcome.commits_added,
            outcome.records_processed,
            outcome.duration_ms,
        )
        return outcome

    def _backfill_file_changes(self, repository_id: int, path: Path, repo_log: Any) -> None:
        try:
            missing = self.store.query(
                """
                SELECT sha FROM commits
                 WHERE repository_id = ? AND is_merge = 0 AND files_changed = 0
                   AND sha NOT IN (SELECT DISTINCT commit_sha FROM file_changes WHERE repository_id = ?)
                 ORDER BY authored_at DESC LIMIT ?
                """,
                (repository_id, repository_id, MAX_FILE_CHANGE_BACKFILL),
            )
            if not missing:
                return
            shas = [row["sha"] for row in missing]
            batch = self.collector.backfill_file_changes(path, shas)
            if not batch.file_changes:
                return
            with self.store.db.transaction() as conn:
                for sha, changes in batch.file_changes.items():
                    self.store.replace_file_changes(repository_id, sha, changes, conn=conn)
                for commit in batch.commits:
                    conn.execute(
                        "UPDATE commits SET additions = ?, deletions = ?, files_changed = ? WHERE repository_id = ? AND sha = ?",
                        (
                            int(commit.get("additions") or 0),
                            int(commit.get("deletions") or 0),
                            int(commit.get("files_changed") or 0),
                            repository_id,
                            commit["sha"],
                        ),
                    )
                contributors = self.store.author_aggregates(repository_id, conn=conn)
                self.store.replace_contributors(repository_id, contributors, conn=conn)
            repo_log.info("backfilled file changes for %d commit(s)", len(batch.file_changes))
        except Exception:  # noqa: BLE001 - backfill is best effort
            repo_log.warning("file-change backfill failed for repository %s", repository_id, exc_info=True)

    def _refresh_health(self, repository_id: int) -> dict[str, Any]:
        repository = self.store.get_repository(repository_id) or {}
        health = repository_health(self.store, repository, settings=self.settings)
        self.store.execute(
            "UPDATE repositories SET health_score = ?, health_grade = ?, staleness = ?, updated_at = ? WHERE id = ?",
            (health["score"], health["grade"], health["staleness"]["bucket"], utc_now(), repository_id),
        )
        return health

    def _fail(self, outcome: ScanOutcome, error: str, started: float, repo_log: Any) -> ScanOutcome:
        outcome.status = "failed"
        outcome.error = error
        outcome.duration_ms = int((time.perf_counter() - started) * 1000)
        if outcome.scan_id:
            self.store.finish_scan_run(
                outcome.scan_id,
                status="failed",
                error=error[:1000],
                duration_ms=outcome.duration_ms,
            )
        if outcome.repository_id:
            self.store.set_repository_error(outcome.repository_id, error[:1000])
        repo_log.error("scan failed: %s", error)
        return outcome

    # ---------------------------------------------------------------- all repos
    def scan_all(
        self,
        *,
        incremental: bool = True,
        discover: bool = False,
        root: str | None = None,
        repositories: Sequence[dict[str, Any]] | None = None,
        progress: Callable[[int, int, str], None] | None = None,
    ) -> ScanReport:
        """Scan every registered repository (E9-S2), optionally discovering first.

        ``progress(done, total, repository_name)`` lets background jobs report how
        far a full scan has progressed (E9-S4).  The whole run is recorded once in
        ``scan_runs`` in addition to the per-repository rows.
        """
        report = ScanReport(kind="full")
        repository_service = self._repository_service()
        run_id = self.store.start_scan_run("full", None)

        def finish(report: ScanReport) -> ScanReport:
            report.finished_at = utc_now()
            report.duration_ms = sum(outcome.duration_ms for outcome in report.outcomes)
            self.store.finish_scan_run(
                run_id,
                status=report.status,
                records_processed=report.records_processed,
                commits_added=report.commits_added,
                repositories_scanned=report.scanned,
                repositories_failed=report.failed,
                duration_ms=report.duration_ms,
                error=(
                    "; ".join(
                        f"{outcome.name}: {outcome.error}" for outcome in report.outcomes if outcome.status == "failed"
                    )[:1000]
                    or None
                ),
            )
            return report

        if discover:
            try:
                discovery = repository_service.discover(root=root, register=True)
                report.discovered = discovery["count"]
                report.registered = discovery.get("registered_count", 0)
            except Exception as exc:  # noqa: BLE001 - discovery problems must not abort a scan
                log.error("discovery before scan failed: %s", exc)
                report.discovered = 0
                report.registered = 0

        targets = list(repositories) if repositories is not None else self.store.list_repositories()
        if not targets:
            log.info("scan all: nothing to scan (no repositories registered)")
            return finish(report)

        available, version = self.git_available()
        if not available:
            message = (
                f"Git executable {self.settings.git_binary!r} was not found. "
                "Install Git or update 'git_binary' in config.json."
            )
            log.error("scan all aborted: %s", message)
            for repository in targets:
                report.outcomes.append(
                    ScanOutcome(
                        repository_id=repository["id"],
                        name=repository["name"],
                        path=repository["path"],
                        status="failed",
                        error=message,
                    )
                )
            return finish(report)

        log.info("scan all started for %d repositories (git %s)", len(targets), version)
        for index, repository in enumerate(targets):
            if progress:
                try:
                    progress(index, len(targets), repository.get("name", "unknown"))
                except Exception:  # noqa: BLE001 - progress reporting is best effort
                    log.debug("progress callback failed", exc_info=True)
            try:
                outcome = self.scan_repository(repository["id"], incremental=incremental, kind="full")
            except Exception as exc:  # noqa: BLE001 - belt and braces: keep scanning the rest
                log.exception("scan of repository %s crashed", repository.get("id"))
                outcome = ScanOutcome(
                    repository_id=repository.get("id"),
                    name=repository.get("name", "unknown"),
                    path=repository.get("path"),
                    status="failed",
                    error=str(exc),
                )
            report.outcomes.append(outcome)

        if progress:
            with contextlib.suppress(Exception):
                progress(len(targets), len(targets), "")
        finish(report)
        log.info(
            "scan all finished: %d ok, %d failed, %d commits added in %dms",
            report.scanned,
            report.failed,
            report.commits_added,
            report.duration_ms,
        )
        return report

    def _repository_service(self):
        from .repository_service import RepositoryService

        return RepositoryService(self.store, self.settings)

    # ------------------------------------------------------------------- status
    def scan_status(self) -> dict[str, Any]:
        latest = self.store.latest_scan_run()
        running = self.store.query_one("SELECT COUNT(*) AS total FROM scan_runs WHERE status = 'running'") or {}
        return {
            "running": int(running.get("total") or 0) > 0,
            "running_count": int(running.get("total") or 0),
            "latest": latest,
            "recent": self.store.list_scan_runs(limit=10),
        }
