"""Full-screen Textual board: arrow keys to move, space to check, a to add."""

from __future__ import annotations

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Footer, Header, Input, Label, ListItem, ListView, Static

from .model import parse_week_key, shift_week, week_key
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
        Binding("q", "quit", "quit"),
    ]

    def __init__(self, key: str | None = None) -> None:
        super().__init__()
        self.store = Store()
        self.key = key or week_key()
        self.week = self.store.load(self.key)
        # Cheap placeholder until the real (network-touching) stats land off-thread.
        self.sys_stats: dict = {"commits": [], "commit_count": 0}

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

    def refresh_board(self, keep_index: int | None = None) -> None:
        """Reload the week and repaint every panel."""
        self.week = self.store.load(self.key)
        listing = self.query_one("#tasks", ListView)
        index = keep_index if keep_index is not None else listing.index
        listing.clear()
        for number, task in enumerate(self.week.tasks, start=1):
            box = "[✓]" if task.done else "[ ]"
            style = "done" if task.done else ("high" if task.priority == "high" else "open")
            tags = f"  #{' #'.join(task.tags)}" if task.tags else ""
            listing.append(ListItem(Label(f"{number:02d} {box} {task.text}{tags}", classes=style)))
        if self.week.tasks:
            listing.index = min(index or 0, len(self.week.tasks) - 1)

        marker = "" if self.week.is_current else "   (not this week)"
        self.query_one("#title", Static).update(f"WEEK {self.week.number:02d}{marker}")
        self.query_one("#range", Static).update(f"// {self.week.date_range}")

        mission = "\n".join(self.week.mission) + f"\n\n{self.week.tagline}"
        self.query_one("#mission", Static).update(f"// MISSION\n\n{mission}\n")
        from . import metrics

        computed = metrics.compute(self.week, self.store, self.sys_stats, self.store.config)
        gauges = "\n".join(
            f"{g['label']:<11}{'█' * (g['value'] // 10)}{'░' * (10 - g['value'] // 10)} "
            f"{g['value']:>3}%{'*' if g['pinned'] else ''}"
            for g in computed
        )
        self.query_one("#gauges", Static).update(f"\n// STATUS\n\n{gauges}\n")
        self.query_one("#quote", Static).update(
            f'\n// QUOTE\n\n"{self.week.quote_text}"\n— {self.week.quote_author}'
        )

        done, total = len(self.week.done_tasks), len(self.week.tasks)
        filled = int(self.week.progress * 40)
        self.query_one("#bar", Static).update(
            f" {'█' * filled}{'░' * (40 - filled)}  {done}/{total}  {int(self.week.progress * 100)}%"
        )

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
        """Store freshly collected stats and repaint (must run on the UI thread)."""
        self.sys_stats = sys_stats
        self.refresh_board(self.query_one("#tasks", ListView).index)

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
        """The highlighted task, or None."""
        index = self.query_one("#tasks", ListView).index
        if index is None or not self.week.tasks:
            return None
        return self.week.tasks[index]

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

    def action_delete(self) -> None:
        """Delete the highlighted task."""
        task = self.current
        if task is None:
            return
        index = self.query_one("#tasks", ListView).index
        self.week.remove(task.id)
        self.week.renumber()
        self.save(max(0, (index or 1) - 1))

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
