"""GitHub events parsing and caching — no network in these tests.

`parse_events` is pure, so it's tested directly against payload shapes GitHub
actually sends. `recent_commits` is tested through its cache: a fresh cache
is trusted without a network call, a stale or forced one is not.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone

import pytest

from weekboard.github import parse_events, recent_commits


def _push_event(when: datetime, repo: str, commits: list[dict]) -> dict:
    return {
        "type": "PushEvent",
        "created_at": when.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "repo": {"name": repo},
        "payload": {"commits": commits},
    }


class TestParseEvents:
    def test_extracts_subject_and_repo(self):
        now = datetime(2026, 9, 3, tzinfo=timezone.utc)
        events = [
            _push_event(
                now - timedelta(hours=1),
                "daffy/weekboard",
                [{"sha": "abc123", "message": "Add github sync\n\nlonger body"}],
            )
        ]
        subjects, count = parse_events(events, days=7, now=now)
        assert subjects == ["weekboard: Add github sync"]
        assert count == 1

    def test_ignores_non_push_events(self):
        now = datetime(2026, 9, 3, tzinfo=timezone.utc)
        events = [
            {"type": "WatchEvent", "created_at": now.isoformat(), "repo": {"name": "x/y"}},
        ]
        subjects, count = parse_events(events, days=7, now=now)
        assert subjects == [] and count == 0

    def test_drops_events_outside_the_window(self):
        now = datetime(2026, 9, 3, tzinfo=timezone.utc)
        events = [
            _push_event(now - timedelta(days=30), "d/x", [{"sha": "old", "message": "stale"}]),
        ]
        subjects, count = parse_events(events, days=7, now=now)
        assert subjects == [] and count == 0

    def test_most_recent_first(self):
        now = datetime(2026, 9, 3, tzinfo=timezone.utc)
        events = [
            _push_event(now - timedelta(hours=5), "d/x", [{"sha": "s1", "message": "first"}]),
            _push_event(now - timedelta(hours=1), "d/x", [{"sha": "s2", "message": "second"}]),
        ]
        subjects, _ = parse_events(events, days=7, now=now)
        assert subjects == ["x: second", "x: first"]

    def test_dedupes_by_sha_across_force_pushes(self):
        now = datetime(2026, 9, 3, tzinfo=timezone.utc)
        events = [
            _push_event(now - timedelta(hours=2), "d/x", [{"sha": "dup", "message": "m"}]),
            _push_event(now - timedelta(hours=1), "d/x", [{"sha": "dup", "message": "m"}]),
        ]
        subjects, count = parse_events(events, days=7, now=now)
        assert count == 1
        assert subjects == ["x: m"]

    def test_multiple_commits_in_one_push(self):
        now = datetime(2026, 9, 3, tzinfo=timezone.utc)
        events = [
            _push_event(
                now - timedelta(hours=1),
                "d/x",
                [
                    {"sha": "s1", "message": "one"},
                    {"sha": "s2", "message": "two"},
                ],
            )
        ]
        subjects, count = parse_events(events, days=7, now=now)
        assert count == 2
        # Same push, same timestamp: stable sort keeps payload order (oldest first).
        assert subjects == ["x: one", "x: two"]

    def test_skips_malformed_timestamp(self):
        now = datetime(2026, 9, 3, tzinfo=timezone.utc)
        events = [_push_event(now, "d/x", [{"sha": "a", "message": "m"}])]
        events[0]["created_at"] = "not-a-date"
        subjects, count = parse_events(events, days=7, now=now)
        assert subjects == [] and count == 0

    def test_skips_commit_with_blank_message(self):
        now = datetime(2026, 9, 3, tzinfo=timezone.utc)
        events = [_push_event(now, "d/x", [{"sha": "a", "message": "   "}])]
        subjects, count = parse_events(events, days=7, now=now)
        assert subjects == [] and count == 0

    def test_empty_events_list(self):
        assert parse_events([], days=7) == ([], 0)


class TestRecentCommitsCache:
    def test_fresh_cache_is_returned_without_touching_network(self, tmp_path, monkeypatch):
        cache_path = tmp_path / ".github.json"
        cache_path.write_text(
            json.dumps({"subjects": ["x: cached"], "count": 3, "at": time.time()}),
            encoding="utf-8",
        )

        def fail_if_called(*args, **kwargs):
            raise AssertionError("should not hit the network with a fresh cache")

        monkeypatch.setattr("weekboard.github.available", fail_if_called)
        subjects, count = recent_commits("daffy", cache_path=cache_path, ttl=900)
        assert subjects == ["x: cached"]
        assert count == 3

    def test_stale_cache_is_ignored(self, tmp_path, monkeypatch):
        cache_path = tmp_path / ".github.json"
        cache_path.write_text(
            json.dumps({"subjects": ["x: old"], "count": 1, "at": time.time() - 3600}),
            encoding="utf-8",
        )
        monkeypatch.setattr("weekboard.github.available", lambda: False)
        subjects, count = recent_commits("daffy", cache_path=cache_path, ttl=900)
        assert subjects == [] and count == 0

    def test_force_bypasses_a_fresh_cache(self, tmp_path, monkeypatch):
        cache_path = tmp_path / ".github.json"
        cache_path.write_text(
            json.dumps({"subjects": ["x: cached"], "count": 3, "at": time.time()}),
            encoding="utf-8",
        )
        monkeypatch.setattr("weekboard.github.available", lambda: False)
        subjects, count = recent_commits("daffy", cache_path=cache_path, ttl=900, force=True)
        assert subjects == [] and count == 0

    def test_no_user_and_no_cache_returns_empty(self, tmp_path):
        cache_path = tmp_path / ".github.json"
        assert recent_commits("", cache_path=cache_path) == ([], 0)

    def test_unavailable_gh_returns_empty_without_raising(self, tmp_path, monkeypatch):
        cache_path = tmp_path / ".github.json"
        monkeypatch.setattr("weekboard.github.available", lambda: False)
        assert recent_commits("daffy", cache_path=cache_path) == ([], 0)

    def test_successful_fetch_writes_cache(self, tmp_path, monkeypatch):
        cache_path = tmp_path / ".github.json"
        now = datetime.now(timezone.utc)
        monkeypatch.setattr("weekboard.github.available", lambda: True)
        monkeypatch.setattr(
            "weekboard.github._fetch_events",
            lambda user: [_push_event(now, "d/x", [{"sha": "a", "message": "shipped it"}])],
        )
        subjects, count = recent_commits("daffy", cache_path=cache_path, days=7)
        assert subjects == ["x: shipped it"]
        assert count == 1
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        assert cached["count"] == 1

    def test_corrupt_cache_is_treated_as_missing(self, tmp_path, monkeypatch):
        cache_path = tmp_path / ".github.json"
        cache_path.write_text("not json", encoding="utf-8")
        monkeypatch.setattr("weekboard.github.available", lambda: False)
        subjects, count = recent_commits("daffy", cache_path=cache_path)
        assert subjects == [] and count == 0

    def test_limit_truncates_subjects(self, tmp_path, monkeypatch):
        cache_path = tmp_path / ".github.json"
        now = datetime.now(timezone.utc)
        monkeypatch.setattr("weekboard.github.available", lambda: True)
        commits = [{"sha": str(i), "message": f"m{i}"} for i in range(10)]
        monkeypatch.setattr(
            "weekboard.github._fetch_events", lambda user: [_push_event(now, "d/x", commits)]
        )
        subjects, count = recent_commits("daffy", cache_path=cache_path, limit=3)
        assert len(subjects) == 3
        assert count == 10
