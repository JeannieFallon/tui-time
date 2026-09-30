"""Tests for weather.py. Run: python3 -m unittest apps/ambient/weather/test_weather.py"""

import http.client
import json
import os
import random
import re
import socket
import sys
import unittest
import urllib.error
import urllib.parse
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import weather  # noqa: E402

LISBON_JSON = json.dumps(
    {
        "results": [
            {
                "id": 2267057,
                "name": "Lisbon",
                "latitude": 38.72509,
                "longitude": -9.1498,
                "country_code": "PT",
                "country": "Portugal",
                "admin1": "Lisbon District",
                "admin2": "Lisbon Municipality",
            }
        ],
        "generationtime_ms": 0.56,
    }
).encode()
NO_MATCH_JSON = b'{"generationtime_ms":0.49}'
MISSING = object()  # marks a field left out of a response


def forecast_json(temperature=12.3, code=61, unit="°C"):
    return json.dumps(
        {
            "latitude": 38.75,
            "longitude": -9.125,
            "current_units": {"time": "iso8601", "interval": "seconds", "temperature_2m": unit, "weather_code": "wmo code"},
            "current": {"time": "2026-09-29T21:30", "interval": 900, "temperature_2m": temperature, "weather_code": code},
        }
    ).encode()


FULL_CURRENT = {
    "time": "2026-09-29T21:30",
    "interval": 900,
    "temperature_2m": 12.3,
    "weather_code": 61,
    "apparent_temperature": 9.4,
    "wind_speed_10m": 12.2,
    "wind_direction_10m": 310,
    "is_day": 1,
}
FULL_DAILY = {
    "time": ["2026-09-29"],
    "temperature_2m_max": [14.2],
    "temperature_2m_min": [6.6],
    "precipitation_probability_max": [40],
}


def full_forecast_json(**fields):
    """A forecast response with every field. A keyword replaces one field
    (None for null), or leaves it out when MISSING."""
    current, daily = dict(FULL_CURRENT), dict(FULL_DAILY)
    for key, value in fields.items():
        target = current if key in current else daily
        if value is MISSING:
            del target[key]
        else:
            target[key] = value if target is current else [value]
    return json.dumps({"latitude": 38.75, "longitude": -9.125, "current": current, "daily": daily}).encode()


class GeocodeResultTest(unittest.TestCase):
    def test_top_match_becomes_a_place_named_with_region_and_country(self):
        place = weather.geocode_result(LISBON_JSON)
        self.assertEqual(place, weather.Place("Lisbon, Lisbon District, PT", 38.72509, -9.1498))

    def test_missing_region_is_left_out_of_the_name(self):
        body = json.dumps({"results": [{"name": "Monaco", "latitude": 43.7, "longitude": 7.4, "country_code": "MC"}]})
        self.assertEqual(weather.geocode_result(body.encode()).label, "Monaco, MC")

    def test_no_results_is_no_match(self):
        self.assertIs(weather.geocode_result(NO_MATCH_JSON), weather.NO_MATCH)
        self.assertIs(weather.geocode_result(b'{"results": []}'), weather.NO_MATCH)

    def test_malformed_json_is_a_bad_response(self):
        self.assertEqual(weather.geocode_result(b"<html>oops"), weather.Failure("bad response"))

    def test_missing_coordinates_are_a_bad_response(self):
        body = json.dumps({"results": [{"name": "Lisbon", "country_code": "PT"}]}).encode()
        self.assertEqual(weather.geocode_result(body), weather.Failure("bad response"))

    def test_an_exception_is_a_failure(self):
        self.assertEqual(weather.geocode_result(TimeoutError()), weather.Failure("timeout"))


class ForecastResultTest(unittest.TestCase):
    def test_current_conditions_become_a_reading_fetched_at_the_given_time(self):
        reading = weather.forecast_result(forecast_json(12.3, 61), "C", fetched_at=500.0)
        self.assertEqual(reading, weather.Reading(12.3, "Light rain", "C", 500.0, sky=weather.Sky.RAIN))

    def test_every_field_becomes_part_of_the_reading(self):
        reading = weather.forecast_result(full_forecast_json(), "C", fetched_at=500.0)
        self.assertEqual(
            reading,
            weather.Reading(
                12.3,
                "Light rain",
                "C",
                500.0,
                sky=weather.Sky.RAIN,
                is_day=True,
                feels=9.4,
                high=14.2,
                low=6.6,
                wind_speed=12.2,
                wind_direction=310.0,
                rain=40.0,
            ),
        )

    def test_each_new_field_missing_or_null_leaves_only_that_item_out(self):
        full = weather.forecast_result(full_forecast_json(), "C", 0.0)
        fields = {
            "apparent_temperature": "feels",
            "temperature_2m_max": "high",
            "temperature_2m_min": "low",
            "precipitation_probability_max": "rain",
            "wind_speed_10m": "wind_speed",
            "wind_direction_10m": "wind_direction",
        }
        for key, attr in fields.items():
            for value in (MISSING, None, "windy"):
                with self.subTest(key=key, value=value):
                    reading = weather.forecast_result(full_forecast_json(**{key: value}), "C", 0.0)
                    self.assertEqual(reading, full._replace(**{attr: None}))

    def test_missing_or_null_is_day_counts_as_day(self):
        for value in (MISSING, None):
            with self.subTest(value=value):
                self.assertTrue(weather.forecast_result(full_forecast_json(is_day=value), "C", 0.0).is_day)
        self.assertFalse(weather.forecast_result(full_forecast_json(is_day=0), "C", 0.0).is_day)

    def test_missing_or_malformed_daily_block_leaves_only_the_daily_items_out(self):
        full = weather.forecast_result(full_forecast_json(), "C", 0.0)
        daily_absent = full._replace(high=None, low=None, rain=None)
        for daily in (MISSING, None, [], {"temperature_2m_max": []}, {"temperature_2m_max": 14.2}):
            with self.subTest(daily=daily):
                body = json.loads(full_forecast_json())
                if daily is MISSING:
                    del body["daily"]
                else:
                    body["daily"] = daily
                self.assertEqual(weather.forecast_result(json.dumps(body).encode(), "C", 0.0), daily_absent)

    def test_unknown_weather_code_maps_to_a_generic_condition(self):
        self.assertEqual(weather.forecast_result(forecast_json(code=42), "C", 0.0).condition, "Unknown")

    def test_malformed_json_is_a_bad_response(self):
        self.assertEqual(weather.forecast_result(b'{"current": ', "C", 0.0), weather.Failure("bad response"))

    def test_missing_fields_are_a_bad_response(self):
        for body in (
            b"{}",
            b"[]",
            b'{"current": {"weather_code": 3}}',
            b'{"current": {"temperature_2m": 12.0}}',
            b'{"current": {"temperature_2m": null, "weather_code": 3}}',
            b'{"current": {"temperature_2m": "warm", "weather_code": 3}}',
            b'{"current": {"temperature_2m": NaN, "weather_code": 3}}',
            b'{"current": {"temperature_2m": Infinity, "weather_code": 3}}',
            b'{"current": {"temperature_2m": 12.0, "weather_code": [61]}}',
        ):
            with self.subTest(body=body):
                self.assertEqual(weather.forecast_result(body, "C", 0.0), weather.Failure("bad response"))


