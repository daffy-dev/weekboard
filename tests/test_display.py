"""Display detection: pure clamping/slugging logic, and the on-disk cache.

`_probe_macos` shells out to `system_profiler`, so it isn't exercised here —
everything that can be tested without a real Mac attached is.
"""

from __future__ import annotations

import json
import time

from weekboard.display import (
    FALLBACK,
    MAX_WIDTH,
    MIN_WIDTH,
    _clamp,
    detect_all,
    slugify_display_name,
)


class TestSlugifyDisplayName:
    def test_lowercases_and_dashes_spaces(self):
        assert slugify_display_name("Color LCD") == "color-lcd"

    def test_folds_british_spelling_to_american(self):
        # Observed on a real machine: system_profiler says "Color LCD" but
        # System Events' `display name of desktop N` says "Colour LCD" for
        # the same physical built-in panel.
        assert slugify_display_name("Colour LCD") == slugify_display_name("Color LCD")

    def test_keeps_hardware_model_names_intact(self):
        assert slugify_display_name("Y27f-30") == "y27f-30"

    def test_strips_punctuation(self):
        assert slugify_display_name("DELL U2720Q!") == "dell-u2720q"

    def test_empty_name_is_never_empty_slug(self):
        assert slugify_display_name("") == "display"
        assert slugify_display_name("   ") == "display"


class TestClamp:
    def test_small_display_scales_up_to_minimum(self):
        width, height = _clamp(1280, 800)
        assert width >= MIN_WIDTH

    def test_huge_display_scales_down_to_maximum(self):
        width, height = _clamp(8000, 4000)
        assert width <= MAX_WIDTH

    def test_typical_display_is_left_alone(self):
        assert _clamp(1920, 1080) == (1920, 1080)

    def test_always_even(self):
        width, height = _clamp(1921, 1081)
        assert width % 2 == 0 and height % 2 == 0


class TestDetectAll:
    def test_no_cache_and_no_darwin_probe_falls_back(self, tmp_path, monkeypatch):
        monkeypatch.setattr("weekboard.display.platform.system", lambda: "Linux")
        sizes = detect_all(tmp_path / "cache.json")
        assert sizes == [("", *FALLBACK)]

    def test_fresh_cache_is_used_without_reprobing(self, tmp_path, monkeypatch):
        cache = tmp_path / "cache.json"
        cache.write_text(json.dumps({
            "sizes": [["Color LCD", 3456, 2234], ["Y27f-30", 1920, 1080]],
            "at": time.time(),
        }))

        def fail_if_called():
            raise AssertionError("should not reprobe with a fresh cache")

        monkeypatch.setattr("weekboard.display._probe_macos", fail_if_called)
        assert detect_all(cache) == [("Color LCD", 3456, 2234), ("Y27f-30", 1920, 1080)]

    def test_stale_cache_triggers_reprobe(self, tmp_path, monkeypatch):
        cache = tmp_path / "cache.json"
        cache.write_text(json.dumps({
            "sizes": [["Old Display", 1024, 768]],
            "at": time.time() - 8 * 24 * 3600,
        }))
        monkeypatch.setattr(
            "weekboard.display._probe_macos",
            lambda: [("New Display", 2560, 1440)],
        )
        monkeypatch.setattr("weekboard.display.platform.system", lambda: "Darwin")
        assert detect_all(cache) == [("New Display", 2560, 1440)]

    def test_multiple_displays_pass_through_in_probe_order(self, tmp_path, monkeypatch):
        # _probe_macos already promises "largest first"; detect_all trusts
        # that rather than re-sorting, so this locks in that it doesn't
        # silently reorder what the probe returned.
        monkeypatch.setattr("weekboard.display.platform.system", lambda: "Darwin")
        monkeypatch.setattr(
            "weekboard.display._probe_macos",
            lambda: [("Color LCD", 3456, 2234), ("Y27f-30", 1920, 1080)],
        )
        sizes = detect_all(tmp_path / "cache.json")
        assert [name for name, _, _ in sizes] == ["Color LCD", "Y27f-30"]

    def test_refresh_ignores_a_fresh_cache(self, tmp_path, monkeypatch):
        cache = tmp_path / "cache.json"
        cache.write_text(json.dumps({
            "sizes": [["Old", 1024, 768]],
            "at": time.time(),
        }))
        monkeypatch.setattr("weekboard.display.platform.system", lambda: "Darwin")
        monkeypatch.setattr("weekboard.display._probe_macos", lambda: [("New", 2560, 1440)])
        assert detect_all(cache, refresh=True) == [("New", 2560, 1440)]
