"""Tests for weather.py. Run: python3 -m unittest apps/ambient/weather/test_weather.py"""

import http.client
import json
import os
import re
import socket
import sys
import unittest
import urllib.error
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


def forecast_json(temperature=12.3, code=61, unit="°C"):
    return json.dumps(
        {
            "latitude": 38.75,
            "longitude": -9.125,
            "current_units": {"time": "iso8601", "interval": "seconds", "temperature_2m": unit, "weather_code": "wmo code"},
            "current": {"time": "2026-09-29T21:30", "interval": 900, "temperature_2m": temperature, "weather_code": code},
        }
    ).encode()


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
        self.assertEqual(reading, weather.Reading(12.3, "Light rain", "C", 500.0))

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


def reading_state(temperature=12.3, condition="Light rain", unit="C"):
    state = weather.resolved(weather.initial_state("lisbon"), LISBON)
    return weather.fetched(state, weather.Reading(temperature, condition, unit, T0))


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
        states = [reading_state(), weather.initial_state("lisbon"), weather.failed(weather.initial_state("lisbon"), "offline")]
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
            caps = weather.Caps(color=False, unicode=unicode)
            with self.subTest(unicode=unicode):
                self.assertIsNone(SGR.search(weather.build_frame(reading_state(), T0, 80, 24, caps)))


class NoReadingFrameTest(unittest.TestCase):
    def test_before_the_first_reading_shows_the_typed_name_fetching(self):
        frame = weather.build_frame(weather.initial_state("lisbon"), T0, 80, 24, UNICODE)
        self.assertIn("lisbon · fetching…", text(frame))

    def test_failed_fetch_shows_the_label_and_the_cause(self):
        state = weather.failed(weather.resolved(weather.initial_state("lisbon"), LISBON), "HTTP 503")
        self.assertIn("Lisbon, Lisbon District, PT · HTTP 503", text(weather.build_frame(state, T0, 80, 24, UNICODE)))


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
