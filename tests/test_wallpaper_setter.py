"""Wallpaper batching and per-desktop matching — no AppleScript involved.

`desktop_names` and `_run_osascript` shell out and aren't exercised here;
everything that decides *which* image goes *where* is pure and is.
"""

from __future__ import annotations

import time
from pathlib import Path

import wallpaper_setter as ws


def _render(name: str, slug: str | None, stamp: str | None, *, size: int = 100) -> ws.Render:
    return ws.Render(path=Path(f"/tmp/{name}"), mtime_ns=0, size=size, slug=slug, stamp=stamp)


class TestParseRender:
    def test_named_render(self):
        slug, stamp = ws._parse_render(Path("weekboard-2026-W37-color-lcd-20260907-091936.png"))
        assert slug == "color-lcd"
        assert stamp == "20260907-091936"

    def test_unnamed_render(self):
        slug, stamp = ws._parse_render(Path("weekboard-2026-W37-20260907-091936.png"))
        assert slug is None
        assert stamp == "20260907-091936"

    def test_arbitrary_photo_does_not_parse(self):
        assert ws._parse_render(Path("holiday.jpg")) == (None, None)

    def test_hyphenated_hardware_name(self):
        slug, stamp = ws._parse_render(Path("weekboard-2026-W37-y27f-30-20260907-091936.png"))
        assert slug == "y27f-30"
        assert stamp == "20260907-091936"

    def test_case_insensitive_extension(self):
        slug, stamp = ws._parse_render(Path("weekboard-2026-W9-color-lcd-20260907-091936.JPG"))
        assert slug == "color-lcd"


class TestScanAndBatch:
    def test_scan_ignores_dotfiles_and_non_images(self, tmp_path):
        (tmp_path / "weekboard-2026-W37-color-lcd-20260907-091936.png").write_bytes(b"a")
        (tmp_path / ".weekboard-2026-W37-color-lcd-20260907-091937.png.part").write_bytes(b"b")
        (tmp_path / "notes.txt").write_text("hi")
        entries = ws.scan(tmp_path)
        assert [e.path.name for e in entries] == ["weekboard-2026-W37-color-lcd-20260907-091936.png"]

    def test_scan_sorts_newest_first(self, tmp_path):
        old = tmp_path / "a.png"
        new = tmp_path / "b.png"
        old.write_bytes(b"a")
        time.sleep(0.01)
        new.write_bytes(b"b")
        entries = ws.scan(tmp_path)
        assert entries[0].path.name == "b.png"

    def test_current_batch_groups_same_stamp(self):
        entries = [
            _render("a.png", "color-lcd", "20260907-091936"),
            _render("b.png", "y27f-30", "20260907-091936"),
            _render("c.png", "color-lcd", "20260907-090000"),  # older stamp
        ]
        batch = ws.current_batch(entries)
        assert {r.path.name for r in batch} == {"a.png", "b.png"}

    def test_current_batch_single_unstamped_image(self):
        entries = [_render("holiday.jpg", None, None)]
        assert ws.current_batch(entries) == entries

    def test_empty_scan_gives_empty_batch(self):
        assert ws.current_batch([]) == []


class TestAssignToDesktops:
    def test_single_image_batch_goes_on_every_desktop(self):
        batch = [_render("holiday.jpg", None, None)]
        names = ["Color LCD", "Y27f-30"]
        assignment = ws.assign_to_desktops(batch, names)
        assert assignment == [batch[0].path, batch[0].path]

    def test_exact_name_match_per_display(self):
        color = _render("a.png", "color-lcd", "s")
        y27f = _render("b.png", "y27f-30", "s")
        batch = [color, y27f]
        # AppleScript reports "Colour LCD" (British) for the same panel
        # system_profiler called "Color LCD" at render time.
        names = ["Colour LCD", "Y27f-30"]
        assignment = ws.assign_to_desktops(batch, names)
        assert assignment == [color.path, y27f.path]

    def test_order_independent_of_desktop_order(self):
        color = _render("a.png", "color-lcd", "s")
        y27f = _render("b.png", "y27f-30", "s")
        batch = [color, y27f]
        names = ["Y27f-30", "Color LCD"]
        assignment = ws.assign_to_desktops(batch, names)
        assert assignment == [y27f.path, color.path]

    def test_unmatched_desktop_falls_back_to_a_remaining_render(self):
        color = _render("a.png", "color-lcd", "s", size=500)
        other = _render("b.png", "dell-u2720q", "s", size=100)
        batch = [color, other]
        names = ["Color LCD", "Some Unrecognized Monitor"]
        assignment = ws.assign_to_desktops(batch, names)
        assert assignment[0] == color.path
        # No exact match for the second desktop; it gets whatever's left.
        assert assignment[1] == other.path

    def test_no_desktop_names_gives_no_assignment(self):
        batch = [_render("a.png", "color-lcd", "s"), _render("b.png", "y27f-30", "s")]
        assert ws.assign_to_desktops(batch, []) == []
