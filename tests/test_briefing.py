"""Briefing tests: the dashboard narrative must never invent a number.

`build_briefing` is a pure function over values the dashboard already computed,
so these tests feed it hand-built inputs and check the sentences it produces: the
counts must match the input, the order must be severity-first, the line list must
stay bounded, and a missing value must drop its sentence instead of guessing.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.analyzers.briefing import MAX_LINES, build_briefing

NOW = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)


def cards(**overrides):
    base = {
        "repositories": 4,
        "uncommitted_changes": 0,
        "dirty_repositories": 0,
        "branches": 8,
        "stale_branches": 0,
        "commits": 120,
        "commits_last_30d": 12,
        "contributors": 3,
        "stale_repositories": 0,
        "failing_repositories": 0,
        "average_health": 82.5,
        "detached_repositories": 0,
        "abandoned_repositories": 0,
    }
    base.update(overrides)
    return base


def repository(**overrides):
    base = {
        "id": 1,
        "name": "demo",
        "state": "clean",
        "staleness": "active",
        "days_since_last_commit": 1,
        "uncommitted_files": 0,
        "detached_head": 0,
    }
    base.update(overrides)
    return base


def insight(**overrides):
    base = {
        "severity": "warning",
        "code": "stale_branches",
        "message": "2 branch(es) have not changed in 90 days.",
        "action": "Review and delete stale branches.",
        "repository_id": 1,
        "repository_name": "demo",
    }
    base.update(overrides)
    return base


def test_empty_workspace_briefing_is_neutral() -> None:
    briefing = build_briefing(cards=cards(repositories=0), insights=[], repositories=[], now=NOW)
    assert briefing["tone"] == "neutral"
    assert briefing["headline"] == "Nothing to read yet"
    assert briefing["lines"] == []
    assert briefing["next_action"] is None
    assert briefing["last_scan"] is None
    assert briefing["counts"]["repositories"] == 0
    assert briefing["generated_at"] == "2026-06-15T12:00:00Z"


def test_clean_workspace_says_nothing_needs_attention() -> None:
    repositories = [repository(id=index + 1, name=f"repo-{index}") for index in range(4)]
    briefing = build_briefing(cards=cards(), insights=[], repositories=repositories, now=NOW)
    assert briefing["tone"] == "ok"
    assert briefing["headline"] == "Nothing needs attention"
    assert [line["code"] for line in briefing["lines"]] == ["activity"]
    assert briefing["lines"][0]["severity"] == "info"
    assert "12 commits" in briefing["lines"][0]["text"]
    assert briefing["summary"] == "4 of 4 repositories moved within 30 days; 0 did not."


def test_findings_are_ordered_by_severity_and_capped() -> None:
    repositories = [
        repository(id=1, name="dirty-one", uncommitted_files=3),
        repository(id=2, name="detached-one", detached_head=1),
        repository(id=3, name="cold-one", staleness="abandoned", days_since_last_commit=400),
        repository(id=4, name="broken-one", state="error", last_error="git exploded"),
    ]
    briefing = build_briefing(
        cards=cards(
            uncommitted_changes=3,
            dirty_repositories=1,
            detached_repositories=1,
            stale_repositories=1,
            abandoned_repositories=1,
            failing_repositories=1,
            stale_branches=5,
            commits_last_30d=0,
        ),
        insights=[
            insight(severity="info", code="no_remote"),
            insight(severity="warning", code="uncommitted", action="Commit or stash."),
            insight(severity="error", code="scan_error", action="Re-run the scan."),
        ],
        repositories=repositories,
        now=NOW,
    )
    assert len(briefing["lines"]) <= MAX_LINES
    severities = [line["severity"] for line in briefing["lines"]]
    assert severities == sorted(severities, key=lambda value: {"error": 0, "warning": 1, "info": 2}[value])
    assert briefing["lines"][0]["code"] == "scan_failures"
    assert briefing["lines"][0]["text"] == "1 repository failed its last scan: broken-one."
    codes = {line["code"] for line in briefing["lines"]}
    assert {"scan_failures", "uncommitted", "detached_head", "decay", "stale_branches"} <= codes
    assert briefing["tone"] == "danger"
    assert briefing["headline"] == "1 finding needs a decision"
    assert briefing["counts"] == {
        "repositories": 4,
        "active": 3,
        "quiet": 1,
        "error": 1,
        "warning": 1,
        "info": 1,
        "failing": 1,
    }


def test_numbers_in_the_text_match_the_inputs() -> None:
    repositories = [
        repository(id=7, name="infra", uncommitted_files=4, days_since_last_commit=9),
        repository(id=8, name="old", staleness="stale", days_since_last_commit=155),
        repository(id=9, name="older", staleness="abandoned", days_since_last_commit=403),
    ]
    briefing = build_briefing(
        cards=cards(
            repositories=3,
            uncommitted_changes=4,
            dirty_repositories=1,
            detached_repositories=0,
            stale_repositories=2,
            abandoned_repositories=1,
            stale_branches=8,
            commits_last_30d=41,
            average_health=71.0,
        ),
        insights=[],
        repositories=repositories,
        quiet_after_days=30,
        stale_branch_days=90,
        now=NOW,
    )
    text = " ".join(line["text"] for line in briefing["lines"])
    assert "4 uncommitted files" in text
    assert "1 repository" in text
    assert "2 repositories have stopped moving" in text
    assert "'older' at 403 days" in text
    assert "8 local branches have not changed in at least 90 days" in text
    assert "41 commits landed in the last 30 days across 1 repository" in text
    decay = next(line for line in briefing["lines"] if line["code"] == "decay")
    assert decay["repository_id"] == 9 and decay["repository_name"] == "older"
    assert briefing["summary"] == "1 of 3 repositories moved within 30 days; 2 did not."


def test_low_average_health_is_a_decision_without_error_insights() -> None:
    briefing = build_briefing(
        cards=cards(average_health=31.5),
        insights=[],
        repositories=[repository(staleness="stale", days_since_last_commit=200)],
        now=NOW,
    )
    assert briefing["tone"] == "danger"
    assert briefing["headline"] == "Average health is 31.5/100"
    assert briefing["counts"]["error"] == 0


def test_next_action_follows_the_first_insight_with_an_action() -> None:
    briefing = build_briefing(
        cards=cards(failing_repositories=1),
        insights=[
            insight(
                severity="error", code="scan_error", action="Re-run the scan from the repository page.", repository_id=4
            ),
            insight(severity="warning", code="uncommitted", action="Commit or stash."),
        ],
        repositories=[repository(id=4, name="broken", state="error")],
        now=NOW,
    )
    assert briefing["next_action"] == {
        "text": "Re-run the scan from the repository page.",
        "reason": "2 branch(es) have not changed in 90 days.",
        "severity": "error",
        "repository_id": 4,
        "repository_name": "demo",
    }


def test_missing_values_drop_their_sentence_instead_of_guessing() -> None:
    # No card totals at all: only the sentences whose inputs are present survive.
    briefing = build_briefing(cards=None, insights=None, repositories=None, now=NOW)
    assert briefing["tone"] == "neutral"
    assert briefing["lines"] == []
    assert briefing["counts"]["repositories"] == 0

    # A repository list without the derived fields still produces no false claims.
    briefing = build_briefing(
        cards=cards(repositories=2, stale_repositories=1, uncommitted_changes=0, dirty_repositories=0),
        insights=[],
        repositories=[{"id": 1, "name": "no-fields"}, {"id": 2, "name": "also-none"}],
        now=NOW,
    )
    assert [line["code"] for line in briefing["lines"]] == ["activity"]
    assert briefing["counts"]["active"] == 0
    assert briefing["counts"]["quiet"] == 2


def test_last_scan_prefers_the_live_job_and_falls_back_to_history() -> None:
    job = {
        "job": {
            "kind": "full",
            "status": "completed",
            "finished_at": "2026-06-15T11:59:00Z",
            "commits_added": 7,
            "progress": {"done": 3, "total": 3},
            "report": {"scanned": 3, "failed": 0, "commits_added": 7, "duration_ms": 250},
        }
    }
    briefing = build_briefing(cards=cards(), insights=[], repositories=[], scan=job, now=NOW)
    assert briefing["last_scan"] == {
        "source": "job",
        "kind": "full",
        "status": "completed",
        "finished_at": "2026-06-15T11:59:00Z",
        "scanned": 3,
        "failed": 0,
        "commits_added": 7,
        "duration_ms": 250,
    }

    stored = {
        "kind": "full",
        "status": "completed",
        "started_at": "2026-06-15T10:00:00Z",
        "completed_at": "2026-06-15T10:00:01Z",
        "duration_ms": 900,
        "records_processed": 12,
        "commits_added": 12,
        "repositories_scanned": 4,
        "repositories_failed": 1,
    }
    briefing = build_briefing(cards=cards(), insights=[], repositories=[], stored_scan=stored, now=NOW)
    assert briefing["last_scan"] == {
        "source": "history",
        "kind": "full",
        "status": "completed",
        "finished_at": "2026-06-15T10:00:01Z",
        "scanned": 4,
        "failed": 1,
        "commits_added": 12,
        "duration_ms": 900,
    }
