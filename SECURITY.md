# Security Policy

weekboard is a local CLI plus a wallpaper renderer — there's no server, no
accounts, and no listening network port. This describes what it actually
touches, so you can judge the attack surface yourself rather than take that
on faith.

## What it does with your data

- Tasks, mission text, quotes, etc. live in plain, unencrypted JSON under
  `data/weeks/`. Nothing is stored anywhere else, and nothing leaves your
  machine unless you use one of the AI features below.
- `wb ai`, `wb flavor`, and `wb art --generate` send board content (task
  text, or a text prompt) to either the local `claude` CLI or the
  Anthropic API, depending on `"backend"` in your config. Don't put
  anything in a task, prompt, or `.env` you wouldn't want leaving the
  machine when those commands run.
- `wb sync`, and the `"github"` commit source, call the GitHub API via the
  `gh` CLI, reusing whatever auth `gh` already has — no separate token is
  requested or stored.
- `wb render` writes an image to `output_dir` (`~/Downloads/desktop_plans`
  by default) and, via `wallpaper_setter.py`, asks macOS's System Events
  to set it as the desktop background. That's the only place this tool
  reaches outside its own project directory.

## API keys

`ANTHROPIC_API_KEY` is read from the environment, an `api_key_file` you
point at, or this project's own `.env` (gitignored, never committed).
Nothing else in the project handles secrets.

## Reporting a vulnerability

Please use GitHub's private vulnerability reporting (the repo's **Security**
tab → "Report a vulnerability") rather than a public issue, so a fix can go
out before details are public. This is a solo side project, not a funded
product — I'll do my best to respond within a few days, not guaranteed SLAs.

## Scope

This is a personal tool, not something hardened against hostile input. It's
built to be run by the person who owns the machine it's on, against their
own data — not to safely process untrusted input from anyone else.
