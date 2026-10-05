"""Helpers that build *real* Git repositories on disk for the test suite.

These helpers deliberately use the ``git`` CLI through :mod:`subprocess` instead of
the application code, so the tests validate the dashboard rather than validating
itself.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

GIT_ENV = {
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_AUTHOR_NAME": "Test Author",
    "GIT_AUTHOR_EMAIL": "author@example.com",
    "GIT_COMMITTER_NAME": "Test Author",
    "GIT_COMMITTER_EMAIL": "author@example.com",
    "LC_ALL": "C.UTF-8",
}

AUTHORS = [
    ("Ada Lovelace", "ada@example.com"),
    ("Grace Hopper", "grace@example.com"),
    ("Linus Torvalds", "linus@example.com"),
]

GIT_AVAILABLE = shutil.which("git") is not None


def git(
    *args: str, cwd: Path | None = None, env: dict[str, str] | None = None, check: bool = True
) -> subprocess.CompletedProcess:
    environment = dict(os.environ)
    environment.update(GIT_ENV)
    if env:
        environment.update(env)
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd) if cwd else None,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    if check and result.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result


def init_repo(path: Path, *, bare: bool = False, branch: str = "main") -> Path:
    path.mkdir(parents=True, exist_ok=True)
    if bare:
        git("init", "--bare", str(path))
        git("config", "user.name", "Test Author", cwd=path)
        git("config", "user.email", "author@example.com", cwd=path)
        return path
    git("init", f"--initial-branch={branch}", cwd=path)
    git("config", "user.name", "Test Author", cwd=path)
    git("config", "user.email", "author@example.com", cwd=path)
    return path


def write(repo: Path, relative: str, content: str) -> Path:
    target = repo / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


def commit(
    repo: Path,
    message: str,
    *,
    when: datetime | None = None,
    author: tuple[str, str] | None = None,
    files: dict[str, str] | None = None,
) -> str:
    """Create a commit and return its SHA."""
    moment = (when or datetime.now(timezone.utc)).astimezone(timezone.utc)
    stamp = moment.strftime("%Y-%m-%dT%H:%M:%S+00:00")
    name, email = author or (GIT_ENV["GIT_AUTHOR_NAME"], GIT_ENV["GIT_AUTHOR_EMAIL"])
    for relative, content in (files or {f"file-{abs(hash(message)) % 1000}.txt": f"{message}\n"}).items():
        write(repo, relative, content)
    git("add", "-A", cwd=repo)
    git(
        "commit",
        "--allow-empty",
        "-m",
        message,
        cwd=repo,
        env={
            "GIT_AUTHOR_DATE": stamp,
            "GIT_COMMITTER_DATE": stamp,
            "GIT_AUTHOR_NAME": name,
            "GIT_AUTHOR_EMAIL": email,
            "GIT_COMMITTER_NAME": name,
            "GIT_COMMITTER_EMAIL": email,
        },
    )
    return git("rev-parse", "HEAD", cwd=repo).stdout.strip()


def make_repo(
    path: Path,
    *,
    commits: int = 3,
    days_ago: int = 1,
    commit_span_days: int = 30,
    author_rotation: bool = True,
    dirty: bool = False,
    staged: bool = False,
    untracked: int = 0,
    detached: bool = False,
    bare: bool = False,
    merge_conflict: bool = False,
) -> Path:
    """Create a repository (or bare repository) with a small, deterministic history."""
    repo = init_repo(path, bare=bare)
    if bare:
        # A bare repository needs history pushed into it from a working clone.
        source = path.parent / f"{path.name}-source"
        make_repo(
            source,
            commits=commits,
            days_ago=days_ago,
            commit_span_days=commit_span_days,
            author_rotation=author_rotation,
        )
        git("remote", "add", "origin", str(path), cwd=source)
        git("push", "-u", "origin", "main", cwd=source)
        git("symbolic-ref", "HEAD", "refs/heads/main", cwd=path)
        shutil.rmtree(source, ignore_errors=True)
        return repo

    now = datetime.now(timezone.utc)
    start = now - timedelta(days=days_ago + commit_span_days)
    span = max(commit_span_days, 1)
    for index in range(commits):
        when = start + timedelta(days=(span / max(commits, 1)) * index)
        author = AUTHORS[index % len(AUTHORS)] if author_rotation else AUTHORS[0]
        commit(
            repo,
            f"commit {index + 1}",
            when=when,
            author=author,
            files={
                f"src/module_{index}.py": f"# module {index}\nvalue = {index}\n",
                "README.md": f"# {path.name}\n\niteration {index}\n",
            },
        )

    if dirty:
        # Modify a tracked file so the working tree is dirty.
        write(repo, "README.md", "# modified but not committed\n")
    if staged:
        write(repo, "src/staged_change.py", "# staged\n")
        git("add", "src/staged_change.py", cwd=repo)
    for index in range(untracked):
        write(repo, f"untracked_{index}.txt", "untracked\n")
    if detached:
        git("checkout", "--detach", "HEAD", cwd=repo)
    if merge_conflict:
        git("checkout", "-b", "conflict-branch", cwd=repo)
        write(repo, "README.md", "conflicting content\n")
        git("add", "README.md", cwd=repo)
        commit(repo, "conflicting commit")
    return repo


def add_branch(repo: Path, name: str, *, days_ago: int = 1, extra_commit: bool = True) -> None:
    """Create a branch whose tip is ``days_ago`` days old."""
    git("checkout", "-b", name, cwd=repo)
    if extra_commit:
        commit(
            repo,
            f"start {name}",
            when=datetime.now(timezone.utc) - timedelta(days=days_ago),
            files={f"docs/{name.replace('/', '-')}.md": f"# {name}\n"},
        )
    git("checkout", "main", cwd=repo)
