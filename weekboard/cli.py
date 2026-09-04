"""wb — the weekboard command line."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import click

from . import agent as agent_mod
from .config import CONFIG_PATH, load_config, save_config
from .metrics import GAUGE_NAMES
from .model import parse_week_key, shift_week, week_key
from .store import Store

GREEN = "\033[38;5;77m"
DIM = "\033[38;5;240m"
WHITE = "\033[97m"
RESET = "\033[0m"
STRIKE = "\033[9m"


def _echo_week(week, show_done: bool = True) -> None:
    """Print a week to the terminal in the dashboard's style."""
    click.echo()
    click.echo(f"{WHITE}  WEEK {week.number:02d}{RESET}  {GREEN}// {week.date_range}{RESET}")
    click.echo(f"{DIM}  {'─' * 62}{RESET}")
    if not week.tasks:
        click.echo(f"{DIM}  no tasks yet — wb add \"your first task\"{RESET}")
    for index, task in enumerate(week.tasks, start=1):
        if task.done and not show_done:
            continue
        box = f"{GREEN}[✓]{RESET}" if task.done else f"{DIM}[ ]{RESET}"
        text = f"{DIM}{STRIKE}{task.text}{RESET}" if task.done else task.text
        if task.priority == "high" and not task.done:
            text = f"{WHITE}{text}{RESET}"
        tags = f" {DIM}#{' #'.join(task.tags)}{RESET}" if task.tags else ""
        carried = f"{DIM}↩ {RESET}" if task.carried_from else ""
        click.echo(f"  {DIM}{index:02d}{RESET} {box} {carried}{text}{tags}")
    click.echo(f"{DIM}  {'─' * 62}{RESET}")
    done, total = len(week.done_tasks), len(week.tasks)
    pct = int(week.progress * 100)
    filled = int(week.progress * 24)
    bar = f"{GREEN}{'█' * filled}{DIM}{'░' * (24 - filled)}{RESET}"
    click.echo(f"  {bar}  {done}/{total} done  {GREEN}{pct}%{RESET}")
    click.echo()


def _render_if_enabled(ctx, store, week) -> None:
    """Re-render the wallpaper unless the user turned it off."""
    config = store.config
    if not config.auto_render or ctx.obj.get("no_render"):
        return
    try:
        from .render import render

        path = render(week, config, store)
        click.echo(f"{DIM}  → {path.name}{RESET}")
    except SystemExit as exc:
        click.echo(f"{DIM}  render skipped: {exc}{RESET}", err=True)
    except Exception as exc:  # pragma: no cover - rendering is best effort
        click.echo(f"{DIM}  render failed: {exc}{RESET}", err=True)


def _resolve(week_ref):
    """parse_week_key, but a bad week reads as a message rather than a traceback."""
    try:
        return parse_week_key(week_ref)
    except ValueError as exc:
        raise click.ClickException(str(exc))


def _week_option(func):
    """Shared --week/-w option."""
    return click.option(
        "-w", "--week", "week_ref", default=None,
        help="Week: 37, 2026-W37, next, prev, +2 (default: current)",
    )(func)


@click.group(invoke_without_command=True)
@click.option("--no-render", is_flag=True, help="Skip regenerating the wallpaper.")
@click.pass_context
def cli(ctx, no_render):
    """A week-shaped to-do board that redraws your desktop wallpaper."""
    ctx.ensure_object(dict)
    ctx.obj["no_render"] = no_render
    if ctx.invoked_subcommand is None:
        store = Store()
        _echo_week(store.load())


@cli.command()
@click.argument("text", nargs=-1, required=True)
@_week_option
@click.option("-p", "--priority", type=click.Choice(["low", "normal", "high"]), default="normal")
@click.option("-t", "--tag", "tags", multiple=True, help="Tag (repeatable).")
@click.pass_context
def add(ctx, text, week_ref, priority, tags):
    """Add a task. wb add "call Kalli" -w 37 -p high"""
    store = Store()
    week = store.load(_resolve(week_ref))
    task = week.add(" ".join(text), priority=priority, tags=list(tags))
    store.save(week)
    click.echo(f"{GREEN}  + {week.key} {len(week.tasks):02d}{RESET} {task.text}")
    _render_if_enabled(ctx, store, store.load())


