# Development guide

How to work on the dashboard: local setup, the layout of the code, the test
strategy, the conventions this project follows and how to extend it without
breaking its architecture.

## Setup

```bash
git clone https://github.com/deathtoconding/gitbhub-dashboard.git
cd gitbhub-dashboard
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"     # runtime + pytest, httpx, ruff; installs `git-dashboard`
```

`pip install -r requirements.txt && pip install -r requirements-dev.txt` is the
equivalent without installing the package itself. Without installation, run the
CLI as `python -m app …` from the project root.

One-command bootstrap (creates the venv, installs dependencies, writes
`config.json` when missing, generates the demo dataset when missing, discovers,
scans and serves):

```bash
scripts/dev_server.sh                                  # http://0.0.0.0:8000
scripts/dev_server.sh --host 127.0.0.1 --port 9000
scripts/dev_server.sh --root ~/projects --skip-demo    # point at real repositories
```

It is idempotent and only writes git-ignored runtime files, so running it again
never overwrites an edited `config.json` or re-generates existing demo data.

Running the app manually during development:

```bash
python -m app --config config.json start --reload --log-level DEBUG
python -m app --log-level DEBUG scan --all
python -m app doctor            # git, config, database, roots
```

Logs go to `data/logs/dashboard.log` (rotating) as well as stderr; the format
includes a `[repo=name]` field for repository-scoped work.

## Repository layout

```text
app/
├── api/             # FastAPI routers, dependencies, SPA fallback
├── analyzers/       # metrics, activity, branch health, health score, insights
├── collectors/      # Git CLI: runner, parsers, discovery, state, branches, commits, contributors
├── database/        # schema + migrations, connection handling, Store (all SQL lives here)
├── models/          # Pydantic request/response schemas
├── services/        # scan service, background scan manager, repository service, exports
├── config.py        # Settings, layered loading, validation
├── logging_config.py
├── main.py          # FastAPI factory and lifespan
└── __main__.py      # CLI (subcommands, exit codes)
frontend/            # buildless UI: index.html + assets/{styles,api,ui,charts,views,app}.js
scripts/             # create_demo_repos.py
tests/               # pytest suite (see below)
docs/                # architecture, configuration, verification, development
```

Dependency direction is one-way:

```text
api ─▶ services ─▶ collectors ─▶ (git CLI)
 └──▶ analyzers ─▶ database.Store ─▶ SQLite
```

`collectors` never import from `api` or `services`; `database` never imports from
`analyzers`. Keeping this direction is what keeps Git execution out of request
handlers.

## Test strategy

```bash
python -m pytest                  # fast suite (default; slow tests deselected)
python -m pytest -m slow -s       # performance, prints [perf] lines
python -m pytest -m requires_git  # only tests that need a real git binary
python -m pytest tests/test_api.py::test_scan_endpoints -vv
ruff check app tests scripts && ruff format --check app tests scripts
```

Principles:

- **Real Git, real files.** Tests build repositories in `tmp_path` through
  `tests/helpers.py` instead of mocking the Git CLI; a parsing or plumbing
  regression fails the suite. `helpers.GIT_AVAILABLE` guards environments without
  Git, and `requires_git` skips (rather than fails) those tests.
- **Drive the whole stack.** Integration tests go filesystem → discovery → scan →
  SQLite → analyzers → API, because that is the path the product actually takes.
- **Failures are features.** `test_failures.py` covers missing Git, vanished,
  corrupt and read-only repositories, timeouts and database errors: a broken
  repository must degrade, never abort.
- **Assert behaviour, not internals.** Prefer public functions and HTTP responses
  over private helpers. When a value is documented (health weights, staleness
  buckets, exit codes), assert the documented contract.
- **Performance tests guard, not benchmark.** They assert generous upper bounds
  and print a `[perf]` line for humans (see `docs/verification.md`).
- **Never call out to the network.** No test may require GitHub or any remote.

Fixtures live in `tests/conftest.py`: `settings` (temporary config and database),
`database`, `store`, `runner`, `collector`, `repositories`, `scanner`,
`repo_factory`, `client` (FastAPI `TestClient` over a temporary database).

## Conventions

- **Formatting and linting:** `ruff format` and `ruff check` (line length 120,
  target Python 3.10). Both must be clean before a commit; no other style rules
  are enforced.
- **Type hints everywhere.** `from __future__ import annotations` is used in
  every module; public functions have annotated parameters and returns.
- **Logging, not printing,** in library code: `get_logger("module")` and
  `get_repo_logger("module", repo)` for repository-scoped work. Never log a whole
  repository row.
- **No `subprocess` outside `app/collectors/`.** A test enforces this for the API
  layer; the rule applies to the rest of the code as well.
- **No invented data.** Every value shown must be computed from Git data or the
  database. If something cannot be known, show a warning or `null`, never a
  plausible number.
- **Errors:** configuration problems raise `ConfigError`; repository problems
  raise `RepositoryError`; database problems raise `DatabaseError`. CLI handlers
  translate them into human messages and stable exit codes.
- **Commits:** one logical change per commit, written in the imperative mood,
  with a body when the *why* is not obvious. Mechanical changes (formatting,
  renames) are separate commits.

### CLI exit codes

| Code | Meaning |
| --- | --- |
| 0 | Success |
| 1 | Refused action (for example `init-config` without `--force`) |
| 2 | Repository error (not registered, invalid path) |
| 4 | Configuration error (bad file, unknown key, invalid value) |
| 5 | Database error (unwritable path, failed migration) |

## How to extend

### Add a configuration key

