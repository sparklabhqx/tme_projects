#!/usr/bin/env python3
"""Alternating month and daily calendar for the TinyPi e-paper HAT."""

from __future__ import annotations

import argparse
import calendar as calendar_module
import json
import sys
import time
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
from common.epaper_display import Canvas, ellipsize, paint, text_width  # noqa: E402

CONFIG_PATH = Path(__file__).with_name("config.json")
EVENTS_PATH = Path(__file__).with_name("events.json")
DEFAULT_CONFIG = {"timezone": "Europe/Berlin", "week_starts_monday": True}
WEEKDAYS = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")


def load_json(path: Path, fallback):
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return fallback


def load_events() -> list[dict]:
    events = load_json(EVENTS_PATH, [])
    return events if isinstance(events, list) else []


def events_for_day(events: list[dict], day: date) -> list[dict]:
    day_key = day.isoformat()
    return sorted(
        [event for event in events if str(event.get("date", "")) == day_key],
        key=lambda event: str(event.get("time", "")),
    )


def wrap_words(value: object, max_chars: int) -> list[str]:
    words = str(value).upper().split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word[:max_chars]
    if current:
        lines.append(current)
    return lines


def render_calendar(now: datetime, events: list[dict]) -> Canvas:
    canvas = Canvas()
    year, month = now.year, now.month
    month_title = now.strftime("%B %Y")
    marked_days = {
        int(event["date"].rsplit("-", 1)[-1])
        for event in events
        if str(event.get("date", "")).startswith(f"{year:04d}-{month:02d}-")
    }

    canvas.fill_rect(0, 0, 250, 18, True)
    canvas.centered_text(5, month_title, 1, False)

    left = 5
    cell_width = 34
    for column, label in enumerate(WEEKDAYS):
        x = left + column * cell_width
        canvas.text(x + (cell_width - text_width(label)) // 2, 23, label, 1)
    canvas.line(4, 33, 245, 33, True)

    weeks = calendar_module.Calendar(firstweekday=0).monthdayscalendar(year, month)
    row_height = 12 if len(weeks) == 6 else 14
    start_y = 36
    for row, week in enumerate(weeks):
        y = start_y + row * row_height
        for column, day in enumerate(week):
            if not day:
                continue
            x = left + column * cell_width
            label = str(day)
            label_x = x + (cell_width - text_width(label)) // 2
            if day == now.day:
                canvas.fill_rect(x + 5, y - 2, cell_width - 10, 11, True)
                canvas.text(label_x, y, label, 1, False)
            else:
                canvas.text(label_x, y, label, 1)
            if day in marked_days:
                canvas.fill_rect(x + cell_width // 2 - 1, y + 10, 3, 2, True)

    footer_y = 112
    canvas.fill_rect(0, 109, 250, 1, True)
    canvas.text(5, footer_y, now.strftime("TODAY %A %d"), 1)
    upcoming = []
    today = now.date().isoformat()
    for event in events:
        if str(event.get("date", "")) >= today and event.get("title"):
            upcoming.append(event)
    if upcoming:
        next_event = sorted(upcoming, key=lambda event: event["date"])[0]
        canvas.right_text(245, footer_y, ellipsize(next_event["title"], 18), 1)
    else:
        canvas.right_text(245, footer_y, now.strftime("%H:%M"), 1)
    return canvas


def render_daily(now: datetime, events: list[dict]) -> Canvas:
    canvas = Canvas()
    todays_events = events_for_day(events, now.date())

    canvas.fill_rect(0, 0, 250, 18, True)
    canvas.text(6, 5, "DAILY CALENDAR", 1, False)
    canvas.right_text(244, 5, now.strftime("%H:%M"), 1, False)

    # Large date card on the left.
    canvas.fill_rect(7, 25, 76, 78, True)
    day_label = str(now.day)
    canvas.text(7 + (76 - text_width(day_label, 5)) // 2, 32, day_label, 5, False)
    month_label = now.strftime("%B")[:10]
    canvas.text(7 + (76 - text_width(month_label)) // 2, 76, month_label, 1, False)
    weekday_label = now.strftime("%A")[:10]
    canvas.text(7 + (76 - text_width(weekday_label)) // 2, 90, weekday_label, 1, False)

    canvas.text(96, 27, "TODAY'S TASK", 1)
    canvas.line(95, 38, 243, 38, True)
    if todays_events:
        event = todays_events[0]
        event_time = str(event.get("time") or "ALL DAY")
        canvas.text(96, 45, ellipsize(event_time, 10), 2)
        lines = wrap_words(event.get("title", "TASK"), 23)
        for index, line in enumerate(lines[:3]):
            canvas.text(96, 68 + index * 12, ellipsize(line, 23), 1)
    else:
        canvas.text(96, 50, "NO TASKS", 2)
        canvas.text(96, 75, "ENJOY YOUR DAY", 1)

    canvas.fill_rect(0, 109, 250, 1, True)
    canvas.text(5, 113, "DAILY VIEW", 1)
    canvas.right_text(245, 113, "MONTH VIEW NEXT", 1)
    return canvas


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--view", choices=("alternate", "month", "day"), default="alternate")
    args = parser.parse_args()
    config = DEFAULT_CONFIG.copy()
    config.update(load_json(CONFIG_PATH, {}))
    timezone = ZoneInfo(config["timezone"])
    refresh_seconds = max(60, int(config.get("refresh_seconds", 60)))

    view_index = 0
    while True:
        cycle_started = time.monotonic()
        now = datetime.now(timezone)
        events = load_events()
        view = args.view
        if view == "alternate":
            view = "month" if view_index % 2 == 0 else "day"
        canvas = render_calendar(now, events) if view == "month" else render_daily(now, events)
        elapsed = paint(canvas)
        print(f"Calendar {view} view refreshed in {elapsed:.2f}s", flush=True)
        view_index += 1
        if args.once:
            return 0
        cycle_elapsed = time.monotonic() - cycle_started
        time.sleep(max(1.0, refresh_seconds - cycle_elapsed))


if __name__ == "__main__":
    raise SystemExit(main())
