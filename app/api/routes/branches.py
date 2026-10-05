"""Branch routes (E6-S4) - per repository and across every repository."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Query

from ...analyzers.branch_health import branch_health_summary
from ...models.schemas import BranchListResponse
from ..deps import Services, get_repository, get_services

router = APIRouter(tags=["branches"])

BranchFilter = Literal["all", "active", "inactive", "stale", "current", "merged"]


@router.get(
    "/repositories/{repository_id}/branches",
    response_model=BranchListResponse,
    summary="Branches of one repository with active/stale/current filters",
)
def list_repository_branches(
    branch_filter: BranchFilter = Query(default="all", alias="filter"),
    search: str | None = Query(default=None),
    include_remote: bool = Query(default=True),
    repository: dict[str, Any] = Depends(get_repository),
    services: Services = Depends(get_services),
) -> dict[str, Any]:
    repository_id = int(repository["id"])
    items = services.store.list_branches(
        repository_id,
        branch_filter=branch_filter,
        search=search,
        include_remote=include_remote,
    )
    return {
        "items": items,
        "summary": branch_health_summary(
            services.store.list_branches(repository_id, include_remote=True),
            inactive_days=services.settings.inactive_branch_days,
            stale_days=services.settings.stale_branch_days,
        ),
    }


@router.get("/branches", summary="Branches across every repository (E7-S1 Branches view)")
def list_all_branches(
    branch_filter: BranchFilter = Query(default="all", alias="filter"),
    search: str | None = Query(default=None),
    services: Services = Depends(get_services),
) -> dict[str, Any]:
    items = services.store.all_branches(branch_filter=branch_filter, search=search)
    return {
        "items": items,
        "count": len(items),
        "filters": {"filter": branch_filter, "search": search},
        "thresholds": {
            "inactive_days": services.settings.inactive_branch_days,
            "stale_days": services.settings.stale_branch_days,
        },
    }
