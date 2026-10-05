"""Dashboard briefing: the short, opinionated story told before the tables.

The briefing is the first thing the dashboard shows and the only part that
*judges*: it states how many findings need a decision, what the workspace looks
like as a whole, and what to do first.

It is a pure function over values the dashboard already computed (the card
totals, the insight list, the enriched repository rows, the last scan job and the
activity summary), so it never queries anything and never estimates. Every number
in every sentence comes from that input; if a value is missing, the sentence that
would have used it is dropped rather than filled in.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}
MAX_LINES = 5


# ------------------------------------------------------------------- helpers
def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _as_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _plural(count: int, singular: str, plural: str | None = None) -> str:
    return f"{count} {singular if count == 1 else (plural or singular + 's')}"


def _list_names(names: Sequence[str], limit: int = 3) -> str:
    shown = [str(name) for name in names[:limit]]
    if not shown:
        return ""
    if len(shown) == 1:
        return shown[0]
    return f"{', '.join(shown[:-1])} and {shown[-1]}"


def _count(insights: Sequence[Mapping[str, Any]], severity: str) -> int:
    return sum(1 for item in insights if item.get("severity") == severity)


def _line(
    severity: str,
    code: str,
    text: str,
    *,
    action: str | None = None,
    repository_id: int | None = None,
    repository_name: str | None = None,
) -> dict[str, Any]:
    return {
        "severity": severity,
        "code": code,
        "text": text,
        "action": action,
        "repository_id": repository_id,
        "repository_name": repository_name,
    }


def _active_within(repositories: Sequence[Mapping[str, Any]], days: int) -> list[Mapping[str, Any]]:
    return [
        row
        for row in repositories
        if row.get("days_since_last_commit") is not None and _as_int(row.get("days_since_last_commit")) <= days
    ]


def _coldest(repositories: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    decaying = [row for row in repositories if row.get("staleness") in {"stale", "abandoned"}]
    if not decaying:
        return None
    return max(decaying, key=lambda row: _as_int(row.get("days_since_last_commit")))


def _last_scan(scan: Mapping[str, Any] | None, stored_run: Mapping[str, Any] | None = None) -> dict[str, Any] | None:
    """Summarise the most recent scan.

    Prefers the in-memory job (it knows progress and the freshly added commits)
    and falls back to the persisted ``scan_runs`` row, which survives a restart.
    """
    job = (scan or {}).get("job") or {}
    if job:
        report = job.get("report") or {}
        return {
            "source": "job",
            "kind": job.get("kind"),
            "status": job.get("status"),
            "finished_at": job.get("finished_at"),
            "scanned": _as_int(report.get("scanned")) or _as_int((job.get("progress") or {}).get("done")),
            "failed": _as_int(report.get("failed")),
            "commits_added": _as_int(job.get("commits_added")) or _as_int(report.get("commits_added")),
            "duration_ms": _as_int(report.get("duration_ms")),
        }
    if stored_run:
        return {
            "source": "history",
            "kind": stored_run.get("kind"),
            "status": stored_run.get("status"),
            "finished_at": stored_run.get("completed_at") or stored_run.get("started_at"),
            "scanned": _as_int(stored_run.get("repositories_scanned")),
            "failed": _as_int(stored_run.get("repositories_failed")),
            "commits_added": _as_int(stored_run.get("commits_added")),
            "duration_ms": _as_int(stored_run.get("duration_ms")),
        }
    return None


# ------------------------------------------------------------------- briefing
def build_briefing(
    *,
    cards: Mapping[str, Any] | None,
    insights: Sequence[Mapping[str, Any]] | None,
    repositories: Sequence[Mapping[str, Any]] | None,
    scan: Mapping[str, Any] | None = None,
    stored_scan: Mapping[str, Any] | None = None,
    activity: Mapping[str, Any] | None = None,
    quiet_after_days: int = 30,
    stale_branch_days: int = 90,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Compose the dashboard briefing from already-computed dashboard values."""
    reference = now or datetime.now(timezone.utc)
    cards = dict(cards or {})
    insights = list(insights or [])
    repositories = list(repositories or [])
    activity_summary = (activity or {}).get("summary") or {}

    total = _as_int(cards.get("repositories")) or len(repositories)
    errors = _count(insights, "error")
    warnings = _count(insights, "warning")
    advisory = _count(insights, "info")
    failing = _as_int(cards.get("failing_repositories"))
    dirty = _as_int(cards.get("dirty_repositories"))
    uncommitted = _as_int(cards.get("uncommitted_changes"))
    detached = _as_int(cards.get("detached_repositories"))
    stale_repositories = _as_int(cards.get("stale_repositories"))
    abandoned = _as_int(cards.get("abandoned_repositories"))
    stale_branches = _as_int(cards.get("stale_branches"))
    commits_30d = _as_int(cards.get("commits_last_30d"))
    average_health = _as_float(cards.get("average_health"))

    active = _active_within(repositories, quiet_after_days)
    quiet = max(0, total - len(active))

    # ---------------------------------------------------------------- lines
    ranked: list[tuple[int, int, dict[str, Any]]] = []

    def add(severity: str, code: str, text: str, action: str | None, order: int, **extra: Any) -> None:
        ranked.append((SEVERITY_ORDER.get(severity, 3), order, _line(severity, code, text, action=action, **extra)))

    if failing:
        broken = [row.get("name", "?") for row in repositories if row.get("state") == "error"]
        add(
            "error",
            "scan_failures",
            f"{_plural(failing, 'repository', 'repositories')} failed {'its' if failing == 1 else 'their'} last scan"
            + (f": {_list_names(broken)}." if broken else "."),
            "Open the repository and run the scan again.",
            0,
        )
    if uncommitted and dirty:
        dirty_rows = [row for row in repositories if _as_int(row.get("uncommitted_files"))]
        add(
            "warning",
            "uncommitted",
            f"{_plural(uncommitted, 'uncommitted file')} sit in {_plural(dirty, 'repository', 'repositories')}"
            + (f": {_list_names([row.get('name', '?') for row in dirty_rows])}." if dirty_rows else "."),
            "Commit or stash them before the next change lands on top.",
            1,
            repository_id=dirty_rows[0].get("id") if len(dirty_rows) == 1 else None,
            repository_name=dirty_rows[0].get("name") if len(dirty_rows) == 1 else None,
        )
    if detached:
        detached_names = [row.get("name", "?") for row in repositories if row.get("detached_head")]
        add(
            "warning",
            "detached_head",
            f"{_plural(detached, 'repository', 'repositories')} on a detached HEAD"
            + (f": {_list_names(detached_names)}." if detached_names else "."),
            "Check out a branch so commits are not lost.",
            2,
        )
    coldest = _coldest(repositories)
    if stale_repositories and coldest is not None:
        days = _as_int(coldest.get("days_since_last_commit"))
        add(
            "error" if abandoned else "warning",
            "decay",
            f"{_plural(stale_repositories, 'repository', 'repositories')} have stopped moving; the coldest is "
            f"'{coldest.get('name', '?')}' at {days} days.",
            "Archive, revive or unregister them.",
            3,
            repository_id=coldest.get("id"),
            repository_name=coldest.get("name"),
        )
    if stale_branches:
        add(
            "warning",
            "stale_branches",
            f"{_plural(stale_branches, 'local branch', 'local branches')} have not changed in at least "
            f"{stale_branch_days} days.",
            "Review them and delete what is already merged.",
            4,
        )
    if total and commits_30d == 0:
        add(
            "warning",
            "no_recent_commits",
            "No commits landed in the last 30 days.",
            "Start with the repository closest to your work.",
            5,
        )
    elif total and commits_30d:
        add(
            "info",
            "activity",
            f"{_plural(commits_30d, 'commit')} landed in the last 30 days across "
            f"{_plural(len(active), 'repository', 'repositories')}.",
            None,
            5,
        )

    lines = [line for _, _, line in sorted(ranked, key=lambda entry: (entry[0], entry[1]))][:MAX_LINES]

    # ------------------------------------------------------------- headline
    if total == 0:
        tone = "neutral"
        headline = "Nothing to read yet"
        summary = "No repositories are registered, so there is nothing to triage."
    else:
        if errors or failing or abandoned or (average_health and average_health < 40):
            tone = "danger"
        elif warnings or (average_health and average_health < 60):
            tone = "warn"
        else:
            tone = "ok"
        if tone == "danger":
            if errors:
                headline = f"{_plural(errors, 'finding')} {'needs' if errors == 1 else 'need'} a decision"
            elif failing:
                headline = (
                    f"{_plural(failing, 'repository', 'repositories')} {'needs' if failing == 1 else 'need'} a decision"
                )
            else:
                # Dangerous only because of the average score: say so instead of
                # reporting a finding count of zero.
                headline = f"Average health is {average_health:g}/100"
        elif tone == "warn":
            headline = (
                f"{_plural(warnings, 'finding')} to review" if warnings else f"Average health is {average_health:g}/100"
            )
        else:
            headline = "Nothing needs attention"
        summary = f"{len(active)} of {total} repositories moved within {quiet_after_days} days; {quiet} did not." + (
            f" {_plural(_as_int(activity_summary.get('total')), 'commit')} in the last "
            f"{_as_int((activity or {}).get('days')) or 30} days."
            if activity_summary
            else ""
        )

    # ---------------------------------------------------------- next action
    next_action = None
    for item in insights:
        if item.get("action"):
            next_action = {
                "text": item["action"],
                "reason": item.get("message"),
                "severity": item.get("severity", "info"),
                "repository_id": item.get("repository_id"),
                "repository_name": item.get("repository_name"),
            }
            break

    return {
        "generated_at": reference.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "tone": tone,
        "headline": headline,
        "summary": summary,
        "lines": lines,
        "next_action": next_action,
        "last_scan": _last_scan(scan, stored_scan),
        "counts": {
            "repositories": total,
            "active": len(active),
            "quiet": quiet,
            "error": errors,
            "warning": warnings,
            "info": advisory,
            "failing": failing,
        },
    }
