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

- **weather** (ambient) — current conditions for one place from
  Open-Meteo, keyless. Place name geocoded once at startup (top
  match; no match exits 2). Big-digit temperature, Condition,
  location and age lines. Fetches on quarter hours, with
  1/2/4/8/15-minute backoff on failure. Every failure state has a
  defined pane. Readings Stale (dimmed) at 30 minutes, Expired
  (dropped) at 3 hours. Size tiers down to a blank pane, plain
  line when piped, `NO_COLOR` and ASCII fallback,
  `--units imperial`.
  Shipped: #19

- **weather v2** (ambient) — feels-like, today's high/low, wind
  and precipitation chance as two detail lines; a static icon per
  Sky (Clear with a night moon, Cloudy, Rain, Snow, Storm);
  falling drops or flakes as an Effect while the Reading is Fresh,
  at 8 fps. Two new top size tiers (full, big with icon), with
  v1's tiers kept below them. Fetch stays synchronous, so the
  Effect stalls during fetches; this is accepted. `simulate.py`
  runs the pane with a fake network for checking icons and
  Effects by hand. Out: humidity, UV, sunrise/sunset, hourly
  sparkline, `--theme`, on-disk cache (still a candidate for a
  later version).
  Shipped: #25

## Next

- **ping** (ambient) — latency to a host as a scrolling
  sparkline. Difficulty: low. Establishes the ring buffer pattern
  that resource-viz reuses.

  The ambient scaffold (setup/loop/teardown) exists twice, in
  clock and weather, and so does the rain Effect (clock's `rain`
  theme, weather's drops). Ping is the third ambient app: decide
  there whether to extract the scaffold.

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
