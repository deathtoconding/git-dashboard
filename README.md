# gitbhub-dashboard

A local-first dashboard for the Git repositories already on your machine.

Point it at a directory, it finds the repositories inside it, scans them with the
`git` command line and stores what it finds in a SQLite file next to the project.
The web UI then shows activity, branches, contributors, file churn and a
transparent health score per repository.

Everything is computed from Git data. There is no GitHub API, no OAuth token, no
telemetry, no cloud service and no build step — the dashboard keeps working with
the network switched off.

## What it gives you

- **Repository discovery** — walk a "projects root" (or several) and register
  every Git repository found, including bare mirrors, without typing paths one by
  one.
- **Commits and file changes** — history per repository with per-file
  additions/deletions, search by subject/SHA/author/date.
- **Branches** — local and remote branches with age, upstream tracking, ahead and
  behind counts, merged/unmerged status.
- **Contributors** — commits, lines added/deleted and last activity per person,
  with weekly trends.
- **Activity** — commit series by day/week/month, heatmap by weekday and hour.
- **Health and insights** — a weighted score with every signal and its
  contribution exposed, plus concrete recommendations ("12 uncommitted files",
  "no commits in 120 days", "3 stale branches").
- **Exports** — JSON snapshots, CSV dumps of every table and SQLite backups.

## Requirements

- Python 3.10 or newer
- `git` on `PATH` (the dashboard shells out to it; no libgit2, no extra binaries)

## Quick start

```bash
git clone https://github.com/deathtoconding/gitbhub-dashboard.git
cd gitbhub-dashboard

python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python -m app init-config                 # writes config.json
$EDITOR config.json                       # set "repository_roots"
python -m app discover --register         # find and register repositories
python -m app scan --all                  # collect commits, branches, contributors
python -m app start                       # http://127.0.0.1:8000
```

A minimal `config.json` for a normal setup:

```json
{
  "repository_roots": ["/home/me/projects", "/home/me/work"],
  "database_path": "data/dashboard.db"
}
```

Every other key has a default; the full reference is in
[docs/configuration.md](docs/configuration.md).

## Everyday use

Scans are explicit: the dashboard never watches the filesystem and never changes
your repositories. When you want fresh numbers, press **Scan all repositories**
in the UI or run a scan from the shell — no restart required.

```bash
python -m app scan --all                  # incremental: only new commits
python -m app scan 3                      # one repository (by id)
python -m app scan --all --full-history   # re-walk complete histories
python -m app scan --all --discover       # pick up repositories added on disk
python -m app status                      # repositories, health, latest scan runs
python -m app insights                    # recommendations as text
python -m app doctor                      # check git, config, database, roots
python -m app export --format json        # data/exports/dashboard-*.json
python -m app export --format csv         # data/exports/csv/*.csv
python -m app export --format backup      # data/backups/dashboard-*.db
```

Add `--json` (before or after the subcommand) for machine-readable output.

## What it does not do

- No GitHub/GitLab API access and no authentication of any kind: it is a
  single-user, local tool. Keep it on `127.0.0.1` (the default) unless the
  machine itself is trusted.
- No live file watching: figures change when you rescan.
- No write operations on your repositories: `git log`, `git status`,
  `git branch`, `git rev-list`, `git shortlog` and friends are read-only.
- No hosted or multi-user mode, no accounts, no sharing.

## HTTP API

All endpoints live under `/api`; the interactive OpenAPI page is at
`http://127.0.0.1:8000/docs`.