@cli.command()
@click.argument("ids", nargs=-1, type=int, required=True)
@_week_option
@click.pass_context
def done(ctx, ids, week_ref):
    """Check tasks off by number. wb done 3 7"""
    _set_done(ctx, ids, week_ref, True)


@cli.command()
@click.argument("ids", nargs=-1, type=int, required=True)
@_week_option
@click.pass_context
def uncheck(ctx, ids, week_ref):
    """Un-check tasks by number. wb uncheck 3"""
    _set_done(ctx, ids, week_ref, False)


@cli.command()
@click.option("--list", "do_list", is_flag=True, help="Show what can be undone.")
@click.pass_context
def undo(ctx, do_list):
    """Undo the last change. Repeat to walk further back."""
    store = Store()
    entries = store.history()
    if do_list:
        if not entries:
            click.echo(f"  {DIM}nothing to undo{RESET}")
        for entry in entries[:10]:
            week, _, stamp = entry.stem.partition("__")
            click.echo(f"  {GREEN}{week}{RESET}  {DIM}{stamp}{RESET}")
        return
    key = store.undo()
    if key is None:
        raise click.ClickException("Nothing to undo.")
    click.echo(f"  {GREEN}↩{RESET} restored {key}  {DIM}({len(entries) - 1} step(s) left){RESET}")
    _echo_week(store.load(key))
    _render_if_enabled(ctx, store, store.load())


def _set_done(ctx, ids, week_ref, value: bool) -> None:
    """Shared body for done/undo."""
    store = Store()
    week = store.load(_resolve(week_ref))
    for number in ids:
        if not 1 <= number <= len(week.tasks):
            raise click.ClickException(f"No task {number} in {week.key}")
        task = week.tasks[number - 1]
        task.mark(value)
        mark = f"{GREEN}✓{RESET}" if value else f"{DIM}○{RESET}"
        click.echo(f"  {mark} {task.text}")
    store.save(week)
    _render_if_enabled(ctx, store, store.load())


@cli.command(name="rm")
@click.argument("ids", nargs=-1, type=int, required=True)
@_week_option
@click.pass_context
def remove(ctx, ids, week_ref):
    """Delete tasks by number."""
    store = Store()
    week = store.load(_resolve(week_ref))
    for number in sorted(ids, reverse=True):
        if not 1 <= number <= len(week.tasks):
            raise click.ClickException(f"No task {number} in {week.key}")
        task = week.tasks.pop(number - 1)
        click.echo(f"  {DIM}- {task.text}{RESET}")
    week.renumber()
    store.save(week)
    _render_if_enabled(ctx, store, store.load())


@cli.command(name="mv")
@click.argument("ids", nargs=-1, type=int, required=True)
@click.option("-w", "--week", "week_ref", default=None, help="Source week.")
@click.option("-t", "--to", "to_ref", required=True, help="Destination week.")
@click.pass_context
def move(ctx, ids, week_ref, to_ref):
    """Move tasks to another week. wb mv 4 5 --to 37"""
    store = Store()
    source = store.load(_resolve(week_ref))
    target = store.load(_resolve(to_ref))
    for number in sorted(ids, reverse=True):
        if not 1 <= number <= len(source.tasks):
            raise click.ClickException(f"No task {number} in {source.key}")
        task = source.tasks.pop(number - 1)
        moved = target.add(task.text, priority=task.priority, tags=task.tags)
        moved.done, moved.completed, moved.carried_from = task.done, task.completed, source.key
        click.echo(f"  {GREEN}→{RESET} {task.text}  {DIM}{source.key} → {target.key}{RESET}")
    source.renumber()
    store.save(source)
    store.save(target)
    _render_if_enabled(ctx, store, store.load())


@cli.command(name="ls")
@_week_option
@click.option("--open", "open_only", is_flag=True, help="Hide completed tasks.")
@click.option("--all", "show_all", is_flag=True, help="List every stored week.")
def list_tasks(week_ref, open_only, show_all):
    """Show a week (default: the current one)."""
    store = Store()
    if show_all:
        for key in store.keys():
            _echo_week(store.load(key), show_done=not open_only)
        return
    _echo_week(store.load(_resolve(week_ref)), show_done=not open_only)


