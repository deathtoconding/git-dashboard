"""API tests for every documented endpoint (E6)."""

from __future__ import annotations

import csv
import io
import json
import time
from pathlib import Path

import pytest

from tests import helpers
from tests.conftest import requires_git


def register(client, path: Path, name: str | None = None) -> dict:
    payload = {"path": str(path)}
    if name:
        payload["name"] = name
    response = client.post("/api/repositories", json=payload)
    assert response.status_code == 201, response.text
    return response.json()["repository"]


def scan(client, repository_id: int, repositories, incremental: bool = True, timeout: float = 120) -> dict:
    """Trigger a synchronous scan through the API job queue and wait for it."""
    response = client.post(
        f"/api/repositories/{repository_id}/scan",
        json={"incremental": incremental, "background": False},
    )
    assert response.status_code == 202, response.text
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = client.get("/api/scan/status").json()
        if not status["running"]:
            return status["job"]
        time.sleep(0.05)
    raise AssertionError("scan did not finish in time")


# ------------------------------------------------------------------- E6-S1 health
def test_health_endpoint(client) -> None:
    body = client.get("/api/health").json()
    assert body["status"] in {"ok", "degraded"}
    assert body["version"]
    assert "database" in body and body["database"]["schema_version"] == 1
    assert isinstance(body["git_available"], bool)
    assert client.get("/health").json()["status"] == body["status"]
    assert client.get("/api/version").json()["version"] == body["version"]


def test_unknown_api_path_returns_404(client) -> None:
    assert client.get("/api/definitely-not-here").status_code == 404


def test_frontend_is_served(client) -> None:
    index = client.get("/")
    assert index.status_code == 200
    assert "Git Dashboard" in index.text
    assert client.get("/static/styles.css").status_code == 200
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/repositories/42").status_code == 200  # SPA fallback


# ----------------------------------------------------------- E6-S2 repositories
@requires_git
def test_repository_crud_flow(client, repo_factory) -> None:
    repo = repo_factory("crud", commits=3)
    repository = register(client, repo, name="custom name")
    assert repository["name"] == "custom name"
    assert repository["state"] == "unknown"
    assert repository["is_scanned"] is False

    listing = client.get("/api/repositories").json()
    assert listing["pagination"]["total"] == 1
    assert listing["items"][0]["id"] == repository["id"]

    detail = client.get(f"/api/repositories/{repository['id']}").json()
    assert detail["repository"]["path"] == str(repo.resolve())
    assert detail["health"]["score"] == pytest.approx(0, abs=100)
    assert detail["working_tree"]["is_bare"] is False

    deleted = client.delete(f"/api/repositories/{repository['id']}").json()
    assert deleted["deleted"] is True
    assert client.get(f"/api/repositories/{repository['id']}").status_code == 404
    assert client.get("/api/repositories").json()["pagination"]["total"] == 0


def test_register_invalid_paths(client, tmp_path: Path) -> None:
    missing = client.post("/api/repositories", json={"path": str(tmp_path / "nope")})
    assert missing.status_code == 400 and "does not exist" in missing.json()["detail"]

    plain = tmp_path / "plain"
    plain.mkdir()
    not_a_repo = client.post("/api/repositories", json={"path": str(plain)})
    assert not_a_repo.status_code == 400 and "No Git repository" in not_a_repo.json()["detail"]


@requires_git
def test_duplicate_registration_is_rejected(client, repo_factory) -> None:
    repo = repo_factory("dupe", commits=1)
    register(client, repo)
    again = client.post("/api/repositories", json={"path": str(repo)})
    assert again.status_code == 400
    assert "already registered" in again.json()["detail"].lower()


@requires_git
def test_bulk_registration_skips_existing(client, repo_factory) -> None:
    first = repo_factory("bulk-a", commits=1)
    second = repo_factory("bulk-b", commits=1)
    response = client.post("/api/repositories/bulk", json={"paths": [str(first), str(second), str(first)]})
    assert response.status_code == 201
    body = response.json()
    assert body["added_count"] == 2
    assert len(body["skipped"]) == 1


@requires_git
def test_discovery_endpoints(client, repo_factory, tmp_path: Path) -> None:
    repo_factory("nested/child", commits=1)
    root = tmp_path / "repos"

    discovered = client.post("/api/repositories/discover", json={"root": str(root), "register": True}).json()
    assert discovered["count"] == 1
    assert discovered["registered_count"] == 1

    suggestions = client.get("/api/repositories/suggestions").json()
    assert suggestions["count"] == 0  # everything is registered now

    discovered = client.post("/api/repositories/discover", json={"root": str(root), "register": False}).json()
    assert discovered["roots"][0]["repositories"][0]["already_registered"] is True


