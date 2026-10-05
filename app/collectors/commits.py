"""Commit and file-change collection (E3-S3, E3-S4, E9-S3).

One ``git log --numstat`` invocation yields commits *and* their per-file change
statistics, which keeps scanning fast on large histories.  Incremental scans pass
``since_sha`` so only commits that are not reachable from the last known commit are
re-visited.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from ..logging_config import get_logger
from .git_runner import GitRunner
from .parsers import COMMIT_FORMAT, parse_commit_log

log = get_logger("collectors.commits")


@dataclass(slots=True)
class CommitBatch:
    commits: list[dict[str, Any]] = field(default_factory=list)
    file_changes: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    truncated: bool = False


def collect_commits(
    runner: GitRunner,
    path: str,
    *,
    history_depth: int = 500,
    since_sha: str | None = None,
    branch: str | None = None,
    timeout: int | None = None,
) -> CommitBatch:
    """Collect commits (plus numstat rows) from every ref, or only new ones.

    ``since_sha`` implements incremental scanning: ``--not <sha>`` excludes every
    commit already reachable from the last scanned commit.
    """
    batch = CommitBatch()
    args: list[str] = [
        "log",
        "--no-color",
        "--date-order",
        "--numstat",
        "--no-renames",
        "--no-show-signature",
        f"--pretty=format:{COMMIT_FORMAT}",
        f"--max-count={max(1, int(history_depth))}",
    ]
    # Use a generous timeout: the first scan of a large repository can take a while.
    effective_timeout = timeout or max(runner.timeout, 60)

    if since_sha:
        # `--not <sha>` excludes everything already reachable from the last scan.
        incremental_args = args + ["--all", "--not", since_sha]
        result = runner.run(incremental_args, cwd=path, timeout=effective_timeout)
        if not result.ok:
            # The recorded SHA may have been rewritten or garbage collected - retry from scratch.
            log.warning(
                "incremental log failed for %s (%s); falling back to a full walk", path, result.failure_reason()
            )
            batch.warnings.append(f"incremental walk failed, performed a full walk instead ({result.failure_reason()})")
            result = runner.run(args + ["--all"], cwd=path, timeout=effective_timeout)
    else:
        args += [branch] if branch else ["--all"]
        result = runner.run(args, cwd=path, timeout=effective_timeout)

    if not result.ok:
        batch.warnings.append(f"git log failed: {result.failure_reason()}")
        return batch

    commits, file_changes = parse_commit_log(result.stdout)
    batch.commits = commits
    batch.file_changes = file_changes
    batch.truncated = len(commits) >= max(1, int(history_depth))
    if batch.truncated:
        log.info("history for %s capped at %d commits (raise 'history_depth' to collect more)", path, history_depth)
    log.debug("collected %d commits and %d file-change sets from %s", len(commits), len(file_changes), path)
    return batch


def collect_file_changes_for(
    runner: GitRunner,
    path: str,
    shas: Sequence[str],
    *,
    timeout: int | None = None,
) -> CommitBatch:
    """Fetch numstat rows for specific commits (used to backfill missing details)."""
    batch = CommitBatch()
    targets: Iterable[str] = [sha for sha in shas if sha]
    args: list[str] = [
        "log",
        "--no-color",
        "--numstat",
        "--no-renames",
        "--no-show-signature",
        f"--pretty=format:{COMMIT_FORMAT}",
        "--no-walk",
        *targets,
    ]
    if not targets:
        return batch
    result = runner.run(args, cwd=path, timeout=timeout or max(runner.timeout, 60))
    if not result.ok:
        batch.warnings.append(f"file-change backfill failed: {result.failure_reason()}")
        return batch
    commits, file_changes = parse_commit_log(result.stdout)
    batch.commits = commits
    batch.file_changes = file_changes
    return batch
