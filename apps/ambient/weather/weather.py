#!/usr/bin/env python3
"""Current weather for one place in an idle tmux pane.

Run: python3 apps/ambient/weather/weather.py <place>
"""

import argparse
import enum
import http.client
import json
import math
import os
import random
import select
import signal
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections import namedtuple

ENTER_ALT_SCREEN = "\033[?1049h"
LEAVE_ALT_SCREEN = "\033[?1049l"
HIDE_CURSOR = "\033[?25l"
SHOW_CURSOR = "\033[?25h"
HOME = "\033[H"
CLEAR_SCREEN = "\033[2J"
DIM = "\033[2m"
UNDIM = "\033[22m"
DEFAULT_FG = "\033[39m"

GAP = " "
ICON_GAP = "  "  # between the icon and the digits
DEFAULT_SIZE = (80, 24)

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
FETCH_TIMEOUT = 3  # seconds
# --units to the Reading's unit, then Open-Meteo's temperature and wind units.
UNITS = {"metric": ("C", "celsius", "kmh"), "imperial": ("F", "fahrenheit", "mph")}
WIND_UNITS = {"C": "km/h", "F": "mph"}  # the wind unit shown, by Reading unit

# A resolved location: its display name and coordinates.
Place = namedtuple("Place", "label latitude longitude")

# One successful fetch of current conditions and today's forecast. fetched_at
# is on the monotonic clock; unit is "C" or "F". sky is the Condition's Sky,
# or None for an unknown code. is_day is False only when the response says
# it is night. The rest are optional, None when the response lacks them:
# feels, high and low in the unit, wind_speed in km/h or mph to match it,
# wind_direction in degrees, and rain as today's precipitation chance in
# percent.
Reading = namedtuple(
    "Reading",
    "temperature condition unit fetched_at sky is_day feels high low wind_speed wind_direction rain",
    defaults=(None, True, None, None, None, None, None, None),
)

# A failed fetch, with its short cause: offline, timeout, HTTP <code>, or
# bad response.
Failure = namedtuple("Failure", "cause")

# Geocoding found nothing for the place name.
NO_MATCH = object()

# WMO weather codes, as Open-Meteo reports them, to Conditions.
CONDITIONS = {
    0: "Clear",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Rime fog",
    51: "Light drizzle",
    53: "Drizzle",
    55: "Heavy drizzle",
    56: "Freezing drizzle",
    57: "Freezing drizzle",
    61: "Light rain",
    63: "Rain",
    65: "Heavy rain",
    66: "Freezing rain",
    67: "Freezing rain",
    71: "Light snow",
    73: "Snow",
    75: "Heavy snow",
    77: "Snow grains",
    80: "Light showers",
    81: "Showers",
    82: "Heavy showers",
    85: "Snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm, hail",
    99: "Thunderstorm, hail",
}
UNKNOWN_CONDITION = "Unknown"

class Sky(enum.Enum):
    """The coarse group a Condition falls into."""

    CLEAR = "clear"
    CLOUDY = "cloudy"
    RAIN = "rain"
    SNOW = "snow"
    STORM = "storm"


# WMO weather codes to Skies. A code with no Condition has no Sky.
SKY_CODES = {
    Sky.CLEAR: range(0, 2),
    Sky.CLOUDY: [*range(2, 4), *range(45, 49)],
    Sky.RAIN: [*range(51, 68), *range(80, 83)],
    Sky.SNOW: [*range(71, 78), *range(85, 87)],
    Sky.STORM: range(95, 100),
}
SKIES = {code: sky for sky, codes in SKY_CODES.items() for code in codes if code in CONDITIONS}

FORECAST_CURRENT = ("temperature_2m", "weather_code", "apparent_temperature", "wind_speed_10m", "wind_direction_10m", "is_day")
FORECAST_DAILY = ("temperature_2m_max", "temperature_2m_min", "precipitation_probability_max")


def failure_cause(exc):
    """The short cause for an exception raised while fetching."""
    if isinstance(exc, urllib.error.HTTPError):
        return f"HTTP {exc.code}"
    if isinstance(exc, urllib.error.URLError):
        exc = exc.reason
    if isinstance(exc, TimeoutError):
        return "timeout"
    if isinstance(exc, OSError):
        return "offline"
    return "bad response"


def geocode_result(outcome):
    """A Place, NO_MATCH, or a Failure, from the geocoding response body or
    the exception raised fetching it."""
    if isinstance(outcome, BaseException):
        return Failure(failure_cause(outcome))
    try:
        results = json.loads(outcome).get("results") or []
        if not results:
            return NO_MATCH
        top = results[0]
        parts = (top["name"], top.get("admin1"), top.get("country_code"))
        return Place(", ".join(p for p in parts if p), float(top["latitude"]), float(top["longitude"]))
    except (ValueError, TypeError, KeyError, AttributeError):
        return Failure("bad response")


