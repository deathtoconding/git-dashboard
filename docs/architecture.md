# Architecture

The dashboard is a single Python process with two faces: a CLI and a local web
server. Both use the same services and the same SQLite database.

```
filesystem
   │  discovery (walk roots, detect .git / bare repositories)
   ▼
collectors ── git CLI ──▶ parsed rows (state, branches, commits, file changes, contributors)
   │
   ▼
SQLite store  (repositories, branches, commits, file_changes, contributors, scan_runs)
   │
   ├──▶ analyzers (metrics, activity, heatmap, churn, branch health, health score, insights)
   │
   ▼
FastAPI  ──▶ JSON under /api  ──▶ browser (plain HTML/CSS/JS, no build step)
```

Git is executed only in the collector layer. Request handlers read SQLite; they
never spawn a process, so an API call cannot block on a repository on a slow
disk, and a hung `git` cannot exhaust the web server.

## Module map

| Path | Responsibility |
| --- | --- |
| `app/config.py` | `Settings` dataclass, layered loading (defaults → file → env → CLI), validation |
| `app/logging_config.py` | Root logger setup, rotating file log, `get_repo_logger()` context |
| `app/database/schema.py` | Versioned DDL and the migration list |
| `app/database/connection.py` | Connection handling (WAL, foreign keys, busy timeout), UTC timestamps |
| `app/database/store.py` | Every query the rest of the app uses: upserts, filters, pagination, aggregates |
| `app/collectors/git_runner.py` | The only place that runs `git`, with timeouts and error normalisation |
| `app/collectors/parsers.py` | Pure parsers for `git log --numstat`, branch refs, porcelain status, timestamps |
| `app/collectors/discovery.py` | Filesystem walk, repository/bare detection, duplicate-root handling |
| `app/collectors/repo_state.py` | Working tree state, HEAD, remotes, tracked files |
| `app/collectors/commits.py` | Commit history collection, incremental walks (`--not <sha>`), file-change backfill |
| `app/collectors/branches.py` | Branch inventory with upstream, ahead/behind, merged detection |
| `app/collectors/contributors.py` | Contributor aggregation, `git shortlog` cross-check |
| `app/collectors/collector.py` | `GitCollector` facade used by the scan service |
| `app/analyzers/metrics.py` | Basic/activity/change metrics, comparison |
| `app/analyzers/activity.py` | Day/week/month buckets, heatmap grid, contributor trends |
| `app/analyzers/branch_health.py` | Branch classification and hygiene summary |
| `app/analyzers/health.py` | Weighted health score, staleness buckets, recommendations |
| `app/services/scan_service.py` | One repository or many: collect → store → refresh health → record the run |
| `app/services/scan_manager.py` | Background scans, job progress, busy guard |
| `app/services/repository_service.py` | Registration, discovery endpoints, suggestions, removal |
| `app/services/export_service.py` | JSON snapshots, CSV dumps, SQLite backups, comparisons |
| `app/models/schemas.py` | Pydantic request/response models used by the routers |
| `app/api/serializers.py` | Derived, UI-ready repository fields (staleness, days since commit, health summary) shared by the routes |
| `app/api/*` | FastAPI routers, dependency wiring, SPA fallback |
| `app/__main__.py` | CLI subcommands, output formatting, exit codes (also installed as `git-dashboard`) |
| `frontend/` | Buildless UI: `index.html` plus `assets/{styles.css,api.js,ui.js,charts.js,views.js,app.js}` |

## HTTP API surface

| Group | Endpoints |
| --- | --- |
| System | `GET /api/health`, `/api/version`, `/api/dashboard`, `/api/insights`, `/api/activity`, `/api/activity/repositories`, `/api/branches` |
| Repositories | `GET`/`POST /api/repositories`, `POST /api/repositories/bulk`, `GET`/`DELETE /api/repositories/{id}`, `GET /api/repositories/{id}/status`, `GET /api/repositories/suggestions`, `POST /api/repositories/discover`, `GET /api/repositories/compare?ids=1,2` |
| Commits | `GET /api/repositories/{id}/commits`, `GET /api/repositories/{id}/commits/{sha}` |
| Branches | `GET /api/repositories/{id}/branches` |
| Analytics | `GET /api/repositories/{id}/(metrics\|activity\|contributors\|contributor-trends\|heatmap\|file-churn\|health\|recent-activity)` |
| Scanning | `POST /api/repositories/{id}/scan`, `POST /api/scan/all`, `/api/scan/full`, `/api/scan/repositories`, `GET /api/scan/status`, `/api/scan/jobs`, `/api/scan/history` |
| Settings & export | `GET`/`PUT /api/settings`, `GET /api/settings/roots`, `GET /api/export/json`, `GET /api/export/csv/{table}`, `POST /api/export/snapshot`, `POST /api/export/backup` |

