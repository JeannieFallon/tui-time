# docs

Reference material for building the apps in this repo.

- **[anatomy.md](anatomy.md)** — the three-phase structure every
  ambient app follows: setup, loop, teardown. Why frames are composed
  as one string, why sleeps target a boundary rather than a duration,
  and why teardown is the hard part.

- **[ansi.md](ansi.md)** — the escape sequences these apps actually
  use. Screen buffer, cursor, color, attributes, block characters,
  and the half-block trick for square pixels.

- **[verifying.md](verifying.md)** — checklists for confirming an app
  works, including the failures that are only visible in the terminal
  after the app exits.

## Design decisions

Recorded here so they are not re-litigated.

**Raw ANSI, not curses or Textual, for ambient apps.** A
non-interactive pane display needs roughly eight escape sequences and
a signal handler. A framework adds an event loop and an input model
that these apps do not use, and it hides the mechanics that make up
the shared contract. Interactive apps are a different case and Textual
is usually right for those.

**Stdlib only by default.** Every dependency is a thing that can break
between one run and the next on a machine you have not touched in
months. Apps that need one declare it with PEP 723 inline metadata and
run under `uv`, staying a single file.

**No shared package.** A `common/` module starts as a keybinding
helper and ends as a framework that every app depends on, where
changing one thing means touching everything. Duplication is cheaper
than premature abstraction at this scale. Revisit at the third
repetition, not the second.

**One directory per app.** Each app is self-contained and can be
copied to a server on its own. This keeps every distribution option
open: packaging, a top-level installer, or splitting an app into its
own repo later.

**Contracts live in CLAUDE.md, not in prose.** `apps/ambient/` and
`apps/interactive/` each carry their own contract file. They load only
when the agent reads files in that subtree, so the ambient rules never
contradict the interactive ones in the same context.
