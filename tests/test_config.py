"""Config load/save: defaults, unknown-key tolerance, and corrupt-file handling.

There was no coverage of load_config() at all before this — including its
silent fallback on a corrupt config.json, which reset every setting to
defaults with no indication why. That's now a warning on stderr instead of
a silent swallow; these tests pin both the old promise (never raise, always
hand back a usable Config) and the new one (say something when it happens).
"""

from __future__ import annotations

import json

import pytest

from weekboard.config import Config, load_config, save_config


@pytest.fixture()
def config_path(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    monkeypatch.setattr("weekboard.config.CONFIG_PATH", path)
    return path


class TestLoadConfig:
    def test_missing_file_returns_defaults(self, config_path):
        config = load_config()
        assert config.accent == Config().accent
        assert not config_path.exists()

    def test_round_trips_through_save(self, config_path):
        original = Config(accent="#ff00ff", tools=["GIT", "COFFEE"])
        save_config(original)
        loaded = load_config()
        assert loaded.accent == "#ff00ff"
        assert loaded.tools == ["GIT", "COFFEE"]

    def test_unknown_keys_are_ignored_not_fatal(self, config_path):
        config_path.write_text(json.dumps({"accent": "#123456", "made_up_field": "x"}))
        config = load_config()
        assert config.accent == "#123456"

    def test_corrupt_json_falls_back_to_defaults_without_raising(self, config_path, capsys):
        config_path.write_text("{not valid json")
        config = load_config()
        assert config.accent == Config().accent

    def test_corrupt_json_warns_on_stderr(self, config_path, capsys):
        config_path.write_text("{not valid json")
        load_config()
        captured = capsys.readouterr()
        assert "not valid JSON" in captured.err
        assert str(config_path) in captured.err

    def test_valid_json_produces_no_warning(self, config_path, capsys):
        save_config(Config())
        load_config()
        captured = capsys.readouterr()
        assert captured.err == ""
