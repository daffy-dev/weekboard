"""Real system telemetry and git activity for the dashboard footer."""

from __future__ import annotations

import json
import platform
import shutil
import socket
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path

try:
    import psutil
except ImportError:  # pragma: no cover - psutil is a declared dependency
    psutil = None

# How many past renders' worth of CPU/RAM/disk/net readings to keep, matching
# the sparklines' own default width so every bar shown is a real sample.
HISTORY_LIMIT = 24


def _sparkline(values: list[float], width: int = 24) -> list[int]:
    """Normalise values to 0-100 heights for a bar sparkline."""
    if not values:
        return [0] * width
    tail = values[-width:]
    tail = [0.0] * (width - len(tail)) + tail
    peak = max(tail) or 1.0
    return [int(round(v / peak * 100)) for v in tail]


def _pseudo_series(seed: float, width: int = 24) -> list[float]:
    """Deterministic wobble used where there's genuinely nothing real to plot
    (the playlist's audio-visualizer bars — the playlist itself is fictional
    flavour text, so a fake waveform under it is honest, not decoration
    pretending to be data).
    """
    import math

    return [
        abs(math.sin(seed * 0.7 + i * 0.9)) * 0.6 + abs(math.cos(i * 0.4)) * 0.4
        for i in range(width)
    ]


