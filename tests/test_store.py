"""Persistence: atomic writes, seeding, and the undo history."""

import json

import pytest

from weekboard.config import Config
from weekboard.store import Store


@pytest.fixture()
def store(tmp_path):
    """A Store rooted in a throwaway directory."""
    return Store(Config(data_dir=str(tmp_path), output_dir=str(tmp_path / "out")))


class TestSaveLoad:
    def test_missing_week_is_created_empty(self, store):
        week = store.load("2026-W36")
        assert week.tasks == [] and week.key == "2026-W36"

    def test_round_trip(self, store):
        week = store.load("2026-W36")
        week.add("Send invoices to Kótlá")
        store.save(week)
        assert store.load("2026-W36").tasks[0].text == "Send invoices to Kótlá"

    def test_written_file_is_valid_json_and_utf8(self, store):
        week = store.load("2026-W36")
        week.add("verðskrá for Hólmur Heilsa")
        path = store.save(week)
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["tasks"][0]["text"] == "verðskrá for Hólmur Heilsa"

    def test_no_temp_files_are_left_behind(self, store):
        week = store.load("2026-W36")
        week.add("x")
        store.save(week)
        assert list(store.root.glob("*.tmp")) == []

    def test_keys_are_sorted(self, store):
        for key in ("2026-W40", "2026-W36", "2026-W38"):
            store.save(store.load(key))
        assert store.keys() == ["2026-W36", "2026-W38", "2026-W40"]

    def test_seed_inherits_soft_settings_from_the_previous_week(self, store):
        first = store.load("2026-W36")
        first.tagline = "Level up."
        first.overrides = {"focus": 77}
        store.save(first)
        seeded = store.load("2026-W37")
        assert seeded.tagline == "Level up."
        assert seeded.overrides == {"focus": 77}
        assert seeded.tasks == []          # tasks are never inherited

    def test_seed_does_not_mutate_the_source_overrides(self, store):
        first = store.load("2026-W36")
        first.overrides = {"focus": 50}
        store.save(first)
        seeded = store.load("2026-W37")
        seeded.overrides["focus"] = 99
        assert store.load("2026-W36").overrides == {"focus": 50}


class TestUndo:
    def test_nothing_to_undo_returns_none(self, store):
        assert store.undo() is None

    def test_undo_walks_backwards_rather_than_toggling(self, store):
        week = store.load("2026-W36")
        store.save(week)                       # baseline: 0 tasks
        for label in ("a", "b", "c"):
            week = store.load("2026-W36")
            week.add(label)
            store.save(week)
        assert len(store.load("2026-W36").tasks) == 3
        for expected in (2, 1, 0):
            store.undo()
            assert len(store.load("2026-W36").tasks) == expected

    def test_undo_recovers_a_destructive_delete(self, store):
        week = store.load("2026-W36")
        for label in ("a", "b", "c"):
            week.add(label)
        store.save(week)
        week = store.load("2026-W36")
        week.tasks = []
        store.save(week)
        assert store.load("2026-W36").tasks == []
        store.undo()
        assert len(store.load("2026-W36").tasks) == 3

    def test_history_is_capped(self, store):
        for index in range(store.HISTORY_LIMIT + 12):
            week = store.load("2026-W36")
            week.add(f"task {index}")
            store.save(week)
        assert len(store.history()) <= store.HISTORY_LIMIT

    def test_first_ever_save_creates_no_snapshot(self, store):
        store.save(store.load("2026-W36"))
        assert store.history() == []
