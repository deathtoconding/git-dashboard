"""Repository metrics (Epic E5).

All metrics are computed from data already stored in SQLite, which means they are
reproducible and available offline - no Git or GitHub call is needed to render the
dashboard.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date, datetime, timedelta, timezone
from typing import Any

from ..database.store import Store

WINDOW_DAYS = {"day": 1, "week": 7, "month": 30, "quarter": 90, "year": 365}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def iso_days_ago(days: int, now: datetime | None = None) -> str:
    reference = now or utc_now()
    return (reference - timedelta(days=days)).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------- E5-S1 basics
def repository_metrics(store: Store, repository_id: int, *, now: datetime | None = None) -> dict[str, Any]:
    """Total commits, contributors, branches, tracked files, first/latest commit, age."""
    reference = now or utc_now()
    repository = store.get_repository(repository_id) or {}
    first, last = store.first_and_last_commit(repository_id)
    contributors = store.list_contributors(repository_id)
    branches = store.list_branches(repository_id, include_remote=False)

    latest_at = (last or {}).get("authored_at") or repository.get("last_commit_at")
    first_at = (first or {}).get("authored_at") or repository.get("first_commit_at")
    latest_dt = parse_timestamp(latest_at)
    first_dt = parse_timestamp(first_at)

    return {
        "repository_id": repository_id,
        "total_commits": repository.get("total_commits", store.count_commits(repository_id)),
        "stored_commits": store.count_commits(repository_id),
        "contributors": len(contributors),
        "branches": len(branches),
        "remote_branches": len(store.list_branches(repository_id, include_remote=True)) - len(branches),
        "tracked_files": repository.get("tracked_files", 0),
        "first_commit": {
            "sha": (first or {}).get("sha"),
            "date": first_at,
            "author": (first or {}).get("author_name"),
            "subject": (first or {}).get("subject"),
        },
        "latest_commit": {
            "sha": (last or {}).get("sha"),
            "date": latest_at,
            "author": (last or {}).get("author_name"),
            "subject": (last or {}).get("subject"),
        },
        "age_days": (latest_dt - first_dt).days if first_dt and latest_dt else 0,
        "days_since_last_commit": (reference - latest_dt).days if latest_dt else None,
    }


# -------------------------------------------------------------- E5-S2 activity
def activity_metrics(
    store: Store,
    repository_id: int,
    *,
    now: datetime | None = None,
    active_window_days: int = 30,
) -> dict[str, Any]:
    """Commits per day/week/month, active contributors and recent activity."""
    reference = now or utc_now()
    counts = {
        "today": store.count_commits(repository_id, since=iso_days_ago(1, reference)),
        "week": store.count_commits(repository_id, since=iso_days_ago(7, reference)),
        "month": store.count_commits(repository_id, since=iso_days_ago(30, reference)),
        "quarter": store.count_commits(repository_id, since=iso_days_ago(90, reference)),
        "year": store.count_commits(repository_id, since=iso_days_ago(365, reference)),
        "all_time": store.count_commits(repository_id),
    }
    first, last = store.first_and_last_commit(repository_id)
    latest_at = (last or {}).get("authored_at")
    first_at = (first or {}).get("authored_at")
    latest_dt = parse_timestamp(latest_at)
    first_dt = parse_timestamp(first_at)

    lifetime_days = max(1, (latest_dt - first_dt).days + 1) if first_dt and latest_dt else 1
    per_day_lifetime = round(counts["all_time"] / lifetime_days, 3)
    per_day_30 = round(counts["month"] / 30, 3)
    per_week_90 = round(counts["quarter"] / 13, 2)
    per_month_year = round(counts["year"] / 12, 2)

    contributors_recent = store.author_aggregates(repository_id, since=iso_days_ago(active_window_days, reference))
    contributors_previous = [
        row
        for row in store.author_aggregates(repository_id, since=iso_days_ago(active_window_days * 2, reference))
        if row["email"] not in {c["email"] for c in contributors_recent}
    ]

    current_week = counts["week"]
    previous_week = store.count_commits(
        repository_id,
        since=iso_days_ago(14, reference),
        until=iso_days_ago(7, reference),
    )
    if previous_week == 0 and current_week == 0:
        trend = "flat"
    elif current_week > previous_week * 1.2:
        trend = "increasing"
    elif current_week < previous_week * 0.8:
        trend = "decreasing"
    else:
        trend = "steady"

    return {
        "repository_id": repository_id,
        "commits": counts,
        "commits_per_day": per_day_lifetime,
        "commits_per_day_30d": per_day_30,
        "commits_per_week": per_week_90,
        "commits_per_month": per_month_year,
        "active_contributors_30d": len(contributors_recent),
        "active_contributors_previous_30d": len(contributors_previous),
        "inactive_contributors_30d": len(contributors_previous),
        "last_commit_at": latest_at,
        "first_commit_at": first_at,
        "days_since_last_commit": (reference - latest_dt).days if latest_dt else None,
        "lifetime_days": lifetime_days,
        "week_over_week": {"current": current_week, "previous": previous_week},
        "trend": trend,
    }


# --------------------------------------------------------- E5-S3 code changes
def change_metrics(store: Store, repository_id: int, *, now: datetime | None = None) -> dict[str, Any]:
    """Lines added/deleted, net change, files changed and averages per commit."""
    reference = now or utc_now()
    totals_all = store.file_change_totals(repository_id)
    totals_year = store.file_change_totals(repository_id, since=iso_days_ago(365, reference))
    totals_month = store.file_change_totals(repository_id, since=iso_days_ago(30, reference))

    commits_row = store.query_one(
        "SELECT COUNT(*) AS commits, COALESCE(SUM(additions), 0) AS additions, COALESCE(SUM(deletions), 0) AS deletions, "
        "COALESCE(SUM(files_changed), 0) AS files_changed FROM commits WHERE repository_id = ?",
        (repository_id,),
    ) or {}
    commits = int(commits_row.get("commits") or 0)
    additions = int(commits_row.get("additions") or 0)
    deletions = int(commits_row.get("deletions") or 0)
    files_changed = int(commits_row.get("files_changed") or 0)

    return {
        "repository_id": repository_id,
        "commits": commits,
        "lines_added": additions,
        "lines_deleted": deletions,
        "net_lines": additions - deletions,
        "files_changed": files_changed,
        "files_touched": totals_all["files_touched"],
        "average_changes_per_commit": round((additions + deletions) / commits, 2) if commits else 0.0,
        "average_files_per_commit": round(files_changed / commits, 2) if commits else 0.0,
        "last_30_days": {
            "lines_added": totals_month["additions"],
            "lines_deleted": totals_month["deletions"],
            "files_touched": totals_month["files_touched"],
        },
        "last_365_days": {
            "lines_added": totals_year["additions"],
            "lines_deleted": totals_year["deletions"],
            "files_touched": totals_year["files_touched"],
        },
        "top_changed_files": store.top_changed_files(repository_id, limit=10),
    }


# ------------------------------------------------------- E5-S2 activity series
def activity_series(
    store: Store,
    repository_id: int,
    *,
    days: int = 30,
    bucket: str = "day",
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Commit counts over time, gap-filled so charts never need client-side maths."""
    reference = now or utc_now()
    since = iso_days_ago(days, reference)
    daily = {row["day"]: int(row["commits"]) for row in store.daily_commit_counts(repository_id, since=since)}
    return _bucket_series(daily, days=days, bucket=bucket, now=reference)


