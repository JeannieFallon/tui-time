# Verifying a TUI App

TUI bugs fall into two groups: the ones you can see, and the ones that
only show up in the terminal you were using afterward. The second
group is the one worth having a checklist for.

---

## Visual checks

Run it in a pane and look at it.

- [ ] Content appears where it should
- [ ] No flicker. If the display blinks each tick, the frame is being
      cleared before it is drawn.
- [ ] No tearing. Partial frames mean the app is writing more than
      once per frame.
- [ ] No stale fragments at the edges. Means frames are not padded to
      the full pane.
- [ ] Colors look right, and are not banding. Visible banding in a
      gradient usually means truecolor is not reaching the terminal
      (see the tmux note in `ansi.md`).

## Terminal state checks

These are the ones that matter, and none of them are visible while the
app is running.

After exiting with Ctrl-C:

- [ ] The cursor is visible. Type something and confirm you can see it.
- [ ] Typing behaves normally. If you need to run `reset`, teardown is
      broken.
- [ ] Scrollback is clean. Scroll up. App frames should not be in your
      history. If they are, the alternate screen is not being used.
- [ ] `echo $?` returns 0 or 130. 130 is normal for Ctrl-C.

## Exit path checks

Each of these is a different code path. Test them separately.

**SIGINT.** Ctrl-C. The one everyone tests.

**SIGTERM.** From another pane:

```
pkill -TERM -f clock.py
```

**SIGHUP.** The one that gets missed, and the one tmux actually sends.
Ctrl-C does not exercise it.

```
tmux kill-pane -t <target>
```

Then open a new pane and confirm the terminal is normal. A teardown
that writes to a dead pty raises `OSError`, which means teardown did
not finish, and you cannot see the error because the terminal it would
have printed to is gone.

## Resize checks

- [ ] Drag the pane divider slowly. No artifacts, no stale content from
      the old size.
- [ ] Drag it fast. Same.
- [ ] Shrink below the app's minimum layout size. The fallback should
      engage, not garbage.
- [ ] Shrink to roughly 10x3. Something reasonable should happen.
- [ ] Grow it back. Layout recovers.

## Cost checks

An ambient app should be effectively free. This matters because the
premise is running several at once.

```
pidstat -p $(pgrep -f clock.py) 1 5
```

- [ ] CPU sits at 0.00 between ticks

If it is spinning, the sleep is wrong. Either it is busy-waiting, or
it is redrawing far more often than the content changes.

```
strace -f -e trace=write,clock_nanosleep -p $(pgrep -f clock.py)
```

- [ ] One `write` per frame, then one sleep, repeating

Multiple writes per frame means the app is not composing the frame as
a single string. That is the tearing bug, whether or not you have
noticed it yet.

## Timing checks

- [ ] Watch a clock for a full minute. No skipped second, no repeated
      second.

Drift from `time.sleep(1)` accumulates slowly. It takes a minute or
two to become visible, which is why it survives casual testing.

## Degradation checks

```
NO_COLOR=1 python3 app.py
```

- [ ] No color escapes emitted at all

```
python3 app.py | cat
```

- [ ] Either plain text, or a clean refusal. Not escape garbage.

```
python3 app.py > /tmp/out
cat -v /tmp/out | head -c 400
```

- [ ] The sequences emitted are the ones you expect

---

## Delegating verification

Two things worth asking the agent to do, neither of which replaces
running the app yourself:

**Contract check.** After a build step:

> Check this file against apps/ambient/CLAUDE.md and list anything
> that violates the contract.

Cheap, and it catches drift before it compounds.

**Diff explanation.** Before committing:

```
git diff
```

Then ask it to explain anything unexpected. Reading a diff with an
explanation beside it is how the domain knowledge actually arrives.

What cannot be delegated: the agent cannot see your terminal. Every
check above that involves looking at something, or checking the state
of your shell afterward, is yours.

---

## The short version

If you only do four things:

1. Look at it running
2. Ctrl-C, then confirm you can see your cursor
3. `tmux kill-pane`, then confirm the next pane is normal
4. Drag the divider around

That catches most of what actually goes wrong.