def forecast_result(outcome, unit, fetched_at):
    """A Reading or a Failure, from the forecast response body or the
    exception raised fetching it."""
    if isinstance(outcome, BaseException):
        return Failure(failure_cause(outcome))
    try:
        body = json.loads(outcome)
        current = body["current"]
        temperature = number(current["temperature_2m"])
        code = current["weather_code"]
        if temperature is None:
            raise ValueError(current["temperature_2m"])
        condition = CONDITIONS.get(code, UNKNOWN_CONDITION)
        sky = SKIES.get(code)
    except (ValueError, TypeError, KeyError):
        return Failure("bad response")
    daily = body.get("daily")
    return Reading(
        temperature,
        condition,
        unit,
        fetched_at,
        sky=sky,
        is_day=current.get("is_day") != 0,
        feels=number(current.get("apparent_temperature")),
        high=number(today(daily, "temperature_2m_max")),
        low=number(today(daily, "temperature_2m_min")),
        wind_speed=number(current.get("wind_speed_10m")),
        wind_direction=number(current.get("wind_direction_10m")),
        rain=number(today(daily, "precipitation_probability_max")),
    )


def number(value):
    """value as a float if it is a finite number, else None."""
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        return None
    return float(value)


def today(daily, key):
    """Today's value of a daily field, or None if the block lacks it."""
    values = daily.get(key) if isinstance(daily, dict) else None
    return values[0] if isinstance(values, list) and values else None


# Each glyph is a 10-row logical-pixel bitmap (twice the height that gets
# printed). Terminal cells are roughly twice as tall as wide, so packing
# two logical rows into one printed row (see pack_rows) undoes that and
# lets curved digits (0, 6, 8, 9) read as curved instead of blocky.
# The digits are copied from the clock.
DIGIT_BITMAPS = {
    "0": (
        " ### ",
        "#   #",
        "#   #",
        "#   #",
        "#   #",
        "#   #",
        "#   #",
        "#   #",
        "#   #",
        " ### ",
    ),
    "1": (
        "  #  ",
        " ##  ",
        "  #  ",
        "  #  ",
        "  #  ",
        "  #  ",
        "  #  ",
        "  #  ",
        "  #  ",
        " ### ",
    ),
    "2": (
        " ### ",
        "#   #",
        "    #",
        "    #",
        "   # ",
        "  #  ",
        " #   ",
        "#    ",
        "#    ",
        "#####",
    ),
    "3": (
        " ### ",
        "#   #",
        "    #",
        "    #",
        "  ## ",
        "  ## ",
        "    #",
        "    #",
        "#   #",
        " ### ",
    ),
    "4": (
        "   # ",
        "  ## ",
        " # # ",
        "#  # ",
        "#  # ",
        "#####",
        "   # ",
        "   # ",
        "   # ",
        "   # ",
    ),
    "5": (
        "#####",
        "#    ",
        "#    ",
        "#    ",
        "#### ",
        "    #",
        "    #",
        "    #",
        "#   #",
        " ### ",
    ),
    "6": (
        " ### ",
        "#    ",
        "#    ",
        "#    ",
        "#### ",
        "#   #",
        "#   #",
        "#   #",
        "#   #",
        " ### ",
    ),
    "7": (
        "#####",
        "    #",
        "   # ",
        "   # ",
        "  #  ",
        "  #  ",
        " #   ",
        " #   ",
        " #   ",
        " #   ",
    ),
    "8": (
        " ### ",
        "#   #",
        "#   #",
        "#   #",
        " ### ",
        "#   #",
        "#   #",
        "#   #",
        "#   #",
        " ### ",
    ),
    "9": (
        " ### ",
        "#   #",
        "#   #",
        "#   #",
        " ####",
        "    #",
        "    #",
        "    #",
        "    #",
        " ### ",
    ),
    "-": (
        "    ",
        "    ",
        "    ",
        "    ",
        "    ",
        "####",
        "    ",
        "    ",
        "    ",
        "    ",
    ),
    "°": (
        " ## ",
        "#  #",
        "#  #",
        " ## ",
        "    ",
        "    ",
        "    ",
        "    ",
        "    ",
        "    ",
    ),
}

