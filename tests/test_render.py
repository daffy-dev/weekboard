"""Layout maths and art handling — no browser needed."""

import pytest

from weekboard.asciiart import BRAILLE_BASE
from weekboard.config import Config
from weekboard.render import _ascii_size, _task_metrics, is_braille


class TestBrailleDetection:
    def test_plain_ascii_art(self):
        assert not is_braille("  /\\_/\\\n ( o.o )")

    def test_braille_art(self):
        assert is_braille("".join(chr(BRAILLE_BASE + i) for i in range(1, 40)))

    def test_empty(self):
        assert not is_braille("   \n  ")

    def test_mostly_braille_with_a_caption(self):
        art = "".join(chr(BRAILLE_BASE + i) for i in range(1, 60)) + "\nyes"
        assert is_braille(art)


class TestTaskMetrics:
    @pytest.fixture()
    def config(self):
        return Config(width=3840, height=2160)

    def test_empty_week_is_safe(self, config):
        cols, size, row, pad = _task_metrics(0, config, config.width / 190.0)
        assert cols == 1 and size > 0 and row > 0

    def test_small_lists_stay_one_column(self, config):
        assert _task_metrics(14, config, config.width / 190.0)[0] == 1

    def test_long_lists_go_two_columns(self, config):
        assert _task_metrics(40, config, config.width / 190.0)[0] == 2

    def test_font_never_collapses(self, config):
        for count in (1, 20, 60, 200):
            _, size, _, _ = _task_metrics(count, config, config.width / 190.0)
            assert 0.18 <= size <= 1.2

    def test_rows_fit_the_panel(self, config):
        unit = config.width / 190.0
        for count in (5, 14, 30, 60):
            cols, _, row, _ = _task_metrics(count, config, unit)
            per_column = -(-count // cols)
            assert row * per_column <= (config.height / unit)

    def test_holds_at_other_resolutions(self):
        for width, height in ((1920, 1080), (2560, 1440), (5120, 2880)):
            config = Config(width=width, height=height)
            cols, size, row, pad = _task_metrics(25, config, width / 190.0)
            assert cols in (1, 2) and size > 0 and row > 0 and pad >= 0


class TestAsciiSizing:
    def test_wide_art_gets_a_smaller_font(self):
        config = Config(width=3840, height=2160)
        unit = config.width / 190.0
        narrow = _ascii_size("\n".join(["x" * 20] * 10), config, unit)
        wide = _ascii_size("\n".join(["x" * 90] * 10), config, unit)
        assert wide < narrow

    def test_tall_art_gets_a_smaller_font(self):
        config = Config(width=3840, height=2160)
        unit = config.width / 190.0
        short = _ascii_size("\n".join(["x" * 30] * 5), config, unit)
        tall = _ascii_size("\n".join(["x" * 30] * 60), config, unit)
        assert tall < short

    def test_stays_within_bounds(self):
        config = Config(width=3840, height=2160)
        unit = config.width / 190.0
        for art in ("x", "\n".join(["x" * 200] * 200), ""):
            assert 0.18 <= _ascii_size(art or "x", config, unit) <= 1.1
