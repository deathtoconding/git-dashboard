"""Background scan jobs (E9-S1, E9-S2, E9-S4).

Scans run in a daemon thread so the API stays responsive and the UI can poll
``GET /api/scan/status`` to display *Scanning… / Completed / Failed / Partial*.
Only one scan runs at a time: concurrent scans of the same repository would fight
over the same SQLite rows for no benefit.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from typing import Any

from ..database.connection import utc_now
from ..logging_config import get_logger
from .scan_service import ScanService

log = get_logger("services.scan_manager")


class ScanBusyError(RuntimeError):
    """Raised when a scan is requested while another scan is still running."""


@dataclass
class ScanJob:
    id: str
    kind: str
    status: str = "running"  # running | completed | failed | partial
    started_at: str = field(default_factory=utc_now)
    finished_at: str | None = None
    incremental: bool = True
    discover: bool = False
    repository_id: int | None = None
    current: str | None = None
    total: int = 0
    done: int = 0
    commits_added: int = 0
    error: str | None = None
    report: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "incremental": self.incremental,
            "discover": self.discover,
            "repository_id": self.repository_id,
            "current": self.current,
            "progress": {"done": self.done, "total": self.total},
            "commits_added": self.commits_added,
            "error": self.error,
            "report": self.report,
        }


class ScanManager:
    """Runs scans in the background and keeps their status for the UI."""

    def __init__(self, service: ScanService, *, keep_jobs: int = 20) -> None:
        self.service = service
        self._lock = threading.Lock()
        self._jobs: dict[str, ScanJob] = {}
        self._order: list[str] = []
        self._keep_jobs = keep_jobs
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------------ queries
    @property
    def busy(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def latest_job(self) -> ScanJob | None:
        for job_id in reversed(self._order):
            job = self._jobs.get(job_id)
            if job:
                return job
        return None

    def get_job(self, job_id: str) -> ScanJob | None:
        return self._jobs.get(job_id)

    def jobs(self, limit: int = 10) -> list[dict[str, Any]]:
        return [self._jobs[job_id].to_dict() for job_id in reversed(self._order[-limit:]) if job_id in self._jobs]

    def status(self) -> dict[str, Any]:
        latest = self.latest_job()
        return {
            "running": self.busy,
            "job": latest.to_dict() if latest else None,
            "jobs": self.jobs(limit=5),
            "database_scan_status": self.service.scan_status(),
        }

    def wait(self, job_id: str | None = None, timeout: float = 120.0) -> dict[str, Any] | None:
        """Block until a job finishes (used by tests and the CLI)."""
        job = self._jobs.get(job_id) if job_id else self.latest_job()
        if not job:
            return None
        finished = threading.Event()
        while timeout > 0 and not finished.is_set():
            if job.status != "running":
                break
            finished.wait(0.05)
            timeout -= 0.05
        return job.to_dict()

    # ------------------------------------------------------------------- start
    def start_repository_scan(
        self,
        repository_id: int,
        *,
        incremental: bool = True,
        full_history: bool = False,
        background: bool = True,
    ) -> ScanJob:
        if self.busy:
            raise ScanBusyError("A scan is already running. Wait for it to finish and try again.")
        job = ScanJob(
            id=uuid.uuid4().hex[:12],
            kind="single",
            incremental=incremental,
            repository_id=repository_id,
            total=1,
        )
        self._register(job)
        if background:
            self._spawn(job, lambda: self._run_single(job, full_history=full_history))
        else:
            self._run_single(job, full_history=full_history)
        return job

    def start_full_scan(
        self,
        *,
        incremental: bool = True,
        discover: bool = False,
        root: str | None = None,
        background: bool = True,
    ) -> ScanJob:
        if self.busy:
            raise ScanBusyError("A scan is already running. Wait for it to finish and try again.")
        job = ScanJob(id=uuid.uuid4().hex[:12], kind="full", incremental=incremental, discover=discover, total=0)
        self._register(job)
        if background:
            self._spawn(job, lambda: self._run_full(job, root=root))
        else:
            self._run_full(job, root=root)
        return job

    def _register(self, job: ScanJob) -> None:
        with self._lock:
            self._jobs[job.id] = job
            self._order.append(job.id)
            while len(self._order) > self._keep_jobs:
                stale = self._order.pop(0)
                self._jobs.pop(stale, None)

    def _spawn(self, job: ScanJob, target) -> None:
        def runner() -> None:
            try:
                target()
            except Exception as exc:  # noqa: BLE001 - never let a thread die silently
                log.exception("scan job %s crashed", job.id)
                job.status = "failed"
                job.error = str(exc)
                job.finished_at = job.finished_at or utc_now()

        self._thread = threading.Thread(target=runner, name=f"scan-{job.id}", daemon=True)
        self._thread.start()

    # -------------------------------------------------------------------- work
    def _run_single(self, job: ScanJob, *, full_history: bool) -> None:
        repositories = self.service.store.list_repositories()
        job.total = 1
        target = next((repo for repo in repositories if repo["id"] == job.repository_id), None)
        job.current = target["name"] if target else f"#{job.repository_id}"
        try:
            outcome = self.service.scan_repository(
                job.repository_id,
                incremental=job.incremental,
                full_history=full_history,
                kind="single",
            )
        except Exception as exc:  # noqa: BLE001
            job.status = "failed"
            job.error = str(exc)
            job.finished_at = utc_now()
            return
        job.done = 1
        job.commits_added = outcome.commits_added
        job.report = {"repositories": [outcome.to_dict()], "scanned": 1 if outcome.status != "failed" else 0, "failed": 1 if outcome.status == "failed" else 0}
        job.status = outcome.status
        job.error = outcome.error
        job.finished_at = utc_now()

    def _run_full(self, job: ScanJob, *, root: str | None) -> None:
        def progress(done: int, total: int, name: str) -> None:
            job.done = done
            job.total = total
            job.current = name or None

        try:
            report = self.service.scan_all(
                incremental=job.incremental,
                discover=job.discover,
                root=root,
                progress=progress,
            )
            job.commits_added = report.commits_added
            job.report = report.to_dict()
            job.status = report.status
            job.error = None if report.failed == 0 else f"{report.failed} repository(ies) failed"
        except Exception as exc:  # noqa: BLE001 - a background job must never die silently
            log.exception("full scan job %s failed", job.id)
            job.status = "failed"
            job.error = str(exc)
        finally:
            job.finished_at = job.finished_at or utc_now()
            job.current = None
