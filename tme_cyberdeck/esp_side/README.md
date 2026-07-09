# ESP LCD Joystick Launcher Hub

Tiny WiFi command bridge and monochrome game/info hub for an ESP32 DevKitC + Waveshare 2-inch ST7789 LCD + passive 5-way joystick.

This project lives at:

```text
/Users/flo/esp32_flappy_st7789
```

It currently exposes a LAN HTTP API on the ESP32 so a Raspberry Pi Zero / TinyPi / cyberdeck on the same WiFi can send cue words such as `dino`, `snake`, `clock`, `weather`, `draw`, `chat`, and `timer`. The ESP32 receives the cue and switches the LCD to the requested game or utility screen.

---

## Current status

- Board: ESP32 DevKitC / ESP32-WROOM style board.
- Framework: PlatformIO + Arduino.
- Display library: `bodmer/TFT_eSPI`.
- Display: Waveshare 2-inch ST7789V SPI LCD, native `240x320`.
- Current orientation: portrait / vertical, `240x320`, `tft.setRotation(0)`.
- Rendering: full-screen 1-bit `TFT_eSprite` framebuffer, pushed to LCD each frame.
- Network: WiFi STA mode, HTTP server on port `8765`.
- Last known ESP IP during testing: `192.168.2.188`.
- Last build/upload: successful.
- Tested endpoints: `/health`, `/cues`, `/launch`.

Last measured PlatformIO size after adding hub modes:

```text
RAM:   15.6%  used 51156 bytes from 327680 bytes
Flash: 61.9%  used 811621 bytes from 1310720 bytes
```

---

## Hardware wiring

This project intentionally uses the safer pinout from the earlier working `esp32_dino_runner` / gaming-station setup. This avoids the problematic ESP32 boot-strapping pins that caused flash/read failures with the first wiring attempt.

### LCD wiring: Waveshare 2-inch ST7789V SPI LCD

| LCD pin | ESP32 pin |
| --- | --- |
| VCC | 3V3 |
| GND | GND |
| DIN / MOSI / SDA | GPIO23 |
| CLK / SCK / SCL | GPIO18 |
| CS | GPIO27 |
| DC / DS / RS | GPIO21 |
| RST / RES | GPIO22 |
| BL / BLK / LED | GPIO25 |

### Passive 5-way joystick wiring

The current joystick module is passive / active-low:

- Joystick `COM` goes to `GND`.
- Each direction/button pin goes to an ESP32 GPIO configured as `INPUT_PULLUP`.
- Pressed state is `LOW`.
- No joystick VCC is needed for the passive module.

| Joystick pin | ESP32 pin | Current use |
| --- | --- | --- |
| COM | GND | common ground |
| UP | GPIO32 | Dino jump, Snake up, Draw up, action button equivalent |
| DWN | GPIO33 | Snake down, Draw down |
| LFT | GPIO26 | Snake left, Draw left |
| RHT | GPIO14 | Snake right, Draw right |
| MID | GPIO13 | action/start/restart, Draw pen toggle |
| SET | GPIO16 | Draw clear |
| RST | GPIO17 | Draw clear |

---

## PlatformIO project structure

```text
esp32_flappy_st7789/
├── platformio.ini
├── README.md
└── src/
    ├── main.cpp
    ├── secrets.h
    ├── main_dino_portrait.cpp.disabled
    └── main_flappy.cpp.disabled
```

### Important files

#### `platformio.ini`

Defines the ESP32 board, Arduino framework, TFT_eSPI dependency, upload speed, monitor speed, and all TFT_eSPI display pins via `build_flags`.

TFT_eSPI is configured only through PlatformIO build flags. The library `User_Setup.h` is not edited.

Current important display flags:

```ini
-DUSER_SETUP_LOADED=1
-DST7789_DRIVER=1
-DTFT_WIDTH=240
-DTFT_HEIGHT=320
-DTFT_MOSI=23
-DTFT_SCLK=18
-DTFT_CS=27
-DTFT_DC=21
-DTFT_RST=22
-DTFT_BL=25
-DTFT_BACKLIGHT_ON=HIGH
-DTOUCH_CS=-1
-DLOAD_GLCD=1
-DSPI_FREQUENCY=40000000
```

#### `src/main.cpp`

Main firmware for the launcher hub. It contains:

- joystick pin setup and debouncing
- TFT + 1-bit sprite setup
- WiFi connection management
- HTTP server setup
- cue parsing
- mode launcher
- Dino game
- Snake game
- Clock screen
- Weather screen
- Drawing canvas
- Chat display screen
- Timer screen

