"""Configuration system tests (E1-S2)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.config import (
    DEFAULT_EXCLUDED_DIRS,
    ConfigError,
    Settings,
    load_settings,
    save_settings,
)


def test_defaults_are_usable(tmp_path: Path) -> None:
    settings = load_settings(config_path=tmp_path / "missing.json", environ={})
    assert settings.git_binary == "git"
    assert settings.port == 8000
    assert ".git" in settings.excluded_dirs
    assert settings.history_depth > 0
    assert settings.repo_inactive_days < settings.repo_stale_days < settings.repo_abandoned_days


def test_config_file_is_read(tmp_path: Path) -> None:
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"database_path": "custom/path.db", "port": 9123, "repository_roots": ["/tmp/projects"]}))
    settings = load_settings(config_path=config, environ={})
    assert settings.port == 9123
    assert settings.repository_roots == ["/tmp/projects"]
    assert settings.database_file.name == "path.db"


def test_environment_overrides_file(tmp_path: Path) -> None:
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"port": 8000, "log_level": "INFO"}))
    settings = load_settings(config_path=config, environ={"GITDASH_PORT": "9999", "GITDASH_LOG_LEVEL": "debug"})
    assert settings.port == 9999
    assert settings.log_level == "DEBUG"


def test_explicit_overrides_win(tmp_path: Path) -> None:
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"port": 8000}))
    settings = load_settings(config_path=config, environ={"GITDASH_PORT": "9999"}, overrides={"port": 7777})
    assert settings.port == 7777


@pytest.mark.parametrize(
    "payload, expected",
    [
        ({"port": "not-a-number"}, "port"),
        ({"port": 0}, "port"),
        ({"log_level": "SHOUTING"}, "log_level"),
        ({"history_depth": -5}, "history_depth"),
        ({"database_path": "   "}, "database_path"),
        ({"repository_roots": 42}, "repository_roots"),
        ({"max_scan_depth": 1000}, "max_scan_depth"),
        ({"unknown_key": 1}, "unknown_key"),
        ({"stale_branch_days": 10, "inactive_branch_days": 30}, "stale_branch_days"),
        ({"repo_stale_days": 10, "repo_inactive_days": 30}, "repo_stale_days"),
        ({"excluded_dirs": []}, "excluded_dirs"),
    ],
)
def test_invalid_configuration_raises_clear_error(tmp_path: Path, payload: dict, expected: str) -> None:
    config = tmp_path / "config.json"
    config.write_text(json.dumps(payload))
    with pytest.raises(ConfigError) as excinfo:
        load_settings(config_path=config, environ={})
    assert expected in str(excinfo.value)
    assert str(config) in str(excinfo.value)  # the error names the offending file


def test_invalid_json_reports_location(tmp_path: Path) -> None:
    config = tmp_path / "config.json"
    config.write_text("{ not json }")
    with pytest.raises(ConfigError) as excinfo:
        load_settings(config_path=config, environ={})
    assert "invalid JSON" in str(excinfo.value)


def test_non_object_config_is_rejected(tmp_path: Path) -> None:
    config = tmp_path / "config.json"
    config.write_text("[1, 2, 3]")
    with pytest.raises(ConfigError, match="JSON object"):
        load_settings(config_path=config, environ={})


def test_paths_are_resolved_against_project_root(tmp_path: Path) -> None:
    settings = load_settings(config_path=tmp_path / "config.json", environ={}, project_root=tmp_path)
    assert settings.database_file == (tmp_path / "data" / "dashboard.db").resolve()
    assert settings.data_dir == (tmp_path / "data").resolve()


def test_tilde_paths_expand(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    settings = load_settings(config_path=tmp_path / "config.json", environ={}, overrides={"repository_roots": ["~/projects"]})
    assert settings.resolve_path("~/projects") == (tmp_path / "projects").resolve()


def test_save_and_reload_round_trip(tmp_path: Path) -> None:
    settings = load_settings(config_path=tmp_path / "config.json", environ={})
    updated = settings.with_overrides({"repository_roots": ["/srv/git"], "stale_branch_days": 120, "log_level": "DEBUG"})
    target = save_settings(updated)
    assert target == tmp_path / "config.json"
    reloaded = load_settings(config_path=target, environ={})
    assert reloaded.repository_roots == ["/srv/git"]
    assert reloaded.stale_branch_days == 120
    assert reloaded.log_level == "DEBUG"


def test_with_overrides_rejects_unknown_keys(tmp_path: Path) -> None:
    settings = load_settings(config_path=tmp_path / "config.json", environ={})
    with pytest.raises(ConfigError):
        settings.with_overrides({"nope": 1})


def test_to_dict_is_json_serialisable(tmp_path: Path) -> None:
    settings = load_settings(config_path=tmp_path / "config.json", environ={})
    payload = settings.to_dict()
    json.dumps(payload)
    assert payload["data_dir"] == str(settings.data_dir)
    assert set(payload["excluded_dirs"]) == set(settings.excluded_dirs) == set(DEFAULT_EXCLUDED_DIRS)


def test_settings_dataclass_defaults_are_valid() -> None:
    # Settings() is constructed without validation in a few places (analyzers),
    # so the class defaults themselves must satisfy the consistency rules.
    settings = Settings()
    assert settings.repo_inactive_days < settings.repo_stale_days < settings.repo_abandoned_days
    assert settings.inactive_branch_days < settings.stale_branch_days
