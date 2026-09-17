#!/usr/bin/env python3
"""Spotify now-playing screen for the TinyPi 250x122 e-paper HAT."""

from __future__ import annotations

import argparse
import base64
import json
import sys
import time
from io import BytesIO
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image, ImageEnhance, ImageOps

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
from common.epaper_display import Canvas, ellipsize, paint  # noqa: E402

CONFIG_PATH = Path(__file__).with_name("config.json")
TIMEZONE = ZoneInfo("Europe/Berlin")
ART_X = 154
ART_Y = 23
ART_SIZE = 92
ART_CACHE: dict[str, Image.Image] = {}


def read_config() -> dict:
    if not CONFIG_PATH.exists():
        raise RuntimeError("Spotify config.json is missing")
    config = json.loads(CONFIG_PATH.read_text())
    missing = [key for key in ("client_id", "client_secret", "refresh_token") if not config.get(key)]
    if missing:
        raise RuntimeError("Spotify config is incomplete")
    return config


def request_json(request: urllib.request.Request, timeout: int = 20):
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if response.status == 204:
                return None
            return json.load(response)
    except urllib.error.HTTPError as error:
        detail = error.read(300).decode("utf-8", "replace")
        raise RuntimeError(f"Spotify HTTP {error.code}: {detail}") from error


def refresh_access_token(config: dict) -> tuple[str, float]:
    credentials = f"{config['client_id']}:{config['client_secret']}".encode()
    body = urllib.parse.urlencode(
        {"grant_type": "refresh_token", "refresh_token": config["refresh_token"]}
    ).encode()
    request = urllib.request.Request(
        "https://accounts.spotify.com/api/token",
        data=body,
        method="POST",
        headers={
            "Authorization": "Basic " + base64.b64encode(credentials).decode(),
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "TinyPi-Epaper/1.0",
        },
    )
    payload = request_json(request)
    if not payload or not payload.get("access_token"):
        raise RuntimeError("Spotify token response did not contain an access token")
    if payload.get("refresh_token") and payload["refresh_token"] != config["refresh_token"]:
        config["refresh_token"] = payload["refresh_token"]
        CONFIG_PATH.write_text(json.dumps(config, indent=2) + "\n")
        CONFIG_PATH.chmod(0o600)
    return payload["access_token"], time.time() + int(payload.get("expires_in", 3600)) - 60


def fetch_player(access_token: str):
    request = urllib.request.Request(
        "https://api.spotify.com/v1/me/player?additional_types=episode",
        headers={"Authorization": f"Bearer {access_token}", "User-Agent": "TinyPi-Epaper/1.0"},
    )
    return request_json(request)


def item_details(state: dict) -> tuple[str, str, str, int, int]:
    item = state.get("item") or {}
    title = item.get("name") or "UNKNOWN TITLE"
    if item.get("type") == "episode":
        artist = (item.get("show") or {}).get("name") or "PODCAST"
        item_id = item.get("id") or title
    else:
        artist = ", ".join(entry.get("name", "") for entry in item.get("artists", [])) or "UNKNOWN ARTIST"
        item_id = item.get("id") or title
    return title, artist, item_id, int(state.get("progress_ms") or 0), int(item.get("duration_ms") or 0)


