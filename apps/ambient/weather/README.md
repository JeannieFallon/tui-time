# weather

Current conditions for one place, from Open-Meteo: the temperature in
big block digits, the Condition in words, the location, and how long
ago the Reading was fetched.

## Usage

```
python3 apps/ambient/weather/weather.py Lisbon
python3 apps/ambient/weather/weather.py New York --units imperial
```

The place name is required. Multi-word names work with or without
quotes. It is geocoded once, at startup, with Open-Meteo's geocoding
API, and the top match is used. The pane shows the match as name,
region and country code (`Lisbon, Lisbon District, PT`).

`--units` takes `metric` (the default, °C) or `imperial` (°F). No
API key is needed.

Exit status:

- **0**: stopped by SIGINT (Ctrl-C), SIGTERM or SIGHUP (a closed tmux
  pane). All three restore the cursor and the main screen.
- **2**: usage error: no place name, an unknown `--units` value, or a
  place name that geocoding matches to nothing. A place name with no
  match exits 2 even after the pane has started. The app leaves the
  alternate screen first, then prints the error.

The app draws on the alternate screen, so nothing goes into
scrollback. Each frame is written in one write and covers every cell
of the pane. It draws one frame a second, on the wall-clock second.

## Fetching

The first frame shows the place name as typed and `fetching…`. After
that the app fetches the geocoding match and then a Reading. The
Reading holds the current temperature and WMO weather code. Codes map
to short Conditions such as `Light rain` or `Overcast`, and a code not
in the table shows as `Unknown`.

After a successful fetch, the next one is due on the next wall-clock
quarter hour (:00, :15, :30, :45). That quarter-hour period is the Fetch interval.
A failed fetch is retried after 1, 2, 4 and then 8 minutes, then
every 15 minutes. The first success resets the sequence. A failed
geocoding lookup is retried on the same sequence, and the pane keeps
the typed name as its label until the lookup succeeds.

Fetches are synchronous, with a 3-second socket timeout, in the same
loop that draws. The frame on screen stays up while a fetch runs.
When a fetch finishes, the outcome is drawn at once.

A failed fetch has one of four causes:

| Cause | When |
|---|---|
| `offline` | DNS or connection errors |
| `timeout` | the socket timed out |
| `HTTP <code>` | a 4xx or 5xx status, for example `HTTP 503` |
| `bad response` | a body that isn't JSON or lacks the expected fields |

## Stale and Expired

A Reading's age counts from when it was fetched, on the monotonic
clock, not from Open-Meteo's timestamp. Changing the system clock
doesn't change it.

- **Fresh**, under 30 minutes: drawn normally.
- **Stale**, 30 minutes up to 3 hours: the temperature and Condition
  are drawn dim (SGR 2). The location and age lines are not dimmed.
- **Expired**, 3 hours or more: the Reading is dropped, and the pane
  shows the no-Reading layout below until a fetch succeeds.

The Reading is kept in memory only. Nothing is written to disk.

## Layouts

Every state has a defined pane. The largest layout that fits is
drawn, centered.

With a Reading:

```
 ▄▀▀▀▄  ▄█   ▄▀▀▄
     █   █   ▀▄▄▀
   ▄▀    █
 ▄▀      █
 █▄▄▄▄  ▄█▄

   Light rain · °C
Lisbon, Lisbon District, PT
   updated 4m ago
```

The age line reads `updated just now` under a minute, `updated 4m ago`
under an hour, and `updated 1h 5m ago` beyond that. When the latest
fetch failed but the Reading is not Expired, the cause is added:
`updated 20m ago · offline`.

With no Reading, and the latest fetch failed:

```
springfield · offline · retry in 2m
```

The countdown rounds up to whole minutes. Once the retry is due, and
while it runs, it reads `retrying…`.

With no Reading, and no fetch finished yet: `Lisbon · fetching…`.

## Pane sizes

Temperatures are rounded to whole degrees, halves away from zero, and
`-0` is never shown. Negative temperatures get a big minus sign.

With a Reading, the tiers are, largest first:

| Tier | Lines | Needs |
|---|---|---|
| big | digits, blank, Condition line, location, age | widest of those lines × 9 rows (14 in ASCII) |
| compact with age | `12°C Light rain`, age line | widest of the two × 2 |
| compact | `12°C Light rain` | its width × 1 |
| minimal | `12°C` | its width × 1 |
| blank | nothing | anything smaller |

Big digits are 5 columns wide, the minus and degree sign 4, with a
1-column gap between glyphs. `12°` is 16 columns wide. The location
line is often the widest, so a long place name moves the big tier
threshold.

Without a Reading, the text shrinks: `label · cause · retry in 2m`,
then the cause alone (`offline`), then `!`. While fetching:
`label · fetching…`, then `fetching…`, then blank. `!` fits any pane
of at least 1×1.

Stale dimming applies in every tier that shows the temperature.
Nothing is clipped. On resize the screen is cleared once and the tier
is picked again.

## NO_COLOR and ASCII

The only styling is the dim on a Stale Reading. When `NO_COLOR` is
set to a non-empty value, the app emits no SGR escapes. A Stale Reading is
then drawn like a fresh one, and only the age line shows its age.

When stdout's encoding can't encode the block characters, `°`, `·`
and `…` (for example `PYTHONIOENCODING=ascii`), the big glyphs are
drawn with `#` at 10 rows tall, the degree sign is left out of text
(`12C Light rain`), `·` becomes `-` and `…` becomes `...`. Place
names lose their accents (`São Paulo` becomes `Sao Paulo`), in the
pane and in the non-tty line, and any other non-ASCII character
becomes `?`.

## Not a terminal

When stdout isn't a tty, as with a pipe, a redirect, cron or a tmux
status line, the app geocodes, fetches once and prints one line:

```
Lisbon, Lisbon District, PT 12°C Light rain
```

It exits 0. It emits no escape codes and doesn't enter the alternate
screen. If geocoding or the fetch fails, it prints the cause to stderr
(`weather.py: offline`), prints nothing to stdout, and exits 1. A
place name with no match exits 2, as above. It doesn't retry.

## Known limitations

- Only the top geocoding match is used. An ambiguous name can resolve
  to the wrong place, and the only way to pick another is a more
  specific name.
- Current temperature and Condition only. No feels-like, high/low,
  wind, humidity or precipitation.
- Readings are not saved to disk. A restart starts with no Reading.
- A fetch blocks the draw loop. A resize or the next second's frame can
  wait for up to the 3-second socket timeout. DNS lookups are not
  covered by that timeout and can take longer.
- Age and retry countdowns run on the monotonic clock, which on Linux
  doesn't advance during suspend. After a resume, the age leaves out
  the time spent suspended, until the next fetch replaces the Reading,
  and that fetch can come up to 15 minutes after its wall-clock
  quarter hour.
- Text widths are counted in characters. A place name with
  double-width characters can be wider on screen than the tier check
  assumes.
- Unicode support is judged from stdout's encoding, not from the font.
- Open-Meteo's free tier is for non-commercial use. At one request per
  quarter hour the app makes about 100 a day.