@cli.command()
@_week_option
@click.option("--html", "keep_html", is_flag=True, help="Also write the HTML next to the PNG.")
@click.option("--width", type=int, default=None)
@click.option("--height", type=int, default=None)
def render(week_ref, keep_html, width, height):
    """Regenerate the wallpaper PNG now."""
    from .render import render as do_render

    store = Store()
    config = store.config
    if width:
        config.width = width
    if height:
        config.height = height
    week = store.load(_resolve(week_ref))
    path = do_render(week, config, store, keep_html=keep_html)
    click.echo(f"{GREEN}  ✓{RESET} {path}")


@cli.command()
@_week_option
def tui(week_ref):
    """Open the full-screen board."""
    from .tui import run

    run(_resolve(week_ref))


@cli.command()
@click.argument("text", nargs=-1, required=True)
@click.option("-y", "--yes", is_flag=True, help="Apply without confirming.")
@click.pass_context
def ai(ctx, text, yes):
    """Talk to the board. wb ai "check off the Kalli one and add invoices to week 37" """
    store = Store()
    config = store.config
    try:
        plan = agent_mod.capture(store, config, " ".join(text))
    except agent_mod.AgentError as exc:
        raise click.ClickException(str(exc))
    ops = plan["ops"]
    if not ops:
        click.echo(f"  {DIM}{plan.get('say') or 'Nothing to change.'}{RESET}")
        return
    click.echo()
    for op in ops:
        click.echo(f"  {DIM}·{RESET} {_describe(op)}")
    click.echo()
    if not yes and not click.confirm("  apply?", default=True):
        return
    for line in agent_mod.apply_ops(store, ops):
        click.echo(f"  {line}")
    if plan.get("say"):
        click.echo(f"\n  {GREEN}{plan['say']}{RESET}")
    _render_if_enabled(ctx, store, store.load())


def _describe(op: dict) -> str:
    """One-line human rendering of a planned operation."""
    kind = op.get("op")
    week = op.get("week", "")
    if kind == "add":
        return f"add to {week}: {op.get('text')}"
    if kind in ("done", "undone", "remove"):
        return f"{kind} in {week}: {op.get('match')}"
    if kind == "move":
        return f"move {op.get('match')} → {op.get('to_week')}"
    if kind == "edit":
        return f"edit in {week}: {op.get('match')} → {op.get('text')}"
    return f"{kind} {week}"


@cli.command()
@_week_option
@click.option("--ai", "use_ai", is_flag=True, help="Let the model decide what to carry.")
@click.pass_context
def rollover(ctx, week_ref, use_ai):
    """Carry unfinished tasks into the next week."""
    store = Store()
    source = store.load(_resolve(week_ref))
    target = store.load(shift_week(source.key, 1))
    pending = source.open_tasks
    if not pending:
        click.echo(f"  {GREEN}{source.key} is clean — nothing to carry.{RESET}")
        return

    carry_ids = {t.id for t in pending}
    if use_ai:
        try:
            plan = agent_mod.rollover_plan(store.config, source)
            carry_ids = set(plan.get("carry") or carry_ids)
            for dropped in plan.get("drop") or []:
                click.echo(f"  {DIM}- dropping: {source.get(dropped).text}{RESET}")
            if plan.get("say"):
                click.echo(f"  {GREEN}{plan['say']}{RESET}")
        except (agent_mod.AgentError, KeyError) as exc:
            click.echo(f"  {DIM}agent unavailable ({exc}); carrying everything{RESET}", err=True)

    for task in pending:
        if task.id not in carry_ids:
            source.remove(task.id)
            continue
        moved = target.add(task.text, priority=task.priority, tags=task.tags)
        moved.carried_from = source.key
        source.remove(task.id)
        click.echo(f"  {GREEN}→{RESET} {task.text}")
    source.renumber()
    store.save(source)
    store.save(target)
    click.echo(f"\n  {len(carry_ids)} carried into {target.key}")
    _render_if_enabled(ctx, store, store.load())


