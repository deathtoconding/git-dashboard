"""Scan routes (E9): manual refresh, full scan, incremental scanning and status."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ...models.schemas import FullScanRequest
from ...services.repository_service import RepositoryError
from ...services.scan_manager import ScanBusyError
from ..deps import Services, get_services

router = APIRouter(tags=["scans"])


@router.get("/scan/status", summary="Scan status for the UI (E9-S4)")
def scan_status(services: Services = Depends(get_services)) -> dict[str, Any]:
    payload = services.scan_manager.status()
    payload["git"] = {"available": services.collector.check_git()[0], "binary": services.settings.git_binary}
    return payload


@router.get("/scan/jobs", summary="Recent background scan jobs")
def scan_jobs(
    limit: int = Query(default=10, ge=1, le=50), services: Services = Depends(get_services)
) -> dict[str, Any]:
    return {"items": services.scan_manager.jobs(limit=limit)}


@router.get("/scan/history", summary="Persisted scan runs (E4-S4)")
def scan_history(
    limit: int = Query(default=20, ge=1, le=200),
    repository_id: int | None = Query(default=None),
    services: Services = Depends(get_services),
) -> dict[str, Any]:
    return {"items": services.store.list_scan_runs(limit=limit, repository_id=repository_id)}


@router.post("/scan/all", status_code=status.HTTP_202_ACCEPTED, summary="Scan every registered repository (E9-S2)")
def scan_all(payload: FullScanRequest | None = None, services: Services = Depends(get_services)) -> dict[str, Any]:
    request_payload = payload or FullScanRequest(discover=False)
    try:
        job = services.scan_manager.start_full_scan(
            incremental=request_payload.incremental,
            discover=request_payload.discover,
            root=request_payload.root,
            background=request_payload.background,
        )
    except ScanBusyError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return {"job": job.to_dict(), "message": "Scanning all repositories…"}


@router.post("/scan/full", status_code=status.HTTP_202_ACCEPTED, summary="Discover, register and scan (full refresh)")
def scan_full(payload: FullScanRequest | None = None, services: Services = Depends(get_services)) -> dict[str, Any]:
    request_payload = payload or FullScanRequest()
    try:
        job = services.scan_manager.start_full_scan(
            incremental=request_payload.incremental,
            discover=request_payload.discover,
            root=request_payload.root,
            background=request_payload.background,
        )
    except ScanBusyError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return {"job": job.to_dict(), "message": "Discovering and scanning repositories…"}


@router.post("/scan/repositories", status_code=status.HTTP_202_ACCEPTED, summary="Scan a list of repositories")
def scan_repositories(
    ids: str = Query(..., description="Comma separated repository ids"),
    incremental: bool = Query(default=True),
    background: bool = Query(default=True),
    services: Services = Depends(get_services),
) -> dict[str, Any]:
    try:
        repository_ids = [int(value) for value in ids.split(",") if value.strip()]
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="ids must be a comma separated list of integers") from exc
    if not repository_ids:
        raise HTTPException(status_code=400, detail="at least one repository id is required")

    repositories = []
    for repository_id in repository_ids:
        try:
            repositories.append(services.repositories.get(repository_id))
        except RepositoryError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    if services.scan_manager.busy:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A scan is already running")
    job = services.scan_manager.start_full_scan(incremental=incremental, discover=False, background=background)
    return {"job": job.to_dict(), "repository_ids": repository_ids}