def test_discovery_of_a_missing_root_reports_errors(client, tmp_path: Path) -> None:
    body = client.post("/api/repositories/discover", json={"root": str(tmp_path / "missing")}).json()
    assert body["count"] == 0
    assert body["errors"] and "not an existing directory" in body["errors"][0]


def test_discovery_without_any_root_reports_clearly(repositories) -> None:
    """With no roots configured and no explicit root the API answers with a clear 400."""
    from app.services.repository_service import RepositoryError

    repositories.settings = repositories.settings.with_overrides({"repository_roots": []})
    with pytest.raises(RepositoryError, match="No repository roots configured"):
        repositories.discover()


@requires_git
def test_repository_listing_filters_and_pagination(client, repo_factory, scanner) -> None:
    for index in range(3):
        register(client, repo_factory(f"filter-{index}", commits=2))
    listing = client.get("/api/repositories?per_page=2&page=1&sort=name&order=asc").json()
    assert listing["pagination"]["total"] == 3
    assert listing["pagination"]["pages"] == 2
    assert len(listing["items"]) == 2

    filtered = client.get("/api/repositories?search=filter-1").json()
    assert filtered["pagination"]["total"] == 1

    unknown_status = client.get("/api/repositories?status=bogus")
    assert unknown_status.status_code == 422  # validated query parameter


@requires_git
def test_scan_then_read_endpoints(client, repo_factory) -> None:
    repo = repo_factory("scanned", commits=6, author_rotation=True)
    repository = register(client, repo)
    job = scan(client, repository["id"], None)
    assert job["status"] in {"completed", "partial"}
    assert job["report"]["repositories"][0]["commits_added"] == 6

    detail = client.get(f"/api/repositories/{repository['id']}").json()
    assert detail["repository"]["total_commits"] == 6
    assert detail["repository"]["current_branch"] == "main"
    assert detail["repository"]["is_scanned"] is True
    assert detail["health"]["score"] > 0
    assert detail["branches"] and detail["contributors"] and detail["recent_commits"]

    metrics = client.get(f"/api/repositories/{repository['id']}/metrics").json()
    assert metrics["metrics"]["total_commits"] == 6
    assert metrics["changes"]["lines_added"] > 0

    activity = client.get(f"/api/repositories/{repository['id']}/activity?days=90").json()
    assert activity["metrics"]["commits"]["all_time"] == 6
    assert len(activity["series"]) == 90

    contributors = client.get(f"/api/repositories/{repository['id']}/contributors").json()
    assert contributors["count"] == 3
    assert contributors["items"][0]["share"] > 0

    heatmap = client.get(f"/api/repositories/{repository['id']}/heatmap?days=365").json()
    assert len(heatmap["grid"]) == 7
    churn = client.get(f"/api/repositories/{repository['id']}/file-churn").json()
    assert churn["items"]


@requires_git
def test_commit_endpoints(client, repo_factory) -> None:
    repo = repo_factory("commit-api", commits=5)
    repository = register(client, repo)
    scan(client, repository["id"], None)

    commits = client.get(f"/api/repositories/{repository['id']}/commits?per_page=2").json()
    assert commits["pagination"] == {"total": 5, "page": 1, "per_page": 2, "pages": 3}
    sha = commits["items"][0]["sha"]

    detail = client.get(f"/api/repositories/{repository['id']}/commits/{sha}").json()
    assert detail["commit"]["sha"] == sha
    assert detail["file_count"] >= 1
    assert all({"path", "change_type", "additions", "deletions"} <= set(file) for file in detail["files"])

    short = client.get(f"/api/repositories/{repository['id']}/commits/{sha[:8]}").json()
    assert short["commit"]["sha"] == sha

    assert client.get(f"/api/repositories/{repository['id']}/commits/{'z' * 40}").status_code == 404
    filtered = client.get(f"/api/repositories/{repository['id']}/commits?search=commit%201").json()
    assert filtered["pagination"]["total"] >= 1
    dated = client.get(f"/api/repositories/{repository['id']}/commits?since=2000-01-01&until=2999-12-31").json()
    assert dated["pagination"]["total"] == 5
    empty = client.get(f"/api/repositories/{repository['id']}/commits?since=2999-01-01").json()
    assert empty["pagination"]["total"] == 0


