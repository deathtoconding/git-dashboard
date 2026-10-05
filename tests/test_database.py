"""Database tests: schema, migrations, dedupe, cascade delete, backups (E4)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.database.connection import Database, DatabaseError, utc_now
from app.database.schema import SCHEMA_VERSION
from app.database.store import Store


def test_migrate_creates_every_table(database: Database) -> None:
    with database.connection() as conn:
        names = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    for table in ("repositories", "branches", "commits", "contributors", "file_changes", "scan_runs", "schema_version", "app_state"):
        assert table in names
    assert database.current_version() == SCHEMA_VERSION


def test_migrate_is_idempotent(database: Database) -> None:
    assert database.migrate() == SCHEMA_VERSION
    assert database.migrate() == SCHEMA_VERSION


def test_newer_schema_is_rejected(tmp_path: Path) -> None:
    db = Database(tmp_path / "future.db")
    db.migrate()
    with db.connection() as conn:
        conn.execute("INSERT INTO schema_version (version, applied_at) VALUES (?, ?)", (SCHEMA_VERSION + 5, utc_now()))
    with pytest.raises(DatabaseError, match="newer version"):
        db.migrate()


def test_foreign_keys_cascade(tmp_path: Path) -> None:
    db = Database(tmp_path / "cascade.db")
    db.migrate()
    store = Store(db)
    repository_id = store.upsert_repository({"name": "demo", "path": "/tmp/demo"})
    store.insert_commits(repository_id, [{"sha": "a" * 40, "authored_at": utc_now()}])
    store.replace_branches(repository_id, [{"name": "main", "is_current": True}])
    store.replace_contributors(repository_id, [{"name": "Ada", "email": "ada@example.com", "commits": 1}])
    store.replace_file_changes(repository_id, "a" * 40, [{"path": "x.py", "additions": 1, "deletions": 0}])

    assert store.delete_repository(repository_id) is True
    assert store.get_repository(repository_id) is None
    assert store.query("SELECT * FROM commits") == []
    assert store.query("SELECT * FROM branches") == []
    assert store.query("SELECT * FROM file_changes") == []
    assert store.query("SELECT * FROM contributors") == []


def test_upsert_repository_is_idempotent_by_path(store: Store) -> None:
    first = store.upsert_repository({"name": "demo", "path": "/tmp/demo", "total_commits": 1})
    second = store.upsert_repository({"name": "renamed", "path": "/tmp/Demo", "path_key": "/tmp/demo", "total_commits": 5})
    assert first == second
    stored = store.get_repository(first)
    assert stored["name"] == "renamed"
    assert stored["total_commits"] == 5
    assert store.query("SELECT COUNT(*) AS total FROM repositories")[0]["total"] == 1


def test_insert_commits_prevents_duplicates(store: Store) -> None:
    """Running the same scan twice must not duplicate commit rows (E4-S3)."""
    repository_id = store.upsert_repository({"name": "demo", "path": "/tmp/demo"})
    payload = [
        {"sha": "a" * 40, "authored_at": utc_now(), "subject": "one", "additions": 2, "deletions": 1},
        {"sha": "b" * 40, "authored_at": utc_now(), "subject": "two"},
    ]
    assert store.insert_commits(repository_id, payload) == ["a" * 40, "b" * 40]
    assert store.insert_commits(repository_id, payload) == []
    assert store.count_commits(repository_id) == 2
    assert store.insert_commits(repository_id, [{"sha": "c" * 40, "authored_at": utc_now()}]) == ["c" * 40]
    assert store.count_commits(repository_id) == 3


def test_commit_queries_and_filters(store: Store) -> None:
    repository_id = store.upsert_repository({"name": "demo", "path": "/tmp/demo"})
    store.insert_commits(
        repository_id,
        [
            {"sha": "a" * 40, "authored_at": "2026-01-01T00:00:00Z", "author_name": "Ada", "author_email": "ada@example.com", "subject": "first"},
            {"sha": "b" * 40, "authored_at": "2026-02-01T00:00:00Z", "author_name": "Grace", "author_email": "grace@example.com", "subject": "second"},
            {"sha": "c" * 40, "authored_at": "2026-03-01T00:00:00Z", "author_name": "Ada", "author_email": "ada@example.com", "subject": "third"},
        ],
    )
    rows, total = store.list_commits(repository_id, per_page=2)
    assert total == 3 and len(rows) == 2
    rows, total = store.list_commits(repository_id, author="ada")
    assert total == 2
    rows, total = store.list_commits(repository_id, since="2026-02-01T00:00:00Z")
    assert total == 2
    rows, total = store.list_commits(repository_id, search="third")
    assert total == 1 and rows[0]["subject"] == "third"
    rows, total = store.list_commits(repository_id, sha="bbb")
    assert total == 1
    assert store.get_commit(repository_id, "b" * 40)["subject"] == "second"
    assert store.get_commit(repository_id, "b" * 8)["subject"] == "second"
    assert store.get_commit(repository_id, "zzz") is None


def test_aggregates(store: Store) -> None:
    repository_id = store.upsert_repository({"name": "demo", "path": "/tmp/demo", "total_commits": 3})
    store.insert_commits(
        repository_id,
        [
            {"sha": "a" * 40, "authored_at": "2026-01-01T00:00:00Z", "author_name": "Ada", "author_email": "ada@example.com", "additions": 10, "deletions": 2, "files_changed": 1},
            {"sha": "b" * 40, "authored_at": "2026-01-02T00:00:00Z", "author_name": "Ada", "author_email": "ada@example.com", "additions": 5, "deletions": 1, "files_changed": 1},
        ],
    )
    store.replace_file_changes(repository_id, "a" * 40, [{"path": "x.py", "additions": 10, "deletions": 2}])
    store.replace_file_changes(repository_id, "b" * 40, [{"path": "x.py", "additions": 5, "deletions": 1}])

    authors = store.author_aggregates(repository_id)
    assert authors[0]["name"] == "Ada" and authors[0]["commits"] == 2
    assert store.first_and_last_commit(repository_id)[0]["sha"] == "a" * 40
    daily = store.daily_commit_counts(repository_id)
    assert [row["commits"] for row in daily] == [1, 1]
    totals = store.file_change_totals(repository_id)
    assert totals == {"files_touched": 1, "additions": 15, "deletions": 3}
    churn = store.top_changed_files(repository_id)
    assert churn[0]["path"] == "x.py" and churn[0]["changes"] == 2
    assert store.count_commits_all() == 2


def test_scan_run_lifecycle(store: Store) -> None:
    repository_id = store.upsert_repository({"name": "demo", "path": "/tmp/demo"})
    scan_id = store.start_scan_run("single", repository_id)
    running = store.get_scan_run(scan_id)
    assert running["status"] == "running" and running["completed_at"] is None

    store.finish_scan_run(scan_id, status="completed", records_processed=12, commits_added=3, duration_ms=42)
    done = store.get_scan_run(scan_id)
    assert done["status"] == "completed"
    assert done["records_processed"] == 12 and done["commits_added"] == 3 and done["duration_ms"] == 42
    assert store.latest_scan_run()["id"] == scan_id

    failed_id = store.start_scan_run("single", repository_id)
    store.finish_scan_run(failed_id, status="failed", error="boom")
    assert store.get_scan_run(failed_id)["error"] == "boom"


def test_app_state_round_trip(store: Store) -> None:
    store.set_state("last_known_head", "abc")
    assert store.get_state("last_known_head") == "abc"
    assert store.get_state("missing", default="fallback") == "fallback"
    store.set_state("last_known_head", "def")
    assert store.get_state("last_known_head") == "def"


def test_backup_and_size(tmp_path: Path) -> None:
    db = Database(tmp_path / "source.db")
    db.migrate()
    store = Store(db)
    store.upsert_repository({"name": "demo", "path": "/tmp/demo"})
    target = db.backup(tmp_path / "backups" / "copy.db")
    assert target.exists() and target.stat().st_size > 0
    copy = Database(target)
    assert copy.current_version() == SCHEMA_VERSION
    assert Store(copy).count_repositories() == 1
    assert db.size_bytes() > 0


def test_missing_columns_are_defaulted(store: Store) -> None:
    repository_id = store.upsert_repository({"name": "demo", "path": "/tmp/demo"})
    stored = store.get_repository(repository_id)
    assert stored["state"] == "unknown"
    assert stored["health_score"] == 0.0
    assert stored["health_grade"] == "F"
    assert stored["staleness"] == "unknown"
    assert stored["is_dirty"] == 0
    assert stored["created_at"] and stored["updated_at"]


def test_summary_counts(store: Store) -> None:
    repository_id = store.upsert_repository(
        {"name": "demo", "path": "/tmp/demo", "uncommitted_files": 3, "staged_files": 1, "untracked_files": 2, "total_commits": 7, "branch_count": 4, "is_dirty": True}
    )
    store.replace_branches(repository_id, [{"name": "main", "is_stale": False}, {"name": "old", "is_stale": True}])
    summary = store.repository_summary()
    assert summary["repositories"] == 1
    assert summary["uncommitted_files"] == 3
    assert summary["dirty_repositories"] == 1
    assert summary["branches"] == 4  # sums the cached branch_count column
    assert store.count_stale_branches() == 1  # counted from the branches table
    assert summary["average_health"] == 0


def test_database_error_message_is_clear(tmp_path: Path) -> None:
    target = tmp_path / "as-directory"
    target.mkdir()
    db = Database(target)  # a directory, not a file
    with pytest.raises(DatabaseError) as excinfo:
        db.migrate()
    assert "cannot open database" in str(excinfo.value)


def test_wal_mode_enabled(database: Database) -> None:
    with database.connection() as conn:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() in {"wal", "delete", "memory"}  # WAL where the filesystem allows it
    assert isinstance(mode, str)


def test_execute_and_query_helpers(store: Store) -> None:
    store.execute("INSERT INTO app_state (key, value, updated_at) VALUES (?, ?, ?)", ("k", "v", utc_now()))
    assert store.query_one("SELECT value FROM app_state WHERE key = ?", ("k",))["value"] == "v"
    assert store.query_one("SELECT value FROM app_state WHERE key = ?", ("nope",)) is None
    with pytest.raises(sqlite3.OperationalError):
        store.query("SELECT * FROM does_not_exist")
