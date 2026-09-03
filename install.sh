#!/usr/bin/env bash
# One-shot setup for weekboard. Safe to re-run.
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$PWD"

echo "→ virtualenv"
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -r requirements.txt

echo "→ chromium for rendering"
.venv/bin/playwright install chromium

echo "→ watched folder"
mkdir -p ~/Downloads/desktop_plans

echo "→ first render"
./wb render

echo "→ wallpaper watcher LaunchAgent"
PLIST="$HOME/Library/LaunchAgents/com.weekboard.wallpapersetter.plist"
mkdir -p "$HOME/Library/LaunchAgents"
sed -e "s#__ROOT__#$ROOT#g" -e "s#__HOME__#$HOME#g" \
  com.weekboard.wallpapersetter.plist.template > "$PLIST"

cat <<TXT

Done.

  ./wb                 show this week
  ./wb tui             full-screen board
  ./wb doctor          check the setup

Put it on your PATH:
  ln -s $ROOT/wb /usr/local/bin/wb

Start the wallpaper watcher (already written to $PLIST):
  launchctl bootstrap gui/"\$(id -u)" "$PLIST"

TXT
