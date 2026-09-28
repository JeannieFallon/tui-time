# Anatomy of an Ambient TUI App

Every app in `apps/ambient/` has the same three-phase shape. Once you
can see the shape, the code stops being opaque.

```
setup    -> take over the terminal
loop     -> compose a frame, write it, sleep
teardown -> give the terminal back, always
```

The whole program is a string builder wrapped in a state change that
must be undone.

---

## Phase 1: Setup

Two things happen, in this order:

1. **Enter the alternate screen.** The terminal keeps two screen
   buffers. The primary one holds your shell history. The alternate
   one is a scratch surface that vanishes on exit. Full-screen
   programs (vim, less, top) all use it. Without it, every frame your
   app draws scrolls into the user's scrollback and is still there
   after the app exits.

2. **Hide the cursor.** A blinking cursor parked in the middle of a
   clock face looks like a bug.

Signal handlers are also registered here. See Phase 3.

## Phase 2: The loop

Each iteration does four things:

1. **Read the world.** Current time, a `/proc` file, an API response.
2. **Measure the pane.** `os.get_terminal_size()` gives columns and
   rows. This can change between any two iterations.
3. **Compose one string.** The entire frame, including padding, as a
   single Python string.
4. **Write it once, then sleep.**

### Why one string

The naive approach is clear-the-screen, then draw. That produces a
visible blank frame between the clear and the draw, which reads as
flicker.

Instead: move the cursor to home (`\033[H`), then overwrite every cell
with new content. Nothing is ever blank, because new content lands on
top of old content in one operation.

This only works if the frame covers the full pane. A frame narrower
than the pane leaves the old frame's right edge visible. A frame
shorter than the pane leaves old rows below it. So every frame is
padded to exactly `columns x rows`.

The rule: **compose, then write.** Never write partial frames.

### Why sleep to a boundary, not a duration

```python
time.sleep(1)
```

This sleeps *at least* one second, plus however long the frame took to
compose and write, plus scheduler jitter. The error accumulates. A
clock using this will eventually skip a displayed second, because two
wall-clock seconds elapsed inside one iteration.

Instead, sleep until the next boundary:

```python
now = time.time()
time.sleep(1.0 - (now % 1.0))
```

This self-corrects. Each iteration wakes just after the second ticks
over, regardless of how long the previous frame took.

The same idea applies at any interval. A weather app polling every 15
minutes should wake on the quarter hour, not 15 minutes after it
happened to start.

### Cost

An ambient app should be invisible in `top`. It is asleep for
essentially all of its life, waking briefly once per interval. If it
shows measurable CPU, the sleep is wrong: either it is spinning, or
it is redrawing far more often than the content changes.

This matters because the point of these apps is running several at
once.

## Phase 3: Teardown

The hardest phase, because it must run on every exit path and it can
fail in ways you cannot see.

### What has to be undone

Everything setup did, in reverse: show the cursor, leave the alternate
screen. If the app changed colors, reset attributes.

Miss it and the user's terminal is left broken after your app exits.
An invisible cursor is the classic symptom.

### Every exit path

Three signals reach a pane app, and they arrive from different causes:

| Signal | Cause |
|---|---|
| SIGINT | Ctrl-C |
| SIGTERM | `kill`, systemd stop |
| SIGHUP | the terminal went away (tmux pane closed) |

Plus normal exceptions, plus normal return.

Handling these separately produces three teardown paths that drift
apart. The pattern that avoids it:

```python
def handle_signal(signum, frame):
    sys.exit(0)

signal.signal(signal.SIGINT, handle_signal)
signal.signal(signal.SIGTERM, handle_signal)
signal.signal(signal.SIGHUP, handle_signal)

try:
    main_loop()
finally:
    teardown()
```

`sys.exit()` raises `SystemExit`. That unwinds the stack like any
exception, so the `finally` runs. Every path converges on one
teardown function. Normal exceptions and normal return land there too.

### Teardown can fail

When tmux closes a pane, the pty master is destroyed before your
process is reaped. Your writes now go to an orphaned slave fd, which
returns `EIO`, which Python raises as `OSError`.

That exception fires inside `finally`, during interpreter shutdown,
with nowhere to go. It is harmless in effect, but it means teardown
did not finish, and you cannot see the failure because the terminal it
would have printed to is gone.

```python
def teardown():
    try:
        sys.stdout.write(SHOW_CURSOR)
        sys.stdout.write(LEAVE_ALT_SCREEN)
        sys.stdout.flush()
    except OSError:
        pass
```

There is nothing useful to do with the error. The terminal is already
gone, and the state you were restoring no longer exists.

---

## Resize

`SIGWINCH` arrives when the pane changes size. It can arrive at any
moment, including in the middle of your write.

**The handler must not draw.** It runs asynchronously, so drawing
inside it races the main loop, and you get two frames interleaved
mid-write.

The handler sets a flag. The loop reads it:

```python
resized = False

def handle_winch(signum, frame):
    global resized
    resized = True
```

The main loop checks the flag at the top of each iteration. If set, it
clears once (`\033[2J`) to wipe content that is now outside the new
bounds, recalculates layout, and clears the flag.

This is the one legitimate use of clear-the-screen. The steady-state
loop never clears.

A note on interrupted writes: since Python 3.5, interrupted syscalls
are retried automatically (PEP 475). A signal arriving mid-write will
not corrupt output or raise `EINTR`.

---

## Degradation

The pane is whatever size the user made it, and the terminal is
whatever they are running. An app that assumes otherwise looks broken
rather than small.

**Size.** Decide what happens below the size your layout needs. A
clock with big digits needs maybe 40x7. Below that: a compact
fallback, or a short message. Undefined behavior here is what makes
an app feel unfinished.

**Color.** Respect `NO_COLOR`. If the environment variable is set to
anything, emit no color escapes at all. This is a widely observed
convention and costs one conditional.

**Not a tty.** If `sys.stdout.isatty()` is false, the output is being
piped or redirected. Escape sequences are garbage in that context.
Either emit plain text or refuse to run.

**Unicode.** Block characters (`█`, `▀`, `▄`) need font and locale
cooperation. When they are unavailable you get replacement boxes,
which look worse than ASCII would have. Detect and fall back.

---

## The whole shape

```python
def main():
    install_signal_handlers()
    enter_alt_screen()
    hide_cursor()
    try:
        while True:
            if resized:
                clear()
                resized = False
            cols, rows = os.get_terminal_size()
            frame = compose(read_world(), cols, rows)
            write(CURSOR_HOME + frame)
            sleep_to_next_boundary()
    finally:
        teardown()
```

Everything else is `compose()`.

That is the part worth spending time on, and it is the only part that
differs between a clock, a weather pane, and a resource visualization.
