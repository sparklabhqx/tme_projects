# Pi Zero / TinyPi side

This folder contains the Pi-side pieces of the TinyPi + ESP32 cyberdeck launcher hub.

## Files

```text
usb_keyboard_display.py
  Main runtime: Bluetooth keyboard input, framebuffer UI, cue parser, local LLM, ESP bridge.

bt_keyboard_pair_wait_input.py
  Re-pairing helper for Bluetooth keyboards; waits until Linux creates a real event device.

chatbot/bt_keyboard_agent.sh
  Keeps a bluetoothctl KeyboardDisplay pairing agent registered.

services/usb-keyboard-display.service
  System service for the main runtime.

services/bt-keyboard-agent.service
  User service for the Bluetooth pairing agent.

install_pi_zero.sh
  Convenience installer for a fresh Pi side.

MODEL_SETUP.md
  Instructions for installing the SmolLM2 GGUF model and llama.cpp.

TINYPI_ESP_LAUNCHER_HUB.md
  Full detailed project documentation.
```

## Hardware/OS assumptions

- Raspberry Pi Zero / Zero 2 W class board.
- Debian/Raspberry Pi OS with systemd.
- SPI TFT exposed as Linux framebuffer `/dev/fb*`.
- Bluetooth adapter available as `hci0`.
- Bluetooth keyboard paired as a Linux input event device.
- Same WiFi/LAN as the ESP32 console.

## Quick install on a fresh Pi

Copy this `piZero_side` folder to the Pi, then:

```bash
cd piZero_side
bash install_pi_zero.sh
```

Then install model/runtime following:

```bash
less MODEL_SETUP.md
```

Set the ESP bridge URL:

```bash
echo http://ESP_IP:8765 > ~/esp_bridge_url
```

Restart:

```bash
sudo systemctl restart usb-keyboard-display.service
```

## Pair keyboard

If the keyboard is not typing into the UI:

```bash
systemctl --user stop bt-keyboard-agent.service
BT_PAIR_TIMEOUT=300 setsid python3 ~/bt_keyboard_pair_wait_input.py </dev/null >/tmp/bt_keyboard_pair_wait_input.nohup 2>&1 &
```

Put the keyboard into pairing mode. When the TinyPi screen says the keyboard is ready, restart the passive agent:

```bash
systemctl --user start bt-keyboard-agent.service
```

## Cue words

Typed cue words are intercepted before the local LLM:

```text
dino
snake
clock
weather [location]
draw
chat [prompt]
timer [duration] [label]
```

Anything else goes to the local SmolLM2 model and displays a one-sentence answer.