class FailureCauseTest(unittest.TestCase):
    def test_each_exception_maps_to_its_cause(self):
        cases = [
            (urllib.error.HTTPError("u", 503, "Service Unavailable", {}, None), "HTTP 503"),
            (urllib.error.HTTPError("u", 404, "Not Found", {}, None), "HTTP 404"),
            (TimeoutError("timed out"), "timeout"),
            (socket.timeout("timed out"), "timeout"),
            (urllib.error.URLError(TimeoutError("timed out")), "timeout"),
            (urllib.error.URLError(socket.gaierror(-3, "Temporary failure in name resolution")), "offline"),
            (urllib.error.URLError(ConnectionRefusedError(111, "Connection refused")), "offline"),
            (ConnectionResetError(104, "Connection reset by peer"), "offline"),
            (http.client.RemoteDisconnected("closed"), "offline"),
            (http.client.IncompleteRead(b""), "bad response"),
            (ValueError("bad"), "bad response"),
        ]
        for exc, cause in cases:
            with self.subTest(exc=repr(exc)):
                self.assertEqual(weather.forecast_result(exc, "C", 0.0), weather.Failure(cause))


CSI = re.compile(r"\033\[[0-9;?]*[A-Za-z]")
SGR = re.compile(r"\033\[[0-9;]*m")
UNICODE = weather.Caps(color=True, unicode=True)
ASCII = weather.Caps(color=True, unicode=False)
LISBON = weather.Place("Lisbon, Lisbon District, PT", 38.7, -9.1)
T0 = 1000.0  # monotonic seconds when the Reading was fetched


def grid(frame):
    """Strip escape codes and return the frame as a list of rows."""
    assert frame.startswith("\033[H"), "frame must start with cursor-home"
    return CSI.sub("", frame).split("\r\n")


def text(frame):
    return "\n".join(line.strip() for line in grid(frame))


QUARTER = 1790000100.0  # a wall-clock quarter-hour boundary (divisible by 900)
NOW0 = weather.Now(QUARTER + 7 * 60, T0)


def at(seconds):
    """NOW0 advanced by seconds on both clocks."""
    return weather.Now(NOW0.wall + seconds, NOW0.mono + seconds)


def resolved_state():
    return weather.resolved(weather.initial_state("lisbon"), LISBON, NOW0)


def reading_state(temperature=12.3, condition="Light rain", unit="C", **fields):
    reading = weather.Reading(temperature, condition, unit, T0, **fields)
    return weather.fetched(resolved_state(), reading, NOW0)


def drawn_box(cells):
    """(width, height) of the bounding box of non-blank cells."""
    points = [(r, c) for r, line in enumerate(cells) for c, ch in enumerate(line) if ch != " "]
    if not points:
        return (0, 0)
    rs = [r for r, _ in points]
    cs = [c for _, c in points]
    return (max(cs) - min(cs) + 1, max(rs) - min(rs) + 1)


def big_rows(frame):
    """The big-digit rows of an ASCII frame, trimmed to their bounding box."""
    rows = [line for line in grid(frame) if "#" in line]
    left = min(len(r) - len(r.lstrip()) for r in rows)
    width = max(len(r.rstrip()) for r in rows) - left
    return [r[left : left + width].ljust(width) for r in rows]


class ReadingFrameTest(unittest.TestCase):
    def test_frame_covers_every_cell_of_the_pane(self):
        states = [reading_state(), weather.initial_state("lisbon"), weather.failed(weather.initial_state("lisbon"), "offline", NOW0)]
        for state in states:
            for cols, rows in [(80, 24), (120, 40), (30, 9), (10, 3), (1, 1)]:
                with self.subTest(state=state, cols=cols, rows=rows):
                    cells = grid(weather.build_frame(state, T0, cols, rows, UNICODE))
                    self.assertEqual([len(line) for line in cells], [cols] * rows)

    def test_shows_condition_with_unit_and_location_under_the_digits(self):
        lines = text(weather.build_frame(reading_state(), T0, 80, 24, UNICODE)).split("\n")
        condition = lines.index("Light rain · °C")
        self.assertEqual(lines[condition + 1], "Lisbon, Lisbon District, PT")
        self.assertTrue(any(set(line) & set("█▀▄") for line in lines[:condition]))

    def test_imperial_unit_on_the_condition_line(self):
        frame = weather.build_frame(reading_state(70.0, "Clear", "F"), T0, 80, 24, UNICODE)
        self.assertIn("Clear · °F", text(frame))

    def test_temperature_in_big_digits_with_a_degree_sign(self):
        frame = weather.build_frame(reading_state(7.0), T0, 80, 24, ASCII)
        self.assertEqual(
            big_rows(frame),
            [
                "#####  ## ",
                "    # #  #",
                "   #  #  #",
                "   #   ## ",
                "  #       ",
                "  #       ",
                " #        ",
                " #        ",
                " #        ",
                " #        ",
            ],
        )

    def test_negative_temperature_has_a_big_minus_sign(self):
        frame = weather.build_frame(reading_state(-7.2), T0, 80, 24, ASCII)
        self.assertEqual(big_rows(frame)[5], "####   #       ")

    def test_temperatures_round_to_whole_degrees_and_never_show_minus_zero(self):
        def digits(t):
            return big_rows(weather.build_frame(reading_state(t), T0, 80, 24, ASCII))

        self.assertEqual(digits(-0.4), digits(0.0))
        self.assertEqual(digits(0.4), digits(0.0))
        self.assertEqual(digits(12.6), digits(13.0))
        self.assertEqual(digits(-12.6), digits(-13.0))
        self.assertNotEqual(digits(-5.0), digits(5.0))

    def test_three_digit_temperatures_are_drawn_whole(self):
        cells = grid(weather.build_frame(reading_state(104.0, "Clear", "F"), T0, 80, 24, ASCII))
        # Three 5-wide digits and a 4-wide degree sign, with 1-cell gaps, less
        # the blank left column of the 1.
        self.assertEqual(len(big_rows("\033[H" + "\r\n".join(cells))[0]), 21)

    def test_no_color_escapes_when_color_is_disabled(self):
        for unicode in (True, False):
            for state in (reading_state(), reading_state(sky=weather.Sky.STORM), reading_state(sky=weather.Sky.CLEAR, is_day=False)):
                caps = weather.Caps(color=False, unicode=unicode)
                with self.subTest(unicode=unicode, sky=state.reading.sky):
                    self.assertIsNone(SGR.search(weather.build_frame(state, T0, 80, 24, caps)))


UNDIM = "\033[22m"
TOKEN = re.compile(r"\033\[[0-9;?]*[A-Za-z]|.")


def styled(frame):
    """The frame as rows of (char, color, dim) cells, with color a 256-color
    index or None for the terminal default."""
    assert frame.startswith("\033[H"), "frame must start with cursor-home"
    rows, color, dim = [], None, False
    for line in frame[len("\033[H") :].split("\r\n"):
        row = []
        for token in TOKEN.findall(line):
            if token == DIM:
                dim = True
            elif token == UNDIM:
                dim = False
            elif token.startswith("\033[38;5;"):
                color = int(token[len("\033[38;5;") : -1])
            elif token == "\033[39m":
                color = None
            elif not token.startswith("\033"):
                row.append((token, color, dim))
        rows.append(row)
    return rows