| Group | Endpoints |
| --- | --- |
| System | `GET /api/health`, `GET /api/version`, `GET /api/dashboard`, `GET /api/insights`, `GET /api/activity`, `GET /api/activity/repositories`, `GET /api/branches` |
| Repositories | `GET/POST /api/repositories`, `POST /api/repositories/bulk`, `GET/DELETE /api/repositories/{id}`, `GET /api/repositories/{id}/status`, `GET /api/repositories/suggestions`, `POST /api/repositories/discover`, `GET /api/repositories/compare?ids=1,2` |
| Commits | `GET /api/repositories/{id}/commits`, `GET /api/repositories/{id}/commits/{sha}` |
| Branches | `GET /api/repositories/{id}/branches` |
| Analytics | `GET /api/repositories/{id}/(metrics\|activity\|contributors\|contributor-trends\|heatmap\|file-churn\|health)` |
| Scanning | `POST /api/repositories/{id}/scan`, `POST /api/scan/all`, `POST /api/scan/full`, `POST /api/scan/repositories`, `GET /api/scan/status`, `GET /api/scan/jobs`, `GET /api/scan/history` |
| Settings & export | `GET/PUT /api/settings`, `GET /api/settings/roots`, `GET /api/export/json`, `GET /api/export/csv/{table}`, `POST /api/export/snapshot`, `POST /api/export/backup` |

Scans can run in the background: `POST /api/scan/all` with
`{"background": true}` returns `202` and a job id; poll `GET /api/scan/status`
for `progress: {done, total}` until `running` is `false`.

## Configuration

Precedence, highest first:

1. CLI flags (`--host`, `--port`, `--database`, `--log-level`)
2. Environment variables prefixed `GITDASH_` (`GITDASH_PORT=9000`)
3. `config.json` (path from `--config` or `GITDASH_CONFIG`)
4. Built-in defaults

Unknown keys are rejected with a clear error instead of being silently ignored.
See [docs/configuration.md](docs/configuration.md) for every key, its default and
what it changes.

## Data on disk

| Path | Contents |
| --- | --- |
| `data/dashboard.db` | SQLite database: repositories, branches, commits, file changes, contributors, scan runs |
| `data/backups/` | `export --format backup` copies |
| `data/exports/` | JSON snapshots and CSV dumps |
| `data/logs/dashboard.log` | Rotating log file (`python -m app start`) |
| `data/demo/` | Repositories created by `scripts/create_demo_repos.py` for trying the dashboard out |

The database and everything under `data/` are generated and git-ignored:
deleting the file simply means the next scan re-collects everything.

`scripts/create_demo_repos.py` builds a small but messy demo dataset (clean,
dirty, detached, bare, empty and abandoned repositories) so you can explore the
UI without pointing it at your own work:

```bash
python scripts/create_demo_repos.py --root data/demo   # 8 repositories, ~545 commits
python -m app discover --register && python -m app scan --all
```

## Testing

```bash
pip install -r requirements-dev.txt
python -m pytest                  # fast suite (~8s)
python -m pytest -m slow          # performance tests on 1/10/50/100 repositories
python -m pytest -m requires_git  # only tests that need a real git binary
```

The tests build real repositories in temporary directories and drive the whole
pipeline (filesystem → discovery → scan → SQLite → analysis → API) instead of
mocking Git, so they fail when Git plumbing or parsing actually breaks. The
performance tests print a `[perf]` line with timings, database size and API
latencies.

Linting:

```bash
pip install ruff
ruff check app tests scripts
```

## Troubleshooting

- **"Git executable 'git' is not available"** — install Git or point
  `git_binary` at the executable; `/api/health` reports the same problem.
- **Repositories are not found** — check `repository_roots` in
  `/api/settings/roots` (missing roots are listed there), raise `max_scan_depth`
  and remember that `excluded_dirs` is skipped during the walk.
- **A repository is trimmed to `history_depth` commits** — raise
  `history_depth`; the scan reports a `History was capped at …` warning instead
  of silently truncating.
- **Scan times out** — raise `git_timeout_seconds` (the timeout is per Git
  invocation).
- **`file_count: 0` on a commit** — merge commits have no per-file diff in
  `git log --numstat`, so they are stored without file statistics; the API adds
  an explanatory `note`.
- **Unreadable directories** — directories the process cannot read are skipped
  and counted in the discovery result instead of aborting the walk.

## How it works

```
filesystem ──▶ discovery ──▶ git CLI (collectors) ──▶ SQLite (store)
                                                         │
                        browser ◀── FastAPI ◀── analyzers (metrics, health, insights)
```

Git is only ever invoked from the collector layer, never from a request handler:
API calls read the SQLite database. The full design, module map and data model
are in [docs/architecture.md](docs/architecture.md).
