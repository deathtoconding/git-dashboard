# Verification record

This document records how the dashboard was verified, what was observed, which
bugs were found and fixed, and what is *not* covered. It is meant to be
reproducible: every command below can be run in a clean checkout and produces
comparable output.

**Verification date:** 2026-10-05
**Verified revision:** `4b44515` — the twenty-fifth commit on top of the initial
commit (`git rev-list --count d2f514d..4b44515` = 25). The commit that adds this
document changes documentation only, so the results apply to the branch tip as
well.

History at that revision (oldest first): `ea78be4` application, `9361253` test
suite, `2618478` documentation and fixes found while verifying, `23952d1`
architecture-boundary test, `4ac35a8` startup Git probe, `54385da` CLI safety and
CLI tests, `d842c0a` markers and dev extras, `f49127c` version guard, `1cb60d3`
formatting, `4eada1e` packaging, `27ba32e` documented-endpoint test, `0e850dd`
global CLI flags, `7fcf8da` UI smoke script, `ea12a99` documentation restructure,
`b11a8ee` bootstrap script, `3cd3a04` ruff in dev requirements, `4a557bd` design
system, `9aac550` UI kit, `d1993e6` theme-aware charts, `2c25e28` derived
repository fields, `72e08a3` rebuilt shell and views, `a1efecb` UI audit,
`fe698ba` UI documentation, `e7dcb0a` briefing analyser, `9bc53e1` briefing panel,
`4b44515` triage presets.

## Environment

| Component | Version |
| --- | --- |
| Python | 3.11.2 (`requires-python = ">=3.10"` in `pyproject.toml`) |
| Git | 2.39.5 |
| pytest | 9.1.1 |
| ruff | latest installed via `pip install ruff` |
| Node.js + jsdom | 22.x + jsdom 30.1.2 (only for the ad-hoc UI check below) |
| OS / user | Linux sandbox, unprivileged non-root user |

The non-root user matters for one test: `chmod 0` directories really deny access.

## 1. Automated test suite

```bash
cd /home/user/gitbhub-dashboard
python -m pytest                       # fast suite, slow tests deselected by default
python -m pytest -m requires_git       # every test that needs a real git binary
python -m pytest -m slow -s            # performance tests, prints [perf] lines
```

Observed:

```text
python -m pytest                  202 passed, 4 deselected, 1 warning in 10.23s
python -m pytest -m requires_git   63 passed, 143 deselected, 1 warning in 25.81s
python -m pytest -m slow -s        4 passed, 202 deselected, 1 warning in 21.18s
```

The single warning is a third-party deprecation notice from
`starlette.testclient` (`Using httpx with starlette.testclient is deprecated`);
it is emitted by the installed Starlette version, not by this project.

Coverage by module:

| Test module | What it proves |
| --- | --- |
| `test_config.py` | defaults, file/env/CLI precedence, validation and error messages |
| `test_cli.py` | `python -m app` commands, global flag positions, exit codes, idempotency, exports |
| `test_discovery.py` | repository/bare detection, excluded dirs, depth, unreadable dirs, duplicate roots |
| `test_parsers.py` | commit/numstat parsing, merges, binary files, timestamps, junk input |
| `test_database.py` | schema, upserts, filters, pagination, cascades, scan runs |
| `test_collectors.py` | repository states, branch classification, incremental walks, contributors |
| `test_analyzers.py` | metrics, activity, heatmap, churn, branch health, health transparency, insights |
| `test_briefing.py` | the briefing prose: empty/clean workspaces, severity order, the 5-line cap, number fidelity, possessives, missing inputs, scan fallback |
| `test_api.py` | every route, scan/export/settings, SPA fallback, architecture boundary, documented-endpoint list, index.html asset integrity |
| `test_logging.py` | repository context, one-line records, tolerant setup |
| `test_integration.py` | discovery → scan → SQLite → analysis → API end to end |
| `test_failures.py` | missing git, vanished/corrupt/read-only repositories, timeouts, database failures |
| `test_performance.py` | 1/10/50/100 repositories with timing regression guards |

## 2. Linting and formatting

```bash
ruff check app tests scripts
ruff format --check app tests scripts
```

Observed:

```text
All checks passed!
58 files already formatted
```

