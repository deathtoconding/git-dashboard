"""Collector tests against real Git repositories (E3-S2, E3-S3, E3-S4, E3-S5, E10-S3)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.analyzers.branch_health import branch_health_summary, classify_branches
from app.collectors.branches import collect_branches
from app.collectors.collector import GitCollector
from app.collectors.commits import collect_commits
from app.collectors.contributors import aggregate_contributors, merge_contributor_sources, shortlog_contributors
from app.collectors.git_runner import GitNotFoundError
from app.collectors.repo_state import collect_repository_state
from tests import helpers
from tests.conftest import requires_git


# ------------------------------------------------------------------ E2-S3 state
@requires_git
def test_collect_state_for_a_clean_repository(repo_factory, runner) -> None:
    repo = repo_factory("clean", commits=4, days_ago=2, commit_span_days=20)
    state = collect_repository_state(runner, str(repo))
    assert state.state == "clean"
    assert state.current_branch == "main"
    assert state.head_commit and len(state.head_commit) == 40
    assert state.total_commits == 4
    assert state.tracked_files >= 4
    assert state.is_dirty is False
    assert state.detached_head is False
    assert state.first_commit_at and state.last_commit_at
    assert state.age_days >= 1
    assert state.warnings == []


@requires_git
def test_collect_state_for_a_dirty_repository(repo_factory, runner) -> None:
    repo = repo_factory("dirty", commits=2, dirty=True, staged=True, untracked=2)
    state = collect_repository_state(runner, str(repo))
    assert state.is_dirty is True
    assert state.state == "dirty"
    assert state.staged_files == 1
    assert state.untracked_files == 2
    # 1 staged + 1 modified + 2 untracked
    assert state.uncommitted_files == 4
    assert state.staged_files + state.untracked_files <= state.uncommitted_files


@requires_git
def test_collect_state_for_detached_head(repo_factory, runner) -> None:
    repo = repo_factory("detached", commits=5, detached=True)
    state = collect_repository_state(runner, str(repo))
    assert state.detached_head is True
    assert state.state == "detached"
    assert any("detached" in warning.lower() for warning in state.warnings)


@requires_git
def test_collect_state_for_bare_repository(repo_factory, runner) -> None:
    bare = repo_factory("mirror.git", commits=3, bare=True)
    state = collect_repository_state(runner, str(bare))
    assert state.is_bare is True
    assert state.state == "bare"
    assert state.total_commits == 3
    assert state.tracked_files == 0


@requires_git
def test_collect_state_for_repository_without_commits(runner, tmp_path: Path) -> None:
    empty = helpers.init_repo(tmp_path / "empty")
    state = collect_repository_state(runner, str(empty))
    assert state.state == "empty"
    assert state.total_commits == 0
    assert state.head_commit is None
    assert not any("cannot resolve HEAD" in warning for warning in state.warnings)


@requires_git
def test_collect_state_records_remote_url(repo_factory, runner) -> None:
    repo = repo_factory("with-remote", commits=1)
    helpers.git("remote", "add", "origin", "https://example.com/team/with-remote.git", cwd=repo)
    state = collect_repository_state(runner, str(repo))
    assert state.remote_url == "https://example.com/team/with-remote.git"


# ------------------------------------------------------------------- E3-S2 branches
@requires_git
def test_collect_branches_and_classify(runner, repo_factory) -> None:
    repo = repo_factory("branchy", commits=5)
    helpers.add_branch(repo, "feature/recent", days_ago=5)
    helpers.add_branch(repo, "feature/stale", days_ago=200)

    branches, warnings = collect_branches(runner, str(repo))
    assert warnings == []
    names = {branch["name"] for branch in branches}
    assert {"main", "feature/recent", "feature/stale"} <= names
    assert sum(branch["is_current"] for branch in branches) == 1

    classified = classify_branches(branches, inactive_days=30, stale_days=90)
    by_name = {branch["name"]: branch for branch in classified}
    assert by_name["main"]["is_stale"] is False
    assert by_name["main"]["status"] == "current"
    assert by_name["feature/stale"]["is_stale"] is True
    assert by_name["feature/stale"]["status"] == "stale"
    assert by_name["feature/recent"]["status"] == "active"

    summary = branch_health_summary(classified, inactive_days=30, stale_days=90)
    assert summary["local_branches"] == 3
    assert summary["stale_branches"] == 1
    assert summary["stale_ratio"] == pytest.approx(1 / 3, abs=0.01)
    assert "feature/stale" in summary["stale_branch_names"]


@requires_git
def test_collect_branches_marks_merged(runner, repo_factory) -> None:
    repo = repo_factory("merged", commits=3)
    helpers.add_branch(repo, "merged-into-main", days_ago=1)
    helpers.git("merge", "--no-ff", "-m", "merge it", "merged-into-main", cwd=repo)
    branches, _ = collect_branches(runner, str(repo))
    classified = {branch["name"]: branch for branch in classify_branches(branches)}
    assert classified["merged-into-main"]["is_merged"] is True


@requires_git
def test_collect_branches_remote_tracking(runner, repo_factory, tmp_path: Path) -> None:
    origin = repo_factory("origin", commits=2)
    clone = tmp_path / "repos" / "clone"
    helpers.git("clone", str(origin), str(clone))
    branches, warnings = collect_branches(runner, str(clone))
    assert warnings == []
    remote = [branch for branch in branches if branch["is_remote"]]
    assert remote and any(branch["name"].startswith("origin/") for branch in remote)


# ------------------------------------------------------------------- E3-S3 commits
@requires_git
def test_collect_commits_with_file_changes(runner, repo_factory) -> None:
    repo = repo_factory("history", commits=8, author_rotation=True)
    batch = collect_commits(runner, str(repo), history_depth=100)
    assert batch.warnings == []
    assert len(batch.commits) == 8
    for commit in batch.commits:
        assert len(commit["sha"]) == 40
        assert commit["author_name"] and commit["author_email"]
        assert commit["authored_at"].endswith("Z")
        assert commit["subject"].startswith("commit ")
        assert commit["files_changed"] >= 1
    assert set(batch.file_changes) <= {commit["sha"] for commit in batch.commits}
    first = batch.commits[-1]
    assert first["parents"] == "" and first["parent_count"] == 0


@requires_git
def test_collect_commits_incremental_returns_only_new_commits(runner, repo_factory) -> None:
    repo = repo_factory("incremental", commits=5)
    first = collect_commits(runner, str(repo), history_depth=100)
    assert len(first.commits) == 5
    head = first.commits[0]["sha"]

    second = collect_commits(runner, str(repo), history_depth=100, since_sha=head)
    assert second.commits == []  # nothing new since the recorded HEAD

    helpers.commit(repo, "brand new work", files={"src/new.py": "print('new')\n"})
    third = collect_commits(runner, str(repo), history_depth=100, since_sha=head)
    assert len(third.commits) == 1
    assert third.commits[0]["subject"] == "brand new work"


@requires_git
def test_collect_commits_respects_history_depth(runner, repo_factory) -> None:
    repo = repo_factory("capped", commits=12)
    batch = collect_commits(runner, str(repo), history_depth=5)
    assert len(batch.commits) == 5
    assert batch.truncated is True


@requires_git
def test_collect_commits_falls_back_when_since_sha_is_unknown(runner, repo_factory) -> None:
    repo = repo_factory("fallback", commits=3)
    batch = collect_commits(runner, str(repo), history_depth=50, since_sha="f" * 40)
    assert len(batch.commits) == 3
    assert batch.warnings and "full walk" in batch.warnings[0]


@requires_git
def test_collect_commits_on_empty_repository(runner, tmp_path: Path) -> None:
    empty = helpers.init_repo(tmp_path / "empty")
    batch = collect_commits(runner, str(empty), history_depth=10)
    assert batch.commits == []
    assert batch.warnings == []


# -------------------------------------------------------------- E3-S5 contributors
@requires_git
def test_aggregate_contributors_from_commits(runner, repo_factory) -> None:
    repo = repo_factory("team", commits=9, author_rotation=True)
    batch = collect_commits(runner, str(repo), history_depth=50)
    contributors = aggregate_contributors(batch.commits)
    assert len(contributors) == 3
    assert sum(contributor["commits"] for contributor in contributors) == 9
    assert contributors[0]["commits"] >= contributors[-1]["commits"]


@requires_git
def test_shortlog_matches_aggregation(runner, repo_factory) -> None:
    repo = repo_factory("shortlog", commits=9, author_rotation=True)
    shortlog, error = shortlog_contributors(runner, str(repo))
    assert error is None
    assert sum(row["commits"] for row in shortlog) == 9
    assert {row["email"] for row in shortlog} == {"ada@example.com", "grace@example.com", "linus@example.com"}


def test_merge_contributor_sources_sums_counts() -> None:
    merged = merge_contributor_sources(
        [{"name": "Ada", "email": "ada@example.com", "commits": 3, "additions": 1, "deletions": 1}],
        [{"name": "Ada", "email": "ada@example.com", "commits": 2, "additions": 4, "deletions": 0}],
    )
    assert merged[0]["commits"] == 5 and merged[0]["additions"] == 5


# ----------------------------------------------------------------- facade/collect
@requires_git
def test_git_collector_facade_collects_everything(collector: GitCollector, repo_factory) -> None:
    repo = repo_factory("facade", commits=6)
    result = collector.collect(str(repo))
    assert result.state.total_commits == 6
    assert result.branches
    assert len(result.commits) == 6
    assert result.contributors
    assert result.warnings == []
    assert result.incremental is False


@requires_git
def test_git_collector_reports_missing_git(settings) -> None:
    broken = GitCollector.__new__(GitCollector)
    from app.collectors.git_runner import GitRunner

    broken.runner = GitRunner(binary="/nonexistent/git")
    broken.history_depth = 10
    broken.include_remote_branches = True
    assert broken.check_git() == (False, None)
    with pytest.raises(GitNotFoundError):
        broken.require_git()


@requires_git
def test_analyzer_threshold_boundaries(runner, repo_factory) -> None:
    """A branch older than the configured threshold is flagged as stale (E5-S4 AC)."""
    repo = repo_factory("thresholds", commits=4)
    helpers.add_branch(repo, "just-under", days_ago=29)
    helpers.add_branch(repo, "just-over", days_ago=31)
    branches, _ = collect_branches(runner, str(repo))
    classified = {branch["name"]: branch for branch in classify_branches(branches, inactive_days=30, stale_days=90)}
    assert classified["just-under"]["is_stale"] is False
    assert classified["just-over"]["is_inactive"] is True


def test_classify_branch_threshold_logic() -> None:
    now = datetime.now(timezone.utc)
    branch = {
        "name": "ancient",
        "is_remote": False,
        "is_current": False,
        "age_days": 100,
        "last_commit_at": (now - timedelta(days=100)).isoformat().replace("+00:00", "Z"),
    }
    assert classify_branches([branch], inactive_days=30, stale_days=90)[0]["is_stale"] is True
    remote = classify_branches([{**branch, "is_remote": True}], inactive_days=30, stale_days=90)[0]
    assert remote["is_stale"] is False  # remote branches are never "stale" for us
