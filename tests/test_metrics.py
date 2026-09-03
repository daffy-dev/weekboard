"""The gauges must be derived from real activity, and never blow up."""

import pytest

from weekboard.config import Config
from weekboard.metrics import compute, consistency, momentum, shipped
from weekboard.store import Store


@pytest.fixture()
def store(tmp_path):
    return Store(Config(data_dir=str(tmp_path), output_dir=str(tmp_path / "out")))


def test_gauges_are_all_in_range(store):
    week = store.load("2026-W36")
    week.add("a")
    gauges = compute(week, store, {"commits": []}, store.config)
    assert len(gauges) == 4
    assert all(0 <= g["value"] <= 100 for g in gauges)


def test_empty_week_does_not_divide_by_zero(store):
    gauges = compute(store.load("2026-W36"), store, {"commits": []}, store.config)
    assert all(g["value"] == 0 or isinstance(g["value"], int) for g in gauges)


def test_override_pins_a_value(store):
    week = store.load("2026-W36")
    week.overrides["focus"] = 42
    focus = next(g for g in compute(week, store, {"commits": []}, store.config)
                 if g["label"] == "FOCUS")
    assert focus["value"] == 42 and focus["pinned"]


def test_shipped_tracks_commits():
    assert shipped({"commits": []}) == 0
    assert shipped({"commits": ["a"] * 15}, target=15) == 100
    assert shipped({"commits": ["a"] * 99}, target=15) == 100   # clamped


def test_consistency_of_a_week_with_no_completions(store):
    assert consistency(store.load("2026-W36")) == 0


def test_momentum_without_history_falls_back_to_progress(store):
    week = store.load("2026-W36")
    week.add("a").mark(True)
    week.add("b")
    assert momentum(week, store) == 50
