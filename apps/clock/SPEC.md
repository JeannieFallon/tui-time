# clock

Big-digit wall clock for an idle pane.

## v1 scope

- Big-digit HH:MM:SS, centered in the pane
- 24-hour, no config, no flags
- Redraws once per second
- Survives resize
- Exits clean, leaves the terminal as it found it

Anything not on this list is v2.

## v2 backlog

Not building these now. Recorded so they stop taking up space.

- Date line under the time
- 12-hour toggle
- Seconds off
- Blinking colon
- Color config / theme
- Second timezone
- Degraded tiny-mode rendering

## Build order

Each step should run and be verifiable before the next starts.

1. **Frame loop.** Alternate screen, hide cursor, draw current time as
   plain text, redraw each second, exit clean on Ctrl-C.
   *Verify: cursor is visible after exit. Scrollback is untouched.*

2. **Signal teardown.** Add SIGTERM and SIGHUP alongside SIGINT. All
   three run the same teardown.
   *Verify: close the tmux pane directly, not Ctrl-C. Then run
   something else in a new pane and confirm the cursor is normal.*

3. **Big digits.** Define each digit 0-9 as a small grid of block
   characters. Render the time from the grids. Center in the pane.
   *Verify: looks right at a few pane widths. This step is taste and
   will take the most iteration.*

4. **Resize.** SIGWINCH sets a flag, handler does not draw. Main loop
   sees the flag, clears once, re-centers, redraws.
   *Verify: drag the tmux pane divider slowly. No artifacts, no
   stale digits left on screen.*

5. **Boundary alignment.** Replace naive one-second sleep with sleep
   until the next wall-clock second boundary.
   *Verify: watch for a full minute. No skipped or repeated second.*

6. **Small-terminal fallback.** Decide and implement behavior below
   the size where big digits fit. Either compact HH:MM or a short
   message. Never undefined.
   *Verify: resize down to roughly 10x3.*

## Failure modes

Things that will bite, in rough order of likelihood.

- **Flicker.** Clearing then drawing produces a visible blank frame.
  Build the whole frame as one string, cursor-home with `\033[H`,
  single write. Clear only on resize.

- **Drift.** `time.sleep(1)` accumulates error and the display will
  eventually skip a second. Sleep to the next second boundary.

- **Resize artifacts.** Drawing inside the SIGWINCH handler races the
  main loop. Handler sets a flag and returns, nothing else.

- **Missed exit paths.** tmux sends SIGHUP on pane close, SIGTERM on
  kill, SIGINT on Ctrl-C. Miss one and the cursor stays hidden in
  whatever runs next. This is the bug most likely to survive to v2.

- **Scrollback pollution.** Without the alternate screen
  (`\033[?1049h` on start, `\033[?1049l` on exit), every frame
  scrolls into history.

- **Undefined small-size behavior.** A pane too narrow for big digits
  with no fallback is what makes an app feel broken rather than
  small.

- **Unicode assumptions.** Block characters need font and locale
  cooperation. Detect and fall back to ASCII rather than emitting
  replacement boxes.

## Difficulty

- Nothing here is algorithmically hard.
- Most of the time goes into step 3, making the digit grid look right
  at multiple sizes. That is taste and iteration, not engineering.
- Expect v1 working in one session. Expect a second session fiddling
  with how the digits look.
