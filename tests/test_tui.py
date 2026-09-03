"""The Textual board — mostly a smoke test.

There's no snapshot testing here, just: does it mount without crashing, and
do the actions that mutate state (toggle, add, delete, ...) survive a full
round trip through Store. The gauges panel is the one thing worth pinning
down explicitly, since it broke silently for a long time — it read a
`week.status.*` shape that the model stopped having, and nothing caught it
because nothing here ever mounted the app.
"""

from __future__ import annotations

import pytest

from weekboard.config import Config
from weekboard.store import Store
from weekboard.tui import Board


@pytest.fixture()
def store(tmp_path, monkeypatch):
    config = Config(data_dir=str(tmp_path), output_dir=str(tmp_path / "out"))
    # Board() constructs its own bare Store() with no way to inject a config,
    # so point the module's load_config() at this fixture's config instead.
    monkeypatch.setattr("weekboard.store.load_config", lambda: config)
    return Store(config)


@pytest.mark.asyncio
async def test_mounts_and_paints_gauges_without_crashing(store):
    week = store.load("2026-W36")
    week.add("Task one", priority="high")
    store.save(week)

    app = Board("2026-W36")
    async with app.run_test() as pilot:
        await pilot.pause()
        gauges = app.query_one("#gauges").render()
        text = str(gauges)
        for label in ("FOCUS", "MOMENTUM", "SHIPPED", "DONE"):
            assert label in text


@pytest.mark.asyncio
async def test_toggle_persists(store):
    week = store.load("2026-W36")
    week.add("Task one")
    store.save(week)

    app = Board("2026-W36")
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("space")
        await pilot.pause()

    assert store.load("2026-W36").tasks[0].done


@pytest.mark.asyncio
async def test_selected_row_is_visibly_highlighted(store):
    """Regression guard: the CSS once targeted `.--highlight` (double dash),
    which Textual's ListItem never sets (it's `-highlight`, single dash) — so
    the rule silently matched nothing and the cursor was invisible. Check the
    *resolved* style, not just that a CSS string is present, so a similar
    selector typo can't slip back in unnoticed.
    """
    from textual.widgets import ListView

    week = store.load("2026-W36")
    week.add("a")
    week.add("b")
    store.save(week)

    app = Board("2026-W36")
    async with app.run_test() as pilot:
        await pilot.pause()
        listing = app.query_one("#tasks", ListView)
        highlighted = listing.highlighted_child
        assert highlighted is not None
        other = next(c for c in listing.children if c is not highlighted)
        assert highlighted.styles.background != other.styles.background


@pytest.mark.asyncio
async def test_background_stats_refresh_does_not_rebuild_the_task_list(store):
    """_apply_stats() must repaint only the gauges, not tear down the ListView.

    Rebuilding the whole list on a background stats tick (which fires after
    every save and could in principle fire on a timer) would flicker or, on
    an unlucky race, disturb the list while someone is navigating it — for a
    panel that only ever displays FOCUS/MOMENTUM/SHIPPED/DONE numbers.
    """
    from textual.widgets import ListView

    week = store.load("2026-W36")
    week.add("a")
    week.add("b")
    week.add("c")
    store.save(week)

    app = Board("2026-W36")
    async with app.run_test() as pilot:
        await pilot.pause()
        listing = app.query_one("#tasks", ListView)
        await pilot.press("down")
        await pilot.pause()
        before_index = listing.index
        before_ids = [id(child) for child in listing.children]

        app._apply_stats({"commits": [], "commit_count": 3})
        await pilot.pause()

        assert listing.index == before_index
        assert [id(child) for child in listing.children] == before_ids


@pytest.mark.asyncio
async def test_survives_background_stats_refresh(store):
    """The gauges repaint once the off-thread stats worker lands; must not crash."""
    import asyncio

    week = store.load("2026-W36")
    week.add("Task one")
    store.save(week)

    app = Board("2026-W36")
    async with app.run_test() as pilot:
        await pilot.pause()
        await asyncio.sleep(0.3)
        await pilot.pause()
        # Still alive and still showing real gauge labels, not a traceback.
        text = str(app.query_one("#gauges").render())
        assert "FOCUS" in text


