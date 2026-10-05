"""End-to-end pipeline tests (E11-S2).

Git repository -> discovery -> collector -> SQLite -> analyzer -> API.
"""

from __future__ import annotations

import time
from pathlib import Path

from app.analyzers.health import dashboard_insights
from app.analyzers.metrics import activity_metrics, repository_metrics
from tests import helpers
from tests.conftest import requires_git

pytestmark = requires_git


def test_full_pipeline_from_disk_to_database(scanner, repositories, store, repo_factory, tmp_path: Path) -> None:
    """Discover repositories on disk, register them, scan and query the results."""
    repo_factory("pipeline-one", commits=5)
    repo_factory("nested/pipeline-two", commits=3)

    discovery = repositories.discover(register=True)
    assert discovery["count"] == 2
    assert discovery["registered_count"] == 2
    assert store.count_repositories() == 2

    report = scanner.scan_all(incremental=True, discover=False)
    assert report.failed == 0
    assert report.scanned == 2
    assert report.commits_added == 8
    assert report.status == "completed"

    for repository in store.list_repositories():
        assert repository["last_scanned_at"]
        assert repository["state"] in {"clean", "dirty", "detached", "empty", "bare"}
        assert repository["health_grade"] in "ABCDEF"
        assert repository["staleness"] in {"active", "inactive", "stale", "abandoned", "empty", "unknown"}
        assert repository["branch_count"] >= 1
        assert repository["tracked_files"] >= 1

    one = store.get_repository_by_path(str((tmp_path / "repos" / "pipeline-one").resolve()).lower()) or store.query_one(
        "SELECT * FROM repositories WHERE name = ?", ("pipeline-one",)
    )
    metrics = repository_metrics(store, one["id"])
    assert metrics["total_commits"] == 5
    assert metrics["contributors"] >= 1
    activity = activity_metrics(store, one["id"])
    assert activity["commits"]["all_time"] == 5
    assert store.list_branches(one["id"])[0]["name"] == "main"
    assert store.list_contributors(one["id"])


def test_rescanning_is_idempotent(scanner, repositories, store, repo_factory) -> None:
    """Running the scanner twice must not duplicate any record (E4-S3)."""
    repo_factory("idempotent", commits=6)
    repositories.discover(register=True)
    scanner.scan_all(incremental=True)

    first_counts = {
        table: store.query(f"SELECT COUNT(*) AS total FROM {table}")[0]["total"]
        for table in ("repositories", "branches", "commits", "contributors", "file_changes")
    }

    second = scanner.scan_all(incremental=True)
    assert second.commits_added == 0

    third = scanner.scan_all(incremental=False)  # full re-walk, still no duplicates
    assert third.commits_added == 0

    second_counts = {
        table: store.query(f"SELECT COUNT(*) AS total FROM {table}")[0]["total"]
        for table in ("repositories", "branches", "commits", "contributors", "file_changes")
    }
    assert first_counts == second_counts
    assert store.query("SELECT COUNT(*) AS total FROM commits WHERE repository_id = 1")[0]["total"] == 6


def test_scan_picks_up_new_commits_and_branches(scanner, repositories, store, repo_factory) -> None:
    repo = repo_factory("growing", commits=3)
    repositories.discover(register=True)
    scanner.scan_all(incremental=True)
    repository_id = store.list_repositories()[0]["id"]

    helpers.commit(repo, "new feature work", files={"src/feature.py": "value = 42\n"})
    helpers.add_branch(repo, "feature/new", days_ago=0)

    outcome = scanner.scan_repository(repository_id, incremental=True)
    assert outcome.status in {"completed", "partial"}
    assert outcome.commits_added == 2  # the commit itself plus the branch commit
    assert outcome.incremental is True
    assert outcome.branches >= 2
    # 3 original + 1 new commit on main + 1 commit on the new branch
    assert store.get_repository(repository_id)["total_commits"] == 5


def test_one_broken_repository_does_not_stop_the_scan(
    scanner, repositories, store, repo_factory, tmp_path: Path
) -> None:
    """E9-S2 acceptance criteria: a single failure must not abort the whole scan."""
    repo_factory("good-one", commits=2)
    broken = repo_factory("broken", commits=2)
    repo_factory("good-two", commits=2)

    repositories.discover(register=True)
    # Simulate a repository that disappears between discovery and scanning.
    import shutil

    shutil.rmtree(broken)

    report = scanner.scan_all(incremental=True)
    outcomes = {outcome.name: outcome for outcome in report.outcomes}
    assert report.scanned == 2
    assert report.failed == 1
    assert report.status == "partial"
    assert outcomes["broken"].status == "failed"
    assert "unavailable" in (outcomes["broken"].error or "").lower()
    assert outcomes["good-one"].commits_added == 2
    assert outcomes["good-two"].commits_added == 2
    assert store.get_repository(outcomes["broken"].repository_id)["state"] == "error"

    # The failure is recorded for debugging (E4-S4) and can be fixed by a later scan.
    repository = store.query_one("SELECT * FROM repositories WHERE name = 'broken'")
    assert repository["last_error"]
    runs = store.list_scan_runs(repository_id=repository["id"])
    assert runs[0]["status"] == "failed" and runs[0]["error"]


