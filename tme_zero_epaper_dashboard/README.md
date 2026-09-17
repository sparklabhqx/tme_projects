# TME Pi Zero E-Paper Dashboard

A Raspberry Pi Zero 2 W dashboard for a 250×122 SPI e-paper HAT. It includes three switchable applications, a one-shot TME.eu logo screen, a shared direct-SPI display driver, a user-level systemd service, and the two STL parts for the enclosure.

## Applications

### Spotify player

- Reads the current Spotify playback state through the Spotify Web API.
- Shows track, artist, play/pause state, progress, and playback time.
- Downloads the current album cover and converts it to a high-contrast, Floyd–Steinberg-dithered monochrome image on the right side.
- Polls every 15 seconds but limits panel redraws to track/state changes and five-minute progress buckets.
- Requires personal Spotify OAuth credentials in an ignored local file.

### Weather station

- Loads live Munich weather from Open-Meteo; no API key is required.
- Shows temperature, apparent temperature, condition, daily high/low, rain probability, wind, and sunset.
- Fetches data and redraws the panel every 60 seconds.
- Location, coordinates, timezone, and interval are configurable in `weather_station/config.json`.

### Calendar

- Alternates every 60 seconds between a month view and a daily-agenda view.
- Highlights today and marks dates containing events.
- The daily view displays today's first task, including its time.
- Personal event data stays in the ignored `calendar/events.json`; a harmless sample is provided as `events.example.json`.

### TME.eu logo

A one-shot native 1-bit TME.eu logo screen with black artwork on a white background:

```bash
python3 ~/epaper_projects/tme_logo/show.py
```

## Hardware

- Raspberry Pi Zero 2 W
- 250×122 SPI e-paper HAT
- SPI device: `/dev/spidev0.0`
- Reset: BCM 17
- Data/command: BCM 25
- Busy: BCM 24

The driver renders on a logical 250×122 landscape canvas and maps it to the panel's native 122×250 memory orientation.

## Enclosure files

Both complementary parts found in Downloads on 2026-09-16 are included:

```text
stl/tme_epaper_zero_body.stl  # approximately 94 × 40.6 × 16 mm
stl/tme_epaper_zero_top.stl   # approximately 83.9 × 33.3 × 3.2 mm
```

Check orientation and slicer tolerances before printing.

## Install on Raspberry Pi OS

The Pi must expose SPI directly. Keep this line enabled in `/boot/firmware/config.txt`:

```text
dtparam=spi=on
```

Disable any old TFT framebuffer overlay such as `tft9341`, `ili9341`, or `fbtft`, then reboot. Those overlays claim SPI and prevent `/dev/spidev0.0` from appearing.

Install:

```bash
git clone https://github.com/sparklabhqx/tme_projects.git
cd tme_projects/tme_zero_epaper_dashboard
chmod +x install.sh
./install.sh
```

The installer:

- installs Pillow, RPi.GPIO, and spidev,
- copies the application to `~/epaper_projects`,
- installs and enables `epaper-app.service` as a user service,
- enables user linger for boot startup,
- installs the `epaper-app` command,
- starts the weather screen by default.

## Switch applications

```bash
epaper-app spotify
epaper-app weather
epaper-app calendar
```

Management commands:

```bash
epaper-app status
epaper-app refresh
epaper-app stop
epaper-app start
epaper-app logs
```

E-paper retains its last image when the service is stopped.

## Spotify configuration

Create a Spotify developer application with a refresh token that has playback-state access. The installer creates the private file from the example if it does not already exist:

```bash
nano ~/epaper_projects/spotify_player/config.json
chmod 600 ~/epaper_projects/spotify_player/config.json
```

Expected structure:

```json
{
  "client_id": "YOUR_SPOTIFY_CLIENT_ID",
  "client_secret": "YOUR_SPOTIFY_CLIENT_SECRET",
  "refresh_token": "YOUR_SPOTIFY_REFRESH_TOKEN"
}
```

Never commit this file.

## Calendar events

Edit:

```bash
nano ~/epaper_projects/calendar/events.json
epaper-app refresh
```

Format:

```json
[
  {
    "date": "2026-09-17",
    "time": "14:00",
    "title": "Meeting with Tom at 2pm"
  }
]
```

## Manual one-shot tests

```bash
cd ~/epaper_projects
python3 spotify_player/app.py --once
python3 weather_station/app.py --once
python3 calendar/app.py --once --view month
python3 calendar/app.py --once --view day
python3 tme_logo/show.py
```

Stop `epaper-app.service` before manual display tests to prevent two processes from accessing SPI simultaneously.

## Refresh-rate note

The weather and calendar applications currently perform a full e-paper redraw every minute. This is useful for demonstration but causes more flashing, power use, and panel wear than a slower interval. Increase the configured interval for long-term unattended operation.

## Secrets and generated files

The repository intentionally excludes:

- Spotify client ID, client secret, and refresh token
- personal live calendar events
- runtime logs, Python caches, and deployment backups

Only placeholder/example configuration files are committed.