@cli.command()
@_week_option
@click.pass_context
def flavor(ctx, week_ref):
    """Let the model rewrite the mission, quote, headline and playlist for this week."""
    store = Store()
    week = store.load(_resolve(week_ref))
    try:
        data = agent_mod.flavor(store, store.config, week)
    except agent_mod.AgentError as exc:
        raise click.ClickException(str(exc))
    week.mission = [str(line) for line in data.get("mission", week.mission)][:4]
    week.tagline = data.get("tagline", week.tagline)
    week.quote_text = data.get("quote_text", week.quote_text)
    week.quote_author = data.get("quote_author", week.quote_author)
    week.headline_ja = data.get("headline_ja", week.headline_ja)
    week.headline_en = data.get("headline_en", week.headline_en)
    week.playlist_title = data.get("playlist_title", week.playlist_title)
    week.playlist_note = data.get("playlist_note", week.playlist_note)
    store.save(week)
    for line in week.mission:
        click.echo(f"  {line}")
    click.echo(f"  {GREEN}{week.tagline}{RESET}")
    click.echo(f'\n  "{week.quote_text}" — {week.quote_author}')
    click.echo(f"\n  {DIM}{week.playlist_title} — {week.playlist_note}{RESET}")
    _render_if_enabled(ctx, store, store.load())


@cli.command()
@click.argument("gauge", type=click.Choice(list(GAUGE_NAMES)), required=False)
@click.argument("value", required=False)
@_week_option
@click.pass_context
def status(ctx, gauge, value, week_ref):
    """Show the gauges, or pin one. wb status focus 90 / wb status focus auto"""
    from . import metrics, stats

    store = Store()
    week = store.load(_resolve(week_ref))

    if gauge is None:
        for g in metrics.compute(week, store, stats.collect(store.config), store.config):
            tag = f"{DIM} (pinned){RESET}" if g["pinned"] else ""
            click.echo(f"  {g['label']:<10}{g['value']:>4}%{tag}")
        click.echo(f"\n{DIM}  computed from your tasks and commits; "
                   f"pin one with `wb status focus 90`{RESET}")
        return

    if value is None:
        raise click.ClickException("Give a number 0-100, or 'auto' to un-pin.")
    if str(value).lower() in ("auto", "clear", "none"):
        week.overrides.pop(gauge, None)
        click.echo(f"  {GREEN}{gauge.upper()} → auto{RESET}")
    else:
        try:
            number = int(value)
        except ValueError:
            raise click.ClickException(f"Not a number: {value!r}")
        week.overrides[gauge] = max(0, min(100, number))
        click.echo(f"  {GREEN}{gauge.upper()} → {week.overrides[gauge]}% (pinned){RESET}")
    store.save(week)
    _render_if_enabled(ctx, store, store.load())


@cli.command()
@click.argument("lines", nargs=-1)
@_week_option
@click.option("--tagline", default=None)
@click.pass_context
def mission(ctx, lines, week_ref, tagline):
    """Set the mission objective lines. wb mission "Ship things." "Help people." """
    store = Store()
    week = store.load(_resolve(week_ref))
    if lines:
        week.mission = list(lines)[:4]
    if tagline:
        week.tagline = tagline
    store.save(week)
    for line in week.mission:
        click.echo(f"  {line}")
    _render_if_enabled(ctx, store, store.load())


@cli.command(name="ascii")
@click.argument("image", type=click.Path(exists=True, dir_okay=False), required=False)
@click.option("--width", default=None, type=int, help="Output columns (default 60 braille, 48 ascii).")
@click.option("--mode", type=click.Choice(["braille", "line", "photo"]), default="braille",
              show_default=True,
              help="braille = 2x4 dots per cell, most detail; line = drawings; photo = shaded ASCII.")