def test_dashboard_insights_reflect_repository_states(scanner, repositories, store, repo_factory) -> None:
    repo_factory("busy", commits=8, days_ago=1)
    repo_factory("forgotten", commits=3, days_ago=400, commit_span_days=10)
    repositories.discover(register=True)
    scanner.scan_all(incremental=True)

    insights = dashboard_insights(store, limit=50)
    messages = " ".join(item["message"] for item in insights)
    assert "No commits detected" in messages
    assert any(item["repository_name"] == "forgotten" for item in insights)
    forgotten = store.query_one("SELECT * FROM repositories WHERE name = 'forgotten'")
    assert forgotten["staleness"] == "abandoned"
    assert forgotten["health_score"] < store.query_one("SELECT * FROM repositories WHERE name = 'busy'")["health_score"]


def test_scan_records_runs_and_reports_status(scanner, repositories, store, repo_factory) -> None:
    repo_factory("observed", commits=2)
    repositories.discover(register=True)
    scanner.scan_all(incremental=True)

    aggregate = store.latest_scan_run()
    assert aggregate["repository_id"] is None
    assert aggregate["status"] == "completed"
    assert aggregate["repositories_scanned"] == 1
    assert aggregate["completed_at"] and aggregate["duration_ms"] is not None

    per_repo = store.list_scan_runs(repository_id=store.list_repositories()[0]["id"])
    assert per_repo and per_repo[0]["records_processed"] > 0


def test_scan_service_health_is_cached_on_the_row(scanner, repositories, store, repo_factory) -> None:
    repo_factory("cached-health", commits=6, days_ago=1)
    repositories.discover(register=True)
    scanner.scan_all(incremental=True)
    repository = store.list_repositories()[0]
    assert 0 < repository["health_score"] <= 100
    assert repository["health_grade"] in "ABCDEF"
    assert repository["staleness"] == "active"


def test_deleting_a_repository_removes_all_related_rows(scanner, repositories, store, repo_factory) -> None:
    repo_factory("disposable", commits=4)
    repositories.discover(register=True)
    scanner.scan_all(incremental=True)
    repository_id = store.list_repositories()[0]["id"]

    repositories.remove(repository_id)
    assert store.count_repositories() == 0
    for table in ("branches", "commits", "contributors", "file_changes"):
        assert (
            store.query(f"SELECT COUNT(*) AS total FROM {table} WHERE repository_id = ?", (repository_id,))[0]["total"]
            == 0
        )


def test_api_reflects_a_complete_workflow(client, repo_factory, tmp_path: Path) -> None:
    """The MVP definition of done, exercised through the HTTP API."""
    repo = repo_factory("workflow", commits=5, author_rotation=True)

    # 1. discover + register
    discovery = client.post(
        "/api/repositories/discover", json={"root": str(tmp_path / "repos"), "register": True}
    ).json()
    assert discovery["registered_count"] == 1
    repository = client.get("/api/repositories").json()["items"][0]

    # 2. scan (synchronous job so the test is deterministic)
    client.post(f"/api/repositories/{repository['id']}/scan", json={"incremental": True, "background": False})
    deadline = time.time() + 60
    while time.time() < deadline:
        if not client.get("/api/scan/status").json()["running"]:
            break
        time.sleep(0.05)

    # 3. dashboard shows the repository
    dashboard = client.get("/api/dashboard?days=90").json()
    assert dashboard["cards"]["repositories"] == 1
    assert dashboard["cards"]["commits"] == 5
    assert dashboard["cards"]["contributors"] == 3

    # 4. detail, commits, branches, contributors, activity, health
    detail = client.get(f"/api/repositories/{repository['id']}").json()
    assert detail["health"]["signals"]
    commits = client.get(f"/api/repositories/{repository['id']}/commits").json()["items"]
    assert len(commits) == 5
    commit_detail = client.get(f"/api/repositories/{repository['id']}/commits/{commits[0]['sha']}").json()
    assert commit_detail["files"]
    assert client.get(f"/api/repositories/{repository['id']}/branches").json()["items"]
    assert client.get(f"/api/repositories/{repository['id']}/contributors").json()["items"]
    assert client.get(f"/api/repositories/{repository['id']}/activity?days=30").json()["series"]

    # 5. refresh updates the data
    helpers.commit(repo, "follow-up commit", files={"src/follow_up.py": "x = 2\n"})
    client.post(f"/api/repositories/{repository['id']}/scan", json={"incremental": True, "background": False})
    deadline = time.time() + 60
    while time.time() < deadline:
        if not client.get("/api/scan/status").json()["running"]:
            break
        time.sleep(0.05)
    assert client.get("/api/dashboard?days=90").json()["cards"]["commits"] == 6
    assert client.get(f"/api/repositories/{repository['id']}/commits").json()["pagination"]["total"] == 6