@requires_git
def test_branch_endpoints_with_filters(client, repo_factory) -> None:
    repo = repo_factory("branch-api", commits=4)
    helpers.add_branch(repo, "feature/stale", days_ago=200)
    helpers.add_branch(repo, "feature/fresh", days_ago=2)
    repository = register(client, repo)
    scan(client, repository["id"], None)

    all_branches = client.get(f"/api/repositories/{repository['id']}/branches").json()
    assert all_branches["summary"]["local_branches"] == 3
    assert all_branches["summary"]["stale_branches"] == 1

    stale = client.get(f"/api/repositories/{repository['id']}/branches?filter=stale").json()
    assert [branch["name"] for branch in stale["items"]] == ["feature/stale"]

    current = client.get(f"/api/repositories/{repository['id']}/branches?filter=current").json()
    assert [branch["name"] for branch in current["items"]] == ["main"]

    searched = client.get(f"/api/repositories/{repository['id']}/branches?search=fresh").json()
    assert len(searched["items"]) == 1

    global_view = client.get("/api/branches?filter=stale").json()
    assert global_view["count"] == 1
    assert global_view["items"][0]["repository_name"] == repository["name"]


# ------------------------------------------------------ E6-S5 analytics & dashboard
@requires_git
def test_dashboard_and_insights_endpoints(client, repo_factory) -> None:
    active = register(client, repo_factory("active-repo", commits=6))
    stale = register(client, repo_factory("stale-repo", commits=2, days_ago=200, commit_span_days=10))
    scan(client, active["id"], None)
    scan(client, stale["id"], None)

    dashboard = client.get("/api/dashboard?days=30").json()
    assert dashboard["cards"]["repositories"] == 2
    assert dashboard["cards"]["commits"] >= 8
    assert len(dashboard["activity"]["series"]) == 30
    assert dashboard["repositories"] and dashboard["recent_repositories"]
    assert dashboard["insights"]

    insights = client.get("/api/insights").json()
    assert insights["counts"]["error"] >= 1  # the stale repository
    assert any(item["repository_name"] == "stale-repo" for item in insights["items"])

    activity = client.get("/api/activity?days=14&bucket=week").json()
    assert all(len(point["bucket"]) == 10 for point in activity["series"])

    by_repo = client.get("/api/activity/repositories?days=30").json()
    assert by_repo["count"] == 2

    compare = client.get(f"/api/repositories/compare?ids={active['id']},{stale['id']}").json()
    assert compare["items"][0]["health_score"] > compare["items"][1]["health_score"]
    assert client.get("/api/repositories/compare?ids=abc").status_code == 400


@requires_git
def test_repository_status_endpoint(client, repo_factory) -> None:
    repo = repo_factory("status-repo", commits=2, dirty=True, untracked=2)
    repository = register(client, repo)
    scan(client, repository["id"], None)
    status = client.get(f"/api/repositories/{repository['id']}/status").json()
    assert status["state"] == "dirty"
    assert status["working_tree"]["untracked_files"] == 2
    assert status["warnings"]
    assert status["scan_runs"]


# ------------------------------------------------------------------ E9 scan API
@requires_git
def test_scan_all_endpoint_and_history(client, repo_factory) -> None:
    register(client, repo_factory("scan-all-a", commits=2))
    register(client, repo_factory("scan-all-b", commits=3))
    response = client.post("/api/scan/all", json={"incremental": True, "discover": False, "background": False})
    assert response.status_code == 202
    deadline = time.time() + 60
    while time.time() < deadline:
        status = client.get("/api/scan/status").json()
        if not status["running"]:
            break
        time.sleep(0.05)
    job = status["job"]
    assert job["status"] in {"completed", "partial"}
    assert job["progress"]["done"] == 2
    assert job["report"]["scanned"] == 2

    history = client.get("/api/scan/history?limit=5").json()["items"]
    assert any(row["repository_id"] is None for row in history)  # aggregate run recorded
    assert client.get("/api/scan/jobs").json()["items"]


@requires_git
def test_incremental_scan_through_api_adds_only_new_commits(client, repo_factory) -> None:
    repo = repo_factory("incremental-api", commits=4)
    repository = register(client, repo)
    first = scan(client, repository["id"], None)
    assert first["report"]["repositories"][0]["commits_added"] == 4

    second = scan(client, repository["id"], None)
    assert second["report"]["repositories"][0]["commits_added"] == 0

    helpers.commit(repo, "a brand new commit", files={"src/extra.py": "x = 1\n"})
    third = scan(client, repository["id"], None)
    assert third["report"]["repositories"][0]["commits_added"] == 1
    assert third["report"]["repositories"][0]["incremental"] is True

    full = scan(client, repository["id"], None, incremental=False)
    assert full["report"]["repositories"][0]["commits_added"] == 0  # still no duplicates


