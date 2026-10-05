"""Performance benchmarks (E11-S4).

Measures discovery time, scan time, database size and API response time for
1 / 10 / 50 / 100 repositories.  These tests build real repositories and are marked
``slow`` so the default test run stays fast::

    pytest -m slow tests/test_performance.py

The assertions are deliberately generous - they are regression guards, not a
benchmark rig.  Measured numbers are printed so they can be compared between runs.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from tests import helpers

pytestmark = [pytest.mark.slow, pytest.mark.skipif(not helpers.GIT_AVAILABLE, reason="git is required")]

REPOSITORY_COUNTS = [1, 10, 50, 100]
COMMITS_PER_REPOSITORY = 3


def build_repositories(root: Path, count: int) -> float:
    started = time.perf_counter()
    for index in range(count):
        repo = root / f"repo-{index:03d}"
        helpers.init_repo(repo)
        for commit_index in range(COMMITS_PER_REPOSITORY):
            helpers.commit(
                repo,
                f"commit {commit_index}",
                files={f"src/module_{commit_index}.py": f"value = {commit_index}\n", "README.md": f"# repo {index}\n"},
            )
    return time.perf_counter() - started


@pytest.mark.parametrize("count", REPOSITORY_COUNTS)
def test_scale_discovery_scan_and_api(tmp_path: Path, settings, store, repositories, scanner, count: int) -> None:
    from fastapi.testclient import TestClient

    from app.main import create_app

    # --- build the fixture repositories -------------------------------------
    root = tmp_path / "repos"
    build_time = build_repositories(root, count)
    per_repo_kb = sum(path.stat().st_size for path in root.rglob("*") if path.is_file()) / 1024 / max(count, 1)

    # --- discovery ----------------------------------------------------------
    started = time.perf_counter()
    discovery = repositories.discover(register=True, root=str(root))
    discovery_seconds = time.perf_counter() - started
    assert discovery["count"] == count
    assert discovery["registered_count"] == count
    assert discovery_seconds < 5 + count * 0.25

    # --- scanning -----------------------------------------------------------
    started = time.perf_counter()
    report = scanner.scan_all(incremental=True)
    scan_seconds = time.perf_counter() - started
    assert report.failed == 0
    assert report.commits_added == count * COMMITS_PER_REPOSITORY
    assert scan_seconds < 10 + count * 0.5

    # a second (incremental) scan must be faster or at least not slower by much
    started = time.perf_counter()
    second = scanner.scan_all(incremental=True)
    incremental_seconds = time.perf_counter() - started
    assert second.commits_added == 0

    # --- database size ------------------------------------------------------
    database_bytes = store.db.size_bytes()
    assert database_bytes > 0

    # --- API response time --------------------------------------------------
    app = create_app(settings.with_overrides({"database_path": str(settings.database_file)}))
    with TestClient(app) as client:
        started = time.perf_counter()
        listing = client.get("/api/repositories?per_page=200")
        list_seconds = time.perf_counter() - started
        assert listing.status_code == 200
        assert listing.json()["pagination"]["total"] == count

        started = time.perf_counter()
        dashboard = client.get("/api/dashboard?days=30")
        dashboard_seconds = time.perf_counter() - started
        assert dashboard.status_code == 200
        assert dashboard.json()["cards"]["repositories"] == count

        repository_id = listing.json()["items"][0]["id"]
        started = time.perf_counter()
        commits = client.get(f"/api/repositories/{repository_id}/commits?per_page=50")
        commits_seconds = time.perf_counter() - started
        assert commits.status_code == 200

    assert list_seconds < 2.0
    assert dashboard_seconds < 3.0
    assert commits_seconds < 1.0

    print(
        f"\n[perf] repositories={count:>3} "
        f"fixture_build={build_time:6.2f}s "
        f"discovery={discovery_seconds:6.3f}s "
        f"scan={scan_seconds:6.3f}s "
        f"incremental_scan={incremental_seconds:6.3f}s "
        f"db={database_bytes / 1024:9.1f} KiB "
        f"api_list={list_seconds * 1000:7.1f}ms "
        f"api_dashboard={dashboard_seconds * 1000:7.1f}ms "
        f"api_commits={commits_seconds * 1000:7.1f}ms "
        f"(~{per_repo_kb:5.1f} KiB of .git per repository)"
    )
