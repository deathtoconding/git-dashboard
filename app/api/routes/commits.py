"""Commit routes (E6-S3): pagination, date filtering, search and file changes."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from ...models.schemas import CommitListResponse
from ..deps import Services, get_repository, get_services

router = APIRouter(tags=["commits"])


@router.get("/repositories/{repository_id}/commits", response_model=CommitListResponse, summary="Commit history")
def list_commits(
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=500),
    since: str | None = Query(default=None, description="ISO date or datetime, inclusive lower bound (author date)"),
    until: str | None = Query(default=None, description="ISO date or datetime, inclusive upper bound (author date)"),
    author: str | None = Query(default=None, description="Filter by author name or email (substring)"),
    search: str | None = Query(default=None, description="Search commit subject or SHA"),
    sha: str | None = Query(default=None, description="Filter by full or short SHA prefix"),
    sort: Literal["date", "author", "changes"] = Query(default="date"),
    order: Literal["asc", "desc"] = Query(default="desc"),
    repository: dict[str, Any] = Depends(get_repository),
    services: Services = Depends(get_services),
) -> dict[str, Any]:
    repository_id = int(repository["id"])
    commits, total = services.store.list_commits(
        repository_id,
        page=page,
        per_page=per_page,
        since=_normalise_bound(since, end=False),
        until=_normalise_bound(until, end=True),
        author=author,
        search=search,
        sha=sha,
        sort=sort,
        order=order,
    )
    return {
        "items": commits,
        "pagination": {
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": max(1, (total + per_page - 1) // per_page),
        },
        "filters": {
            "since": since,
            "until": until,
            "author": author,
            "search": search,
            "sha": sha,
            "sort": sort,
            "order": order,
        },
    }


@router.get("/repositories/{repository_id}/commits/{sha}", summary="A single commit with its changed files (E3-S4)")
def get_commit(
    sha: str,
    repository: dict[str, Any] = Depends(get_repository),
    services: Services = Depends(get_services),
) -> dict[str, Any]:
    repository_id = int(repository["id"])
    commit = services.store.get_commit(repository_id, sha)
    if not commit:
        raise HTTPException(status_code=404, detail=f"Commit {sha} was not found in '{repository['name']}'")
    files = services.store.list_file_changes(repository_id, commit["sha"])
    payload = {
        "commit": commit,
        "files": files,
        "file_count": len(files),
        "additions": commit.get("additions", 0),
        "deletions": commit.get("deletions", 0),
        "repository_id": repository_id,
    }
    if commit.get("is_merge") and not files:
        # `git log --numstat` prints no diff for a merge unless asked, so make the
        # empty file list explicit instead of leaving consumers guessing.
        payload["note"] = (
            "Merge commit: git reports no per-file diff for merges, "
            "so no file statistics are stored for it."
        )
    return payload


def _normalise_bound(value: str | None, *, end: bool) -> str | None:
    """Accept ``2026-01-31`` as well as a full ISO datetime and make it a UTC bound."""
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        return f"{text}T23:59:59Z" if end else f"{text}T00:00:00Z"
    if text.endswith("Z"):
        return text
    if "+" in text[10:] or text.endswith("00:00"):
        return text
    return f"{text}Z"
