#!/usr/bin/env python3
"""Run weather.py's pane with a fake network that reports a chosen Sky.

Run: python3 apps/ambient/weather/simulate.py <sky> [options]
See the README's Simulating section for the options.
"""

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import weather  # noqa: E402

# A weather code for each Sky.
CODES = {"clear": 0, "cloudy": 3, "rain": 63, "snow": 73, "storm": 95}


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Run the weather pane with a fake network that reports a chosen Sky.",
    )
    parser.add_argument("sky", choices=list(CODES))
    parser.add_argument("--night", action="store_true", help="report night (Clear draws a moon)")
    parser.add_argument(
        "--stale-after",
        type=float,
        default=weather.STALE_AFTER,
        help="seconds until the Reading goes Stale (default: %(default)s)",
    )
    parser.add_argument(
        "--fetch-every",
        type=float,
        default=weather.FETCH_INTERVAL,
        help="Fetch interval in seconds (default: %(default)s)",
    )
    parser.add_argument("--delay", type=float, default=0.0, help="seconds each fetch blocks (default: %(default)s)")
    parser.add_argument("--units", choices=list(weather.UNITS), default="metric")
    return parser.parse_args(argv)


def fake_get(opts):
    """A stand-in for weather.http_get that answers with fixed values."""

    def get(url):
        if "geocoding" in url:
            place = {"name": "Simulated", "latitude": 0, "longitude": 0, "country_code": "XX"}
            return json.dumps({"results": [place]}).encode()
        time.sleep(opts.delay)
        current = {
            "temperature_2m": 4.2,
            "weather_code": CODES[opts.sky],
            "apparent_temperature": 1.1,
            "wind_speed_10m": 14.0,
            "wind_direction_10m": 250,
            "is_day": 0 if opts.night else 1,
        }
        daily = {"temperature_2m_max": [6.0], "temperature_2m_min": [0.4], "precipitation_probability_max": [85]}
        return json.dumps({"current": current, "daily": daily}).encode()

    return get


def main():
    opts = parse_args(sys.argv[1:])
    weather.http_get = fake_get(opts)
    weather.STALE_AFTER = opts.stale_after
    weather.FETCH_INTERVAL = opts.fetch_every
    sys.argv = [sys.argv[0], "Simulated", "--units", opts.units]
    weather.main()


if __name__ == "__main__":
    main()
