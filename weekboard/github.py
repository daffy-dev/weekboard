"""Recent commit activity from GitHub, via the `gh` CLI.

Local git only knows about repos cloned on this machine, and only about refs
that have been fetched. If the work happens on another machine, GitHub is the
real source of truth — so this asks GitHub instead.

Uses `gh api`, which reuses the auth you already have, so there is no token to
manage here. Results are cached, because a render happens on every `wb done`
and nobody wants a network round trip in that path.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

CACHE_TTL_SECONDS = 900          # 15 minutes
REQUEST_TIMEOUT = 20
EVENT_PAGES = 3                  # 100 events each; plenty for a week


def available() -> bool:
    """True if the gh CLI is installed and authenticated."""
    if not shutil.which("gh"):
        return False
    try:
        result = subprocess.run(
            ["gh", "auth", "status"], capture_output=True, text=True, timeout=10, check=False
        )
    except (subprocess.SubprocessError, OSError):
        return False
    return result.returncode == 0


def current_user() -> str:
    """The logged-in GitHub username, or empty if unknown."""
    try:
        result = subprocess.run(
            ["gh", "api", "user", "--jq", ".login"],
            capture_output=True, text=True, timeout=REQUEST_TIMEOUT, check=False,
        )
    except (subprocess.SubprocessError, OSError):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def parse_events(events: list[dict], days: int, now: datetime | None = None) -> tuple[list[str], int]:
    """Pull commit subjects and a count out of a GitHub events payload.

    Kept pure so it can be tested without touching the network.
    """
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)
    found: list[tuple[datetime, str, str]] = []

    for event in events:
        if event.get("type") != "PushEvent":
            continue
        stamp = event.get("created_at") or ""
        try:
            when = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        except ValueError:
            continue
        if when < cutoff:
            continue
        repo = (event.get("repo") or {}).get("name", "")
        short_repo = repo.split("/")[-1]
        for commit in (event.get("payload") or {}).get("commits", []) or []:
            message = (commit.get("message") or "").strip().splitlines()
            if not message:
                continue
            sha = commit.get("sha", "")
            found.append((when, sha, f"{short_repo}: {message[0]}"))

    # A force-push can replay the same sha; count each commit once.
    seen: set[str] = set()
    unique: list[tuple[datetime, str]] = []
    for when, sha, text in sorted(found, key=lambda item: item[0], reverse=True):
        key = sha or text
        if key in seen:
            continue
        seen.add(key)
        unique.append((when, text))
    return [text for _, text in unique], len(unique)


def _fetch_events(user: str) -> list[dict]:
    """Raw event feed for a user. Includes private repos when it's you."""
    events: list[dict] = []
    for page in range(1, EVENT_PAGES + 1):
        try:
            result = subprocess.run(
                ["gh", "api", f"users/{user}/events?per_page=100&page={page}"],
                capture_output=True, text=True, timeout=REQUEST_TIMEOUT, check=False,
            )
        except (subprocess.SubprocessError, OSError):
            break
        if result.returncode != 0:
            break
        try:
            batch = json.loads(result.stdout)
        except json.JSONDecodeError:
            break
        if not isinstance(batch, list) or not batch:
            break
        events.extend(batch)
        if len(batch) < 100:
            break
    return events


def recent_commits(
    user: str,
    days: int = 7,
    cache_path: Path | None = None,
    ttl: int = CACHE_TTL_SECONDS,
    force: bool = False,
    limit: int = 6,
) -> tuple[list[str], int]:
    """Commit subjects and count from GitHub, cached.

    Returns ([], 0) on any failure — a dashboard must never fail to draw
    because the network is down.
    """
    if cache_path and not force and cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if time.time() - cached.get("at", 0) < ttl:
                return cached.get("subjects", [])[:limit], int(cached.get("count", 0))
        except (OSError, json.JSONDecodeError, ValueError):
            pass

    if not user or not available():
        return [], 0

    subjects, count = parse_events(_fetch_events(user), days)

    if cache_path:
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(
                json.dumps({"subjects": subjects[:20], "count": count, "at": time.time()}),
                encoding="utf-8",
            )
        except OSError:
            pass
    return subjects[:limit], count
