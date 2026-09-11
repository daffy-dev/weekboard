"""Work out what resolution(s) to render at, instead of assuming 4K.

Asking macOS costs about a second, so the answer is cached on disk and only
refreshed occasionally — a display setup does not change often.
"""

from __future__ import annotations

import json
import platform
import re
import subprocess
import time
from pathlib import Path

FALLBACK = (3840, 2160)
CACHE_TTL_SECONDS = 7 * 24 * 3600
# Below this, a wallpaper looks soft; above it, renders get slow for no gain.
MIN_WIDTH, MAX_WIDTH = 1920, 5120


def slugify_display_name(name: str) -> str:
    """Normalize a display name for a filename, tolerant of macOS spelling quirks.

    system_profiler and System Events (`display name of desktop N`) don't
    always agree on the built-in panel's generic label — observed on one
    machine as "Color LCD" vs "Colour LCD", American vs British — even
    though they mean the same physical screen. Both the render side (this
    function) and `wallpaper_setter.py`'s matching use this same
    normalization, so that variant folds away instead of causing a mismatch.
    An external display's real model name, read off its EDID, isn't
    localized and matches exactly either way.
    """
    text = name.strip().lower().replace("colour", "color")
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text or "display"


def _parse_resolution(text: str) -> tuple[int, int] | None:
    """Pull '3456 x 2234' out of a system_profiler resolution string."""
    match = re.search(r"(\d{3,5})\s*[x×]\s*(\d{3,5})", text)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def _probe_macos() -> list[tuple[str, int, int]]:
    """Every attached display's (name, native pixel width, native pixel height),
    largest first. The name is whatever system_profiler calls the panel — the
    built-in's generic label, or an external's real model name (from its EDID) —
    which is what `wallpaper_setter.py` later matches against System Events'
    `display name of desktop N` to know which render goes on which screen.
    """
    try:
        result = subprocess.run(
            ["system_profiler", "-json", "SPDisplaysDataType"],
            capture_output=True, text=True, timeout=20, check=False,
        )
        if result.returncode != 0:
            return []
        data = json.loads(result.stdout)
    except (subprocess.SubprocessError, OSError, json.JSONDecodeError):
        return []

    found: list[tuple[str, int, int]] = []
    for gpu in data.get("SPDisplaysDataType", []):
        if not isinstance(gpu, dict):
            continue
        for display in gpu.get("spdisplays_ndrvs", []):
            if not isinstance(display, dict):
                continue
            name = display.get("_name")
            if not isinstance(name, str) or not name:
                continue
            # Prefer the native panel pixel count; not every display reports
            # it, so fall back to the (refresh-rate-suffixed) resolution field.
            size = None
            pixels = display.get("_spdisplays_pixels")
            if isinstance(pixels, str):
                size = _parse_resolution(pixels)
            if size is None:
                for key in ("_spdisplays_resolution", "spdisplays_resolution"):
                    value = display.get(key)
                    if isinstance(value, str):
                        size = _parse_resolution(value)
                        if size:
                            break
            if size:
                found.append((name, size[0], size[1]))

    return sorted(found, key=lambda item: item[1] * item[2], reverse=True)


def _clamp(width: int, height: int) -> tuple[int, int]:
    """Scale into [MIN_WIDTH, MAX_WIDTH] and round to even numbers."""
    if width < MIN_WIDTH:
        # Scale a small display up so text stays crisp when macOS resamples.
        scale = MIN_WIDTH / width
        width, height = round(width * scale), round(height * scale)
    if width > MAX_WIDTH:
        scale = MAX_WIDTH / width
        width, height = round(width * scale), round(height * scale)
    # Even numbers keep the encoders happy.
    return width - width % 2, height - height % 2


def detect_all(cache_path: Path | None = None, refresh: bool = False) -> list[tuple[str, int, int]]:
    """Render size for every attached display: (name, width, height), largest first."""
    if cache_path and not refresh and cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if time.time() - cached.get("at", 0) < CACHE_TTL_SECONDS:
                sizes = cached.get("sizes")
                if sizes:
                    return [(str(s[0]), int(s[1]), int(s[2])) for s in sizes]
        except (OSError, json.JSONDecodeError, KeyError, ValueError, TypeError, IndexError):
            pass

    raw = _probe_macos() if platform.system() == "Darwin" else []
    sizes = [(name, *_clamp(w, h)) for name, w, h in raw] or [("", *FALLBACK)]

    if cache_path:
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(
                json.dumps({"sizes": sizes, "at": time.time(), "all": raw}),
                encoding="utf-8",
            )
        except OSError:
            pass
    return sizes


def detect(cache_path: Path | None = None, refresh: bool = False) -> tuple[int, int]:
    """Best render size for this machine: the largest display, clamped."""
    _, width, height = detect_all(cache_path, refresh)[0]
    return width, height


def describe() -> str:
    """Human summary of the attached displays, for `wb doctor`."""
    sizes = _probe_macos() if platform.system() == "Darwin" else []
    if not sizes:
        return f"none detected — using {FALLBACK[0]}x{FALLBACK[1]}"
    return ", ".join(f"{name} {w}x{h}" for name, w, h in sizes)
