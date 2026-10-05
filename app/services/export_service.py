"""Export and backup (E12-S4).

Everything is written locally: JSON snapshots, CSV dumps and SQLite backups.
"""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..analyzers.branch_health import branch_health_summary
from ..analyzers.health import repository_health
from ..analyzers.metrics import activity_metrics, change_metrics, repository_metrics
from ..config import Settings
from ..database.store import Store
from ..logging_config import get_logger

log = get_logger("services.export")

EXPORT_TABLES = ("repositories", "branches", "commits", "contributors", "file_changes", "scan_runs")


class ExportService:
    def __init__(self, store: Store, settings: Settings) -> None:
        self.store = store
        self.settings = settings

    # ------------------------------------------------------------------- helpers
    def snapshot(self, *, repository_id: int | None = None, include_commits: bool = True) -> dict[str, Any]:
        """Build a JSON-serialisable snapshot of the dashboard data."""
        repositories = (
            [self.store.get_repository(repository_id)] if repository_id else self.store.list_repositories()
        )
        payload: dict[str, Any] = {
            "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "settings": self.settings.to_dict(include_paths=False),
            "summary": self.store.repository_summary(),
            "repositories": [],
        }
        for repository in repositories:
            if not repository:
                continue
            repo_id = int(repository["id"])
            entry: dict[str, Any] = {
                "repository": repository,
                "metrics": repository_metrics(self.store, repo_id),
                "activity": activity_metrics(self.store, repo_id),
                "changes": change_metrics(self.store, repo_id),
                "health": repository_health(self.store, repository, settings=self.settings),
                "branches": self.store.list_branches(repo_id, include_remote=True),
                "contributors": self.store.list_contributors(repo_id),
                "scan_runs": self.store.list_scan_runs(limit=10, repository_id=repo_id),
            }
            if include_commits:
                commits, _ = self.store.list_commits(repo_id, page=1, per_page=500)
                entry["commits"] = commits
            payload["repositories"].append(entry)
        return payload

    def snapshot_json(self, *, repository_id: int | None = None, indent: int | None = 2) -> str:
        return json.dumps(self.snapshot(repository_id=repository_id), indent=indent, default=str)

    def table_csv(self, table: str, *, repository_id: int | None = None) -> str:
        """Dump a single table (or a repository subset) as CSV."""
        if table not in EXPORT_TABLES:
            raise ValueError(f"unknown table {table!r}; expected one of {', '.join(EXPORT_TABLES)}")
        sql = f"SELECT * FROM {table}"
        params: list[Any] = []
        if repository_id is not None and table != "repositories":
            sql += " WHERE repository_id = ?"
            params.append(repository_id)
        elif repository_id is not None:
            sql += " WHERE id = ?"
            params.append(repository_id)
        rows = self.store.query(sql, params)

        buffer = io.StringIO()
        columns = list(rows[0].keys()) if rows else _table_columns(self.store, table)
        writer = csv.DictWriter(buffer, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
        return buffer.getvalue()

    def csv_bundle(self, tables: Sequence[str] = EXPORT_TABLES, *, repository_id: int | None = None) -> dict[str, str]:
        return {table: self.table_csv(table, repository_id=repository_id) for table in tables}

    def backup_database(self, *, directory: str | None = None) -> Path:
        target_dir = Path(directory) if directory else self.settings.data_dir / "backups"
        target_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        return self.store.db.backup(target_dir / f"dashboard-{stamp}.db")

    def write_snapshot(self, *, directory: str | None = None, repository_id: int | None = None) -> Path:
        target_dir = Path(directory) if directory else self.settings.data_dir / "exports"
        target_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        suffix = f"-repo{repository_id}" if repository_id else ""
        target = target_dir / f"dashboard{suffix}-{stamp}.json"
        target.write_text(self.snapshot_json(repository_id=repository_id), encoding="utf-8")
        log.info("snapshot written to %s", target)
        return target

    def compare(self, repository_ids: Iterable[int]) -> list[dict[str, Any]]:
        from ..analyzers.metrics import repository_comparison

        return repository_comparison(self.store, list(repository_ids))


def _table_columns(store: Store, table: str) -> list[str]:
    rows = store.query(f"PRAGMA table_info({table})")
    return [row["name"] for row in rows]


def branch_summary_for(store: Store, repository_id: int, settings: Settings) -> dict[str, Any]:
    return branch_health_summary(
        store.list_branches(repository_id, include_remote=True),
        inactive_days=settings.inactive_branch_days,
        stale_days=settings.stale_branch_days,
    )
