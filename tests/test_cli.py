"""End-to-end tests for the `wb` command line, via Click's CliRunner.

Everything below this used to be untested: the model, store, render maths,
agent parsing and TUI all had direct coverage, but the actual commands a
person types — `wb add`, `wb sync`, `wb config` — were never invoked in a
test at all. That gap is exactly the kind that lets a broken flag or a bad
wire-up ship unnoticed (see the TUI's `.--highlight` typo and its stale
`week.status` reference, both invisible until someone actually ran the app).

Everything here runs with `--no-render`, so no Chromium/Playwright is
needed, and every command is pointed at an isolated tmp_path via the
`cli_env` fixture rather than the real ~/.../data directory.
"""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from weekboard import cli as cli_mod
from weekboard import config as config_mod
from weekboard.config import Config
from weekboard.store import Store


@pytest.fixture()
def cli_env(tmp_path, monkeypatch):
    """Isolate every `wb` command from the real config/data directories."""
    config = Config(data_dir=str(tmp_path / "data"), output_dir=str(tmp_path / "out"))
    config_path = tmp_path / "config.json"

    # Every command builds its own bare Store(), which calls this.
    monkeypatch.setattr("weekboard.store.load_config", lambda: config)
    # `wb config` / `wb doctor` use their own imported copies of these names.
    monkeypatch.setattr(cli_mod, "load_config", lambda: config)
    monkeypatch.setattr(cli_mod, "CONFIG_PATH", config_path)
    monkeypatch.setattr(config_mod, "CONFIG_PATH", config_path)

    return config


@pytest.fixture()
def runner():
    return CliRunner()


class TestTaskCommands:
    def test_add_then_ls(self, cli_env, runner):
        result = runner.invoke(cli_mod.cli, ["--no-render", "add", "Call Harry"])
        assert result.exit_code == 0, result.output
        result = runner.invoke(cli_mod.cli, ["--no-render", "ls"])
        assert "Call Harry" in result.output

    def test_add_requires_text(self, cli_env, runner):
        result = runner.invoke(cli_mod.cli, ["--no-render", "add"])
        assert result.exit_code != 0

    def test_done_and_uncheck(self, cli_env, runner):
        runner.invoke(cli_mod.cli, ["--no-render", "add", "Ship it"])
        result = runner.invoke(cli_mod.cli, ["--no-render", "done", "1"])
        assert result.exit_code == 0
        store = Store(cli_env)
        assert store.load(_current_key(store)).tasks[0].done
        result = runner.invoke(cli_mod.cli, ["--no-render", "uncheck", "1"])
        assert result.exit_code == 0
        assert not store.load(_current_key(store)).tasks[0].done

    def test_done_bad_number_errors_cleanly(self, cli_env, runner):
        runner.invoke(cli_mod.cli, ["--no-render", "add", "Only task"])
        result = runner.invoke(cli_mod.cli, ["--no-render", "done", "99"])
        assert result.exit_code != 0
        assert "No task 99" in result.output

    def test_rm(self, cli_env, runner):
        runner.invoke(cli_mod.cli, ["--no-render", "add", "Delete me"])
        result = runner.invoke(cli_mod.cli, ["--no-render", "rm", "1"])
        assert result.exit_code == 0
        result = runner.invoke(cli_mod.cli, ["--no-render", "ls"])
        assert "Delete me" not in result.output

    def test_mv_between_weeks(self, cli_env, runner):
        runner.invoke(cli_mod.cli, ["--no-render", "add", "Push to next week"])
        result = runner.invoke(cli_mod.cli, ["--no-render", "mv", "1", "--to", "next"])
        assert result.exit_code == 0
        result = runner.invoke(cli_mod.cli, ["--no-render", "ls", "-w", "next"])
        assert "Push to next week" in result.output

    def test_undo_restores_after_rm(self, cli_env, runner):
        runner.invoke(cli_mod.cli, ["--no-render", "add", "Don't lose me"])
        runner.invoke(cli_mod.cli, ["--no-render", "rm", "1"])
        result = runner.invoke(cli_mod.cli, ["--no-render", "undo"])
        assert result.exit_code == 0
        result = runner.invoke(cli_mod.cli, ["--no-render", "ls"])
        assert "Don't lose me" in result.output

    def test_undo_with_nothing_to_undo(self, cli_env, runner):
        result = runner.invoke(cli_mod.cli, ["--no-render", "undo"])
        assert result.exit_code != 0

    def test_priority_and_tags(self, cli_env, runner):
        result = runner.invoke(
            cli_mod.cli,
            ["--no-render", "add", "Important thing", "-p", "high", "-t", "urgent"],
        )
        assert result.exit_code == 0
        store = Store(cli_env)
        week = store.load(_current_key(store))
        assert week.tasks[0].priority == "high"
        assert "urgent" in week.tasks[0].tags