def format_time(milliseconds: int) -> str:
    seconds = max(0, milliseconds // 1000)
    return f"{seconds // 60}:{seconds % 60:02d}"


def wrapped_lines(value: object, max_chars: int, max_lines: int) -> list[str]:
    words = str(value).upper().split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            lines.append(current)
        current = word
        if len(lines) == max_lines - 1:
            break
    if current and len(lines) < max_lines:
        lines.append(current)
    if len(lines) == max_lines and len(" ".join(words)) > len(" ".join(lines)):
        lines[-1] = ellipsize(lines[-1], max_chars)
    return lines


def album_art_url(state: dict) -> str:
    item = state.get("item") or {}
    if item.get("type") == "episode":
        images = item.get("images") or (item.get("show") or {}).get("images") or []
    else:
        images = (item.get("album") or {}).get("images") or []
    usable = [image for image in images if image.get("url")]
    if not usable:
        return ""
    chosen = min(usable, key=lambda image: abs(int(image.get("width") or 300) - 300))
    return str(chosen["url"])


def fetch_album_art(url: str) -> Image.Image | None:
    if not url:
        return None
    if url in ART_CACHE:
        return ART_CACHE[url]
    request = urllib.request.Request(url, headers={"User-Agent": "TinyPi-Epaper/1.0"})
    with urllib.request.urlopen(request, timeout=20) as response:
        source = Image.open(BytesIO(response.read())).convert("L")
    fitted = ImageOps.fit(source, (ART_SIZE, ART_SIZE), method=Image.Resampling.LANCZOS)
    fitted = ImageOps.autocontrast(fitted)
    fitted = ImageEnhance.Contrast(fitted).enhance(1.15)
    mono = fitted.convert("1", dither=Image.Dither.FLOYDSTEINBERG)
    ART_CACHE.clear()
    ART_CACHE[url] = mono
    print(f"Album art cached: {url.rsplit('/', 1)[-1][:24]}", flush=True)
    return mono


def draw_art_placeholder(canvas: Canvas) -> None:
    canvas.rect(ART_X - 3, ART_Y - 3, ART_SIZE + 6, ART_SIZE + 6, True)
    for index, height in enumerate((20, 42, 31, 55, 37)):
        canvas.fill_rect(ART_X + 17 + index * 11, ART_Y + 70 - height, 7, height, True)
    canvas.text(ART_X + 25, 101, "NO ART", 1)


def draw_album_art(canvas: Canvas, state: dict) -> None:
    try:
        image = fetch_album_art(album_art_url(state))
    except Exception as error:
        print(f"Album art error: {error}", file=sys.stderr, flush=True)
        image = None
    if image is None:
        draw_art_placeholder(canvas)
        return
    canvas.rect(ART_X - 3, ART_Y - 3, ART_SIZE + 6, ART_SIZE + 6, True)
    pixels = image.load()
    for y in range(ART_SIZE):
        for x in range(ART_SIZE):
            if pixels[x, y] == 0:
                canvas.pixel(ART_X + x, ART_Y + y, True)


def render_state(state: dict | None = None, error: str | None = None) -> Canvas:
    canvas = Canvas()
    now = datetime.now(TIMEZONE)
    canvas.fill_rect(0, 0, 250, 17, True)
    canvas.text(6, 5, "SPOTIFY", 1, False)
    canvas.right_text(244, 5, now.strftime("%H:%M"), 1, False)

    if error:
        canvas.centered_text(35, "SPOTIFY OFFLINE", 2)
        canvas.centered_text(64, ellipsize(error, 35), 1)
        canvas.centered_text(91, "WILL RETRY AUTOMATICALLY", 1)
        return canvas

    if not state or not state.get("item"):
        for index, height in enumerate((12, 25, 18, 31, 21)):
            canvas.fill_rect(62 + index * 10, 62 - height, 6, height, True)
        canvas.text(124, 36, "NOTHING", 2)
        canvas.text(124, 55, "PLAYING", 2)
        canvas.centered_text(94, "START MUSIC IN SPOTIFY", 1)
        return canvas

    title, artist, _, progress_ms, duration_ms = item_details(state)
    playing = bool(state.get("is_playing"))
    title_lines = wrapped_lines(title, 22, 2)
    for index, line in enumerate(title_lines):
        canvas.text(7, 25 + index * 12, ellipsize(line, 22), 1)
    canvas.text(7, 53, ellipsize(artist, 22), 1)
    badge = "PLAYING" if playing else "PAUSED"
    canvas.fill_rect(7, 67, 52 if playing else 46, 13, True)
    canvas.text(11, 70, badge, 1, False)
    if duration_ms:
        canvas.progress(7, 88, 137, progress_ms / duration_ms)
        canvas.text(7, 102, format_time(progress_ms), 1)
        canvas.right_text(144, 102, format_time(duration_ms), 1)
    draw_album_art(canvas, state)
    return canvas


def state_signature(state: dict | None):
    if not state or not state.get("item"):
        return ("idle",)
    _, _, item_id, progress_ms, _ = item_details(state)
    playing = bool(state.get("is_playing"))
    progress_bucket = progress_ms // 300_000 if playing else progress_ms
    return item_id, playing, progress_bucket


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="refresh once and exit")
    args = parser.parse_args()
    config = read_config()
    access_token = ""
    token_expires = 0.0
    last_signature = object()
    last_error = ""

    while True:
        try:
            if time.time() >= token_expires:
                access_token, token_expires = refresh_access_token(config)
            try:
                state = fetch_player(access_token)
            except RuntimeError as error:
                if "HTTP 401" not in str(error):
                    raise
                access_token, token_expires = refresh_access_token(config)
                state = fetch_player(access_token)
            signature = state_signature(state)
            if signature != last_signature or args.once:
                elapsed = paint(render_state(state))
                print(f"Spotify display refreshed in {elapsed:.2f}s", flush=True)
                last_signature = signature
            last_error = ""
        except Exception as error:
            message = str(error).splitlines()[0][:80]
            print(f"Spotify error: {message}", file=sys.stderr, flush=True)
            if message != last_error or args.once:
                paint(render_state(error=message))
                last_error = message
        if args.once:
            return 0 if not last_error else 1
        time.sleep(15)


if __name__ == "__main__":
    raise SystemExit(main())