#### `src/secrets.h`

Local WiFi credentials. Do not publish this file.

Expected shape:

```cpp
#pragma once
#define WIFI_SSID "your wifi ssid"
#define WIFI_PASSWORD "your wifi password"
```

#### Backup files

- `src/main_dino_portrait.cpp.disabled` — previous standalone portrait Dino game backup.
- `src/main_flappy.cpp.disabled` — previous standalone Flappy Bird backup.

They are not compiled because only `.cpp` files without the `.disabled` suffix are built.

---

## Build and upload

From the project directory:

```bash
cd /Users/flo/esp32_flappy_st7789
pio run -e esp32dev
```

Upload to the currently detected CP2102 serial adapter:

```bash
pio run -e esp32dev -t upload --upload-port /dev/cu.usbserial-0001
```

List devices if the port changes:

```bash
pio device list
```

Do not leave a blocking monitor open during automated tasks. If logs are needed, use a short timed serial read or PlatformIO monitor manually.

---

## Runtime serial log

On successful boot the ESP prints logs similar to:

```text
sprite ok, free heap=292060, display=240x320
WiFi connecting
HTTP server listening on port 8765
WiFi connected, IP=192.168.2.188
Health: http://192.168.2.188:8765/health
Cues:   http://192.168.2.188:8765/cues
```

When a launch request arrives, it logs:

```text
HTTP /launch from <remote-ip> body=<json> cue=<cue>
launched cue=<cue>
```

---

## HTTP API

The ESP32 listens on fixed port:

```text
8765
```

Base URL, using the last known IP:

```text
http://192.168.2.188:8765
```

The IP is assigned by WiFi/DHCP, so check serial logs after reboot if the URL stops working.

### `GET /health`

Health check endpoint.

```bash
curl http://192.168.2.188:8765/health
```

Response:

```json
{"ok":true,"device":"esp-lcd-joystick"}
```

### `GET /cues`

Returns supported cue names.

```bash
curl http://192.168.2.188:8765/cues
```

Response:

```json
{"ok":true,"cues":["dino","snake","clock","weather","draw","chat","timer"]}
```

### `POST /launch`

Launches a mode/game. Request body is JSON with at least a `cue` string.

Generic form:

```bash
curl -X POST http://192.168.2.188:8765/launch \
  -H 'Content-Type: application/json' \
  -d '{"cue":"dino"}'
```

Success response:

```json
{"ok":true,"launched":"dino"}
```

Unknown cue response:

```json
{"ok":false,"error":"unknown cue"}
```

---

## Supported cues and behavior

### 1. Dino

Payload:

```json
{"cue":"dino"}
```

Behavior:

- Starts the portrait Dino runner.
- Dino runs left-to-right against incoming obstacles.
- `UP` or `MID` jumps.
- Collision causes game over.
- `UP` or `MID` restarts after game over.
- HTTP server remains alive while game runs.

Test:

```bash
curl -X POST http://192.168.2.188:8765/launch \
  -H 'Content-Type: application/json' \
  -d '{"cue":"dino"}'
```

### 2. Snake

Payload:

```json
{"cue":"snake"}
```

Behavior:

- Starts a minimal monochrome joystick-controlled Snake game.
- Joystick directions control the snake.
- Snake eats food and grows.
- Wall or self collision causes game over.
- `MID` restarts after game over.
- HTTP server remains alive while game runs.

Test:

```bash
curl -X POST http://192.168.2.188:8765/launch \
  -H 'Content-Type: application/json' \
  -d '{"cue":"snake"}'
```

### 3. Clock

Payload example from TinyPi/cyberdeck:

```json
{"cue":"clock","epoch":1783597369,"time":"11:42","date":"2026-07-09","timezone":"GMT"}
```

Behavior:

- Shows a clean portrait clock screen.
- Uses the provided `time` string when available.
- Uses `date` and `timezone` for labels.
- Locally increments seconds using `millis()` after launch.
- If `time` is missing but `epoch` exists, it derives time-of-day from the epoch modulo 86400.
- It does not currently perform full timezone conversion; it trusts TinyPi-provided display fields.

Test:

```bash
curl -X POST http://192.168.2.188:8765/launch \
  -H 'Content-Type: application/json' \
  -d '{"cue":"clock","epoch":1783597369,"time":"11:42","date":"2026-07-09","timezone":"GMT"}'
```

### 4. Weather

