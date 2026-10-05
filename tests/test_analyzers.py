"""Analyzer tests: metrics, activity, health score, recommendations (E5, E10)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.analyzers.branch_health import branch_health_summary, classify_branches
from app.analyzers.health import (
    SIGNAL_WEIGHTS,
    dashboard_insights,
    recommendations,
    repository_health,
    repository_staleness,
    working_tree_warnings,
)
from app.analyzers.metrics import (
    activity_metrics,
    activity_series,
    change_metrics,
    contributor_trends,
    heatmap,
    repository_comparison,
    repository_metrics,
    summarize_series,
)

NOW = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)


def seed_repository(
    store, *, name="demo", commits=6, days_since_last=2, uncommitted=0, detached=False, branches=(), health_row=None
):
    repository_id = store.upsert_repository(
        {
            "name": name,
            "path": f"/tmp/{name}",
            "current_branch": "main",
            "head_commit": "h" * 40,
            "total_commits": commits,
            "tracked_files": 12,
            "branch_count": len([b for b in branches if not b.get("is_remote")]) or 1,
            "uncommitted_files": uncommitted,
            "is_dirty": bool(uncommitted),
            "detached_head": detached,
            "last_commit_at": (NOW - timedelta(days=days_since_last)).isoformat().replace("+00:00", "Z"),
            "first_commit_at": (NOW - timedelta(days=400)).isoformat().replace("+00:00", "Z"),
            **(health_row or {}),
        }
    )
    rows = []
    for index in range(commits):
        rows.append(
            {
                "sha": f"{index:040d}",
                "authored_at": (NOW - timedelta(days=days_since_last + index * 3)).isoformat().replace("+00:00", "Z"),
                "author_name": "Ada" if index % 2 == 0 else "Grace",
                "author_email": "ada@example.com" if index % 2 == 0 else "grace@example.com",
                "subject": f"commit {index}",
                "additions": 10,
                "deletions": 4,
                "files_changed": 2,
            }
        )
    store.insert_commits(repository_id, rows)
    for index in range(commits):
        store.replace_file_changes(
            repository_id, f"{index:040d}", [{"path": "src/app.py", "additions": 10, "deletions": 4}]
        )
    store.replace_contributors(repository_id, store.author_aggregates(repository_id))
    store.replace_branches(
        repository_id,
        classify_branches(list(branches) or [{"name": "main", "is_current": True, "age_days": days_since_last}]),
    )
    return repository_id


# ------------------------------------------------------------------- E5-S1 metrics
def test_repository_metrics(store) -> None:
    repository_id = seed_repository(store, commits=6, days_since_last=2)
    metrics = repository_metrics(store, repository_id, now=NOW)
    assert metrics["total_commits"] == 6
    assert metrics["stored_commits"] == 6
    assert metrics["contributors"] == 2
    assert metrics["tracked_files"] == 12
    assert metrics["latest_commit"]["sha"] == f"{0:040d}"
    assert metrics["first_commit"]["sha"] == f"{5:040d}"  # oldest authored_at
    assert metrics["days_since_last_commit"] == 2
    assert metrics["age_days"] == 15


def test_repository_metrics_for_empty_repository(store) -> None:
    repository_id = store.upsert_repository({"name": "empty", "path": "/tmp/empty"})
    metrics = repository_metrics(store, repository_id, now=NOW)
    assert metrics["total_commits"] == 0
    assert metrics["latest_commit"]["sha"] is None
    assert metrics["age_days"] == 0
    assert metrics["days_since_last_commit"] is None


# ------------------------------------------------------------------- E5-S2 activity
def test_activity_metrics_windows(store) -> None:
    repository_id = seed_repository(store, commits=6, days_since_last=1)
    activity = activity_metrics(store, repository_id, now=NOW)
    assert activity["commits"]["week"] == 3  # commits every 3 days => 1,4,7,10,13,16 days old
    assert activity["commits"]["month"] == 6
    assert activity["commits"]["all_time"] == 6
    assert activity["active_contributors_30d"] >= 1
    assert activity["trend"] in {"increasing", "decreasing", "steady", "flat"}
    assert activity["commits_per_day"] > 0


def test_activity_series_is_gap_filled(store) -> None:
    repository_id = seed_repository(store, commits=4, days_since_last=0)
    series = activity_series(store, repository_id, days=10, bucket="day", now=NOW)
    assert len(series) == 10
    assert all("bucket" in point and "commits" in point for point in series)
    assert series[-1]["bucket"] == NOW.date().isoformat()
    summary = summarize_series(series)
    assert summary["buckets"] == 10 and summary["total"] >= 1


def test_activity_series_week_and_month_buckets(store) -> None:
    repository_id = seed_repository(store, commits=10, days_since_last=0)
    weekly = activity_series(store, repository_id, days=60, bucket="week", now=NOW)
    monthly = activity_series(store, repository_id, days=365, bucket="month", now=NOW)
    assert all(len(point["bucket"]) == 10 for point in weekly)
    assert all(len(point["bucket"]) == 7 for point in monthly)
    assert sum(point["commits"] for point in weekly) == sum(point["commits"] for point in monthly) == 10
    with pytest.raises(ValueError):
        activity_series(store, repository_id, days=10, bucket="hour", now=NOW)


def test_heatmap_grid_shape(store) -> None:
    repository_id = seed_repository(store, commits=5, days_since_last=1)
    payload = heatmap(store, repository_id, days=365, now=NOW)
    assert len(payload["grid"]) == 7 and all(len(row) == 24 for row in payload["grid"])
    assert payload["total"] == 5
    assert payload["peak"] >= 1


def test_contributor_trends(store) -> None:
    repository_id = seed_repository(store, commits=6, days_since_last=1)
    trends = contributor_trends(store, repository_id, weeks=12, now=NOW)
    assert trends and {"contributor", "email", "weeks"} <= set(trends[0])


# ------------------------------------------------------------------- E5-S3 changes
def test_change_metrics(store) -> None:
    repository_id = seed_repository(store, commits=6, days_since_last=1)
    changes = change_metrics(store, repository_id, now=NOW)
    assert changes["lines_added"] == 60
    assert changes["lines_deleted"] == 24
    assert changes["net_lines"] == 36
    assert changes["files_touched"] == 1
    assert changes["average_changes_per_commit"] == pytest.approx(14.0)
    assert changes["top_changed_files"][0]["path"] == "src/app.py"


# -------------------------------------------------------------------- E5-S4 branches
def test_branch_health_summary_counts() -> None:
    branches = classify_branches(
        [
            {"name": "main", "is_current": True, "age_days": 1},
            {"name": "stale-1", "age_days": 200},
            {"name": "stale-2", "age_days": 150},
            {"name": "remote", "is_remote": True, "age_days": 500},
        ],
        inactive_days=30,
        stale_days=90,
    )
    summary = branch_health_summary(branches, inactive_days=30, stale_days=90)
    assert summary["local_branches"] == 3
    assert summary["remote_branches"] == 1
    assert summary["stale_branches"] == 2
    assert summary["stale_ratio"] == pytest.approx(2 / 3, abs=0.01)
    assert summary["current_branch"] == "main"


# --------------------------------------------------------------------- E10 health
def test_health_score_is_transparent_and_bounded(store) -> None:
    repository_id = seed_repository(store, commits=20, days_since_last=1)
    repository = store.get_repository(repository_id)
    health = repository_health(store, repository, now=NOW)

    assert 0 <= health["score"] <= 100
    assert health["grade"] in "ABCDEF"
    signal_names = {signal["name"] for signal in health["signals"]}
    assert signal_names == set(SIGNAL_WEIGHTS)
    assert sum(signal["weight"] for signal in health["signals"]) == pytest.approx(1.0)
    for signal in health["signals"]:
        assert 0 <= signal["score"] <= 100
        assert signal["contribution"] == pytest.approx(signal["score"] * signal["weight"], abs=0.01)
        assert signal["detail"]  # every signal explains itself
    assert health["score"] == pytest.approx(sum(signal["contribution"] for signal in health["signals"]), abs=0.05)


def test_inactive_repository_scores_lower_than_active_one(store) -> None:
    active_id = seed_repository(store, name="active", commits=30, days_since_last=1)
    stale_id = seed_repository(
        store,
        name="stale",
        commits=3,
        days_since_last=400,
        branches=[{"name": "main", "is_current": True, "age_days": 400}, {"name": "old", "age_days": 500}],
    )
    active = repository_health(store, store.get_repository(active_id), now=NOW)
    stale = repository_health(store, store.get_repository(stale_id), now=NOW)
    assert active["score"] > stale["score"]
    assert stale["staleness"]["bucket"] == "abandoned"
    assert active["staleness"]["bucket"] == "active"
    assert any(item["code"] == "no_recent_commits" for item in stale["recommendations"])


def test_working_tree_reduces_health_and_warns(store) -> None:
    repository_id = seed_repository(store, name="dirty", commits=10, days_since_last=1, uncommitted=42, detached=True)
    repository = store.get_repository(repository_id)
    health = repository_health(store, repository, now=NOW)
    tree_signal = next(signal for signal in health["signals"] if signal["name"] == "working_tree")
    assert tree_signal["score"] < 60
    codes = {warning["code"] for warning in health["working_tree_warnings"]}
    assert {"detached_head", "uncommitted_changes"} <= codes
    assert any(
        "42 uncommitted" in warning["message"] or "42" in warning["message"]
        for warning in health["working_tree_warnings"]
    )


@pytest.mark.parametrize(
    "days, expected",
    [(5, "active"), (45, "inactive"), (120, "stale"), (400, "abandoned")],
)
def test_staleness_buckets(days: int, expected: str) -> None:
    repository = {"last_commit_at": (NOW - timedelta(days=days)).isoformat().replace("+00:00", "Z"), "total_commits": 5}
    payload = repository_staleness(repository, settings=None, now=NOW)
    assert payload["bucket"] == expected
    assert str(days) in payload["message"]


def test_staleness_for_empty_repository() -> None:
    payload = repository_staleness({"total_commits": 0, "last_commit_at": None}, now=NOW)
    assert payload["bucket"] == "empty"


def test_working_tree_warnings_content() -> None:
    warnings = working_tree_warnings(
        {"uncommitted_files": 5, "staged_files": 2, "untracked_files": 1, "detached_head": True}
    )
    codes = [warning["code"] for warning in warnings]
    assert codes[0] == "detached_head"
    assert "staged_changes" in codes and "untracked_files" in codes
    assert all(warning["message"] for warning in warnings)


def test_recommendations_are_actionable(store) -> None:
    branches = classify_branches(
        [{"name": "main", "is_current": True, "age_days": 1}, {"name": "old", "age_days": 200}]
    )
    summary = branch_health_summary(branches, inactive_days=30, stale_days=90)

    class Config:
        stale_branch_days = 90
        repo_inactive_days = 30
        repo_stale_days = 90

    items = recommendations(
        {"name": "demo", "uncommitted_files": 12, "detached_head": True, "remote_url": None, "total_commits": 5},
        branch_summary=summary,
        days_since_last_commit=120,
        uncommitted=12,
        settings=Config(),
    )
    messages = " ".join(item["message"] for item in items)
    assert "have not changed in 90 days" in messages  # stale branches are named explicitly
    assert "12 uncommitted" in messages
    assert "No commits detected in 120 days" in messages
    assert all(item["action"] for item in items)


def test_dashboard_insights_sorted_by_severity(store) -> None:
    seed_repository(store, name="active", commits=20, days_since_last=1)
    seed_repository(store, name="dead", commits=2, days_since_last=400, uncommitted=80)
    insights = dashboard_insights(store, limit=20)
    assert insights
    severities = [item["severity"] for item in insights]
    assert severities == sorted(severities, key={"error": 0, "warning": 1, "info": 2}.get)
    assert any(item["repository_name"] == "dead" for item in insights)


def test_repository_comparison(store) -> None:
    first = seed_repository(store, name="one", commits=10, days_since_last=1)
    second = seed_repository(store, name="two", commits=2, days_since_last=200)
    payload = repository_comparison(store, [first, second])
    assert [item["name"] for item in payload] == ["one", "two"]
    assert payload[0]["health_score"] > payload[1]["health_score"]
    assert {"commits", "contributors", "branches", "churn", "stale_branches"} <= set(payload[0])
