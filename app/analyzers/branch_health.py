"""Branch health analysis (E5-S4).

A branch is flagged as:

* **current** - checked out right now,
* **active** - commit activity inside ``inactive_branch_days``,
* **inactive** - no commits for at least ``inactive_branch_days``,
* **stale** - no commits for at least ``stale_branch_days`` (the configurable
  threshold required by the acceptance criteria).

Remote-tracking branches are never flagged as stale: they mirror somebody else's
repository and are not ours to clean up.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from typing import Any


def classify_branch(
    branch: dict[str, Any],
    *,
    inactive_days: int = 30,
    stale_days: int = 90,
) -> dict[str, Any]:
    """Add ``is_stale`` / ``is_inactive`` / ``status`` to a branch row."""
    age = int(branch.get("age_days") or 0)
    enriched = dict(branch)
    enriched["is_stale"] = bool(not branch.get("is_remote") and not branch.get("is_current") and age >= stale_days)
    enriched["is_inactive"] = bool(
        not branch.get("is_remote") and not branch.get("is_current") and inactive_days <= age < stale_days
    )
    if enriched["is_stale"]:
        enriched["status"] = "stale"
    elif branch.get("is_current"):
        enriched["status"] = "current"
    elif branch.get("is_remote"):
        enriched["status"] = "remote"
    elif enriched["is_inactive"]:
        enriched["status"] = "inactive"
    elif branch.get("is_merged"):
        enriched["status"] = "merged"
    else:
        enriched["status"] = "active"
    return enriched


def classify_branches(
    branches: Iterable[dict[str, Any]],
    *,
    inactive_days: int = 30,
    stale_days: int = 90,
) -> list[dict[str, Any]]:
    return [classify_branch(branch, inactive_days=inactive_days, stale_days=stale_days) for branch in branches]


def branch_health_summary(
    branches: Sequence[dict[str, Any]],
    *,
    inactive_days: int = 30,
    stale_days: int = 90,
) -> dict[str, Any]:
    """Aggregate branch hygiene signals for a repository."""
    local = [branch for branch in branches if not branch.get("is_remote")]
    stale = [branch for branch in local if branch.get("is_stale")]
    inactive = [branch for branch in local if branch.get("is_inactive")]
    merged = [branch for branch in local if branch.get("is_merged") and not branch.get("is_current")]
    damaged = [branch for branch in local if branch.get("upstream_gone")]
    current = [branch for branch in local if branch.get("is_current")]

    ratio = round(len(stale) / len(local), 3) if local else 0.0
    return {
        "total_branches": len(branches),
        "local_branches": len(local),
        "remote_branches": len(branches) - len(local),
        "current_branch": current[0]["name"] if current else None,
        "stale_branches": len(stale),
        "inactive_branches": len(inactive),
        "merged_branches": len(merged),
        "upstream_gone_branches": len(damaged),
        "stale_ratio": ratio,
        "stale_branch_names": [branch["name"] for branch in stale][:25],
        "merged_branch_names": [branch["name"] for branch in merged][:25],
        "thresholds": {"inactive_days": inactive_days, "stale_days": stale_days},
        "oldest_branch": _oldest(local),
    }


def _oldest(branches: Sequence[dict[str, Any]]) -> dict[str, Any] | None:
    if not branches:
        return None
    oldest = max(branches, key=lambda branch: int(branch.get("age_days") or 0))
    return {
        "name": oldest.get("name"),
        "age_days": int(oldest.get("age_days") or 0),
        "last_commit_at": oldest.get("last_commit_at"),
    }


def branch_age_days(branch: dict[str, Any], *, now: datetime | None = None) -> int:
    timestamp = branch.get("last_commit_at")
    if not timestamp:
        return 0
    reference = now or datetime.now(timezone.utc)
    try:
        moment = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
    except ValueError:
        return 0
    return max(0, (reference - moment).days)
