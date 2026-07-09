# tme_cyberdeck manifest

This folder contains the reproducible source/docs for the TinyPi + ESP32 cyberdeck launcher hub.

## Included

- `README.md` — top-level recreation guide.
- `piZero_side/TINYPI_ESP_LAUNCHER_HUB.md` — detailed project record.
- `piZero_side/usb_keyboard_display.py` — Pi Zero runtime app.
- `piZero_side/bt_keyboard_pair_wait_input.py` — Bluetooth pairing helper.
- `piZero_side/chatbot/bt_keyboard_agent.sh` — Bluetooth pairing agent script.
- `piZero_side/services/*.service` — systemd units.
- `piZero_side/install_pi_zero.sh` — convenience installer for the Pi side.
- `piZero_side/MODEL_SETUP.md` — local LLM setup notes.
- `esp_side/README.md` — ESP-side detailed README from the ESP agent.
- `esp_side/platformio.ini` — PlatformIO build config.
- `esp_side/src/main.cpp` — ESP32 launcher hub firmware.
- `esp_side/src/secrets.example.h` — sanitized secrets template.

## Not included

- Real WiFi credentials or API keys.
- `esp_side/src/secrets.h`.
- The 85 MB GGUF model file.
- The llama.cpp binary bundle.
- Physical hardware, SD card image, or OS image.

A third party can recreate the project if they provide equivalent hardware, credentials, the model, and llama.cpp binaries/build.
