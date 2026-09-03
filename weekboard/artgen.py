"""Generate background art for the dashboard from a text prompt.

The model writes the scene as a self-contained SVG document — code, not
pixels — and it's rendered to a JPG through the same headless-Chromium
pipeline render.py already uses for the dashboard itself. Same backend as
`wb ai`/`wb flavor` (the CLI or the API, whichever is configured), no extra
provider or API key.
"""

from __future__ import annotations

import re
import time
from pathlib import Path

from . import agent
from .config import Config

ART_SYSTEM = """You write background art for a cyberpunk terminal dashboard wallpaper, as a
single self-contained SVG document.

Rules:
- Output ONLY the SVG, starting with <svg and ending with </svg>. No prose,
  no markdown fences, no explanation before or after it.
- The root <svg> must have width="1240" height="940" viewBox="0 0 1240 940".
- Use only inline gradients, shapes, filters and paths defined within the
  SVG itself (<defs>, <linearGradient>, <radialGradient>, <path>, <rect>,
  <circle>, <polygon>, <filter>, ...). No <image>, no external fonts, no
  external references of any kind — everything must be self-contained
  vector art that renders correctly with zero network access.
- Never depict a specific copyrighted character, logo, trademark, or brand
  (anime, game, movie, corporate, or otherwise) — original, generic scenes
  and shapes only. If the prompt names one, draw an original design in a
  similar mood instead, and do not reproduce or label the recognizable one.
- Default to this palette unless the prompt clearly asks for something
  else: dark navy/violet background, neon accents (cyan, magenta, amber,
  green) — the board's own accent color is meant to read clearly over it.
"""

SVG_RE = re.compile(r"<svg[\s\S]*</svg>", re.IGNORECASE)

# A detailed scene (gradients, dozens of shapes) easily runs past the small
# default api_max_tokens every other prompt in agent.py uses for short JSON
# replies — this is a per-call override, not a change to that default.
MAX_TOKENS = 8000


class ArtGenError(RuntimeError):
    """Raised when art generation fails or the model's reply isn't usable."""


def _extract_svg(text: str) -> str:
    """Pull the <svg>...</svg> document out of a reply that should be just that."""
    match = SVG_RE.search(text)
    if not match:
        raise ArtGenError(f"The model didn't return an SVG:\n{text.strip()[:300]}")
    return match.group(0)


def _slug(prompt: str) -> str:
    """A short filesystem-safe stem for the prompt, so filenames stay legible."""
    slug = re.sub(r"[^a-z0-9]+", "-", prompt.lower()).strip("-")
    return slug[:40] or "art"


def generate(config: Config, prompt: str, timeout: int = 120) -> Path:
    """Ask the model for an SVG scene, render it, and save it under data/art/.

    Returns the path to the new JPG. Does not touch the config's "art" key —
    callers decide whether/when to point at it.
    """
    reply = agent.ask_text(config, ART_SYSTEM, prompt.strip(), timeout=timeout, max_tokens=MAX_TOKENS)
    svg = _extract_svg(reply)

    art_dir = config.data_path / "art"
    art_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out_path = art_dir / f"{_slug(prompt)}-{stamp}.jpg"

    _shoot_svg(svg, out_path)
    return out_path


def _shoot_svg(svg: str, out_path: Path) -> None:
    """Screenshot a standalone SVG document to a JPG via headless Chromium."""
    import tempfile

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover
        raise ArtGenError(
            "Playwright is not installed. Run:\n"
            "  .venv/bin/pip install -r requirements.txt\n"
            "  .venv/bin/playwright install chromium"
        ) from exc

    with tempfile.TemporaryDirectory(prefix="weekboard-art-") as tmp:
        svg_path = Path(tmp) / "art.svg"
        svg_path.write_text(svg, encoding="utf-8")
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            try:
                page = browser.new_page(viewport={"width": 1240, "height": 940})
                page.goto(svg_path.resolve().as_uri(), wait_until="load")
                page.screenshot(path=str(out_path), type="jpeg", quality=92)
            finally:
                browser.close()
