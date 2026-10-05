"""Repository registration, discovery and lookup (Epic E2)."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from ..collectors.discovery import (
    DiscoveredRepository,
    DiscoveryResult,
    inspect_path,
    path_key,
    walk_repositories,
)
from ..config import Settings
from ..database.store import Store
from ..logging_config import get_logger

log = get_logger("services.repository")


class RepositoryError(ValueError):
    """Raised for invalid repository registrations (message is user facing)."""


class RepositoryService:
    """Business logic for the repository registry."""

    def __init__(self, store: Store, settings: Settings) -> None:
        self.store = store
        self.settings = settings

    # ------------------------------------------------------------------ lookup
    def all(self, **kwargs) -> list[dict[str, Any]]:
        return self.store.list_repositories(**kwargs)

    def get(self, repository_id: int) -> dict[str, Any]:
        repository = self.store.get_repository(repository_id)
        if not repository:
            raise RepositoryError(f"Repository {repository_id} is not registered")
        return repository

    def get_by_path(self, path: str) -> dict[str, Any] | None:
        return self.store.get_repository_by_path(path_key(path))

    def summary(self) -> dict[str, Any]:
        return self.store.repository_summary()

    # -------------------------------------------------------------- registration
    def add(self, path: str, *, name: str | None = None, allow_duplicate: bool = False) -> dict[str, Any]:
        """Register a local Git repository (E2-S1).

        Validates the path, requires a ``.git`` directory, normalises the absolute
        path and rejects duplicates.
        """
        if not path or not str(path).strip():
            raise RepositoryError("A repository path is required")

        candidate = inspect_path(path)
        if candidate.error:
            raise RepositoryError(candidate.error)

        key = candidate.path_key
        existing = self.store.get_repository_by_path(key)
        if existing and not allow_duplicate:
            raise RepositoryError(f"Repository is already registered as '{existing['name']}' (id {existing['id']})")

        repository_id = self.store.upsert_repository(
            {
                "name": name or candidate.name,
                "path": str(candidate.path),
                "path_key": key,
                "is_bare": candidate.is_bare,
                "state": "bare" if candidate.is_bare else "unknown",
            }
        )
        log.info("registered repository %s at %s (id %s)", name or candidate.name, candidate.path, repository_id)
        return self.get(repository_id)

    def add_many(self, paths: Iterable[str], *, skip_existing: bool = True) -> dict[str, Any]:
        added: list[dict[str, Any]] = []
        skipped: list[dict[str, str]] = []
        for path in paths:
            try:
                repository = self.add(path, allow_duplicate=False)
                added.append(repository)
            except RepositoryError as exc:
                if skip_existing:
                    skipped.append({"path": str(path), "reason": str(exc)})
                    continue
                raise
        return {"added": added, "skipped": skipped}

    def remove(self, repository_id: int) -> dict[str, Any]:
        """Unregister a repository and delete its collected data (cascade)."""
        repository = self.get(repository_id)
        self.store.delete_repository(repository_id)
        log.info("removed repository %s (id %s)", repository["name"], repository_id)
        return repository

    # ---------------------------------------------------------------- discovery
    def discover(
        self,
        *,
        root: str | None = None,
        register: bool = False,
        max_depth: int | None = None,
    ) -> dict[str, Any]:
        """Scan configured roots for repositories (E2-S2)."""
        roots = [root] if root else list(self.settings.repository_roots)
        if not roots:
            raise RepositoryError(
                "No repository roots configured. Add at least one root directory in Settings "
                "(or pass an explicit root path to scan)."
            )

        depth = self.settings.max_scan_depth if max_depth is None else max_depth
        results: list[DiscoveryResult] = []
        seen: set[str] = set()
        for candidate_root in roots:
            result = walk_repositories(
                candidate_root,
                excluded_dirs=self.settings.excluded_dirs,
                max_depth=depth,
            )
            unique: list[DiscoveredRepository] = []
            for repository in result.repositories:
                key = repository.path_key
                if key in seen:
                    continue
                seen.add(key)
                repository.already_registered = self.store.get_repository_by_path(key) is not None
                unique.append(repository)
            result.repositories = unique
            results.append(result)

        payload: dict[str, Any] = {
            "roots": [result.to_dict() for result in results],
            "count": sum(len(result.repositories) for result in results),
            "errors": [error for result in results for error in result.errors],
        }
        if register:
            paths = [
                str(repository.path)
                for result in results
                for repository in result.repositories
                if not repository.already_registered
            ]
            registration = self.add_many(paths)
            payload["registration"] = {
                "added": [
                    {"id": repo["id"], "name": repo["name"], "path": repo["path"]} for repo in registration["added"]
                ],
                "skipped": registration["skipped"],
            }
            payload["registered_count"] = len(registration["added"])
        return payload

    def suggestions(self, *, limit: int = 50) -> list[dict[str, Any]]:
        """Repositories visible under the configured roots that are not registered yet."""
        suggestions: list[dict[str, Any]] = []
        for root in self.settings.repository_roots:
            result = walk_repositories(
                root,
                excluded_dirs=self.settings.excluded_dirs,
                max_depth=self.settings.max_scan_depth,
            )
            for repository in result.repositories:
                if self.store.get_repository_by_path(repository.path_key):
                    continue
                suggestions.append(repository.to_dict())
                if len(suggestions) >= limit:
                    return suggestions
        return suggestions

    def known_paths(self) -> set[str]:
        return {row["path_key"] for row in self.store.list_repositories()}

    def resolve_root(self, root: str) -> Path:
        return self.settings.resolve_path(root)
