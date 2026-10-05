"""Shared pytest fixtures."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.collectors.collector import GitCollector  # noqa: E402
from app.collectors.git_runner import GitRunner  # noqa: E402
from app.config import Settings, load_settings  # noqa: E402
from app.database.connection import Database  # noqa: E402
from app.database.store import Store  # noqa: E402
from app.services.repository_service import RepositoryService  # noqa: E402
from app.services.scan_service import ScanService  # noqa: E402
from tests import helpers  # noqa: E402

requires_git = pytest.mark.skipif(not helpers.GIT_AVAILABLE, reason="git executable is required for this test")


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Isolated settings: private database, private repository roots, no config file."""
    return load_settings(
        config_path=tmp_path / "config.json",
        environ={},
        overrides={
            "database_path": str(tmp_path / "data" / "dashboard.db"),
            "repository_roots": [str(tmp_path / "repos")],
            "log_level": "WARNING",
        },
    )


@pytest.fixture
def database(settings: Settings) -> Database:
    db = Database(settings.database_file)
    db.migrate()
    return db


@pytest.fixture
def store(database: Database) -> Store:
    return Store(database)


@pytest.fixture
def runner(settings: Settings) -> GitRunner:
    return GitRunner(binary=settings.git_binary, timeout=settings.git_timeout_seconds)


@pytest.fixture
def collector(settings: Settings, runner: GitRunner) -> GitCollector:
    return GitCollector(runner, history_depth=settings.history_depth)


@pytest.fixture
def repositories(store: Store, settings: Settings) -> RepositoryService:
    return RepositoryService(store, settings)


@pytest.fixture
def scanner(store: Store, settings: Settings, collector: GitCollector) -> ScanService:
    return ScanService(store, settings, collector=collector)


@pytest.fixture
def repo_factory(tmp_path: Path):
    """Return a factory that creates real Git repositories under ``tmp_path/repos``."""
    counter = {"value": 0}

    def factory(name: str | None = None, **kwargs) -> Path:
        counter["value"] += 1
        target = tmp_path / "repos" / (name or f"repo-{counter['value']}")
        return helpers.make_repo(target, **kwargs)

    return factory


@pytest.fixture
def client(settings: Settings, monkeypatch: pytest.MonkeyPatch):
    """A FastAPI test client bound to an isolated database and settings."""
    from fastapi.testclient import TestClient

    from app.main import create_app

    app = create_app(settings)
    with TestClient(app) as test_client:
        test_client.app_state = app.state  # convenient access for assertions
        yield test_client
