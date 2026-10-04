# tui-time

Small terminal apps to jazz up idle panes. Each app is a single Python
file with no dependencies beyond the standard library.

![Six tmux panes in two rows. On the left, the clock with the night theme's stars and the clock with the wave theme's color gradient. In the middle, weather for New Bern, North Carolina with a rain icon and drops falling around it, and weather for Tokyo with a sun icon. On the right, ping sparklines of green bars with yellow spikes, for 1.1.1.1 at 10 ms and for a farther host at 61 ms](res/clock-weather-ping_demo.gif)

## Apps

| App | Class | What it does |
|-----|-------|--------------|
| [clock](apps/ambient/clock/README.md) | ambient | Big-digit wall clock that fills the pane, with optional themes: `plain`, `night`, `rain`, `wave` |
| [weather](apps/ambient/weather/README.md) | ambient | Current conditions for one place from Open-Meteo: an icon for the sky beside a big-digit temperature, the condition, feels-like, today's high and low, wind and chance of rain, with falling rain or snow around them. Every failure has a defined pane |
| [ping](apps/ambient/ping/README.md) | ambient | Latency to one host, one ICMP probe a second: the current round-trip time in big digits over a scrolling sparkline, colored from green when fast through yellow to red when slow, with gray columns for lost probes and min, avg, max and loss below |

```
python3 apps/ambient/clock/clock.py --theme night
python3 apps/ambient/weather/weather.py Lisbon
python3 apps/ambient/ping/ping.py one.one.one.one
```

Ambient apps fill a pane and are looked at, not driven. Interactive
apps take keyboard input; none are built yet. [ROADMAP.md](ROADMAP.md)
lists what's next.

## Requirements

- A Unix-like system (Linux or macOS). The apps rely on POSIX signals
  and terminal handling. Developed and tested on Linux.
- Python 3, standard library only. Tested on Python 3.13.
- A terminal with 256-color support. With `NO_COLOR` set, the apps
  draw without color.
- A UTF-8 terminal and a font with block characters for the best
  rendering. Otherwise the apps fall back to ASCII.
- Network access to Open-Meteo for weather. No API key is needed.
- For ping, Linux with unprivileged ICMP sockets allowed for your
  group by `net.ipv4.ping_group_range`. No root is needed. The ping
  README shows how to widen the range.
- tmux is optional. Each app fills whatever terminal or pane it runs in
  and redraws on resize.

## Why this repo exists

tui-time is a project for learning agentic development with
[Claude Code](https://claude.com/claude-code). The apps are small on
purpose. Each one is enough work to exercise the whole loop, from idea
to merged PR, without the app itself taking over.

Matt Pocock's [skills](https://github.com/mattpocock/skills) guide the
workflow. A typical app goes through these steps:

1. **Grill** the idea until its scope and edge cases are settled
   (`grilling`).
2. **Spec** it as a GitHub issue, then split the spec into tickets
   (`to-spec`, `to-tickets`).
3. **Implement** the tickets on one branch per app, named
   `<class>-<app>-v<N>`, with one commit per ticket (`implement`, `tdd`).
4. **Review** the branch on two axes, repo standards and spec
   (`code-review`), then fix what the review turns up.
5. **Merge** through a single PR that closes the spec and its tickets.

The agent writes code, commits, and manages issues and PRs. A human
pushes. [CLAUDE.md](CLAUDE.md) and the per-class `CLAUDE.md` files hold
the conventions and app contracts the agent works under, and
[docs/](docs/README.md) holds the reference material behind them.
[docs/lessons/](docs/lessons/) records what went wrong along the way
and what changed because of it.
