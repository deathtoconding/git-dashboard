"""Repository discovery tests (E2-S1, E2-S2) and Git command safety (E3-S1)."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from app.collectors.discovery import (
    discover_repositories,
    inspect_path,
    is_git_repository,
    path_key,
    walk_repositories,
)
from app.collectors.git_runner import GitNotFoundError, GitRunner
from tests import helpers
from tests.conftest import requires_git


# --------------------------------------------------------------------- E2-S1
@requires_git
def test_inspect_path_accepts_a_repository(repo_factory) -> None:
    repo = repo_factory("valid")
    discovered = inspect_path(repo)
    assert discovered.error is None
    assert discovered.path == repo.resolve()
    assert discovered.name == "valid"
    assert discovered.is_bare is False


@requires_git
def test_inspect_path_accepts_a_bare_repository(repo_factory) -> None:
    bare = repo_factory("bare.git", bare=True)
    discovered = inspect_path(bare)
    assert discovered.error is None
    assert discovered.is_bare is True


def test_inspect_path_rejects_missing_path(tmp_path: Path) -> None:
    discovered = inspect_path(tmp_path / "nope")
    assert discovered.error and "does not exist" in discovered.error


def test_inspect_path_rejects_file(tmp_path: Path) -> None:
    target = tmp_path / "file.txt"
    target.write_text("x")
    assert "Not a directory" in (inspect_path(target).error or "")


def test_inspect_path_rejects_plain_directory(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    error = inspect_path(plain).error or ""
    assert "No Git repository" in error and ".git" in error


def test_inspect_path_requires_a_path() -> None:
    assert inspect_path("   ").error


def test_is_git_repository_detects_gitdir_pointer(tmp_path: Path) -> None:
    """Worktrees and submodules use a `gitdir:` file instead of a `.git` folder."""
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / ".git").write_text("gitdir: /somewhere/else/.git/worktrees/worktree\n")
    assert is_git_repository(worktree) == (True, False)


# --------------------------------------------------------------------- E2-S2
@requires_git
def test_walk_finds_nested_repositories(repo_factory, tmp_path: Path) -> None:
    repo_factory("alpha", commits=2)
    repo_factory("group/beta", commits=2)
    result = walk_repositories(tmp_path / "repos", excluded_dirs=[".git"], max_depth=5)
    names = sorted(repository.name for repository in result.repositories)
    assert names == ["alpha", "beta"]
    assert result.visited_dirs > 0
    assert result.errors == []


@requires_git
def test_walk_ignores_configured_directories(repo_factory, tmp_path: Path) -> None:
    repo_factory("alpha", commits=2)
    nested = tmp_path / "repos" / "node_modules" / "dependency"
    nested.mkdir(parents=True)
    helpers.init_repo(nested)
    helpers.commit(nested, "inside node_modules")

    result = walk_repositories(tmp_path / "repos", excluded_dirs=[".git", "node_modules"], max_depth=6)
    assert [repository.name for repository in result.repositories] == ["alpha"]
    assert result.skipped_dirs >= 1


@requires_git
def test_walk_respects_max_depth(repo_factory, tmp_path: Path) -> None:
    repo_factory("top", commits=1)
    repo_factory("a/b/c/deep", commits=1)
    shallow = walk_repositories(tmp_path / "repos", excluded_dirs=[".git"], max_depth=1)
    assert [repository.name for repository in shallow.repositories] == ["top"]
    deep = walk_repositories(tmp_path / "repos", excluded_dirs=[".git"], max_depth=6)
    assert sorted(repository.name for repository in deep.repositories) == ["deep", "top"]


def test_walk_reports_missing_root(tmp_path: Path) -> None:
    result = walk_repositories(tmp_path / "missing", excluded_dirs=[".git"])
    assert result.repositories == []
    assert result.errors and "not an existing directory" in result.errors[0]


@pytest.mark.skipif(os.name == "nt" or os.geteuid() == 0, reason="permission tests need a non-root POSIX user")
def test_walk_handles_permission_errors(tmp_path: Path) -> None:
    blocked = tmp_path / "blocked"
    blocked.mkdir()
    (blocked / "inner").mkdir()
    os.chmod(blocked, stat.S_IRUSR)  # no read/execute for the owner's traversal
    try:
        result = walk_repositories(tmp_path, excluded_dirs=[".git"], max_depth=3)
        assert result.errors, "permission problem should be reported"
        assert "permission denied" in " ".join(result.errors)
    finally:
        os.chmod(blocked, stat.S_IRWXU)


def test_path_key_normalises_and_dedupes(tmp_path: Path) -> None:
    target = tmp_path / "Repo"
    target.mkdir()
    assert path_key(target) == path_key(tmp_path / "Repo" / "." / ".." / "Repo")
    assert path_key(target).endswith("repo") or path_key(target).endswith("Repo")


@requires_git
def test_discover_repositories_deduplicates_multiple_roots(repo_factory, tmp_path: Path) -> None:
    """Overlapping roots must not report the same repository twice (E2-S2)."""
    repo_factory("alpha", commits=1)
    root = tmp_path / "repos"
    results = discover_repositories([root, root / "alpha"], excluded_dirs=[".git"], max_depth=3)
    assert len(results) == 2
    repositories = [repository for result in results for repository in result.repositories]
    assert len(repositories) == 1
    assert repositories[0].name == "alpha"
    assert results[0].repositories and results[1].repositories == []  # already seen via the parent root


# --------------------------------------------------------------------- E3-S1
@requires_git
def test_git_runner_detects_version(runner: GitRunner) -> None:
    assert runner.is_available() is True
    assert runner.version and runner.version[0].isdigit()


def test_git_runner_missing_binary_raises() -> None:
    runner = GitRunner(binary="/nonexistent/definitely-not-git")
    assert runner.is_available() is False
    with pytest.raises(GitNotFoundError):
        runner.require_available()
    with pytest.raises(GitNotFoundError):
        runner.run(["--version"])


@requires_git
def test_git_runner_returns_failures_instead_of_raising(runner: GitRunner, tmp_path: Path) -> None:
    result = runner.run(["rev-parse", "--git-dir"], cwd=tmp_path)  # not a repository
    assert result.ok is False
    assert result.code != 0
    assert result.failure_reason()


@requires_git
def test_git_runner_never_prompts_for_credentials(runner: GitRunner, tmp_path: Path) -> None:
    env = runner.environment()
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert env["GIT_PAGER"] == "cat"
    assert env["GIT_OPTIONAL_LOCKS"] == "0"


@pytest.mark.skipif(helpers.shutil.which("sleep") is None, reason="needs the sleep binary")
def test_git_runner_times_out_without_hanging(tmp_path: Path) -> None:
    """A hanging command must be killed by the timeout instead of blocking for ever (E11-S3)."""
    runner = GitRunner(binary=helpers.shutil.which("sleep") or "sleep", timeout=1)
    runner._available = True  # bypass the `--version` probe: we intentionally point at `sleep`
    runner._version = "fake"
    result = runner.run(["5"], cwd=tmp_path)
    assert result.timed_out is True
    assert result.ok is False
    assert "timed out" in result.failure_reason()
