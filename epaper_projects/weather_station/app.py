#!/usr/bin/env python3
"""Live Munich weather screen using Open-Meteo."""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
from common.epaper_display import Canvas, ellipsize, paint  # noqa: E402

CONFIG_PATH = Path(__file__).with_name("config.json")

WEATHER_CODES = {
    0: "CLEAR",
    1: "MOSTLY CLEAR",
    2: "PARTLY CLOUDY",
    3: "OVERCAST",
    45: "FOG",
    48: "RIME FOG",
    51: "LIGHT DRIZZLE",
    53: "DRIZZLE",
    55: "HEAVY DRIZZLE",
    56: "FREEZING DRIZZLE",
    57: "FREEZING DRIZZLE",
    61: "LIGHT RAIN",
    63: "RAIN",
    65: "HEAVY RAIN",
    66: "FREEZING RAIN",
    67: "FREEZING RAIN",
    71: "LIGHT SNOW",
    73: "SNOW",
    75: "HEAVY SNOW",
    77: "SNOW GRAINS",
    80: "RAIN SHOWERS",
    81: "RAIN SHOWERS",
    82: "HEAVY SHOWERS",
    85: "SNOW SHOWERS",
    86: "HEAVY SNOW",
    95: "THUNDERSTORM",
    96: "STORM + HAIL",
    99: "STORM + HAIL",
}

DEFAULT_CONFIG = {
    "location": "MUNICH",
    "latitude": 48.1374,
    "longitude": 11.5755,
    "timezone": "Europe/Berlin",
    "refresh_seconds": 60,
}


def load_config() -> dict:
    config = DEFAULT_CONFIG.copy()
    if CONFIG_PATH.exists():
        config.update(json.loads(CONFIG_PATH.read_text()))
    return config


def fetch_weather(config: dict) -> dict:
    query = urllib.parse.urlencode(
        {
            "latitude": config["latitude"],
            "longitude": config["longitude"],
            "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,sunrise,sunset",
            "timezone": config["timezone"],
            "forecast_days": 2,
        }
    )
    request = urllib.request.Request(
        "https://api.open-meteo.com/v1/forecast?" + query,
        headers={"User-Agent": "TinyPi-Epaper-Weather/1.0"},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response)


def short_clock(value: str) -> str:
    return value.rsplit("T", 1)[-1][:5]


def render_weather(payload: dict, config: dict) -> Canvas:
    current = payload["current"]
    daily = payload["daily"]
    timezone = ZoneInfo(config["timezone"])
    now = datetime.now(timezone)
    temperature = round(float(current["temperature_2m"]))
    feels = round(float(current["apparent_temperature"]))
    weather = WEATHER_CODES.get(int(current["weather_code"]), "WEATHER")
    high = round(float(daily["temperature_2m_max"][0]))
    low = round(float(daily["temperature_2m_min"][0]))
    rain = round(float(daily["precipitation_probability_max"][0] or 0))
    wind = round(float(current["wind_speed_10m"]))

    canvas = Canvas()
    canvas.fill_rect(0, 0, 250, 17, True)
    canvas.text(6, 5, ellipsize(config["location"], 24), 1, False)
    canvas.right_text(244, 5, now.strftime("%H:%M"), 1, False)

    canvas.text(8, 30, f"{temperature} C", 3)
    canvas.text(8, 60, f"FEELS {feels} C", 1)
    canvas.line(112, 24, 112, 77, True)
    canvas.text(124, 29, ellipsize(weather, 19), 1)
    canvas.text(124, 45, f"HIGH {high} C", 1)
    canvas.text(124, 58, f"LOW  {low} C", 1)

    canvas.fill_rect(0, 83, 250, 1, True)
    canvas.text(7, 91, f"RAIN {rain}%", 1)
    canvas.centered_text(91, f"WIND {wind} KM/H", 1)
    canvas.right_text(243, 91, "SUN " + short_clock(daily["sunset"][0]), 1)
    canvas.text(7, 108, now.strftime("%A %d %B"), 1)
    return canvas


def render_error(message: str, config: dict) -> Canvas:
    canvas = Canvas()
    canvas.fill_rect(0, 0, 250, 17, True)
    canvas.text(6, 5, ellipsize(config["location"], 24), 1, False)
    canvas.centered_text(37, "WEATHER OFFLINE", 2)
    canvas.centered_text(68, ellipsize(message, 36), 1)
    canvas.centered_text(96, "RETRYING AUTOMATICALLY", 1)
    return canvas


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    config = load_config()
    last_payload = None
    refresh_seconds = max(60, int(config.get("refresh_seconds", 60)))

    while True:
        cycle_started = time.monotonic()
        try:
            payload = fetch_weather(config)
            elapsed = paint(render_weather(payload, config))
            print(f"Weather display refreshed in {elapsed:.2f}s", flush=True)
            last_payload = payload
        except Exception as error:
            message = str(error).splitlines()[0][:80]
            print(f"Weather error: {message}", file=sys.stderr, flush=True)
            if last_payload is None:
                paint(render_error(message, config))
            if args.once:
                return 1
        if args.once:
            return 0
        cycle_elapsed = time.monotonic() - cycle_started
        time.sleep(max(1.0, refresh_seconds - cycle_elapsed))


if __name__ == "__main__":
    raise SystemExit(main())