def icon_colors(state, mono=T0, caps=UNICODE):
    """The colors of the frame's colored cells: those of its icon."""
    return {color for row in styled(weather.build_frame(state, mono, 80, 24, caps)) for ch, color, _ in row if color is not None}


# Each Condition's Sky, from the spec.
EXPECTED_SKIES = {
    **dict.fromkeys((0, 1), weather.Sky.CLEAR),
    **dict.fromkeys((2, 3, 45, 48), weather.Sky.CLOUDY),
    **dict.fromkeys((51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82), weather.Sky.RAIN),
    **dict.fromkeys((71, 73, 75, 77, 85, 86), weather.Sky.SNOW),
    **dict.fromkeys((95, 96, 99), weather.Sky.STORM),
}
SKIES = (weather.Sky.CLEAR, weather.Sky.CLOUDY, weather.Sky.RAIN, weather.Sky.SNOW, weather.Sky.STORM)


class SkyTest(unittest.TestCase):
    def test_every_condition_has_its_sky(self):
        self.assertEqual(set(EXPECTED_SKIES), set(weather.CONDITIONS))
        for code, sky in EXPECTED_SKIES.items():
            with self.subTest(code=code):
                self.assertEqual(weather.forecast_result(forecast_json(code=code), "C", 0.0).sky, sky)

    def test_unknown_code_has_no_sky_and_no_icon(self):
        for code in (-1, 4, 42, 50, 100):
            with self.subTest(code=code):
                self.assertIsNone(weather.forecast_result(forecast_json(code=code), "C", 0.0).sky)
        reading = weather.forecast_result(forecast_json(code=42), "C", T0)
        frame = weather.build_frame(weather.fetched(resolved_state(), reading, NOW0), T0, 80, 24, ASCII)
        self.assertEqual(big_rows(frame), big_rows(weather.build_frame(reading_state(), T0, 80, 24, ASCII)))


class IconTest(unittest.TestCase):
    def icon(self, caps=ASCII, **fields):
        """The icon's rows: the big rows left of the digits."""
        rows = big_rows(weather.build_frame(reading_state(**fields), T0, 80, 24, caps))
        digits = big_rows(weather.build_frame(reading_state(), T0, 80, 24, caps))
        width = len(digits[0])
        self.assertEqual([row[-width:] for row in rows], digits)
        return [row[:-width] for row in rows]

    def test_icon_sits_left_of_the_digits(self):
        for sky in SKIES:
            with self.subTest(sky=sky):
                icon = self.icon(sky=sky)
                self.assertTrue(any("#" in row for row in icon))
                self.assertTrue(all(row.endswith(" ") for row in icon))  # a gap before the digits

    def test_ascii_icons_are_ten_rows_like_the_digits(self):
        for sky in SKIES:
            for is_day in (True, False):
                with self.subTest(sky=sky, is_day=is_day):
                    self.assertEqual(len(self.icon(sky=sky, is_day=is_day)), 10)

    def test_unicode_icons_are_five_rows_like_the_digits(self):
        for sky in SKIES:
            with self.subTest(sky=sky):
                cells = styled(weather.build_frame(reading_state(sky=sky), T0, 80, 24, UNICODE))
                icon_rows = [r for r, row in enumerate(cells) if any(color is not None for _, color, _ in row)]
                self.assertLessEqual(max(icon_rows) - min(icon_rows) + 1, 5)
                digit_rows = [r for r, row in enumerate(cells) if any(ch in "█▀▄" and color is None for ch, color, _ in row)]
                self.assertEqual(len(digit_rows), 5)
                self.assertTrue(set(icon_rows) <= set(digit_rows))

    def test_clear_at_night_is_a_moon_and_no_other_sky_changes(self):
        self.assertNotEqual(self.icon(sky=weather.Sky.CLEAR, is_day=False), self.icon(sky=weather.Sky.CLEAR))
        self.assertNotEqual(icon_colors(reading_state(sky=weather.Sky.CLEAR, is_day=False)), icon_colors(reading_state(sky=weather.Sky.CLEAR)))
        for sky in SKIES[1:]:
            with self.subTest(sky=sky):
                self.assertEqual(self.icon(sky=sky, is_day=False), self.icon(sky=sky))

    def test_icons_are_colored_by_sky_and_the_digits_are_not(self):
        sun = icon_colors(reading_state(sky=weather.Sky.CLEAR))
        self.assertEqual(len(sun), 1)
        self.assertEqual(len(icon_colors(reading_state(sky=weather.Sky.CLOUDY))), 1)
        for sky in (weather.Sky.RAIN, weather.Sky.SNOW, weather.Sky.STORM):
            with self.subTest(sky=sky):
                self.assertEqual(len(icon_colors(reading_state(sky=sky))), 2)  # a cloud and what falls from it
        self.assertTrue(sun < icon_colors(reading_state(sky=weather.Sky.STORM)))  # the bolt is the sun's yellow
        self.assertEqual(icon_colors(reading_state(sky=weather.Sky.RAIN), caps=ASCII), icon_colors(reading_state(sky=weather.Sky.RAIN)))

    def test_a_stale_reading_dims_the_icon(self):
        for mono, dim in ((T0, False), (T0 + 30 * MIN, True)):
            with self.subTest(dim=dim):
                cells = styled(weather.build_frame(reading_state(sky=weather.Sky.STORM), mono, 80, 24, UNICODE))
                self.assertEqual({d for row in cells for ch, color, d in row if color is not None}, {dim})


FULL_FIELDS = dict(sky=weather.Sky.RAIN, feels=9.4, high=14.2, low=6.6, wind_speed=12.2, wind_direction=310.0, rain=40.0)


def full_state(unit="C", **fields):
    """A Reading with a Sky and every detail, with fields overriding them."""
    return reading_state(unit=unit, **{**FULL_FIELDS, **fields})


