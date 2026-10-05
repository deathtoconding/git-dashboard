"""SQLite schema definition and migration mechanism (Epic E4).

The schema is versioned through the ``schema_version`` table.  Each entry in
:data:`MIGRATIONS` is applied once, in order, inside a transaction, which makes
upgrades of an existing ``data/dashboard.db`` safe and repeatable.
"""

from __future__ import annotations

SCHEMA_VERSION = 1

# --- v1 -------------------------------------------------------------------
_V1 = """
CREATE TABLE IF NOT EXISTS repositories (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    name                TEXT    NOT NULL,
    path                TEXT    NOT NULL,
    path_key            TEXT    NOT NULL UNIQUE,   -- normalised path (case folded on Windows)
    current_branch      TEXT,
    head_commit         TEXT,
    head_subject        TEXT,
    remote_url          TEXT,
    default_branch      TEXT,
    state               TEXT    NOT NULL DEFAULT 'unknown',  -- ok | dirty | bare | detached | missing | error
    is_bare             INTEGER NOT NULL DEFAULT 0,
    is_dirty            INTEGER NOT NULL DEFAULT 0,
    detached_head       INTEGER NOT NULL DEFAULT 0,
    uncommitted_files   INTEGER NOT NULL DEFAULT 0,
    staged_files        INTEGER NOT NULL DEFAULT 0,
    untracked_files     INTEGER NOT NULL DEFAULT 0,
    total_commits       INTEGER NOT NULL DEFAULT 0,
    tracked_files       INTEGER NOT NULL DEFAULT 0,
    branch_count        INTEGER NOT NULL DEFAULT 0,
    first_commit_at     TEXT,
    last_commit_at      TEXT,
    health_score        REAL    NOT NULL DEFAULT 0,
    health_grade        TEXT    NOT NULL DEFAULT 'F',
    staleness           TEXT    NOT NULL DEFAULT 'unknown',  -- active | inactive | stale | abandoned | empty | unknown
    last_scanned_at     TEXT,
    last_error          TEXT,
    created_at          TEXT    NOT NULL,
    updated_at          TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_repositories_name ON repositories(name);
CREATE INDEX IF NOT EXISTS idx_repositories_last_commit ON repositories(last_commit_at);

CREATE TABLE IF NOT EXISTS branches (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    repository_id   INTEGER NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
    name            TEXT    NOT NULL,
    is_current      INTEGER NOT NULL DEFAULT 0,
    is_remote       INTEGER NOT NULL DEFAULT 0,
    is_stale        INTEGER NOT NULL DEFAULT 0,
    is_merged       INTEGER NOT NULL DEFAULT 0,
    has_upstream    INTEGER NOT NULL DEFAULT 0,
    upstream        TEXT,
    ahead           INTEGER NOT NULL DEFAULT 0,
    behind          INTEGER NOT NULL DEFAULT 0,
    commit_sha      TEXT,
    subject         TEXT,
    last_commit_at  TEXT,
    age_days        INTEGER NOT NULL DEFAULT 0,
    updated_at      TEXT    NOT NULL,
    UNIQUE (repository_id, name)
);
CREATE INDEX IF NOT EXISTS idx_branches_repo ON branches(repository_id);
CREATE INDEX IF NOT EXISTS idx_branches_last_commit ON branches(repository_id, last_commit_at);

CREATE TABLE IF NOT EXISTS commits (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    repository_id   INTEGER NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
    sha             TEXT    NOT NULL,
    short_sha       TEXT    NOT NULL,
    author_name     TEXT    NOT NULL,
    author_email    TEXT    NOT NULL DEFAULT '',
    authored_at     TEXT    NOT NULL,   -- UTC ISO-8601 (author date)
    committed_at    TEXT    NOT NULL,   -- UTC ISO-8601 (commit date)
    subject         TEXT    NOT NULL DEFAULT '',
    parents         TEXT    NOT NULL DEFAULT '',   -- space separated parent shas
    parent_count    INTEGER NOT NULL DEFAULT 0,
    is_merge        INTEGER NOT NULL DEFAULT 0,
    refs            TEXT    NOT NULL DEFAULT '',   -- decorated ref names (branch association)
    additions       INTEGER NOT NULL DEFAULT 0,
    deletions       INTEGER NOT NULL DEFAULT 0,
    files_changed   INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT    NOT NULL,
    UNIQUE (repository_id, sha)
);
CREATE INDEX IF NOT EXISTS idx_commits_repo_date ON commits(repository_id, authored_at DESC);
CREATE INDEX IF NOT EXISTS idx_commits_author ON commits(repository_id, author_email);
CREATE INDEX IF NOT EXISTS idx_commits_sha ON commits(repository_id, sha);

CREATE TABLE IF NOT EXISTS file_changes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    repository_id   INTEGER NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
    commit_sha      TEXT    NOT NULL,
    path            TEXT    NOT NULL,
    change_type     TEXT    NOT NULL DEFAULT 'modified',  -- modified | added | deleted | renamed | binary
    additions       INTEGER NOT NULL DEFAULT 0,
    deletions       INTEGER NOT NULL DEFAULT 0,
    UNIQUE (repository_id, commit_sha, path)
);
CREATE INDEX IF NOT EXISTS idx_file_changes_commit ON file_changes(repository_id, commit_sha);
CREATE INDEX IF NOT EXISTS idx_file_changes_path ON file_changes(repository_id, path);

CREATE TABLE IF NOT EXISTS contributors (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    repository_id   INTEGER NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
    name            TEXT    NOT NULL,
    email           TEXT    NOT NULL DEFAULT '',
    commit_count    INTEGER NOT NULL DEFAULT 0,
    additions       INTEGER NOT NULL DEFAULT 0,
    deletions       INTEGER NOT NULL DEFAULT 0,
    first_commit_at TEXT,
    last_commit_at  TEXT,
    updated_at      TEXT    NOT NULL,
    UNIQUE (repository_id, email, name)
);
CREATE INDEX IF NOT EXISTS idx_contributors_repo ON contributors(repository_id);

CREATE TABLE IF NOT EXISTS scan_runs (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    repository_id       INTEGER REFERENCES repositories(id) ON DELETE CASCADE,
    kind                TEXT    NOT NULL DEFAULT 'single',  -- single | full | incremental
    status              TEXT    NOT NULL DEFAULT 'running', -- running | completed | failed | partial
    started_at          TEXT    NOT NULL,
    completed_at        TEXT,
    duration_ms         INTEGER,
    records_processed   INTEGER NOT NULL DEFAULT 0,
    commits_added       INTEGER NOT NULL DEFAULT 0,
    repositories_scanned INTEGER NOT NULL DEFAULT 0,
    repositories_failed  INTEGER NOT NULL DEFAULT 0,
    error               TEXT
);
CREATE INDEX IF NOT EXISTS idx_scan_runs_started ON scan_runs(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_scan_runs_repo ON scan_runs(repository_id, started_at DESC);

CREATE TABLE IF NOT EXISTS app_state (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
"""

MIGRATIONS: list[tuple[int, str]] = [
    (1, _V1),
]


def migration_statements(sql: str) -> list[str]:
    """Split a migration script into individual statements executable by sqlite3."""
    return [statement.strip() for statement in sql.split(";") if statement.strip()]
