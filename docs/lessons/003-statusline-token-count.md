# Reading token and context usage

## What happened

I expected the status bar to show token usage and it showed nothing but the
model indicator. I assumed something was misconfigured.

## Why

Claude Code ships with no status line. There is no default token display to
lose or break. The bar stays empty until a `statusLine` command is configured
in settings, and most of what I had seen in screenshots elsewhere was people's
custom scripts, not stock behavior.

## What I changed

Two things, in order of usefulness.

**On demand, no setup:**

    /context     # context window usage and what is filling it
    /usage       # subscription limits, session and weekly

`/context` is the one that matters mid-session. Auto-compact fires around 78%,
so watching it tells me when a conversation is about to get summarized out from
under me.

**Persistent, in the bar:**

    /statusline show model name, context percentage, and total tokens used

Typed inside a session. It generates the script, writes the `statusLine` entry
to settings, and the bar appears after a restart. No manual JSON editing.

The script receives a JSON object on stdin each refresh. The relevant fields:

    context_window.used_percentage      # how full the window is
    context_window.total_input_tokens   # cumulative input this session
    context_window.total_output_tokens  # cumulative output this session

These two numbers answer different questions and I kept conflating them.
`used_percentage` is *right now* — how close the conversation is to being
compacted. The token totals are *cumulative* — everything the session has
consumed, which keeps climbing even after a compaction drops the percentage
back down.

Worth knowing: `used_percentage` is computed from input tokens only, including
cache creation and cache reads. Output tokens are excluded. Calculating the
percentage by hand from the totals above will not match.

## What I'd do differently

Check what the tool actually ships with before assuming a missing feature is a
broken configuration. The instinct to debug came from pattern-matching against
other people's terminals, where the customization was invisible.

One field-specific note: most published status line examples render
`cost.total_cost_usd`. On a subscription plan that figure is what the session
would have cost at API rates, not money being spent. It is interesting and it
is not the constraint. The constraint is the rolling session and weekly caps,
which only `/usage` reports.