class DetailLinesTest(unittest.TestCase):
    def details(self, state, caps=UNICODE, mono=T0):
        """The lines between the Condition line and the location line."""
        lines = lines_of(weather.build_frame(state, mono, 80, 24, caps))
        condition = next(i for i, line in enumerate(lines) if line.startswith("Light rain"))
        return lines[condition + 1 : lines.index("Lisbon, Lisbon District, PT")]

    def test_two_detail_lines_at_full_data(self):
        self.assertEqual(self.details(full_state()), ["feels 9° · H 14° L 7°", "wind 12 km/h NW · rain 40%"])

    def test_a_missing_field_drops_only_its_item(self):
        cases = [
            (dict(feels=None), ["H 14° L 7°", "wind 12 km/h NW · rain 40%"]),
            (dict(high=None), ["feels 9° · L 7°", "wind 12 km/h NW · rain 40%"]),
            (dict(low=None), ["feels 9° · H 14°", "wind 12 km/h NW · rain 40%"]),
            (dict(high=None, low=None), ["feels 9°", "wind 12 km/h NW · rain 40%"]),
            (dict(wind_direction=None), ["feels 9° · H 14° L 7°", "wind 12 km/h · rain 40%"]),
            (dict(wind_speed=None), ["feels 9° · H 14° L 7°", "rain 40%"]),
            (dict(rain=None), ["feels 9° · H 14° L 7°", "wind 12 km/h NW"]),
            (dict(feels=None, high=None, low=None), ["wind 12 km/h NW · rain 40%"]),
            (dict(wind_speed=None, rain=None), ["feels 9° · H 14° L 7°"]),
            (dict(feels=None, high=None, low=None, wind_speed=None, rain=None), []),
        ]
        for fields, expected in cases:
            with self.subTest(fields=fields):
                self.assertEqual(self.details(full_state(**fields)), expected)

    def test_temperatures_round_like_the_big_temperature(self):
        state = full_state(feels=-0.4, high=12.5, low=-3.5)
        self.assertEqual(self.details(state)[0], "feels 0° · H 13° L -4°")

    def test_wind_below_1_is_calm_with_no_direction(self):
        for speed, expected in [(0.0, "wind calm"), (0.49, "wind calm"), (0.5, "wind 1 km/h NW"), (1.4, "wind 1 km/h NW")]:
            with self.subTest(speed=speed):
                self.assertEqual(self.details(full_state(wind_speed=speed, rain=None))[1], expected)
        self.assertEqual(self.details(full_state(wind_speed=0.2, wind_direction=None))[1], "wind calm · rain 40%")

    def test_wind_direction_is_an_8_point_compass(self):
        cases = [
            (0, "N"),
            (22.4, "N"),
            (22.5, "NE"),
            (45, "NE"),
            (90, "E"),
            (135, "SE"),
            (180, "S"),
            (225, "SW"),
            (270, "W"),
            (315, "NW"),
            (337.4, "NW"),
            (337.5, "N"),
            (359.9, "N"),
            (360, "N"),
        ]
        for degrees, point in cases:
            with self.subTest(degrees=degrees):
                self.assertEqual(self.details(full_state(wind_direction=degrees, rain=None))[1], f"wind 12 km/h {point}")

    def test_imperial_wind_is_in_mph(self):
        state = full_state("F", feels=48.2, high=57.6, low=44.0, wind_speed=7.6)
        self.assertEqual(self.details(state), ["feels 48° · H 58° L 44°", "wind 8 mph NW · rain 40%"])

    def test_ascii_drops_the_degree_sign_and_uses_a_plain_separator(self):
        self.assertEqual(self.details(full_state(), ASCII), ["feels 9 - H 14 L 7", "wind 12 km/h NW - rain 40%"])

    def test_no_detail_lines_without_a_sky(self):
        lines = lines_of(weather.build_frame(full_state(sky=None), T0, 80, 24, UNICODE))
        self.assertFalse(any(line.startswith(("feels", "wind")) for line in lines))

    def test_a_stale_reading_dims_the_detail_lines(self):
        stale = weather.build_frame(full_state(), T0 + 30 * MIN, 80, 24, UNICODE)
        dimmed = [CSI.sub("", part.split(UNDIM)[0]) for part in stale.split(DIM)[1:]]
        self.assertIn("feels 9° · H 14° L 7°", dimmed)
        self.assertIn("wind 12 km/h NW · rain 40%", dimmed)
        self.assertNotIn(DIM, weather.build_frame(full_state(), T0, 80, 24, UNICODE))


def block_box(cells):
    """(top, left, bottom, right) of the drawn text and icon plus a 1-cell
    margin."""
    points = [(r, c) for r, line in enumerate(cells) for c, ch in enumerate(line) if ch != " "]
    rs = [r for r, _ in points]
    cs = [c for _, c in points]
    return (min(rs) - 1, min(cs) - 1, max(rs) + 1, max(cs) + 1)


class EffectTest(unittest.TestCase):
    # A few seconds apart, and between frames, so the Effect is mid-motion.
    TIMES = [T0 + 0.125 * i for i in range(8)] + [T0 + s for s in range(1, 60, 7)]
    SIZES = [(80, 24), (40, 14), (120, 40), (29, 11), (31, 13)]

    def frame(self, state, mono, cols, rows, caps=UNICODE, seed=1):
        """A frame with the Effect seeded as the app seeds it."""
        effect = weather.showing_effect(state, mono, cols, rows, caps)
        seeded = effect.seed(cols, rows, random.Random(seed)) if effect else None
        return weather.build_frame(state, mono, cols, rows, caps, seeded)

    def drawn(self, state, mono, cols, rows, caps=UNICODE):
        """Whether either Effect, seeded and passed in, changes the frame."""
        plain = weather.build_frame(state, mono, cols, rows, caps)
        for sky in (weather.Sky.RAIN, weather.Sky.SNOW):
            effect = weather.showing_effect(full_state(sky=sky), T0, 80, 24, caps)
            seeded = effect.seed(cols, rows, random.Random(1))
            if weather.build_frame(state, mono, cols, rows, caps, seeded) != plain:
                return True
        return False

    def test_drops_on_rain_and_storm_and_flakes_on_snow(self):
        glyphs = {}
        for sky in (weather.Sky.RAIN, weather.Sky.STORM, weather.Sky.SNOW):
            with self.subTest(sky=sky):
                state = full_state(sky=sky)
                plain = grid(weather.build_frame(state, T0, 80, 24, UNICODE))
                cells = grid(self.frame(state, T0, 80, 24))
                glyphs[sky] = {a for row, base in zip(cells, plain) for a, b in zip(row, base) if a != b}
                self.assertTrue(glyphs[sky])
        self.assertEqual(glyphs[weather.Sky.RAIN], glyphs[weather.Sky.STORM])
        self.assertIn("│", glyphs[weather.Sky.RAIN])
        self.assertNotIn("*", glyphs[weather.Sky.RAIN])
        self.assertIn("*", glyphs[weather.Sky.SNOW])
        self.assertNotIn("│", glyphs[weather.Sky.SNOW])

    def test_the_block_and_its_margin_are_never_drawn_over(self):
        for sky in (weather.Sky.RAIN, weather.Sky.SNOW):
            for caps in (UNICODE, ASCII):
                for state in (full_state(sky=sky), reading_state(sky=sky), full_state(sky=sky, wind_speed=None, rain=None)):
                    for cols, rows in self.SIZES:
                        plain = grid(weather.build_frame(state, T0, cols, rows, caps))
                        top, left, bottom, right = block_box(plain)
                        for mono in self.TIMES:
                            plain = grid(weather.build_frame(state, mono, cols, rows, caps))
                            for seed in range(3):
                                with self.subTest(sky=sky, unicode=caps.unicode, cols=cols, rows=rows, mono=mono, seed=seed):
                                    cells = grid(self.frame(state, mono, cols, rows, caps, seed))
                                    self.assertEqual([len(line) for line in cells], [cols] * rows)
                                    for r in range(max(0, top), min(rows, bottom + 1)):
                                        self.assertEqual(cells[r][left : right + 1], plain[r][left : right + 1])

    def test_the_effect_moves(self):
        state = full_state(sky=weather.Sky.SNOW)
        self.assertNotEqual(self.frame(state, T0, 80, 24), self.frame(state, T0 + 1, 80, 24))

    def test_no_effect_on_clear_cloudy_or_an_unknown_code(self):
        for sky in (weather.Sky.CLEAR, weather.Sky.CLOUDY, None):
            for is_day in (True, False):
                with self.subTest(sky=sky, is_day=is_day):
                    state = full_state(sky=sky, is_day=is_day)
                    self.assertIsNone(weather.showing_effect(state, T0, 80, 24, UNICODE))
                    self.assertFalse(self.drawn(state, T0, 80, 24))

    def test_no_effect_once_the_reading_is_stale(self):
        state = full_state()
        self.assertIsNotNone(weather.showing_effect(state, T0 + 30 * MIN - 1, 80, 24, UNICODE))
        for mono in (T0 + 30 * MIN, T0 + 2 * HOUR, T0 + 3 * HOUR):
            with self.subTest(mono=mono):
                self.assertIsNone(weather.showing_effect(state, mono, 80, 24, UNICODE))
                self.assertFalse(self.drawn(state, mono, 80, 24))

    def test_no_effect_without_a_reading(self):
        for state in (weather.initial_state("lisbon"), weather.failed(resolved_state(), "offline", NOW0)):
            with self.subTest(state=state):
                self.assertIsNone(weather.showing_effect(state, T0, 80, 24, UNICODE))
                self.assertFalse(self.drawn(state, T0, 80, 24))

    def test_effect_only_in_the_icon_tiers(self):
        # full needs 29x11, big with icon 29x9, big 27x9.
        state = full_state()
        for cols, rows, shows in [(29, 11, True), (29, 9, True), (28, 11, False), (29, 8, False), (20, 2, False), (4, 1, False)]:
            with self.subTest(cols=cols, rows=rows):
                self.assertEqual(weather.showing_effect(state, T0, cols, rows, UNICODE) is not None, shows)
                if not shows:
                    self.assertFalse(self.drawn(state, T0, cols, rows))

    def test_uncolored_but_still_drawn_without_color(self):
        caps = weather.Caps(color=False, unicode=True)
        for sky in (weather.Sky.RAIN, weather.Sky.SNOW):
            with self.subTest(sky=sky):
                frame = self.frame(full_state(sky=sky), T0, 80, 24, caps)
                self.assertIsNone(SGR.search(frame))
                self.assertNotEqual(frame, weather.build_frame(full_state(sky=sky), T0, 80, 24, caps))

    def test_ascii_glyphs_without_unicode(self):
        for sky in (weather.Sky.RAIN, weather.Sky.SNOW):
            for mono in self.TIMES:
                with self.subTest(sky=sky, mono=mono):
                    frame = self.frame(full_state(sky=sky), mono, 80, 24, ASCII)
                    self.assertTrue(frame.isascii())
                    self.assertNotEqual(frame, weather.build_frame(full_state(sky=sky), mono, 80, 24, ASCII))


