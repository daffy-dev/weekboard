"""The SYSTEM STATUS gauges, computed from what actually happened.

The original four were numbers you typed once and then never changed, which
makes them decoration. These are derived from the board and your git history,
so they move on their own. Any of them can still be pinned by hand.
"""

from __future__ import annotations

from datetime import date

GAUGE_NAMES = ("focus", "momentum", "shipped", "done")

# A week with this many commits across the tracked repos reads as "full".
DEFAULT_COMMIT_TARGET = 15
# Weeks of history used for the momentum baseline.
BASELINE_WEEKS = 4


def _clamp(value: float) -> int:
    """Round into 0-100."""
    return max(0, min(100, round(value)))


def consistency(week) -> int:
    """Share of the days so far this week on which you closed something.

    Rewards showing up daily rather than one heroic Thursday.
    """
    start, _ = week.bounds
    today = date.today()
    elapsed = 7 if today > week.bounds[1] else max(1, (today - start).days + 1)
    counts = week.completions_by_day()[:elapsed]
    active = sum(1 for c in counts if c)
    return _clamp(active / elapsed * 100)


def momentum(week, store) -> int:
    """This week's completions against the trailing average.

    Matching your recent pace reads as 60; roughly doubling it maxes out.
    """
    from .model import shift_week

    done_now = len(week.done_tasks)
    history = []
    for offset in range(1, BASELINE_WEEKS + 1):
        key = shift_week(week.key, -offset)
        if store.exists(key):
            history.append(len(store.load(key).done_tasks))
    if not history:
        # No history yet: fall back to raw progress so it isn't stuck at zero.
        return _clamp(week.progress * 100)
    baseline = sum(history) / len(history)
    return _clamp(done_now / max(baseline, 0.5) * 60)


def shipped(sys_stats, target: int = DEFAULT_COMMIT_TARGET) -> int:
    """Recent commits across the tracked repos, against a weekly target.

    Uses the true count, not the handful of subjects shown in TERMINAL.LOG —
    those are capped for display and would silently cap this gauge too.
    """
    count = sys_stats.get("commit_count")
    if count is None:
        count = len(sys_stats.get("commits", []))
    return _clamp(count / max(target, 1) * 100)


def completion(week) -> int:
    """Plain share of this week's tasks that are done."""
    return _clamp(week.progress * 100)


def compute(week, store, sys_stats, config) -> list[dict]:
    """The four gauges, honouring any manual overrides on the week."""
    target = getattr(config, "commit_target", DEFAULT_COMMIT_TARGET)
    values = {
        "focus": consistency(week),
        "momentum": momentum(week, store),
        "shipped": shipped(sys_stats, target),
        "done": completion(week),
    }
    labels = {
        "focus": "FOCUS",
        "momentum": "MOMENTUM",
        "shipped": "SHIPPED",
        "done": "DONE",
    }
    overrides = getattr(week, "overrides", None) or {}
    out = []
    for name in GAUGE_NAMES:
        pinned = overrides.get(name)
        out.append(
            {
                "label": labels[name],
                "value": _clamp(pinned) if pinned is not None else values[name],
                "pinned": pinned is not None,
            }
        )
    return out
