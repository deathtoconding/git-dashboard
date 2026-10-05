"""Presentation helpers shared by API routes.

The database stores raw repository rows. Several endpoints return them to the
UI, which needs derived, ready-to-render fields (staleness bucket, days since
the last commit, a health summary). Keeping that enrichment in one place means
``/api/repositories`` and ``/api/dashboard`` describe the same repository
identically.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..analyzers.health import repository_staleness
from ..analyzers.metrics import parse_timestamp


def enrich_repository(repository: dict[str, Any], services: Any, *, now: datetime | None = None) -> dict[str, Any]:
    """Attach derived, UI-ready fields to a repository row.

    The input row is not modified; a new dict is returned.
    """
    reference = now or datetime.now(timezone.utc)
    last_dt = parse_timestamp(repository.get("last_commit_at"))
    days_since = (reference - last_dt).days if last_dt else None
    staleness = repository_staleness(
        repository, days_since_last_commit=days_since, settings=services.settings, now=reference
    )
    scan_dt = parse_timestamp(repository.get("last_scanned_at"))
    return {
        **repository,
        "days_since_last_commit": days_since,
        "days_since_scan": (reference - scan_dt).days if scan_dt else None,
        "staleness": staleness["bucket"],
        "staleness_label": staleness["label"],
        "staleness_message": staleness["message"],
        "health": {
            "score": round(float(repository.get("health_score") or 0), 1),
            "grade": repository.get("health_grade") or "F",
        },
        "is_scanned": bool(repository.get("last_scanned_at")),
    }
