"""Turn a Week into a wallpaper PNG via Jinja2 -> HTML -> headless Chromium."""

from __future__ import annotations

import os
import shutil
import tempfile
import time
from datetime import date
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

from . import metrics, stats
from .config import ASSETS_DIR, TEMPLATES_DIR, Config, load_config
from .model import Week

DAY_LABELS = ["M", "T", "W", "T", "F", "S", "S"]

DEFAULT_ASCII = "  ( ^_^ )/\n  // no ascii.txt found"

# Layout constants that mirror the stylesheet, so sizing can be computed
# from real geometry instead of guessed at.
BOARD_PADDING_U = 1.1
COLUMN_GAP_U = 0.85
PANEL_PADDING_U = 1.05
BODY_GAP_U = 1.0
LEFT_COLUMN = 0.515
RIGHT_COLUMN = 0.155

# Share of the reminder window's body the art may occupy.
ASCII_SHARE = 0.38
BRAILLE_SHARE = 0.52          # braille art is a picture; give it more room
# Fraction of board height the art may take before it starves the photo above.
ASCII_MAX_HEIGHT = 0.17
BRAILLE_MAX_HEIGHT = 0.27
# A glyph's advance as a fraction of its font size.
MONO_ADVANCE = 0.6
BRAILLE_ADVANCE = 0.55
# Braille packs 2x4 dots per cell, so the lines must sit flush.
BRAILLE_LINE_HEIGHT = 1.0
ASCII_LINE_HEIGHT = 1.05


def is_braille(art: str) -> bool:
    """True if the art is drawn with Unicode braille rather than ASCII."""
    glyphs = [c for c in art if not c.isspace()]
    if not glyphs:
        return False
    dots = sum(1 for c in glyphs if 0x2800 <= ord(c) <= 0x28FF)
    return dots / len(glyphs) > 0.5

DEFAULT_LOOP_CALLS = ["focus", "build", "ship", "help_people", "make_money", "create_freedom"]
DEFAULT_LOOP_COMMENTS = ["You are the developer of your life.", "Make it epic."]
DEFAULT_FOCUS_WORDS = ["FOCUS", "BUILD", "DELIVER", "REPEAT"]

