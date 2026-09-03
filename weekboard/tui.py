"""Full-screen Textual board: arrow keys to move, space to check, a to add."""

from __future__ import annotations

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Footer, Header, Input, Label, ListItem, ListView, Static

from .model import PRIORITIES, parse_week_key, shift_week, week_key
from .store import Store

CSS = """
Screen { background: #040806; }
#head { height: 3; padding: 0 1; }
#title { color: #eef7f0; text-style: bold; }
#range { color: #3ddc4a; }
#body { height: 1fr; }
#tasks { width: 1fr; border: round #1c3a2c; background: #071310; }
#side { width: 34; border: round #1c3a2c; background: #071310; padding: 1; }
ListView { background: #071310; }
ListItem { padding: 0 1; background: #071310; border-left: thick transparent; }
ListItem.-highlight { background: #1e5030; border-left: thick #3ddc4a; }
.done { color: #3f6a55; text-style: strike; }
.open { color: #dcefe2; }
.high { color: #ffffff; text-style: bold; }
.cap { color: #3ddc4a; text-style: bold; }
.dim { color: #4d6b5c; }
#bar { height: 1; color: #3ddc4a; }
#status { height: 1; color: #4d6b5c; padding: 0 1; }
AddModal { align: center middle; }
#addbox { width: 70; height: auto; border: round #3ddc4a; background: #071310; padding: 1 2; }
HelpModal { align: center middle; }
#helpbox { width: 60; height: auto; border: round #3ddc4a; background: #071310; padding: 1 2; }
#helptext { color: #dcefe2; }
"""


class AddModal(ModalScreen[str]):
    """Prompt for a new task."""

    BINDINGS = [Binding("escape", "dismiss_none", "cancel")]

    def __init__(self, prompt: str = "new task", initial: str = "") -> None:
        super().__init__()
        self.prompt = prompt
        self.initial = initial

    def compose(self) -> ComposeResult:
        """Build the modal."""
        with Vertical(id="addbox"):
            yield Label(f"// {self.prompt.upper()}", classes="cap")
            yield Input(value=self.initial, placeholder="type and press enter")

    def on_mount(self) -> None:
        """Focus the input."""
        self.query_one(Input).focus()

    @on(Input.Submitted)
    def submit(self, event: Input.Submitted) -> None:
        """Return the typed value."""
        self.dismiss(event.value.strip())

    def action_dismiss_none(self) -> None:
        """Cancel."""
        self.dismiss("")


class HelpModal(ModalScreen[None]):
    """List every keybinding, read live from Board.BINDINGS so it can't drift out of sync."""

    BINDINGS = [
        Binding("escape", "close", "close"),
        Binding("question_mark", "close", "close", key_display="?"),
    ]

    def compose(self) -> ComposeResult:
        """Build the modal."""
        rows = "\n".join(f"{b.key:<14} {b.description}" for b in self.app.BINDINGS)
        with Vertical(id="helpbox"):
            yield Label("// KEYBINDINGS", classes="cap")
            yield Static(rows, id="helptext")

    def action_close(self) -> None:
        """Dismiss the overlay."""
        self.dismiss(None)


