"""CLI tests: `python -m app <command>` behaviour, output and exit codes.

The handlers are called in-process (no subprocess) so the suite stays fast; the
only process spawned is `git`, by the collectors themselves.
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

import pytest

from app import __version__
from app.__main__ import main
from tests.conftest import requires_git


def run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    code = main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


# ------------------------------------------------------------------ init-config
def test_init_config_writes_the_defaults(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config = tmp_path / "config.json"
    code, out, _ = run(capsys, "--config", str(config), "init-config")
    assert code == 0
    assert "Configuration written" in out
    payload = json.loads(config.read_text())
    assert payload["repository_roots"] == []
    assert payload["port"] == 8000


def test_init_config_never_overwrites_an_edited_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config = tmp_path / "config.json"
    config.write_text('{"port": 9123}\n')
    code, _, err = run(capsys, "--config", str(config), "init-config")
    assert code == 1
    assert "already exists" in err
    assert json.loads(config.read_text()) == {"port": 9123}  # untouched


def test_init_config_force_resets_to_defaults(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config = tmp_path / "config.json"
    config.write_text('{"port": 9123, "history_depth": 5}\n')
    code, _, _ = run(capsys, "--config", str(config), "init-config", "--force")
    assert code == 0
    payload = json.loads(config.read_text())
    assert payload["port"] == 8000 and payload["history_depth"] == 500


def test_init_config_honours_cli_overrides(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config = tmp_path / "config.json"
    database = tmp_path / "custom.db"
    code, _, _ = run(capsys, "--config", str(config), "--database", str(database), "init-config")
    assert code == 0
    assert json.loads(config.read_text())["database_path"] == str(database)


# --------------------------------------------------------------------- plumbing
def test_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_version_is_declared_in_exactly_one_place() -> None:
    """`app.__version__` and `pyproject.toml` must not drift apart."""
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    match = re.search(r'^version = "([^"]+)"', pyproject.read_text(encoding="utf-8"), re.MULTILINE)
    assert match is not None
    assert match.group(1) == __version__


def test_unknown_configuration_key_is_a_configuration_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = tmp_path / "config.json"
    config.write_text('{"not_a_setting": true}\n')
    code, _, err = run(capsys, "--config", str(config), "status")
    assert code == 4
    assert "not_a_setting" in err


def test_read_only_commands_never_write_a_config_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config = tmp_path / "config.json"
    original = json.dumps({"database_path": str(tmp_path / "d.db")})
    config.write_text(original)

    code, out, _ = run(capsys, "--config", str(config), "--json", "repositories")
    assert code == 0
    assert json.loads(out)["items"] == []
    assert config.read_text() == original  # read-only commands never rewrite it


def test_missing_config_path_uses_defaults_but_says_so(tmp_path: Path, capsys: pytest.CaptureFixture[str], caplog) -> None:
    missing = tmp_path / "nope.json"
    with caplog.at_level("WARNING", logger="app.config"):
        code, _, _ = run(capsys, "--config", str(missing), "repositories")
    assert code == 0
    assert any("does not exist" in record.message for record in caplog.records)
    assert not missing.exists()


@requires_git
def test_doctor_reports_git_database_and_roots(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"database_path": str(tmp_path / "d.db"), "repository_roots": [str(tmp_path)]}))
    code, out, _ = run(capsys, "--config", str(config), "doctor")
    assert code == 0
    assert "[ok] Git" in out
    assert "[ok] Database" in out


@requires_git
def test_scan_and_status_round_trip(repo_factory, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = repo_factory("cli-repo", commits=2)
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"database_path": str(tmp_path / "d.db"), "repository_roots": [str(tmp_path / "repos")]}))

    code, out, _ = run(capsys, "--config", str(config), "add", str(repo))
    assert code == 0
    assert "registered" in out.lower()

    code, out, _ = run(capsys, "--config", str(config), "scan", "--all")
    assert code == 0
    assert "2 new commit" in out

    code, out, _ = run(capsys, "--config", str(config), "--json", "status")
    assert code == 0
    payload = json.loads(out)
    assert payload["summary"]["repositories"] == 1
    assert payload["recent_scans"]

    # A second scan adds nothing: incremental scanning is idempotent.
    code, out, _ = run(capsys, "--config", str(config), "scan", "--all")
    assert code == 0
    assert "0 new commit" in out

    database = sqlite3.connect(tmp_path / "d.db")
    assert database.execute("SELECT COUNT(*) FROM commits").fetchone()[0] == 2
    database.close()


@requires_git
def test_export_writes_a_json_snapshot(repo_factory, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = repo_factory("export-repo", commits=2)
    output = tmp_path / "out"
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"database_path": str(tmp_path / "d.db"), "repository_roots": [str(tmp_path / "repos")]}))
    run(capsys, "--config", str(config), "add", str(repo))
    run(capsys, "--config", str(config), "scan", "--all")

    code, out, _ = run(capsys, "--config", str(config), "export", "--format", "json", "--out", str(output))
    assert code == 0
    files = list(output.glob("dashboard-*.json"))
    assert len(files) == 1
    assert json.loads(files[0].read_text())["summary"]["repositories"] == 1


def test_insights_and_remove_handle_an_empty_database(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"database_path": str(tmp_path / "d.db")}))
    code, out, _ = run(capsys, "--config", str(config), "insights", "--json")
    assert code == 0
    assert json.loads(out)["items"] == []

    code, _, err = run(capsys, "--config", str(config), "remove", "42")
    assert code == 2  # usage-level failure: the repository does not exist
    assert "not registered" in err
