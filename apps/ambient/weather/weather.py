#!/usr/bin/env python3
"""Current weather for one place in an idle tmux pane.

Run: python3 apps/ambient/weather/weather.py <place>
"""

import argparse
import http.client
import json
import math
import os
import select
import signal
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import namedtuple

ENTER_ALT_SCREEN = "\033[?1049h"
LEAVE_ALT_SCREEN = "\033[?1049l"
HIDE_CURSOR = "\033[?25l"
SHOW_CURSOR = "\033[?25h"
HOME = "\033[H"
CLEAR = "\033[2J"

GAP = " "
DEFAULT_SIZE = (80, 24)

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
FETCH_TIMEOUT = 3  # seconds
UNITS = {"metric": ("C", "celsius"), "imperial": ("F", "fahrenheit")}

# A resolved location: its display name and coordinates.
Place = namedtuple("Place", "label latitude longitude")

# One successful fetch of current conditions. fetched_at is on the monotonic
# clock; unit is "C" or "F".
Reading = namedtuple("Reading", "temperature condition unit fetched_at")

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
        current = json.loads(outcome)["current"]
        temperature = current["temperature_2m"]
        code = current["weather_code"]
        if not isinstance(temperature, (int, float)) or isinstance(temperature, bool):
            raise TypeError(temperature)
    except (ValueError, TypeError, KeyError):
        return Failure("bad response")
    return Reading(float(temperature), CONDITIONS.get(code, UNKNOWN_CONDITION), unit, fetched_at)


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

# Text glyphs that have an ASCII stand-in.
TEXT_GLYPHS = {True: {"deg": "°", "sep": " · ", "more": "…"}, False: {"deg": "", "sep": " - ", "more": "..."}}

Caps = namedtuple("Caps", "color unicode")


def detect_caps():
    """Read terminal capabilities once, at startup."""
    return Caps(color=not os.environ.get("NO_COLOR"), unicode=unicode_ok())


def unicode_ok():
    """Whether stdout can encode every non-ASCII glyph the app draws."""
    glyphs = "█▀▄" + "".join(TEXT_GLYPHS[True].values())
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


def big_text(chars, caps):
    """Lines of chars drawn in big glyphs."""
    glyphs = BLOCK_GLYPHS if caps.unicode else DIGIT_BITMAPS
    drawn = [glyphs[ch] for ch in chars]
    return [GAP.join(g[i] for g in drawn) for i in range(len(drawn[0]))]


def whole_degrees(temperature):
    """The temperature rounded to whole degrees, halves away from zero,
    as text. Never "-0"."""
    rounded = int(math.floor(abs(temperature) + 0.5))
    return f"-{rounded}" if temperature < 0 and rounded else str(rounded)


# The app state. label is the typed place name until geocoding resolves it,
# then the resolved name. place is the resolved Place, or None. reading is
# the current Reading, or None. cause is the last fetch's failure cause, or
# None if it succeeded or nothing has been tried yet.
State = namedtuple("State", "label place reading cause")


def initial_state(typed_name):
    return State(typed_name, None, None, None)


def resolved(state, place):
    """Geocoding matched the place name."""
    return state._replace(label=place.label, place=place, cause=None)


def fetched(state, reading):
    """A fetch succeeded with this Reading."""
    return state._replace(reading=reading, cause=None)


def failed(state, cause):
    """A geocoding or forecast fetch failed with this cause."""
    return state._replace(cause=cause)


def layouts(state, caps):
    """Candidate layouts, largest first. Each is a list of lines."""
    g = TEXT_GLYPHS[caps.unicode]
    reading = state.reading
    if reading is not None:
        return [
            big_text(whole_degrees(reading.temperature) + "°", caps)
            + ["", f"{reading.condition}{g['sep']}{g['deg']}{reading.unit}", state.label]
        ]
    if state.cause is None:
        return [[f"{state.label}{g['sep']}fetching{g['more']}"]]
    return [[f"{state.label}{g['sep']}{state.cause}"]]


def pick_layout(state, cols, rows, caps):
    """The largest layout that fits the pane, or [] for a blank pane."""
    for lines in layouts(state, caps):
        if max(len(line) for line in lines) <= cols and len(lines) <= rows:
            return lines
    return []


def build_frame(state, mono, cols, rows, caps):
    """One complete frame for the pane: cursor-home, then every cell.

    Pure: the state, the monotonic time, the pane size and the capabilities
    are all inputs. The block of lines is centered as a whole, and each line
    is centered on its own within it.
    """
    lines = pick_layout(state, cols, rows, caps)
    cells = [[" "] * cols for _ in range(rows)]
    top = (rows - len(lines)) // 2
    for i, line in enumerate(lines):
        left = (cols - len(line)) // 2
        cells[top + i][left : left + len(line)] = line
    return HOME + "\r\n".join("".join(row) for row in cells)


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
                "current": "temperature_2m,weather_code",
                "temperature_unit": UNITS[units][1],
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


def next_boundary(now):
    """The first whole second strictly after now."""
    return math.floor(now) + 1


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
    try:
        write_out(SHOW_CURSOR + LEAVE_ALT_SCREEN)
    except OSError:
        pass


resized = False


def handle_signal(signum, frame):
    sys.exit(0)


def handle_winch(signum, frame):
    global resized
    resized = True


def step(state, args):
    """Fetch whatever the state needs next: the place, then a Reading.
    Returns the new state, or NO_MATCH."""
    if state.place is None:
        result = geocode_result(http_get(geocode_url(args.place)))
        if result is NO_MATCH:
            return NO_MATCH
        return failed(state, result.cause) if isinstance(result, Failure) else resolved(state, result)
    outcome = http_get(forecast_url(state.place, args.units))
    result = forecast_result(outcome, UNITS[args.units][0], time.monotonic())
    return failed(state, result.cause) if isinstance(result, Failure) else fetched(state, result)


def run_pane(args, caps, wake_fd):
    """Draw frames until a signal ends the app. Returns NO_MATCH if
    geocoding finds nothing, or None if the pty goes away."""
    global resized
    state = initial_state(args.place)
    tried = False
    while True:
        # Take the flag before reading the size, so a resize that lands
        # mid-frame is still seen, and cleared for, next time round.
        was_resized, resized = resized, False
        cols, rows = get_pane_size()
        frame = build_frame(state, time.monotonic(), cols, rows, caps)
        if was_resized:
            frame = CLEAR + frame
        try:
            write_out(frame)
        except OSError:
            return None  # the pty is gone
        if not tried or state.place is not None and state.reading is None and state.cause is None:
            tried = True
            state = step(state, args)
            if state is NO_MATCH:
                return NO_MATCH
            continue
        wait_until(next_boundary(time.time()), wake_fd)


def main():
    args = parse_args(sys.argv[1:])
    caps = detect_caps()

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