# Sky icons, as 10-row logical-pixel bitmaps like the digits. Each letter is
# a part of the icon, drawn in that part's color (ICON_COLORS). Icons are
# drawn with "#" in ASCII.
ICON_BITMAPS = {
    "sun": (
        "  S  S  S  ",
        "           ",
        "    SSS    ",
        "S  SSSSS  S",
        "  SSSSSSS  ",
        "  SSSSSSS  ",
        "S  SSSSS  S",
        "    SSS    ",
        "           ",
        "  S  S  S  ",
    ),
    "moon": (
        "   MMMM  ",
        " MMMM    ",
        "MMMM     ",
        "MMM      ",
        "MMM      ",
        "MMM      ",
        "MMM      ",
        "MMMM     ",
        " MMMM    ",
        "   MMMM  ",
    ),
    "cloud": (
        "           ",
        "           ",
        "   CCC     ",
        "  CCCCC CC ",
        " CCCCCCCCCC",
        "CCCCCCCCCCC",
        "CCCCCCCCCCC",
        " CCCCCCCCC ",
        "           ",
        "           ",
    ),
    "rain cloud": (
        "   CCC     ",
        "  CCCCC CC ",
        " CCCCCCCCCC",
        "CCCCCCCCCCC",
        "CCCCCCCCCCC",
        " CCCCCCCCC ",
        "  R   R    ",
        "  R   R  R ",
        "    R    R ",
        "    R      ",
    ),
    "snow cloud": (
        "   CCC     ",
        "  CCCCC CC ",
        " CCCCCCCCCC",
        "CCCCCCCCCCC",
        "CCCCCCCCCCC",
        " CCCCCCCCC ",
        "           ",
        " F   F   F ",
        "           ",
        "   F   F   ",
    ),
    "storm cloud": (
        "   KKK     ",
        "  KKKKK KK ",
        " KKKKKKKKKK",
        "KKKKKKKKKKK",
        "KKKKKKKKKKK",
        " KKKKKKKKK ",
        "    BBB    ",
        "   BBB     ",
        "    BB     ",
        "   B       ",
    ),
}

# 256-color indices for the parts of the icons.
ICON_COLORS = {
    "S": 220,  # sun: yellow
    "M": 230,  # moon: pale yellow
    "C": 250,  # cloud: light grey
    "K": 243,  # storm cloud: dark grey
    "R": 75,  # rain: blue
    "F": 255,  # snow: white
    "B": 220,  # bolt: yellow
}


# Each Sky's icon. Only Clear has a night icon, the moon.
SKY_ICONS = {Sky.CLEAR: "sun", Sky.CLOUDY: "cloud", Sky.RAIN: "rain cloud", Sky.SNOW: "snow cloud", Sky.STORM: "storm cloud"}


def icon_name(sky, is_day):
    """The icon for a Sky, by day or by night."""
    return "moon" if sky is Sky.CLEAR and not is_day else SKY_ICONS[sky]


# Text glyphs that have an ASCII stand-in.
TEXT_GLYPHS = {True: {"deg": "°", "sep": " · ", "more": "…"}, False: {"deg": "", "sep": " - ", "more": "..."}}

Caps = namedtuple("Caps", "color unicode")


def detect_caps():
    """Read terminal capabilities once, at startup."""
    return Caps(color=not os.environ.get("NO_COLOR"), unicode=unicode_ok())


def unicode_ok():
    """Whether stdout can encode every non-ASCII glyph the app draws."""
    glyphs = "█▀▄" + "".join(TEXT_GLYPHS[True].values()) + "".join(RAIN_GLYPHS[True] + FLAKE_GLYPHS[True])
    try:
        glyphs.encode(sys.stdout.encoding or "ascii")
        return True
    except (UnicodeEncodeError, LookupError):
        return False


def pack_rows(rows):
    """Pack a 10-row logical bitmap into 5 printed rows via half-blocks."""
    packed = []
    for i in range(0, len(rows), 2):
        top, bottom = rows[i], rows[i + 1]
        line = []
        for t, b in zip(top, bottom):
            if t != " " and b != " ":
                line.append("█")  # full block
            elif t != " ":
                line.append("▀")  # upper half block
            elif b != " ":
                line.append("▄")  # lower half block
            else:
                line.append(" ")
        packed.append("".join(line))
    return tuple(packed)


BLOCK_GLYPHS = {ch: pack_rows(rows) for ch, rows in DIGIT_BITMAPS.items()}


def pack_colors(rows):
    """The color of each cell pack_rows makes from rows: its top part's
    color, else its bottom part's."""
    return tuple(
        tuple(ICON_COLORS.get(t if t != " " else b) for t, b in zip(rows[i], rows[i + 1]))
        for i in range(0, len(rows), 2)
    )


