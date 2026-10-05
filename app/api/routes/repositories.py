"""Repository routes (E6-S2) plus discovery and scanning (E2, E9)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ...analyzers.health import repository_health, repository_staleness, working_tree_warnings
from ...analyzers.metrics import parse_timestamp, repository_comparison
from ...models.schemas import (
    DiscoveryRequest,
    RepositoryBulkCreate,
    RepositoryCreate,
    RepositoryListResponse,
    ScanRequest,
)
from ...services.repository_service import RepositoryError
from ...services.scan_manager import ScanBusyError
from ..deps import Services, get_repository, get_services

router = APIRouter(tags=["repositories"])


def _enrich(repository: dict[str, Any], services: Services) -> dict[str, Any]:
    """Attach derived, UI-ready fields to a repository row."""
    reference = datetime.now(timezone.utc)
    last_dt = parse_timestamp(repository.get("last_commit_at"))
    days_since = (reference - last_dt).days if last_dt else None
    staleness = repository_staleness(
        repository, days_since_last_commit=days_since, settings=services.settings, now=reference
    )
    scan_dt = parse_timestamp(repository.get("last_scanned_at"))
    return {
        **repository,
        "days_since_last_commit": days_since,
        "days_since_scan": (reference - scan_dt).days if scan_dt else None,
        "staleness": staleness["bucket"],
        "staleness_label": staleness["label"],
        "staleness_message": staleness["message"],
        "health": {
            "score": round(float(repository.get("health_score") or 0), 1),
            "grade": repository.get("health_grade") or "F",
        },
        "is_scanned": bool(repository.get("last_scanned_at")),
    }


@router.get("/repositories", response_model=RepositoryListResponse, summary="List registered repositories")
def list_repositories(
    search: str | None = Query(default=None, description="Match name, path or current branch"),
    status_filter: Literal["all", "clean", "dirty", "detached", "bare", "empty", "error", "unknown"] = Query(
        default="all", alias="status"
    ),
    staleness: Literal["all", "active", "inactive", "stale", "abandoned", "empty", "unknown"] = Query(default="all"),
    sort: Literal["name", "last_commit", "commits", "branches", "changes", "scanned", "health"] = Query(
        default="last_commit"
    ),
    order: Literal["asc", "desc"] = Query(default="desc"),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=25, ge=1, le=200),
    services: Services = Depends(get_services),
) -> dict[str, Any]:
    total = len(services.store.list_repositories(search=search, status=status_filter, staleness=staleness))
    rows = services.store.list_repositories(
        search=search,
        status=status_filter,
        staleness=staleness,
        sort=sort,
        order=order,
        limit=per_page,
        offset=(page - 1) * per_page,
    )
    return {
        "items": [_enrich(row, services) for row in rows],
        "pagination": {
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": max(1, (total + per_page - 1) // per_page),
        },
        "filters": {"search": search, "status": status_filter, "staleness": staleness, "sort": sort, "order": order},
    }


@router.post("/repositories", status_code=status.HTTP_201_CREATED, summary="Register a local repository (E2-S1)")
def create_repository(payload: RepositoryCreate, services: Services = Depends(get_services)) -> dict[str, Any]:
    try:
        repository = services.repositories.add(payload.path, name=payload.name)
    except RepositoryError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {
        "repository": _enrich(repository, services),
        "message": f"Registered '{repository['name']}'. Run a scan to collect its Git data.",
    }


@router.post("/repositories/bulk", status_code=status.HTTP_201_CREATED, summary="Register several repositories")
def create_repositories(payload: RepositoryBulkCreate, services: Services = Depends(get_services)) -> dict[str, Any]:
    result = services.repositories.add_many(payload.paths, skip_existing=payload.skip_existing)
    return {
        "added": [_enrich(repository, services) for repository in result["added"]],
        "skipped": result["skipped"],
        "added_count": len(result["added"]),
    }


@router.post("/repositories/discover", summary="Discover repositories under a root (E2-S2)")
def discover_repositories(payload: DiscoveryRequest, services: Services = Depends(get_services)) -> dict[str, Any]:
    try:
        result = services.repositories.discover(
            root=payload.root, register=payload.register_found, max_depth=payload.max_depth
        )
    except RepositoryError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return result


@router.get("/repositories/suggestions", summary="Repositories under the configured roots that are not registered")
def suggest_repositories(
    limit: int = Query(default=50, ge=1, le=500),
    services: Services = Depends(get_services),
) -> dict[str, Any]:
    suggestions = services.repositories.suggestions(limit=limit)
    return {"items": suggestions, "count": len(suggestions), "roots": services.settings.repository_roots}


@router.get("/repositories/compare", summary="Compare repositories side by side (E13-S4)")
def compare_repositories(
    ids: str = Query(..., description="Comma separated repository ids"),
    services: Services = Depends(get_services),
) -> dict[str, Any]:
    try:
        repository_ids = [int(value) for value in ids.split(",") if value.strip()]
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="ids must be a comma separated list of integers") from exc
    if not repository_ids:
        raise HTTPException(status_code=400, detail="at least one repository id is required")
    return {"items": repository_comparison(services.store, repository_ids)}


@router.get("/repositories/{repository_id}", summary="Repository detail")
def get_repository_detail(
    repository: dict[str, Any] = Depends(get_repository),
    services: Services = Depends(get_services),
) -> dict[str, Any]:
    repository_id = int(repository["id"])
    health = repository_health(services.store, repository, settings=services.settings)
    return {
        "repository": _enrich(repository, services),
        "health": health,
        "branches": services.store.list_branches(repository_id, include_remote=True)[:15],
        "contributors": services.store.list_contributors(repository_id)[:15],
        "recent_commits": services.store.list_commits(repository_id, page=1, per_page=10)[0],
        "scans": services.store.list_scan_runs(limit=5, repository_id=repository_id),
        "working_tree": _working_tree(repository),
    }


@router.delete("/repositories/{repository_id}", summary="Unregister a repository and drop its data")
def delete_repository(
    repository: dict[str, Any] = Depends(get_repository),
    services: Services = Depends(get_services),
) -> dict[str, Any]:
    removed = services.repositories.remove(int(repository["id"]))
    return {"deleted": True, "repository": removed, "message": f"Removed '{removed['name']}' from the dashboard."}


@router.get("/repositories/{repository_id}/health", summary="Transparent health score breakdown (E10-S1)")
def get_health(
    repository: dict[str, Any] = Depends(get_repository),
    services: Services = Depends(get_services),
) -> dict[str, Any]:
    return repository_health(services.store, repository, settings=services.settings)


@router.get("/repositories/{repository_id}/status", summary="Working tree status (E10-S3)")
def get_status(
    repository: dict[str, Any] = Depends(get_repository),
    services: Services = Depends(get_services),
) -> dict[str, Any]:
    return {
        "repository_id": repository["id"],
        "state": repository.get("state"),
        "working_tree": _working_tree(repository),
        "warnings": working_tree_warnings(repository),
        "staleness": repository_staleness(repository, settings=services.settings),
        "last_scanned_at": repository.get("last_scanned_at"),
        "last_error": repository.get("last_error"),
        "scan_runs": services.store.list_scan_runs(limit=5, repository_id=int(repository["id"])),
    }


def _working_tree(repository: dict[str, Any]) -> dict[str, Any]:
    return {
        "is_dirty": bool(repository.get("is_dirty")),
        "detached_head": bool(repository.get("detached_head")),
        "is_bare": bool(repository.get("is_bare")),
        "uncommitted_files": int(repository.get("uncommitted_files") or 0),
        "staged_files": int(repository.get("staged_files") or 0),
        "untracked_files": int(repository.get("untracked_files") or 0),
        "tracked_files": int(repository.get("tracked_files") or 0),
    }


# ------------------------------------------------------------------------ scanning
@router.post(
    "/repositories/{repository_id}/scan",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Scan one repository (E9-S1, E9-S3)",
)
def scan_repository(
    payload: ScanRequest | None = None,
    repository: dict[str, Any] = Depends(get_repository),
    services: Services = Depends(get_services),
) -> dict[str, Any]:
    request_payload = payload or ScanRequest()
    try:
        job = services.scan_manager.start_repository_scan(
            int(repository["id"]),
            incremental=request_payload.incremental,
            full_history=request_payload.full_history,
            background=request_payload.background,
        )
    except ScanBusyError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return {
        "job": job.to_dict(),
        "repository_id": repository["id"],
        "message": f"Scanning '{repository['name']}'…",
    }


@router.get("/repositories/{repository_id}/recent-activity", summary="Per day activity for one repository")
def recent_activity(
    days: int = Query(default=30, ge=1, le=730),
    bucket: str = Query(default="day", pattern="^(day|week|month)$"),
    repository: dict[str, Any] = Depends(get_repository),
    services: Services = Depends(get_services),
) -> dict[str, Any]:
    from ...analyzers.metrics import activity_series, summarize_series

    series = activity_series(services.store, int(repository["id"]), days=days, bucket=bucket)
    return {
        "repository_id": repository["id"],
        "days": days,
        "bucket": bucket,
        "series": series,
        "summary": summarize_series(series),
    }