class FrameRateTest(unittest.TestCase):
    def test_8_while_an_effect_shows_else_1(self):
        cases = [
            (full_state(), T0, 80, 24, 8),
            (full_state(sky=weather.Sky.STORM), T0, 80, 24, 8),
            (reading_state(sky=weather.Sky.SNOW), T0, 29, 9, 8),
            (full_state(), T0 + 30 * MIN, 80, 24, 1),
            (full_state(), T0 + 3 * HOUR, 80, 24, 1),
            (full_state(), T0, 28, 24, 1),
            (full_state(), T0, 20, 2, 1),
            (full_state(sky=weather.Sky.CLEAR), T0, 80, 24, 1),
            (full_state(sky=weather.Sky.CLOUDY), T0, 80, 24, 1),
            (full_state(sky=None), T0, 80, 24, 1),
            (weather.initial_state("lisbon"), T0, 80, 24, 1),
        ]
        for state, mono, cols, rows, fps in cases:
            with self.subTest(sky=state.reading and state.reading.sky, mono=mono, cols=cols, rows=rows):
                self.assertEqual(weather.frame_rate(state, mono, cols, rows, UNICODE), fps)
        self.assertEqual(weather.frame_rate(full_state(), T0, 80, 24, weather.Caps(color=False, unicode=False)), 8)


class FrameTimingTest(unittest.TestCase):
    EPOCH = 1790000000.0  # a whole second

    def test_boundary_is_in_the_future_and_within_one_period(self):
        for fps in (1, 8):
            period = 1 / fps
            for offset in (0.0, 1e-9, 0.1, 0.125, 0.4999, 0.5, 0.75, 0.999999):
                now = self.EPOCH + offset
                with self.subTest(fps=fps, now=now):
                    boundary = weather.next_boundary(now, fps)
                    self.assertGreater(boundary, now)
                    self.assertLessEqual(boundary - now, period + 1e-9)

    def test_boundaries_fall_on_every_whole_second(self):
        for fps in (1, 8):
            with self.subTest(fps=fps):
                t = self.EPOCH - 0.001
                seen = []
                while t < self.EPOCH + 3:
                    t = weather.next_boundary(t, fps)
                    seen.append(t)
                for second in (1, 2, 3):
                    self.assertIn(self.EPOCH + second, seen)
                self.assertEqual(len(seen), 3 * fps + 1)


class NoReadingFrameTest(unittest.TestCase):
    def test_before_the_first_reading_shows_the_typed_name_fetching(self):
        frame = weather.build_frame(weather.initial_state("lisbon"), T0, 80, 24, UNICODE)
        self.assertIn("lisbon · fetching…", text(frame))

    def test_failed_fetch_shows_the_label_and_the_cause(self):
        state = weather.failed(resolved_state(), "HTTP 503", NOW0)
        self.assertIn("Lisbon, Lisbon District, PT · HTTP 503", text(weather.build_frame(state, T0, 80, 24, UNICODE)))

    def test_failed_fetch_counts_down_to_the_retry(self):
        state = weather.failed(weather.initial_state("springfield"), "offline", NOW0)  # retry in 60s
        for elapsed, countdown in [(0, "retry in 1m"), (59.5, "retry in 1m"), (60, "retrying…"), (200, "retrying…")]:
            with self.subTest(elapsed=elapsed):
                frame = weather.build_frame(state, T0 + elapsed, 80, 24, UNICODE)
                self.assertIn(f"springfield · offline · {countdown}", text(frame))
        state = weather.failed(state, "offline", NOW0)  # retry in 120s
        self.assertIn("offline · retry in 2m", text(weather.build_frame(state, T0, 80, 24, UNICODE)))
        self.assertIn("offline · retry in 2m", text(weather.build_frame(state, T0 + 59, 80, 24, UNICODE)))
        self.assertIn("offline · retry in 1m", text(weather.build_frame(state, T0 + 60, 80, 24, UNICODE)))

    def test_typed_label_until_geocoding_resolves_then_the_resolved_name(self):
        state = weather.failed(weather.initial_state("lisbon"), "timeout", NOW0)
        self.assertIn("lisbon · timeout", text(weather.build_frame(state, T0, 80, 24, UNICODE)))
        state = weather.resolved(state, LISBON, at(60))
        frame = text(weather.build_frame(state, T0 + 60, 80, 24, UNICODE))
        self.assertIn("Lisbon, Lisbon District, PT · fetching…", frame)
        self.assertNotIn("lisbon", frame)


