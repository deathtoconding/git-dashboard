"""Repository state and metadata collection (E2-S3, E10-S3).

Collects everything the dashboard needs to describe a repository right now:
current branch, HEAD, remote, working-tree state, counts and key timestamps.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..logging_config import get_logger
from .git_runner import GitRunner
from .parsers import age_in_days, normalize_timestamp, parse_rev_list_count, parse_status_porcelain

log = get_logger("collectors.repo_state")


@dataclass(slots=True)
class RepositoryState:
    """Raw repository metadata as reported by Git."""

    path: str
    name: str
    is_bare: bool = False
    is_dirty: bool = False
    detached_head: bool = False
    current_branch: str | None = None
    head_commit: str | None = None
    head_subject: str | None = None
    remote_url: str | None = None
    default_branch: str | None = None
    total_commits: int = 0
    tracked_files: int = 0
    first_commit_at: str | None = None
    last_commit_at: str | None = None
    uncommitted_files: int = 0
    staged_files: int = 0
    untracked_files: int = 0
    conflicted_files: int = 0
    age_days: int = 0
    state: str = "unknown"
    warnings: list[str] = field(default_factory=list)

    def to_row(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "path": self.path,
            "current_branch": self.current_branch,
            "head_commit": self.head_commit,
            "head_subject": self.head_subject,
            "remote_url": self.remote_url,
            "default_branch": self.default_branch,
            "state": self.state,
            "is_bare": self.is_bare,
            "is_dirty": self.is_dirty,
            "detached_head": self.detached_head,
            "uncommitted_files": self.uncommitted_files,
            "staged_files": self.staged_files,
            "untracked_files": self.untracked_files,
            "total_commits": self.total_commits,
            "tracked_files": self.tracked_files,
            "first_commit_at": self.first_commit_at,
            "last_commit_at": self.last_commit_at,
        }


def collect_repository_state(runner: GitRunner, path: str, *, name: str | None = None) -> RepositoryState:
    """Gather repository metadata. Individual failures become warnings, never crashes."""
    state = RepositoryState(path=path, name=name or path.rstrip("/\\").split("/")[-1].split("\\")[-1] or path)

    bare = runner.run(["rev-parse", "--is-bare-repository"], cwd=path)
    if bare.ok:
        state.is_bare = bare.first_line().lower() == "true"
    elif not bare.ok and bare.code != 0:
        state.warnings.append(f"rev-parse --is-bare-repository failed: {bare.failure_reason()}")

    # --- repository kind -------------------------------------------------
    if state.is_bare:
        state.state = "bare"

    # --- current branch / detached HEAD ----------------------------------
    branch = runner.run(["symbolic-ref", "--quiet", "--short", "HEAD"], cwd=path)
    if branch.ok and branch.first_line():
        state.current_branch = branch.first_line()
    else:
        head = runner.run(["rev-parse", "--abbrev-ref", "HEAD"], cwd=path)
        if head.ok:
            reference = head.first_line()
            if reference and reference != "HEAD":
                state.current_branch = reference
            else:
                state.detached_head = True
                state.warnings.append("HEAD is detached (no branch checked out)")

    # --- HEAD commit -----------------------------------------------------
    head_sha = runner.run(["rev-parse", "HEAD"], cwd=path)
    if head_sha.ok:
        state.head_commit = head_sha.first_line() or None
        subject = runner.run(["log", "-1", "--no-color", "--pretty=%s"], cwd=path)
        if subject.ok:
            state.head_subject = subject.first_line()[:300]
    else:
        # A repository without any commit has no HEAD yet - that is a state, not an error.
        state.warnings.append(f"cannot resolve HEAD: {head_sha.failure_reason()}")

    # --- remote url ------------------------------------------------------
    remote = runner.run(["remote"], cwd=path)
    remotes = remote.lines() if remote.ok else []
    if remotes:
        preferred = "origin" if "origin" in remotes else remotes[0]
        url = runner.run(["remote", "get-url", preferred], cwd=path)
        if url.ok:
            state.remote_url = url.first_line() or None
        default = runner.run(["symbolic-ref", "--quiet", "--short", f"refs/remotes/{preferred}/HEAD"], cwd=path)
        if default.ok and default.first_line():
            state.default_branch = default.first_line().split("/", 1)[-1]

    # --- working tree ----------------------------------------------------
    if not state.is_bare:
        status = runner.run(["status", "--porcelain", "--untracked-files=normal"], cwd=path)
        if status.ok:
            counts = parse_status_porcelain(status.stdout)
            state.staged_files = counts["staged"]
            state.untracked_files = counts["untracked"]
            state.conflicted_files = counts["conflicted"]
            state.uncommitted_files = counts["total"]
            state.is_dirty = counts["total"] > 0 or state.detached_head
        else:
            state.warnings.append(f"git status failed: {status.failure_reason()}")

        tracked = runner.run(["ls-files", "-z"], cwd=path)
        if tracked.ok:
            state.tracked_files = len([entry for entry in tracked.stdout.split("\x00") if entry])
        else:
            state.warnings.append(f"git ls-files failed: {tracked.failure_reason()}")

    # --- commit counts and dates ----------------------------------------
    total = runner.run(["rev-list", "--count", "--all"], cwd=path)
    if total.ok:
        state.total_commits = parse_rev_list_count(total.stdout)
    else:
        # Fall back to the current branch only (works in shallow clones too).
        fallback = runner.run(["rev-list", "--count", "HEAD"], cwd=path)
        if fallback.ok:
            state.total_commits = parse_rev_list_count(fallback.stdout)
        else:
            state.warnings.append(f"git rev-list --count failed: {fallback.failure_reason()}")

    latest = runner.run(["log", "-1", "--no-color", "--date=iso-strict", "--pretty=%cI"], cwd=path)
    if latest.ok:
        state.last_commit_at = normalize_timestamp(latest.first_line())

    first = _first_commit_date(runner, path)
    if first:
        state.first_commit_at = first
    if state.first_commit_at and state.last_commit_at:
        from datetime import datetime, timezone

        try:
            start = datetime.fromisoformat(state.first_commit_at.replace("Z", "+00:00"))
            end = datetime.fromisoformat(state.last_commit_at.replace("Z", "+00:00"))
            state.age_days = max(0, (end - start).days)
        except ValueError:  # pragma: no cover - defensive
            state.age_days = age_in_days(state.first_commit_at, datetime.now(timezone.utc))

    if not state.is_bare and state.head_commit is None and state.total_commits == 0:
        # Freshly initialised repository: no commits yet. Report it as a state,
        # not as a failure ("cannot resolve HEAD" is expected here).
        state.state = "empty"
        state.is_dirty = False
        state.warnings = [warning for warning in state.warnings if not warning.startswith("cannot resolve HEAD")]
    elif not state.is_bare:
        if state.detached_head:
            state.state = "detached"
        elif state.is_dirty:
            state.state = "dirty"
        else:
            state.state = "clean"

    return state


def _first_commit_date(runner: GitRunner, path: str) -> str | None:
    """Timestamp of the oldest root commit (best effort, cheap on packed repos)."""
    roots = runner.run(["rev-list", "--max-parents=0", "--all"], cwd=path)
    if not roots.ok or not roots.lines():
        return None
    oldest: str | None = None
    for sha in roots.lines()[:20]:
        result = runner.run(["log", "-1", "--no-color", "--date=iso-strict", "--pretty=%cI", sha], cwd=path)
        if not result.ok:
            continue
        candidate = normalize_timestamp(result.first_line())
        if candidate and (oldest is None or candidate < oldest):
            oldest = candidate
    return oldest
