"""Application configuration for the Local Git Repository Dashboard.

Configuration is externalised and validated.  Precedence (highest first):

1. Explicit overrides passed to :func:`load_settings` (CLI flags / tests)
2. Environment variables prefixed with ``GITDASH_`` (e.g. ``GITDASH_PORT=9000``)
3. A JSON configuration file (``config.json`` next to the project root by default,
   or the path in ``GITDASH_CONFIG``)
4. The built-in defaults below

No credentials, tokens or secrets are ever required.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, fields, replace
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.json"
ENV_PREFIX = "GITDASH_"

DEFAULT_EXCLUDED_DIRS = (
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    ".tox",
    ".nox",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    "site-packages",
    "dist",
    "build",
    "target",
    "out",
    ".next",
    ".nuxt",
    ".cache",
    ".idea",
    ".vscode",
    "Library",
    "AppData",
    "$RECYCLE.BIN",
    "System Volume Information",
)

LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


class ConfigError(ValueError):
    """Raised when configuration is invalid. The message always names the field."""


def _as_int(name: str, value: Any, *, minimum: int = 0, maximum: int | None = None) -> int:
    if isinstance(value, bool):
        raise ConfigError(f"{name}: expected an integer, got a boolean ({value!r})")
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ConfigError(f"{name}: expected an integer, got {value!r}") from None
    if number < minimum:
        raise ConfigError(f"{name}: must be >= {minimum}, got {number}")
    if maximum is not None and number > maximum:
        raise ConfigError(f"{name}: must be <= {maximum}, got {number}")
    return number


def _as_bool(name: str, value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    raise ConfigError(f"{name}: expected a boolean, got {value!r}")


_STRING_LISTS = {"repository_roots", "excluded_dirs"}


@dataclass(slots=True)
class Settings:
    """Validated application settings."""

    # --- storage ---
    database_path: str = "data/dashboard.db"

    # --- discovery ---
    repository_roots: list[str] = field(default_factory=list)
    excluded_dirs: list[str] = field(default_factory=lambda: list(DEFAULT_EXCLUDED_DIRS))
    max_scan_depth: int = 6

    # --- collection ---
    history_depth: int = 500
    file_changes_per_commit_limit: int = 100
    git_binary: str = "git"
    git_timeout_seconds: int = 30

    # --- analysis thresholds (days) ---
    stale_branch_days: int = 90
    inactive_branch_days: int = 30
    repo_inactive_days: int = 30
    repo_stale_days: int = 90
    repo_abandoned_days: int = 180

    # --- runtime ---
    refresh_interval_minutes: int = 0  # 0 disables the optional background refresh
    log_level: str = "INFO"
    host: str = "127.0.0.1"
    port: int = 8000

    # --- derived / not user configurable through the config file ---
    project_root: Path = field(default=PROJECT_ROOT, compare=False)
    config_path: Path | None = field(default=None, compare=False)

    # ------------------------------------------------------------------ helpers
    @property
    def database_file(self) -> Path:
        """Absolute path of the SQLite database."""
        return self.resolve_path(self.database_path)

    @property
    def data_dir(self) -> Path:
        return self.database_file.parent

    def resolve_path(self, value: str | os.PathLike[str]) -> Path:
        """Resolve ``value`` relative to the project root (user paths survive ~)."""
        path = Path(os.path.expanduser(str(value)))
        if not path.is_absolute():
            path = self.project_root / path
        return path.resolve()

    def to_dict(self, *, include_paths: bool = True) -> dict[str, Any]:
        data = {
            "database_path": self.database_path,
            "repository_roots": list(self.repository_roots),
            "excluded_dirs": list(self.excluded_dirs),
            "max_scan_depth": self.max_scan_depth,
            "history_depth": self.history_depth,
            "file_changes_per_commit_limit": self.file_changes_per_commit_limit,
            "git_binary": self.git_binary,
            "git_timeout_seconds": self.git_timeout_seconds,
            "stale_branch_days": self.stale_branch_days,
            "inactive_branch_days": self.inactive_branch_days,
            "repo_inactive_days": self.repo_inactive_days,
            "repo_stale_days": self.repo_stale_days,
            "repo_abandoned_days": self.repo_abandoned_days,
            "refresh_interval_minutes": self.refresh_interval_minutes,
            "log_level": self.log_level,
            "host": self.host,
            "port": self.port,
        }
        if include_paths:
            data["config_path"] = str(self.config_path) if self.config_path else None
            data["data_dir"] = str(self.data_dir)
        return data

    def apply(self, changes: Mapping[str, Any]) -> Settings:
        """Return a copy of these settings with ``changes`` validated and applied."""
        return validate_settings(self, changes)

    def with_overrides(self, overrides: Mapping[str, Any] | None) -> Settings:
        """Validate and apply a partial update, raising :class:`ConfigError` on bad input."""
        if not overrides:
            return replace(self)
        clean = {key: value for key, value in overrides.items() if value is not None}
        return validate_settings(self, clean)


def _coerce(name: str, value: Any) -> Any:
    if name in _STRING_LISTS:
        if isinstance(value, str):
            parts: Iterable[str] = value.replace(";", os.pathsep).split(os.pathsep)
            return [part.strip() for part in parts if part.strip()]
        if isinstance(value, (list, tuple, set)):
            return [str(item) for item in value]
        raise ConfigError(f"{name}: expected a list of paths or a string, got {value!r}")
    if name in {"port", "max_scan_depth"}:
        return _as_int(name, value, minimum=1, maximum=65535 if name == "port" else 64)
    if name in {
        "history_depth",
        "file_changes_per_commit_limit",
        "git_timeout_seconds",
        "stale_branch_days",
        "inactive_branch_days",
        "repo_inactive_days",
        "repo_stale_days",
        "repo_abandoned_days",
        "refresh_interval_minutes",
    }:
        minimum = 1 if name in {"git_timeout_seconds", "history_depth", "file_changes_per_commit_limit"} else 0
        return _as_int(name, value, minimum=minimum)
    if name in {"database_path", "git_binary", "host"}:
        text = str(value).strip()
        if not text:
            raise ConfigError(f"{name}: must not be empty")
        return text
    if name == "log_level":
        level = str(value).strip().upper()
        if level not in LOG_LEVELS:
            raise ConfigError(f"log_level: must be one of {', '.join(LOG_LEVELS)} (got {value!r})")
        return level
    return value


def _read_config_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{path}: invalid JSON ({exc.msg} at line {exc.lineno} column {exc.colno})") from exc
    except OSError as exc:
        raise ConfigError(f"{path}: cannot read configuration file ({exc})") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: top level configuration must be a JSON object")
    return raw


def _read_env(environ: Mapping[str, str]) -> dict[str, Any]:
    known = {f.name for f in fields(Settings)}
    values: dict[str, Any] = {}
    for key, value in environ.items():
        if not key.startswith(ENV_PREFIX):
            continue
        name = key[len(ENV_PREFIX) :].strip().lower()
        if name in known:
            values[name] = value
    return values


def validate_settings(base: Settings, changes: Mapping[str, Any]) -> Settings:
    """Validate ``changes`` against ``base`` and return a new :class:`Settings`."""
    coerced: dict[str, Any] = {}
    for name, value in changes.items():
        if value is None:
            continue
        if not hasattr(base, name):
            raise ConfigError(f"{name}: unknown configuration key")
        coerced[name] = _coerce(name, value)

    updated = replace(base, **coerced)
    _validate_consistency(updated)
    return updated


def _validate_consistency(settings: Settings) -> None:
    if settings.repo_inactive_days >= settings.repo_stale_days:
        raise ConfigError("repo_stale_days: must be greater than repo_inactive_days")
    if settings.repo_stale_days >= settings.repo_abandoned_days:
        raise ConfigError("repo_abandoned_days: must be greater than repo_stale_days")
    if settings.inactive_branch_days >= settings.stale_branch_days:
        raise ConfigError("stale_branch_days: must be greater than inactive_branch_days")
    if not settings.excluded_dirs:
        raise ConfigError("excluded_dirs: at least one entry is required ('.git' must stay excluded)")
    for root in settings.repository_roots:
        if not str(root).strip():
            raise ConfigError("repository_roots: entries must not be empty")
    try:
        settings.database_file.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ConfigError(f"database_path: cannot create directory {settings.database_file.parent} ({exc})") from exc


def load_settings(
    *,
    config_path: str | os.PathLike[str] | None = None,
    overrides: Mapping[str, Any] | None = None,
    environ: Mapping[str, str] | None = None,
    project_root: Path | None = None,
) -> Settings:
    """Load, merge and validate configuration from every source."""
    env = dict(os.environ if environ is None else environ)
    root = Path(project_root) if project_root else PROJECT_ROOT

    raw_path = config_path or env.get(f"{ENV_PREFIX}CONFIG") or DEFAULT_CONFIG_PATH
    path = Path(os.path.expanduser(str(raw_path)))
    if not path.is_absolute():
        path = root / path

    merged: dict[str, Any] = {}
    merged.update(_read_config_file(path))
    merged.update(_read_env(env))
    if overrides:
        merged.update({k: v for k, v in overrides.items() if v is not None})

    settings = Settings(project_root=root.resolve(), config_path=path)
    try:
        settings = validate_settings(settings, merged)
    except ConfigError as exc:
        source = f" (from {path})" if path.exists() else ""
        raise ConfigError(f"{exc}{source}") from None
    return replace(settings, config_path=path)


def save_settings(settings: Settings, *, path: str | os.PathLike[str] | None = None) -> Path:
    """Persist the user-editable portion of the settings as JSON."""
    target = Path(path) if path else (settings.config_path or DEFAULT_CONFIG_PATH)
    payload = settings.to_dict(include_paths=False)
    target.parent.mkdir(parents=True, exist_ok=True)
    # Atomic write so a crash cannot leave a half-written configuration behind.
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary.replace(target)
    return target
