# Local Git Repository Dashboard

A self-contained, local dashboard for discovering, analyzing and monitoring the
Git repositories on your machine.

The project does **not require the GitHub API, cloud services, paid APIs or a
hosted database**. Repositories are analyzed locally through the Git CLI, the
results are stored in SQLite and presented in a local web dashboard. It keeps
working with the network switched off.

## Features

- Discover local Git repositories under one or more configured roots
- Register repositories manually or through directory scanning
- Analyze branches, commits, contributors and file changes
- Detect uncommitted changes and detached HEAD repositories
- Identify merged, inactive and stale branches
- Calculate repository activity and health metrics
- Incrementally scan repositories (only new commits are collected)
- Store normalized data in SQLite
- Browse repositories in a local web UI, including commit history and details
- Run scans through the CLI or the HTTP API
- Export JSON snapshots, CSV dumps and SQLite backups

## Architecture

```text
                 Local Machine
                      │
                      ▼
              Repository Discovery
                      │
                      ▼
                Git Collectors
                      │
                      ▼
                 Normalization
                      │
                      ▼
                    SQLite
                      │
             ┌────────┴────────┐
             ▼                 ▼
        REST API          CLI / Services
             │
             ▼
        Web Dashboard
```

### Architectural boundary

Git execution is deliberately isolated in the collector layer. The API layer does
not execute Git commands, so a slow repository or a hung `git` process can never
block a web request.

```text
app/
├── api/          # HTTP/API layer (routes, request models, dependency wiring)
├── collectors/   # Git interaction: the only place a process is spawned
├── analyzers/    # Metrics and health analysis over stored data
├── services/     # Application services (scanning, discovery, exports)
├── database/     # SQLite schema, connection handling and queries
├── models/       # Request/response schemas for the API
└── __main__.py   # Command-line interface (`python -m app`)
```

This boundary is enforced by automated tests
(`tests/test_api.py::test_request_handlers_never_spawn_processes`).

## Requirements

- Python 3.10 or newer (developed and verified on 3.11)
- Git on `PATH`
- A local Git repository, or a directory containing repositories
- A modern web browser

No GitHub account, token or API access is required.

## Installation

