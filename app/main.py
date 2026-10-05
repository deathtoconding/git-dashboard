"""FastAPI application factory (E6-S1, E12-S1).

``python -m app start`` (or ``git-dashboard start`` once installed) boots this app
and serves both the JSON API and the static dashboard - a single local process with
no build step and no external service.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .api.router import api_router
from .collectors.collector import GitCollector
from .collectors.git_runner import GitRunner
from .config import PROJECT_ROOT, Settings, load_settings  # noqa: F401 - PROJECT_ROOT is re-exported
from .database.connection import Database, DatabaseError
from .database.store import Store
from .logging_config import configure_logging, get_logger
from .services.scan_manager import ScanManager
from .services.scan_service import ScanService

log = get_logger("main")

FRONTEND_DIR = PROJECT_ROOT / "frontend"
ASSETS_DIR = FRONTEND_DIR / "assets"


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the FastAPI application with all services wired to SQLite."""
    settings = settings or load_settings()
    configure_logging(settings.log_level, log_file=settings.data_dir / "logs" / "dashboard.log")

    database = Database(settings.database_file)
    try:
        database.migrate()
    except DatabaseError as exc:
        log.error("database initialisation failed: %s", exc)
        raise

    store = Store(database)
    collector = GitCollector(GitRunner(binary=settings.git_binary, timeout=settings.git_timeout_seconds), history_depth=settings.history_depth)
    scan_manager = ScanManager(ScanService(store, settings, collector=collector))
    refresh_task: asyncio.Task[Any] | None = None

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        nonlocal refresh_task
        # Probe Git once at startup: the result is cached on the runner, so no
        # request handler ever has to spawn a process (see docs/architecture.md).
        git_available, git_version = await asyncio.to_thread(collector.check_git)
        log.info("dashboard ready on http://%s:%s (database: %s)", settings.host, settings.port, settings.database_file)
        log.info(
            "registered repositories: %d | git: %s",
            store.count_repositories(),
            f"{settings.git_binary} {git_version}" if git_available else f"{settings.git_binary} (NOT AVAILABLE)",
        )
        if settings.refresh_interval_minutes > 0:
            refresh_task = asyncio.create_task(_auto_refresh(app, settings.refresh_interval_minutes))
            log.info("background refresh every %s minute(s) enabled", settings.refresh_interval_minutes)
        try:
            yield
        finally:
            if refresh_task:
                refresh_task.cancel()
                with contextlib.suppress(Exception):
                    await refresh_task
            log.info("dashboard stopped")

    app = FastAPI(
        title="Local Git Repository Dashboard",
        description=(
            "Self-sufficient dashboard for local Git repositories. "
            "Discovers repositories, reads Git metadata through the Git CLI, stores it in SQLite "
            "and presents health, activity and branch hygiene in a local web UI. "
            "No GitHub API, no cloud database, no paid SaaS."
        ),
        version=__version__,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.store = store
    app.state.database = database
    app.state.collector = collector
    app.state.scan_manager = scan_manager

    # The UI is served from the same origin; CORS stays permissive so a user can
    # open the dashboard from a file:// page or a different local port if they want.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router)

    @app.get("/health", include_in_schema=False)
    def health_alias(request: Request) -> JSONResponse:
        """Root-level alias for ``GET /api/health`` (E6-S1)."""
        from .api.deps import build_services
        from .api.routes.system import health

        payload = health(request=request, services=build_services(request.app))
        return JSONResponse(payload)

    if ASSETS_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(ASSETS_DIR)), name="static")

    @app.get("/", include_in_schema=False)
    def index() -> Any:
        return _serve_index()

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_fallback(full_path: str) -> Any:
        """Serve the dashboard for client-side routes, but never for API paths."""
        if full_path.startswith(("api/", "static/")):
            raise HTTPException(status_code=404, detail="Not found")
        return _serve_index()

    return app


def _serve_index() -> Any:
    index_file = FRONTEND_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file, media_type="text/html", headers={"Cache-Control": "no-store"})
    return JSONResponse(
        {
            "detail": "The frontend directory is missing.",
            "hint": "Run the dashboard from a full checkout, or use the JSON API under /api.",
            "docs": "/docs",
        },
        status_code=500,
    )


async def _auto_refresh(app: FastAPI, interval_minutes: int) -> None:
    """Optional periodic refresh (disabled unless refresh_interval_minutes > 0)."""
    interval = max(60, interval_minutes * 60)
    while True:
        await asyncio.sleep(interval)
        manager: ScanManager = app.state.scan_manager
        if manager.busy:
            log.info("auto refresh skipped: a scan is already running")
            continue
        try:
            manager.start_full_scan(incremental=True, discover=False, background=True)
            log.info("auto refresh started a full scan")
        except Exception as exc:  # noqa: BLE001 - background task must never die
            log.warning("auto refresh failed to start: %s", exc)


__all__ = ["ASSETS_DIR", "FRONTEND_DIR", "create_app"]

# Usage:
#   python -m app start                     (recommended, see app/__main__.py)
#   uvicorn app.main:create_app --factory   (equivalent, for deployment tooling)
