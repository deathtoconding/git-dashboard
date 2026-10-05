# Configuration reference

`config.json` lives next to the project (or wherever `--config` /
`GITDASH_CONFIG` points). `python -m app init-config` writes one containing the
current defaults.

Precedence, highest first:

1. CLI flags — `--host`, `--port`, `--database`, `--log-level`
2. Environment variables prefixed `GITDASH_`, e.g. `GITDASH_PORT=9000`,
   `GITDASH_DATABASE_PATH=/tmp/x.db`, `GITDASH_REPOSITORY_ROOTS="/a:/b"`
3. `config.json`
4. Built-in defaults

Unknown keys are **fatal**: the loader refuses to start rather than quietly
ignoring a typo, and the error names the offending file and key.

## Keys

| Key | Type | Default | Meaning |
| --- | --- | --- | --- |
| `host` | string | `"127.0.0.1"` | Bind address of the web server |
| `port` | int | `8000` | Port of the web server |
| `database_path` | string | `"data/dashboard.db"` | SQLite file; relative paths resolve against the project root |
| `git_binary` | string | `"git"` | Git executable to invoke |
| `git_timeout_seconds` | int | `30` | Timeout **per Git invocation** (the first scan of a huge repository may need more) |
| `history_depth` | int | `500` | Maximum commits collected per repository in one scan |
| `max_scan_depth` | int | `6` | Directory levels traversed during discovery |
| `file_changes_per_commit_limit` | int | `100` | Per-file rows stored per commit (larger commits keep the totals, drop the tail) |
| `repository_roots` | list of strings | `[]` | Directories scanned by discovery |
| `excluded_dirs` | list of strings | see `config.example.json` | Directory names skipped during discovery (`.git`, `node_modules`, `venv`, …) |
| `inactive_branch_days` | int | `30` | Branch age at which a branch stops counting as active |
| `stale_branch_days` | int | `90` | Branch age at which a branch is reported as stale |
| `repo_inactive_days` | int | `30` | Repository-level inactivity threshold |
| `repo_stale_days` | int | `90` | Repository-level staleness threshold (`stale`) |
| `repo_abandoned_days` | int | `180` | Repository-level abandonment threshold (`abandoned`) |
| `refresh_interval_minutes` | int | `0` | Background rescan interval in minutes (`0` disables it) |
| `log_level` | string | `"INFO"` | `DEBUG`, `INFO`, `WARNING` or `ERROR` |

Settings are validated on load and on `PUT /api/settings`; invalid values
(negative depths, bad port, unknown log level, non-list roots) return a readable
error instead of a traceback.

## Examples

Several roots, a deeper walk and a longer Git timeout:

```json
{
  "repository_roots": ["/home/me/work", "/home/me/oss", "/srv/mirrors"],
  "max_scan_depth": 8,
  "git_timeout_seconds": 120,
  "database_path": "data/dashboard.db"
}
```

Laptop-friendly scan of very large repositories:

```json
{
  "repository_roots": ["/home/me/projects"],
  "history_depth": 2000,
  "file_changes_per_commit_limit": 50
}
```

Keep a mirror of the dashboard busy while it runs:

```json
{
  "refresh_interval_minutes": 30,
  "repository_roots": ["/srv/mirrors"],
  "log_level": "WARNING"
}
```

## Where the values are used

- `history_depth` and `git_timeout_seconds` are applied per Git invocation in
  `app/collectors/`.
- `max_scan_depth` and `excluded_dirs` only affect discovery; already registered
  repositories are never dropped by changing them.
- `inactive_branch_days` / `stale_branch_days` drive branch states
  (`active` → `inactive` → `stale`) and the `stale_branches` counters.
- `repo_*_days` drive the repository staleness bucket (`active`, `inactive`,
  `stale`, `abandoned`) shown in lists, filters and insights.
- `refresh_interval_minutes` starts an in-process timer that triggers an
  incremental scan; it is off by default because scans are meant to be explicit.
