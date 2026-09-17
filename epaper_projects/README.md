# Three E-Paper Apps for the Raspberry Pi Zero 2 W

One 250x122 e-paper display, three apps: a live weather station, a Spotify
now-playing screen, and a calendar with a month view and a daily agenda.
A single command switches between them; a systemd user service keeps the
selected app running and restarts it after power loss.

Because the panel is bistable, the last image simply stays on screen when the
app is stopped or the power is cut.

## Hardware

- Raspberry Pi Zero 2 W (any Pi with a 40-pin header works)
- Waveshare 2.13 inch e-Paper HAT, 250 x 122 pixels, black/white
  (plugs straight onto the 40-pin header, no wiring)
- microSD card with Raspberry Pi OS, USB power supply
- Optional: 3D-printed case in `case/` — `case_bottom.stl` (94 x 41 x 16 mm,
  holds the Pi + HAT) and `case_top.stl` (84 x 33 x 3 mm frame around the
  display), joined with four small self-tapping screws

Signals used by the driver (`common/epaper_display.py`): hardware SPI0
(`/dev/spidev0.0`, CE0) plus DC = GPIO25, RST = GPIO17, BUSY = GPIO24 —
the standard pinout of the Waveshare HAT.

## Install

On the Pi (Raspberry Pi OS Bookworm):

```bash
sudo raspi-config          # Interface Options -> SPI -> enable
sudo apt install python3-pil python3-spidev python3-rpi-lgpio
```

Copy this folder to `~/epaper_projects`, then install the switcher command
and the service:

```bash
ln -s ~/epaper_projects/epaper-app ~/bin/epaper-app   # or anywhere on PATH
cp ~/epaper_projects/epaper-app.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now epaper-app.service
loginctl enable-linger $USER   # start at boot without a login session
```

## Switch apps

```bash
epaper-app weather
epaper-app spotify
epaper-app calendar
```

Other commands: `status`, `refresh`, `stop`, `start`, `logs`. Stopping the
service leaves the last image on the panel.

## Weather Station (`weather_station/`)

Uses the free Open-Meteo API — no API key needed. Shows current temperature,
feels-like, condition, high/low, rain probability, wind and sunset, and
refreshes every 60 seconds. Edit `weather_station/config.json` to set your
location, coordinates and timezone.

One-shot test: `python3 weather_station/app.py --once`

## Spotify Player (`spotify_player/`)

Shows the current track, artist, play state, progress bar and dithered album
art. Polls Spotify every 15 seconds but only repaints the panel when the
track or play state changes.

Setup: create an app in the [Spotify developer
dashboard](https://developer.spotify.com/dashboard), authorize it once for
your account with the `user-read-playback-state` scope, then copy
`config.example.json` to `config.json`, fill in `client_id`,
`client_secret` and `refresh_token`, and set `chmod 600 config.json`.
Never publish this file.

One-shot test: `python3 spotify_player/app.py --once`

## Calendar (`calendar/`)

Alternates every 60 seconds between a month view (today highlighted, event
days dotted) and a daily agenda. Events live in `calendar/events.json`:

```json
[
  {"date": "2026-09-20", "time": "14:00", "title": "Meeting with Tom at 2pm"}
]
```

After editing, run `epaper-app refresh`.

One-shot tests: `python3 calendar/app.py --once --view month` (or `--view day`)

## How it works

`epaper-app <name>` writes the choice to `active_app` and restarts the
service; `run_selected.py` execs the chosen `app.py`. All three apps share
`common/epaper_display.py`: a 250x122 one-bit canvas with a small pixel font,
and a minimal SPI driver that wakes the panel, sends the ~4 KB frame, waits
for BUSY, and puts the panel into deep sleep after every update.

`tme_logo/show.py` pushes a static logo image once — handy as a first test
that the display works.
