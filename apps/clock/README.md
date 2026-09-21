# clock

Big-digit wall clock for an idle tmux pane.

## Usage

```
python3 apps/clock/clock.py
```

Fills the pane with the current time (`HH:MM:SS`, 24-hour) in big block
digits, centered, redrawing once a second. No flags, no config. Exit with
Ctrl-C, or by closing the pane/killing the process — cursor and screen
are restored on any of SIGINT, SIGTERM, or SIGHUP.

Falls back to plain ASCII glyphs if the terminal encoding can't render
block characters.

## Status

Implements SPEC.md build order steps 1–3 (frame loop, signal teardown,
big digits). Not yet implemented: resize handling, drift-free second
boundaries, small-terminal fallback. See SPEC.md for the full plan.
