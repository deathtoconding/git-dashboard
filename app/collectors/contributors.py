"""Contributor collection (E3-S5).

Contributors are derived from Git history only, so the resulting statistics are
fully reproducible: re-running a scan over the same history yields the same rows.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from typing import Any

from ..logging_config import get_logger
from .git_runner import GitRunner
from .parsers import parse_name_email

log = get_logger("collectors.contributors")


def aggregate_contributors(commits: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate ``(name, email)`` statistics from a list of parsed commits."""
    buckets: dict[tuple[str, str], dict[str, Any]] = defaultdict(
        lambda: {
            "name": "unknown",
            "email": "",
            "commits": 0,
            "additions": 0,
            "deletions": 0,
            "first_commit_at": None,
            "last_commit_at": None,
        }
    )
    for commit in commits:
        name = (commit.get("author_name") or "unknown").strip() or "unknown"
        email = (commit.get("author_email") or "").strip().lower()
        bucket = buckets[(email, name)]
        bucket["name"] = name
        bucket["email"] = email
        bucket["commits"] += 1
        bucket["additions"] += int(commit.get("additions") or 0)
        bucket["deletions"] += int(commit.get("deletions") or 0)
        authored_at = commit.get("authored_at")
        if authored_at:
            if bucket["first_commit_at"] is None or authored_at < bucket["first_commit_at"]:
                bucket["first_commit_at"] = authored_at
            if bucket["last_commit_at"] is None or authored_at > bucket["last_commit_at"]:
                bucket["last_commit_at"] = authored_at
    contributors = list(buckets.values())
    contributors.sort(key=lambda row: (-row["commits"], row["name"].lower()))
    return contributors


def shortlog_contributors(runner: GitRunner, path: str, *, limit: int = 0) -> tuple[list[dict[str, Any]], str | None]:
    """Read contributors straight from ``git shortlog`` (alternative data source)."""
    args = ["shortlog", "-sne", "--all", "HEAD"]
    if limit:
        args.insert(1, f"-{limit}")
    result = runner.run(args, cwd=path)
    if not result.ok:
        return [], f"git shortlog failed: {result.failure_reason()}"
    contributors: list[dict[str, Any]] = []
    for line in result.lines():
        stripped = line.strip()
        if "\t" not in stripped:
            continue
        count_text, _, identity = stripped.partition("\t")
        try:
            commits = int(count_text.strip())
        except ValueError:
            continue
        name, email = parse_name_email(identity.strip())
        contributors.append({"name": name, "email": email, "commits": commits, "additions": 0, "deletions": 0})
    contributors.sort(key=lambda row: -row["commits"])
    return contributors, None


def merge_contributor_sources(*sources: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge contributor lists, summing commit counts per identity."""
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for source in sources:
        for row in source:
            key = ((row.get("email") or "").lower(), row.get("name") or "unknown")
            if key not in merged:
                merged[key] = dict(row)
                merged[key]["commits"] = int(row.get("commits") or 0)
                continue
            target = merged[key]
            target["commits"] = int(target.get("commits") or 0) + int(row.get("commits") or 0)
            target["additions"] = int(target.get("additions") or 0) + int(row.get("additions") or 0)
            target["deletions"] = int(target.get("deletions") or 0) + int(row.get("deletions") or 0)
    rows = list(merged.values())
    rows.sort(key=lambda row: (-int(row.get("commits") or 0), str(row.get("name", "")).lower()))
    return rows
