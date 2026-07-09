#!/usr/bin/env bash
set -euo pipefail

# Install the TinyPi / Pi Zero side runtime files.
# Run from this directory on the Pi as the user that should own the cyberdeck app.
# Example:
#   cd ~/tme_cyberdeck/piZero_side
#   bash install_pi_zero.sh

APP_USER="${SUDO_USER:-$USER}"
APP_HOME="$(getent passwd "$APP_USER" | cut -d: -f6)"

if [[ -z "$APP_HOME" || ! -d "$APP_HOME" ]]; then
  echo "Could not determine home directory for $APP_USER" >&2
  exit 1
fi

if [[ ! -f usb_keyboard_display.py ]]; then
  echo "Run this script from the piZero_side directory." >&2
  exit 1
fi

echo "Installing packages..."
sudo apt-get update
sudo apt-get install -y \
  bluetooth \
  bluez \
  curl \
  wget \
  python3 \
  python3-pygame \
  python3-venv \
  rfkill

echo "Installing app files into $APP_HOME ..."
install -m 0755 usb_keyboard_display.py "$APP_HOME/usb_keyboard_display.py"
install -m 0755 bt_keyboard_pair_wait_input.py "$APP_HOME/bt_keyboard_pair_wait_input.py"
install -d -m 0755 "$APP_HOME/chatbot"
install -m 0755 chatbot/bt_keyboard_agent.sh "$APP_HOME/chatbot/bt_keyboard_agent.sh"

# Preserve an existing bridge URL if present. Otherwise create an empty placeholder.
if [[ ! -f "$APP_HOME/esp_bridge_url" ]]; then
  cat > "$APP_HOME/esp_bridge_url" <<'EOF'
http://ESP_IP_HERE:8765
EOF
  chown "$APP_USER:$APP_USER" "$APP_HOME/esp_bridge_url"
fi

echo "Installing systemd services..."
sudo install -m 0644 services/usb-keyboard-display.service /etc/systemd/system/usb-keyboard-display.service
mkdir -p "$APP_HOME/.config/systemd/user"
install -m 0644 services/bt-keyboard-agent.service "$APP_HOME/.config/systemd/user/bt-keyboard-agent.service"
chown -R "$APP_USER:$APP_USER" "$APP_HOME/.config"

sudo systemctl daemon-reload
sudo loginctl enable-linger "$APP_USER" || true

# Try to enable the user service as the app user. If this fails over non-interactive SSH,
# run the printed command manually after logging in as APP_USER.
if command -v runuser >/dev/null 2>&1; then
  sudo runuser -u "$APP_USER" -- systemctl --user daemon-reload || true
  sudo runuser -u "$APP_USER" -- systemctl --user enable --now bt-keyboard-agent.service || true
fi

sudo systemctl enable --now bluetooth.service
sudo systemctl enable --now usb-keyboard-display.service

cat <<EOF

Pi side installed.

Next steps:
1. Install llama.cpp + SmolLM2 model following MODEL_SETUP.md.
2. Set the ESP bridge URL:
     echo http://ESP_IP:8765 > ~/esp_bridge_url
3. Pair the Bluetooth keyboard if needed:
     systemctl --user stop bt-keyboard-agent.service
     BT_PAIR_TIMEOUT=300 setsid python3 ~/bt_keyboard_pair_wait_input.py </dev/null >/tmp/bt_keyboard_pair_wait_input.nohup 2>&1 &
4. Restart the display app:
     sudo systemctl restart usb-keyboard-display.service

EOF
