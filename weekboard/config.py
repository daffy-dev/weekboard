"""Paths and user-tunable settings for weekboard."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parent
PROJECT_DIR = PKG_DIR.parent
ASSETS_DIR = PKG_DIR / "assets"
TEMPLATES_DIR = PKG_DIR / "templates"

DEFAULT_DATA_DIR = PROJECT_DIR / "data"
CONFIG_PATH = Path(
    os.environ.get("WEEKBOARD_CONFIG", DEFAULT_DATA_DIR / "config.json")
).expanduser()


@dataclass
class Config:
    """Everything the user might reasonably want to change."""

    data_dir: str = str(DEFAULT_DATA_DIR)
    output_dir: str = "~/Downloads/desktop_plans"
    width: int = 0                       # 0 = detect this Mac's largest display
    height: int = 0
    image_format: str = "png"            # "png" (sharpest) or "jpeg" (~6x faster)
    jpeg_quality: int = 94
    # Keep content clear of things that sit on top of the wallpaper — a menu bar,
    # SketchyBar, the Dock. Percentages of the render, so they hold at any size.
    inset_top_pct: float = 0.0
    inset_bottom_pct: float = 0.0
    inset_left_pct: float = 0.0
    inset_right_pct: float = 0.0
    scale: float = 1.0
    keep_renders: int = 3
    art: str = ""
    ascii_art: str = ""
    art_prompt: str = (
        "moody cyberpunk lo-fi bedroom at night, rain on the window, neon city "
        "skyline, cherry blossoms, developer at a desk seen from behind, dark "
        "blue and violet palette, cinematic, anime illustration"
    )
    accent: str = "#3ddc4a"
    git_repos: list[str] = field(default_factory=list)
    commit_days: int = 7                 # window for TERMINAL.LOG and SHIPPED
    commit_target: int = 15              # commits/week that fills the SHIPPED gauge
    git_author: str = ""                 # e.g. your email, to count only your commits
    commit_source: str = "auto"          # "auto" | "github" | "git"
    github_user: str = ""                # blank = ask `gh` who you are
    github_cache_seconds: int = 900
    backend: str = "cli"                 # "cli" (no key needed) or "api" (far cheaper)
    claude_bin: str = "claude"
    api_model: str = "claude-haiku-4-5"
    api_key_env: str = "ANTHROPIC_API_KEY"
    api_key_file: str = ""               # optional; this project's .env is read anyway
    api_max_tokens: int = 1024
    claude_model: str = ""
    auto_render: bool = True
    user_label: str = ""
    host_label: str = ""
    tools: list[str] = field(
        default_factory=lambda: [
            "VS CODE",
            "ZSH",
            "GIT",
            "NOTION",
            "DOCKER",
            "FIGMA",
            "COFFEE",
        ]
    )

    @property
    def data_path(self) -> Path:
        """Directory holding the week JSON files."""
        return Path(self.data_dir).expanduser()

    @property
    def weeks_path(self) -> Path:
        """Directory holding one JSON file per week."""
        return self.data_path / "weeks"

    @property
    def output_path(self) -> Path:
        """Folder the wallpaper watcher is watching."""
        return Path(self.output_dir).expanduser()

    @property
    def github_cache(self) -> Path:
        """Where recent GitHub activity is remembered between renders."""
        return self.data_path / ".github.json"

    @property
    def display_cache(self) -> Path:
        """Where the detected display size is remembered."""
        return self.data_path / ".display.json"

    @property
    def stats_history_cache(self) -> Path:
        """Recent CPU/RAM/disk/network readings, so the footer's trend
        sparklines plot real history instead of decoration."""
        return self.data_path / ".stats_history.json"

    def resolve_size(self) -> tuple[int, int]:
        """Render size: whatever the config pins, else this machine's display."""
        if self.width and self.height:
            return self.width, self.height
        from .display import detect

        return detect(self.display_cache)

    @property
    def art_path(self) -> Path:
        """Background artwork used in the dashboard."""
        if self.art:
            return Path(self.art).expanduser()
        return ASSETS_DIR / "art_default.jpg"


def load_config() -> Config:
    """Read config.json, falling back to defaults for anything missing.

    A config that fails to parse falls back to every default silently — no
    accent, tools, git_repos, or anything else you'd set, with no sign why.
    That's a bad surprise, so this warns on stderr instead of just eating it;
    every command still runs, since a wallpaper board shouldn't refuse to
    draw over a bad config file.
    """
    if CONFIG_PATH.exists():
        try:
            raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            print(
                f"weekboard: {CONFIG_PATH} is not valid JSON ({exc}) — "
                f"falling back to defaults for everything. Your settings are "
                f"still on disk; fix the file (or `wb config --edit`) and "
                f"they'll be picked up again.",
                file=sys.stderr,
            )
            raw = {}
        known = {k: v for k, v in raw.items() if k in Config.__annotations__}
        return Config(**known)
    return Config()


def save_config(config: Config) -> None:
    """Persist config.json."""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(
        json.dumps(asdict(config), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