class AgeLineTest(unittest.TestCase):
    def age_line(self, state, elapsed):
        lines = text(weather.build_frame(state, T0 + elapsed, 80, 24, UNICODE)).split("\n")
        return lines[lines.index("Lisbon, Lisbon District, PT") + 1]

    def test_age_counts_minutes_since_the_reading_was_fetched(self):
        cases = [
            (0, "updated just now"),
            (59, "updated just now"),
            (60, "updated 1m ago"),
            (4 * 60 + 30, "updated 4m ago"),
            (59 * 60 + 59, "updated 59m ago"),
            (60 * 60, "updated 1h 0m ago"),
            (125 * 60, "updated 2h 5m ago"),
        ]
        for elapsed, line in cases:
            with self.subTest(elapsed=elapsed):
                self.assertEqual(self.age_line(reading_state(), elapsed), line)

    def test_a_failed_fetch_keeps_the_reading_and_notes_the_cause(self):
        state = weather.failed(reading_state(), "offline", at(20 * 60))
        self.assertEqual(self.age_line(state, 20 * 60), "updated 20m ago · offline")
        self.assertIn("Light rain · °C", text(weather.build_frame(state, T0 + 20 * 60, 80, 24, UNICODE)))

    def test_success_after_failure_clears_the_cause(self):
        state = weather.failed(reading_state(), "offline", at(15 * 60))
        state = weather.fetched(state, weather.Reading(9.0, "Clear", "C", T0 + 16 * 60), at(16 * 60))
        self.assertEqual(self.age_line(state, 17 * 60), "updated 1m ago")


def lines_of(frame):
    """The frame's non-blank lines, stripped."""
    return [line.strip() for line in grid(frame) if line.strip()]


class SizeTierTest(unittest.TestCase):
    # For reading_state() at T0: the label is 27 wide, the big digits "12°"
    # 16 wide and 5 rows (10 in ASCII), so big needs 27x9 (27x14 in ASCII).
    COMPACT_AGE = ["12°C Light rain", "updated just now"]
    COMPACT = ["12°C Light rain"]
    MINIMAL = ["12°C"]

    def tier(self, state, cols, rows, caps=UNICODE, mono=T0):
        return lines_of(weather.build_frame(state, mono, cols, rows, caps))

    def big(self, caps):
        return self.tier(reading_state(), 80, 24, caps)

    def test_big_tier_is_digits_condition_location_and_age(self):
        lines = self.big(UNICODE)
        self.assertEqual(len(lines), 8)  # 5 digit rows, then 3 text lines; the blank row is stripped
        self.assertEqual(lines[5:], ["Light rain · °C", "Lisbon, Lisbon District, PT", "updated just now"])

    def test_reading_tiers_at_exact_thresholds(self):
        cases = [
            (27, 9, "big"),
            (26, 9, self.COMPACT_AGE),
            (27, 8, self.COMPACT_AGE),
            (16, 2, self.COMPACT_AGE),
            (15, 2, self.COMPACT),
            (16, 1, self.COMPACT),
            (15, 1, self.COMPACT),
            (14, 5, self.MINIMAL),
            (4, 1, self.MINIMAL),
            (3, 1, []),
            (3, 20, []),
        ]
        for cols, rows, expected in cases:
            with self.subTest(cols=cols, rows=rows):
                self.assertEqual(self.tier(reading_state(), cols, rows), self.big(UNICODE) if expected == "big" else expected)

    def test_big_with_icon_tier_at_exact_thresholds(self):
        # The rain icon is 11 wide, then a 2-cell gap, then the 16-wide digits.
        state = reading_state(sky=weather.Sky.RAIN)
        big_with_icon = self.tier(state, 80, 24)
        self.assertEqual(len(big_with_icon), 8)
        self.assertEqual(big_with_icon[5:], ["Light rain · °C", "Lisbon, Lisbon District, PT", "updated just now"])
        for caps, rows in ((UNICODE, 9), (ASCII, 14)):
            cases = [
                (29, rows, self.tier(state, 80, 24, caps)),
                (28, rows, self.tier(reading_state(), 80, 24, caps)),
                (29, rows - 1, self.tier(reading_state(), 29, rows - 1, caps)),
            ]
            for cols, r, expected in cases:
                with self.subTest(unicode=caps.unicode, cols=cols, rows=r):
                    self.assertEqual(self.tier(state, cols, r, caps), expected)
        self.assertEqual(self.tier(state, 29, 8), self.COMPACT_AGE)

    def test_full_tier_at_exact_thresholds(self):
        # Two detail lines under the big-with-icon tier: 29 wide, 11 rows.
        state = full_state()
        full = self.tier(state, 80, 24)
        self.assertEqual(
            full[5:],
            ["Light rain · °C", "feels 9° · H 14° L 7°", "wind 12 km/h NW · rain 40%", "Lisbon, Lisbon District, PT", "updated just now"],
        )
        for caps, rows in ((UNICODE, 11), (ASCII, 16)):
            big_with_icon = self.tier(reading_state(sky=weather.Sky.RAIN), 80, 24, caps)
            cases = [
                (29, rows, self.tier(state, 80, 24, caps)),
                (29, rows - 1, big_with_icon),
                (29, rows - 2, big_with_icon),
                (28, rows, self.tier(reading_state(), 80, 24, caps)),
            ]
            for cols, r, expected in cases:
                with self.subTest(unicode=caps.unicode, cols=cols, rows=r):
                    self.assertEqual(self.tier(state, cols, r, caps), expected)

    def test_one_detail_line_needs_one_row_more_than_big_with_icon(self):
        state = full_state(wind_speed=None, rain=None)
        self.assertIn("feels 9° · H 14° L 7°", self.tier(state, 29, 10))
        self.assertNotIn("feels 9° · H 14° L 7°", self.tier(state, 29, 9))

    def test_ascii_reading_tiers_at_exact_thresholds(self):
        cases = [
            (27, 14, "big"),
            (27, 13, ["12C Light rain", "updated just now"]),
            (14, 1, ["12C Light rain"]),
            (13, 1, ["12C"]),
            (3, 1, ["12C"]),
            (2, 1, []),
        ]
        for cols, rows, expected in cases:
            with self.subTest(cols=cols, rows=rows):
                self.assertEqual(self.tier(reading_state(), cols, rows, ASCII), self.big(ASCII) if expected == "big" else expected)

    def test_failure_text_shrinks_with_the_pane(self):
        state = weather.failed(weather.initial_state("springfield"), "offline", NOW0)
        full = "springfield · offline · retry in 1m"  # 35 wide
        for cols, expected in [(35, [full]), (34, ["offline"]), (7, ["offline"]), (6, ["!"]), (1, ["!"])]:
            with self.subTest(cols=cols):
                self.assertEqual(self.tier(state, cols, 1), expected)
        self.assertEqual(self.tier(state, 0, 1), [])
        http = weather.failed(weather.initial_state("x"), "HTTP 503", NOW0)
        self.assertEqual(self.tier(http, 8, 1), ["HTTP 503"])
        self.assertEqual(self.tier(http, 7, 1), ["!"])

    def test_fetching_text_shrinks_with_the_pane(self):
        state = weather.initial_state("springfield")
        for cols, expected in [(23, ["springfield · fetching…"]), (22, ["fetching…"]), (9, ["fetching…"]), (8, [])]:
            with self.subTest(cols=cols):
                self.assertEqual(self.tier(state, cols, 3), expected)

    def test_reading_with_a_failure_keeps_the_cause_on_the_age_line(self):
        state = weather.failed(reading_state(), "offline", at(20 * 60))
        self.assertEqual(
            self.tier(state, 30, 3, mono=T0 + 20 * 60),
            ["12°C Light rain", "updated 20m ago · offline"],
        )

    def test_stale_reading_is_dimmed_in_every_tier(self):
        stale = T0 + 45 * 60
        for cols, rows in [(80, 24), (20, 2), (15, 1), (4, 1)]:
            with self.subTest(cols=cols, rows=rows):
                self.assertIn(DIM, weather.build_frame(reading_state(), stale, cols, rows, UNICODE))

    def states(self):
        """(state, time, how many distinct layouts it has, blank included)."""
        return [
            (reading_state(), T0, 5),
            (reading_state(sky=weather.Sky.RAIN), T0, 6),
            (full_state(), T0, 7),
            (full_state("F", sky=weather.Sky.SNOW, wind_speed=0.1), T0 + 45 * 60, 7),
            (reading_state(-104.0, "Thunderstorm, hail", "F", sky=weather.Sky.STORM), T0 + 45 * 60, 6),
            (reading_state(-104.0, "Thunderstorm, hail", "F"), T0 + 45 * 60, 5),
            (weather.failed(reading_state(), "bad response", at(20 * 60)), T0 + 20 * 60, 5),
            (weather.initial_state("springfield"), T0, 3),
            # "!" fits any pane at least 1x1, so blank never shows here.
            (weather.failed(weather.initial_state("springfield"), "HTTP 503", NOW0), T0, 3),
        ]

    def test_frames_cover_every_cell_and_never_clip(self):
        for caps in (UNICODE, ASCII):
            for state, mono, count in self.states():
                seen = set()
                for cols in range(1, 60):
                    for rows in range(1, 19):
                        frame = weather.build_frame(state, mono, cols, rows, caps)
                        with self.subTest(unicode=caps.unicode, state=state.label, cols=cols, rows=rows):
                            self.assertEqual([len(line) for line in grid(frame)], [cols] * rows)
                        seen.add(tuple(lines_of(frame)))
                # A clipped layout would show up as an extra distinct layout.
                with self.subTest(unicode=caps.unicode, state=state.label):
                    self.assertEqual(len(seen), count, seen)

    def test_non_ascii_place_names_are_transliterated_in_ascii_frames(self):
        state = weather.initial_state("São Paulo")
        self.assertIn("Sao Paulo - fetching...", text(weather.build_frame(state, T0, 80, 24, ASCII)))
        zurich = weather.resolved(weather.initial_state("zurich"), weather.Place("Zürich, Zürich, CH", 47.4, 8.5), NOW0)
        zurich = weather.fetched(zurich, weather.Reading(9.0, "Fog", "C", T0), NOW0)
        frame = weather.build_frame(zurich, T0, 80, 24, ASCII)
        self.assertTrue(frame.isascii())
        self.assertIn("Zurich, Zurich, CH", text(frame))
        self.assertIn("Zürich, Zürich, CH", text(weather.build_frame(zurich, T0, 80, 24, UNICODE)))

    def test_ascii_frames_are_pure_ascii(self):
        for state, mono, _ in self.states():
            for cols, rows in [(80, 24), (30, 14), (20, 2), (15, 1), (4, 1), (1, 1)]:
                with self.subTest(state=state.label, cols=cols, rows=rows):
                    self.assertTrue(weather.build_frame(state, mono, cols, rows, ASCII).isascii())


