"""Analytics routes (E6-S5, E13): metrics, activity, contributors, heatmap, trends."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from ...analyzers.metrics import (
    activity_metrics,
    activity_series,
    change_metrics,
    contributor_trends,
    heatmap,
    repository_metrics,
    summarize_series,
)
from ..deps import Services, get_repository, get_services

router = APIRouter(tags=["analytics"])


@router.get("/repositories/{repository_id}/metrics", summary="Basic + change metrics (E5-S1, E5-S3)")
def metrics(
    repository: dict[str, Any] = Depends(get_repository),
    services: Services = Depends(get_services),
) -> dict[str, Any]:
    repository_id = int(repository["id"])
    return {
        "repository_id": repository_id,
        "name": repository["name"],
        "metrics": repository_metrics(services.store, repository_id),
        "changes": change_metrics(services.store, repository_id),
    }


@router.get("/repositories/{repository_id}/activity", summary="Activity metrics (E5-S2)")
def activity(
    days: int = Query(default=30, ge=1, le=730),
    bucket: str = Query(default="day", pattern="^(day|week|month)$"),
    repository: dict[str, Any] = Depends(get_repository),
    services: Services = Depends(get_services),
) -> dict[str, Any]:
    repository_id = int(repository["id"])
    series = activity_series(services.store, repository_id, days=days, bucket=bucket)
    return {
        "repository_id": repository_id,
        "days": days,
        "bucket": bucket,
        "metrics": activity_metrics(services.store, repository_id),
        "series": series,
        "summary": summarize_series(series),
    }


@router.get("/repositories/{repository_id}/contributors", summary="Contributors with commit and line statistics (E3-S5, E8-S4)")
def contributors(
    repository: dict[str, Any] = Depends(get_repository),
    services: Services = Depends(get_services),
) -> dict[str, Any]:
    rows = services.store.list_contributors(int(repository["id"]))
    total_commits = sum(int(row.get("commit_count") or 0) for row in rows) or 1
    items = [
        {
            **row,
            "share": round(int(row.get("commit_count") or 0) / total_commits * 100, 1),
            "net_lines": int(row.get("additions") or 0) - int(row.get("deletions") or 0),
        }
        for row in rows
    ]
    return {
        "repository_id": repository["id"],
        "items": items,
        "count": len(items),
        "top_contributor": items[0] if items else None,
    }


@router.get("/repositories/{repository_id}/heatmap", summary="Commit heatmap by weekday x hour (E13-S1)")
def commit_heatmap(
    days: int = Query(default=365, ge=7, le=3650),
    repository: dict[str, Any] = Depends(get_repository),
    services: Services = Depends(get_services),
) -> dict[str, Any]:
    return heatmap(services.store, int(repository["id"]), days=days)


@router.get("/repositories/{repository_id}/contributor-trends", summary="Weekly contributor trends (E13-S2)")
def trends(
    weeks: int = Query(default=12, ge=1, le=104),
    repository: dict[str, Any] = Depends(get_repository),
    services: Services = Depends(get_services),
) -> dict[str, Any]:
    return {
        "repository_id": repository["id"],
        "weeks": weeks,
        "series": contributor_trends(services.store, int(repository["id"]), weeks=weeks),
    }


@router.get("/repositories/{repository_id}/file-churn", summary="Most frequently changed files (E13-S3)")
def file_churn(
    limit: int = Query(default=20, ge=1, le=200),
    repository: dict[str, Any] = Depends(get_repository),
    services: Services = Depends(get_services),
) -> dict[str, Any]:
    return {
        "repository_id": repository["id"],
        "items": services.store.top_changed_files(int(repository["id"]), limit=limit),
    }