Payload example:

```json
{"cue":"weather","location":"Berlin","summary":"Berlin: ☁️ +18°C, cloudy, wind 10 km/h."}
```

Behavior:

- Shows a weather screen.
- Prefers the provided `summary` string.
- If `summary` is missing, shows `<location>: weather unavailable`.
- If both summary and location are missing, shows `weather unavailable`.
- The current renderer uses TFT_eSPI GLCD font and a 1-bit sprite, so non-ASCII characters / emoji may be simplified or replaced with spaces by the firmware display sanitizer.

Test:

```bash
curl -X POST http://192.168.2.188:8765/launch \
  -H 'Content-Type: application/json' \
  -d '{"cue":"weather","location":"Berlin","summary":"Berlin: cloudy, +18C, wind 10 km/h."}'
```

### 5. Draw

Payload:

```json
{"cue":"draw"}
```

Behavior:

- Starts a joystick drawing canvas.
- Joystick moves a cursor on a low-resolution grid.
- Pen starts enabled.
- `MID` toggles pen on/off.
- `SET` or `RST` clears the drawing canvas.
- HTTP server remains alive.

Controls:

| Control | Action |
| --- | --- |
| UP/DWN/LFT/RHT | move cursor |
| MID | toggle pen on/off |
| SET | clear canvas |
| RST | clear canvas |

Test:

```bash
curl -X POST http://192.168.2.188:8765/launch \
  -H 'Content-Type: application/json' \
  -d '{"cue":"draw"}'
```

### 6. Chat

Payload variants:

```json
{"cue":"chat"}
```

or:

```json
{"cue":"chat","prompt":"hello","answer":"Hello!"}
```

Behavior:

- Shows a chat display screen.
- If `answer` exists, displays it in large wrapped text.
- If `prompt` exists, displays it near the top as `Q: ...`.
- If no answer exists, shows a waiting screen.
- Current renderer is simple and optimized for short text snippets.

Test:

```bash
curl -X POST http://192.168.2.188:8765/launch \
  -H 'Content-Type: application/json' \
  -d '{"cue":"chat","prompt":"hello","answer":"Hello!"}'
```

### 7. Timer

Payload:

```json
{"cue":"timer","seconds":300,"label":"tea"}
```

Behavior:

- Starts a countdown timer.
- Shows label and remaining `MM:SS` time.
- When the timer reaches zero, the display flashes/inverts.
- No buzzer is currently wired or used.
- HTTP server remains alive during countdown.

Test with a short 5-second timer:

```bash
curl -X POST http://192.168.2.188:8765/launch \
  -H 'Content-Type: application/json' \
  -d '{"cue":"timer","seconds":5,"label":"tea"}'
```

---

## TinyPi integration

TinyPi only needs to send HTTP requests to the ESP32 on the same LAN.

Use the ESP IP reported in serial logs. Last tested:

```text
192.168.2.188
```

Example from TinyPi:

```bash
curl -X POST http://192.168.2.188:8765/launch \
  -H 'Content-Type: application/json' \
  -d '{"cue":"dino"}'
```

Recommended TinyPi-side sequence:

1. Call `/health` to confirm the ESP is reachable.
2. Send `POST /launch` with the cue payload.
3. Optionally call `/cues` if the cyberdeck wants to discover supported modes.

---

## Implementation notes

### Rendering model

The project uses one full-screen 1-bit sprite:

```cpp
spr.setColorDepth(1);
spr.createSprite(240, 320);
spr.setBitmapColor(TFT_BLACK, TFT_WHITE);
```

Each frame:

1. Clear sprite to white.
2. Draw black UI/game elements into the sprite.
3. Push the whole sprite to the LCD with `spr.pushSprite(0, 0)`.

This avoids flicker and direct partial LCD drawing during gameplay/modes.

### HTTP server model

The firmware uses Arduino `WebServer`:

```cpp
WebServer server(8765);
```

`server.handleClient()` is called continuously in `loop()` through `serviceNetwork()`, even while a game or utility screen is active. This keeps the launcher responsive to new cues after a mode has already launched.

### JSON parsing

The firmware currently uses a small hand-written parser for simple JSON payloads. It supports the specific flat payloads used by TinyPi:

- string values such as `cue`, `time`, `date`, `timezone`, `location`, `summary`, `prompt`, `answer`, `label`
- integer values such as `epoch`, `seconds`

It is not a general-purpose JSON parser. If payloads become more complex, add ArduinoJson or improve parsing.