MIN, HOUR = 60, 3600
DIM = "\033[2m"


class FreshnessTest(unittest.TestCase):
    def test_fresh_under_30_minutes_stale_until_3_hours_then_expired(self):
        reading = weather.Reading(1.0, "Clear", "C", T0)
        cases = [
            (0, weather.FRESH),
            (30 * MIN - 0.001, weather.FRESH),
            (30 * MIN, weather.STALE),
            (3 * HOUR - 0.001, weather.STALE),
            (3 * HOUR, weather.EXPIRED),
        ]
        for age, freshness in cases:
            with self.subTest(age=age):
                self.assertIs(weather.freshness(reading, T0 + age), freshness)

    def test_stale_reading_is_dimmed_when_color_is_on(self):
        self.assertNotIn(DIM, weather.build_frame(reading_state(), T0 + 30 * MIN - 1, 80, 24, UNICODE))
        stale = weather.build_frame(reading_state(), T0 + 30 * MIN, 80, 24, UNICODE)
        dimmed = [CSI.sub("", part.split("\033[22m")[0]) for part in stale.split(DIM)[1:]]
        self.assertIn("Light rain · °C", dimmed)
        self.assertTrue(any(set(part) & set("█▀▄") for part in dimmed))
        self.assertNotIn("Lisbon, Lisbon District, PT", dimmed)

    def test_stale_reading_is_not_styled_under_no_color(self):
        caps = weather.Caps(color=False, unicode=True)
        frame = weather.build_frame(reading_state(), T0 + 45 * MIN, 80, 24, caps)
        self.assertIsNone(SGR.search(frame))
        self.assertIn("updated 45m ago", text(frame))

    def test_expired_reading_is_dropped_for_the_no_reading_layout(self):
        state = weather.failed(reading_state(), "offline", at(2 * HOUR + 59.5 * MIN))  # retry 30s after expiry
        now = T0 + 3 * HOUR
        dropped = weather.expire(state, now)
        self.assertIsNone(dropped.reading)
        self.assertIs(weather.expire(state, now - 1), state)
        no_reading = weather.failed(resolved_state(), "offline", at(2 * HOUR + 59.5 * MIN))
        self.assertEqual(weather.build_frame(dropped, now, 80, 24, UNICODE), weather.build_frame(no_reading, now, 80, 24, UNICODE))
        self.assertEqual(weather.build_frame(state, now, 80, 24, UNICODE), weather.build_frame(no_reading, now, 80, 24, UNICODE))
        self.assertIn("Lisbon, Lisbon District, PT · offline · retry in 1m", text(weather.build_frame(dropped, now, 80, 24, UNICODE)))

    def test_success_after_expiry_shows_a_fresh_reading(self):
        state = weather.expire(weather.failed(reading_state(), "offline", at(3 * HOUR)), T0 + 3 * HOUR)
        state = weather.fetched(state, weather.Reading(5.0, "Fog", "C", T0 + 4 * HOUR), at(4 * HOUR))
        frame = weather.build_frame(state, T0 + 4 * HOUR, 80, 24, UNICODE)
        self.assertNotIn(DIM, frame)
        self.assertIn("Fog · °C", text(frame))
        self.assertIn("updated just now", text(frame))