class TestStatusGauges:
    def test_status_shows_all_four(self, cli_env, runner):
        result = runner.invoke(cli_mod.cli, ["--no-render", "status"])
        assert result.exit_code == 0
        for label in ("FOCUS", "MOMENTUM", "SHIPPED", "DONE"):
            assert label in result.output

    def test_pin_and_unpin(self, cli_env, runner):
        result = runner.invoke(cli_mod.cli, ["--no-render", "status", "focus", "77"])
        assert result.exit_code == 0
        result = runner.invoke(cli_mod.cli, ["--no-render", "status"])
        assert "77" in result.output
        result = runner.invoke(cli_mod.cli, ["--no-render", "status", "focus", "auto"])
        assert result.exit_code == 0

    def test_bad_gauge_value_errors(self, cli_env, runner):
        result = runner.invoke(cli_mod.cli, ["--no-render", "status", "focus", "not-a-number"])
        assert result.exit_code != 0


class TestMission:
    def test_set_mission_lines(self, cli_env, runner):
        result = runner.invoke(
            cli_mod.cli,
            ["--no-render", "mission", "Ship things.", "Help people.", "--tagline", "Go."],
        )
        assert result.exit_code == 0
        store = Store(cli_env)
        week = store.load(_current_key(store))
        assert week.mission == ["Ship things.", "Help people."]
        assert week.tagline == "Go."


class TestConfigAndDoctor:
    def test_config_creates_file_on_first_run(self, cli_env, runner, tmp_path):
        config_path = tmp_path / "config.json"
        assert not config_path.exists()
        result = runner.invoke(cli_mod.cli, ["--no-render", "config"])
        assert result.exit_code == 0
        assert config_path.exists()
        data = json.loads(config_path.read_text())
        assert data["accent"] == cli_env.accent

    def test_doctor_runs_and_reports_something(self, cli_env, runner):
        result = runner.invoke(cli_mod.cli, ["--no-render", "doctor"])
        # doctor exits non-zero when playwright/output dir aren't set up in the
        # test sandbox — that's expected here. It must not crash outright.
        assert "data dir" in result.output

    def test_path_prints_data_root(self, cli_env, runner):
        result = runner.invoke(cli_mod.cli, ["--no-render", "path"])
        assert result.exit_code == 0
        assert str(cli_env.weeks_path) in result.output


class TestAi:
    def test_ai_applies_ops_on_confirm(self, cli_env, runner, monkeypatch):
        """`wb ai` end to end, with the model call itself mocked out."""

        def fake_capture(store, config, text):
            return {"ops": [{"op": "add", "text": "from the agent", "week": _current_key(Store(config))}], "say": "done"}

        monkeypatch.setattr(cli_mod.agent_mod, "capture", fake_capture)
        result = runner.invoke(cli_mod.cli, ["--no-render", "ai", "-y", "add something"])
        assert result.exit_code == 0, result.output
        result = runner.invoke(cli_mod.cli, ["--no-render", "ls"])
        assert "from the agent" in result.output

    def test_ai_reports_no_changes(self, cli_env, runner, monkeypatch):
        monkeypatch.setattr(
            cli_mod.agent_mod, "capture", lambda store, config, text: {"ops": [], "say": "nothing to do"}
        )
        result = runner.invoke(cli_mod.cli, ["--no-render", "ai", "-y", "do nothing"])
        assert result.exit_code == 0
        assert "nothing to do" in result.output

    def test_ai_surfaces_agent_errors_cleanly(self, cli_env, runner, monkeypatch):
        from weekboard.agent import AgentError

        def raise_error(store, config, text):
            raise AgentError("no claude CLI found")

        monkeypatch.setattr(cli_mod.agent_mod, "capture", raise_error)
        result = runner.invoke(cli_mod.cli, ["--no-render", "ai", "-y", "add something"])
        assert result.exit_code != 0
        assert "no claude CLI found" in result.output


class TestRollover:
    def test_rollover_without_ai_carries_everything(self, cli_env, runner):
        runner.invoke(cli_mod.cli, ["--no-render", "add", "Unfinished"])
        result = runner.invoke(cli_mod.cli, ["--no-render", "rollover"])
        assert result.exit_code == 0
        result = runner.invoke(cli_mod.cli, ["--no-render", "ls", "-w", "next"])
        assert "Unfinished" in result.output

    def test_rollover_on_clean_week_says_so(self, cli_env, runner):
        result = runner.invoke(cli_mod.cli, ["--no-render", "rollover"])
        assert result.exit_code == 0
        assert "clean" in result.output.lower()


def _current_key(store: Store) -> str:
    from weekboard.model import week_key

    return week_key()
