"""Pydantic request/response models for the local API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

FilterName = Literal["all", "active", "inactive", "stale", "current", "merged", "remote"]


class RepositoryCreate(BaseModel):
    """Register a single local Git repository (E2-S1)."""

    path: str = Field(..., description="Absolute or ~-relative path of a local Git repository", examples=["/home/me/projects/api"])
    name: str | None = Field(default=None, description="Optional display name (defaults to the directory name)")


class RepositoryBulkCreate(BaseModel):
    paths: list[str] = Field(..., min_length=1, description="Repository paths to register")
    skip_existing: bool = Field(default=True, description="Ignore paths that are already registered")


class DiscoveryRequest(BaseModel):
    """Request body for ``POST /api/repositories/discover``.

    ``register`` is exposed as a JSON alias so the API stays natural while the
    Python attribute avoids shadowing ``BaseModel.register``.
    """

    model_config = ConfigDict(populate_by_name=True)

    root: str | None = Field(default=None, description="Root to scan; defaults to the configured repository roots")
    register_found: bool = Field(
        default=False, alias="register", description="Register every newly discovered repository"
    )
    max_depth: int | None = Field(default=None, ge=1, le=64, description="Override the configured scan depth")


class ScanRequest(BaseModel):
    incremental: bool = Field(default=True, description="Only walk commits that are new since the last scan")
    full_history: bool = Field(default=False, description="Ignore the incremental cursor and re-walk history")
    background: bool = Field(default=True, description="Return immediately and run the scan in a background thread")


class FullScanRequest(BaseModel):
    incremental: bool = Field(default=True)
    discover: bool = Field(default=True, description="Discover and register repositories under the configured roots first")
    root: str | None = Field(default=None, description="Scan a single root instead of every configured root")
    background: bool = Field(default=True)


class SettingsUpdate(BaseModel):
    """Partial settings update; only whitelisted keys are accepted."""

    database_path: str | None = None
    repository_roots: list[str] | None = None
    excluded_dirs: list[str] | None = None
    max_scan_depth: int | None = Field(default=None, ge=1, le=64)
    history_depth: int | None = Field(default=None, ge=1)
    file_changes_per_commit_limit: int | None = Field(default=None, ge=1)
    git_binary: str | None = None
    git_timeout_seconds: int | None = Field(default=None, ge=1)
    stale_branch_days: int | None = Field(default=None, ge=1)
    inactive_branch_days: int | None = Field(default=None, ge=0)
    repo_inactive_days: int | None = Field(default=None, ge=0)
    repo_stale_days: int | None = Field(default=None, ge=1)
    repo_abandoned_days: int | None = Field(default=None, ge=1)
    refresh_interval_minutes: int | None = Field(default=None, ge=0)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] | None = None
    host: str | None = None
    port: int | None = Field(default=None, ge=1, le=65535)


class Pagination(BaseModel):
    total: int
    page: int
    per_page: int
    pages: int


class RepositoryListResponse(BaseModel):
    items: list[dict[str, Any]]
    pagination: Pagination
    filters: dict[str, Any]


class CommitListResponse(BaseModel):
    items: list[dict[str, Any]]
    pagination: Pagination
    filters: dict[str, Any]


class BranchListResponse(BaseModel):
    items: list[dict[str, Any]]
    summary: dict[str, Any] | None = None


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded", "error"]
    version: str
    git_available: bool
    git_version: str | None = None
    git_binary: str
    database: dict[str, Any]
    repositories: int
    scan: dict[str, Any] | None = None
    warnings: list[str] = Field(default_factory=list)