def _bucket_series(daily: dict[str, int], *, days: int, bucket: str, now: datetime) -> list[dict[str, Any]]:
    start = (now - timedelta(days=days - 1)).date()
    buckets: dict[str, int] = {}
    for offset in range(days):
        day = start + timedelta(days=offset)
        buckets[day.isoformat()] = daily.get(day.isoformat(), 0)

    if bucket == "day":
        return [{"bucket": key, "label": key, "commits": value} for key, value in buckets.items()]
    if bucket == "week":
        grouped: dict[str, int] = {}
        for key, value in buckets.items():
            day = date.fromisoformat(key)
            monday = day - timedelta(days=day.weekday())
            grouped[monday.isoformat()] = grouped.get(monday.isoformat(), 0) + value
        return [
            {"bucket": key, "label": f"week of {key}", "commits": value}
            for key, value in sorted(grouped.items())
        ]
    if bucket == "month":
        grouped = {}
        for key, value in buckets.items():
            month = key[:7]
            grouped[month] = grouped.get(month, 0) + value
        return [{"bucket": key, "label": key, "commits": value} for key, value in sorted(grouped.items())]
    raise ValueError(f"unsupported bucket {bucket!r}; expected day, week or month")


def heatmap(store: Store, repository_id: int, *, days: int = 365, now: datetime | None = None) -> dict[str, Any]:
    """Commit counts by weekday x hour (E13-S1, useful on the detail page)."""
    reference = now or utc_now()
    rows = store.hourly_commit_counts(repository_id, since=iso_days_ago(days, reference))
    grid = [[0] * 24 for _ in range(7)]
    total = 0
    for row in rows:
        moment = parse_timestamp(row.get("authored_at"))
        if not moment:
            continue
        grid[moment.weekday()][moment.hour] += 1
        total += 1
    return {
        "repository_id": repository_id,
        "days": days,
        "grid": grid,
        "weekdays": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
        "total": total,
        "peak": max((max(column) for column in grid), default=0),
    }


