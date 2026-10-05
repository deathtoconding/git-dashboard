"""FastAPI dependencies: one place that assembles the service container."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import Depends, HTTPException, Request, status

from ..analyzers.health import repository_health
from ..collectors.collector import GitCollector
from ..collectors.git_runner import GitRunner
from ..config import Settings
from ..database.store import Store
from ..services.export_service import ExportService
from ..services.repository_service import RepositoryError, RepositoryService
from ..services.scan_manager import ScanManager
from ..services.scan_service import ScanService


@dataclass
class Services:
    """Per-request view of the application services."""

    settings: Settings
    store: Store
    repositories: RepositoryService
    scan: ScanService
    scan_manager: ScanManager
    export: ExportService
    collector: GitCollector


def build_services(app: Any) -> Services:
    settings: Settings = app.state.settings
    store: Store = app.state.store
    collector: GitCollector = getattr(app.state, "collector", None) or GitCollector(
        GitRunner(binary=settings.git_binary, timeout=settings.git_timeout_seconds),
        history_depth=settings.history_depth,
    )
    # Reuse the same runner (Git availability is cached) but follow settings changes.
    collector.runner.binary = settings.git_binary
    collector.runner.timeout = settings.git_timeout_seconds
    collector.history_depth = settings.history_depth
    app.state.collector = collector
    manager: ScanManager = app.state.scan_manager
    scan_service = ScanService(store, settings, collector=collector)
    manager.service = scan_service  # keep background jobs on the current settings
    return Services(
        settings=settings,
        store=store,
        repositories=RepositoryService(store, settings),
        scan=scan_service,
        scan_manager=manager,
        export=ExportService(store, settings),
        collector=collector,
    )


def get_services(request: Request) -> Services:
    return build_services(request.app)


def get_repository(repository_id: int, services: Services = Depends(get_services)) -> dict[str, Any]:
    """Resolve ``{repository_id}`` or raise a 404 with a helpful message."""
    try:
        return services.repositories.get(repository_id)
    except RepositoryError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


def repository_health_for(services: Services, repository: dict[str, Any]) -> dict[str, Any]:
    return repository_health(services.store, repository, settings=services.settings)
