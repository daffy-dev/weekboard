# weekboard — cheat sheet

## One-time setup

    cd ~/workFiles/freelanceFiles/wallpapersetter
    ./install.sh                              # venv + deps + chromium + first render
    sudo ln -s $PWD/wb /usr/local/bin/wb      # so `wb` works from anywhere

Start the wallpaper watcher (survives reboots):

    cp com.daffy.wallpapersetter.plist ~/Library/LaunchAgents/
    launchctl bootstrap gui/"$(id -u)" ~/Library/LaunchAgents/com.daffy.wallpapersetter.plist

Say yes when macOS asks about controlling System Events, or the wallpaper never changes.

    wb doctor        # confirms everything, incl. which AI backend is live

The API key is already in .env — nothing to configure.

## Every day

    wb                        show this week
    wb add "Call Harry"       add a task
    wb done 3                 check off number 3
    wb tui                    full-screen board (space = check, q = quit)
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

## Now and then

    wb ascii --list           swap the character art
    wb ascii photo.jpg        make braille art from any image
    wb config --edit          settings
    wb render                 force a redraw
    wb doctor                 health check

## Cost

Only `wb ai`, `wb flavor` and `wb rollover --ai` call a model — via the API on
Haiku, about $0.001 each. Everything else is local and free.

----
Here's the full map of what's actually adjustable right now, panel by panel:

Mission Objective — fully yours. wb mission "Ship things." "Help people." --tagline "Level up." sets it by hand (up to 4 lines + a tagline), or wb flavor lets the model rewrite it based on what's actually on your board that week. It's stored per-week, so it's fine for it to change every week.

Quote of the week — same deal, just no dedicated flag yet: wb flavor writes it, or you can say it directly to the agent — wb ai "set the quote to 'move fast' by nobody in particular". It's a real op the model understands (quote, with text + author).

Kaizen headline (the 改善は毎日の積み重ねだ / KAIZEN IS DAILY block near the top) — also per-week, also only settable via wb flavor / wb ai right now, no manual CLI flag.

Tools of the day — config, not per-week: "tools" in config.json (wb config --edit), a list of up to 7 names. It's not free text though — each name maps to a built-in icon (VS CODE, ZSH, GIT, NOTION, DOCKER, FIGMA, COFFEE, CLAUDE, SLACK, PYTHON, LINEAR, MUSIC, DESIGN, SHIP, CURSOR, CHROME, GITHUB); anything else just renders a plain diamond.

Playlist — config: "playlist_title" and "playlist_note". Static text, no actual audio hookup — it's just for vibes.

System Status gauges (FOCUS/MOMENTUM/SHIPPED/DONE) — computed automatically from your tasks and commits, but any one can be pinned: wb status focus 90, back to auto with wb status focus auto.

Accent color, artwork, ASCII character — "accent" (hex) in config; wb ascii --use ninja-b / wb ascii yourphoto.jpg for the character in DAILY_REMINDER.EXE; "art" in config points at the background photo (there's also art_prompt if you regenerate it with an image model later).

Now the honest part — Focus Mode (that FOCUS / BUILD / DELIVER / REPEAT word loop) and the DAILY_REMINDER.EXE code block (while(alive){ focus(); build(); ship(); ...} and its two comment lines) and the "NO EXCUSES / ONLY RESULTS" panel are currently just hardcoded constants in render.py/the template — there's no config field or command for any of them yet. If you want those editable too (say, focus_words in config, or a wb loop command for the code block), that's a quick add — just say the word and I'll wire it up the same way tools/playlist work.

And as a catch-all: everything per-week (mission, quote, headline, tasks, overrides) lives in plain JSON at data/weeks/2026-W36.json, so if a command doesn't exist for something yet, hand-editing that file always works too.