```bash
git clone https://github.com/deathtoconding/gitbhub-dashboard.git
cd gitbhub-dashboard

python3 -m venv .venv
source .venv/bin/activate        # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Optional — install the development tooling and the `git-dashboard` console
script (the commands below use `python -m app`, which works without installing):

```bash
pip install -e ".[dev]"     # editable: the checkout stays the source of truth
python -m pytest            # verify the checkout
```

Use an **editable** install or run from the checkout: the UI assets (`frontend/`)
and local data (`data/`) live next to the source. A copied, non-editable
`pip install .` serves the JSON API under `/api` only and answers `/` with a clear
message instead of pretending the UI is there.

## Quick start

```bash
python -m app init-config            # writes config.json (refuses to overwrite; --force resets)
$EDITOR config.json                  # set "repository_roots"
python -m app discover --register    # find repositories and register them
python -m app scan --all             # collect commits, branches, contributors
python -m app start                  # http://127.0.0.1:8000
```

### One-command setup

`scripts/dev_server.sh` performs the setup above and starts the server; it is
idempotent, so it is also the way to bring a machine back to a serving state:

```bash
scripts/dev_server.sh                                  # 0.0.0.0:8000, demo dataset
scripts/dev_server.sh --root ~/projects --skip-demo     # your own repositories
```

### Everyday commands

```bash
python -m app scan --all                  # incremental: only new commits
python -m app scan 3                      # one repository (by id)
python -m app scan --all --full-history   # re-walk complete histories
python -m app scan --all --discover       # also pick up repositories added on disk
python -m app repositories                # list repositories
python -m app status                      # summary, git version, latest scan runs
python -m app insights                    # actionable recommendations
python -m app export --format json        # data/exports/dashboard-*.json
python -m app export --format csv         # data/exports/csv/*.csv
python -m app export --format backup      # data/backups/dashboard-*.db
```

Add `--json` (before or after the subcommand) for machine-readable output.

Then open <http://localhost:8000>.

A minimal `config.json`:

```json
{
  "repository_roots": ["/home/me/projects", "/home/me/work"],
  "database_path": "data/dashboard.db"
}
```

Every other key has a default; see [docs/configuration.md](docs/configuration.md).

## Dashboard

### Overview

Aggregate metrics for every registered repository:

- Repository, commit, branch and contributor counts
- Stale branches and stale repositories
- Uncommitted files and dirty repositories
- Detached HEAD repositories
- Average repository health and failing repositories

### Repositories

A searchable, sortable repository list with state, staleness, branch, change
count, health grade and last commit; scan or open any row.

### Activity

Commit activity across repositories over a selectable window (day/week/month).

### Branches

Branch hygiene across all repositories: current, remote, merged, inactive and
stale branches with age and upstream information.

### Repository detail

Per repository: **Overview** (working tree, health signals, recent commits),
**Commits** (search, filters, per-commit file changes), **Branches**,
**Contributors** and **Insights**.

### Settings

Repository roots, scan thresholds, exports (JSON/CSV/backup) and the effective
configuration.

## Data model

The application stores normalized local Git information in SQLite:

```text
Repositories
Branches
Commits
Contributors
File changes
Scan runs
```

Git remains the source of truth; SQLite provides the searchable, queryable
representation that the UI and API read. The full schema, column semantics and
relationships are documented in [docs/architecture.md](docs/architecture.md).

## Incremental scanning

The scanner avoids unnecessary work. After an initial scan the newest commit SHA
per repository is persisted, and the next scan asks Git only for commits that are
not reachable from it (`git log --all --not <sha>`).

```text
Initial scan            Next scan
    ↓                       ↓
545 commits collected   nothing new
    ↓                       ↓
