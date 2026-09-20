# tui-time

Small TUI apps to jazz up idle panes. Each app is standalone and
non-interactive: it fills a tmux pane and is looked at, not driven.

## Pane contract

Every app in this repo must:
- Render on a timer, no input handling, no mouse
- Build each frame as one string and write it once (no clear-then-draw)
- Enter the alternate screen on start, leave it on every exit path
- Hide the cursor on start, restore it on every exit path
- Handle SIGINT, SIGTERM, and SIGHUP identically (tmux sends SIGHUP on
  pane close)
- Handle SIGWINCH by setting a flag; the handler must not draw
- Define behavior at small sizes explicitly, never undefined
- Respect NO_COLOR, degrade gracefully when stdout is not a tty
- Fall back to ASCII when the terminal can't render block characters

## Conventions

- Python 3, stdlib only, raw ANSI escapes
- No curses, no Textual, no Rich, unless an app is interactive (none are yet)
- One directory per app under apps/, one file where possible
- PEP 723 inline metadata if an app ever needs a dependency
- Run as: uv run apps/<name>/<name>.py

## Non-goals

- No shared framework. Duplicate until the third repetition.
- No config files in v1 of anything.
- No packaging until an app outgrows a single file.
