# tui-time

Small TUI apps to jazz up idle panes.

Two classes of app, each with its own contract:

- `apps/ambient/` — non-interactive. Fills a pane, is looked at,
  not driven. See apps/ambient/CLAUDE.md.
- `apps/interactive/` — accepts keyboard input. See
  apps/interactive/CLAUDE.md.

Read the contract for the class you are working in.

## Conventions

- Python 3, stdlib only by default
- One directory per app, one file where possible
- No shared package. Duplicate until the third repetition.
- Run as: python3 apps/<class>/<name>/<name>.py
- If an app needs a dependency, add PEP 723 inline metadata and run
  with uv
- No packaging until an app outgrows a single file

## App READMEs

Each app has a README.md written as the last build step, not before.

- What it does, in one or two lines
- How to run it
- Behavior at small pane sizes
- Known limitations
- No audience framing. Describe the app, not who it is for.
- Describe what the code does, not what it is meant to do

## Non-goals

- No config files in v1 of anything
- No shared framework

## Agent skills

### Issue tracker

Issues live in GitHub Issues on JeannieFallon/tui-time, managed with the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Default vocabulary: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one root `CONTEXT.md` plus `docs/adr/`, both created lazily. See `docs/agents/domain.md`.
