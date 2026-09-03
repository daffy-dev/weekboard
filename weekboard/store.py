"""Load and save week files. One JSON file per ISO week, atomic writes."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

from .config import Config, load_config
from .model import Week, now_iso, week_key


class Store:
    """Filesystem-backed collection of weeks."""

    def __init__(self, config: Config | None = None) -> None:
        self.config = config or load_config()
        self.root = self.config.weeks_path

    HISTORY_LIMIT = 30

    @property
    def history_root(self) -> Path:
        """Where pre-change snapshots live, so `wb undo` has something to restore."""
        return self.config.data_path / "history"

    def _snapshot(self, key: str) -> None:
        """Copy the current file aside before it is overwritten."""
        current = self.path_for(key)
        if not current.exists():
            return
        self.history_root.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        try:
            shutil.copy2(current, self.history_root / f"{key}__{stamp}.json")
        except OSError:
            return
        self._prune_history()

    def _prune_history(self) -> None:
        """Keep only the most recent snapshots."""
        entries = sorted(self.history_root.glob("*.json"), reverse=True)
        for stale in entries[self.HISTORY_LIMIT:]:
            stale.unlink(missing_ok=True)

    def history(self) -> list[Path]:
        """Snapshots, newest first."""
        if not self.history_root.is_dir():
            return []
        return sorted(self.history_root.glob("*.json"), reverse=True)

    def undo(self) -> str | None:
        """Restore the most recent snapshot. Returns the week key, or None."""
        entries = self.history()
        if not entries:
            return None
        newest = entries[0]
        key = newest.name.split("__")[0]
        target = self.path_for(key)
        self.root.mkdir(parents=True, exist_ok=True)
        # Pop the snapshot rather than pushing the current state back on, so
        # repeated undo walks backwards instead of toggling between two states.
        shutil.copy2(newest, target)
        newest.unlink(missing_ok=True)
        return key

    def path_for(self, key: str) -> Path:
        """JSON path for a week key."""
        return self.root / f"{key}.json"

    def exists(self, key: str) -> bool:
        """True if the week has been written before."""
        return self.path_for(key).exists()

    def keys(self) -> list[str]:
        """Every stored week key, oldest first."""
        if not self.root.is_dir():
            return []
        return sorted(p.stem for p in self.root.glob("*.json"))

    def load(self, key: str | None = None) -> Week:
        """Load a week, returning a fresh empty one if it does not exist yet."""
        key = key or week_key()
        path = self.path_for(key)
        if not path.exists():
            return self.seed(key)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise SystemExit(f"Cannot read {path}: {exc}") from exc
        raw.setdefault("key", key)
        return Week.from_dict(raw)

    def seed(self, key: str) -> Week:
        """Create a new week, inheriting soft settings from the previous one."""
        week = Week(key=key)
        previous = sorted(k for k in self.keys() if k < key)
        if previous:
            last = self.load(previous[-1])
            week.mission = list(last.mission)
            week.tagline = last.tagline
            week.headline_ja = last.headline_ja
            week.headline_en = last.headline_en
            week.overrides = dict(last.overrides)
        return week

    def save(self, week: Week) -> Path:
        """Write a week to disk atomically, keeping the previous version."""
        self._snapshot(week.key)
        week.updated = now_iso()
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.path_for(week.key)
        payload = json.dumps(week.to_dict(), indent=2, ensure_ascii=False) + "\n"
        handle, tmp_name = tempfile.mkstemp(dir=str(self.root), suffix=".tmp")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as fh:
                fh.write(payload)
            os.replace(tmp_name, path)
        except BaseException:
            Path(tmp_name).unlink(missing_ok=True)
            raise
        return path

    def all_weeks(self) -> list[Week]:
        """Load every stored week."""
        return [self.load(k) for k in self.keys()]