1. Add the field (with default) to `Settings` in `app/config.py`.
2. Add it to `config.example.json` and document it in `docs/configuration.md`.
3. If it changes behaviour, cover it in `tests/test_config.py`.
4. Remember: unknown keys are fatal, so the field name is a public contract.

### Add a collector

1. Put the Git invocation in `app/collectors/` and parse it with a pure function
   in `parsers.py` (testable without Git).
2. Return plain dicts/dataclasses; do not write to the database from a collector.
3. Wire it through `GitCollector`, then store it in `ScanService`.
4. Test parsing with synthetic output in `tests/test_parsers.py` and the happy
   path with a real repository in `tests/test_collectors.py`.

### Add an analyzer

1. Accept `(store, repository_id, …)` and return plain serialisable structures.
2. Keep it deterministic and cheap enough for a dashboard request; add an index
   in `app/database/schema.py` (with a migration) if a query gets slow.
3. Expose it through a service or route and cover it in `tests/test_analyzers.py`.

### Add an API route

1. Add the handler to the relevant router in `app/api/routes/`, declare
   request/response models in `app/models/schemas.py`.
2. Read data from the store; never spawn a process.
3. Add the endpoint to the tables in `README.md` and cover it in
   `tests/test_api.py` (including a failure case).

### Add or change a briefing line

1. Add the rule to `app/analyzers/briefing.py` (`add(...)` with a severity, a
   code and an explicit order), reading only values passed into
   `build_briefing`. Never query inside it.
2. Every number in the sentence must come from the input: no rounding up, no
   "about", no placeholder text. If the input can be missing, drop the sentence.
3. Cover it in `tests/test_briefing.py` (the existing tests check number
   fidelity, severity order, the 5-line cap, possessives and the empty case) and,
   when the payload changes, in `tests/test_api.py`'s dashboard test.
4. Keep the cap and the ordering: the briefing is a summary, not a report. Depth
   belongs in the evidence layer.

### Change the database schema

1. Append a new migration to `MIGRATIONS` in `app/database/schema.py` and bump
   `SCHEMA_VERSION`; never edit a released migration.
2. Keep migrations idempotent and additive where possible.
3. Update the data-model table in `docs/architecture.md` and cover the upgrade in
   `tests/test_database.py`.

### Touch the frontend

- Plain HTML/CSS/JS only; no npm, no bundler, no build step. Assets are served
  from `/static` and the server falls back to `index.html` for non-API paths.
- Assets load in one fixed order and the router depends on it:
  `api.js` → `ui.js` → `charts.js` → `views.js` → `app.js`.
- Views are functions `(root, ctx, ...params)` returning rendered HTML, exposed on
  `window.Views`. `ctx` carries the per-view contract: `state`, `persistState`,
  `navigate`, `reload`, `toast`, `showModal`/`hideModal`, `pollScan`,
  `startScanAll` and `openPalette`.
- Shared helpers: `Fmt` (formatting, escaping, badges, meters, avatars) and `Api`
  in `api.js`; `Icons`, `UI.theme`, `UI.toast`, `UI.modal`, `UI.palette`,
  `UI.copy` in `ui.js`; SVG renderers in `charts.js`.
- Style with the classes in `styles.css` and its custom properties — never with
  inline hex colours, otherwise the dark theme breaks. Add new colours as
  `--*` tokens in both theme blocks.
- The overview reads briefing → evidence → triage. If you add a figure, decide
  which layer it belongs to: briefing (judgement, capped, tested prose), evidence
  (tables/charts of stored values) or triage (an action that filters or links).
  Do not repeat a briefing sentence in the evidence layer — the "All findings"
  panel exists precisely because the briefing is capped at five lines.
- Frontend state is persisted in `localStorage` under `git-dashboard-state-v1`
  (filters, ranges, tab) and `git-dashboard-theme` (explicit theme choice).
- After changes, walk the UI by hand or with the optional harnesses (Node +
  jsdom, nothing the app itself depends on):

  ```bash
  scripts/dev_server.sh --host 0.0.0.0 &
  npm install --prefix /tmp/ui-smoke jsdom
  NODE_PATH=/tmp/ui-smoke/node_modules node scripts/ui_smoke.js http://127.0.0.1:8000
  NODE_PATH=/tmp/ui-smoke/node_modules node scripts/ui_audit.js http://127.0.0.1:8000
  ```

  `ui_smoke.js` covers every view, every repository tab and the commit dialog and
  fails on console errors or failed requests. `ui_audit.js` additionally asserts
  the design system is wired up (charts, meters, heatmap, filters, tabs, modal
  focus, theme cycle, keyboard shortcuts, persisted state, accessible names) and
  ends by running a real incremental scan through the sidebar button.
- There is no real-browser automation here: jsdom checks structure and behaviour,
  not layout. Look at the page in a browser before calling a visual change done.

## Definition of done

Before a change is considered complete:

1. `ruff check app tests scripts` and `ruff format --check app tests scripts` pass.
2. `python -m pytest` passes; new behaviour has tests, including at least one
   failure-mode test where relevant.
3. `python -m pytest -m slow -s` still passes when scanners, storage or API
   aggregation changed.
4. Documentation is updated: `README.md` for user-visible behaviour,
   `docs/configuration.md` for new keys, `docs/architecture.md` for structural
   changes, and `docs/verification.md` when the verification record changes.
   Frontend changes also update `scripts/ui_smoke.js` / `scripts/ui_audit.js`
   when the markup they assert on changes.
5. The app was exercised manually at least once in the way the change affects it
   (CLI command, API call, or UI view).
6. The change is committed on its own, with a message explaining *why*.