### Text limitations

The current display setup uses TFT_eSPI GLCD font on a monochrome sprite. Unicode/emoji strings from TinyPi may not render as expected. The code sanitizes text down to readable ASCII-ish content. Weather summaries should preferably be plain ASCII for best display quality, e.g. `Berlin: cloudy, +18C, wind 10 km/h`.

---

## Troubleshooting

### ESP uploads but HTTP does not respond

1. Check serial logs for WiFi IP:

   ```text
   WiFi connected, IP=...
   ```

2. Confirm Mac/TinyPi is on the same LAN.
3. Test:

   ```bash
   curl http://ESP_IP:8765/health
   ```

4. If IP changed, update TinyPi/cyberdeck target URL.

### Display is blank

Check LCD wiring, especially:

```text
BL -> GPIO25
CS -> GPIO27
DC -> GPIO21
RST -> GPIO22
DIN -> GPIO23
CLK -> GPIO18
VCC -> 3V3
GND -> GND
```

The LCD test previously worked with this exact wiring.

### ESP fails to boot or shows flash read errors

The first wiring attempt used boot-strapping pins like GPIO2, GPIO4, GPIO5, GPIO15 for TFT control and caused failures on one board. Current wiring intentionally avoids that set for LCD control.

If boot errors return:

- disconnect recently added wires
- power-cycle the ESP32
- verify no external module is pulling boot strap pins into a bad state
- use the known-good LCD pinout above

### Joystick does not respond

Verify passive joystick wiring:

```text
COM -> GND
UP  -> GPIO32
DWN -> GPIO33
LFT -> GPIO26
RHT -> GPIO14
MID -> GPIO13
SET -> GPIO16
RST -> GPIO17
```

The code uses `INPUT_PULLUP`; pressed must read `LOW`.

### Weather emoji/degree symbol looks wrong

Expected with the current GLCD font/ASCII sanitizer. Send plain text summaries from TinyPi for best results:

```json
{"cue":"weather","location":"Berlin","summary":"Berlin: cloudy, +18C, wind 10 km/h."}
```

---

## Known limitations / future improvements

- IP is DHCP-assigned; consider a router DHCP reservation for the ESP32 MAC or a static IP.
- JSON parsing is intentionally minimal; add ArduinoJson if cue payloads grow.
- Weather/chat rendering is basic and best with short ASCII text.
- Timer completion only flashes/inverts the screen; no buzzer output is currently implemented.
- Clock uses TinyPi-provided `time`, `date`, and `timezone`; it does not synchronize NTP itself.
- WiFi credentials are stored in `src/secrets.h`; keep it private.
- Some render paths use Arduino `String`; acceptable for this prototype, but fixed buffers would be more robust for long-running production use.

---

## Quick test matrix

Replace `192.168.2.188` with the current ESP IP if needed.

```bash
ESP=192.168.2.188

curl http://$ESP:8765/health
curl http://$ESP:8765/cues

curl -X POST http://$ESP:8765/launch -H 'Content-Type: application/json' -d '{"cue":"dino"}'
curl -X POST http://$ESP:8765/launch -H 'Content-Type: application/json' -d '{"cue":"snake"}'
curl -X POST http://$ESP:8765/launch -H 'Content-Type: application/json' -d '{"cue":"clock","epoch":1783597369,"time":"11:42","date":"2026-07-09","timezone":"GMT"}'
curl -X POST http://$ESP:8765/launch -H 'Content-Type: application/json' -d '{"cue":"weather","location":"Berlin","summary":"Berlin: cloudy, +18C, wind 10 km/h."}'
curl -X POST http://$ESP:8765/launch -H 'Content-Type: application/json' -d '{"cue":"draw"}'
curl -X POST http://$ESP:8765/launch -H 'Content-Type: application/json' -d '{"cue":"chat","prompt":"hello","answer":"Hello!"}'
curl -X POST http://$ESP:8765/launch -H 'Content-Type: application/json' -d '{"cue":"timer","seconds":5,"label":"tea"}'

# Expected error:
curl -X POST http://$ESP:8765/launch -H 'Content-Type: application/json' -d '{"cue":"pong"}'
```

---

## One-line summary

This project turns an ESP32 + Waveshare ST7789 LCD + passive joystick into a tiny WiFi-controlled launcher hub: TinyPi sends simple HTTP cue JSON, and the ESP32 switches locally between Dino, Snake, Clock, Weather, Drawing, Chat, and Timer screens while keeping the HTTP API alive.
