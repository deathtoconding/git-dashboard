"""System routes: health, settings, dashboard overview, insights, exports."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from ... import __version__
from ...analyzers.health import dashboard_insights
from ...analyzers.metrics import activity_series, summarize_series
from ...config import ConfigError, save_settings
from ...logging_config import get_logger
from ...models.schemas import SettingsUpdate
from ..deps import Services, get_services
from ..serializers import enrich_repository

log = get_logger("api.system")

router = APIRouter(tags=["system"])


@router.get("/health", summary="Liveness and readiness of the dashboard")
def health(request: Request, services: Services = Depends(get_services)) -> dict[str, Any]:
    """E6-S1 ``GET /health`` - reports Git, database and scan status."""
    warnings: list[str] = []
    git_available, git_version = services.collector.check_git()
    if not git_available:
        warnings.append(
            f"Git executable {services.settings.git_binary!r} is not available; "
            "repositories cannot be discovered or scanned until it is installed."
        )

    database: dict[str, Any] = {
        "path": str(services.settings.database_file),
        "exists": services.settings.database_file.exists(),
        "size_bytes": services.store.db.size_bytes(),
        "schema_version": services.store.db.current_version(),
        "imported_repositories": services.store.count_repositories(),
    }
    latest = services.store.latest_scan_run()
    if latest and latest.get("status") == "failed":
        warnings.append(f"Last scan failed: {latest.get('error') or 'unknown error'}")

    scan = services.scan_manager.status()
    return {
        "status": "ok" if not warnings else "degraded",
        "version": __version__,
        "git_available": git_available,
        "git_version": git_version,
        "git_binary": services.settings.git_binary,
        "database": database,
        "repositories": database["imported_repositories"],
        "scan": {
            "running": scan["running"],
            "latest_run": latest,
            "job": scan["job"],
        },
        "warnings": warnings,
    }


@router.get("/version", summary="Application version")
def version() -> dict[str, str]:
    return {"version": __version__, "name": "Local Git Repository Dashboard"}


# ---------------------------------------------------------------------- settings
@router.get("/settings", summary="Effective configuration")
def read_settings(services: Services = Depends(get_services)) -> dict[str, Any]:
    settings = services.settings
    return {
        "settings": settings.to_dict(),
        "paths": {
            "project_root": str(settings.project_root),
            "config_file": str(settings.config_path) if settings.config_path else None,
            "database_file": str(settings.database_file),
            "data_dir": str(settings.data_dir),
        },
        "repository_roots": [_root_info(settings, root) for root in settings.repository_roots],
        "excluded_dirs": settings.excluded_dirs,
        "thresholds": {
            "stale_branch_days": settings.stale_branch_days,
            "inactive_branch_days": settings.inactive_branch_days,
            "repo_inactive_days": settings.repo_inactive_days,
            "repo_stale_days": settings.repo_stale_days,
            "repo_abandoned_days": settings.repo_abandoned_days,
        },
    }


@router.put("/settings", summary="Validate and persist configuration")
def update_settings(
    payload: SettingsUpdate,
    request: Request,
    services: Services = Depends(get_services),
) -> dict[str, Any]:
    """Invalid configuration produces a clear 400 error naming the offending key."""
    changes = {key: value for key, value in payload.model_dump().items() if value is not None}
    if not changes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No settings were provided")
    try:
        updated = services.settings.with_overrides(changes)
    except ConfigError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    path = save_settings(updated, path=services.settings.config_path)
    request.app.state.settings = updated
    log.info("settings updated via API: %s (saved to %s)", ", ".join(sorted(changes)), path)
    return {
        "saved": True,
        "config_file": str(path),
        "changed": sorted(changes),
        "settings": updated.to_dict(),
        "restart_required_for": [
            key for key in changes if key in {"host", "port", "database_path", "log_level", "refresh_interval_minutes"}
        ],
    }


@router.get("/settings/roots", summary="Configured roots with availability")
def list_roots(services: Services = Depends(get_services)) -> dict[str, Any]:
    return {"roots": [_root_info(services.settings, root) for root in services.settings.repository_roots]}


def _root_info(settings, root: str) -> dict[str, Any]:
    path = settings.resolve_path(root)
    return {"value": root, "path": str(path), "exists": path.exists(), "is_dir": path.is_dir()}


# ---------------------------------------------------------------------- dashboard
@router.get("/dashboard", summary="Everything the overview page needs")
def dashboard(
    days: int = Query(default=30, ge=1, le=730, description="Activity window in days"),
    bucket: str = Query(default="day", pattern="^(day|week|month)$"),
    services: Services = Depends(get_services),
) -> dict[str, Any]:
    """E7-S2 overview cards, recent activity chart and insights in one call."""
    summary = services.store.repository_summary()
    reference = datetime.now(timezone.utc)
    repositories = [
        enrich_repository(row, services, now=reference)
        for row in services.store.list_repositories(sort="last_commit", order="desc")
    ]
    recent = [
        enrich_repository(row, services, now=reference) for row in services.store.recently_active_repositories(limit=6)
    ]

    series = _global_series(services.store, days=days, bucket=bucket)
    total_commits_30d = services.store.count_commits_all(since=_days_ago(30))

    return {
        "cards": {
            "repositories": summary["repositories"],
            "uncommitted_changes": summary["uncommitted_files"],
            "dirty_repositories": summary["dirty_repositories"],
            "branches": summary["branches"],
            "stale_branches": services.store.count_stale_branches(),
            "commits": summary["total_commits"],
            "commits_last_30d": total_commits_30d,
            "contributors": summary["contributors"],
            "stale_repositories": summary["stale_repositories"],
            "failing_repositories": summary["failing_repositories"],
            "average_health": round(float(summary.get("average_health") or 0), 1),
            "detached_repositories": summary["detached_repositories"],
        },
        "activity": {
            "days": days,
            "bucket": bucket,
            "series": series,
            "summary": summarize_series(series),
        },
        "recent_repositories": recent,
        "repositories": repositories,
        "insights": dashboard_insights(services.store, settings=services.settings, limit=15),
        "scan": services.scan_manager.status(),
        "last_updated": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }


@router.get("/activity", summary="Commit activity across repositories (E7-S4)")
def activity(
    days: int = Query(default=30, ge=1, le=730),
    bucket: str = Query(default="day", pattern="^(day|week|month)$"),
    repository_id: int | None = Query(default=None),
    services: Services = Depends(get_services),
) -> dict[str, Any]:
    if repository_id is not None:
        repository = services.store.get_repository(repository_id)
        if not repository:
            raise HTTPException(status_code=404, detail=f"Repository {repository_id} is not registered")
        series = activity_series(services.store, repository_id, days=days, bucket=bucket)
    else:
        series = _global_series(services.store, days=days, bucket=bucket)
    return {
        "days": days,
        "bucket": bucket,
        "repository_id": repository_id,
        "series": series,
        "summary": summarize_series(series),
    }


@router.get("/activity/repositories", summary="Commit counts per repository inside a window (E7-S4)")
def activity_by_repository(
    days: int = Query(default=30, ge=1, le=730),
    services: Services = Depends(get_services),
) -> dict[str, Any]:
    since = _days_ago(days)
    rows = services.store.query(
        """
        SELECT r.id, r.name, r.path, r.state, r.staleness, r.health_score, r.health_grade,
               r.total_commits, r.last_commit_at,
               COALESCE(COUNT(c.id), 0) AS commits
          FROM repositories r
          LEFT JOIN commits c ON c.repository_id = r.id AND c.authored_at >= ?
         GROUP BY r.id
         ORDER BY commits DESC, r.last_commit_at DESC
        """,
        (since,),
    )
    return {"days": days, "since": since, "items": rows, "count": len(rows)}


@router.get("/insights", summary="Actionable recommendations across repositories (E10-S4)")
def insights(
    limit: int = Query(default=25, ge=1, le=200),
    services: Services = Depends(get_services),
) -> dict[str, Any]:
    items = dashboard_insights(services.store, settings=services.settings, limit=limit)
    return {
        "items": items,
        "counts": {
            "error": len([item for item in items if item["severity"] == "error"]),
            "warning": len([item for item in items if item["severity"] == "warning"]),
            "info": len([item for item in items if item["severity"] == "info"]),
        },
    }


def _days_ago(days: int) -> str:
    from datetime import timedelta

    return (datetime.now(timezone.utc) - timedelta(days=days)).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _global_series(store, *, days: int, bucket: str) -> list[dict[str, Any]]:
    """Commit counts across every repository, gap-filled, using a single SQL query."""
    from ...analyzers.metrics import _bucket_series

    daily = {row["day"]: int(row["commits"]) for row in store.daily_commit_counts_all(since=_days_ago(days))}
    return _bucket_series(daily, days=days, bucket=bucket, now=datetime.now(timezone.utc))


# ------------------------------------------------------------------------ exports
@router.get("/export/json", summary="JSON snapshot of the dashboard data (E12-S4)")
def export_json(
    repository_id: int | None = Query(default=None),
    download: bool = Query(default=False, description="Send as a file download instead of inline JSON"),
    services: Services = Depends(get_services),
) -> Any:
    from fastapi.responses import Response

    payload = services.export.snapshot_json(repository_id=repository_id)
    if download:
        filename = f"git-dashboard-{repository_id or 'all'}.json"
        return Response(
            content=payload,
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    import json

    return json.loads(payload)


@router.get("/export/csv/{table}", summary="CSV export of a single table")
def export_csv(table: str, repository_id: int | None = Query(default=None), services: Services = Depends(get_services)):
    from fastapi.responses import Response

    try:
        payload = services.export.table_csv(table, repository_id=repository_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Response(
        content=payload,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{table}.csv"'},
    )


@router.post("/export/backup", summary="Copy the SQLite database to data/backups")
def export_backup(
    directory: str | None = Query(default=None), services: Services = Depends(get_services)
) -> dict[str, Any]:
    try:
        target = services.export.backup_database(directory=directory)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Backup failed: {exc}") from exc
    return {"backup": str(target), "size_bytes": target.stat().st_size if target.exists() else 0}


@router.post("/export/snapshot", summary="Write a JSON snapshot to data/exports")
def export_snapshot(
    directory: str | None = Query(default=None),
    repository_id: int | None = Query(default=None),
    services: Services = Depends(get_services),
) -> dict[str, Any]:
    target = services.export.write_snapshot(directory=directory, repository_id=repository_id)
    return {"snapshot": str(target)}
