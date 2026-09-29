# Dev Workflow

How one roadmap entry goes from idea to merged. Follow it top to
bottom. One roadmap entry per run, never several at once.

Uses the mattpocock-skills plugin and GitHub Issues.

## Who does what

- **Agent:** grilling, specs, issues, branches (via `/implement`), code, tests,
  commits, opening and editing PRs.
- **You:** answering the grill, deciding ticket questions, visual
  and terminal testing, `git push`, merging.

The agent cannot push. Its shell has no SSH agent. `gh` still works
for issues and PRs because it uses its own token over HTTPS.

## Context budget

Keep the session under about 100k tokens. `/clear` at the marked
points below. State lives in GitHub issues and the repo, not the
session, so clearing loses nothing.

---

## 1. Start clean

On main, up to date, fresh session.

    git checkout main
    git pull
    claude

## 2. Grill

    /grill-with-docs the "<entry>" entry in ROADMAP.md

Answer until it stops asking. If it tries to write an ADR for
something already in docs/README.md under "Design decisions", tell
it to reference that file instead.

## 3. Spec

    /to-spec

Creates the spec as a GitHub issue. Note the number. This is the
parent issue.

## 4. Tickets

    /to-tickets

Breaks the spec into ticket issues with blocking edges. It will ask
questions. Typical answers:

- **Tiny ticket?** Merge it into its neighbor.
- **Labels:** `ready-for-agent` for everything the agent builds,
  including visual work. Add "looks right in a real pane, checked
  by owner" as an acceptance criterion where it applies.
  `ready-for-human` means you write the code yourself, not that
  the agent pauses for review. Labels never pause anything.
- **Edges:** check that anything deferrable says its edges come off
  if deferred.

Verify on GitHub, not in the agent's summary, that the issues
exist and your answers landed.

## 5. Clear

**`/clear` here.** The spec and tickets are on GitHub, so nothing
is lost.

## 6. Implement

    /implement #<ticket>

`/implement` creates the branch for the issue as its first step.
Confirm with `git branch` before it gets far. If it didn't, stop
and ask for one.

It then drives TDD (failing test first) and runs a code review
before each commit. One ticket at a time is safest. If the session
passes about 100k, `/clear` before the next ticket.

Tests cover pure logic only. Terminal behavior is yours.

## 7. Manual testing

Run it in a real pane. Minimum four checks, from
docs/verifying.md:

1. Look at it running
2. Ctrl-C, then confirm the cursor is visible
3. `tmux kill-pane`, then confirm the next pane is normal
4. Drag the pane divider around

Tick any by-eye acceptance criteria on the tickets.

**`/clear` here.**

## 8. Whole-branch review

    /code-review the diff from main to this branch, against spec
    issue #<parent>

The per-ticket reviews never saw everything together. This one
does. Runs sub-agents, so it costs more usage than a normal turn.

Fix anything it finds before continuing.

## 9. Push (you)

    ssh-add ~/.ssh/id_ed25519
    git push -u origin <branch>

## 10. Open the PR

    Open a PR for this branch. In the description, put a separate
    "Closes #n" line for the parent issue and every ticket issue.

Each issue needs its own `Closes` line. Closing the parent does not
close its tickets.

Check the PR page: the **Development** section in the right sidebar
should list every issue. If one is missing:

    Edit the PR description to add "Closes #n" for <missing>.

## 11. Merge (you)

On GitHub, use **Create a merge commit**. It keeps every commit and
the Co-Authored-By trailers. Delete the branch when offered.

## 12. Close out

    git checkout main
    git pull

Then:

    Move "<entry>" to Built in ROADMAP.md with "Shipped: #<pr>".
    Change nothing else in the file.

Commit, then push by hand.

---

## Quick reference

    git checkout main && git pull && claude
    /grill-with-docs "<entry>" in ROADMAP.md
    /to-spec
    /to-tickets
    /clear
    /implement #<ticket>              (creates branch; repeat per ticket)
    manual testing
    /clear
    /code-review main..branch against #<parent>
    git push -u origin <branch>       (you)
    Open a PR, one "Closes #n" per issue
    Merge commit on GitHub            (you)
    git checkout main && git pull
    Move entry to Built in ROADMAP.md
    commit, push                      (you)

## If you get lost

    /ask-matt where am I and what's next