## 3. Performance

`python -m pytest -m slow -s` builds real repositories, scans them and prints one
line per repository count:

```text
[perf] repositories=  1 fixture_build=  0.03s discovery= 0.005s scan= 0.041s incremental_scan= 0.040s db=    120.0 KiB api_list=   27.0ms api_dashboard=   10.2ms api_commits=    9.1ms
[perf] repositories= 10 fixture_build=  0.31s discovery= 0.036s scan= 0.361s incremental_scan= 0.393s db=    128.0 KiB api_list=   29.8ms api_dashboard=   20.5ms api_commits=    9.1ms
[perf] repositories= 50 fixture_build=  1.60s discovery= 0.186s scan= 2.081s incremental_scan= 1.932s db=    288.0 KiB api_list=   25.8ms api_dashboard=   56.0ms api_commits=    9.1ms
[perf] repositories=100 fixture_build=  3.48s discovery= 0.403s scan= 3.800s incremental_scan= 3.891s db=    452.0 KiB api_list=   28.6ms api_dashboard=  100.3ms api_commits=    8.7ms
```

Each repository contains 3 commits and ~26 KiB of `.git`. Two observations worth
keeping in mind: scanning is dominated by process spawns (one `git` invocation
per data area per repository), and dashboard latency grows roughly linearly with
repository count because it aggregates every repository in one request.

## 4. Fresh-install workflow

The steps below are also available as a script, which is what a fresh machine or
a wiped workspace should use:

```bash
scripts/dev_server.sh            # venv -> deps -> config -> demo -> discover -> scan -> serve
```

Observed on an empty workspace (15.5s from nothing to a serving dashboard):
creating the venv, installing dependencies, writing `config.json`, generating the
demo dataset, `8 repository(ies) found.`, `8 scanned, 0 failed, 545 commits added
in 365ms`, then `Uvicorn running on http://0.0.0.0:8000`. A second run reported
`keeping the existing config.json`, skipped the demo generation, and started a
second instance on port 8999 (`/api/health` → `200`), confirming idempotency.

The individual commands:

An empty directory, an empty environment, no database and no `config.json`:

```bash
export GITDASH_CONFIG=/tmp/fresh2/config.json
export GITDASH_DATABASE_PATH=/tmp/fresh2/data/dashboard.db

python scripts/create_demo_repos.py --target /tmp/fresh2/projects --repos 8 --seed 1337
python -m app init-config
# set repository_roots to ["/tmp/fresh2/projects"]
python -m app discover --register
python -m app scan --all
python -m app doctor
```

Observed:

```text
8 repository(ies) found.
8 scanned, 0 failed, 545 commits added in 339ms
[ok] Git          : git v2.39.5
[ok] Database     : /tmp/fresh2/data/dashboard.db (schema v1, 122880 bytes)
[ok] Root         : /tmp/fresh2/projects
[ok] Repositories : 8 registered, 0 unregistered under the configured roots
Everything looks good.
```

Also checked: with no roots configured, `discover --register` fails with a clear
message (`No repository roots configured…`) instead of scanning the filesystem
root, and `scan --all` reports `No repositories registered.` with a hint.

## 5. Live API workflow

Against the running server (`python -m app --config config.json start --host 0.0.0.0 --port 8000`):

```text
POST /api/scan/all {"incremental": true, "discover": true, "background": true}
  -> 202 Accepted
job: completed  progress {"done": 8, "total": 8}
  report {"scanned": 8, "failed": 0, "commits_added": 0, "duration_ms": 289}

GET /api/dashboard
  cards: {"average_health": 72.0, "branches": 22, "commits": 545, "commits_last_30d": 114,
          "contributors": 5, "detached_repositories": 1, "dirty_repositories": 2,
          "failing_repositories": 0, "repositories": 8, "stale_branches": 8,
          "stale_repositories": 2, "uncommitted_changes": 5}

GET /api/scan/history?limit=3
  [("full", "completed", 0, 8), ("full", "completed", 0, 8), ("full", "completed", 0, 8)]
  (kind, status, commits_added, repositories_scanned)

GET /api/repositories/1/commits?search=merge&per_page=1 -> adf9addc799d97d83aa625a601fb8419053666a4
GET /api/repositories/1/commits/adf9addc…
  file_count = 0
  note = "Merge commit: git reports no per-file diff for merges, so no file statistics are stored for it."
```

