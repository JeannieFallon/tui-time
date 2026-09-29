# Roadmap

Not a schedule. An ordered backlog with scope notes.

Difficulty is relative to the clock, which is the baseline.

## Built

## Next

- **clock v2** (ambient) — `--theme` flag selecting a palette plus
  at most one effect: `plain` (default), `night` (starfield),
  `rain`, `wave`. Difficulty: low. Scope trap: effects are
  unbounded. Each effect is its own ticket, built last. All four
  themes and the v1 finish are built on `ambient-clock`, awaiting
  review and merge.
  In progress: #1

- **weather** (ambient) — current conditions for a location.
  Difficulty: low-moderate. Use a keyless API (Open-Meteo,
  wttr.in) so v1 has no secret management. The work is in failure
  states: timeout, no network, stale cache, what the pane shows
  when the request fails.

- **resource-viz** (ambient) — abstract visualization of system
  load. Difficulty: moderate. v1 is CPU only, one visual
  metaphor. Memory, disk, network are v2. Needs an exponential
  moving average on every input; raw samples jitter and read as
  broken. Sampling from /proc is the easy part, the mapping from
  numbers to aesthetics is the app.

## Backlog

Ambient:

- **gitstat** — branch, dirty file count, ahead/behind, last
  commit age for a given repo path. Difficulty: low. Shells out
  to git, so it exercises subprocess handling.

- **ping** — latency to a host as a scrolling sparkline.
  Difficulty: low. Establishes the ring buffer pattern that
  resource-viz reuses.

- **moon** — moon phase, illuminated fraction, next full/new.
  Difficulty: low. No API needed: closed-form from a known epoch,
  synodic month ~29.53 days, accurate to well under a day. The
  interesting part is drawing the illuminated shape.

- **daylight** — sunrise, sunset, remaining daylight. Difficulty:
  low. Pure computation like moon, pairs with it. Needs a
  lat/long, which is the first app to want any config at all.

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
