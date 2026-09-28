# Ambient apps

Non-interactive. Fills a tmux pane and is looked at, not driven.

## Contract

- Render on a timer, no input handling, no mouse
- Build each frame as one string and write it once (no clear-then-draw)
- Pad frames to full pane dimensions rather than clearing between
  frames
- Enter the alternate screen on start, leave it on every exit path
- Hide the cursor on start, restore it on every exit path
- Handle SIGINT, SIGTERM, and SIGHUP identically (tmux sends SIGHUP
  on pane close)
- Teardown must tolerate a dead pty (wrap writes, swallow OSError)
- Handle SIGWINCH by setting a flag; the handler must not draw
- Sleep to the next interval boundary, not a fixed duration
- Define behavior at small sizes explicitly, never undefined
- Respect NO_COLOR, degrade gracefully when stdout is not a tty
- Fall back to ASCII when the terminal can't render block characters

## Stack

Raw ANSI escapes, stdlib only. No curses, no Textual, no Rich.
