"""Persistence layer (dao) for the local dashboard.

All SQL lives here.  Every method accepts an optional ``conn`` so callers can wrap
several writes in a single transaction (used by the scan service).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Sequence
from typing import Any

from .connection import Database, utc_now

REPOSITORY_COLUMNS = [
    "name",
    "path",
    "path_key",
    "current_branch",
    "head_commit",
    "head_subject",
    "remote_url",
    "default_branch",
    "state",
    "is_bare",
    "is_dirty",
    "detached_head",
    "uncommitted_files",
    "staged_files",
    "untracked_files",
    "total_commits",
    "tracked_files",
    "branch_count",
    "first_commit_at",
    "last_commit_at",
    "health_score",
    "health_grade",
    "staleness",
    "last_scanned_at",
    "last_error",
]

REPOSITORY_SORTS = {
    "name": "r.name COLLATE NOCASE",
    "last_commit": "r.last_commit_at",
    "commits": "r.total_commits",
    "branches": "r.branch_count",
    "changes": "r.uncommitted_files",
    "scanned": "r.last_scanned_at",
    "health": "r.health_score",
}

COMMIT_SORTS = {
    "date": "authored_at",
    "author": "author_name COLLATE NOCASE",
    "changes": "(additions + deletions)",
}


def _rows(cursor: sqlite3.Cursor) -> list[dict[str, Any]]:
    return [dict(row) for row in cursor.fetchall()]


def _one(cursor: sqlite3.Cursor) -> dict[str, Any] | None:
    row = cursor.fetchone()
    return dict(row) if row else None


class Store:
    """High level data access object."""

    def __init__(self, database: Database) -> None:
        self.db = database

    # ------------------------------------------------------------------ helpers
    def execute(self, sql: str, params: Sequence[Any] = (), *, conn: sqlite3.Connection | None = None) -> None:
        with self.db.connection(conn) as connection:
            connection.execute(sql, params)

    def query(self, sql: str, params: Sequence[Any] = (), *, conn: sqlite3.Connection | None = None) -> list[dict]:
        with self.db.connection(conn) as connection:
            return _rows(connection.execute(sql, params))

    def query_one(self, sql: str, params: Sequence[Any] = (), *, conn: sqlite3.Connection | None = None) -> dict | None:
        with self.db.connection(conn) as connection:
            return _one(connection.execute(sql, params))

    # ------------------------------------------------------------- repositories
    def upsert_repository(self, data: dict[str, Any], *, conn: sqlite3.Connection | None = None) -> int:
        now = utc_now()
        if not data.get("name") or not data.get("path"):
            raise ValueError("a repository row requires both 'name' and 'path'")
        payload = {column: data.get(column) for column in REPOSITORY_COLUMNS}
        # NOT NULL columns need concrete values even when the caller omits them.
        payload["path_key"] = data.get("path_key") or str(data["path"]).lower()
        payload["state"] = payload.get("state") or "unknown"
        for boolean_column in ("is_bare", "is_dirty", "detached_head"):
            payload[boolean_column] = int(bool(payload.get(boolean_column) or 0))
        for numeric in ("uncommitted_files", "staged_files", "untracked_files", "total_commits", "tracked_files", "branch_count"):
            payload[numeric] = int(payload.get(numeric) or 0)
        payload["health_score"] = float(payload.get("health_score") or 0.0)
        payload["health_grade"] = payload.get("health_grade") or "F"
        payload["staleness"] = payload.get("staleness") or "unknown"

        with self.db.connection(conn) as connection:
            existing = connection.execute(
                "SELECT id FROM repositories WHERE path_key = ?", (payload["path_key"],)
            ).fetchone()
            if existing:
                assignments = ", ".join(f"{column} = :{column}" for column in REPOSITORY_COLUMNS)
                connection.execute(
                    f"UPDATE repositories SET {assignments}, updated_at = :updated_at WHERE id = :id",
                    {**payload, "updated_at": now, "id": existing["id"]},
                )
                return int(existing["id"])
            columns = ", ".join(REPOSITORY_COLUMNS + ["created_at", "updated_at"])
            placeholders = ", ".join(f":{column}" for column in REPOSITORY_COLUMNS + ["created_at", "updated_at"])
            cursor = connection.execute(
                f"INSERT INTO repositories ({columns}) VALUES ({placeholders})",
                {**payload, "created_at": now, "updated_at": now},
            )
            return int(cursor.lastrowid)

    def get_repository(self, repository_id: int, *, conn: sqlite3.Connection | None = None) -> dict | None:
        return self.query_one("SELECT * FROM repositories WHERE id = ?", (repository_id,), conn=conn)

    def get_repository_by_path(self, path_key: str, *, conn: sqlite3.Connection | None = None) -> dict | None:
        return self.query_one("SELECT * FROM repositories WHERE path_key = ?", (path_key,), conn=conn)

    def list_repositories(
        self,
        *,
        search: str | None = None,
        status: str | None = None,
        staleness: str | None = None,
        sort: str = "last_commit",
        order: str = "desc",
        limit: int | None = None,
        offset: int = 0,
        conn: sqlite3.Connection | None = None,
    ) -> list[dict]:
        sql = "SELECT r.* FROM repositories r"
        clauses: list[str] = []
        params: list[Any] = []
        if search:
            clauses.append("(r.name LIKE ? OR r.path LIKE ? OR r.current_branch LIKE ?)")
            needle = f"%{search}%"
            params += [needle, needle, needle]
        if status and status != "all":
            clauses.append("r.state = ?")
            params.append(status)
        if staleness and staleness != "all":
            clauses.append("r.staleness = ?")
            params.append(staleness)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        column = REPOSITORY_SORTS.get(sort, REPOSITORY_SORTS["last_commit"])
        direction = "ASC" if str(order).lower() == "asc" else "DESC"
        sql += f" ORDER BY {column} {direction}, r.name COLLATE NOCASE ASC"
        if limit is not None:
            sql += " LIMIT ? OFFSET ?"
            params += [int(limit), int(offset)]
        return self.query(sql, params, conn=conn)

    def delete_repository(self, repository_id: int, *, conn: sqlite3.Connection | None = None) -> bool:
        with self.db.connection(conn) as connection:
            cursor = connection.execute("DELETE FROM repositories WHERE id = ?", (repository_id,))
            return cursor.rowcount > 0

    def set_repository_error(self, repository_id: int, error: str | None, *, conn: sqlite3.Connection | None = None) -> None:
        state = "error" if error else "ok"
        self.execute(
            "UPDATE repositories SET last_error = ?, state = CASE WHEN ? IS NULL THEN state ELSE ? END, updated_at = ? WHERE id = ?",
            (error, error, state, utc_now(), repository_id),
            conn=conn,
        )

    def count_repositories(self, *, conn: sqlite3.Connection | None = None) -> int:
        row = self.query_one("SELECT COUNT(*) AS total FROM repositories", conn=conn)
        return int(row["total"]) if row else 0

    def repository_summary(self, *, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
        row = self.query_one(
            """
            SELECT
                COUNT(*)                                        AS repositories,
                COALESCE(SUM(uncommitted_files), 0)             AS uncommitted_files,
                COALESCE(SUM(staged_files), 0)                  AS staged_files,
                COALESCE(SUM(untracked_files), 0)               AS untracked_files,
                COALESCE(SUM(total_commits), 0)                 AS total_commits,
                COALESCE(SUM(branch_count), 0)                  AS branches,
                COALESCE(SUM(CASE WHEN is_dirty = 1 THEN 1 ELSE 0 END), 0) AS dirty_repositories,
                COALESCE(SUM(CASE WHEN is_bare = 1 THEN 1 ELSE 0 END), 0)  AS bare_repositories,
                COALESCE(SUM(CASE WHEN detached_head = 1 THEN 1 ELSE 0 END), 0) AS detached_repositories,
                COALESCE(SUM(CASE WHEN state = 'error' THEN 1 ELSE 0 END), 0)   AS failing_repositories,
                COALESCE(SUM(CASE WHEN staleness IN ('stale', 'abandoned') THEN 1 ELSE 0 END), 0) AS stale_repositories,
                COALESCE(SUM(CASE WHEN staleness = 'abandoned' THEN 1 ELSE 0 END), 0) AS abandoned_repositories,
                COALESCE(AVG(CASE WHEN last_scanned_at IS NOT NULL THEN health_score END), 0) AS average_health
            FROM repositories
            """,
            conn=conn,
        ) or {}
        contributors = self.query_one("SELECT COUNT(DISTINCT email) AS total FROM contributors WHERE email <> ''", conn=conn)
        row["contributors"] = int(contributors["total"]) if contributors else 0
        return row

    def recently_active_repositories(self, limit: int = 5, *, conn: sqlite3.Connection | None = None) -> list[dict]:
        return self.query(
            "SELECT * FROM repositories WHERE last_commit_at IS NOT NULL ORDER BY last_commit_at DESC LIMIT ?",
            (limit,),
            conn=conn,
        )

    def count_stale_branches(self, *, conn: sqlite3.Connection | None = None) -> int:
        row = self.query_one("SELECT COUNT(*) AS total FROM branches WHERE is_stale = 1 AND is_remote = 0", conn=conn)
        return int(row["total"]) if row else 0

    # ----------------------------------------------------------------- branches
    def replace_branches(self, repository_id: int, branches: Iterable[dict[str, Any]], *, conn: sqlite3.Connection | None = None) -> int:
        now = utc_now()
        rows = list(branches)
        with self.db.connection(conn) as connection:
            connection.execute("DELETE FROM branches WHERE repository_id = ?", (repository_id,))
            connection.executemany(
                """
                INSERT INTO branches (
                    repository_id, name, is_current, is_remote, is_stale, is_merged, has_upstream,
                    upstream, ahead, behind, commit_sha, subject, last_commit_at, age_days, updated_at
                ) VALUES (:repository_id, :name, :is_current, :is_remote, :is_stale, :is_merged, :has_upstream,
                          :upstream, :ahead, :behind, :commit_sha, :subject, :last_commit_at, :age_days, :updated_at)
                """,
                [
                    {
                        "repository_id": repository_id,
                        "name": row.get("name", ""),
                        "is_current": int(bool(row.get("is_current"))),
                        "is_remote": int(bool(row.get("is_remote"))),
                        "is_stale": int(bool(row.get("is_stale"))),
                        "is_merged": int(bool(row.get("is_merged"))),
                        "has_upstream": int(bool(row.get("upstream"))),
                        "upstream": row.get("upstream"),
                        "ahead": int(row.get("ahead") or 0),
                        "behind": int(row.get("behind") or 0),
                        "commit_sha": row.get("commit_sha"),
                        "subject": row.get("subject"),
                        "last_commit_at": row.get("last_commit_at"),
                        "age_days": int(row.get("age_days") or 0),
                        "updated_at": now,
                    }
                    for row in rows
                ],
            )
        return len(rows)

    def list_branches(
        self,
        repository_id: int,
        *,
        branch_filter: str = "all",
        search: str | None = None,
        include_remote: bool = True,
        conn: sqlite3.Connection | None = None,
    ) -> list[dict]:
        sql = "SELECT * FROM branches WHERE repository_id = ?"
        params: list[Any] = [repository_id]
        if not include_remote:
            sql += " AND is_remote = 0"
        if branch_filter == "current":
            sql += " AND is_current = 1"
        elif branch_filter == "stale":
            sql += " AND is_stale = 1"
        elif branch_filter == "active":
            sql += " AND is_stale = 0 AND is_current = 0"
        elif branch_filter == "merged":
            sql += " AND is_merged = 1"
        if search:
            sql += " AND name LIKE ?"
            params.append(f"%{search}%")
        sql += " ORDER BY is_current DESC, is_remote ASC, last_commit_at DESC"
        return self.query(sql, params, conn=conn)

    def all_branches(self, *, branch_filter: str = "all", search: str | None = None, conn: sqlite3.Connection | None = None) -> list[dict]:
        """Branches across every repository (used by the global Branches view)."""
        sql = """
            SELECT b.*, r.name AS repository_name, r.path AS repository_path
            FROM branches b JOIN repositories r ON r.id = b.repository_id
            WHERE 1 = 1
        """
        params: list[Any] = []
        if branch_filter == "stale":
            sql += " AND b.is_stale = 1"
        elif branch_filter == "current":
            sql += " AND b.is_current = 1"
        elif branch_filter == "merged":
            sql += " AND b.is_merged = 1"
        elif branch_filter == "active":
            sql += " AND b.is_stale = 0"
        if search:
            sql += " AND (b.name LIKE ? OR r.name LIKE ?)"
            params += [f"%{search}%", f"%{search}%"]
        sql += " ORDER BY b.is_stale DESC, b.last_commit_at DESC LIMIT 500"
        return self.query(sql, params, conn=conn)

    # ------------------------------------------------------------------ commits
    def insert_commits(
        self, repository_id: int, commits: Sequence[dict[str, Any]], *, conn: sqlite3.Connection | None = None
    ) -> list[str]:
        """Insert commits, ignoring duplicates. Returns the SHAs that were new."""
        if not commits:
            return []
        now = utc_now()
        inserted: list[str] = []
        with self.db.connection(conn) as connection:
            for commit in commits:
                parents = commit.get("parents") or ""
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO commits (
                        repository_id, sha, short_sha, author_name, author_email, authored_at, committed_at,
                        subject, parents, parent_count, is_merge, refs, additions, deletions, files_changed, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        repository_id,
                        commit["sha"],
                        commit.get("short_sha") or commit["sha"][:8],
                        commit.get("author_name") or "unknown",
                        commit.get("author_email") or "",
                        commit["authored_at"],
                        commit.get("committed_at") or commit["authored_at"],
                        commit.get("subject") or "",
                        parents,
                        int(commit.get("parent_count") or len(parents.split())),
                        int(bool(commit.get("is_merge"))),
                        commit.get("refs") or "",
                        int(commit.get("additions") or 0),
                        int(commit.get("deletions") or 0),
                        int(commit.get("files_changed") or 0),
                        now,
                    ),
                )
                if cursor.rowcount:
                    inserted.append(commit["sha"])
        return inserted

    def commit_shas(self, repository_id: int, *, conn: sqlite3.Connection | None = None) -> set[str]:
        rows = self.query("SELECT sha FROM commits WHERE repository_id = ?", (repository_id,), conn=conn)
        return {row["sha"] for row in rows}

    def get_commit(self, repository_id: int, sha: str, *, conn: sqlite3.Connection | None = None) -> dict | None:
        """Look a commit up by full SHA or any unambiguous prefix (git allows both).

        Only hexadecimal input is accepted, which also keeps the LIKE pattern safe.
        """
        candidate = (sha or "").strip().lower()
        if not candidate or any(character not in "0123456789abcdef" for character in candidate):
            return None
        if len(candidate) == 40:
            exact = self.query_one(
                "SELECT * FROM commits WHERE repository_id = ? AND sha = ? LIMIT 1", (repository_id, candidate), conn=conn
            )
            if exact:
                return exact
        return self.query_one(
            "SELECT * FROM commits WHERE repository_id = ? AND sha LIKE ? ORDER BY authored_at DESC LIMIT 1",
            (repository_id, f"{candidate}%"),
            conn=conn,
        )

    def list_commits(
        self,
        repository_id: int,
        *,
        page: int = 1,
        per_page: int = 50,
        since: str | None = None,
        until: str | None = None,
        author: str | None = None,
        search: str | None = None,
        sha: str | None = None,
        sort: str = "date",
        order: str = "desc",
        conn: sqlite3.Connection | None = None,
    ) -> tuple[list[dict], int]:
        clauses = ["repository_id = ?"]
        params: list[Any] = [repository_id]
        if sha:
            clauses.append("(sha LIKE ? OR short_sha LIKE ?)")
            params += [f"{sha}%", f"{sha}%"]
        if since:
            clauses.append("authored_at >= ?")
            params.append(since)
        if until:
            clauses.append("authored_at <= ?")
            params.append(until)
        if author:
            clauses.append("(author_name LIKE ? OR author_email LIKE ?)")
            params += [f"%{author}%", f"%{author}%"]
        if search:
            clauses.append("(subject LIKE ? OR sha LIKE ?)")
            params += [f"%{search}%", f"{search}%"]
        where = " AND ".join(clauses)
        total_row = self.query_one(f"SELECT COUNT(*) AS total FROM commits WHERE {where}", params, conn=conn)
        total = int(total_row["total"]) if total_row else 0
        column = COMMIT_SORTS.get(sort, COMMIT_SORTS["date"])
        direction = "ASC" if str(order).lower() == "asc" else "DESC"
        per_page = max(1, min(int(per_page), 500))
        page = max(1, int(page))
        rows = self.query(
            f"SELECT * FROM commits WHERE {where} ORDER BY {column} {direction} LIMIT ? OFFSET ?",
            params + [per_page, (page - 1) * per_page],
            conn=conn,
        )
        return rows, total

    def count_commits(self, repository_id: int, *, since: str | None = None, until: str | None = None, conn=None) -> int:
        sql = "SELECT COUNT(*) AS total FROM commits WHERE repository_id = ?"
        params: list[Any] = [repository_id]
        if since:
            sql += " AND authored_at >= ?"
            params.append(since)
        if until:
            sql += " AND authored_at <= ?"
            params.append(until)
        row = self.query_one(sql, params, conn=conn)
        return int(row["total"]) if row else 0

    def count_commits_all(self, *, since: str | None = None, until: str | None = None, conn=None) -> int:
        """Commit count across every repository (used by the overview cards)."""
        sql = "SELECT COUNT(*) AS total FROM commits WHERE 1 = 1"
        params: list[Any] = []
        if since:
            sql += " AND authored_at >= ?"
            params.append(since)
        if until:
            sql += " AND authored_at <= ?"
            params.append(until)
        row = self.query_one(sql, params, conn=conn)
        return int(row["total"]) if row else 0

    def daily_commit_counts_all(self, *, since: str | None = None, conn=None) -> list[dict]:
        sql = "SELECT substr(authored_at, 1, 10) AS day, COUNT(*) AS commits FROM commits"
        params: list[Any] = []
        if since:
            sql += " WHERE authored_at >= ?"
            params.append(since)
        sql += " GROUP BY day ORDER BY day"
        return self.query(sql, params, conn=conn)

    def author_aggregates(self, repository_id: int, *, since: str | None = None, conn=None) -> list[dict]:
        sql = """
            SELECT author_name AS name, author_email AS email, COUNT(*) AS commits,
                   COALESCE(SUM(additions), 0) AS additions, COALESCE(SUM(deletions), 0) AS deletions,
                   MIN(authored_at) AS first_commit_at, MAX(authored_at) AS last_commit_at
            FROM commits WHERE repository_id = ?
        """
        params: list[Any] = [repository_id]
        if since:
            sql += " AND authored_at >= ?"
            params.append(since)
        sql += " GROUP BY author_email, author_name ORDER BY commits DESC"
        return self.query(sql, params, conn=conn)

    def daily_commit_counts(self, repository_id: int, *, since: str | None = None, conn=None) -> list[dict]:
        sql = "SELECT substr(authored_at, 1, 10) AS day, COUNT(*) AS commits FROM commits WHERE repository_id = ?"
        params: list[Any] = [repository_id]
        if since:
            sql += " AND authored_at >= ?"
            params.append(since)
        sql += " GROUP BY day ORDER BY day"
        return self.query(sql, params, conn=conn)

    def hourly_commit_counts(self, repository_id: int, *, since: str | None = None, conn=None) -> list[dict]:
        """Commit counts per weekday/hour (used by the activity heatmap)."""
        sql = "SELECT authored_at FROM commits WHERE repository_id = ?"
        params: list[Any] = [repository_id]
        if since:
            sql += " AND authored_at >= ?"
            params.append(since)
        return self.query(sql, params, conn=conn)

    def contributor_totals(self, repository_id: int | None = None, *, since: str | None = None, conn=None) -> list[dict]:
        sql = """
            SELECT author_email AS email, author_name AS name, COUNT(*) AS commits,
                   MAX(authored_at) AS last_commit_at
            FROM commits
        """
        params: list[Any] = []
        clauses = []
        if repository_id is not None:
            clauses.append("repository_id = ?")
            params.append(repository_id)
        if since:
            clauses.append("authored_at >= ?")
            params.append(since)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " GROUP BY author_email, author_name ORDER BY commits DESC"
        return self.query(sql, params, conn=conn)

    def first_and_last_commit(self, repository_id: int, *, conn=None) -> tuple[dict | None, dict | None]:
        first = self.query_one(
            "SELECT sha, authored_at, author_name, subject FROM commits WHERE repository_id = ? ORDER BY authored_at ASC LIMIT 1",
            (repository_id,),
            conn=conn,
        )
        last = self.query_one(
            "SELECT sha, authored_at, author_name, subject FROM commits WHERE repository_id = ? ORDER BY authored_at DESC LIMIT 1",
            (repository_id,),
            conn=conn,
        )
        return first, last

    # ------------------------------------------------------------- file changes
    def replace_file_changes(
        self, repository_id: int, sha: str, changes: Sequence[dict[str, Any]], *, conn=None
    ) -> int:
        with self.db.connection(conn) as connection:
            connection.execute("DELETE FROM file_changes WHERE repository_id = ? AND commit_sha = ?", (repository_id, sha))
            connection.executemany(
                """
                INSERT OR REPLACE INTO file_changes (repository_id, commit_sha, path, change_type, additions, deletions)
                VALUES (:repository_id, :commit_sha, :path, :change_type, :additions, :deletions)
                """,
                [
                    {
                        "repository_id": repository_id,
                        "commit_sha": sha,
                        "path": change.get("path", ""),
                        "change_type": change.get("change_type", "modified"),
                        "additions": int(change.get("additions") or 0),
                        "deletions": int(change.get("deletions") or 0),
                    }
                    for change in changes
                ],
            )
        return len(changes)

    def list_file_changes(self, repository_id: int, sha: str, *, conn=None) -> list[dict]:
        return self.query(
            "SELECT path, change_type, additions, deletions FROM file_changes WHERE repository_id = ? AND commit_sha = ? "
            "ORDER BY (additions + deletions) DESC, path ASC",
            (repository_id, sha),
            conn=conn,
        )

    def top_changed_files(self, repository_id: int, *, limit: int = 10, conn=None) -> list[dict]:
        return self.query(
            """
            SELECT path,
                   COUNT(*) AS changes,
                   COALESCE(SUM(additions), 0) AS additions,
                   COALESCE(SUM(deletions), 0) AS deletions,
                   COALESCE(SUM(additions + deletions), 0) AS churn
            FROM file_changes WHERE repository_id = ?
            GROUP BY path ORDER BY churn DESC, changes DESC LIMIT ?
            """,
            (repository_id, limit),
            conn=conn,
        )

    def file_change_totals(self, repository_id: int, *, since: str | None = None, conn=None) -> dict[str, int]:
        sql = """
            SELECT COUNT(DISTINCT f.path) AS files_touched,
                   COALESCE(SUM(f.additions), 0) AS additions,
                   COALESCE(SUM(f.deletions), 0) AS deletions
            FROM file_changes f
            JOIN commits c ON c.repository_id = f.repository_id AND c.sha = f.commit_sha
            WHERE f.repository_id = ?
        """
        params: list[Any] = [repository_id]
        if since:
            sql += " AND c.authored_at >= ?"
            params.append(since)
        row = self.query_one(sql, params, conn=conn) or {}
        return {
            "files_touched": int(row.get("files_touched") or 0),
            "additions": int(row.get("additions") or 0),
            "deletions": int(row.get("deletions") or 0),
        }

    # ------------------------------------------------------------- contributors
    def replace_contributors(self, repository_id: int, contributors: Sequence[dict[str, Any]], *, conn=None) -> int:
        now = utc_now()
        rows = list(contributors)
        with self.db.connection(conn) as connection:
            connection.execute("DELETE FROM contributors WHERE repository_id = ?", (repository_id,))
            connection.executemany(
                """
                INSERT OR REPLACE INTO contributors (
                    repository_id, name, email, commit_count, additions, deletions, first_commit_at, last_commit_at, updated_at
                ) VALUES (:repository_id, :name, :email, :commit_count, :additions, :deletions, :first_commit_at, :last_commit_at, :updated_at)
                """,
                [
                    {
                        "repository_id": repository_id,
                        "name": row.get("name") or "unknown",
                        "email": row.get("email") or "",
                        "commit_count": int(row.get("commits") or row.get("commit_count") or 0),
                        "additions": int(row.get("additions") or 0),
                        "deletions": int(row.get("deletions") or 0),
                        "first_commit_at": row.get("first_commit_at"),
                        "last_commit_at": row.get("last_commit_at"),
                        "updated_at": now,
                    }
                    for row in rows
                ],
            )
        return len(rows)

    def list_contributors(self, repository_id: int, *, conn=None) -> list[dict]:
        return self.query(
            "SELECT * FROM contributors WHERE repository_id = ? ORDER BY commit_count DESC, name COLLATE NOCASE ASC",
            (repository_id,),
            conn=conn,
        )

    # ---------------------------------------------------------------- scan runs
    def start_scan_run(self, kind: str, repository_id: int | None = None, *, conn=None) -> int:
        with self.db.connection(conn) as connection:
            cursor = connection.execute(
                "INSERT INTO scan_runs (repository_id, kind, status, started_at) VALUES (?, ?, 'running', ?)",
                (repository_id, kind, utc_now()),
            )
            return int(cursor.lastrowid)

    def finish_scan_run(
        self,
        scan_id: int,
        *,
        status: str,
        records_processed: int = 0,
        commits_added: int = 0,
        repositories_scanned: int = 0,
        repositories_failed: int = 0,
        error: str | None = None,
        duration_ms: int | None = None,
        conn=None,
    ) -> None:
        self.execute(
            """
            UPDATE scan_runs
               SET status = ?, completed_at = ?, duration_ms = ?, records_processed = ?, commits_added = ?,
                   repositories_scanned = ?, repositories_failed = ?, error = ?
             WHERE id = ?
            """,
            (status, utc_now(), duration_ms, records_processed, commits_added, repositories_scanned, repositories_failed, error, scan_id),
            conn=conn,
        )

    def get_scan_run(self, scan_id: int, *, conn=None) -> dict | None:
        return self.query_one("SELECT * FROM scan_runs WHERE id = ?", (scan_id,), conn=conn)

    def list_scan_runs(self, *, limit: int = 20, repository_id: int | None = None, conn=None) -> list[dict]:
        sql = "SELECT s.*, r.name AS repository_name FROM scan_runs s LEFT JOIN repositories r ON r.id = s.repository_id"
        params: list[Any] = []
        if repository_id is not None:
            sql += " WHERE s.repository_id = ?"
            params.append(repository_id)
        # Aggregate "scan everything" runs (repository_id IS NULL) are the summary a
        # user looks for first, so they lead the history; the rest is newest first.
        sql += " ORDER BY (s.repository_id IS NULL) DESC, COALESCE(s.completed_at, s.started_at) DESC, s.id DESC LIMIT ?"
        params.append(int(limit))
        return self.query(sql, params, conn=conn)

    def latest_scan_run(self, *, conn=None) -> dict | None:
        rows = self.list_scan_runs(limit=1, conn=conn)
        return rows[0] if rows else None

    # --------------------------------------------------------------- app state
    def set_state(self, key: str, value: str, *, conn=None) -> None:
        self.execute(
            "INSERT INTO app_state (key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
            (key, value, utc_now()),
            conn=conn,
        )

    def get_state(self, key: str, default: str | None = None, *, conn=None) -> str | None:
        row = self.query_one("SELECT value FROM app_state WHERE key = ?", (key,), conn=conn)
        return row["value"] if row else default
