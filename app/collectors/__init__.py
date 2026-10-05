"""Collectors: repository discovery and Git CLI data extraction."""

from .collector import CollectionResult, GitCollector
from .contributors import aggregate_contributors, shortlog_contributors
from .discovery import (
    DiscoveredRepository,
    DiscoveryResult,
    discover_repositories,
    inspect_path,
    is_git_repository,
    path_key,
    walk_repositories,
)
from .git_runner import GitError, GitNotFoundError, GitResult, GitRunner

__all__ = [
    "CollectionResult",
    "DiscoveredRepository",
    "DiscoveryResult",
    "GitCollector",
    "GitError",
    "GitNotFoundError",
    "GitResult",
    "GitRunner",
    "aggregate_contributors",
    "discover_repositories",
    "inspect_path",
    "is_git_repository",
    "path_key",
    "shortlog_contributors",
    "walk_repositories",
]
