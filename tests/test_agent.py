"""The ops applier and reply parser — everything except the network call.

These matter because the input is a language model: it will eventually return
something malformed, and that must never corrupt the board.
"""

import pytest

from weekboard.agent import AgentError, _extract_json, api_key, apply_ops, backend
from weekboard.config import Config
from weekboard.store import Store


@pytest.fixture()
def store(tmp_path):
    return Store(Config(data_dir=str(tmp_path), output_dir=str(tmp_path / "out")))


class TestExtractJson:
    def test_bare_object(self):
        assert _extract_json('{"ops": []}') == {"ops": []}

    def test_fenced(self):
        assert _extract_json('```json\n{"ops": []}\n```') == {"ops": []}

    def test_fenced_without_language(self):
        assert _extract_json('```\n{"ops": []}\n```') == {"ops": []}

    def test_chatty_preamble(self):
        assert _extract_json('Sure! Here you go:\n{"ops": [], "say": "hi"}')["say"] == "hi"

    def test_unparseable_raises(self):
        with pytest.raises(AgentError):
            _extract_json("I'd rather not.")


class TestApplyOps:
    def test_add(self, store):
        apply_ops(store, [{"op": "add", "text": "Call Harry", "week": "2026-W36"}])
        assert store.load("2026-W36").tasks[0].text == "Call Harry"

    def test_add_with_no_text_is_skipped(self, store):
        apply_ops(store, [{"op": "add", "week": "2026-W36"}])
        assert store.load("2026-W36").tasks == []

    def test_add_with_whitespace_only_text_is_skipped(self, store):
        apply_ops(store, [{"op": "add", "text": "   ", "week": "2026-W36"}])
        assert store.load("2026-W36").tasks == []

    def test_done_by_substring(self, store):
        apply_ops(store, [{"op": "add", "text": "Call Kalli back", "week": "2026-W36"}])
        apply_ops(store, [{"op": "done", "match": "Kalli", "week": "2026-W36"}])
        assert store.load("2026-W36").tasks[0].done

    def test_done_by_number(self, store):
        apply_ops(store, [{"op": "add", "text": "one", "week": "2026-W36"},
                          {"op": "add", "text": "two", "week": "2026-W36"}])
        apply_ops(store, [{"op": "done", "match": "2", "week": "2026-W36"}])
        assert store.load("2026-W36").tasks[1].done

    def test_done_with_no_match_changes_nothing(self, store):
        apply_ops(store, [{"op": "add", "text": "one", "week": "2026-W36"}])
        apply_ops(store, [{"op": "done", "match": "nonexistent", "week": "2026-W36"}])
        assert not store.load("2026-W36").tasks[0].done

    def test_move_between_weeks_marks_the_origin(self, store):
        apply_ops(store, [{"op": "add", "text": "Prep talk", "week": "2026-W36"}])
        apply_ops(store, [{"op": "move", "match": "Prep", "week": "2026-W36",
                           "to_week": "2026-W37"}])
        assert store.load("2026-W36").tasks == []
        moved = store.load("2026-W37").tasks[0]
        assert moved.text == "Prep talk" and moved.carried_from == "2026-W36"

    def test_remove(self, store):
        apply_ops(store, [{"op": "add", "text": "gone", "week": "2026-W36"}])
        apply_ops(store, [{"op": "remove", "match": "gone", "week": "2026-W36"}])
        assert store.load("2026-W36").tasks == []

    def test_edit(self, store):
        apply_ops(store, [{"op": "add", "text": "old", "week": "2026-W36"}])
        apply_ops(store, [{"op": "edit", "match": "old", "text": "new", "week": "2026-W36"}])
        assert store.load("2026-W36").tasks[0].text == "new"

    def test_status_override_is_clamped(self, store):
        apply_ops(store, [{"op": "status", "focus": 500, "week": "2026-W36"}])
        assert store.load("2026-W36").overrides["focus"] == 100

    def test_unknown_op_is_ignored(self, store):
        apply_ops(store, [{"op": "launch_missiles", "week": "2026-W36"}])
        assert store.load("2026-W36").tasks == []

    def test_op_without_a_kind_is_ignored(self, store):
        assert apply_ops(store, [{"nope": 1}]) == []

    def test_null_week_falls_back_to_the_current_one(self, store):
        from weekboard.model import week_key

        apply_ops(store, [{"op": "add", "text": "x", "week": None}])
        assert store.load(week_key()).tasks[0].text == "x"


class TestKeyResolution:
    def test_environment_wins(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text("ANTHROPIC_API_KEY=from-file\n")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "from-env")
        config = Config(backend="api", api_key_file=str(env_file))
        assert api_key(config)[0] == "from-env"

    def test_dotenv_style_file(self, tmp_path, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        env_file = tmp_path / ".env"
        env_file.write_text('# comment\nOTHER=x\nexport ANTHROPIC_API_KEY="sk-ant-quoted"\n')
        config = Config(backend="api", api_key_file=str(env_file))
        assert api_key(config)[0] == "sk-ant-quoted"

    def test_bare_key_file(self, tmp_path, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        key_file = tmp_path / "key"
        key_file.write_text("sk-ant-bare\n")
        config = Config(backend="api", api_key_file=str(key_file))
        assert api_key(config)[0] == "sk-ant-bare"

    def test_missing_key_falls_back_to_the_cli(self, tmp_path, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        config = Config(backend="api", api_key_file=str(tmp_path / "nope"))
        assert backend(config) == "cli"
