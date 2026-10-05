"""Repository discovery (Epic E2).

Two entry points:

* :func:`discover_repositories` walks configured root directories and reports every
  Git repository found below them (E2-S2).
* :func:`inspect_path` validates a single path that the user typed in or registered
  manually (E2-S1).

Discovery never raises for an unreadable directory: permission errors are logged and
the traversal continues.
"""

from __future__ import annotations

import contextlib
import os
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from ..logging_config import get_logger

log = get_logger("collectors.discovery")


@dataclass(slots=True)
class DiscoveredRepository:
    """A Git repository found on disk (before it is registered/scanned)."""

    path: Path
    name: str
    is_bare: bool = False
    already_registered: bool = False
    error: str | None = None

    @property
    def path_key(self) -> str:
        return path_key(self.path)

    def to_dict(self) -> dict[str, object]:
        return {
            "path": str(self.path),
            "name": self.name,
            "is_bare": self.is_bare,
            "already_registered": self.already_registered,
            "error": self.error,
        }


@dataclass(slots=True)
class DiscoveryResult:
    root: str
    repositories: list[DiscoveredRepository] = field(default_factory=list)
    visited_dirs: int = 0
    skipped_dirs: int = 0
    errors: list[str] = field(default_factory=list)
    duration_ms: int = 0

    def to_dict(self) -> dict[str, object]:
        return {
            "root": self.root,
            "repositories": [repo.to_dict() for repo in self.repositories],
            "visited_dirs": self.visited_dirs,
            "skipped_dirs": self.skipped_dirs,
            "errors": self.errors,
            "duration_ms": self.duration_ms,
            "count": len(self.repositories),
        }


def path_key(path: str | os.PathLike[str]) -> str:
    """Case-folded, normalised key used to detect duplicate repositories.

    Windows and macOS treat paths case-insensitively; normalising here means the
    same repository cannot be registered twice through different spellings.
    """
    text = os.path.normpath(os.path.abspath(str(path)))
    if os.name == "nt" or (os.path.exists(text) and _is_case_insensitive(text)):
        text = text.lower()
    return text


def _is_case_insensitive(path: str) -> bool:
    probe = Path(path)
    name = probe.name
    if not name:
        return False
    try:
        return any(entry.name == name and entry.name.lower() != name for entry in probe.parent.iterdir())
    except OSError:
        return False


def is_git_repository(path: str | os.PathLike[str]) -> tuple[bool, bool]:
    """Return ``(is_repository, is_bare)`` using filesystem inspection only.

    ``pathlib`` re-raises ``EACCES`` from ``is_dir()``/``is_file()`` (unlike
    ``ENOENT``), so the whole inspection is guarded: an unreadable directory is
    simply "not a repository" and never an exception.
    """
    candidate = Path(path)
    try:
        if not candidate.is_dir():
            return False, False

        git_entry = candidate / ".git"
        if git_entry.is_dir():
            return True, False
        if git_entry.is_file():
            # Submodules and worktrees store a `gitdir: <path>` pointer file.
            try:
                content = git_entry.read_text(encoding="utf-8", errors="replace").strip()
            except OSError:
                return False, False
            return content.lower().startswith("gitdir:"), False

        # Bare repository: HEAD, objects/ and refs/ live directly in the directory.
        if (candidate / "HEAD").is_file() and (candidate / "objects").is_dir() and (candidate / "refs").is_dir():
            return True, True
    except OSError:
        return False, False
    return False, False


def inspect_path(path: str | os.PathLike[str]) -> DiscoveredRepository:
    """Validate a single user supplied path (E2-S1)."""
    raw = Path(os.path.expanduser(str(path)))
    try:
        resolved = raw.resolve(strict=False)
    except OSError:
        resolved = raw

    if not str(path).strip():
        return DiscoveredRepository(path=resolved, name=resolved.name or str(resolved), error="Path must not be empty")
    if not resolved.exists():
        return DiscoveredRepository(path=resolved, name=resolved.name or str(resolved), error=f"Path does not exist: {resolved}")
    if not resolved.is_dir():
        return DiscoveredRepository(path=resolved, name=resolved.name or str(resolved), error=f"Not a directory: {resolved}")
    if not os.access(resolved, os.R_OK | os.X_OK):
        return DiscoveredRepository(path=resolved, name=resolved.name or str(resolved), error=f"Directory is not readable: {resolved}")

    is_repo, is_bare = is_git_repository(resolved)
    if not is_repo:
        return DiscoveredRepository(
            path=resolved,
            name=resolved.name or str(resolved),
            error=f"No Git repository found at {resolved} (missing .git directory)",
        )
    return DiscoveredRepository(path=resolved, name=resolved.name or str(resolved), is_bare=is_bare)