class ScheduleTest(unittest.TestCase):
    def test_after_success_the_next_fetch_is_the_next_quarter_hour(self):
        reading = weather.Reading(1.0, "Clear", "C", T0)
        for offset, wait in [(0, 900), (0.001, 899.999), (7 * 60, 8 * 60), (899.5, 0.5), (900, 900)]:
            with self.subTest(offset=offset):
                now = weather.Now(QUARTER + offset, T0)
                state = weather.fetched(resolved_state(), reading, now)
                self.assertAlmostEqual(state.next_fetch, T0 + wait, places=6)

    def test_failures_back_off_1_2_4_8_then_15_minutes(self):
        state = resolved_state()
        delays = []
        for i in range(7):
            now = at(i * 1000)
            state = weather.failed(state, "offline", now)
            delays.append(state.next_fetch - now.mono)
        self.assertEqual(delays, [60, 120, 240, 480, 900, 900, 900])

    def test_success_resets_the_backoff(self):
        state = weather.failed(weather.failed(resolved_state(), "offline", NOW0), "offline", NOW0)
        state = weather.fetched(state, weather.Reading(1.0, "Clear", "C", T0), NOW0)
        state = weather.failed(state, "timeout", NOW0)
        self.assertEqual(state.next_fetch - T0, 60)

    def test_geocoding_failures_back_off_the_same_way(self):
        state = weather.initial_state("lisbon")
        self.assertTrue(weather.is_due(state, T0))
        delays = []
        for _ in range(3):
            state = weather.failed(state, "offline", NOW0)
            delays.append(state.next_fetch - T0)
        self.assertEqual(delays, [60, 120, 240])

    def test_resolving_the_place_makes_a_fetch_due_at_once_and_resets_the_backoff(self):
        state = weather.failed(weather.failed(weather.initial_state("lisbon"), "offline", NOW0), "offline", NOW0)
        state = weather.resolved(state, LISBON, at(300))
        self.assertTrue(weather.is_due(state, T0 + 300))
        self.assertEqual(weather.failed(state, "HTTP 500", at(300)).next_fetch - (T0 + 300), 60)

    def test_a_fetch_is_due_only_once_its_time_arrives(self):
        state = weather.failed(resolved_state(), "offline", NOW0)
        self.assertFalse(weather.is_due(state, T0 + 59.9))
        self.assertTrue(weather.is_due(state, T0 + 60))


class FakeHttp:
    """Stands in for http_get: answers geocoding and forecast URLs with
    canned outcomes, and remembers the URLs it was asked for."""

    def __init__(self, geocode=LISBON_JSON, forecast=None):
        self.geocode = geocode
        self.forecast = forecast if forecast is not None else forecast_json()
        self.urls = []

    def __call__(self, url):
        self.urls.append(url)
        return self.geocode if "geocoding" in url else self.forecast


class PlainOutputTest(unittest.TestCase):
    def run_plain(self, http, argv=("Lisbon",), unicode=True):
        out, err = StringIO(), StringIO()
        with redirect_stderr(err):
            code = weather.run_plain(weather.parse_args(list(argv)), http, unicode, out)
        return code, out.getvalue(), err.getvalue()

    def test_success_prints_one_plain_line_and_exits_0(self):
        code, out, err = self.run_plain(FakeHttp())
        self.assertEqual((code, out, err), (0, "Lisbon, Lisbon District, PT 12°C Light rain\n", ""))
        self.assertNotIn("\033", out)

    def test_imperial_units(self):
        http = FakeHttp(forecast=forecast_json(70.4, 0, "°F"))
        code, out, _ = self.run_plain(http, ["Lisbon", "--units", "imperial"])
        self.assertEqual((code, out), (0, "Lisbon, Lisbon District, PT 70°F Clear\n"))
        self.assertIn("temperature_unit=fahrenheit", http.urls[-1])
        self.assertIn("wind_speed_unit=mph", http.urls[-1])

    def test_forecast_asks_for_todays_forecast_in_local_time_and_the_wind_unit(self):
        http = FakeHttp()
        self.run_plain(http)
        query = urllib.parse.parse_qs(urllib.parse.urlparse(http.urls[-1]).query)
        self.assertEqual(query["timezone"], ["auto"])
        self.assertEqual(query["forecast_days"], ["1"])
        self.assertEqual(query["wind_speed_unit"], ["kmh"])
        self.assertEqual(
            set(query["current"][0].split(",")),
            {"temperature_2m", "weather_code", "apparent_temperature", "wind_speed_10m", "wind_direction_10m", "is_day"},
        )
        self.assertEqual(
            set(query["daily"][0].split(",")),
            {"temperature_2m_max", "temperature_2m_min", "precipitation_probability_max"},
        )

    def test_the_line_is_unchanged_by_the_new_fields(self):
        for forecast in (forecast_json(), full_forecast_json()):
            with self.subTest(forecast=forecast):
                _, out, _ = self.run_plain(FakeHttp(forecast=forecast))
                self.assertEqual(out, "Lisbon, Lisbon District, PT 12°C Light rain\n")

    def test_ascii_line_drops_the_degree_sign(self):
        _, out, _ = self.run_plain(FakeHttp(), unicode=False)
        self.assertEqual(out, "Lisbon, Lisbon District, PT 12C Light rain\n")

    def test_ascii_line_transliterates_the_place_name(self):
        body = json.dumps({"results": [{"name": "São Paulo", "admin1": "São Paulo", "country_code": "BR", "latitude": -23.5, "longitude": -46.6}]})
        _, out, _ = self.run_plain(FakeHttp(geocode=body.encode()), ["Sao", "Paulo"], unicode=False)
        self.assertEqual(out, "Sao Paulo, Sao Paulo, BR 12C Light rain\n")

    def test_failures_exit_1_with_the_cause_on_stderr(self):
        cases = [
            (FakeHttp(geocode=urllib.error.URLError(socket.gaierror(-3, "x"))), "offline"),
            (FakeHttp(forecast=urllib.error.HTTPError("u", 503, "x", {}, None)), "HTTP 503"),
            (FakeHttp(forecast=b"nope"), "bad response"),
        ]
        for http, cause in cases:
            with self.subTest(cause=cause):
                code, out, err = self.run_plain(http)
                self.assertEqual((code, out), (1, ""))
                self.assertIn(cause, err)

    def test_no_match_exits_2_with_a_usage_error(self):
        err = StringIO()
        with redirect_stderr(err), self.assertRaises(SystemExit) as exit:
            weather.run_plain(weather.parse_args(["Nowhere"]), FakeHttp(geocode=NO_MATCH_JSON), True, StringIO())
        self.assertEqual(exit.exception.code, 2)
        self.assertIn("usage:", err.getvalue())
        self.assertIn("Nowhere", err.getvalue())


class ArgumentParsingTest(unittest.TestCase):
    def parse_error(self, argv):
        err = StringIO()
        with redirect_stderr(err), self.assertRaises(SystemExit) as exit:
            weather.parse_args(argv)
        self.assertEqual(exit.exception.code, 2)
        return err.getvalue()

    def test_place_name_and_default_metric_units(self):
        self.assertEqual(weather.parse_args(["Lisbon"]), weather.Args("Lisbon", "metric"))

    def test_multi_word_place_name(self):
        self.assertEqual(weather.parse_args(["New", "York"]).place, "New York")
        self.assertEqual(weather.parse_args(["New York", "--units", "imperial"]), weather.Args("New York", "imperial"))

    def test_missing_place_name_exits_with_usage(self):
        self.assertIn("usage:", self.parse_error([]))

    def test_unknown_units_exits_listing_valid_values(self):
        err = self.parse_error(["Lisbon", "--units", "kelvin"])
        self.assertIn("metric", err)
        self.assertIn("imperial", err)

    def test_help_describes_the_place_and_units(self):
        out = StringIO()
        with redirect_stdout(out), self.assertRaises(SystemExit) as exit:
            weather.parse_args(["--help"])
        self.assertEqual(exit.exception.code, 0)
        for word in ("place", "--units", "metric", "imperial"):
            self.assertIn(word, out.getvalue())


if __name__ == "__main__":
    unittest.main()
