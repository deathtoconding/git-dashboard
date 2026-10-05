"""Repository health and insights (Epic E10).

The health score is deliberately **transparent**: it is a weighted sum of five
human-readable signals, every one of which is exposed with its raw value, its
weight and its contribution so the UI can explain the number.  There is no opaque
AI score anywhere in this module.

Signals (weights sum to 1.0):

===========  ======  ====================================================
Signal       Weight  Based on
===========  ======  ====================================================
activity     0.30    days since the last commit
branch       0.25    stale branch ratio, unreleased merged branches
working tree 0.20    uncommitted/untracked files, detached HEAD
recent       0.15    commits in the last 30 days
maintenance  0.10    remote configured, scan health, branch/file hygiene
===========  ======  ====================================================
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any

from ..config import Settings
from ..database.store import Store
from .branch_health import branch_health_summary

SIGNAL_WEIGHTS = {
    "activity": 0.30,
    "branch_hygiene": 0.25,
    "working_tree": 0.20,
    "recent_commits": 0.15,
    "maintenance": 0.10,
}

GRADES = ((85, "A"), (70, "B"), (55, "C"), (40, "D"), (25, "E"), (0, "F"))
LEVELS = ((85, "healthy"), (70, "good"), (55, "watch"), (40, "attention"), (0, "critical"))


def _default_settings() -> Settings:
    return Settings()


def _interpolate(value: float, anchors: Sequence[tuple[float, float]]) -> float:
    """Piecewise-linear scoring between explicit anchors (transparent by design)."""
    ordered = sorted(anchors)
    if value <= ordered[0][0]:
        return ordered[0][1]
    if value >= ordered[-1][0]:
        return ordered[-1][1]
    for (low_x, low_y), (high_x, high_y) in zip(ordered, ordered[1:], strict=False):
        if low_x <= value <= high_x:
            span = high_x - low_x or 1
            ratio = (value - low_x) / span
            return round(low_y + (high_y - low_y) * ratio, 1)
    return ordered[-1][1]  # pragma: no cover - unreachable


def _signal(name: str, label: str, score: float, detail: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    weight = SIGNAL_WEIGHTS[name]
    bounded = max(0.0, min(100.0, float(score)))
    payload = {
        "name": name,
        "label": label,
        "weight": weight,
        "score": round(bounded, 1),
        "contribution": round(bounded * weight, 2),
        "detail": detail,
    }
    if extra:
        payload.update(extra)
    return payload


# ------------------------------------------------------------- staleness (E10-S2)
def repository_staleness(
    repository: dict[str, Any],
    *,
    days_since_last_commit: int | None = None,
    settings: Settings | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Bucket a repository as active / inactive / stale / abandoned candidate."""
    config = settings or _default_settings()
    reference = now or datetime.now(timezone.utc)

    days = days_since_last_commit
    if days is None:
        timestamp = repository.get("last_commit_at")
        if timestamp:
            try:
                moment = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
                days = max(0, (reference - moment).days)
            except ValueError:
                days = None
    if days is None and not repository.get("total_commits"):
        return {
            "bucket": "empty",
            "label": "No commits",
            "days_since_last_commit": None,
            "message": "Repository has no commits yet.",
        }
    if days is None:
        return {"bucket": "unknown", "label": "Unknown", "days_since_last_commit": None, "message": "Never scanned."}

    if days < config.repo_inactive_days:
        bucket, label = "active", "Active"
        message = f"Last commit {days} day(s) ago."
    elif days < config.repo_stale_days:
        bucket, label = "inactive", "Inactive"
        message = f"No commits for {days} days (inactive threshold: {config.repo_inactive_days})."
    elif days < config.repo_abandoned_days:
        bucket, label = "stale", "Stale"
        message = f"No commits for {days} days (stale threshold: {config.repo_stale_days})."
    else:
        bucket, label = "abandoned", "Abandoned candidate"
        message = f"No commits for {days} days (abandoned threshold: {config.repo_abandoned_days})."
    return {
        "bucket": bucket,
        "label": label,
        "days_since_last_commit": days,
        "message": message,
    }


# --------------------------------------------------------- working tree (E10-S3)
def working_tree_warnings(repository: dict[str, Any]) -> list[dict[str, Any]]:
    """Detect uncommitted, staged, untracked files and detached HEAD."""
    warnings: list[dict[str, Any]] = []
    if repository.get("detached_head"):
        warnings.append({"code": "detached_head", "severity": "warning", "message": "HEAD is detached (no branch checked out)."})
    unstaged = int(repository.get("uncommitted_files") or 0)
    staged = int(repository.get("staged_files") or 0)
    untracked = int(repository.get("untracked_files") or 0)
    if staged:
        warnings.append({"code": "staged_changes", "severity": "info", "message": f"{staged} staged change(s) not committed."})
    dirty_worktree = max(0, unstaged - untracked - staged)
    if dirty_worktree:
        warnings.append({"code": "uncommitted_changes", "severity": "warning", "message": f"{dirty_worktree} uncommitted file change(s)."})
    if untracked:
        warnings.append({"code": "untracked_files", "severity": "info", "message": f"{untracked} untracked file(s) present."})
    if repository.get("state") == "error":
        warnings.append(
            {"code": "scan_error", "severity": "error", "message": repository.get("last_error") or "Last scan failed."}
        )
    return warnings


