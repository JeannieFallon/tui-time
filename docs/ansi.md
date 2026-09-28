# ANSI Escape Reference

The full ANSI/VT100 surface is large. The subset an ambient pane app
needs is small enough to memorize.

All sequences begin with the escape character, `0x1b`. In Python this
is written `\033` (octal), `\x1b` (hex), or `\e` in shell contexts.

`CSI` below means Control Sequence Introducer: `\033[`.

---

## Screen buffer

| Sequence | Effect |
|---|---|
| `\033[?1049h` | switch to alternate screen |
| `\033[?1049l` | switch back to primary screen |

The alternate screen is a second buffer with no scrollback. Contents
are discarded on exit, and the primary buffer is restored exactly as
it was. This is what vim, less, and top use.

Enter on setup, leave on teardown. Always both.

## Cursor

| Sequence | Effect |
|---|---|
| `\033[?25l` | hide cursor |
| `\033[?25h` | show cursor |
| `\033[H` | move to row 1, col 1 (home) |
| `\033[<r>;<c>H` | move to row r, col c (1-indexed) |
| `\033[s` | save cursor position |
| `\033[u` | restore saved position |

Coordinates are 1-indexed, not 0-indexed. Row and column, in that
order, which is the opposite of the (x, y) convention.

`\033[H` is the workhorse. Move home, write a full-pane frame,
repeat.

## Erasing

| Sequence | Effect |
|---|---|
| `\033[2J` | clear entire screen |
| `\033[J` | clear from cursor to end of screen |
| `\033[2K` | clear entire current line |
| `\033[K` | clear from cursor to end of line |

Used only on resize. In steady state, overwriting is better than
clearing: clearing produces a visible blank frame.

## Color

Three color models, in increasing fidelity.

**16 colors (widest support):**

| Sequence | Effect |
|---|---|
| `\033[30m` to `\033[37m` | foreground, black through white |
| `\033[40m` to `\033[47m` | background |
| `\033[90m` to `\033[97m` | bright foreground |
| `\033[100m` to `\033[107m` | bright background |

**256 colors:**

```
\033[38;5;<n>m    foreground, n in 0-255
\033[48;5;<n>m    background
```

Index layout: 0-15 are the standard colors, 16-231 are a 6x6x6 RGB
cube, 232-255 are a 24-step grayscale ramp. The grayscale ramp is
useful for fades and sparklines.

**24-bit truecolor:**

```
\033[38;2;<r>;<g>;<b>m    foreground
\033[48;2;<r>;<g>;<b>m    background
```

Supported by most modern terminals. Check `$COLORTERM` for `truecolor`
or `24bit` before relying on it.

Note that tmux needs explicit configuration to pass truecolor through:

```
set -ga terminal-overrides ",*256col*:Tc"
```

Without it, truecolor sequences are degraded to 256 colors and
gradients band visibly.

## Attributes

| Sequence | Effect |
|---|---|
| `\033[0m` | reset all attributes |
| `\033[1m` | bold |
| `\033[2m` | dim |
| `\033[3m` | italic (spotty support) |
| `\033[4m` | underline |
| `\033[7m` | reverse video |

`\033[0m` resets color and attributes together. Emit it at the end of
any styled run, and as part of teardown.

Reverse video is worth knowing: it swaps foreground and background
without needing to know either. Useful for a cursor or a highlight
when you do not control the theme.

---

## Block characters

Not escape sequences, just Unicode, but they are how ambient apps draw.

| Char | Codepoint | Name |
|---|---|---|
| `█` | U+2588 | full block |
| `▀` | U+2580 | upper half block |
| `▄` | U+2584 | lower half block |
| `▌` | U+258C | left half block |
| `▐` | U+2590 | right half block |
| `░` `▒` `▓` | U+2591-2593 | light, medium, dark shade |

**The half-block trick.** Terminal cells are roughly twice as tall as
they are wide. Rendering with `█` gives you non-square pixels, so
circles look like ellipses.

Using `▀` with a foreground color for the top half and a background
color for the bottom half gives you two independently colored pixels
per cell. That doubles vertical resolution and makes the pixels
approximately square.

```python
# top and bottom are (r, g, b)
f"\033[38;2;{tr};{tg};{tb}m\033[48;2;{br};{bg};{bb}m▀"
```

This single trick is how most terminal image viewers and plasma
effects work.

**Eighth blocks** (U+2581 through U+2588, `▁▂▃▄▅▆▇█`) give eight
vertical levels within one cell. This is what sparklines are built
from.

---

## Terminal size

Not an escape sequence. Python provides it directly:

```python
import os
cols, rows = os.get_terminal_size()
```

Returns a named tuple, `(columns, lines)`. Raises `OSError` if stdout
is not a terminal, which is also a useful signal.

Re-read it every frame, or on `SIGWINCH`. It is not constant.

---

## Inspecting output

Escape sequences are invisible by definition. To see what an app
actually emits:

```
python3 app.py > /tmp/out & sleep 3; kill %1
cat -v /tmp/out | head -c 400
```

`cat -v` renders the escape byte as `^[`, so `\033[H` appears as
`^[[H`. Two things to look for:

- One frame per interval, not a continuous stream
- No `\033[2J` in the steady-state loop. If it clears every frame,
  that is the flicker bug.