# Each icon as rows of text, and the color of each cell, per glyph set.
ICONS = {
    True: {name: (pack_rows(rows), pack_colors(rows)) for name, rows in ICON_BITMAPS.items()},
    False: {
        name: (
            tuple("".join(" " if ch == " " else "#" for ch in row) for row in rows),
            tuple(tuple(ICON_COLORS.get(ch) for ch in row) for row in rows),
        )
        for name, rows in ICON_BITMAPS.items()
    },
}


def ascii_text(text):
    """text with accents stripped and anything else non-ASCII as "?"."""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return stripped.encode("ascii", "replace").decode("ascii")


def shown_label(label, unicode):
    """The location label as drawn: as-is, or made ASCII for the fallback."""
    return label if unicode else ascii_text(label)


def big_text(chars, caps):
    """Lines of chars drawn in big glyphs."""
    glyphs = BLOCK_GLYPHS if caps.unicode else DIGIT_BITMAPS
    drawn = [glyphs[ch] for ch in chars]
    return [GAP.join(g[i] for g in drawn) for i in range(len(drawn[0]))]


def whole(value):
    """value rounded to a whole number, halves away from zero, as text.
    Never "-0"."""
    rounded = int(math.floor(abs(value) + 0.5))
    return f"-{rounded}" if value < 0 and rounded else str(rounded)


COMPASS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")


def compass_point(degrees):
    """The nearest of the 8 compass points to a direction in degrees."""
    return COMPASS[int(math.floor(degrees % 360 / 45 + 0.5)) % len(COMPASS)]


def detail_lines(reading, g):
    """The detail lines for a Reading: feels-like and today's high and low,
    then wind and today's precipitation chance. Each missing field leaves
    out only its own item, and a line with no items is left out."""

    def degrees(value):
        return f"{whole(value)}{g['deg']}"

    wind = None
    if reading.wind_speed is not None:
        speed = whole(reading.wind_speed)
        if int(speed) < 1:
            wind = "wind calm"
        else:
            wind = f"wind {speed} {WIND_UNITS[reading.unit]}"
            if reading.wind_direction is not None:
                wind += f" {compass_point(reading.wind_direction)}"
    high_low = " ".join(
        f"{letter} {degrees(value)}" for letter, value in (("H", reading.high), ("L", reading.low)) if value is not None
    )
    lines = (
        (reading.feels is not None and f"feels {degrees(reading.feels)}", high_low),
        (wind, reading.rain is not None and f"rain {whole(reading.rain)}%"),
    )
    return [g["sep"].join(item for item in items if item) for items in lines if any(items)]


FETCH_INTERVAL = 15 * 60  # seconds; fetches land on wall-clock quarter hours
BACKOFF = (60, 120, 240, 480, 900)  # seconds before each retry; the last repeats

# The current time on both clocks: wall (time.time) for aligning fetches to
# quarter hours, mono (time.monotonic) for everything measured.
Now = namedtuple("Now", "wall mono")

# The app state. label is the typed place name until geocoding resolves it,
# then the resolved name. place is the resolved Place, or None. reading is
# the current Reading, or None. cause is the last fetch's failure cause, or
# None if it succeeded or nothing has been tried yet. failures counts
# consecutive failed fetches. next_fetch is when the next fetch is due, on
# the monotonic clock.
State = namedtuple("State", "label place reading cause failures next_fetch")


def initial_state(typed_name):
    return State(typed_name, None, None, None, 0, -math.inf)


def resolved(state, place, now):
    """Geocoding matched the place name. A Reading is due at once."""
    return state._replace(label=place.label, place=place, cause=None, failures=0, next_fetch=now.mono)


def fetched(state, reading, now):
    """A fetch succeeded with this Reading. The next is due on the next
    quarter hour."""
    boundary = (math.floor(now.wall / FETCH_INTERVAL) + 1) * FETCH_INTERVAL
    return state._replace(reading=reading, cause=None, failures=0, next_fetch=now.mono + boundary - now.wall)


def failed(state, cause, now):
    """A geocoding or forecast fetch failed with this cause. Retry after the
    backoff for this many consecutive failures."""
    delay = BACKOFF[min(state.failures, len(BACKOFF) - 1)]
    return state._replace(cause=cause, failures=state.failures + 1, next_fetch=now.mono + delay)


STALE_AFTER = 2 * FETCH_INTERVAL  # seconds
EXPIRED_AFTER = 3 * 60 * 60  # seconds
FRESH, STALE, EXPIRED = "fresh", "stale", "expired"


