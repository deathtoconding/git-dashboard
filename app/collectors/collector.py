"""Collector facade: one object that turns a repository path into dashboard data."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..logging_config import get_logger
from .branches import collect_branches
from .commits import CommitBatch, collect_commits, collect_file_changes_for
from .contributors import aggregate_contributors
from .git_runner import GitNotFoundError, GitRunner
from .repo_state import RepositoryState, collect_repository_state

log = get_logger("collectors.collector")


@dataclass(slots=True)
class CollectionResult:
    """Everything a single repository scan produced."""

    state: RepositoryState
    branches: list[dict[str, Any]] = field(default_factory=list)
    commit_batch: CommitBatch = field(default_factory=CommitBatch)
    contributors: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    incremental: bool = False

    @property
    def commits(self) -> list[dict[str, Any]]:
        return self.commit_batch.commits

    @property
    def file_changes(self) -> dict[str, list[dict[str, Any]]]:
        return self.commit_batch.file_changes


class GitCollector:
    """Collects Git data for repositories using the Git CLI."""

    def __init__(
        self,
        runner: GitRunner | None = None,
        *,
        history_depth: int = 500,
        include_remote_branches: bool = True,
    ) -> None:
        self.runner = runner or GitRunner()
        self.history_depth = history_depth
        self.include_remote_branches = include_remote_branches

    # ------------------------------------------------------------------ health
    def check_git(self) -> tuple[bool, str | None]:
        """Return ``(available, version)``; never raises."""
        return self.runner.is_available(), self.runner.version

    def require_git(self) -> None:
        self.runner.require_available()

    # --------------------------------------------------------------- collection
    def collect_state(self, path: str | Path, *, name: str | None = None) -> RepositoryState:
        return collect_repository_state(self.runner, str(path), name=name)

    def collect_branches(self, path: str | Path, *, default_branch: str | None = None) -> tuple[list[dict], list[str]]:
        return collect_branches(
            self.runner,
            str(path),
            include_remote=self.include_remote_branches,
            default_branch=default_branch,
        )

    def collect_commits(
        self, path: str | Path, *, since_sha: str | None = None, branch: str | None = None
    ) -> CommitBatch:
        return collect_commits(
            self.runner,
            str(path),
            history_depth=self.history_depth,
            since_sha=since_sha,
            branch=branch,
        )

    def backfill_file_changes(self, path: str | Path, shas: list[str]) -> CommitBatch:
        return collect_file_changes_for(self.runner, str(path), shas)

    def collect(
        self,
        path: str | Path,
        *,
        since_sha: str | None = None,
        include_branches: bool = True,
        include_commits: bool = True,
    ) -> CollectionResult:
        """Collect state, branches, commits and contributors for one repository.

        Failures are reported through :attr:`CollectionResult.warnings` so that one
        problematic repository never stops a scan of the others.
        """
        repository_path = str(path)
        state = self.collect_state(repository_path)
        result = CollectionResult(state=state, warnings=list(state.warnings))
        if not self.runner.is_available():
            raise GitNotFoundError("Git is not available")

        if include_branches:
            branches, warnings = self.collect_branches(repository_path, default_branch=state.default_branch)
            result.branches = branches
            result.warnings.extend(warnings)

        if include_commits:
            batch = self.collect_commits(repository_path, since_sha=since_sha)
            result.commit_batch = batch
            result.incremental = bool(since_sha) and not any("full walk" in warning for warning in batch.warnings)
            result.warnings.extend(batch.warnings)
            result.contributors = aggregate_contributors(batch.commits)

        return result