Per-repository insights are intentionally *not* an endpoint: `/api/insights`
returns recommendations for every repository, and the repository page filters
them client-side. Unknown non-API paths return `index.html` (SPA fallback),
unknown `/api/…` paths return JSON `404`.

## Data model

| Table | Key columns | Notes |
| --- | --- | --- |
| `repositories` | `path_key` (unique), `state`, `staleness`, `health_score`, cached counts | One row per registered repository; `path_key` is case-folded so the same path cannot be registered twice |
| `branches` | `repository_id`, `name`, `is_remote`, `is_current`, `is_stale`, `is_merged`, `ahead`, `behind`, `age_days` | Replaced on every scan |
| `commits` | `repository_id`, `sha`, `authored_at`, `is_merge`, `additions`, `deletions` | Unique per `(repository_id, sha)` |
| `file_changes` | `repository_id`, `commit_sha`, `path`, `change_type`, additions/deletions | `change_type` is `added`, `deleted` or `modified`; capped per commit by `file_changes_per_commit_limit` |
| `contributors` | `repository_id`, `name`, `email`, counts | Derived from stored commits |
| `scan_runs` | `repository_id` (NULL for an aggregate run), `status`, counters, `duration_ms` | Append-only audit trail of every scan |
| `app_state` | key/value | Reserved for small persisted flags |

Every child table cascades from `repositories`, so unregistering a repository
deletes its data. The database uses WAL mode and a busy timeout, which keeps
reads working while a scan writes.

### Where Git is executed

`app/collectors/git_runner.py` owns the only `subprocess` call in the project;
everything else asks it for output. The runner pins a deterministic environment
(`GIT_TERMINAL_PROMPT=0`, `GIT_PAGER=cat`, `GIT_OPTIONAL_LOCKS=0`, `LC_ALL=C.UTF-8`),
applies a per-invocation timeout and reduces failures to one readable line.
The server probes Git once during startup and caches the result, so no request
handler ever waits on a process.

### Incremental scans

The scan service stores the newest commit SHA per repository. The next
incremental scan asks Git for `git log --all --not <sha>`, so only new commits
are parsed and inserted; when the SHA is unknown (rewritten history, garbage
collection) the collector falls back to a full walk and says so in the scan
warnings.

## Health score

The score is a weighted sum of five signals, weights summing to exactly 1.0:

| Signal | Weight | Inputs |
| --- | --- | --- |
| `activity` | 0.30 | days since the last commit |
| `branch_hygiene` | 0.25 | stale branch ratio, merged branches still present |
| `working_tree` | 0.20 | uncommitted/untracked files, detached HEAD |
| `recent_commits` | 0.15 | commits in the last 30 days |
| `maintenance` | 0.10 | remote configured, scan health, hygiene checks |

`GET /api/repositories/{id}/health` returns each signal with its weight, its raw
score and its contribution (`score × weight`), so the number on screen can be
recomputed by hand. Grades are `A ≥ 85`, `B ≥ 70`, `C ≥ 55`, `D ≥ 40`, `E ≥ 25`,
`F` below that.

## Design decisions

- **No `subprocess` in request handlers.** Scanning is a service operation;
  HTTP requests read stored data. Background scans run in a worker thread owned
  by `ScanManager`, and the UI polls `/api/scan/status`.
- **Warnings are first-class.** A repository that is dirty, detached, empty,
  capped at `history_depth` or has a broken remote still scans; the warning is
  stored on the outcome and surfaced in the UI. Only real failures (missing
  repository, Git errors, database errors) make a scan `failed`/`partial`.
- **Counts come from Git.** Totals such as `total_commits` come from
  `git rev-list --count`, not from the number of rows a particular scan happened
  to insert, so a capped history never silently redefines "total commits".
- **Merge commits carry no file statistics.** `git log --numstat` prints no diff
  for merges, so they are stored with `files_changed = 0` and `is_merge = 1`
  (the API explains this in a `note` instead of pretending the commit changed
  nothing).
- **Discovery never raises on permissions.** Unreadable directories are skipped
  and counted, because a projects root often contains directories the user
  cannot read.
- **No build step and no npm.** The frontend is `index.html` plus six static
  assets served from `/static` and loaded in one fixed order: `api.js` (client
  and `Fmt` helpers), `ui.js` (icon set, theme, toasts, modal, command palette),
  `charts.js` (SVG renderers), `views.js` (one function per route) and `app.js`
  (router, shell behaviour). The server falls back to `index.html` for unknown
  non-API paths so client-side routes work on a hard refresh.
- **One stylesheet, token driven.** `styles.css` defines every colour, radius,
  shadow and type scale as a CSS custom property, overridden for the dark theme
  under `[data-theme="dark"]` (with a `prefers-color-scheme` fallback for users
  who never touched the switch). Charts read the same variables, so they follow
  the theme without re-rendering.
- **Frontend state lives in one place.** Filters and view preferences are
  persisted in `localStorage` under `git-dashboard-state-v1`, the colour theme
  under `git-dashboard-theme`; nothing is inferred from the server.
