"""Mini agent: shells out to the local `claude` CLI to turn language into board edits."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

from .config import PROJECT_DIR, Config
from .model import parse_week_key, week_key

FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)

CAPTURE_SYSTEM = """You are the planning brain of a terminal to-do board organised by ISO week.
You translate one line of natural language into a list of operations on the board.

Return ONLY a JSON object, no prose, in this exact shape:
{"ops": [ ... ], "say": "one short line for the user"}

Allowed operations:
  {"op":"add","text":"...","week":"2026-W37","priority":"low|normal|high","tags":["x"]}
  {"op":"done","week":"2026-W36","match":"substring or task number"}
  {"op":"undone","week":"2026-W36","match":"..."}
  {"op":"remove","week":"2026-W36","match":"..."}
  {"op":"move","week":"2026-W36","match":"...","to_week":"2026-W37"}
  {"op":"edit","week":"2026-W36","match":"...","text":"new text"}
  {"op":"mission","week":"2026-W36","lines":["...","..."],"tagline":"..."}
  {"op":"quote","week":"2026-W36","text":"...","author":"..."}
  {"op":"status","week":"2026-W36","focus":90,"momentum":70,"shipped":85,"done":60}

Rules:
- "week" must always be a full ISO key like 2026-W37. Default to the current week.
- "next week" means the week after the current one. "week 37" means W37 of the current year.
- Prefer matching an existing task by a distinctive substring over its number.
- Keep task text short and imperative, in the language the user wrote it in.
- Gauges are normally computed automatically; only emit "status" if the user
  explicitly asks to pin one to a number.
- If the user says something that is not a board edit, return {"ops": [], "say": "..."}.
"""

FLAVOR_SYSTEM = """You write the flavour text for a cyberpunk terminal dashboard wallpaper.
Given the user's week and their tasks, return ONLY this JSON:
{"mission":["line one","line two","line three"],"tagline":"...",
 "quote_text":"...","quote_author":"...",
 "headline_ja":"...","headline_en":"..."}
Mission lines are short, punchy, second-person-implied imperatives (max 40 chars each).
The quote must be a real quote from a real person, relevant to the week's actual work.
headline_ja is a short Japanese motivational line; headline_en is its English gloss in caps.
"""

ROLLOVER_SYSTEM = """You help close out a week. Given the unfinished tasks, decide for each one
whether it should be carried into next week, or dropped as no longer relevant.
Return ONLY: {"carry":[<task ids>],"drop":[<task ids>],"say":"one short line"}
Be conservative: carry unless the task is clearly stale, duplicated, or superseded.
"""


class AgentError(RuntimeError):
    """Raised when the local claude CLI is missing or returns nothing usable."""


API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"


def api_key(config: Config) -> tuple[str, str]:
    """Find the API key. Returns (key, where it came from).

    Resolution order:
      1. the environment
      2. `api_key_file`, if the config names one
      3. this project's own `.env`, so dropping the key there just works

    Either file may hold the bare key or a `NAME=value` line. Files matter for
    launchd and cron, which never load your shell profile.
    """
    key = os.environ.get(config.api_key_env, "").strip()
    if key:
        return key, f"${config.api_key_env}"

    candidates = []
    if config.api_key_file:
        candidates.append(Path(config.api_key_file).expanduser())
    candidates.append(PROJECT_DIR / ".env")

    for path in candidates:
        if path.exists():
            found = _read_key_file(path, config.api_key_env)
            if found:
                return found, str(path)
    return "", ""


def _read_key_file(path: Path, var_name: str) -> str:
    """Read a key from a bare-key file or a .env-style file."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    bare = text.strip()
    if bare and "=" not in bare and "\n" not in bare:
        return bare
    for line in text.splitlines():
        line = line.strip().removeprefix("export ").strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        if name.strip() == var_name:
            return value.strip().strip("\"'")
    return ""


def backend(config: Config) -> str:
    """Which backend will actually be used: 'api' or 'cli'."""
    if config.backend == "api" and api_key(config)[0]:
        return "api"
    return "cli"