@click.option("--invert", is_flag=True, help="Source is dark ink on a light background.")
@click.option("--threshold", default=None, type=float, help="Ink/edge cutoff, 0-1.")
@click.option("--no-dither", is_flag=True, help="Braille: hard threshold instead of dithering.")
@click.option("--use", "use_name", default=None, help="Switch to a piece from the gallery.")
@click.option("--list", "do_list", is_flag=True, help="List the bundled gallery.")
@click.option("--save/--no-save", default=True, help="Write it into the board.")
@click.pass_context
def ascii_cmd(ctx, image, width, mode, invert, threshold, no_dither, use_name, do_list, save):
    """Set the character art (DAILY_REMINDER.EXE). Give it an image, pick from --list, or show the current one."""
    from .config import ASSETS_DIR

    target = ASSETS_DIR / "ascii.txt"
    gallery = ASSETS_DIR / "gallery"

    if do_list:
        for item in sorted(gallery.glob("*.txt")):
            lines = [ln for ln in item.read_text(encoding="utf-8").splitlines() if ln.strip()]
            shape = f"{max((len(ln) for ln in lines), default=0)}x{len(lines)}"
            click.echo(f"  {GREEN}{item.stem:<14}{RESET}{DIM}{shape}{RESET}")
        click.echo(f"\n{DIM}  wb ascii --use <name>{RESET}")
        return

    if use_name:
        source = gallery / f"{use_name}.txt"
        if not source.exists():
            raise click.ClickException(f"No gallery piece named {use_name!r}. Try: wb ascii --list")
        art = source.read_text(encoding="utf-8")
        target.write_text(art, encoding="utf-8")
        click.echo(art)
        click.echo(f"{GREEN}  ✓{RESET} {DIM}now using {use_name}{RESET}")
        _render_if_enabled(ctx, Store(), Store().load())
        return

    if image is None:
        click.echo(target.read_text(encoding="utf-8") if target.exists() else "  (none set)")
        return

    from .asciiart import from_image, from_line_art, to_braille

    if mode == "braille":
        art = to_braille(image, width=width or 60, invert=invert, dither=not no_dither,
                         **({"threshold": threshold} if threshold else {}))
    elif mode == "line":
        art = from_line_art(image, width=width or 48, invert=invert,
                            **({"ink_threshold": threshold} if threshold else {}))
    else:
        art = from_image(image, width=width or 48, invert=invert,
                         **({"edge_threshold": threshold} if threshold else {}))
    click.echo(art)
    if not save:
        return
    target.write_text(art + "\n", encoding="utf-8")
    click.echo(f"\n{GREEN}  ✓{RESET} {DIM}saved to {target}{RESET}")
    _render_if_enabled(ctx, Store(), Store().load())


@cli.command(name="art")
@click.argument("image", type=click.Path(exists=True, dir_okay=False), required=False)
@click.option("--generate", "prompt", default=None, metavar="PROMPT",
              help="Describe a scene; the model writes it as SVG and it's rendered in.")
@click.option("--reset", is_flag=True, help="Go back to the bundled default.")
@click.pass_context
def art_cmd(ctx, image, prompt, reset):
    """Set the background art: point at your own image, generate one, or show the current one.

    wb art photo.jpg                 use your own image
    wb art --generate "rainy Kyoto street at night, neon signs"
    wb art --reset                   back to the bundled default
    """
    store = Store()
    config_obj = store.config

    if reset:
        config_obj.art = ""
        save_config(config_obj)
        click.echo(f"{GREEN}  ✓{RESET} {DIM}back to the bundled default{RESET}")
        _render_if_enabled(ctx, store, store.load())
        return

    if prompt:
        from . import artgen

        click.echo(f"{DIM}  generating…{RESET}")
        try:
            path = artgen.generate(config_obj, prompt)
        except artgen.ArtGenError as exc:
            raise click.ClickException(str(exc))
        config_obj.art = str(path)
        config_obj.art_prompt = prompt
        save_config(config_obj)
        click.echo(f"{GREEN}  ✓{RESET} {path}")
        _render_if_enabled(ctx, store, store.load())
        return

    if image:
        art_dir = config_obj.data_path / "art"
        art_dir.mkdir(parents=True, exist_ok=True)
        dest = art_dir / Path(image).name
        shutil.copy(image, dest)
        config_obj.art = str(dest)
        save_config(config_obj)
        click.echo(f"{GREEN}  ✓{RESET} {dest}")
        _render_if_enabled(ctx, store, store.load())
        return

    current = config_obj.art_path
    kind = "bundled default" if not config_obj.art else "custom"
    click.echo(f"  {current}{DIM}  ({kind}){RESET}")


@cli.command()
@click.option("--edit", is_flag=True, help="Open config.json in $EDITOR.")
def config(edit):
    """Show or edit configuration."""
    current = load_config()
    if not CONFIG_PATH.exists():
        save_config(current)
    if edit:
        click.edit(filename=str(CONFIG_PATH))
        return
    click.echo(f"{DIM}  {CONFIG_PATH}{RESET}")
    click.echo(CONFIG_PATH.read_text(encoding="utf-8"))


