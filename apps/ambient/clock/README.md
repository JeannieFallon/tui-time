# clock

Wall clock that fills a pane with the local time (`HH:MM:SS`, 24-hour)
in big block digits, centered, with an optional theme.

## Usage

```
python3 apps/ambient/clock/clock.py
python3 apps/ambient/clock/clock.py --theme night
```

`--theme` is the only flag. It takes `plain` (the default), `night`,
`rain` or `wave`. An unknown name exits with status 2 and a usage
error that lists the valid names, and `--help` lists them too.

The clock runs until it gets SIGINT (Ctrl-C), SIGTERM or SIGHUP (a
closed tmux pane). All three restore the cursor and the main screen
and exit with status 0. It draws on the alternate screen, so nothing
goes into scrollback.

Each frame is written in one write and covers every cell of the pane.
Frames land on exact boundaries of the frame rate, which always
include each whole second, so the displayed second changes on the
wall-clock second and doesn't drift.

## Pane sizes

The clock draws the largest of these size tiers that fits the pane:

| Tier | Needs (block digits) | Needs (ASCII digits) |
|---|---|---|
| big `HH:MM:SS` | 41×5 | 41×10 |
| big `HH:MM` | 26×5 | 26×10 |
| plain-text `HH:MM:SS` | 8×1 | 8×1 |
| blank pane | anything smaller | anything smaller |

Nothing is ever clipped. On resize the screen is cleared once and the
tier is picked again, so the clock grows back to big digits when the
pane is enlarged. The digits don't scale beyond the big tiers. A large
pane shows the same size of digits, with more space around them.

## Themes

A theme sets the digit color, and some add an effect. Colors come
from the 256-color palette and apply only to the foreground. No theme
paints the background.

- **plain**: the terminal's default foreground, no effect, one frame a
  second.
- **night**: light blue digits. Sparse stars fade in and out on a
  grayscale ramp around the clock, and each star reappears somewhere
  new after it fades. There is about one star per 60 cells, and at any
  moment roughly 60% of them are lit. 4 frames a second.
- **rain**: pale blue digits. About a third of the columns carry a drop
  that falls at 2–6 rows a second, a bright lead glyph trailing a
  dimmer tail. 8 frames a second.
- **wave**: a cyan-to-magenta gradient moves left to right across the
  digits. It draws nothing outside them. 8 frames a second.

Effects show only in the big `HH:MM:SS` tier. They never draw inside
the digits' bounding box or the 1-cell margin around it. In the
smaller tiers every theme draws only its digits, in its static color
(cyan for `wave`), at one frame a second. A resize restarts the effect with
new random positions.

### NO_COLOR

When `NO_COLOR` is set to a non-empty value, the clock emits no color
escapes under any theme. `night` and `rain` keep their effect in
monochrome, their fades shown only by the choice of glyph. `wave`
draws exactly what `plain` draws, at one frame a second.

### ASCII fallback

When stdout's encoding can't encode every non-ASCII character the clock
draws, block digits and effect glyphs alike (for example
`PYTHONIOENCODING=ascii` or `cp437`), the digits are drawn with `#` at 10 rows tall. Stars
become `.` `+` `*` and raindrops `|` `:` `.`. With Unicode, the digits
are half-block characters at 5 rows tall, stars are `·` `✦` and
raindrops are `│` `╎` `·`.

## Not a terminal

When stdout isn't a tty, as with a pipe, a redirect or cron, the clock
prints `HH:MM:SS` and a newline once and exits 0. It emits no escape
codes.

## Known limitations

- 24-hour local time only. No date, no 12-hour mode, and seconds can't
  be turned off.
- Colors assume a 256-color terminal. There are no 16-color or
  truecolor palettes.
- Unicode support is judged from stdout's encoding, not from the font.
  A UTF-8 terminal whose font lacks the block, star or rain glyphs
  shows replacement boxes.
- Stars and raindrops jump to new positions on every resize.
- The theme is fixed at launch. Changing it means restarting the clock.