# ------------------------------------------------------------------- score (E10-S1)
def repository_health(
    store: Store,
    repository: dict[str, Any],
    *,
    settings: Settings | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Compute the transparent health score for one repository."""
    config = settings or _default_settings()
    reference = now or datetime.now(timezone.utc)
    repository_id = int(repository["id"])

    branches = store.list_branches(repository_id, include_remote=True)
    local_branches = [branch for branch in branches if not branch.get("is_remote")]
    branch_summary = branch_health_summary(
        branches,
        inactive_days=config.inactive_branch_days,
        stale_days=config.stale_branch_days,
    )

    commits_30d = store.count_commits(repository_id, since=_days_ago_iso(30, reference))
    commits_90d = store.count_commits(repository_id, since=_days_ago_iso(90, reference))

    last_dt = _parse(repository.get("last_commit_at"))
    days_since = (reference - last_dt).days if last_dt else None

    staleness = repository_staleness(repository, days_since_last_commit=days_since, settings=config, now=reference)

    signals: list[dict[str, Any]] = []

    # --- activity -------------------------------------------------------
    if days_since is None:
        activity_score = 0.0 if not repository.get("total_commits") else 20.0
        activity_detail = "No commits found in this repository." if not repository.get("total_commits") else "No commit dates available."
    else:
        activity_score = _interpolate(
            days_since,
            [(0, 100), (7, 100), (30, 80), (90, 45), (180, 20), (365, 5), (1000, 0)],
        )
        activity_detail = f"Last commit {days_since} day(s) ago."
    signals.append(_signal("activity", "Activity", activity_score, activity_detail, {"days_since_last_commit": days_since}))

    # --- branch hygiene --------------------------------------------------
    if not local_branches:
        hygiene_score = 70.0
        hygiene_detail = "No local branches detected."
    else:
        stale_ratio = branch_summary["stale_ratio"]
        merged_unclean = branch_summary["merged_branches"]
        hygiene_score = 100 - stale_ratio * 60 - min(20, merged_unclean * 4)
        hygiene_detail = (
            f"{branch_summary['stale_branches']} stale of {len(local_branches)} local branch(es)"
            + (f", {merged_unclean} merged branch(es) not deleted" if merged_unclean else "")
            + "."
        )
    signals.append(
        _signal(
            "branch_hygiene",
            "Branch hygiene",
            hygiene_score,
            hygiene_detail,
            {"stale_branches": branch_summary["stale_branches"], "merged_branches": branch_summary["merged_branches"]},
        )
    )

    # --- working tree ----------------------------------------------------
    uncommitted = int(repository.get("uncommitted_files") or 0)
    tree_score = _interpolate(
        uncommitted,
        [(0, 100), (1, 92), (5, 80), (20, 60), (50, 35), (100, 15), (500, 5)],
    )
    if repository.get("detached_head"):
        tree_score -= 25
    if repository.get("is_bare"):
        tree_score = 100.0
        tree_detail = "Bare repository (no working tree)."
    else:
        tree_detail = (
            "Working tree is clean." if uncommitted == 0 else f"{uncommitted} uncommitted file(s) in the working tree."
        )
        if repository.get("detached_head"):
            tree_detail += " HEAD is detached."
    signals.append(_signal("working_tree", "Working tree", tree_score, tree_detail, {"uncommitted_files": uncommitted}))

    # --- recent commits --------------------------------------------------
    recent_score = _interpolate(commits_30d, [(0, 10), (1, 45), (5, 70), (15, 88), (50, 100), (500, 100)])
    signals.append(
        _signal(
            "recent_commits",
            "Recent commits",
            recent_score,
            f"{commits_30d} commit(s) in the last 30 days, {commits_90d} in the last 90 days.",
            {"commits_30d": commits_30d, "commits_90d": commits_90d},
        )
    )

    # --- maintenance ------------------------------------------------------
    checks = [
        ("remote configured", bool(repository.get("remote_url"))),
        ("default branch known", bool(repository.get("default_branch") or repository.get("current_branch"))),
        ("last scan succeeded", not repository.get("last_error")),
        ("repository has history", bool(repository.get("total_commits"))),
        ("head resolved", bool(repository.get("head_commit"))),
        ("configured upstream", any(branch.get("upstream") for branch in local_branches) or bool(repository.get("is_bare"))),
    ]
    passed = [name for name, ok in checks if ok]
    failed = [name for name, ok in checks if not ok]
    maintenance_score = round(100 * len(passed) / len(checks), 1)
    maintenance_detail = (
        "All maintenance checks passed." if not failed else f"Missing: {', '.join(failed)}."
    )
    signals.append(
        _signal(
            "maintenance",
            "Maintenance",
            maintenance_score,
            maintenance_detail,
            {"checks": dict(checks)},
        )
    )

    score = round(sum(signal["contribution"] for signal in signals), 1)
    grade = next(label for threshold, label in GRADES if score >= threshold)
    level = next(label for threshold, label in LEVELS if score >= threshold)

    return {
        "repository_id": repository_id,
        "name": repository.get("name"),
        "score": score,
        "grade": grade,
        "level": level,
        "signals": signals,
        "staleness": staleness,
        "branch_health": branch_summary,
        "working_tree_warnings": working_tree_warnings(repository),
        "recommendations": recommendations(
            repository,
            branch_summary=branch_summary,
            days_since_last_commit=days_since,
            uncommitted=uncommitted,
            settings=config,
        ),
        "counts": {
            "commits_30d": commits_30d,
            "commits_90d": commits_90d,
            "local_branches": len(local_branches),
            "remote_branches": len(branches) - len(local_branches),
        },
    }


# ------------------------------------------------------- recommendations (E10-S4)
def recommendations(
    repository: dict[str, Any],
    *,
    branch_summary: dict[str, Any],
    days_since_last_commit: int | None,
    uncommitted: int,
    settings: Settings,
) -> list[dict[str, Any]]:
    """Human readable, actionable next steps for a repository."""
    items: list[dict[str, Any]] = []
    stale = branch_summary.get("stale_branches", 0)
    if stale:
        items.append(
            {
                "severity": "warning",
                "code": "stale_branches",
                "message": f"{stale} branch(es) have not changed in {settings.stale_branch_days} days.",
                "action": "Review and delete stale branches.",
            }
        )
    merged = branch_summary.get("merged_branches", 0)
    if merged:
        items.append(
            {
                "severity": "info",
                "code": "merged_branches",
                "message": f"{merged} branch(es) are already merged and can be deleted.",
                "action": "git branch -d <branch>",
            }
        )
    if uncommitted:
        items.append(
            {
                "severity": "warning",
                "code": "uncommitted",
                "message": f"Repository has {uncommitted} uncommitted file(s).",
                "action": "Commit or stash the working tree changes.",
            }
        )
    if repository.get("detached_head"):
        items.append(
            {
                "severity": "warning",
                "code": "detached_head",
                "message": "HEAD is detached.",
                "action": "Check out a branch to avoid losing commits.",
            }
        )
    if days_since_last_commit is not None and days_since_last_commit >= settings.repo_inactive_days:
        items.append(
            {
                "severity": "error" if days_since_last_commit >= settings.repo_stale_days else "warning",
                "code": "no_recent_commits",
                "message": f"No commits detected in {days_since_last_commit} days.",
                "action": "Archive, revive or remove this repository from the dashboard.",
            }
        )
    if not repository.get("remote_url"):
        items.append(
            {
                "severity": "info",
                "code": "no_remote",
                "message": "No Git remote configured.",
                "action": "Add a backup remote if this repository matters.",
            }
        )
    if repository.get("last_error"):
        items.append(
            {
                "severity": "error",
                "code": "scan_error",
                "message": f"Last scan failed: {repository['last_error']}",
                "action": "Re-run the scan from the repository page.",
            }
        )
    if not repository.get("total_commits"):
        items.append(
            {
                "severity": "info",
                "code": "no_history",
                "message": "Repository has no commits yet.",
                "action": "Create the first commit.",
            }
        )
    return items


# ------------------------------------------------------------ dashboard insights
def dashboard_insights(store: Store, *, settings: Settings | None = None, limit: int = 25) -> list[dict[str, Any]]:
    """Aggregate the most important findings across every repository."""
    config = settings or _default_settings()
    reference = datetime.now(timezone.utc)
    insights: list[dict[str, Any]] = []

    for repository in store.list_repositories():
        repository_id = int(repository["id"])
        branches = store.list_branches(repository_id, include_remote=True)
        summary = branch_health_summary(
            branches, inactive_days=config.inactive_branch_days, stale_days=config.stale_branch_days
        )
        commits_30d = store.count_commits(repository_id, since=_days_ago_iso(30, reference))
        last_dt = _parse(repository.get("last_commit_at"))
        days_since = (reference - last_dt).days if last_dt else None
        staleness = repository_staleness(repository, days_since_last_commit=days_since, settings=config, now=reference)
        for item in recommendations(
            repository,
            branch_summary=summary,
            days_since_last_commit=days_since,
            uncommitted=int(repository.get("uncommitted_files") or 0),
            settings=config,
        ):
            insights.append(
                {
                    **item,
                    "repository_id": repository_id,
                    "repository_name": repository["name"],
                    "repository_path": repository["path"],
                    "days_since_last_commit": days_since,
                    "commits_30d": commits_30d,
                    "staleness": staleness["bucket"],
                }
            )

    order = {"error": 0, "warning": 1, "info": 2}
    insights.sort(key=lambda item: (order.get(item.get("severity", "info"), 3), -(item.get("days_since_last_commit") or 0)))
    return insights[:limit]


def _days_ago_iso(days: int, now: datetime) -> str:
    from datetime import timedelta

    return (now - timedelta(days=days)).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def repository_health_sort_key(health: dict[str, Any]) -> float:
    """Sort helper so repository lists can be ordered by health score."""
    return float(health.get("score") or 0)