ICON_SVGS = {
    "DEFAULT": '<svg viewBox="0 0 24 24"><path d="M12 3 21 12 12 21 3 12Z"/></svg>',
    "VS CODE": '<svg viewBox="0 0 24 24"><path d="M9 8 5 12l4 4M15 8l4 4-4 4M13 5l-2 14"/></svg>',
    "ZSH": '<svg viewBox="0 0 24 24"><rect x="2.5" y="4" width="19" height="16" rx="1.5"/>'
           '<path d="M6.5 10 9 12.5 6.5 15M11.5 15.5h6"/></svg>',
    "TERMINAL": '<svg viewBox="0 0 24 24"><rect x="2.5" y="4" width="19" height="16" rx="1.5"/>'
                '<path d="M6.5 10 9 12.5 6.5 15M11.5 15.5h6"/></svg>',
    "GIT": '<svg viewBox="0 0 24 24"><circle cx="6.5" cy="5.5" r="2.5"/><circle cx="6.5" cy="18.5" r="2.5"/>'
           '<circle cx="17.5" cy="9" r="2.5"/><path d="M6.5 8v8M17.5 11.5c0 4-4 3.5-6.5 5.5"/></svg>',
    "NOTION": '<svg viewBox="0 0 24 24"><rect x="3.5" y="3.5" width="17" height="17" rx="1.5"/>'
              '<path d="M9 16V8l6 8V8"/></svg>',
    "DOCKER": '<svg viewBox="0 0 24 24"><path d="M3 14h15v3a3 3 0 0 1-3 3H7a4 4 0 0 1-4-4Z"/>'
              '<path d="M6 11h3v3H6zM10 11h3v3h-3zM14 11h3v3h-3zM10 7.5h3v3h-3z"/>'
              '<path d="M18.5 12.5c1.5-1 3 0 3 0"/></svg>',
    "FIGMA": '<svg viewBox="0 0 24 24"><path d="M9 3h3v6H9a3 3 0 0 1 0-6ZM12 3h3a3 3 0 0 1 0 6h-3Z"/>'
             '<path d="M9 9h3v6H9a3 3 0 0 1 0-6ZM9 15h3v3a3 3 0 1 1-3-3Z"/><circle cx="15" cy="12" r="3"/></svg>',
    "COFFEE": '<svg viewBox="0 0 24 24"><path d="M4 9h13v6a4 4 0 0 1-4 4H8a4 4 0 0 1-4-4Z"/>'
              '<path d="M17 10.5h1.5a2.5 2.5 0 0 1 0 5H17"/><path d="M8 3v2.5M11.5 3v2.5"/></svg>',
    "CLAUDE": '<svg viewBox="0 0 24 24"><path d="M12 3v18M4.5 7.5l15 9M19.5 7.5l-15 9"/></svg>',
    "SLACK": '<svg viewBox="0 0 24 24"><path d="M9 3v10M15 11v10M3 15h10M11 9h10"/></svg>',
    "PYTHON": '<svg viewBox="0 0 24 24"><path d="M12 3c-3 0-4 1.2-4 3v2h8v1H6c-2 0-3 1.5-3 4s1 4 3 4h2v-3'
              'c0-2 1-3 3-3h4c2 0 3-1 3-3V6c0-1.8-1-3-4-3Z"/><circle cx="9.5" cy="6" r=".6"/></svg>',
    "LINEAR": '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M5 10l9 9M7.5 6.5 17.5 16.5"/></svg>',
    "MUSIC": '<svg viewBox="0 0 24 24"><path d="M9 18V6l11-2v12"/><circle cx="6.5" cy="18" r="2.5"/>'
             '<circle cx="17.5" cy="16" r="2.5"/></svg>',
    "DESIGN": '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 3a9 9 0 0 1 0 18Z"/></svg>',
    "SHIP": '<svg viewBox="0 0 24 24"><path d="M12 3 21 20H3Z"/><path d="M8 15h8"/></svg>',
    "CURSOR": '<svg viewBox="0 0 24 24"><path d="M5 3l14 8-6 1.5L10 19Z"/></svg>',
    "CHROME": '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="3.5"/>'
              '<path d="M12 8.5h9M8.9 13.7 4.4 21M15.1 13.7 10.6 21"/></svg>',
    "GITHUB": '<svg viewBox="0 0 24 24"><path d="M9 20c-4 1.2-4-2.2-5.5-2.8M15 21v-3.4c0-1 .3-1.7.8-2.2'
              '3-.3 5.2-1.4 5.2-5.6a4.3 4.3 0 0 0-1.2-3 4 4 0 0 0-.1-3s-1-.3-3.2 1.2a11 11 0 0 0-5.8 0'
              'C8.5 1.5 7.5 1.8 7.5 1.8a4 4 0 0 0-.1 3 4.3 4.3 0 0 0-1.2 3c0 4.2 2.2 5.3 5.2 5.6'
              '-.4.4-.7.9-.8 1.7V21"/></svg>',
}


def _chart(week: Week) -> dict:
    """Bar chart of tasks completed per weekday."""
    counts = week.completions_by_day()
    peak = max(counts) or 1
    today_index = (date.today() - week.bounds[0]).days
    bars = []
    for index, count in enumerate(counts):
        bars.append(
            {
                "height": max(3, round(count / peak * 100)),
                "label": DAY_LABELS[index],
                "hot": count == peak and count > 0,
                "today": index == today_index,
            }
        )
    total = sum(counts)
    if total:
        caption = f"{total} SHIPPED THIS WEEK"
    else:
        caption = "1% BETTER EVERY DAY"
    return {"bars": bars, "caption": caption}


def _peek(week: Week, store) -> dict:
    """Right-rail panel: either what is queued next week, or this week's high-priority items."""
    from .model import shift_week

    nxt = shift_week(week.key, 1)
    if store.exists(nxt):
        upcoming = store.load(nxt)
        if upcoming.tasks:
            return {
                "title": f"WEEK {upcoming.number} QUEUE",
                "entries": [t.text for t in upcoming.tasks[:8]],
            }
    highs = [t.text for t in week.open_tasks if t.priority == "high"][:8]
    if highs:
        return {"title": "PRIORITY", "entries": highs}
    return {"title": "UP NEXT", "entries": [t.text for t in week.open_tasks[:8]]}