state persisted         0 additional commits collected
```

Repeated scans are idempotent, and a full re-walk is always available with
`python -m app scan --all --full-history`.

## Repository health

Health is computed from observable repository properties, deterministically and
locally — no external service and no AI model. Five weighted signals add up to
the score (weights sum to 1.0):

| Signal | Weight | Inputs |
| --- | --- | --- |
| `activity` | 0.30 | days since the last commit |
| `branch_hygiene` | 0.25 | stale branch ratio, merged branches still present |
| `working_tree` | 0.20 | uncommitted/untracked files, detached HEAD |
| `recent_commits` | 0.15 | commits in the last 30 days |
| `maintenance` | 0.10 | remote configured, scan health, hygiene checks |

`GET /api/repositories/{id}/health` returns every signal with its weight, raw
score and contribution, so the displayed number can be recomputed by hand.
Grades: `A ≥ 85`, `B ≥ 70`, `C ≥ 55`, `D ≥ 40`, `E ≥ 25`, `F` below that.

## HTTP API

Every view is backed by JSON endpoints under `/api`; the interactive schema is at
<http://localhost:8000/docs> and the OpenAPI document at `/openapi.json`. Scans
run in the background: `POST /api/scan/all` with `{"background": true}` returns
`202` and a job, and `GET /api/scan/status` reports
`progress: {done, total}` until `running` is `false`. The endpoint groups are
listed in [docs/architecture.md](docs/architecture.md#http-api-surface).

## Verification

Automated and manual verification was run against commit `7fcf8da` on
2026-10-05 (the documentation commit that follows changes no code):

```text
python -m pytest                 193 passed, 4 deselected
python -m pytest -m slow         4 passed (1/10/50/100 repositories)
python -m pytest -m requires_git 63 passed, 134 deselected
ruff check app tests scripts     clean
ruff format --check app tests scripts  clean
```

The manual record covers a live API workflow (8 repositories, 545 commits,
incremental rescan), a fresh-install workflow in an empty directory, a headless
UI walk through every view and dialog, and the architecture-boundary check. The
complete record — commands, observed output, discovered bugs, known limitations
and the exact commit history — is in [docs/verification.md](docs/verification.md).

## Verified demo dataset

`scripts/create_demo_repos.py` generates the dataset below; all figures in the
table come from scanning it.

```text
Repositories:       8
Commits:            545
Branches:           22
Stale branches:      8
Contributors:        5
Uncommitted files:   5
Dirty repositories:  2
Stale repositories:  2
Detached repos:      1
Bare mirrors:        1
Empty repositories:  1
Average health:    72.0
```

Try it without touching your own repositories:

```bash
python scripts/create_demo_repos.py --target data/demo --repos 8 --seed 1337
python -m app --config config.json discover --register
python -m app --config config.json scan --all
```

`--seed` keeps the generated histories reproducible; `--repos` caps the dataset
at the eight repository archetypes (clean, dirty, detached, bare mirror, empty,
abandoned, busy, small).

## Merge commits

Git does not produce a normal per-file diff for merge commits through:

```bash
git log --numstat
```

A merge commit may therefore legitimately have `file_count = 0`. The API states
this explicitly instead of leaving it as a missing value:

```json
{
  "file_count": 0,
  "note": "Merge commit: git reports no per-file diff for merges, so no file statistics are stored for it."
}
```

The commit row keeps `is_merge = 1` and its real author, date and message, so
merges are still counted in history, activity and contributor statistics.

## Development principles

- **Local-first** — the dashboard stays useful without any cloud service.
- **Git as source of truth** — metadata comes from the local Git CLI; nothing is
  invented and nothing is inferred from a hosted API.
- **Layered architecture** — Git execution, persistence, analysis, services and
  HTTP presentation are separate, with a test enforcing the boundary.
- **Fail gracefully** — one broken repository never aborts a scan; warnings are
  surfaced instead of being swallowed.
- **Test behaviour, not implementation details** — tests build real repositories
  and drive the whole pipeline rather than mocking Git.
- **Incremental processing** — repeated scans avoid unnecessary work.
- **Explicit over implicit** — unknown configuration keys, missing roots and
  unimplemented behaviour are reported, never guessed at.

## Project status

Complete for its defined MVP scope:

- Application code, CLI and REST API
- SQLite persistence with migrations
- Repository discovery, Git collectors and normalization
- Repository analytics and health analysis
- Web dashboard (buildless, no npm)
- Unit, integration, failure, CLI and performance tests
- Documentation: architecture, configuration, verification and development

## Out of scope

The current version intentionally does not include:

- GitHub API integration
- Cloud database or hosted deployment
- Paid APIs
- AI/LLM dependency
- GitHub Actions CI workflow
- An explicit project license

None of these change the core local-first architecture; each can be added
independently.

## License

No license has currently been declared.

If this repository is intended for public redistribution, add an explicit
open-source license before presenting it as an open-source project.

## Roadmap

Implemented already (listed here because they were originally planned as future
work): CSV/JSON export, repository comparison, file-churn analysis, commit
heatmaps and contributor trends.

Potential future work:

1. CI workflow (lint + tests on push)
2. License
3. More advanced health analytics
4. Optional local LLM integration for narrative summaries
5. Desktop packaging
6. Optional GitHub API integration (additive, never required)

The core application does not depend on any of these.

## Further documentation

| Document | Contents |
| --- | --- |
| [docs/architecture.md](docs/architecture.md) | Pipeline, module map, data model, health model, design decisions |
| [docs/configuration.md](docs/configuration.md) | Every configuration key, its default and its effect |
| [docs/verification.md](docs/verification.md) | Reproducible verification record and known limitations |
| [docs/development.md](docs/development.md) | Local setup, test strategy, conventions, how to extend |
