#!/usr/bin/env python3
"""Watch a folder and set the newest image(s) as the Mac desktop wallpaper.

A plain single image gets applied to every screen, same as always — this
still works as a generic "watch a folder, set the wallpaper" tool for any
image you drop in. But when weekboard renders one image per attached
display (see weekboard/render.py), the filenames say which display each one
is for, and this matches each render to its screen by display name so every
screen gets its own correctly-sized wallpaper instead of one image
stretched over all of them.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

DEFAULT_DIR = Path.home() / "Downloads" / "desktop_plans"
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".heic", ".gif", ".tif", ".tiff"}
DEBOUNCE_SECONDS = 1.0

# Matches weekboard's own render filenames, e.g.
#   weekboard-2026-W37-color-lcd-20260907-091936.png   (named — one of several displays)
#   weekboard-2026-W37-20260907-091936.png             (unnamed — a pinned/fallback render)
# Anything else (a photo you dropped in by hand) just doesn't match, and is
# treated as a single generic wallpaper applied everywhere, as before.
_RENDER_RE = re.compile(
    r"^weekboard-\d{4}-W\d{1,2}-(?:(?P<slug>[a-z0-9]+(?:-[a-z0-9]+)*)-)?(?P<stamp>\d{8}-\d{6})\.(?:png|jpe?g)$",
    re.IGNORECASE,
)


def log(message: str) -> None:
    """Write a status line to stderr."""
    print(message, file=sys.stderr, flush=True)


def is_image(path: Path) -> bool:
    """Return True if path looks like a supported image file."""
    return path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES and not path.name.startswith(".")


@dataclass(frozen=True)
class Render:
    """One candidate wallpaper file, with whatever weekboard encoded in its name."""

    path: Path
    mtime_ns: int
    size: int
    slug: str | None   # which display this was rendered for, or None if unlabeled
    stamp: str | None  # which render pass it belongs to, or None if not a weekboard render


def _parse_render(path: Path) -> tuple[str | None, str | None]:
    """Pull (slug, stamp) out of a weekboard render filename, if it is one."""
    match = _RENDER_RE.match(path.name)
    if not match:
        return None, None
    return match.group("slug"), match.group("stamp")


def scan(folder: Path) -> list[Render]:
    """Every candidate image in folder, newest first."""
    entries: list[Render] = []
    try:
        candidates = list(folder.iterdir())
    except OSError as exc:
        log(f"Cannot read {folder}: {exc}")
        return []
    for path in candidates:
        if not is_image(path):
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        slug, stamp = _parse_render(path)
        entries.append(Render(
            path=path.resolve(), mtime_ns=stat.st_mtime_ns, size=stat.st_size,
            slug=slug, stamp=stamp,
        ))
    entries.sort(key=lambda e: e.mtime_ns, reverse=True)
    return entries


def current_batch(entries: list[Render]) -> list[Render]:
    """The newest image, plus every other image from the same render pass.

    A weekboard multi-display render pass writes several files sharing one
    stamp; this returns all of them together so they get applied as a set.
    A lone dropped-in photo (no stamp) just returns as a batch of one.
    """
    if not entries:
        return []
    newest = entries[0]
    if newest.stamp is None:
        return [newest]
    return [e for e in entries if e.stamp == newest.stamp]


def desktop_names() -> list[str]:
    """`display name of desktop N`, in desktop-index order (1, 2, 3, ...).

    Empty if System Events can't answer — an older macOS, a missing
    Automation permission, or no desktops — so callers can fall back to
    applying one image everywhere, same as before per-display support
    existed. (System Events' `desktop` objects don't expose their screen's
    pixel bounds, only this display name — confirmed against a real
    two-monitor setup — which is why matching goes by name, not geometry.)
    """
    script = (
        'tell application "System Events"\n'
        "set out to {}\n"
        "repeat with d in desktops\n"
        "set end of out to (display name of d)\n"
        "end repeat\n"
        "return out\n"
        "end tell"
    )
    result = subprocess.run(
        ["osascript", "-e", script],
        check=False, capture_output=True, text=True, timeout=20,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return []
    return [chunk.strip() for chunk in result.stdout.strip().split(", ") if chunk.strip()]


def assign_to_desktops(batch: list[Render], names: list[str]) -> list[Path | None]:
    """Which render goes on which desktop, in `names` order (desktop 1, 2, ...).

    Matches by display name first — exact whenever weekboard rendered one
    image per display, since render.py and this module normalize names the
    same way (see weekboard.display.slugify_display_name). Anything left
    over — a desktop whose name didn't match any render — falls back to
    whatever's left, biggest file first, so every desktop still gets
    *something* rather than being skipped.
    """
    if not names:
        return []
    if len(batch) <= 1:
        path = batch[0].path if batch else None
        return [path] * len(names)

    from weekboard.display import slugify_display_name

    by_slug = {r.slug: r for r in batch if r.slug}
    remaining = sorted(batch, key=lambda r: r.size, reverse=True)
    assignment: list[Path | None] = []
    for name in names:
        match = by_slug.get(slugify_display_name(name))
        if match is None:
            match = remaining[0] if remaining else batch[0]
        assignment.append(match.path)
        if match in remaining:
            remaining.remove(match)
    return assignment


def _desktop_script(assignment: list[Path | None]) -> str:
    """AppleScript setting each desktop's picture individually."""
    lines = ['tell application "System Events"']
    for index, path in enumerate(assignment, start=1):
        if path is None:
            continue
        posix = json.dumps(str(path))
        lines.append(f"\ttell desktop {index}")
        lines.append(f"\t\tset picture to POSIX file {posix}")
        lines.append("\tend tell")
    lines.append("end tell")
    return "\n".join(lines)