# Vertical units consumed by everything above and below the task rows
# (board padding, header block, panel chrome, bottom band, footer, gaps).
CHROME_UNITS = 39.8
MIN_ROW = 1.25
MAX_ROW = 5.5
# The plateau most weeks live on: for any count that leaves rows at least
# this tall, font size sits at MAX_TASK_SIZE rather than tracking row height.
# (row_h * TASK_SIZE_RATIO only starts to bite once row_h drops below
# MAX_TASK_SIZE / TASK_SIZE_RATIO, ~2.8u — comfortably past a typical week.)
MAX_TASK_SIZE = 1.18
MIN_TASK_SIZE = 0.62
TASK_SIZE_RATIO = 0.42


def _task_metrics(count: int, config: Config, unit: float) -> tuple[int, float, float, float]:
    """Choose column count, font size and row height so the list fills its panel.

    Everything is expressed in layout units, so this holds at any resolution.
    """
    available = max(12.0, config.height / unit - CHROME_UNITS)
    if count <= 0:
        return 1, MAX_TASK_SIZE, MAX_ROW, 0.4
    cols = 1
    if available / count < MIN_ROW * 1.75:
        cols = 2
    per_column = -(-count // cols)  # ceil
    row_h = min(MAX_ROW, max(MIN_ROW, available / per_column))
    # Font tracks row height only until the rows are comfortable, then stops.
    size = min(MAX_TASK_SIZE, max(MIN_TASK_SIZE, row_h * TASK_SIZE_RATIO))
    if cols == 2:
        size = min(size, MAX_TASK_SIZE * 0.88)
    # CSS columns cannot flex, so multi-column mode fills its panel with padding.
    pad = max(0.12, (row_h - size * 1.45) / 2) if cols > 1 else 0.18
    return cols, round(size, 3), round(row_h, 3), round(pad, 3)



def _pct(value: float) -> float:
    """A percentage as a fraction, clamped so a typo can't blank the board."""
    return max(0.0, min(25.0, float(value or 0))) / 100.0


def _ascii_size(art: str, config: Config, unit: float) -> float:
    """Font size, in layout units, that makes the art fit its panel either way."""
    lines = [line for line in art.splitlines() if line.strip()]
    columns = max((len(line) for line in lines), default=1)
    rows = max(len(lines), 1)
    braille = is_braille(art)
    share = BRAILLE_SHARE if braille else ASCII_SHARE
    advance = BRAILLE_ADVANCE if braille else MONO_ADVANCE
    leading = BRAILLE_LINE_HEIGHT if braille else ASCII_LINE_HEIGHT
    ceiling = BRAILLE_MAX_HEIGHT if braille else ASCII_MAX_HEIGHT

    available_px = _art_panel_width(config, unit) * share
    by_width = available_px / columns / advance / unit
    by_height = (config.height * ceiling) / (rows * leading) / unit
    # 3% margin so a wide glyph never touches the panel edge.
    return round(max(0.18, min(1.1, by_width, by_height) * 0.97), 3)


def _art_panel_width(config: Config, unit: float) -> float:
    """Pixel width available inside the reminder window, mirroring the CSS."""
    inner = config.width - 2 * BOARD_PADDING_U * unit
    centre = inner - 2 * COLUMN_GAP_U * unit - (LEFT_COLUMN + RIGHT_COLUMN) * inner
    body = centre - 2 * PANEL_PADDING_U * unit - BODY_GAP_U * unit
    return max(unit * 10, body)


def build_html(week: Week, config: Config, store=None) -> str:
    """Render the dashboard template to an HTML string."""
    from .store import Store

    store = store or Store(config)
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html", "j2"]),
    )
    unit = config.width / 190.0  # base layout unit; 1920 wide -> ~10px

    cols, size, row_h, pad = _task_metrics(len(week.tasks), config, unit)

    ascii_path = Path(config.ascii_art).expanduser() if config.ascii_art else ASSETS_DIR / "ascii.txt"
    ascii_art = ascii_path.read_text(encoding="utf-8") if ascii_path.exists() else DEFAULT_ASCII
    ascii_size = _ascii_size(ascii_art, config, unit)

    sys_stats = stats.collect(config)
    terminal_lines = sys_stats["commits"] or [
        f"{len(week.done_tasks)} task(s) closed this week.",
        "Mission plan updated.",
        "Let's ship.",
    ]

    art = config.art_path
    art_uri = art.resolve().as_uri() if art.exists() else ""

    template = env.get_template("dashboard.html.j2")
    return template.render(
        week=week,
        width=config.width,
        height=config.height,
        unit=round(unit, 4),
        inset_top=round(config.height * _pct(config.inset_top_pct)),
        inset_bottom=round(config.height * _pct(config.inset_bottom_pct)),
        inset_left=round(config.width * _pct(config.inset_left_pct)),
        inset_right=round(config.width * _pct(config.inset_right_pct)),
        accent=config.accent,
        fonts=(ASSETS_DIR / "fonts").resolve().as_uri(),
        art=art_uri,
        chart=_chart(week),
        gauges=metrics.compute(week, store, sys_stats, config),
        peek=_peek(week, store),
        sys=sys_stats,
        audio_spark=sys_stats["audio_spark"],
        terminal_lines=terminal_lines[:6],
        focus_words=DEFAULT_FOCUS_WORDS,
        loop_calls=DEFAULT_LOOP_CALLS,
        loop_comments=DEFAULT_LOOP_COMMENTS,
        ascii_art=ascii_art,
        ascii_size=ascii_size,
        ascii_braille=is_braille(ascii_art),
        ascii_share=round((BRAILLE_SHARE if is_braille(ascii_art) else ASCII_SHARE) * 100, 1),
        ascii_leading=BRAILLE_LINE_HEIGHT if is_braille(ascii_art) else ASCII_LINE_HEIGHT,
        ascii_caption="やればできる",
        ascii_caption_en="(YOU CAN DO IT)",
        tools=[
            {"name": t, "svg": Markup(ICON_SVGS.get(t.upper(), ICON_SVGS["DEFAULT"]))}
            for t in config.tools[:7]
        ],
        playlist={"title": week.playlist_title, "note": week.playlist_note},
        task_cols=cols,
        task_size=size,
        task_row=row_h,
        task_pad=pad,
    )


