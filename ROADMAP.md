# Roadmap

Not a schedule. An ordered backlog with scope notes.

Difficulty is relative to the clock, which is the baseline.

## Built

- **clock** (ambient) — big-digit wall clock. Full-pane frames
  with clean resize, frame-boundary timing, size tiers down to a
  blank pane, plain output when piped, `NO_COLOR` and ASCII
  fallback. `--theme` selects a palette plus at most one effect:
  `plain` (default), `night` (starfield), `rain`, `wave`.
  Shipped: #11

## Next

- **weather** (ambient) — current conditions for a location.
  Difficulty: low-moderate. The work is in failure states:
  timeout, no network, stale reading, what the pane shows when a
  fetch fails. Scope so far:
  - Open-Meteo, keyless, so v1 has no secret management
  - Location is a required positional place name, geocoded once
    at startup via Open-Meteo; top match, resolved name shown in
    the pane (the typed name until geocoding succeeds); no match
    exits 2; no auto-detection
  - Shows temperature (big digits, glyphs copied from clock),
    condition word, location name, last-updated age
  - Fetch every 15 minutes on a boundary; on failure retry with
    backoff 1/2/4/8 minutes, capped at 15
  - Synchronous fetch with a short timeout, no threads
  - Last reading kept in memory only, nothing on disk. Age
    counts from fetch time (monotonic), not the API timestamp. Stale
    after 30 minutes (shown dimmed), expired after 3 hours
    (dropped)
  - Every failure state has a defined pane: fetching, failed
    with cause and retry countdown, reading with failure noted
    on the age line
  - One frame a second; size tiers big / compact line /
    temperature only / blank
  - Not a tty: one plain line, exit 0, or exit 1 with the cause
    on stderr
  - Metric by default, `--units imperial`
  - v2: feels-like, high/low, wind, humidity, precipitation,
    condition icons, themes, on-disk cache

  In progress: #12

  After weather, the ambient scaffold (setup/loop/teardown)
  exists twice. Decide at the third ambient app whether to
  extract it.

- **ping** (ambient) — latency to a host as a scrolling
  sparkline. Difficulty: low. Establishes the ring buffer pattern
  that resource-viz reuses.

- **resource-viz** (ambient) — abstract visualization of system
  load. Difficulty: moderate. v1 is CPU only, one visual
  metaphor. Memory, disk, network are v2. Reuses ping's ring
  buffer. Needs an exponential moving average on every input; raw samples jitter and read as
  broken. Sampling from /proc is the easy part, the mapping from
  numbers to aesthetics is the app.

## Backlog

Ambient:

- **gitstat** — branch, dirty file count, ahead/behind, last
  commit age for a given repo path. Difficulty: low. Shells out
  to git, so it exercises subprocess handling.

- **moon** — moon phase, illuminated fraction, next full/new.
  Difficulty: low. No API needed: closed-form from a known epoch,
  synodic month ~29.53 days, accurate to well under a day. The
  interesting part is drawing the illuminated shape.

- **daylight** — sunrise, sunset, remaining daylight. Difficulty:
  low. Pure computation like moon, pairs with it. Needs a
  lat/long, taken the same way weather takes its location.

- **headlines** — RSS or Hacker News top items, scrolling.
  Difficulty: moderate. Network plus text wrapping at arbitrary
  widths, which every text-heavy app after this will need.

Interactive:

- **todo** — quick checklist in a pane. Difficulty: moderate.
  First interactive app, first persistent state. Design fork:
  edit in-app, or display-only watching a markdown file you edit
  elsewhere. The display-only variant is ambient, much cheaper,
  and possibly more useful in a tmux workflow.

- **pomodoro** — countdown with a bell on completion. Difficulty:
  low-moderate. Arguably ambient if it takes no input. State must
  survive, and completion needs a terminal bell or a
  notify-send.

## Ideas, unscoped

- **Inference-backed apps.** TUI apps that call an inference
  endpoint, either a frontier API or a self-hosted server
  (vLLM, Ollama). Not scoped. Open questions: what an ambient
  app does with a non-deterministic, latency-variable,
  sometimes-failing backend; whether the interesting apps here
  are ambient or interactive; whether local and remote are one
  app with a config switch or two apps.

## Shelved

- **ssh-chat** — chat between developer VMs over SSH. Shelved:
  the SSH framing hides the actual cost, which is concurrency
  plus TUI. Rendering while blocked on a socket read needs
  threads or asyncio, a different program shape from everything
  else here. If revisited, build a single-machine Unix socket
  version first and swap the transport later.