def freshness(reading, mono):
    """FRESH, STALE or EXPIRED, by the Reading's age at mono."""
    age = mono - reading.fetched_at
    if age >= EXPIRED_AFTER:
        return EXPIRED
    return STALE if age >= STALE_AFTER else FRESH


def expire(state, mono):
    """The state without its Reading once that Reading is Expired."""
    if state.reading is not None and freshness(state.reading, mono) is EXPIRED:
        return state._replace(reading=None)
    return state


def is_due(state, mono):
    return mono >= state.next_fetch


def age_text(seconds):
    minutes = int(seconds // 60)
    if minutes < 1:
        return "just now"
    if minutes < 60:
        return f"{minutes}m ago"
    return f"{minutes // 60}h {minutes % 60}m ago"


def retry_text(state, mono, g):
    remaining = state.next_fetch - mono
    if remaining <= 0:
        return f"retrying{g['more']}"
    return f"retry in {math.ceil(remaining / 60)}m"


# One line of a size tier: its text, whether it belongs to a Stale Reading,
# and the 256-color index of each character, or None for no colors.
Line = namedtuple("Line", "text dim colors", defaults=(False, None))

FULL, BIG_ICON, BIG, COMPACT_AGE, COMPACT, MINIMAL = (
    "full",
    "big with icon",
    "big",
    "compact with age",
    "compact",
    "minimal",
)


def icon_rows(reading, digits, caps, stale):
    """The Sky icon and the big digits side by side, as Lines."""
    text, colors = ICONS[caps.unicode][icon_name(reading.sky, reading.is_day)]
    return [
        Line(icon + ICON_GAP + row, stale, shades + (None,) * (len(ICON_GAP) + len(row)))
        for icon, shades, row in zip(text, colors, digits)
    ]


def tiers(state, mono, caps):
    """Size tiers, largest first, as (name, Lines) pairs.

    With a Reading: the Sky icon beside the big digits, with the Condition
    line, the detail lines, and the location and age lines; the same without
    the detail lines (these two only when the Reading has a Sky); the big
    digits alone, with the Condition, location and age lines; the
    temperature and Condition on one line, with the age under it; that line
    alone; the temperature alone. Without one: the
    label, cause and retry countdown on one line; the cause alone; "!".
    While fetching: the label and "fetching…"; "fetching…" alone.
    """
    g = TEXT_GLYPHS[caps.unicode]
    state = expire(state, mono)
    label = shown_label(state.label, caps.unicode)
    reading = state.reading
    if reading is not None:
        stale = freshness(reading, mono) is STALE
        degrees = whole(reading.temperature)
        temperature = f"{degrees}{g['deg']}{reading.unit}"
        compact = Line(f"{temperature} {reading.condition}", stale)
        age = f"updated {age_text(mono - reading.fetched_at)}"
        if state.cause is not None:
            age += g["sep"] + state.cause
        digits = big_text(degrees + "°", caps)
        condition = [Line(""), Line(f"{reading.condition}{g['sep']}{g['deg']}{reading.unit}", stale)]
        where = [Line(label), Line(age)]
        found = []
        if reading.sky is not None:
            icon = icon_rows(reading, digits, caps, stale)
            details = [Line(text, stale) for text in detail_lines(reading, g)]
            if details:
                found.append((FULL, icon + condition + details + where))
            found.append((BIG_ICON, icon + condition + where))
        return found + [
            (BIG, [Line(row, stale) for row in digits] + condition + where),
            (COMPACT_AGE, [compact, Line(age)]),
            (COMPACT, [compact]),
            (MINIMAL, [Line(temperature, stale)]),
        ]
    if state.cause is None:
        fetching = f"fetching{g['more']}"
        return [(COMPACT, [Line(label + g["sep"] + fetching)]), (MINIMAL, [Line(fetching)])]
    full = g["sep"].join((label, state.cause, retry_text(state, mono, g)))
    return [(COMPACT, [Line(full)]), (MINIMAL, [Line(state.cause)]), (MINIMAL, [Line("!")])]


def layout(state, mono, cols, rows, caps):
    """The Lines of the largest size tier that fits the pane, and the Effect
    that shows around them, or None.

    An Effect shows only while the Reading is Fresh, only in the icon tiers,
    and only for a Sky that has one.
    """
    for name, lines in tiers(state, mono, caps):
        if max(len(line.text) for line in lines) <= cols and len(lines) <= rows:
            break
    else:
        return [], None
    reading = expire(state, mono).reading
    if name not in (FULL, BIG_ICON) or freshness(reading, mono) is not FRESH:
        return lines, None
    return lines, SKY_EFFECTS.get(reading.sky)


def build_frame(state, mono, cols, rows, caps, effect_state=None):
    """One complete frame for the pane: cursor-home, then every cell.

    Pure: the state, the monotonic time, the pane size, the capabilities and
    the Effect state are all inputs, and mono also sets where the Effect is
    in its motion. Freshness is judged at mono, so an Expired Reading is
    never drawn even if it is still in the state. The block of lines is
    centered as a whole, and each line is centered on its own within it.
    The Effect, when one shows, never draws inside the block's bounding box
    plus a 1-cell margin.
    """
    lines, effect = layout(state, mono, cols, rows, caps)
    # Each cell is (character, 256-color index or None, dim).
    cells = [[(" ", None, False)] * cols for _ in range(rows)]
    top = (rows - len(lines)) // 2

    if effect is not None and effect_state is not None:
        width = max(len(line.text) for line in lines)
        left = (cols - width) // 2
        bottom, right = top + len(lines) - 1, left + width - 1
        for r, c, ch, color in effect.glyphs(effect_state, mono, cols, rows, caps.unicode):
            in_margin = top - 1 <= r <= bottom + 1 and left - 1 <= c <= right + 1
            if 0 <= r < rows and 0 <= c < cols and not in_margin:
                cells[r][c] = (ch, color, False)

    for i, line in enumerate(lines):
        left = (cols - len(line.text)) // 2
        dim = line.dim and bool(line.text.strip())
        for j, ch in enumerate(line.text):
            cells[top + i][left + j] = (ch, line.colors[j] if line.colors else None, dim)
    return HOME + "\r\n".join(paint(row, caps) for row in cells)


def paint(row, caps):
    """One row of cells as text, with color and dim escapes only if color is
    on. Each row ends with the default style."""
    if not caps.color:
        return "".join(ch for ch, _, _ in row)
    out = []
    color, dim = None, False
    for ch, cell_color, cell_dim in row:
        if cell_dim != dim:
            out.append(DIM if cell_dim else UNDIM)
            dim = cell_dim
        if cell_color != color:
            out.append(DEFAULT_FG if cell_color is None else f"\033[38;5;{cell_color}m")
            color = cell_color
        out.append(ch)
    if dim:
        out.append(UNDIM)
    if color is not None:
        out.append(DEFAULT_FG)
    return "".join(out)


def showing_effect(state, mono, cols, rows, caps):
    """The Effect build_frame draws for these inputs, or None."""
    return layout(state, mono, cols, rows, caps)[1]


def frame_rate(state, mono, cols, rows, caps):
    """Frames per second for build_frame's frame with these inputs."""
    return effect_fps(showing_effect(state, mono, cols, rows, caps))


def effect_fps(effect):
    """Frames per second: EFFECT_FPS while an Effect is showing, else 1."""
    return EFFECT_FPS if effect else 1


# An Effect is the time-varying part of a frame: seed(cols, rows, rng)
# returns its state as plain data, and glyphs(state, t, cols, rows, unicode)
# yields (row, col, char, color) to draw around the block.
Effect = namedtuple("Effect", "seed glyphs")
EFFECT_FPS = 8

# Drops: falling slowly down some columns, each column with its own speed,
# length and gap between drops. Copied from the clock's rain. Tuning
# constants, chosen by eye.
RAIN_COLUMNS = 0.3  # fraction of columns with rain
RAIN_SPEED = (2.0, 6.0)  # rows a second
RAIN_LENGTH = (2, 6)  # rows, including the leading glyph
RAIN_GAP = (0.5, 2.0)  # rows between drops, as a multiple of pane height
RAIN_GLYPHS = {True: ("│", "╎", "·"), False: ("|", ":", ".")}  # lead to tail
RAIN_COLORS = (153, 110, 67, 60)  # lead to tail
Drop = namedtuple("Drop", "speed length span offset")


def seed_rain(cols, rows, rng):
    """One Drop, or None, per column."""
    columns = []
    for _ in range(cols):
        if rng.random() >= RAIN_COLUMNS:
            columns.append(None)
            continue
        length = rng.randint(*RAIN_LENGTH)
        span = rows + length + round(rows * rng.uniform(*RAIN_GAP))
        columns.append(Drop(rng.uniform(*RAIN_SPEED), length, span, rng.uniform(0, span)))
    return columns


def rain_glyphs(columns, t, cols, rows, unicode):
    glyphs = RAIN_GLYPHS[unicode]
    for col, drop in enumerate(columns):
        if drop is None:
            continue
        lead = int((drop.offset + t * drop.speed) % drop.span)
        for k in range(drop.length):
            shade = k / drop.length
            yield (
                lead - k,
                col,
                glyphs[int(shade * len(glyphs))],
                RAIN_COLORS[int(shade * len(RAIN_COLORS))],
            )


# Flakes: the drops' approach, slower, one flake at a time per column, each
# swaying a column either way as it falls. Tuning constants, chosen by eye.
FLAKE_COLUMNS = 0.45  # fraction of columns with snow
FLAKE_SPEED = (0.6, 1.8)  # rows a second
FLAKE_GAP = (0.1, 0.8)  # rows between flakes, as a multiple of pane height
FLAKE_SWAY = (0.3, 0.9)  # radians a second
FLAKE_GLYPHS = {True: ("·", "*"), False: (".", "*")}  # small to large
FLAKE_COLORS = (250, 255)  # small to large
Flake = namedtuple("Flake", "speed span offset size sway phase")


def seed_snow(cols, rows, rng):
    """One Flake, or None, per column."""
    columns = []
    for _ in range(cols):
        if rng.random() >= FLAKE_COLUMNS:
            columns.append(None)
            continue
        span = rows + 1 + round(rows * rng.uniform(*FLAKE_GAP))
        columns.append(
            Flake(
                rng.uniform(*FLAKE_SPEED),
                span,
                rng.uniform(0, span),
                rng.randrange(len(FLAKE_GLYPHS[True])),
                rng.uniform(*FLAKE_SWAY),
                rng.uniform(0, 2 * math.pi),
            )
        )
    return columns


def snow_glyphs(columns, t, cols, rows, unicode):
    glyphs = FLAKE_GLYPHS[unicode]
    for col, flake in enumerate(columns):
        if flake is None:
            continue
        yield (
            int((flake.offset + t * flake.speed) % flake.span),
            col + round(math.sin(t * flake.sway + flake.phase)),
            glyphs[flake.size],
            FLAKE_COLORS[flake.size],
        )


DROPS = Effect(seed_rain, rain_glyphs)
FLAKES = Effect(seed_snow, snow_glyphs)
SKY_EFFECTS = {Sky.RAIN: DROPS, Sky.STORM: DROPS, Sky.SNOW: FLAKES}


def get_pane_size():
    try:
        size = os.get_terminal_size()
        return size.columns, size.lines
    except OSError:
        return DEFAULT_SIZE


Args = namedtuple("Args", "place units")


def make_parser():
    parser = argparse.ArgumentParser(
        description="Current weather for one place, from Open-Meteo.",
    )
    parser.add_argument(
        "place",
        nargs="+",
        help="place name, geocoded once at startup; the top match is used "
        "(multi-word names need no quotes)",
    )
    parser.add_argument(
        "--units",
        choices=list(UNITS),
        default="metric",
        help="metric (°C) or imperial (°F) (default: %(default)s)",
    )
    return parser


def parse_args(argv):
    """The place name and units selected on the command line."""
    ns = make_parser().parse_args(argv)
    return Args(" ".join(ns.place), ns.units)


def no_match_error(place):
    """Exit 2 with a usage error: geocoding found nothing."""
    make_parser().error(f"no place matches {place!r}")


def geocode_url(name):
    return GEOCODE_URL + "?" + urllib.parse.urlencode({"name": name, "count": 1, "language": "en", "format": "json"})


def forecast_url(place, units):
    return (
        FORECAST_URL
        + "?"
        + urllib.parse.urlencode(
            {
                "latitude": place.latitude,
                "longitude": place.longitude,
                "current": ",".join(FORECAST_CURRENT),
                "daily": ",".join(FORECAST_DAILY),
                "forecast_days": 1,
                "timezone": "auto",
                "temperature_unit": UNITS[units][1],
                "wind_speed_unit": UNITS[units][2],
            }
        )
    )


def http_get(url):
    """The response body, or the exception raised getting it."""
    try:
        with urllib.request.urlopen(url, timeout=FETCH_TIMEOUT) as response:
            return response.read()
    except (OSError, http.client.HTTPException, ValueError) as exc:
        return exc


def next_boundary(now, fps):
    """The first frame boundary strictly after now, at fps frames a second.

    Boundaries are k / fps, so with an integer fps every whole second is one.
    """
    k = math.floor(now * fps) + 1
    while k / fps <= now:
        k += 1
    return k / fps


def wait_until(deadline, wake_fd):
    """Sleep until deadline, or until a resize arrives."""
    while not resized:
        timeout = deadline - time.time()
        if timeout <= 0:
            return
        ready, _, _ = select.select([wake_fd], [], [], timeout)
        if ready:
            try:
                os.read(wake_fd, 4096)
            except BlockingIOError:
                pass


def write_out(text):
    """Write text to stdout in one write, bypassing Python's buffering."""
    data = text.encode(sys.stdout.encoding or "utf-8")
    while data:
        data = data[os.write(1, data) :]


def teardown(caps):
    reset = UNDIM + DEFAULT_FG if caps.color else ""
    try:
        write_out(reset + SHOW_CURSOR + LEAVE_ALT_SCREEN)
    except OSError:
        pass


resized = False


def handle_signal(signum, frame):
    sys.exit(0)


def handle_winch(signum, frame):
    global resized
    resized = True


def step(state, args, get):
    """Fetch whatever the state needs next, the place and then a Reading,
    with get (http_get, or a stand-in). Returns the new state, or NO_MATCH."""
    if state.place is None:
        result = geocode_result(get(geocode_url(args.place)))
        now = Now(time.time(), time.monotonic())
        if result is NO_MATCH:
            return NO_MATCH
        return failed(state, result.cause, now) if isinstance(result, Failure) else resolved(state, result, now)
    outcome = get(forecast_url(state.place, args.units))
    now = Now(time.time(), time.monotonic())
    result = forecast_result(outcome, UNITS[args.units][0], now.mono)
    return failed(state, result.cause, now) if isinstance(result, Failure) else fetched(state, result, now)


def one_line(label, reading, unicode):
    """The Reading as one plain line, for when stdout isn't a tty."""
    deg = TEXT_GLYPHS[unicode]["deg"]
    return f"{shown_label(label, unicode)} {whole(reading.temperature)}{deg}{reading.unit} {reading.condition}"


def run_plain(args, get, unicode, out):
    """Geocode, fetch once and print one line to out. Returns the exit
    status: 0, or 1 with the cause on stderr. No match exits 2."""
    state = initial_state(args.place)
    while state.reading is None:
        state = step(state, args, get)
        if state is NO_MATCH:
            no_match_error(args.place)
        if state.cause is not None:
            print(f"{os.path.basename(sys.argv[0])}: {state.cause}", file=sys.stderr)
            return 1
    print(one_line(state.label, state.reading, unicode), file=out)
    return 0


def run_pane(args, caps, wake_fd):
    """Draw frames at the frame rate, fetching whenever one is due, until a
    signal ends the app. Returns NO_MATCH if geocoding finds nothing, or
    None if the pty goes away."""
    global resized
    state = initial_state(args.place)
    rng = random.Random()
    effect_state, seeded_for = None, None
    while True:
        # Take the flag before reading the size, so a resize that lands
        # mid-frame is still seen, and cleared for, next time round.
        was_resized, resized = resized, False
        cols, rows = get_pane_size()
        mono = time.monotonic()
        state = expire(state, mono)
        # Seed the Effect as it starts showing, and again on resize.
        effect = showing_effect(state, mono, cols, rows, caps)
        if effect is None:
            seeded_for = None
        elif was_resized or seeded_for != (effect, cols, rows):
            effect_state = effect.seed(cols, rows, rng)
            seeded_for = (effect, cols, rows)
        frame = build_frame(state, mono, cols, rows, caps, effect_state)
        if was_resized:
            frame = CLEAR_SCREEN + frame
        try:
            write_out(frame)
        except OSError:
            return None  # the pty is gone
        if is_due(state, mono):
            # The frame just drawn stays up while the fetch blocks, and the
            # Effect with it. Draw the outcome straight away, then go back
            # to frame boundaries.
            state = step(state, args, http_get)
            if state is NO_MATCH:
                return NO_MATCH
            continue
        fps = effect_fps(effect)
        wait_until(next_boundary(time.time(), fps), wake_fd)


def main():
    args = parse_args(sys.argv[1:])
    caps = detect_caps()
    if not sys.stdout.isatty():
        sys.exit(run_plain(args, http_get, caps.unicode, sys.stdout))

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGHUP, handle_signal)
    signal.signal(signal.SIGWINCH, handle_winch)
    wake_fd, wake_write_fd = os.pipe()
    os.set_blocking(wake_fd, False)
    os.set_blocking(wake_write_fd, False)
    signal.set_wakeup_fd(wake_write_fd)

    try:
        write_out(ENTER_ALT_SCREEN + HIDE_CURSOR)
        outcome = run_pane(args, caps, wake_fd)
    finally:
        teardown(caps)
    if outcome is NO_MATCH:
        no_match_error(args.place)


if __name__ == "__main__":
    main()
