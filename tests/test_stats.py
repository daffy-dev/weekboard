"""The pure pieces of stats.py: the sparkline maths and the on-disk trend
history behind it. collect() itself shells out to psutil/git/gh and isn't
covered here — see the module docstring pattern in test_render.py's sibling
for why that's the deliberate line drawn in this codebase.
"""

from __future__ import annotations

from weekboard.stats import HISTORY_LIMIT, _load_history, _pseudo_series, _record_history, _sparkline


class TestSparkline:
    def test_empty_input_is_flat_zero(self):
        assert _sparkline([]) == [0] * 24

    def test_scales_to_the_peak(self):
        assert _sparkline([10, 20, 40], width=3) == [25, 50, 100]

    def test_pads_short_series_with_leading_zeros(self):
        result = _sparkline([50], width=5)
        assert result == [0, 0, 0, 0, 100]

    def test_only_keeps_the_most_recent_values(self):
        values = list(range(1, 31))  # 1..30, width 24 -> keep the last 24
        assert _sparkline(values, width=24)[-1] == 100
        assert len(_sparkline(values, width=24)) == 24

    def test_respects_width(self):
        assert len(_sparkline([1, 2, 3], width=10)) == 10

    def test_flat_series_does_not_divide_by_zero(self):
        assert _sparkline([0, 0, 0], width=3) == [0, 0, 0]


class TestPseudoSeries:
    def test_deterministic_for_the_same_seed(self):
        assert _pseudo_series(42) == _pseudo_series(42)

    def test_respects_width(self):
        assert len(_pseudo_series(1, width=40)) == 40


class TestHistory:
    def test_missing_file_loads_as_empty(self, tmp_path):
        assert _load_history(tmp_path / "nope.json") == {}

    def test_corrupt_file_loads_as_empty_rather_than_raising(self, tmp_path):
        path = tmp_path / "history.json"
        path.write_text("not json{{{", encoding="utf-8")
        assert _load_history(path) == {}

    def test_record_appends_and_round_trips(self, tmp_path):
        path = tmp_path / "data" / ".stats_history.json"
        _record_history(path, {"cpu": 10.0})
        history = _record_history(path, {"cpu": 20.0})
        assert history["cpu"] == [10.0, 20.0]
        assert _load_history(path)["cpu"] == [10.0, 20.0]

    def test_record_tracks_each_metric_independently(self, tmp_path):
        path = tmp_path / "history.json"
        _record_history(path, {"cpu": 1.0, "ram": 50.0})
        history = _record_history(path, {"cpu": 2.0, "ram": 51.0})
        assert history["cpu"] == [1.0, 2.0]
        assert history["ram"] == [50.0, 51.0]

    def test_record_trims_to_the_history_limit(self, tmp_path):
        path = tmp_path / "history.json"
        history = {}
        for i in range(HISTORY_LIMIT + 10):
            history = _record_history(path, {"cpu": float(i)})
        assert len(history["cpu"]) == HISTORY_LIMIT
        assert history["cpu"][-1] == float(HISTORY_LIMIT + 9)

    def test_record_creates_parent_directories(self, tmp_path):
        path = tmp_path / "nested" / "dir" / "history.json"
        _record_history(path, {"cpu": 1.0})
        assert path.exists()