def _everywhere_script(path: Path) -> str:
    """AppleScript setting the same picture on every desktop."""
    posix = json.dumps(str(path))
    return (
        'tell application "System Events"\n'
        "\ttell every desktop\n"
        f"\t\tset picture to POSIX file {posix}\n"
        "\tend tell\n"
        "end tell"
    )


def _run_osascript(script: str) -> None:
    result = subprocess.run(
        ["osascript", "-e", script],
        check=False, capture_output=True, text=True,
    )
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "osascript failed").strip()
        raise RuntimeError(err)


def apply_wallpaper(batch: list[Render]) -> None:
    """Apply a render batch as wallpaper — one image per screen where possible."""
    if len(batch) <= 1:
        _run_osascript(_everywhere_script(batch[0].path.resolve()))
        return
    names = desktop_names()
    if not names:
        # Can't tell desktops apart; fall back to the biggest render
        # everywhere rather than leaving the wallpaper untouched.
        largest = max(batch, key=lambda r: r.size)
        _run_osascript(_everywhere_script(largest.path.resolve()))
        return
    assignment = [p.resolve() if p else None for p in assign_to_desktops(batch, names)]
    _run_osascript(_desktop_script(assignment))


class WallpaperWatcher:
    """Apply the newest render batch after filesystem events settle."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self._applied: tuple[tuple[Path, int], ...] | None = None
        self._lock = threading.Lock()
        self._timer: threading.Timer | None = None

    def apply_now(self) -> None:
        """Set wallpaper to the newest render batch if it differs from the last apply."""
        entries = scan(self.folder)
        with self._lock:
            if not entries:
                return
            batch = current_batch(entries)
            fingerprint = tuple(sorted((e.path, e.mtime_ns) for e in batch))
            if self._applied is not None and fingerprint == self._applied:
                return
            try:
                apply_wallpaper(batch)
            except RuntimeError as exc:
                log(f"Failed to set wallpaper: {exc}")
                return
            self._applied = fingerprint
            log(f"Wallpaper set: {', '.join(e.path.name for e in batch)}")
            self._clean_others(keep={e.path for e in batch})

    def _clean_others(self, keep: set[Path]) -> None:
        """Delete every other image in the folder now that keep is applied."""
        try:
            entries = list(self.folder.iterdir())
        except OSError:
            return
        for path in entries:
            if not is_image(path) or path.resolve() in keep:
                continue
            try:
                path.unlink()
                log(f"Removed old wallpaper: {path.name}")
            except OSError as exc:
                log(f"Could not remove {path.name}: {exc}")

    def schedule(self) -> None:
        """Debounce: wait until events stop before applying."""
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(DEBOUNCE_SECONDS, self.apply_now)
            self._timer.daemon = True
            self._timer.start()


class FolderHandler(FileSystemEventHandler):
    """Rescan the folder when a non-directory file changes."""

    def __init__(self, watcher: WallpaperWatcher) -> None:
        super().__init__()
        self._watcher = watcher

    def on_any_event(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        self._watcher.schedule()


def watch(folder: Path) -> None:
    """Watch folder via FSEvents and apply a stable newest render batch as wallpaper."""
    if not folder.is_dir():
        raise SystemExit(f"Not a directory: {folder}")

    log(f"Watching {folder}")
    watcher = WallpaperWatcher(folder)
    watcher.apply_now()

    observer = Observer()
    observer.schedule(FolderHandler(watcher), str(folder), recursive=False)
    observer.start()
    try:
        while observer.is_alive():
            observer.join(timeout=1.0)
    finally:
        observer.stop()
        observer.join()


def parse_args() -> argparse.Namespace:
    """Parse CLI flags."""
    parser = argparse.ArgumentParser(
        description="Set the newest image(s) in a folder as the Mac desktop wallpaper."
    )
    parser.add_argument(
        "--dir",
        type=Path,
        default=DEFAULT_DIR,
        help=f"Folder to watch (default: {DEFAULT_DIR})",
    )
    return parser.parse_args()


def main() -> None:
    """Entry point."""
    args = parse_args()
    try:
        watch(args.dir.expanduser())
    except KeyboardInterrupt:
        log("Stopped")


if __name__ == "__main__":
    main()