def render(week: Week, config: Config | None = None, store=None, keep_html: bool = False) -> Path:
    """Render week to a PNG in the watched folder and prune old renders."""
    config = config or load_config()
    if not (config.width and config.height):
        config.width, config.height = config.resolve_size()
    html = build_html(week, config, store)

    out_dir = config.output_path
    out_dir.mkdir(parents=True, exist_ok=True)

    tmp_dir = Path(tempfile.mkdtemp(prefix="weekboard-"))
    html_path = tmp_dir / "board.html"
    html_path.write_text(html, encoding="utf-8")

    stamp = time.strftime("%Y%m%d-%H%M%S")
    suffix = "jpg" if config.image_format.lower() in ("jpeg", "jpg") else "png"
    png_path = out_dir / f"weekboard-{week.key}-{stamp}.{suffix}"

    # Shoot to a dotfile first, then rename into place. The wallpaper watcher
    # ignores dotfiles, so it only ever sees a complete image.
    staging = out_dir / f".{png_path.name}.part"
    _shoot(html_path, staging, config)
    os.replace(staging, png_path)

    if keep_html:
        shutil.copy(html_path, out_dir / f"weekboard-{week.key}.html")
    shutil.rmtree(tmp_dir, ignore_errors=True)

    _prune(out_dir, keep=config.keep_renders)
    return png_path


def _shoot(html_path: Path, png_path: Path, config: Config) -> None:
    """Screenshot a local HTML file with Playwright's Chromium."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            "Playwright is not installed. Run:\n"
            "  .venv/bin/pip install -r requirements.txt\n"
            "  .venv/bin/playwright install chromium"
        ) from exc

    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=["--force-color-profile=srgb", "--font-render-hinting=none"])
        page = browser.new_page(
            viewport={"width": config.width, "height": config.height},
            device_scale_factor=config.scale,
        )
        page.goto(html_path.resolve().as_uri(), wait_until="load")
        # Wait on the fonts themselves rather than guessing at a delay.
        try:
            page.evaluate("document.fonts.ready")
        except Exception:  # pragma: no cover - older engines
            page.wait_for_timeout(250)
        if config.image_format.lower() in ("jpeg", "jpg"):
            page.screenshot(path=str(png_path), type="jpeg",
                            quality=max(1, min(100, config.jpeg_quality)))
        else:
            page.screenshot(path=str(png_path), type="png")
        browser.close()


def _prune(folder: Path, keep: int) -> None:
    """Keep only the newest `keep` weekboard renders."""
    renders = sorted(
        (p for p in folder.iterdir()
         if p.name.startswith("weekboard-") and p.suffix.lower() in (".png", ".jpg")),
        key=lambda p: p.stat().st_mtime, reverse=True,
    )
    for stale in renders[max(keep, 1):]:
        stale.unlink(missing_ok=True)