def available(config: Config) -> bool:
    """True if the configured backend is usable."""
    if backend(config) == "api":
        return True
    return shutil.which(config.claude_bin) is not None


def _extract_json(text: str) -> dict:
    """Pull a JSON object out of a model response that may be fenced or chatty."""
    text = text.strip()
    for candidate in ([m.group(1) for m in FENCE_RE.finditer(text)] + [text]):
        candidate = candidate.strip()
        if not candidate:
            continue
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            start, end = candidate.find("{"), candidate.rfind("}")
            if start != -1 and end > start:
                try:
                    return json.loads(candidate[start : end + 1])
                except json.JSONDecodeError:
                    continue
    raise AgentError(f"Could not parse a JSON reply from the model:\n{text[:400]}")


def ask(config: Config, system: str, user: str, timeout: int = 90) -> dict:
    """Send one prompt to the configured backend and return the parsed JSON reply."""
    if backend(config) == "api":
        return _extract_json(_ask_api(config, system, user, timeout))
    return _ask_cli(config, system, user, timeout)


def _ask_api(config: Config, system: str, user: str, timeout: int) -> str:
    """Call the Messages API directly. Cheapest path: no agent scaffolding is sent.

    Uses urllib so this needs no extra dependency.
    """
    key = api_key(config)[0]
    if not key:
        raise AgentError(
            f"backend is 'api' but no key was found. Put "
            f"{config.api_key_env}=... in {PROJECT_DIR / '.env'}, export it, "
            f'or point "api_key_file" at the file holding it.'
        )
    payload = json.dumps(
        {
            "model": config.api_model,
            "max_tokens": config.api_max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        API_URL,
        data=payload,
        headers={
            "content-type": "application/json",
            "anthropic-version": API_VERSION,
            "x-api-key": key,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise AgentError(f"API error {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise AgentError(f"Could not reach the API: {exc}") from exc

    blocks = [b.get("text", "") for b in body.get("content", []) if b.get("type") == "text"]
    if not blocks:
        raise AgentError("The API returned no text.")
    return "\n".join(blocks)


def _ask_cli(config: Config, system: str, user: str, timeout: int) -> dict:
    """Call the local claude CLI. Convenient, but it sends its own agent scaffolding."""
    if not available(config):
        raise AgentError(
            f"`{config.claude_bin}` not found on PATH. Install Claude Code, or set "
            f'"claude_bin" in data/config.json to its full path.'
        )
    cmd = [config.claude_bin, "-p", f"{system}\n\n---\n\n{user}"]
    if config.claude_model:
        cmd += ["--model", config.claude_model]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise AgentError("The model took too long to answer.") from exc
    if result.returncode != 0:
        raise AgentError((result.stderr or result.stdout or "claude CLI failed").strip()[:400])
    return _extract_json(result.stdout)


def _board_context(store, weeks: int = 3) -> str:
    """A compact view of the current and adjacent weeks for the model."""
    from .model import shift_week

    current = week_key()
    keys = [shift_week(current, offset) for offset in range(-1, weeks - 1)]
    lines = [f"Today is {date.today().isoformat()} ({current})."]
    for key in keys:
        week = store.load(key)
        if not week.tasks and key != current:
            continue
        lines.append(f"\n{key} ({week.date_range}):")
        for index, task in enumerate(week.tasks, start=1):
            flag = "x" if task.done else " "
            lines.append(f"  {index:02d} [{flag}] {task.text}")
        if not week.tasks:
            lines.append("  (empty)")
    return "\n".join(lines)


def capture(store, config: Config, text: str) -> dict:
    """Turn one natural-language line into board operations."""
    payload = f"{_board_context(store)}\n\nUser says: {text}"
    reply = ask(config, CAPTURE_SYSTEM, payload)
    ops = reply.get("ops") or []
    for op in ops:
        if "week" in op and op["week"]:
            op["week"] = parse_week_key(op["week"])
        if op.get("to_week"):
            op["to_week"] = parse_week_key(op["to_week"])
    return {"ops": ops, "say": reply.get("say", "")}


def flavor(store, config: Config, week) -> dict:
    """Ask the model for mission/quote/headline text tuned to this week's tasks."""
    tasks = "\n".join(f"- {t.text}" for t in week.tasks) or "(no tasks yet)"
    payload = f"Week {week.key} ({week.date_range}).\nTasks:\n{tasks}"
    return ask(config, FLAVOR_SYSTEM, payload)


def rollover_plan(config: Config, week) -> dict:
    """Ask the model which unfinished tasks deserve to move to next week."""
    open_tasks = week.open_tasks
    listing = "\n".join(f"{t.id}: {t.text}" for t in open_tasks) or "(none)"
    payload = f"Week {week.key} is ending.\nUnfinished:\n{listing}"
    return ask(config, ROLLOVER_SYSTEM, payload)


def apply_ops(store, ops: list[dict]) -> list[str]:
    """Execute agent operations against the store; return a human summary."""
    from .model import Week

    touched: dict[str, Week] = {}
    messages: list[str] = []

    def week_for(key: str | None) -> Week:
        key = parse_week_key(key)
        if key not in touched:
            touched[key] = store.load(key)
        return touched[key]

    def find(week: Week, needle: str):
        needle = str(needle).strip()
        if needle.isdigit():
            index = int(needle)
            if 1 <= index <= len(week.tasks):
                return week.tasks[index - 1]
        low = needle.lower()
        hits = [t for t in week.tasks if low in t.text.lower()]
        if len(hits) == 1:
            return hits[0]
        if hits:
            return hits[0]
        return None

    for op in ops:
        kind = op.get("op")
        week = week_for(op.get("week"))
        if kind == "add":
            if not op.get("text", "").strip():
                continue          # a malformed reply must not add a blank row
            task = week.add(
                op.get("text", "").strip(),
                priority=op.get("priority", "normal"),
                tags=op.get("tags") or [],
            )
            messages.append(f"+ {week.key} {task.id:02d} {task.text}")
        elif kind in ("done", "undone"):
            task = find(week, op.get("match", ""))
            if task:
                task.mark(kind == "done")
                mark = "✓" if kind == "done" else "○"
                messages.append(f"{mark} {week.key} {task.id:02d} {task.text}")
        elif kind == "remove":
            task = find(week, op.get("match", ""))
            if task:
                week.remove(task.id)
                messages.append(f"- {week.key} {task.text}")
        elif kind == "move":
            task = find(week, op.get("match", ""))
            if task:
                target = week_for(op.get("to_week"))
                week.remove(task.id)
                moved = target.add(task.text, priority=task.priority, tags=task.tags)
                moved.done = task.done
                moved.completed = task.completed
                moved.carried_from = week.key
                messages.append(f"→ {task.text}  ({week.key} → {target.key})")
        elif kind == "edit":
            task = find(week, op.get("match", ""))
            if task and op.get("text"):
                task.text = op["text"].strip()
                messages.append(f"~ {week.key} {task.id:02d} {task.text}")
        elif kind == "mission":
            if op.get("lines"):
                week.mission = [str(line) for line in op["lines"]][:4]
            if op.get("tagline"):
                week.tagline = op["tagline"]
            messages.append(f"~ {week.key} mission updated")
        elif kind == "quote":
            week.quote_text = op.get("text", week.quote_text)
            week.quote_author = op.get("author", week.quote_author)
            messages.append(f"~ {week.key} quote updated")
        elif kind == "status":
            from .metrics import GAUGE_NAMES

            for field in GAUGE_NAMES:
                if field in op:
                    try:
                        week.overrides[field] = max(0, min(100, int(op[field])))
                    except (TypeError, ValueError):
                        continue
            messages.append(f"~ {week.key} gauges pinned")

    for week in touched.values():
        store.save(week)
    return messages