# ---------- Phase A: undo, delete hint, help overlay ----------


@pytest.mark.asyncio
async def test_delete_then_undo_restores_the_task(store):
    week = store.load("2026-W36")
    week.add("Task one")
    store.save(week)

    app = Board("2026-W36")
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("d")
        await pilot.pause()
        assert store.load("2026-W36").tasks == []
        await pilot.press("u")
        await pilot.pause()
        assert [t.text for t in store.load("2026-W36").tasks] == ["Task one"]


@pytest.mark.asyncio
async def test_undo_with_nothing_to_undo_does_not_crash(store):
    app = Board("2026-W36")
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("u")
        await pilot.pause()
        assert "nothing to undo" in str(app.query_one("#status").render())


@pytest.mark.asyncio
async def test_delete_shows_the_deleted_task_text_in_the_status_hint(store):
    week = store.load("2026-W36")
    week.add("Call Harry")
    store.save(week)

    app = Board("2026-W36")
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("d")
        await pilot.pause()
        assert "Call Harry" in str(app.query_one("#status").render())


@pytest.mark.asyncio
async def test_help_overlay_lists_bindings_and_can_be_closed(store):
    from textual.css.query import NoMatches

    app = Board("2026-W36")
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("?")
        await pilot.pause()
        text = str(app.screen.query_one("#helptext").render())
        assert "undo" in text
        await pilot.press("escape")
        await pilot.pause()
        with pytest.raises(NoMatches):
            app.query_one("#helptext")


# ---------- Phase B: priority cycling, tag editing, search/filter ----------


@pytest.mark.asyncio
async def test_priority_cycles_low_normal_high(store):
    week = store.load("2026-W36")
    week.add("Task one")  # default priority "normal"
    store.save(week)

    app = Board("2026-W36")
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("p")
        await pilot.pause()
        assert store.load("2026-W36").tasks[0].priority == "high"
        await pilot.press("p")
        await pilot.pause()
        assert store.load("2026-W36").tasks[0].priority == "low"


@pytest.mark.asyncio
async def test_tag_edit_prefills_and_parses_comma_separated_tags(store):
    from textual.widgets import Input

    week = store.load("2026-W36")
    week.add("Task one", tags=["old"])
    store.save(week)

    app = Board("2026-W36")
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("#")
        await pilot.pause()
        assert app.screen.query_one(Input).value == "old"
        app.screen.query_one(Input).value = "work, urgent"
        await pilot.press("enter")
        await pilot.pause()

    assert store.load("2026-W36").tasks[0].tags == ["work", "urgent"]


@pytest.mark.asyncio
async def test_search_filters_the_list_and_clearing_shows_all(store):
    from textual.widgets import Input, ListView

    week = store.load("2026-W36")
    week.add("Call Harry")
    week.add("Buy milk")
    store.save(week)

    app = Board("2026-W36")
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("/")
        await pilot.pause()
        app.screen.query_one(Input).value = "harry"
        await pilot.press("enter")
        await pilot.pause()
        assert len(app.query_one("#tasks", ListView).children) == 1

        await pilot.press("/")
        await pilot.pause()
        app.screen.query_one(Input).value = ""
        await pilot.press("enter")
        await pilot.pause()
        assert len(app.query_one("#tasks", ListView).children) == 2


@pytest.mark.asyncio
async def test_filter_does_not_change_the_progress_bar(store):
    from textual.widgets import Input

    week = store.load("2026-W36")
    week.add("Call Harry").mark(True)
    week.add("Buy milk")
    store.save(week)

    app = Board("2026-W36")
    async with app.run_test() as pilot:
        await pilot.pause()
        before = str(app.query_one("#bar").render())
        await pilot.press("/")
        await pilot.pause()
        app.screen.query_one(Input).value = "harry"
        await pilot.press("enter")
        await pilot.pause()
        after = str(app.query_one("#bar").render())
        assert before == after
        assert "1/2" in after
