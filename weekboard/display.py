"""Work out what resolution to render at, instead of assuming 4K.

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


def _parse_resolution(text: str) -> tuple[int, int] | None:
    """Pull '3456 x 2234' out of a system_profiler resolution string."""
    match = re.search(r"(\d{3,5})\s*[x×]\s*(\d{3,5})", text)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def _probe_macos() -> list[tuple[int, int]]:
    """Every attached display's pixel resolution, largest first."""
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

    found: list[tuple[int, int]] = []

    def walk(node) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if isinstance(value, str) and "resolution" in key.lower():
                    size = _parse_resolution(value)
                    if size:
                        found.append(size)
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(data)
    return sorted(set(found), key=lambda wh: wh[0] * wh[1], reverse=True)


def detect(cache_path: Path | None = None, refresh: bool = False) -> tuple[int, int]:
    """Best render size for this machine: the largest display, clamped."""
    if cache_path and not refresh and cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if time.time() - cached.get("at", 0) < CACHE_TTL_SECONDS:
                return int(cached["width"]), int(cached["height"])
        except (OSError, json.JSONDecodeError, KeyError, ValueError):
            pass

    sizes = _probe_macos() if platform.system() == "Darwin" else []
    width, height = sizes[0] if sizes else FALLBACK

    if width < MIN_WIDTH:
        # Scale a small display up so text stays crisp when macOS resamples.
        scale = MIN_WIDTH / width
        width, height = round(width * scale), round(height * scale)
    if width > MAX_WIDTH:
        scale = MAX_WIDTH / width
        width, height = round(width * scale), round(height * scale)
    # Even numbers keep the encoders happy.
    width, height = width - width % 2, height - height % 2

    if cache_path:
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(
                json.dumps({"width": width, "height": height, "at": time.time(),
                            "all": sizes}),
                encoding="utf-8",
            )
        except OSError:
            pass
    return width, height


def describe() -> str:
    """Human summary of the attached displays, for `wb doctor`."""
    sizes = _probe_macos() if platform.system() == "Darwin" else []
    if not sizes:
        return f"none detected — using {FALLBACK[0]}x{FALLBACK[1]}"
    return ", ".join(f"{w}x{h}" for w, h in sizes)
