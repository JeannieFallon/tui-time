# weather

Current conditions for one place, from Open-Meteo: an icon for the
Sky beside the temperature in big block digits, the Condition in
words, feels-like, today's high and low, wind and chance of rain, the
location, and how long ago the Reading was fetched. Rain and storms
get falling drops across the pane, and snow gets falling flakes.

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
of the pane. It draws one frame a second, on the wall-clock second,
or 8 a second while an Effect is showing, on eighths of a second.

## Fetching

The first frame shows the place name as typed and `fetching…`. After
that the app fetches the geocoding match and then a Reading. The
forecast request asks for current conditions and today's forecast, in
the place's local time zone, in one call:

- current: temperature, WMO weather code, feels-like temperature, wind
  speed and direction at 10 m, and whether it is day
- today: high and low temperature, and the highest chance of
  precipitation

Temperatures come in °C or °F and wind in km/h or mph, following
`--units`. All of these belong to the Reading. The temperature and
weather code are required: a response missing either is a
`bad response`. Every other field is optional, and a missing or null
one only drops its own item from the pane (see Detail lines). A
missing day flag counts as day.

Codes map to short Conditions such as `Light rain` or `Overcast`, and
a code not in the table shows as `Unknown`. Each Condition also
belongs to a Sky:

| Sky | WMO codes |
|---|---|
| Clear | 0–1 |
| Cloudy | 2–3, 45–48 |
| Rain | drizzle, rain and showers: 51–67, 80–82 |
| Snow | 71–77, 85–86 |
| Storm | 95–99 |

An `Unknown` Condition has no Sky, so no icon and no Effect.

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
- **Stale**, 30 minutes up to 3 hours: the icon, temperature,
  Condition and detail lines are drawn dim (SGR 2). The location and
  age lines are not dimmed. The Effect stops.
- **Expired**, 3 hours or more: the Reading is dropped, and the pane
  shows the no-Reading layout below until a fetch succeeds.

The Reading is kept in memory only. Nothing is written to disk.

## Layouts

Every state has a defined pane. The largest layout that fits is
drawn, centered.

With a Reading, in the largest layout:

```
  ▄███▄ ▄▄   ▄▀▀▀▄  ▄█   ▄▀▀▄
▄██████████      █   █   ▀▄▄▀
▀█████████▀    ▄▀    █
  █   █  ▄   ▄▀      █
    █    ▀   █▄▄▄▄  ▄█▄

       Light rain · °C
   feels 23° · H 25° L 20°
  wind 15 km/h SW · rain 68%
 Lisbon, Lisbon District, PT
       updated just now
```

The icon sits left of the digits, top-aligned with them, with a
2-column gap. The icon and digits are centered as one block.

### Detail lines

```
feels 9° · H 14° L 7°
wind 12 km/h NW · rain 40%
```

Feels-like, high and low are whole degrees, rounded like the big
temperature. Wind speed is a whole number in km/h or mph, and its
direction is the nearest of 8 compass points (N, NE, E, SE, S, SW, W,
NW). A speed that rounds below 1 reads `wind calm`, with no
direction. `rain` is today's highest precipitation chance.

A missing field leaves out only its own item: with no high or low the
first line reads `feels 9°`, and with no wind speed the second reads
`rain 40%`. A wind speed without a direction reads `wind 12 km/h`. A
line with no items left is dropped, and with no items at all the
largest layout is the same as big with icon.

A Reading fetched late in the day keeps that day's high and low until
the next successful fetch after midnight.

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
| full | icon and digits, blank, Condition line, detail lines, location, age | widest of those lines × 11 rows with both detail lines, 10 with one (16 or 15 in ASCII) |
| big with icon | icon and digits, blank, Condition line, location, age | widest of those lines × 9 rows (14 in ASCII) |
| big | digits, blank, Condition line, location, age | widest of those lines × 9 rows (14 in ASCII) |
| compact with age | `12°C Light rain`, age line | widest of the two × 2 |
| compact | `12°C Light rain` | its width × 1 |
| minimal | `12°C` | its width × 1 |
| blank | nothing | anything smaller |

Full and big with icon need a Sky. There is no layout with the
detail lines but no icon. Big and the tiers below it are the same with
or without a Sky, and show no icon.