def _load_history(path: Path) -> dict[str, list[float]]:
    """Read the on-disk trend history, tolerating a missing or corrupt file."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _record_history(path: Path, sample: dict[str, float]) -> dict[str, list[float]]:
    """Append this render's real readings to the trend history on disk.

    Best-effort: a write failure (read-only disk, odd permissions) shouldn't
    stop a render, it should just cost that one render's worth of history.
    """
    history = _load_history(path)
    for key, value in sample.items():
        series = history.get(key, [])
        series.append(value)
        history[key] = series[-HISTORY_LIMIT:]
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(history), encoding="utf-8")
    except OSError:
        pass
    return history


def uptime_string() -> tuple[str, float]:
    """Return a human uptime and a 0-100 'uptime' gauge value."""
    if psutil is None:
        return "unknown", 99.9
    boot = datetime.fromtimestamp(psutil.boot_time())
    delta = datetime.now() - boot
    days, rem = divmod(int(delta.total_seconds()), 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days:
        text = f"{days}d {hours}h"
    elif hours:
        text = f"{hours}h {minutes}m"
    else:
        text = f"{minutes}m"
    # A soft "availability" figure that creeps toward 100% the longer you're up.
    gauge = min(99.9, 90.0 + delta / timedelta(days=1) * 2.0)
    return text, round(gauge, 1)


def git_log(
    repos: list[str],
    limit: int = 6,
    days: int = 7,
    author: str = "",
) -> tuple[list[str], int]:
    """Recent commit subjects across the configured repos, plus the total count.

    Reads `--all`, so commits fetched from a remote count even when you haven't
    merged them into your local branch — which is the normal case if the actual
    work happens on another machine. Run `wb sync` to refresh those refs.
    """
    lines: list[tuple[float, str]] = []
    if not shutil.which("git"):
        return [], 0
    since = f"--since={days}.days.ago"
    for repo in repos:
        path = Path(repo).expanduser()
        if not (path / ".git").exists():
            continue
        command = ["git", "-C", str(path), "log", "--all", since,
                   "--pretty=%ct%x1f%s", "-n", "200"]
        if author:
            command += [f"--author={author}"]
        try:
            result = subprocess.run(
                command, capture_output=True, text=True, timeout=10, check=False,
            )
        except (subprocess.SubprocessError, OSError):
            continue
        if result.returncode != 0:
            continue
        for line in result.stdout.splitlines():
            stamp, _, subject = line.partition("\x1f")
            if not subject:
                continue
            try:
                lines.append((float(stamp), subject.strip()))
            except ValueError:
                continue
    lines.sort(key=lambda item: item[0], reverse=True)
    seen: set[str] = set()
    out: list[str] = []
    for _, subject in lines:
        if subject in seen:
            continue
        seen.add(subject)
        out.append(subject)
    # `out` is every distinct commit in the window; the caller shows only a few.
    return out[:limit], len(seen)


def commit_activity(config, force: bool = False) -> tuple[list[str], int]:
    """Recent commits, from GitHub if we can reach it, else from local clones.

    GitHub is preferred because it sees every machine you work on; local git
    only sees repos cloned here, with refs as stale as your last fetch.
    """
    days = getattr(config, "commit_days", 7)
    source = getattr(config, "commit_source", "auto")

    if source in ("auto", "github"):
        from . import github

        user = getattr(config, "github_user", "") or ""
        if not user and github.available():
            user = github.current_user()
        if user:
            subjects, count = github.recent_commits(
                user,
                days=days,
                cache_path=config.github_cache,
                ttl=getattr(config, "github_cache_seconds", 900),
                force=force,
            )
            if count or source == "github":
                return subjects, count

    return git_log(
        config.git_repos, days=days, author=getattr(config, "git_author", "")
    )


def collect(config) -> dict:
    """Gather everything the footer and status panels need."""
    now = datetime.now()
    seed = now.hour * 60 + now.minute

    if psutil is not None:
        cpu = psutil.cpu_percent(interval=0.15)
        ram = psutil.virtual_memory().percent
        disk = psutil.disk_usage("/").percent
        net_counters = psutil.net_io_counters()
        time.sleep(0.12)
        net_after = psutil.net_io_counters()
        delta_bytes = max(
            0,
            (net_after.bytes_sent + net_after.bytes_recv)
            - (net_counters.bytes_sent + net_counters.bytes_recv),
        )
        net_rate = delta_bytes / 0.12 / 1024
        history = _record_history(
            config.stats_history_cache, {"cpu": cpu, "ram": ram, "disk": disk, "net": net_rate}
        )
    else:
        cpu = ram = disk = 0.0
        net_rate = 0.0
        history = _load_history(config.stats_history_cache)

    if net_rate > 1024:
        net_label = f"{net_rate / 1024:.1f} MB/s"
    else:
        net_label = f"{net_rate:.0f} KB/s"

    up_text, up_gauge = uptime_string()
    commit_subjects, commit_count = commit_activity(config)

    return {
        "cpu": round(cpu),
        "ram": round(ram),
        "disk": round(disk),
        "net_label": net_label,
        # Real trend lines, from readings actually taken at past renders —
        # the pseudo series is only a first-run fallback, before there's any
        # history yet.
        "cpu_spark": _sparkline(history.get("cpu") or _pseudo_series(seed)),
        "ram_spark": _sparkline(history.get("ram") or _pseudo_series(seed + 11)),
        "disk_spark": _sparkline(history.get("disk") or _pseudo_series(seed + 23)),
        "net_spark": _sparkline(history.get("net") or _pseudo_series(seed + 37)),
        "audio_spark": _sparkline(_pseudo_series(seed + 5), width=40),
        "uptime": up_text,
        "uptime_gauge": up_gauge,
        "user": (config.user_label or _current_user()).upper(),
        "host": (config.host_label or socket.gethostname().split(".")[0]).upper(),
        "os": _os_label(),
        "time": now.strftime("%H:%M"),
        "date": now.strftime("%Y-%m-%d"),
        "commits": commit_subjects,
        "commit_count": commit_count,
    }


def _current_user() -> str:
    """Best-effort login name."""
    import getpass

    try:
        return getpass.getuser()
    except Exception:  # pragma: no cover - environment dependent
        return "user"


def _os_label() -> str:
    """Short OS description."""
    system = platform.system()
    if system == "Darwin":
        return f"MACOS {platform.mac_ver()[0]}"
    return f"{system} {platform.release()}".upper()
