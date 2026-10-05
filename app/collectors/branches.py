"""Branch collection (E3-S2)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..logging_config import get_logger
from .git_runner import GitRunner
from .parsers import BRANCH_FORMAT, age_in_days, parse_branch_refs

log = get_logger("collectors.branches")


def collect_branches(
    runner: GitRunner,
    path: str,
    *,
    now: datetime | None = None,
    include_remote: bool = True,
    default_branch: str | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Return ``(branches, warnings)`` for a repository.

    Branches always belong to exactly one repository: the caller persists them with
    the repository id, which is what keeps them correctly associated (E3-S2 AC).
    """
    warnings: list[str] = []
    namespaces = ["refs/heads"] + (["refs/remotes"] if include_remote else [])
    result = runner.run(["for-each-ref", f"--format={BRANCH_FORMAT}", "--sort=-committerdate", *namespaces], cwd=path)
    if not result.ok:
        warnings.append(f"git for-each-ref failed: {result.failure_reason()}")
        return [], warnings

    reference_now = now or datetime.now(timezone.utc)
    branches = parse_branch_refs(result.stdout, now=reference_now)

    merged = _merged_branch_names(runner, path, default_branch=default_branch, warnings=warnings)
    for branch in branches:
        branch["is_merged"] = (not branch["is_remote"]) and branch["name"] in merged
        branch["has_upstream"] = bool(branch.get("upstream"))
        branch["age_days"] = age_in_days(branch.get("last_commit_at"), reference_now)
    return branches, warnings


def _merged_branch_names(
    runner: GitRunner,
    path: str,
    *,
    default_branch: str | None,
    warnings: list[str],
) -> set[str]:
    """Branches whose tip is reachable from the mainline (merged into it)."""
    merged: set[str] = set()
    for base in filter(None, [default_branch, "HEAD"]):
        # A repository without commits has no resolvable base - skip quietly.
        if not runner.run(["rev-parse", "--verify", "--quiet", f"{base}^{{commit}}"], cwd=path).ok:
            continue
        # --merged takes an *optional* argument, so use the ``=`` form to keep the
        # format string from being parsed as a revision.
        result = runner.run(["branch", "--format=%(refname:short)", f"--merged={base}"], cwd=path)
        if result.ok:
            merged.update(result.lines())
        else:
            warnings.append(f"cannot determine merged branches against {base}: {result.failure_reason()}")
    return merged


def classify_branch(branch: dict[str, Any], *, inactive_days: int, stale_days: int) -> dict[str, Any]:
    """Flag a branch as stale/inactive (E5-S4). Remote branches are never stale flags."""
    age = int(branch.get("age_days") or 0)
    branch["is_stale"] = bool(not branch.get("is_remote") and age >= stale_days and not branch.get("is_current"))
    branch["is_inactive"] = bool(not branch.get("is_remote") and inactive_days <= age < stale_days)
    if branch["is_stale"]:
        branch["status"] = "stale"
    elif branch.get("is_current"):
        branch["status"] = "current"
    elif branch["is_inactive"]:
        branch["status"] = "inactive"
    else:
        branch["status"] = "active"
    return branch