The second scan adds 0 commits, which is the incremental path working: state was
persisted by the first scan and no new history existed.

All read endpoints answered `200`: `/`, `/api/health`, `/api/version`,
`/api/dashboard`, `/api/repositories`, `/api/repositories/{id}` and its
`metrics`/`commits`/`branches`/`contributors`/`health`/`status`/`heatmap`/
`file-churn`/`activity`/`contributor-trends` sub-resources, `/api/activity`,
`/api/activity/repositories`, `/api/branches`, `/api/insights`,
`/api/scan/status`, `/api/scan/history`, `/api/settings`, `/api/settings/roots`,
`/api/repositories/suggestions`, `/api/repositories/compare?ids=1,4`,
`/api/export/json`, `/api/export/csv/repositories`, `/openapi.json`, `/docs`.
`/api/repositories/1/insights` correctly answers `404` (insights are a global
endpoint; the repository page reuses `Views.insightsHtml`).

## 6. UI verification (headless)

Two optional developer tools (Node + jsdom, see their headers) loaded the real
page from the running server with `fetch` replaced by a recorder. Nothing in the
application depends on them.

```bash
npm install --prefix /tmp/ui-smoke jsdom
NODE_PATH=/tmp/ui-smoke/node_modules node scripts/ui_smoke.js http://127.0.0.1:8000
NODE_PATH=/tmp/ui-smoke/node_modules node scripts/ui_audit.js http://127.0.0.1:8000
```

`scripts/ui_smoke.js` walks every view, every repository tab and the commit
dialog:

```text
errors: []            failedRequests: []        requests: 26 (20 unique paths)
/repositories: ok     /activity: ok             /branches: ok
/settings: ok         /: ok                     repository detail: /repositories/1
repo tab commits: ok  branches: ok              contributors: ok      insights: ok
commit modal: ok (Commit 9aa58f57 …)
repository rows: 8    theme toggle: null -> light   palette: ok (1 entry after filter)
```

`scripts/ui_audit.js` asserts that the design system and the narrative layer are
actually wired up rather than merely present, and finishes by driving a real
scan:

```text
errors: []
briefing: 2 findings need a decision (5 lines)   findings: 15 in 3 severity groups
presets: 8 rows -> 1 dirty -> back               theme states: light, dark, system
tabs rendered: 5                                 branch rows: 22 -> 8 after the stale filter
scan progress indicator seen: state-dot state-dot--busy
expectedRepositories: 8                          audits: 9
```

The narrative layer is also checked against the live payload: on the demo dataset
the briefing reports `tone: danger`, `"2 findings need a decision"`, five lines in
severity order (decay, uncommitted, detached HEAD, stale branches, activity), a
"Do this first" pointing at the coldest repository, and a footer naming the last
scan (`8 scanned · +0 commits · 289 ms` from the live job, falling back to the
persisted `scan_runs` row after a restart).

What the audit checks: 6 KPI cards with a rendered activity chart and sparkline,
sidebar and page badges matching `/api/repositories`, health meters for every row,
the briefing panel (tone class, headline, summary, ≤ 5 severity-ordered lines,
footer, "Do this first"), findings grouped into severity buckets, the triage
presets actually narrowing the list and persisting their filter, health ring plus
the five weighted signal bars on the repository page, 168 heatmap cells and 10
churn bars, `aria-selected` tracking while the audit walks
five of the six repository tabs, modal focus moving inside
the dialog and back on close, the theme cycling light → dark → system with the
choice persisted, `g r` keyboard navigation, persisted bucket state after a
re-render, an accessible name on every button/link/tab of each view, and the
sidebar scan button producing a busy indicator, a progress bar, a completion
toast, a re-enabled button and an `ok` indicator.

Colour contrast was verified by computing WCAG ratios from the token values (no
browser needed): body text on surface 17.85:1 light / 15.04:1 dark, muted text
5.43 / 6.91, primary button label 4.63 / 7.48, and every badge/status pair
≥ 4.5:1 in both themes after darkening the light-theme `--ok` and `--warn`
tokens (they were 4.44 and 4.17).

