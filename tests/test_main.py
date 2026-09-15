"""CLI tests for main.py (no network, temporary artefacts)."""

from __future__ import annotations

import pytest

import main as main_module
from config import load_settings
from main import main


@pytest.fixture
def env_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("OUTPUT_CSV_DIR", str(tmp_path / "csv"))
    monkeypatch.setenv("OUTPUT_EXCEL_DIR", str(tmp_path / "excel"))
    monkeypatch.setenv("DB_PATH", str(tmp_path / "cli.db"))
    monkeypatch.setenv("REQUEST_DELAY_SECONDS", "0")
    return load_settings()


def test_init_db_command(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("DB_PATH", str(tmp_path / "cli.db"))
    monkeypatch.delenv("TARGET_BASE_URL", raising=False)
    exit_code = main(["init-db"])
    assert exit_code == 0
    assert (tmp_path / "cli.db").exists()


def test_run_command_success(tmp_path, monkeypatch):
    monkeypatch.setenv("LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("DB_PATH", str(tmp_path / "x.db"))
    monkeypatch.delenv("TARGET_BASE_URL", raising=False)

    from pipeline import PipelineOutcome

    outcome = PipelineOutcome(status="success", records_stored=5)
    monkeypatch.setattr(main_module, "run_pipeline", lambda settings: outcome)
    assert main(["run"]) == 0


def test_run_command_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.delenv("TARGET_BASE_URL", raising=False)

    from pipeline import PipelineOutcome

    outcome = PipelineOutcome(status="failed", error="scrape failed")
    monkeypatch.setattr(main_module, "run_pipeline", lambda settings: outcome)
    assert main(["run"]) == 1


def test_config_error_exit_code(tmp_path, monkeypatch):
    monkeypatch.setenv("TARGET_BASE_URL", "   ")
    monkeypatch.setenv("LOG_DIR", str(tmp_path / "logs"))
    assert main(["run"]) == 2


def test_default_command_is_run(tmp_path, monkeypatch):
    monkeypatch.setenv("LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.delenv("TARGET_BASE_URL", raising=False)
    from pipeline import PipelineOutcome

    captured = {}
    monkeypatch.setattr(
        main_module, "run_pipeline", lambda settings: captured.setdefault("outcome", PipelineOutcome(status="success"))
    )
    assert main([]) == 0
    assert "outcome" in captured


def test_schedule_overrides(tmp_path, monkeypatch):
    monkeypatch.setenv("LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.delenv("TARGET_BASE_URL", raising=False)
    captured = {}

    def fake_run_scheduler(settings):
        captured["interval"] = settings.scheduler.interval_minutes
        captured["max_runs"] = settings.scheduler.max_runs

    monkeypatch.setattr(main_module, "run_scheduler", fake_run_scheduler)
    assert main(["schedule", "--interval", "5", "--max-runs", "2"]) == 0
    assert captured["interval"] == 5
    assert captured["max_runs"] == 2
