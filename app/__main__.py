"""Command line interface (E12-S1).

Target usage::

    python -m app start                    # serve the dashboard on http://127.0.0.1:8000
    python -m app scan --all               # scan every registered repository
    python -m app add ~/projects/api       # register a repository
    python -m app discover ~/projects --register
    python -m app doctor                   # environment / configuration checks
    python -m app export --format json     # snapshot the collected data

Everything runs locally and offline; no command ever contacts a remote service.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
import webbrowser
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from . import __version__
from .config import ConfigError, Settings, load_settings, save_settings
from .database.connection import Database, DatabaseError
from .database.store import Store
from .logging_config import configure_logging, get_logger
from .services.export_service import ExportService
from .services.repository_service import RepositoryError, RepositoryService
from .services.scan_service import ScanService

log = get_logger("__main__")


# --------------------------------------------------------------------- helpers
def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    # Shared flags so they work both before and after the subcommand
    # (``--json status`` and ``status --json``).
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Machine readable output where supported")

    parser = argparse.ArgumentParser(
        prog="git-dashboard",
        description="Local Git Repository Dashboard - discover, analyse and visualise local Git repositories.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"git-dashboard {__version__}")
    parser.add_argument("--config", help="Path to config.json (defaults to ./config.json)")
    parser.add_argument("--database", help="Override the SQLite database path")
    parser.add_argument("--log-level", help="Override the log level (DEBUG/INFO/WARNING/ERROR)")
    parser.add_argument("--json", action="store_true", default=False, help="Machine readable output where supported")

    subparsers = parser.add_subparsers(dest="command")

    start = subparsers.add_parser("start", parents=[common], help="Start the local dashboard (default command)")
    start.add_argument("--host", help="Bind address (default: config 'host', 127.0.0.1)")
    start.add_argument("--port", type=int, help="Port (default: config 'port', 8000)")
    start.add_argument("--reload", action="store_true", help="Auto-reload on code changes (development)")
    start.add_argument("--open", action="store_true", help="Open the dashboard in the default browser")
    start.add_argument("--scan-on-start", action="store_true", help="Run a scan before serving requests")

    subparsers.add_parser("init-config", parents=[common], help="Write a config.json with the current defaults")

    discover = subparsers.add_parser("discover", parents=[common], help="Find Git repositories under a root directory")
    discover.add_argument("root", nargs="?", help="Root directory (defaults to the configured repository_roots)")
    discover.add_argument("--register", action="store_true", help="Register every discovered repository")
    discover.add_argument("--max-depth", type=int, help="Limit recursion depth")

    add = subparsers.add_parser("add", parents=[common], help="Register a single local repository")
    add.add_argument("path", help="Path of the Git repository")
    add.add_argument("--name", help="Display name")

    remove = subparsers.add_parser("remove", parents=[common], help="Unregister a repository and delete its collected data")
    remove.add_argument("repository_id", type=int)

    scan = subparsers.add_parser("scan", parents=[common], help="Scan one or all repositories")
    scan.add_argument("repository_id", nargs="?", type=int, help="Repository id (omit with --all)")
    scan.add_argument("--all", action="store_true", help="Scan every registered repository")
    scan.add_argument("--full-history", action="store_true", help="Re-walk the full history instead of only new commits")
    scan.add_argument("--discover", action="store_true", help="Discover and register repositories before scanning")

    subparsers.add_parser("repositories", parents=[common], help="List registered repositories")
    subparsers.add_parser("status", parents=[common], help="Show dashboard and scan status")
    subparsers.add_parser("insights", parents=[common], help="Show actionable recommendations")
    subparsers.add_parser("doctor", parents=[common], help="Check Git, configuration and database state")

    export = subparsers.add_parser("export", parents=[common], help="Export data (JSON snapshot, CSV tables, SQLite backup)")
    export.add_argument("--format", choices=["json", "csv", "backup"], default="json")
    export.add_argument("--out", help="Output directory (default: data/exports)")
    export.add_argument("--repository-id", type=int, help="Limit the export to a single repository")

    return parser.parse_args(argv)


def build_settings(args: argparse.Namespace) -> Settings:
    overrides: dict[str, Any] = {}
    if getattr(args, "database", None):
        overrides["database_path"] = args.database
    if getattr(args, "log_level", None):
        overrides["log_level"] = args.log_level
    if getattr(args, "host", None):
        overrides["host"] = args.host
    if getattr(args, "port", None):
        overrides["port"] = args.port
    return load_settings(config_path=getattr(args, "config", None), overrides=overrides)


def bootstrap(settings: Settings) -> tuple[Store, ScanService, RepositoryService]:
    configure_logging(settings.log_level, log_file=settings.data_dir / "logs" / "dashboard.log")
    database = Database(settings.database_file)
    database.migrate()
    store = Store(database)
    return store, ScanService(store, settings), RepositoryService(store, settings)


def _print(payload: Any, *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, default=str))
        return
    if isinstance(payload, str):
        print(payload)
        return
    print(json.dumps(payload, indent=2, default=str))


# -------------------------------------------------------------------- commands
def cmd_start(args: argparse.Namespace, settings: Settings) -> int:
    import uvicorn

    from .main import create_app

    store, scan_service, _ = bootstrap(settings)
    if args.scan_on_start:
        available, _version = scan_service.git_available()
        if available and store.count_repositories():
            print("Running an initial scan before start…")
            report = scan_service.scan_all(incremental=True, discover=bool(settings.repository_roots))
            for outcome in report.outcomes:
                marker = "ok" if outcome.status != "failed" else "FAILED"
                print(f"  [{marker}] {outcome.name}: {outcome.commits_added} commit(s){'' if not outcome.error else ' - ' + outcome.error}")
        elif not available:
            print("Warning: Git was not found - repositories cannot be scanned until it is installed.", file=sys.stderr)

    app = create_app(settings)
    url = f"http://{settings.host if settings.host != '0.0.0.0' else '127.0.0.1'}:{settings.port}/"
    print(f"\n  Local Git Repository Dashboard {__version__}")
    print(f"  Dashboard : {url}")
    print(f"  API docs  : {url}docs")
    print(f"  Database  : {settings.database_file}")
    print(f"  Config    : {settings.config_path}")
    print("  Press Ctrl+C to stop.\n")
    if args.open:
        with contextlib.suppress(Exception):  # pragma: no cover - headless environments
            webbrowser.open(url)
    if args.reload:
        uvicorn.run("app.main:create_app", factory=True, host=settings.host, port=settings.port, reload=True, log_level=settings.log_level.lower())
    else:
        uvicorn.run(app, host=settings.host, port=settings.port, log_level=settings.log_level.lower())
    return 0


def cmd_discover(args: argparse.Namespace, settings: Settings) -> int:
    _, _, repository_service = bootstrap(settings)
    try:
        result = repository_service.discover(root=args.root, register=args.register, max_depth=args.max_depth)
    except RepositoryError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        _print(result, as_json=True)
        return 0
    total = 0
    for discovery in result["roots"]:
        print(f"\n{discovery['root']}  ({discovery['count']} repositories, {discovery['visited_dirs']} directories visited)")
        for repository in discovery["repositories"]:
            marker = "registered" if repository["already_registered"] else "new"
            print(f"  [{marker:>10}] {repository['path']}")
            total += 1
        for error in discovery["errors"]:
            print(f"  [skipped]    {error}")
    if result.get("registration"):
        print(f"\nRegistered {result['registered_count']} new repository(ies).")
    print(f"\n{total} repository(ies) found.")
    return 0


def cmd_add(args: argparse.Namespace, settings: Settings) -> int:
    _, _, repository_service = bootstrap(settings)
    try:
        repository = repository_service.add(args.path, name=args.name)
    except RepositoryError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    _print(
        {"registered": {"id": repository["id"], "name": repository["name"], "path": repository["path"]}}
        if args.json
        else f"Registered '{repository['name']}' (id {repository['id']}) - run 'python -m app scan {repository['id']}' to collect its data.",
        as_json=args.json,
    )
    return 0


def cmd_remove(args: argparse.Namespace, settings: Settings) -> int:
    _, _, repository_service = bootstrap(settings)
    try:
        repository = repository_service.remove(args.repository_id)
    except RepositoryError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"Removed '{repository['name']}' (id {repository['id']}) and all of its collected data.")
    return 0


def cmd_scan(args: argparse.Namespace, settings: Settings) -> int:
    store, scan_service, _ = bootstrap(settings)
    available, version = scan_service.git_available()
    if not available:
        print(f"error: Git executable {settings.git_binary!r} was not found. Install Git or set 'git_binary'.", file=sys.stderr)
        return 3
    print(f"Using git {version}")

    if args.all or (args.repository_id is None and not args.discover):
        if store.count_repositories() == 0:
            print("No repositories registered.")
            if settings.repository_roots:
                print("Tip: run 'python -m app discover --register' to register repositories under your configured roots.")
            else:
                print("Tip: register one with 'python -m app add <path>' or configure 'repository_roots' in config.json.")
            return 0
        report = scan_service.scan_all(incremental=not args.full_history, discover=args.discover)
        for outcome in report.outcomes:
            line = f"  [{outcome.status:>9}] {outcome.name}: {outcome.commits_added} new commit(s)"
            if outcome.error:
                line += f" - {outcome.error}"
            print(line)
            for warning in outcome.warnings:
                print(f"               warning: {warning}")
        print(f"\n{report.scanned} scanned, {report.failed} failed, {report.commits_added} commits added in {report.duration_ms}ms")
        return 0 if report.failed == 0 else 1

    if args.discover:
        report = scan_service.scan_all(incremental=not args.full_history, discover=True)
        print(f"Discovered {report.discovered} repositories, registered {report.registered}.")
        print(f"{report.scanned} scanned, {report.failed} failed, {report.commits_added} commits added")
        return 0 if report.failed == 0 else 1

    outcome = scan_service.scan_repository(args.repository_id, incremental=not args.full_history, full_history=args.full_history)
    print(f"  [{outcome.status}] {outcome.name}: {outcome.commits_added} new commit(s), {outcome.records_processed} records in {outcome.duration_ms}ms")
    for warning in outcome.warnings:
        print(f"          warning: {warning}")
    if outcome.error:
        print(f"          error: {outcome.error}", file=sys.stderr)
    return 0 if outcome.status != "failed" else 1


def cmd_repositories(args: argparse.Namespace, settings: Settings) -> int:
    store, _, _ = bootstrap(settings)
    rows = store.list_repositories(sort="last_commit", order="desc")
    if args.json:
        _print({"items": rows}, as_json=True)
        return 0
    if not rows:
        print("No repositories registered yet.")
        return 0
    print(f"{'ID':>4}  {'NAME':<28} {'BRANCH':<18} {'COMMITS':>8} {'CHANGES':>8} {'HEALTH':>6}  {'LAST COMMIT':<20} PATH")
    for row in rows:
        print(
            f"{row['id']:>4}  {row['name'][:28]:<28} {(row.get('current_branch') or '-')[:18]:<18} "
            f"{row.get('total_commits', 0):>8} {row.get('uncommitted_files', 0):>8} "
            f"{row.get('health_grade') or '-':>6}  {(row.get('last_commit_at') or 'never')[:19]:<20} {row['path']}"
        )
    print(f"\n{len(rows)} repository(ies).")
    return 0


def cmd_status(args: argparse.Namespace, settings: Settings) -> int:
    store, scan_service, _ = bootstrap(settings)
    available, version = scan_service.git_available()
    summary = store.repository_summary()
    payload = {
        "version": __version__,
        "git": {"available": available, "version": version, "binary": settings.git_binary},
        "database": {
            "path": str(settings.database_file),
            "size_bytes": store.db.size_bytes(),
            "schema_version": store.db.current_version(),
        },
        "summary": summary,
        "latest_scan": store.latest_scan_run(),
        "recent_scans": store.list_scan_runs(limit=5),
    }
    if args.json:
        _print(payload, as_json=True)
        return 0
    print(f"git-dashboard {__version__}")
    print(f"Git          : {'available (' + str(version) + ')' if available else 'NOT AVAILABLE'}")
    print(f"Database     : {settings.database_file} ({store.db.size_bytes()} bytes, schema v{store.db.current_version()})")
    print(f"Repositories : {summary.get('repositories', 0)} | commits {summary.get('total_commits', 0)} | branches {summary.get('branches', 0)} | contributors {summary.get('contributors', 0)}")
    print(f"Changes      : {summary.get('uncommitted_files', 0)} uncommitted file(s) across {summary.get('dirty_repositories', 0)} repository(ies)")
    print(f"Stale        : {summary.get('stale_repositories', 0)} repository(ies), {store.count_stale_branches()} stale branch(es)")
    latest = store.latest_scan_run()
    if latest:
        print(f"Last scan    : {latest['started_at']} [{latest['status']}] {latest.get('commits_added') or 0} commit(s){' - ' + (latest.get('error') or '') if latest.get('error') else ''}")
    else:
        print("Last scan    : never - run 'python -m app scan --all'")
    return 0


def cmd_insights(args: argparse.Namespace, settings: Settings) -> int:
    from .analyzers.health import dashboard_insights

    store, _, _ = bootstrap(settings)
    items = dashboard_insights(store, settings=settings, limit=50)
    if args.json:
        _print({"items": items}, as_json=True)
        return 0
    if not items:
        print("No issues detected. Nothing to recommend.")
        return 0
    for item in items:
        print(f"[{item['severity']:>7}] {item['repository_name']}: {item['message']}")
        if item.get("action"):
            print(f"          → {item['action']}")
    return 0


def cmd_export(args: argparse.Namespace, settings: Settings) -> int:
    store, _, _ = bootstrap(settings)
    export_service = ExportService(store, settings)
    if args.format == "backup":
        target = export_service.backup_database()
        print(f"Database backed up to {target}")
        return 0
    if args.format == "csv":
        directory = Path(args.out) if args.out else settings.data_dir / "exports"
        directory.mkdir(parents=True, exist_ok=True)
        written = []
        for table, payload in export_service.csv_bundle(repository_id=args.repository_id).items():
            target = directory / f"{table}.csv"
            target.write_text(payload, encoding="utf-8")
            written.append(str(target))
        print("\n".join(written))
        return 0
    target = export_service.write_snapshot(directory=args.out, repository_id=args.repository_id)
    print(f"JSON snapshot written to {target}")
    return 0


def cmd_init_config(args: argparse.Namespace, settings: Settings) -> int:
    path = save_settings(settings, path=args.config or None)
    print(f"Configuration written to {path}")
    print("Edit 'repository_roots' to point at the folders that contain your Git repositories.")
    return 0


def cmd_doctor(args: argparse.Namespace, settings: Settings) -> int:
    store, scan_service, repository_service = bootstrap(settings)
    problems: list[str] = []
    print(f"git-dashboard {__version__}\n")

    available, version = scan_service.git_available()
    print(f"[{'ok' if available else '!!'}] Git          : {settings.git_binary} {'v' + str(version) if version else 'NOT FOUND'}")
    if not available:
        problems.append("Git is not available - discovery and scanning will fail.")

    try:
        settings.database_file.parent.mkdir(parents=True, exist_ok=True)
        print(f"[ok] Database     : {settings.database_file} (schema v{store.db.current_version()}, {store.db.size_bytes()} bytes)")
    except OSError as exc:
        problems.append(f"Database path is not writable: {exc}")
        print(f"[!!] Database     : {settings.database_file} - {exc}")

    if settings.config_path:
        exists = settings.config_path.exists()
        print(f"[{'ok' if exists else '--'}] Config file   : {settings.config_path}{'' if exists else ' (not created yet, defaults are in use)'}")

    if not settings.repository_roots:
        problems.append("No repository_roots configured - automatic discovery is disabled (manual 'add' still works).")
        print("[--] Roots        : none configured")
    for root in settings.repository_roots:
        resolved = settings.resolve_path(root)
        ok = resolved.is_dir()
        print(f"[{'ok' if ok else '!!'}] Root          : {resolved}{'' if ok else ' (missing)'}")
        if not ok:
            problems.append(f"Configured root does not exist: {resolved}")

    suggestions = repository_service.suggestions(limit=10) if settings.repository_roots else []
    registered = store.count_repositories()
    print(f"[ok] Repositories : {registered} registered, {len(suggestions) if suggestions else 0} unregistered under the configured roots")

    if problems:
        print("\nIssues found:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("\nEverything looks good. Start the dashboard with: python -m app start")
    return 0


COMMANDS = {
    "start": cmd_start,
    "init-config": cmd_init_config,
    "discover": cmd_discover,
    "add": cmd_add,
    "remove": cmd_remove,
    "scan": cmd_scan,
    "repositories": cmd_repositories,
    "status": cmd_status,
    "insights": cmd_insights,
    "export": cmd_export,
    "doctor": cmd_doctor,
}


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    command = args.command or "start"
    try:
        settings = build_settings(args)
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 4

    handler = COMMANDS[command]
    try:
        return handler(args, settings)
    except DatabaseError as exc:
        print(f"database error: {exc}", file=sys.stderr)
        return 5
    except KeyboardInterrupt:  # pragma: no cover - interactive
        print("\nStopped.")
        return 0


if __name__ == "__main__":  # pragma: no cover - module entry point
    sys.exit(main())


__all__ = ["build_settings", "main", "parse_args"]