Big digits are 5 columns wide, the minus and degree sign 4, with a
1-column gap between glyphs. `12°` is 16 columns wide. An icon adds
its width plus 2, so `12°` with the rain icon is 29 columns wide. The
icon row or the location line is usually the widest, so a long place
name moves the thresholds.

Without a Reading, the text shrinks: `label · cause · retry in 2m`,
then the cause alone (`offline`), then `!`. While fetching:
`label · fetching…`, then `fetching…`, then blank. `!` fits any pane
of at least 1×1.

Stale dimming applies in every tier that shows the temperature.
Nothing is clipped. On resize the screen is cleared once and the tier
is picked again.

## Icons

One static icon per Sky, 5 rows tall like the digits and 9 to 11
columns wide:

| Sky | Icon | Colors (256-color) |
|---|---|---|
| Clear, by day | sun | yellow |
| Clear, by night | crescent moon | pale yellow |
| Cloudy | cloud | light grey |
| Rain | cloud with drops | light grey, blue |
| Snow | cloud with flakes | light grey, white |
| Storm | dark cloud with a bolt | dark grey, yellow |

Day and night come from the Reading's day flag. Only Clear has a night
icon. The icon dims with the rest of a Stale Reading.

## Effects

| Sky | Effect |
|---|---|
| Rain, Storm | drops falling down about 30% of columns, `│╎·` in shades of blue |
| Snow | slower flakes, `*` and `·` in white and light grey, swaying a column either way |
| Clear, Cloudy, none | no Effect |

Storm has no lightning. An Effect shows only while the Reading is
Fresh, and only in the full and big-with-icon layouts. It draws in the
pane background and never inside the bounding box of the text and icon
plus a 1-cell margin, so a pane only just big enough for its layout
shows little or no Effect. The drops and flakes are placed at random
when an Effect starts showing, and again on each resize.

The pane draws 8 frames a second while an Effect shows and 1 a second
otherwise. The age line and retry countdown count from the monotonic
clock, so the frame rate doesn't change them.

## NO_COLOR and ASCII

The styling is the icon and Effect colors, and the dim on a Stale
Reading. When `NO_COLOR` is set to a non-empty value, the app emits no
SGR escapes. The icon is drawn uncolored and the Effect still
animates, uncolored. A Stale Reading is then drawn like a fresh one,
and only the age line and the stopped Effect show its age.

When stdout's encoding can't encode the block characters, `°`, `·`
and `…` (for example `PYTHONIOENCODING=ascii`), the big glyphs are
drawn with `#` at 10 rows tall, icons included, the degree sign is
left out of text (`12C Light rain`, `feels 9 - H 14 L 7`), `·`
becomes `-` and `…` becomes `...`. Drops are drawn with `|:.` and
flakes with `*` and `.`. Place
names lose their accents (`São Paulo` becomes `Sao Paulo`), in the
pane and in the non-tty line, and any other non-ASCII character
becomes `?`.

## Not a terminal

When stdout isn't a tty, as with a pipe, a redirect, cron or a tmux
status line, the app geocodes, fetches once and prints one line:

```
Lisbon, Lisbon District, PT 12°C Light rain
```

The line has only the location, temperature and Condition. It
exits 0. It emits no escape codes and doesn't enter the alternate
screen. If geocoding or the fetch fails, it prints the cause to stderr
(`weather.py: offline`), prints nothing to stdout, and exits 1. A
place name with no match exits 2, as above. It doesn't retry.

## Known limitations

- Only the top geocoding match is used. An ambiguous name can resolve
  to the wrong place, and the only way to pick another is a more
  specific name.
- No humidity, UV index, gusts, sunrise or sunset, and no hourly
  data.
- Readings are not saved to disk. A restart starts with no Reading.
- A fetch blocks the draw loop. A resize or the next second's frame can
  wait for up to the 3-second socket timeout. DNS lookups are not
  covered by that timeout and can take longer.
- The Effect freezes for the length of each fetch, longer when DNS
  stalls. During an outage this repeats at each retry, until the
  Reading goes Stale and the Effect stops.
- A pane only just big enough for its layout shows little or no
  Effect.
- After midnight, today's high and low are still yesterday's until
  the next successful fetch.
- Day and night follow the Reading's day flag, so the sun and moon can
  lag dusk and dawn by up to a Fetch interval.
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
