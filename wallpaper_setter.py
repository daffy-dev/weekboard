#!/usr/bin/env python3
"""Watch a folder and set the newest image as the Mac desktop wallpaper."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

DEFAULT_DIR = Path("/Users/daffy/Downloads/desktop_plans")
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".heic", ".gif", ".tif", ".tiff"}
DEBOUNCE_SECONDS = 1.0


@dataclass(frozen=True)
class ImageSnapshot:
    """Fingerprint of a candidate wallpaper file."""

    path: Path
    mtime_ns: int
    size: int


def log(message: str) -> None:
    """Write a status line to stderr."""
    print(message, file=sys.stderr, flush=True)


def is_image(path: Path) -> bool:
    """Return True if path looks like a supported image file."""
    return path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES and not path.name.startswith(".")


def snapshot_image(path: Path) -> ImageSnapshot | None:
    """Stat an image; return None if it disappears mid-scan."""
    try:
        stat = path.stat()
    except OSError:
        return None
    return ImageSnapshot(path=path.resolve(), mtime_ns=stat.st_mtime_ns, size=stat.st_size)


def newest_image(folder: Path) -> ImageSnapshot | None:
    """Return the newest top-level image in folder by modification time."""
    newest: ImageSnapshot | None = None
    try:
        entries = list(folder.iterdir())
    except OSError as exc:
        log(f"Cannot read {folder}: {exc}")
        return None
    for path in entries:
        if not is_image(path):
            continue
        snap = snapshot_image(path)
        if snap is None:
            continue
        if newest is None or snap.mtime_ns > newest.mtime_ns:
            newest = snap
    return newest


def set_wallpaper(path: Path) -> None:
    """Apply path as wallpaper on every desktop via System Events."""
    posix = str(path.resolve())
    script = f"""
tell application "System Events"
    tell every desktop
        set picture to POSIX file {json.dumps(posix)}
    end tell
end tell
"""
    result = subprocess.run(
        ["osascript", "-e", script],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "osascript failed").strip()
        raise RuntimeError(err)


class WallpaperWatcher:
    """Apply the newest image after filesystem events settle."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self._applied: ImageSnapshot | None = None
        self._lock = threading.Lock()
        self._timer: threading.Timer | None = None

    def apply_now(self) -> None:
        """Set wallpaper to the newest image if it differs from the last apply."""
        candidate = newest_image(self.folder)
        with self._lock:
            if candidate is None:
                return
            if self._applied is not None and candidate == self._applied:
                return
            try:
                set_wallpaper(candidate.path)
            except RuntimeError as exc:
                log(f"Failed to set wallpaper: {exc}")
                return
            self._applied = candidate
            log(f"Wallpaper set: {candidate.path.name}")

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
    """Watch folder via FSEvents and apply a stable newest image as wallpaper."""
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
        description="Set the newest image in a folder as the Mac desktop wallpaper."
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