@cli.command()
def doctor():
    """Check that everything this needs is actually installed."""
    config_obj = load_config()
    ok = True

    def check(label: str, good: bool, detail: str = "", required: bool = True) -> None:
        nonlocal ok
        if required:
            ok = ok and good
        mark = f"{GREEN}✓{RESET}" if good else (f"\033[31m✗{RESET}" if required else f"{DIM}·{RESET}")
        click.echo(f"  {mark} {label}{DIM}{'  ' + detail if detail else ''}{RESET}")

    check("data dir", True, str(config_obj.data_path))
    out = config_obj.output_path
    check("watched folder exists", out.is_dir(), str(out))
    try:
        import playwright  # noqa: F401

        have_pw = True
    except ImportError:
        have_pw = False
    check("playwright installed", have_pw)
    if have_pw:
        from playwright.sync_api import sync_playwright

        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                browser.close()
            check("chromium available", True)
        except Exception as exc:
            check("chromium available", False, str(exc)[:70])
    try:
        import psutil  # noqa: F401

        check("psutil installed", True)
    except ImportError:
        check("psutil installed", False)
    check("art asset", config_obj.art_path.exists(), str(config_obj.art_path.name))

    from . import github

    gh_wanted = config_obj.commit_source in ("auto", "github")
    gh_required = config_obj.commit_source == "github"
    gh_ok = github.available()
    if gh_wanted:
        if gh_ok:
            user = config_obj.github_user or github.current_user()
            check("github (gh)", bool(user), user or "no username — set github_user",
                  required=gh_required)
        else:
            check("github (gh)", False, "not installed or not `gh auth login`ed",
                  required=gh_required)
    active = agent_mod.backend(config_obj)
    if active == "api":
        check("agent: API", True, f"{config_obj.api_model}  key from {agent_mod.api_key(config_obj)[1]}")
    else:
        detail = config_obj.claude_bin
        if config_obj.backend == "api":
            detail += "  (backend=api but no key found — fell back)"
        check("agent: claude CLI", agent_mod.available(config_obj), detail)
    if not out.is_dir():
        click.echo(f"\n  {DIM}mkdir -p {out}{RESET}")
    sys.exit(0 if ok else 1)


@cli.command()
@click.pass_context
def sync(ctx):
    """Refresh commit activity: force a GitHub fetch, and `git fetch` your repos.

    `wb done` and the like never do this on their own — that would put a
    network round trip on every command. Run this by hand (or from cron)
    when you've just pushed from another machine and want SHIPPED / the
    terminal log to catch up immediately, instead of waiting out the cache.
    """
    from . import github

    store = Store()
    config = store.config

    if config.commit_source in ("auto", "github"):
        user = config.github_user or (github.available() and github.current_user())
        if not user:
            click.echo(f"  {DIM}github: not signed in — run `gh auth login`, "
                       f"or set github_user in the config{RESET}")
        else:
            subjects, count = github.recent_commits(
                user, days=config.commit_days, cache_path=config.github_cache,
                ttl=config.github_cache_seconds, force=True,
            )
            click.echo(f"  {GREEN}✓{RESET} github: {count} commit(s) in the last "
                       f"{config.commit_days}d for {user}")

    if config.git_repos:
        import shutil
        import subprocess

        if not shutil.which("git"):
            click.echo(f"  {DIM}git: not installed, skipping local fetch{RESET}")
        for repo in config.git_repos:
            path_ = Path(repo).expanduser()
            if not (path_ / ".git").exists():
                click.echo(f"  {DIM}✗ {repo} — not a git repo{RESET}")
                continue
            try:
                result = subprocess.run(
                    ["git", "-C", str(path_), "fetch", "--all", "--quiet"],
                    capture_output=True, text=True, timeout=30, check=False,
                )
            except (subprocess.SubprocessError, OSError) as exc:
                click.echo(f"  {DIM}✗ {repo} — {exc}{RESET}")
                continue
            if result.returncode == 0:
                click.echo(f"  {GREEN}✓{RESET} git: fetched {repo}")
            else:
                click.echo(f"  {DIM}✗ {repo} — {result.stderr.strip()[:80]}{RESET}")

    if config.commit_source not in ("auto", "github") and not config.git_repos:
        click.echo(f"  {DIM}nothing to sync — set git_repos or commit_source{RESET}")

    _render_if_enabled(ctx, store, store.load())


@cli.command()
def path():
    """Print where the data lives."""
    store = Store()
    click.echo(store.root)


def main() -> None:
    """Console entry point."""
    cli(obj={})


if __name__ == "__main__":
    main()
