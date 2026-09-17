#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -eq 0 ]]; then
  echo "Run this installer as the normal Pi user, not as root." >&2
  exit 1
fi

SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="${HOME}/epaper_projects"
SERVICE_DIR="${HOME}/.config/systemd/user"

if grep -Eq '^[[:space:]]*dtoverlay=.*(tft|ili934|fbtft)' /boot/firmware/config.txt 2>/dev/null; then
  cat >&2 <<'EOF'
An active TFT framebuffer overlay still claims SPI in /boot/firmware/config.txt.
Disable that overlay and reboot before running this direct-SPI e-paper project.
Keep `dtparam=spi=on` enabled.
EOF
  exit 1
fi

sudo apt-get update
sudo apt-get install -y python3-pil python3-rpi.gpio python3-spidev
sudo raspi-config nonint do_spi 0
sudo usermod -aG gpio,spi "${USER}"

mkdir -p "${DEST}" "${SERVICE_DIR}"
cp -a "${SOURCE_DIR}/epaper_projects/." "${DEST}/"
install -m 0644 "${SOURCE_DIR}/systemd/epaper-app.service" "${SERVICE_DIR}/epaper-app.service"

if [[ ! -f "${DEST}/spotify_player/config.json" ]]; then
  install -m 0600 "${DEST}/spotify_player/config.example.json" \
    "${DEST}/spotify_player/config.json"
fi
if [[ ! -f "${DEST}/calendar/events.json" ]]; then
  install -m 0644 "${DEST}/calendar/events.example.json" \
    "${DEST}/calendar/events.json"
fi

chmod +x "${DEST}/epaper-app" "${DEST}/run_selected.py" "${DEST}"/*/app.py 2>/dev/null || true
chmod +x "${DEST}/tme_logo/show.py"
printf 'weather\n' > "${DEST}/active_app"

sudo ln -sfn "${DEST}/epaper-app" /usr/local/bin/epaper-app
sudo loginctl enable-linger "${USER}"
systemctl --user daemon-reload
systemctl --user enable --now epaper-app.service

cat <<EOF
Installed to: ${DEST}
Default app: weather

Switch apps with:
  epaper-app spotify
  epaper-app weather
  epaper-app calendar

Before selecting Spotify, edit:
  ${DEST}/spotify_player/config.json

If group membership was added for the first time, reboot once before using the display.
EOF