def _normalised_exclusions(excluded_dirs: Iterable[str]) -> set[str]:
    return {entry.strip().lower().rstrip("/\\") for entry in excluded_dirs if entry and entry.strip()}


def walk_repositories(
    root: str | os.PathLike[str],
    *,
    excluded_dirs: Sequence[str] = (".git",),
    max_depth: int = 6,
) -> DiscoveryResult:
    """Walk ``root`` and yield every Git repository below it."""
    root_path = Path(os.path.expanduser(str(root)))
    result = DiscoveryResult(root=str(root_path))
    with contextlib.suppress(OSError):
        root_path = root_path.resolve(strict=False)

    if not root_path.exists() or not root_path.is_dir():
        message = f"{root_path} is not an existing directory"
        log.warning("discovery skipped: %s", message)
        result.errors.append(message)
        return result

    exclusions = _normalised_exclusions(excluded_dirs)
    seen: set[str] = set()
    queue: list[tuple[Path, int]] = [(root_path, 0)]

    while queue:
        current, depth = queue.pop()
        try:
            key = str(current.resolve(strict=False))
        except OSError:
            key = str(current)
        if key in seen:
            continue
        seen.add(key)

        try:
            is_repo, is_bare = is_git_repository(current)
        except OSError as exc:  # defensive: is_git_repository already guards OSError
            log.warning("discovery cannot inspect %s (%s)", current, exc)
            result.errors.append(f"cannot inspect {current}: {exc}")
            result.skipped_dirs += 1
            continue
        if is_repo:
            result.repositories.append(
                DiscoveredRepository(path=current, name=current.name or str(current), is_bare=is_bare)
            )

        if depth >= max_depth:
            continue

        try:
            entries = sorted(os.scandir(current), key=lambda entry: entry.name.lower())
        except PermissionError as exc:
            message = f"permission denied: {current}"
            log.warning("discovery %s (%s)", message, exc)
            result.errors.append(message)
            result.skipped_dirs += 1
            continue
        except OSError as exc:
            message = f"cannot read {current}: {exc}"
            log.warning("discovery %s", message)
            result.errors.append(message)
            result.skipped_dirs += 1
            continue

        for entry in entries:
            try:
                if entry.is_symlink():
                    continue  # avoids symlink loops
                if not entry.is_dir(follow_symlinks=False):
                    continue
            except OSError:
                continue
            if entry.name.lower() in exclusions:
                result.skipped_dirs += 1
                continue
            result.visited_dirs += 1
            queue.append((Path(entry.path), depth + 1))

    result.repositories.sort(key=lambda repo: str(repo.path).lower())
    log.info("discovery finished for %s: %d repositories (%d dirs visited)", root_path, len(result.repositories), result.visited_dirs)
    return result


def discover_repositories(
    roots: Sequence[str | os.PathLike[str]],
    *,
    excluded_dirs: Sequence[str] = (".git",),
    max_depth: int = 6,
) -> list[DiscoveryResult]:
    """Walk several roots, de-duplicating repositories by normalised path."""
    results: list[DiscoveryResult] = []
    seen: set[str] = set()
    for root in roots:
        result = walk_repositories(root, excluded_dirs=excluded_dirs, max_depth=max_depth)
        unique: list[DiscoveredRepository] = []
        for repository in result.repositories:
            key = repository.path_key
            if key in seen:
                continue
            seen.add(key)
            unique.append(repository)
        result.repositories = unique
        results.append(result)
    return results


def iter_repository_paths(
    roots: Sequence[str | os.PathLike[str]],
    *,
    excluded_dirs: Sequence[str] = (".git",),
    max_depth: int = 6,
) -> Iterator[Path]:
    for result in discover_repositories(roots, excluded_dirs=excluded_dirs, max_depth=max_depth):
        for repository in result.repositories:
            yield repository.path
