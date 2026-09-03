# weekboard — cheat sheet

## One-time setup

    cd ~/workFiles/freelanceFiles/wallpapersetter
    ./install.sh                              # venv + deps + chromium + first render
    sudo ln -s $PWD/wb /usr/local/bin/wb      # so `wb` works from anywhere

`install.sh` already wrote the LaunchAgent — start it (survives reboots):

    launchctl bootstrap gui/"$(id -u)" ~/Library/LaunchAgents/com.weekboard.wallpapersetter.plist

Say yes when macOS asks about controlling System Events, or the wallpaper never changes.

    wb doctor        # confirms everything, incl. which AI backend is live

The API key is already in `.env` — nothing to configure.

## Every day

    wb                        show this week
    wb add "Call Harry"       add a task
    wb done 3                 check off number 3
    wb tui                    full-screen board (space = check, ? = all keys, q = quit)
    wb ai "..."               plain language: add, check off, move, reschedule

All of them redraw the wallpaper automatically. That's the whole loop.

## Weeks

    wb add "Prep talk" -w 37   add to week 37
    wb add "Fix bug" -p high   high priority (shown in white)
    wb ls -w next              look at next week
    wb ls --open               hide completed
    wb mv 4 --to 37            push task 4 to week 37
    wb uncheck 3               un-check
    wb rm 9                    delete
    wb undo                    undo the last change (repeat to go further back)

Week refs: `37`, `2026-W37`, `next`, `prev`, `+2`, `-1`. Default is always the
current week — the board only shows the week you're in.

## Friday

    wb rollover --ai          carry unfinished work into next week, drop the stale
    wb flavor                 AI rewrites mission + quote around this week's work

## Gauges

    wb status                  FOCUS / MOMENTUM / SHIPPED / DONE, all computed
    wb status focus 90         pin one by hand
    wb status focus auto       back to computed

SHIPPED reads 0 until you list your repos in `wb config --edit`:

    "git_repos": ["~/workFiles/freelanceFiles/pungar.is", "..."]

Or point it at GitHub instead of local clones (sees every machine you push
from, not just this one):

    wb sync                    force-refresh commit activity right now
    "commit_source": "auto"    "auto" (default) | "github" | "git"

## Now and then

    wb ascii --list           swap the character art
    wb ascii photo.jpg        make braille art from any image
    wb config --edit          settings
    wb render                 force a redraw
    wb doctor                 health check
    wb sync                   force-refresh commit activity from GitHub/git

## Cost

Only `wb ai`, `wb flavor` and `wb rollover --ai` call a model — via the API on
Haiku, about $0.001 each. Everything else is local and free.

## Customization map

What's adjustable, and how, panel by panel:

| panel | how |
|---|---|
| Mission Objective | `wb mission "line one" "line two" --tagline "..."`, or `wb flavor` (AI, tuned to this week's actual tasks) |
| Quote of the week | `wb flavor`, or `wb ai "set the quote to '...' by ..."` |
| Kaizen headline (改善は毎日の積み重ねだ) | `wb flavor` / `wb ai` only — no dedicated flag yet |
| Tools of the day | `"tools"` in `wb config --edit` — up to 7 names from the built-in icon set (`VS CODE`, `ZSH`, `GIT`, `NOTION`, `DOCKER`, `FIGMA`, `COFFEE`, `CLAUDE`, `SLACK`, `PYTHON`, `LINEAR`, `MUSIC`, `DESIGN`, `SHIP`, `CURSOR`, `CHROME`, `GITHUB`) — anything else renders a plain diamond |
| Playlist | `"playlist_title"` / `"playlist_note"` in config — text only, no real audio hookup |
| System Status gauges | computed automatically; pin one with `wb status focus 90`, back to auto with `wb status focus auto` |
| Accent color / artwork / ASCII character | `"accent"` (hex) in config; `wb ascii --use ninja-b` or `wb ascii yourphoto.jpg`; `"art"` in config for the background photo |

Not yet configurable — hardcoded in `render.py` / the template, but a quick
add if wanted: the **Focus Mode** word loop (`FOCUS / BUILD / DELIVER /
REPEAT`), the **DAILY_REMINDER.EXE** code block (`while(alive){...}` and its
comments), and the **"NO EXCUSES / ONLY RESULTS"** panel.

Everything per-week (mission, quote, headline, tasks, overrides) also just
lives in plain JSON at `data/weeks/2026-W36.json` — hand-editing it always
works, even for things no command covers yet.