Layout, native rendering, animations and print output are **not** covered here —
see the known limitations below.

## 7. Architecture boundary

`tests/test_api.py::test_request_handlers_never_spawn_processes` fails if
`subprocess`, `Popen`, `.run(` or `check_output(` appears anywhere under
`app/api/`. Git is only executed by `app/collectors/`, and the server probes it
once in the startup hook, so no request handler waits on a Git process.

## Bugs found and fixed during verification

| Symptom | Cause | Fix |
| --- | --- | --- |
| `/api/repositories/{id}/commits/{sha}` returned `404` for a short SHA shown in the UI | lookup matched the full SHA or the stored `short_sha` only | `Store.get_commit` now accepts any hexadecimal prefix |
| Repository rows were dumped verbatim into log lines | `get_repo_logger` did `str()` on dict rows | dict rows resolve to `name`/`path`, covered by `tests/test_logging.py` |
| Saved UI preferences were dropped on reload | boot merged only `repoFilters` from `localStorage` | the persisted state is merged wholesale |
| `init-config` silently overwrote a hand-edited `config.json` | `save_settings` wrote unconditionally | refuses without `--force`; `--force` resets to defaults |
| A typo in `--config` silently used defaults (looked like "empty dashboard") | missing explicit config file was ignored | warning naming the missing file |
| `repositories.state` NOT NULL violation when a caller omitted `state` | upsert did not default the column | defaults to `"unknown"` |
| Overview tables showed no health and a "never" age for every repository | `/api/dashboard` returned raw rows while `/api/repositories` enriched them with derived fields | enrichment moved to `app/api/serializers.py` and used by both routes, with a test comparing the payloads |
| Briefing could read "1 finding need a decision" and "0 repositories need a decision" | headline built from one plural helper with no subject/verb agreement, and a danger tone that can come from the average score alone | verb agreement is handled per count and a score-only danger tone reports the score instead of a zero finding count; both cases are unit-tested |
| "1 repository failed their last scan" | fixed possessive in the scan-failure sentence | singular uses "its", plural "their" |
| Discovery crashed on unreadable directories | `pathlib` re-raises `EACCES` from `is_dir()` | guarded; unreadable directories are skipped and counted |
| `repo_factory(..., bare=True)` failed | helper pushed to a branch that did not exist yet (`git init -b` semantics) | helper uses `--initial-branch` and pushes `main` |
| A wheel built from the project contained `app/` only | `packages = ["app"]` listed no subpackages | `packages.find` with `include = ["app*"]`, verified with `pip wheel` |
| `python -m app scan 8 --log-level DEBUG` failed with "unrecognized arguments" | global flags were only accepted before the subcommand | `--config/--database/--log-level` are shared options now, like `--json` |
| `pytest -m requires_git` selected nothing | `requires_git` was a bare `skipif`, not a registered marker | registered marker plus a `pytest_collection_modifyitems` hook that skips when Git is missing |

## 8. Packaging and console script

```bash
pip wheel . --no-deps -w /tmp/wheelhouse      # wheel contains every subpackage
pip install -e ".[dev]"                       # editable install
git-dashboard --version                       # -> git-dashboard 1.0.0
git-dashboard --config /tmp/x/config.json doctor   # -> [ok] … exit 0
```

The wheels built before the packaging fix contained `app/` only (no `api/`,
`collectors/`, …); that was found and fixed here. A non-editable install is not a
supported deployment: `frontend/` and `data/` live next to the source, and such an
install answers `/` with an explanatory message while the JSON API keeps working.

## Known limitations of this verification

- The UI checks run in jsdom, not a real browser: layout, CSS painting,
  animations and native rendering are not covered, and no screenshot comparison
  exists. jsdom also has no layout engine, so the audit asserts structure,
  behaviour and (computed) colour contrast rather than geometry. Visual work was
  reviewed in the browser by hand.
- Verification ran on Linux only; Windows and macOS were not exercised (path
  normalization is unit-tested, but not the platforms themselves).
- Performance numbers come from this sandbox's filesystem; they are relative
  indicators, not benchmarks.
- The performance tests are regression guards with deliberately generous bounds;
  they will not catch small slowdowns.
- No CI workflow exists yet, so these checks are run manually.
