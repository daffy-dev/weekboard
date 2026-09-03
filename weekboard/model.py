"""Data model for weekboard: tasks grouped into ISO weeks."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta

ISO_WEEK_RE = re.compile(r"^(\d{4})-?W(\d{1,2})$", re.IGNORECASE)

PRIORITIES = ("low", "normal", "high")


def now_iso() -> str:
    """Current local time as an ISO-8601 string."""
    return datetime.now().isoformat(timespec="seconds")


def week_key(day: date | None = None) -> str:
    """Return the ISO week key (e.g. 2026-W36) containing day."""
    day = day or date.today()
    year, week, _ = day.isocalendar()
    return f"{year}-W{week:02d}"


def parse_week_key(value: str | int | None, base: date | None = None) -> str:
    """Normalise a user-supplied week reference into an ISO week key.

    Accepts: None (current week), 37, "37", "2026-W37", "2026W37",
    "next", "prev"/"last", "+2", "-1".
    """
    base = base or date.today()
    if value is None:
        return week_key(base)
    text = str(value).strip().lower()
    if text in ("", "now", "this", "current"):
        return week_key(base)
    if text in ("next", "+1"):
        return week_key(base + timedelta(weeks=1))
    if text in ("prev", "previous", "last", "-1"):
        return week_key(base - timedelta(weeks=1))
    if re.fullmatch(r"[+-]\d+", text):
        return week_key(base + timedelta(weeks=int(text)))
    match = ISO_WEEK_RE.match(text.replace(" ", ""))
    if match:
        year, week = int(match.group(1)), int(match.group(2))
        total = weeks_in_year(year)
        if not 1 <= week <= total:
            raise ValueError(f"{year} has {total} ISO weeks, so week {week} does not exist.")
        return f"{year}-W{week:02d}"
    if text.isdigit():
        week, year = int(text), base.isocalendar().year
        total = weeks_in_year(year)
        if not 1 <= week <= total:
            raise ValueError(f"{year} has {total} ISO weeks, so week {week} does not exist.")
        return f"{year}-W{week:02d}"
    raise ValueError(f"Cannot understand week reference: {value!r}")


def weeks_in_year(year: int) -> int:
    """52 or 53 — how many ISO weeks that year actually has."""
    return date(year, 12, 28).isocalendar().week


def week_bounds(key: str) -> tuple[date, date]:
    """Return (monday, sunday) for an ISO week key."""
    match = ISO_WEEK_RE.match(key)
    if not match:
        raise ValueError(f"Bad week key: {key}")
    year, week = int(match.group(1)), int(match.group(2))
    total = weeks_in_year(year)
    if not 1 <= week <= total:
        raise ValueError(f"{year} has {total} ISO weeks, so week {week} does not exist.")
    monday = date.fromisocalendar(year, week, 1)
    return monday, monday + timedelta(days=6)


def shift_week(key: str, weeks: int) -> str:
    """Return the week key `weeks` away from key."""
    monday, _ = week_bounds(key)
    return week_key(monday + timedelta(weeks=weeks))


def week_number(key: str) -> int:
    """Return just the week number from a key."""
    return int(ISO_WEEK_RE.match(key).group(2))


@dataclass
class Task:
    """A single to-do item belonging to one week."""

    id: int
    text: str
    done: bool = False
    priority: str = "normal"
    tags: list[str] = field(default_factory=list)
    created: str = field(default_factory=now_iso)
    completed: str | None = None
    carried_from: str | None = None

    @classmethod
    def from_dict(cls, raw: dict) -> "Task":
        """Build a Task from stored JSON, ignoring unknown keys."""
        known = {k: v for k, v in raw.items() if k in cls.__annotations__}
        known.setdefault("tags", [])
        return cls(**known)

    def to_dict(self) -> dict:
        """Serialise for JSON storage."""
        return asdict(self)

    def mark(self, done: bool) -> None:
        """Set completion state and stamp the completion time."""
        self.done = done
        self.completed = now_iso() if done else None


DEFAULT_MISSION = [
    "Ship things. Solve problems.",
    "Build value. Help people.",
    "Create freedom.",
]


@dataclass
class Week:
    """All state for one ISO week."""

    key: str
    tasks: list[Task] = field(default_factory=list)
    mission: list[str] = field(default_factory=lambda: list(DEFAULT_MISSION))
    tagline: str = "Level up."
    quote_text: str = "The best way to predict the future is to build it."
    quote_author: str = "Alan Kay"
    headline_ja: str = "改善は毎日の積み重ねだ。"
    headline_en: str = "KAIZEN IS DAILY."
    playlist_title: str = "Lo-fi Beats / Japanese City Pop"
    playlist_note: str = "To keep the mind in flow state."
    overrides: dict = field(default_factory=dict)
    updated: str = field(default_factory=now_iso)

    @property
    def number(self) -> int:
        """ISO week number."""
        return week_number(self.key)

    @property
    def bounds(self) -> tuple[date, date]:
        """Monday and Sunday of this week."""
        return week_bounds(self.key)

    @property
    def date_range(self) -> str:
        """Human date range, e.g. '31 AUGUST - 6 SEPTEMBER 2026'."""
        start, end = self.bounds
        if start.year != end.year:
            return f"{start.day} {start:%B %Y} - {end.day} {end:%B %Y}".upper()
        if start.month == end.month:
            return f"{start.day} - {end.day} {end:%B %Y}".upper()
        return f"{start.day} {start:%B} - {end.day} {end:%B %Y}".upper()

    @property
    def is_current(self) -> bool:
        """True if today falls inside this week."""
        return self.key == week_key()

    def next_id(self) -> int:
        """Smallest unused task id."""
        used = {task.id for task in self.tasks}
        candidate = 1
        while candidate in used:
            candidate += 1
        return candidate

    def add(self, text: str, **kwargs) -> Task:
        """Append a new task and return it."""
        task = Task(id=self.next_id(), text=text.strip(), **kwargs)
        self.tasks.append(task)
        return task

    def get(self, task_id: int) -> Task:
        """Look up a task by id."""
        for task in self.tasks:
            if task.id == task_id:
                return task
        raise KeyError(f"No task {task_id} in {self.key}")

    def remove(self, task_id: int) -> Task:
        """Delete and return a task."""
        task = self.get(task_id)
        self.tasks.remove(task)
        return task

    def renumber(self) -> None:
        """Reassign ids 1..n in list order."""
        for index, task in enumerate(self.tasks, start=1):
            task.id = index

    @property
    def open_tasks(self) -> list[Task]:
        """Tasks still to do."""
        return [t for t in self.tasks if not t.done]

    @property
    def done_tasks(self) -> list[Task]:
        """Completed tasks."""
        return [t for t in self.tasks if t.done]

    @property
    def progress(self) -> float:
        """Fraction complete, 0.0-1.0."""
        if not self.tasks:
            return 0.0
        return len(self.done_tasks) / len(self.tasks)

    def completions_by_day(self) -> list[int]:
        """Count of tasks completed on each day Mon..Sun of this week."""
        start, _ = self.bounds
        counts = [0] * 7
        for task in self.done_tasks:
            if not task.completed:
                continue
            try:
                day = datetime.fromisoformat(task.completed).date()
            except ValueError:
                continue
            offset = (day - start).days
            if 0 <= offset < 7:
                counts[offset] += 1
        return counts

    @classmethod
    def from_dict(cls, raw: dict) -> "Week":
        """Build a Week from stored JSON."""
        week = cls(key=raw["key"])
        week.tasks = [Task.from_dict(t) for t in raw.get("tasks", [])]
        week.mission = raw.get("mission") or list(DEFAULT_MISSION)
        week.tagline = raw.get("tagline", week.tagline)
        week.quote_text = raw.get("quote_text", week.quote_text)
        week.quote_author = raw.get("quote_author", week.quote_author)
        week.headline_ja = raw.get("headline_ja", week.headline_ja)
        week.headline_en = raw.get("headline_en", week.headline_en)
        week.playlist_title = raw.get("playlist_title", week.playlist_title)
        week.playlist_note = raw.get("playlist_note", week.playlist_note)
        week.overrides = {
            k: int(v) for k, v in (raw.get("overrides") or {}).items() if v is not None
        }
        week.updated = raw.get("updated", now_iso())
        return week

    def to_dict(self) -> dict:
        """Serialise for JSON storage."""
        return {
            "key": self.key,
            "start": self.bounds[0].isoformat(),
            "end": self.bounds[1].isoformat(),
            "mission": self.mission,
            "tagline": self.tagline,
            "quote_text": self.quote_text,
            "quote_author": self.quote_author,
            "headline_ja": self.headline_ja,
            "headline_en": self.headline_en,
            "playlist_title": self.playlist_title,
            "playlist_note": self.playlist_note,
            "overrides": self.overrides,
            "updated": self.updated,
            "tasks": [t.to_dict() for t in self.tasks],
        }
