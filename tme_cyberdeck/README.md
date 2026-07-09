# TME Cyberdeck: TinyPi + ESP32 LCD Joystick Launcher Hub

This folder packages the docs and source needed to recreate the TinyPi cyberdeck + ESP32 LCD joystick launcher hub.

## What this project does

- A Raspberry Pi Zero / TinyPi reads a Bluetooth keyboard and drives a tiny framebuffer display.
- Typed cue words launch modes on an ESP32 LCD joystick console over WiFi.
- Non-cue text is answered locally on the Pi by a small SmolLM2 model.
- The ESP32 exposes an HTTP JSON API and displays/plays modes such as Dino, Snake, Clock, Weather, Draw, Chat, and Timer.

## Folder layout

```text
tme_cyberdeck/
├── README.md
├── MANIFEST.md
├── .gitignore
├── piZero_side/
│   ├── README.md
│   ├── TINYPI_ESP_LAUNCHER_HUB.md
│   ├── usb_keyboard_display.py
│   ├── bt_keyboard_pair_wait_input.py
│   ├── install_pi_zero.sh
│   ├── MODEL_SETUP.md
│   ├── chatbot/
│   │   └── bt_keyboard_agent.sh
│   └── services/
│       ├── usb-keyboard-display.service
│       └── bt-keyboard-agent.service
└── esp_side/
    ├── README.md
    ├── platformio.ini
    ├── .gitignore
    └── src/
        ├── main.cpp
        └── secrets.example.h
```

## Is this enough to recreate the project?

Mostly yes, with these required external pieces:

1. Matching or equivalent hardware.
2. WiFi credentials in `esp_side/src/secrets.h` copied from `secrets.example.h`.
3. A Pi OS install with the TFT framebuffer configured.
4. The SmolLM2 GGUF model and llama.cpp binary bundle, installed using `piZero_side/MODEL_SETUP.md`.
5. The ESP32 IP/bridge URL configured on the Pi with `~/esp_bridge_url`.

Secrets, the GGUF model, and llama.cpp binaries are intentionally not committed into this folder.

## Recreate ESP side

```bash
cd esp_side
cp src/secrets.example.h src/secrets.h
# edit src/secrets.h with WiFi SSID/password
pio run
pio run -t upload
pio device monitor
```

After upload, find the ESP IP in the serial monitor and test:

```bash
curl http://ESP_IP:8765/health
curl http://ESP_IP:8765/cues
```

## Recreate Pi side

Copy `piZero_side` to the Pi, then:

```bash
cd piZero_side
bash install_pi_zero.sh
```

Install the local model and llama.cpp runtime following:

```bash
less MODEL_SETUP.md
```

Configure ESP URL:

```bash
echo http://ESP_IP:8765 > ~/esp_bridge_url
sudo systemctl restart usb-keyboard-display.service
```

## Full details

Read:

```text
piZero_side/TINYPI_ESP_LAUNCHER_HUB.md
esp_side/README.md
```