def test_scan_unknown_repository_is_404(client) -> None:
    assert client.post("/api/repositories/999/scan", json={}).status_code == 404


# ------------------------------------------------------------------ E1 settings API
def test_settings_read_and_update(client, tmp_path: Path) -> None:
    body = client.get("/api/settings").json()
    assert body["settings"]["database_path"]
    assert body["paths"]["database_file"]
    assert body["thresholds"]["stale_branch_days"] > 0

    response = client.put("/api/settings", json={"stale_branch_days": 45, "history_depth": 250})
    assert response.status_code == 200
    assert response.json()["saved"] is True
    assert set(response.json()["changed"]) == {"stale_branch_days", "history_depth"}

    reloaded = client.get("/api/settings").json()
    assert reloaded["settings"]["stale_branch_days"] == 45
    assert reloaded["settings"]["history_depth"] == 250


def test_settings_validation_errors_are_clear(client) -> None:
    response = client.put("/api/settings", json={"stale_branch_days": 5, "inactive_branch_days": 30})
    assert response.status_code == 400
    assert "stale_branch_days" in response.json()["detail"]

    empty = client.put("/api/settings", json={})
    assert empty.status_code == 400

    invalid_port = client.put("/api/settings", json={"port": 99999})
    assert invalid_port.status_code == 422


def test_repository_roots_endpoint(client) -> None:
    roots = client.get("/api/settings/roots").json()["roots"]
    assert roots and all({"value", "path", "exists"} <= set(root) for root in roots)


# ------------------------------------------------------------------ E12-S4 exports
@requires_git
def test_export_endpoints(client, repo_factory) -> None:
    repository = register(client, repo_factory("export-repo", commits=3))
    scan(client, repository["id"], None)

    snapshot = client.get("/api/export/json").json()
    assert snapshot["repositories"][0]["repository"]["name"] == "export-repo"
    assert snapshot["repositories"][0]["health"]["signals"]

    download = client.get("/api/export/json?download=true")
    assert download.headers["content-disposition"].startswith("attachment")

    csv_response = client.get("/api/export/csv/commits")
    assert csv_response.status_code == 200
    rows = list(csv.DictReader(io.StringIO(csv_response.text)))
    assert len(rows) == 3 and "sha" in rows[0]

    assert client.get("/api/export/csv/nonsense").status_code == 400

    backup = client.post("/api/export/backup").json()
    assert Path(backup["backup"]).exists()
    snapshot_file = client.post("/api/export/snapshot").json()
    assert json.loads(Path(snapshot_file["snapshot"]).read_text())["summary"]["repositories"] == 1


# ---------------------------------------------------------------------- API docs
def test_openapi_schema_is_valid(client) -> None:
    schema = client.get("/openapi.json").json()
    assert schema["info"]["title"] == "Local Git Repository Dashboard"
    paths = schema["paths"]
    for expected in ("/api/health", "/api/repositories", "/api/branches", "/api/scan/status", "/api/settings"):
        assert expected in paths


# ------------------------------------------------------------------- startup
def test_startup_reports_the_git_version(settings, caplog) -> None:
    """The server probes Git once at boot so no request has to spawn a process."""
    from fastapi.testclient import TestClient

    from app.main import create_app

    with caplog.at_level("INFO", logger="app.main"):
        with TestClient(create_app(settings)) as client:
            assert client.get("/api/health").status_code == 200
    messages = [record.getMessage() for record in caplog.records if record.name == "app.main"]
    assert any("| git: git" in message for message in messages), messages


# --------------------------------------------------------- architectural rules
def test_request_handlers_never_spawn_processes() -> None:
    """Architecture rule (E1): Git is invoked by collectors, never by a route.

    A request handler that shells out would block the web server on a slow
    repository, so subprocess use is confined to `app/collectors/`.
    """
    import app.api

    api_dir = Path(app.api.__file__).parent
    forbidden = ("import subprocess", "subprocess.", ".run(", "Popen(", "check_output(")
    offenders = [
        f"{path.relative_to(api_dir)}: {needle}"
        for path in sorted(api_dir.rglob("*.py"))
        for needle in forbidden
        if needle in path.read_text(encoding="utf-8")
    ]
    assert offenders == [], f"request handlers must not run processes: {offenders}"