class Board(App):
    """Terminal view of one week."""

    CSS = CSS
    BINDINGS = [
        Binding("space", "toggle", "check"),
        Binding("a", "add", "add"),
        Binding("e", "edit", "edit"),
        Binding("d", "delete", "delete"),
        Binding("m", "move_next", "→ next week"),
        Binding("left,h", "prev_week", "prev week"),
        Binding("right,l", "next_week", "next week"),
        Binding("t", "today", "this week"),
        Binding("r", "render", "render"),
        Binding("i", "ask", "ask AI"),
        Binding("u", "undo", "undo"),
        Binding("p", "cycle_priority", "priority"),
        Binding("number_sign", "edit_tags", "edit tags", key_display="#"),
        Binding("slash", "search", "search", key_display="/"),
        Binding("question_mark", "help", "help", key_display="?"),
        Binding("q", "quit", "quit"),
    ]

    def __init__(self, key: str | None = None) -> None:
        super().__init__()
        self.store = Store()
        self.key = key or week_key()
        self.week = self.store.load(self.key)
        # Cheap placeholder until the real (network-touching) stats land off-thread.
        self.sys_stats: dict = {"commits": [], "commit_count": 0}
        self.filter_query: str = ""

    def compose(self) -> ComposeResult:
        """Build the layout."""
        yield Header(show_clock=True)
        with Vertical(id="head"):
            yield Static("", id="title")
            yield Static("", id="range")
        with Horizontal(id="body"):
            yield ListView(id="tasks")
            with VerticalScroll(id="side"):
                yield Static("", id="mission")
                yield Static("", id="gauges")
                yield Static("", id="quote")
        yield Static("", id="bar")
        yield Static("", id="status")
        yield Footer()

    def on_mount(self) -> None:
        """First paint."""
        self.refresh_board()
        self.refresh_stats()

    # ---------- painting ----------

    def visible_tasks(self) -> list:
        """Tasks shown in the list right now — every task, or the filtered subset."""
        if not self.filter_query:
            return self.week.tasks
        query = self.filter_query.lower()
        return [
            task
            for task in self.week.tasks
            if query in task.text.lower() or any(query in tag.lower() for tag in task.tags)
        ]

    def refresh_board(self, keep_index: int | None = None) -> None:
        """Reload the week and repaint every panel."""
        self.week = self.store.load(self.key)
        listing = self.query_one("#tasks", ListView)
        index = keep_index if keep_index is not None else listing.index
        listing.clear()
        visible = self.visible_tasks()
        for task in visible:
            box = "[✓]" if task.done else "[ ]"
            style = "done" if task.done else ("high" if task.priority == "high" else "open")
            tags = f"  #{' #'.join(task.tags)}" if task.tags else ""
            listing.append(ListItem(Label(f"{task.id:02d} {box} {task.text}{tags}", classes=style)))
        if visible:
            listing.index = min(index or 0, len(visible) - 1)

        marker = "" if self.week.is_current else "   (not this week)"
        filter_marker = f'   [filter: "{self.filter_query}"]' if self.filter_query else ""
        self.query_one("#title", Static).update(f"WEEK {self.week.number:02d}{marker}{filter_marker}")
        self.query_one("#range", Static).update(f"// {self.week.date_range}")

        mission = "\n".join(self.week.mission) + f"\n\n{self.week.tagline}"
        self.query_one("#mission", Static).update(f"// MISSION\n\n{mission}\n")
        self._repaint_gauges()
        self.query_one("#quote", Static).update(
            f'\n// QUOTE\n\n"{self.week.quote_text}"\n— {self.week.quote_author}'
        )

        done, total = len(self.week.done_tasks), len(self.week.tasks)
        filled = int(self.week.progress * 40)
        self.query_one("#bar", Static).update(
            f" {'█' * filled}{'░' * (40 - filled)}  {done}/{total}  {int(self.week.progress * 100)}%"
        )

    def _repaint_gauges(self) -> None:
        """Redraw just the STATUS panel from the current week + sys_stats.

        Split out of refresh_board() so the background stats worker can
        update FOCUS/MOMENTUM/SHIPPED/DONE without tearing down and
        rebuilding the whole task ListView just to change four numbers.
        """
        from . import metrics

        computed = metrics.compute(self.week, self.store, self.sys_stats, self.store.config)
        gauges = "\n".join(
            f"{g['label']:<11}{'█' * (g['value'] // 10)}{'░' * (10 - g['value'] // 10)} "
            f"{g['value']:>3}%{'*' if g['pinned'] else ''}"
            for g in computed
        )
        self.query_one("#gauges", Static).update(f"\n// STATUS\n\n{gauges}\n")

    def note(self, message: str) -> None:
        """Write a transient line to the status strip."""
        self.query_one("#status", Static).update(message)

    def save(self, keep_index: int | None = None) -> None:
        """Persist, repaint, and kick off a wallpaper render."""
        self.store.save(self.week)
        self.refresh_board(keep_index)
        self.rerender()
        self.refresh_stats()

    @work(thread=True, exclusive=True)
    def refresh_stats(self) -> None:
        """Re-collect CPU/commit telemetry off the UI thread and repaint the gauges.

        stats.collect() shells out to git/gh and deliberately sleeps ~0.1s to
        sample network throughput, so it must never run on the UI thread —
        that would stall every keypress that triggers a repaint.
        """
        from . import stats

        try:
            fresh = stats.collect(self.store.config)
        except Exception:  # pragma: no cover - best effort, keep the old numbers
            return
        self.call_from_thread(self._apply_stats, fresh)

    def _apply_stats(self, sys_stats: dict) -> None:
        """Store freshly collected stats and repaint just the gauges.

        Must run on the UI thread. Deliberately not a full refresh_board():
        this fires on its own timer/after every save, and a stats-only
        change has nothing to do with the task list — rebuilding it too
        would mean an unrelated background tick can flicker or steal the
        list's scroll position while you're navigating it.
        """
        self.sys_stats = sys_stats
        self._repaint_gauges()

    @work(thread=True, exclusive=True)
    def rerender(self) -> None:
        """Render the wallpaper off the UI thread."""
        try:
            from .render import render

            path = render(self.store.load(self.key), self.store.config, self.store)
            self.call_from_thread(self.note, f" → {path.name}")
        except Exception as exc:  # pragma: no cover - best effort
            self.call_from_thread(self.note, f" render failed: {exc}")

    # ---------- actions ----------

    @property
    def current(self):
        """The highlighted task, respecting an active filter, or None."""
        index = self.query_one("#tasks", ListView).index
        tasks = self.visible_tasks()
        if index is None or not tasks or index >= len(tasks):
            return None
        return tasks[index]

    def action_toggle(self) -> None:
        """Check or uncheck the highlighted task."""
        task = self.current
        if task is None:
            return
        task.mark(not task.done)
        self.save(self.query_one("#tasks", ListView).index)

    def action_add(self) -> None:
        """Prompt for a new task."""

        def done(text: str | None) -> None:
            if text:
                self.week.add(text)
                self.filter_query = ""
                self.save(len(self.week.tasks) - 1)

        self.push_screen(AddModal(f"add to week {self.week.number:02d}"), done)

    def action_edit(self) -> None:
        """Edit the highlighted task's text."""
        task = self.current
        if task is None:
            return
        index = self.query_one("#tasks", ListView).index

        def done(text: str | None) -> None:
            if text:
                task.text = text
                self.save(index)

        self.push_screen(AddModal("edit task", task.text), done)

    def action_cycle_priority(self) -> None:
        """Cycle the highlighted task's priority: low → normal → high → low."""
        task = self.current
        if task is None:
            return
        order = list(PRIORITIES)
        position = order.index(task.priority) if task.priority in order else -1
        task.priority = order[(position + 1) % len(order)]
        self.save(self.query_one("#tasks", ListView).index)

    def action_edit_tags(self) -> None:
        """Prompt for the highlighted task's tags, comma-separated."""
        task = self.current
        if task is None:
            return
        index = self.query_one("#tasks", ListView).index

        def done(text: str | None) -> None:
            if text:
                task.tags = [tag.strip() for tag in text.split(",") if tag.strip()]
                self.save(index)

        self.push_screen(AddModal("tags, comma-separated", ", ".join(task.tags)), done)

    def action_delete(self) -> None:
        """Delete the highlighted task, leaving an undo hint in the status line."""
        task = self.current
        if task is None:
            return
        index = self.query_one("#tasks", ListView).index
        text = task.text
        self.week.remove(task.id)
        self.week.renumber()
        self.save(max(0, (index or 1) - 1))
        self.note(f' deleted "{text}" — press u to undo')

    def action_move_next(self) -> None:
        """Push the highlighted task into next week."""
        task = self.current
        if task is None:
            return
        target = self.store.load(shift_week(self.key, 1))
        moved = target.add(task.text, priority=task.priority, tags=task.tags)
        moved.carried_from = self.key
        self.store.save(target)
        self.week.remove(task.id)
        self.week.renumber()
        self.save()
        self.note(f" → moved to {target.key}")

    def action_undo(self) -> None:
        """Restore the most recent snapshot, wherever it belongs in time.

        Store.undo() is global, not scoped to the week currently on screen — it
        always pops the single newest snapshot from ANY week's history. If that
        happens to be this week, repaint and re-render so the change is visible
        immediately; if it is some other week, say so rather than silently
        jumping the user there or pretending nothing happened.
        """
        restored_key = self.store.undo()
        if restored_key is None:
            self.note(" nothing to undo")
            return
        if restored_key == self.key:
            self.refresh_board()
            self.rerender()
            self.note(" undone")
        else:
            self.note(f" undid a change to {restored_key} (not this week)")

    def action_prev_week(self) -> None:
        """Go back one week."""
        self.key = shift_week(self.key, -1)
        self.refresh_board(0)

    def action_next_week(self) -> None:
        """Go forward one week."""
        self.key = shift_week(self.key, 1)
        self.refresh_board(0)

    def action_today(self) -> None:
        """Jump to the current week."""
        self.key = week_key()
        self.refresh_board(0)

    def action_render(self) -> None:
        """Force a wallpaper render."""
        self.note(" rendering…")
        self.rerender()

    def action_ask(self) -> None:
        """Send a line of natural language to the agent."""

        def done(text: str | None) -> None:
            if text:
                self.run_agent(text)

        self.push_screen(AddModal("ask the agent"), done)

    def action_search(self) -> None:
        """Prompt for a filter query; narrows the visible list to text/tag matches."""

        def done(text: str | None) -> None:
            self.filter_query = (text or "").strip()
            self.refresh_board(0)
            if self.filter_query:
                self.note(f' filtering: "{self.filter_query}"')
            else:
                self.note(" showing all tasks")

        self.push_screen(AddModal("filter (blank to show all)", self.filter_query), done)

    def action_help(self) -> None:
        """Show the keybinding overlay."""
        self.push_screen(HelpModal())

    @work(thread=True, exclusive=True)
    def run_agent(self, text: str) -> None:
        """Call the model and apply whatever it proposes."""
        from . import agent as agent_mod

        try:
            self.call_from_thread(self.note, " thinking…")
            plan = agent_mod.capture(self.store, self.store.config, text)
            messages = agent_mod.apply_ops(self.store, plan["ops"])
            summary = plan.get("say") or f"{len(messages)} change(s)"
            self.call_from_thread(self.note, f" {summary}")
            self.call_from_thread(self.refresh_board)
        except Exception as exc:
            self.call_from_thread(self.note, f" agent: {exc}")
            return
        self.rerender()


def run(key: str | None = None) -> None:
    """Launch the TUI."""
    Board(parse_week_key(key) if key else None).run()