def contributor_trends(store: Store, repository_id: int, *, weeks: int = 12, now: datetime | None = None) -> list[dict[str, Any]]:
    """Weekly contribution counts for the most active contributors (E13-S2)."""
    reference = now or utc_now()
    since = iso_days_ago(weeks * 7, reference)
    rows = store.query(
        "SELECT author_email AS email, author_name AS name, authored_at FROM commits WHERE repository_id = ? AND authored_at >= ?",
        (repository_id, since),
    )
    buckets: dict[str, dict[str, int]] = {}
    for row in rows:
        moment = parse_timestamp(row.get("authored_at"))
        if not moment:
            continue
        monday = (moment.date() - timedelta(days=moment.weekday())).isoformat()
        key = row.get("email") or row.get("name") or "unknown"
        buckets.setdefault(key, {})
        buckets[key][monday] = buckets[key].get(monday, 0) + 1
    names = {row.get("email") or row.get("name"): row.get("name") for row in rows}
    series = [
        {"contributor": names.get(key, key), "email": key, "weeks": buckets[key]}
        for key in sorted(buckets, key=lambda item: -sum(buckets[item].values()))[:10]
    ]
    return series


def repository_comparison(store: Store, repository_ids: Sequence[int]) -> list[dict[str, Any]]:
    """Side-by-side metrics for several repositories (E13-S4)."""
    comparison: list[dict[str, Any]] = []
    for repository_id in repository_ids:
        repository = store.get_repository(repository_id)
        if not repository:
            continue
        metrics = repository_metrics(store, repository_id)
        activity = activity_metrics(store, repository_id)
        health = _lazy_health(store, repository)
        changes = change_metrics(store, repository_id)
        comparison.append(
            {
                "repository_id": repository_id,
                "name": repository["name"],
                "state": repository.get("state"),
                "staleness": repository.get("staleness"),
                "commits": metrics["total_commits"],
                "commits_last_30d": activity["commits"]["month"],
                "contributors": metrics["contributors"],
                "branches": metrics["branches"],
                "local_branches": health["counts"]["local_branches"],
                "stale_branches": health["branch_health"]["stale_branches"],
                "merged_branches": health["branch_health"]["merged_branches"],
                "uncommitted_files": int(repository.get("uncommitted_files") or 0),
                "lines_added": changes["lines_added"],
                "lines_deleted": changes["lines_deleted"],
                "churn": changes["lines_added"] + changes["lines_deleted"],
                "health_score": health["score"],
                "health_grade": health["grade"],
                "days_since_last_commit": activity["days_since_last_commit"],
            }
        )
    return comparison


def _lazy_health(store: Store, repository: dict[str, Any]) -> dict[str, Any]:
    from .health import repository_health

    return repository_health(store, repository)


def summarize_series(series: Iterable[dict[str, Any]]) -> dict[str, Any]:
    values = [int(item.get("commits") or 0) for item in series]
    return {
        "total": sum(values),
        "average": round(sum(values) / len(values), 2) if values else 0.0,
        "peak": max(values) if values else 0,
        "buckets": len(values),
    }
