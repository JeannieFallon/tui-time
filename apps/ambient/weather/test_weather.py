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


QUARTER = 1790000100.0  # a wall-clock quarter-hour boundary (divisible by 900)
NOW0 = weather.Now(QUARTER + 7 * 60, T0)


def at(seconds):
    """NOW0 advanced by seconds on both clocks."""
    return weather.Now(NOW0.wall + seconds, NOW0.mono + seconds)


def resolved_state():
    return weather.resolved(weather.initial_state("lisbon"), LISBON, NOW0)


def reading_state(temperature=12.3, condition="Light rain", unit="C"):
    return weather.fetched(resolved_state(), weather.Reading(temperature, condition, unit, T0), NOW0)


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
            caps = weather.Caps(color=False, unicode=unicode)
            with self.subTest(unicode=unicode):
                self.assertIsNone(SGR.search(weather.build_frame(reading_state(), T0, 80, 24, caps)))


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
                    for rows in range(1, 16):
                        frame = weather.build_frame(state, mono, cols, rows, caps)
                        with self.subTest(unicode=caps.unicode, state=state.label, cols=cols, rows=rows):
                            self.assertEqual([len(line) for line in grid(frame)], [cols] * rows)
                        seen.add(tuple(lines_of(frame)))
                # A clipped layout would show up as an extra distinct layout.
                with self.subTest(unicode=caps.unicode, state=state.label):
                    self.assertEqual(len(seen), count, seen)

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
