"""ISO week arithmetic — the part most likely to break silently at New Year."""

from datetime import date

import pytest

from weekboard.model import (
    Task,
    Week,
    parse_week_key,
    shift_week,
    week_bounds,
    week_key,
    weeks_in_year,
)


class TestWeekMaths:
    def test_weeks_in_year(self):
        # 2026 is a 53-week ISO year; 2025 and 2027 are 52.
        assert weeks_in_year(2026) == 53
        assert weeks_in_year(2025) == 52
        assert weeks_in_year(2027) == 52

    def test_week_53_valid_only_where_it_exists(self):
        assert parse_week_key("2026-W53") == "2026-W53"
        with pytest.raises(ValueError, match="52 ISO weeks"):
            parse_week_key("2025-W53")

    def test_bare_number_uses_the_current_year(self):
        base = date(2026, 9, 2)
        assert parse_week_key("37", base=base) == "2026-W37"

    def test_relative_references(self):
        base = date(2026, 9, 2)  # a Wednesday in W36
        assert parse_week_key(None, base=base) == "2026-W36"
        assert parse_week_key("next", base=base) == "2026-W37"
        assert parse_week_key("prev", base=base) == "2026-W35"
        assert parse_week_key("+2", base=base) == "2026-W38"
        assert parse_week_key("-1", base=base) == "2026-W35"

    def test_garbage_is_rejected(self):
        for bad in ("banana", "W", "2026-W99", "0"):
            with pytest.raises(ValueError):
                parse_week_key(bad)

    def test_bounds_are_monday_to_sunday(self):
        start, end = week_bounds("2026-W36")
        assert start.weekday() == 0 and end.weekday() == 6
        assert (end - start).days == 6

    def test_shift_crosses_the_year_boundary(self):
        # W53 of 2026 -> W01 of 2027, not W54.
        assert shift_week("2026-W53", 1) == "2027-W01"
        assert shift_week("2027-W01", -1) == "2026-W53"

    def test_week_key_round_trips(self):
        day = date(2026, 12, 31)
        key = week_key(day)
        start, end = week_bounds(key)
        assert start <= day <= end


class TestWeek:
    def test_ids_are_reused_after_removal(self):
        week = Week(key="2026-W36")
        week.add("a"), week.add("b")
        week.remove(1)
        assert week.add("c").id == 1

    def test_renumber_is_sequential(self):
        week = Week(key="2026-W36")
        for text in "abcd":
            week.add(text)
        week.remove(2)
        week.renumber()
        assert [t.id for t in week.tasks] == [1, 2, 3]

    def test_progress_of_empty_week_is_zero(self):
        assert Week(key="2026-W36").progress == 0.0

    def test_completions_land_on_the_right_weekday(self):
        week = Week(key="2026-W36")           # Mon 31 Aug - Sun 6 Sep 2026
        task = week.add("x")
        task.done = True
        task.completed = "2026-09-02T10:00:00"  # Wednesday = index 2
        assert week.completions_by_day()[2] == 1

    def test_completion_outside_the_week_is_ignored(self):
        week = Week(key="2026-W36")
        task = week.add("x")
        task.done = True
        task.completed = "2026-01-01T10:00:00"
        assert sum(week.completions_by_day()) == 0

    def test_unparseable_completion_does_not_crash(self):
        week = Week(key="2026-W36")
        task = week.add("x")
        task.done, task.completed = True, "not a date"
        assert sum(week.completions_by_day()) == 0

    def test_round_trip_preserves_tasks(self):
        week = Week(key="2026-W36")
        week.add("Glóra sales pitch", priority="high", tags=["sales"])
        week.overrides["focus"] = 90
        restored = Week.from_dict(week.to_dict())
        assert restored.tasks[0].text == "Glóra sales pitch"
        assert restored.tasks[0].priority == "high"
        assert restored.tasks[0].tags == ["sales"]
        assert restored.overrides == {"focus": 90}

    def test_unknown_keys_from_older_files_are_ignored(self):
        # v1 files carried a `note` field that no longer exists.
        task = Task.from_dict({"id": 1, "text": "x", "note": "gone", "bogus": 1})
        assert task.text == "x"

    def test_mark_stamps_and_clears_completion(self):
        task = Task(id=1, text="x")
        task.mark(True)
        assert task.done and task.completed
        task.mark(False)
        assert not task.done and task.completed is None
