# TinyPi Cyberdeck + ESP32 LCD Joystick Launcher Hub

_Last updated: 2026-07-09_

This document is the detailed project record for the two-device cyberdeck/game-console setup built during this session. It covers the Raspberry Pi Zero / TinyPi side, the ESP32 ST7789 LCD joystick side, the local LLM integration, the Bluetooth keyboard flow, the LAN HTTP command bridge, the cue-word launcher hub, current paths, current IPs, APIs, troubleshooting, and extension notes.

> Security note: this document intentionally does **not** include WiFi passwords, API keys, or contents of `src/secrets.h`. That file exists in the ESP project and must be treated as private.

---

## 1. High-level summary

The project is a small two-screen/two-device launcher and interaction system:

1. **TinyPi cyberdeck**
   - Raspberry Pi Zero-class board named `tinypi`.
   - Runs Debian 13 / Raspberry Pi OS derivative.
   - Has a small SPI TFT framebuffer display.
   - Uses a Bluetooth keyboard for input.
   - Runs a local SmolLM2 135M instruct model through `llama-cli`.
   - Parses typed cue words such as `dino`, `snake`, `clock`, `weather`, `draw`, `chat`, and `timer`.
   - Routes recognized cue words to the ESP32 over WiFi.
   - Sends non-cue text to the local LLM and displays a one-sentence response.

2. **ESP32 LCD joystick console**
   - Project path on Mac: `/Users/flo/esp32_flappy_st7789`
   - ESP32 dev board with portrait ST7789 LCD, 240x320.
   - Passive joystick/button input.
   - Runs an HTTP server on port `8765`.
   - Receives launch commands from TinyPi.
   - Displays/plays launched modes:
     - Dino game
     - Snake game
     - Clock
     - Weather
     - Draw canvas
     - Chat display
     - Timer countdown

The system behaves like a tiny cue-word launcher hub: the TinyPi is the keyboard/LLM/router, and the ESP32 is the visual game/action station.

---

## 2. Current known network state

### TinyPi

- Host alias: `tinypi`
- Hostname: `tinypi`
- User: `tinypi`
- Current WiFi IPv4 observed: `192.168.2.222`
- SSH alias works from Mac:

```bash
ssh tinypi
```

### ESP32 LCD joystick console

- Current IPv4: `192.168.2.188`
- HTTP port: `8765`
- Configured on TinyPi in:

```text
/home/tinypi/esp_bridge_url
/tmp/esp_bridge_url
```

Both currently contain:

```text
http://192.168.2.188:8765
```

### Verified ESP endpoints

From both Mac and TinyPi:

```bash
curl http://192.168.2.188:8765/health
```

Expected response:

```json
{"ok":true,"device":"esp-lcd-joystick"}
```

Supported cues endpoint:

```bash
curl http://192.168.2.188:8765/cues
```

Expected response:

```json
{"ok":true,"cues":["dino","snake","clock","weather","draw","chat","timer"]}
```

---

## 3. Current TinyPi system details

Observed state on `tinypi`:

```text
Hostname: tinypi
OS: Debian GNU/Linux 13 (trixie)
Kernel: Linux 6.12.75+rpt-rpi-v8 aarch64
Timezone: Etc/Greenwich (GMT, +0000)
NTP: active
```

The timezone was set to Greenwich/GMT.

### TinyPi display

Framebuffer display:

```text
/dev/fb1
/sys/class/graphics/fb1/name = fb_ili9340
/sys/class/graphics/fb1/virtual_size = 320,240
```

Important boot/display config:

```text
/boot/firmware/config.txt
  dtoverlay=tft9341:rotate=90
  dtoverlay=dwc2,dr_mode=host
```

The screen was flipped 180 degrees from the original orientation by changing the TFT overlay rotation from `270` to `90`.

### TinyPi Bluetooth keyboard

Known paired keyboard:

```text
Bluetooth Keyboard
Current observed device identity: D9:EB:43:BE:33:F5
```

When working, Linux exposes it as an input event device similar to:

```text
N: Name="Bluetooth Keyboard"
H: Handlers=sysrq kbd leds event3
```

The TinyPi app reads `/dev/input/event*` directly and automatically rescans/reopens the keyboard event device after reconnects.

---

## 4. TinyPi services

### Main display/input/LLM/bridge service

Service name:

```text
usb-keyboard-display.service
```

Systemd unit:

```ini
[Unit]
Description=Bluetooth keyboard display typepad
After=multi-user.target bluetooth.service
Wants=bluetooth.service

[Service]
Type=simple
User=tinypi
WorkingDirectory=/home/tinypi
Environment=SDL_VIDEODRIVER=dummy
ExecStart=/usr/bin/python3 /home/tinypi/usb_keyboard_display.py
Restart=always
RestartSec=2
TimeoutStopSec=3
KillMode=mixed

[Install]
WantedBy=multi-user.target
```

Useful commands:

```bash
ssh tinypi 'systemctl status usb-keyboard-display.service --no-pager'
ssh tinypi 'sudo systemctl restart usb-keyboard-display.service'
ssh tinypi 'journalctl -u usb-keyboard-display.service -n 100 --no-pager'
```

The service is enabled and active.

### Bluetooth pairing agent service

User service:

```text
bt-keyboard-agent.service
```

Unit:

```ini
[Unit]
Description=Bluetooth keyboard pairing agent
After=default.target

[Service]
Type=simple
ExecStart=/home/tinypi/chatbot/bt_keyboard_agent.sh
Restart=always
RestartSec=2

[Install]
WantedBy=default.target
```

The helper script keeps a `bluetoothctl --agent=KeyboardDisplay` process alive so pairing/PIN prompts work.

Useful commands:

```bash
ssh tinypi 'systemctl --user status bt-keyboard-agent.service --no-pager'
ssh tinypi 'systemctl --user restart bt-keyboard-agent.service'
```

### Bluetooth repair/pairing helper

Path:

```text
/home/tinypi/bt_keyboard_pair_wait_input.py
```

Purpose:

- Removes stale Bluetooth Keyboard pairings.
- Starts a controlled `bluetoothctl --agent=KeyboardDisplay` session.
- Scans for a keyboard in pairing mode.
- Pairs/trusts/connects it.
- Waits until a real Linux input device appears.
- Writes user-visible status to `/tmp/bt_keyboard_status`.

Useful manual invocation:

```bash
ssh tinypi 'systemctl --user stop bt-keyboard-agent.service; BT_PAIR_TIMEOUT=300 setsid /usr/bin/python3 /home/tinypi/bt_keyboard_pair_wait_input.py </dev/null >/tmp/bt_keyboard_pair_wait_input.nohup 2>&1 &'
```

After pairing is complete, restart the agent:

```bash
ssh tinypi 'systemctl --user start bt-keyboard-agent.service'
```

---

## 5. TinyPi main application

Main script:

```text
/home/tinypi/usb_keyboard_display.py
```

Despite the historical name, it now handles:

- Bluetooth keyboard input
- TFT framebuffer drawing
- One-line UI/status
- Cue-word parsing
- Local LLM prompting
- ESP bridge discovery
- ESP launch requests
- Bluetooth reconnect attempts

### TinyPi UI behavior

The screen is high-contrast:

- White background
- Black text
- Bigger main text
- Thin top status area
- Only the Bluetooth/status line is shown above the typed/answer text

Typical top line:

```text
BT keyboard ready. Type now.
```

Typing behavior:

1. Type text on the Bluetooth keyboard.
2. Press Enter.
3. If the text is a recognized cue command, TinyPi sends it to the ESP bridge.
4. If it is not a recognized cue command, TinyPi sends it to the local LLM.
5. The display shows either a launch confirmation or a one-sentence LLM answer.

Escape clears the screen/input.

Backspace edits typed input, or clears the answer if no input is active.

### TinyPi input handling details

The Python app uses raw Linux input events:

- Reads `/dev/input/event*`
- Uses `select` for non-blocking input
- Tracks shift/caps/ctrl modifiers
- Maps evdev keycodes to characters
- Handles stale Bluetooth HID devices by dropping deleted fds and reopening new event nodes

This was needed because Bluetooth keyboards can disconnect/reconnect with the same event path but a deleted old file descriptor.

### TinyPi framebuffer handling

The app draws with `pygame` into a software surface, then writes RGB565 bytes directly to the Linux framebuffer.

Important environment:

```text
SDL_VIDEODRIVER=dummy
```

The framebuffer is chosen by scanning `/sys/class/graphics/fb*` and preferring names starting with `fb_` or `fbtft`.

---

## 6. Local LLM on TinyPi

The TinyPi has a local LLM already installed.

### Model

```text
/home/tinypi/chatbot/models/SmolLM2-135M-Instruct-Q2_K.gguf
```

Details:

```text
Model family: SmolLM2
Provider/company: Hugging Face
Size: 135M parameters
Quantization: Q2_K
File size: about 85 MB
```

### Runner

```text
/home/tinypi/chatbot/bin/llama-cli
```

Observed version:

```text
version: 9886 (20a04b220)
built with GNU 14.2.0 for Linux aarch64
```

### How TinyPi calls the model

TinyPi calls `llama-cli` through Python `subprocess.run()` with roughly:

```bash
LD_LIBRARY_PATH=/home/tinypi/chatbot/bin \
/home/tinypi/chatbot/bin/llama-cli \
  -m /home/tinypi/chatbot/models/SmolLM2-135M-Instruct-Q2_K.gguf \
  -t 2 -tb 2 \
  -c 256 -n 48 \
  --temp 0.6 --top-k 30 --top-p 0.9 \
  --repeat-penalty 1.08 \
  --log-disable --no-display-prompt --no-perf --no-warmup \
  -st --simple-io \
  -sys "You are TinyPi... Answer with exactly one short, helpful sentence under 20 words." \
  -p "user question"
```

The app then strips banners/logging/noise and extracts a single sentence for display.

### LLM fallback rule

If typed text is **not** recognized as a cue command, it goes to the local LLM.

Examples:

```text
what is a transistor?
why is the sky blue?
tell me a tiny joke
```

TinyPi displays only one sentence.

---

## 7. Cue-word launcher hub on TinyPi

TinyPi recognizes cue commands before invoking the LLM.

### Supported cue words and aliases

Canonical cues:

```text
dino
snake
clock
weather
draw
chat
timer
```

Aliases implemented on TinyPi:

```text
dino:    dino, /dino, runner, trex
snake:   snake, /snake
clock:   clock, /clock, time
weather: weather, /weather
draw:    draw, /draw, paint, sketch
chat:    chat, /chat, talk
timer:   timer, /timer, countdown
```

### Cue command examples

```text
dino
snake
clock
time
weather
weather Berlin
weather Greenwich
draw
paint
chat hello tiny screen
timer
timer 5m
timer 90s tea
timer 1:30
timer 2 minutes coffee
```

### Payloads sent from TinyPi to ESP

TinyPi sends HTTP POST requests to:

```text
http://192.168.2.188:8765/launch
```

with JSON payloads.

#### Dino

Typed:

```text
dino
```

Payload:

```json
{"cue":"dino"}
```

#### Snake

Typed:

```text
snake
```

Payload:

```json
{"cue":"snake"}
```

#### Clock

Typed:

```text
clock
```

Payload shape:

```json
{
  "cue":"clock",
  "epoch":1783597369,
  "time":"11:42",
  "date":"2026-07-09",
  "timezone":"GMT"
}
```

TinyPi uses its local time and date.

#### Weather

Typed:

```text
weather Berlin
```

Payload shape:

```json
{
  "cue":"weather",
  "location":"Berlin",
  "summary":"Berlin: cloudy, +18°C, wind 10 km/h."
}
```

Implementation detail:

- TinyPi optionally fetches a compact weather summary from `https://wttr.in/`.
- The ESP does not need internet access for weather if TinyPi provides `summary`.
- If weather fetch fails, TinyPi can still send `location`; ESP displays fallback text.

#### Draw

Typed:

```text
draw
```

Payload:

```json
{"cue":"draw"}
```

#### Chat

Typed:

```text
chat hello
```

Payload shape:

```json
{
  "cue":"chat",
  "prompt":"hello",
  "answer":"Hello!"
}
```

Implementation detail:

- If `chat` includes a prompt, TinyPi asks the local LLM first.
- TinyPi sends both the prompt and one-sentence answer to ESP.
- TinyPi also displays the answer locally.

Typed:

```text
chat
```

Payload:

```json
{"cue":"chat"}
```

This simply opens the ESP chat display screen.

#### Timer

Typed:

```text
timer 90s tea
```

Payload:

```json
{
  "cue":"timer",
  "seconds":90,
  "label":"tea"
}
```

Timer parser details:

- Bare numbers are treated as minutes.
- `90s` means 90 seconds.
- `5m` means 5 minutes.
- `2h` means 2 hours.
- `1:30` means 1 minute 30 seconds.
- Max duration is capped at 24 hours.
- Default timer is 5 minutes.

Examples:

```text
timer        -> 300 seconds, label "5 minutes"
timer 5      -> 300 seconds
timer 5m     -> 300 seconds
timer 90s    -> 90 seconds
timer 1:30   -> 90 seconds
timer 2h     -> 7200 seconds
```

---

## 8. TinyPi bridge discovery

TinyPi can find the ESP bridge in several ways.

### Primary explicit config

Best/current method:

```bash
ssh tinypi 'echo http://192.168.2.188:8765 > ~/esp_bridge_url'
```

The app checks:

```text
$ESP_BRIDGE_URL
/home/tinypi/esp_bridge_url
/home/tinypi/esp_bridge.txt
/tmp/esp_bridge_url
```

### Hostname candidates

If explicit files are missing, it tries:

```text
http://esp-lcd-joystick.local:8765
http://lcd-joystick.local:8765
http://esp32.local:8765
http://esp.local:8765
```

### Local subnet scan

If config and mDNS names fail, TinyPi scans small local IPv4 subnets, checking `/health` on port `8765`.

Scan is limited to networks with at most 512 addresses to avoid overly broad scans.

### Cache

When discovered, bridge URL is cached in:

```text
/tmp/esp_bridge_url
```

---

## 9. ESP32 project details

Local Mac project path:

```text
/Users/flo/esp32_flappy_st7789
```

Primary source:

```text
/Users/flo/esp32_flappy_st7789/src/main.cpp
```

PlatformIO config:

```text
/Users/flo/esp32_flappy_st7789/platformio.ini
```

Secrets file:

```text
/Users/flo/esp32_flappy_st7789/src/secrets.h
```

Do not publish `src/secrets.h`; it contains private credentials.

### PlatformIO environment

```ini
[env:esp32dev]
platform = espressif32
board = esp32dev
framework = arduino
lib_deps = bodmer/TFT_eSPI
monitor_speed = 115200
upload_speed = 115200
```

### TFT build flags

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

The display is portrait 240x320.

### ESP hardware pins

Joystick/buttons are active-low using pullups:

```cpp
JOY_UP  = 32
JOY_DWN = 33
JOY_LFT = 26
JOY_RHT = 14
JOY_MID = 13
JOY_SET = 16
JOY_RST = 17
```

Comment in source:

```cpp
// Passive joystick: COM -> GND, pressed == LOW
```

### ESP graphics model

The ESP uses TFT_eSPI plus a 1-bit full-screen sprite:

```cpp
TFT_eSPI tft;
TFT_eSprite spr(&tft);

constexpr int16_t SCREEN_W = 240;
constexpr int16_t SCREEN_H = 320;
constexpr uint16_t BG = 0;
constexpr uint16_t FG = 1;
```

The sprite is configured as black-on-white:

```cpp
spr.setColorDepth(1);
spr.createSprite(SCREEN_W, SCREEN_H);
spr.setBitmapColor(TFT_BLACK, TFT_WHITE);
```

This saves RAM and keeps the visual style simple and readable.

---

## 10. ESP HTTP API

ESP server:

```cpp
WebServer server(8765);
```

### GET `/health`

Request:

```bash
curl http://192.168.2.188:8765/health
```

Response:

```json
{"ok":true,"device":"esp-lcd-joystick"}
```

### GET `/cues`

Request:

```bash
curl http://192.168.2.188:8765/cues
```

Response:

```json
{"ok":true,"cues":["dino","snake","clock","weather","draw","chat","timer"]}
```

### POST `/launch`

Request pattern:

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

### Current supported launch payloads

```bash
curl -X POST http://192.168.2.188:8765/launch \
  -H 'Content-Type: application/json' \
  -d '{"cue":"dino"}'

curl -X POST http://192.168.2.188:8765/launch \
  -H 'Content-Type: application/json' \
  -d '{"cue":"snake"}'

curl -X POST http://192.168.2.188:8765/launch \
  -H 'Content-Type: application/json' \
  -d '{"cue":"clock","time":"12:34","date":"2026-07-09","timezone":"GMT","epoch":1783600440}'

curl -X POST http://192.168.2.188:8765/launch \
  -H 'Content-Type: application/json' \
  -d '{"cue":"weather","location":"Greenwich","summary":"Greenwich: cloudy, +18C."}'

curl -X POST http://192.168.2.188:8765/launch \
  -H 'Content-Type: application/json' \
  -d '{"cue":"draw"}'

curl -X POST http://192.168.2.188:8765/launch \
  -H 'Content-Type: application/json' \
  -d '{"cue":"chat","prompt":"hello","answer":"Hello!"}'

curl -X POST http://192.168.2.188:8765/launch \
  -H 'Content-Type: application/json' \
  -d '{"cue":"timer","seconds":90,"label":"tea"}'
```

---

## 11. ESP modes

ESP mode enum:

```cpp
enum AppMode : uint8_t {
  MODE_DINO,
  MODE_SNAKE,
  MODE_CLOCK,
  MODE_WEATHER,
  MODE_DRAW,
  MODE_CHAT,
  MODE_TIMER
};
```

Game run state enum:

```cpp
enum RunState : uint8_t {
  READY,
  PLAYING,
  GAME_OVER
};
```

### Dino mode

Cue:

```json
{"cue":"dino"}
```

Behavior:

- Launches Dino runner immediately.
- Resets score and obstacles.
- `JOY_UP` or `JOY_MID` jumps.
- Collision sets game over.
- Press jump/action again after game over to restart.

Important implementation details:

- Dino at fixed x position.
- Obstacles scroll left.
- Speed increases gradually with score.
- Ground line and score drawn on 1-bit sprite.

### Snake mode

Cue:

```json
{"cue":"snake"}
```

Behavior:

- Launches Snake immediately.
- Joystick controls direction.
- Food spawns randomly.
- Wall/self collision ends game.
- `JOY_MID` restarts after game over.

Grid details:

```cpp
SNAKE_COLS = 24
SNAKE_ROWS = 22
SNAKE_CELL = 10
SNAKE_Y0 = 52
```

### Clock mode

Cue:

```json
{"cue":"clock","time":"11:42","date":"2026-07-09","timezone":"GMT","epoch":1783597369}
```

Behavior:

- Displays a clock screen.
- Uses provided time/date/timezone from TinyPi.
- Locally advances seconds using `millis()`.
- No internet or RTC required on ESP.

### Weather mode

Cue:

```json
{"cue":"weather","location":"Berlin","summary":"Berlin: cloudy, +18C."}
```

Behavior:

- Displays weather summary text.
- Prefers `summary` from TinyPi.
- If no summary, displays location plus `weather unavailable`.

TinyPi handles weather fetching, so the ESP stays simple.

### Draw mode

Cue:

```json
{"cue":"draw"}
```

Behavior:

- Opens a joystick drawing canvas.
- Cursor starts in the center.
- Pen defaults to on.
- Joystick moves cursor.
- `JOY_MID` toggles pen on/off.
- `JOY_SET` or `JOY_RST` clears the canvas.

Grid details:

```cpp
DRAW_CELL = 4
DRAW_COLS = SCREEN_W / DRAW_CELL = 60
DRAW_ROWS = 66
DRAW_Y0 = 44
```

### Chat mode

Cue without text:

```json
{"cue":"chat"}
```

Cue with TinyPi LLM output:

```json
{"cue":"chat","prompt":"hello","answer":"Hello!"}
```

Behavior:

- Displays chat header.
- Shows prompt as `Q: ...` if supplied.
- Displays one-sentence answer in wrapped large text.
- If no answer exists, shows waiting placeholder.

### Timer mode

Cue:

```json
{"cue":"timer","seconds":90,"label":"tea"}
```

Behavior:

- Starts a countdown from `seconds`.
- Displays label and remaining `MM:SS`.
- When done, flashes/inverts the display every 250ms.

---

## 12. ESP main loop architecture

ESP loop structure:

1. `serviceNetwork()`
   - Keeps WiFi/server alive.
   - Calls `server.handleClient()` whenever WiFi is connected.
   - Retries WiFi every 15 seconds if disconnected.

2. Debounce joystick/button inputs.

3. Update active mode logic:
   - Draw mode updates cursor frequently.
   - Dino updates physics/collision.
   - Snake updates grid movement.
   - Clock/weather/chat/timer mostly render-only.

4. Render at about 30 FPS:

```cpp
if (now - lastFrameMs < 33) return;
lastFrameMs = now;
render();
```

This keeps the HTTP server alive while games or modes run.

---

## 13. Build, upload, and monitor

From the ESP project directory:

```bash
cd /Users/flo/esp32_flappy_st7789
```

Build:

```bash
pio run
```

Upload:

```bash
pio run -t upload
```

Monitor:

```bash
pio device monitor
```

Common all-in-one:

```bash
pio run -t upload && pio device monitor
```

Observed successful build/upload status from the ESP agent:

```text
Upload succeeded
RAM: 14.4%
Flash: 61.4%
LCD stays portrait 240x320
HTTP server keeps running while game loop runs
```

---

## 14. End-to-end operating procedure

### Normal startup

1. Power ESP32 LCD joystick console.
2. Power TinyPi.
3. Wait for TinyPi display to show:

```text
BT keyboard ready. Type now.
```

4. Type commands on Bluetooth keyboard.

### Use cue launcher

Type one of:

```text
dino
snake
clock
weather Berlin
draw
chat hello there
timer 90s tea
```

Then press Enter.

### Use local LLM

Type any non-cue text:

```text
what is ohm's law?
```

Press Enter.

TinyPi shows a one-sentence local model answer.

---

## 15. Test commands

### From Mac

```bash
curl http://192.168.2.188:8765/health
curl http://192.168.2.188:8765/cues
```

Launch each mode:

```bash
curl -X POST http://192.168.2.188:8765/launch -H 'Content-Type: application/json' -d '{"cue":"dino"}'
curl -X POST http://192.168.2.188:8765/launch -H 'Content-Type: application/json' -d '{"cue":"snake"}'
curl -X POST http://192.168.2.188:8765/launch -H 'Content-Type: application/json' -d '{"cue":"clock","time":"12:34","date":"2026-07-09","timezone":"GMT","epoch":1783600440}'
curl -X POST http://192.168.2.188:8765/launch -H 'Content-Type: application/json' -d '{"cue":"weather","location":"Greenwich","summary":"Greenwich: cloudy, +18C."}'
curl -X POST http://192.168.2.188:8765/launch -H 'Content-Type: application/json' -d '{"cue":"draw"}'
curl -X POST http://192.168.2.188:8765/launch -H 'Content-Type: application/json' -d '{"cue":"chat","prompt":"hello","answer":"Hello!"}'
curl -X POST http://192.168.2.188:8765/launch -H 'Content-Type: application/json' -d '{"cue":"timer","seconds":90,"label":"tea"}'
```

### From TinyPi

```bash
ssh tinypi 'curl -sS http://192.168.2.188:8765/health; echo'
ssh tinypi 'curl -sS http://192.168.2.188:8765/cues; echo'
```

Launch Dino from TinyPi:

```bash
ssh tinypi 'curl -sS -X POST http://192.168.2.188:8765/launch -H "Content-Type: application/json" -d "{\"cue\":\"dino\"}"; echo'
```

Test TinyPi local LLM directly:

```bash
ssh tinypi 'cd /home/tinypi && python3 - <<"PY"
import importlib.util
spec = importlib.util.spec_from_file_location("ukd", "/home/tinypi/usb_keyboard_display.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
print(mod.ask_local_model("Say hello"))
PY'
```

Expected example output:

```text
Hello!
```

---

## 16. Troubleshooting

### TinyPi says keyboard ready but typing does nothing

Check if Linux sees a Bluetooth Keyboard event device:

```bash
ssh tinypi 'cat /proc/bus/input/devices | awk '\''/^N: Name=/{name=$0} /^H: Handlers=/{print name " " $0}'\'''
```

Expected:

```text
N: Name="Bluetooth Keyboard" H: Handlers=sysrq kbd leds event3
```

Check if the TinyPi app has opened the event device:

```bash
ssh tinypi 'pid=$(systemctl show -p MainPID --value usb-keyboard-display.service); ls -l /proc/$pid/fd | grep /dev/input || true'
```

Restart display app:

```bash
ssh tinypi 'sudo systemctl restart usb-keyboard-display.service'
```

If the keyboard is not listed, re-pair:

```bash
ssh tinypi 'systemctl --user stop bt-keyboard-agent.service; BT_PAIR_TIMEOUT=300 setsid /usr/bin/python3 /home/tinypi/bt_keyboard_pair_wait_input.py </dev/null >/tmp/bt_keyboard_pair_wait_input.nohup 2>&1 &'
```

Put the keyboard into pairing mode. After it works:

```bash
ssh tinypi 'systemctl --user start bt-keyboard-agent.service'
```

### ESP bridge not found

Explicitly set the bridge URL on TinyPi:

```bash
ssh tinypi 'echo http://192.168.2.188:8765 > ~/esp_bridge_url; echo http://192.168.2.188:8765 > /tmp/esp_bridge_url'
```

Then test:

```bash
ssh tinypi 'curl -sS http://192.168.2.188:8765/health; echo'
```

### ESP IP changed

Check router/DHCP or use serial monitor. ESP prints:

```text
WiFi connected, IP=...
Health: http://...:8765/health
Cues:   http://...:8765/cues
```

Update TinyPi:

```bash
ssh tinypi 'echo http://NEW_IP:8765 > ~/esp_bridge_url'
```

### ESP server responds but launch does nothing

Check launch response:

```bash
curl -v -X POST http://192.168.2.188:8765/launch \
  -H 'Content-Type: application/json' \
  -d '{"cue":"dino"}'
```

Expected:

```json
{"ok":true,"launched":"dino"}
```

If unknown cue:

```json
{"ok":false,"error":"unknown cue"}
```

Then confirm cue string exactly matches supported names.

### Weather does not show live data

TinyPi fetches weather summaries via `wttr.in`. If TinyPi lacks internet, the ESP still opens weather mode but may display a fallback.

Test TinyPi internet/weather:

```bash
ssh tinypi 'python3 - <<"PY"
import urllib.request
print(urllib.request.urlopen("https://wttr.in/Greenwich?format=%l:+%c+%t,+%C,+wind+%w", timeout=6).read().decode())
PY'
```

### Local LLM is slow

Expected: small model, small Pi, but still can take several seconds.

The app displays:

```text
thinking...
```

The model timeout is 120 seconds.

### TinyPi display orientation wrong

Current relevant config:

```text
/boot/firmware/config.txt
dtoverlay=tft9341:rotate=90
```

Changing it requires sudo and reboot.

### TinyPi screen blank or wrong framebuffer

Check framebuffer:

```bash
ssh tinypi 'ls -l /dev/fb*; for f in /sys/class/graphics/fb*/name /sys/class/graphics/fb*/virtual_size; do echo $f; cat $f; done'
```

The app selects framebuffer names beginning with `fb_` or `fbtft`.

---

## 17. Security and secrets

Important private files:

```text
/Users/flo/esp32_flappy_st7789/src/secrets.h
```

This file contains private WiFi credentials and an API-key-looking value. Do not commit or publish it.

Recommended `.gitignore` entry if this becomes a git repo:

```gitignore
src/secrets.h
.pio/
```

If any private key in `src/secrets.h` was ever committed, pasted, or exposed, rotate/revoke it.

---

## 18. Extension guide: adding a new cue

Adding a cue requires work in two places.

### 18.1 Add cue on TinyPi

File:

```text
/home/tinypi/usb_keyboard_display.py
```

Steps:

1. Add aliases to `CUE_ALIASES`.
2. Add payload shaping to `cue_command_for_text()` if the cue needs arguments.
3. Add optional local preprocessing to `launch_cue()` if TinyPi should fetch/generate data before sending to ESP.
4. Restart service:

```bash
ssh tinypi 'sudo systemctl restart usb-keyboard-display.service'
```

Example minimal cue:

```python
CUE_ALIASES = {
    ...
    "pong": "pong",
    "/pong": "pong",
}
```

If no special payload is required, TinyPi will send:

```json
{"cue":"pong"}
```

### 18.2 Add cue on ESP

File:

```text
/Users/flo/esp32_flappy_st7789/src/main.cpp
```

Steps:

1. Add an enum value to `AppMode`.
2. Add global state needed by the mode.
3. Add `renderNewMode()`.
4. Add update logic in `loop()` if interactive.
5. Add a case in `render()`.
6. Add cue handling in `launchByCue()`.
7. Add cue name to `/cues` response.
8. Build/upload.

Example launch case:

```cpp
else if (cue == "pong") {
  sendLaunchOk("pong");
  activeMode = MODE_PONG;
  resetPong();
}
```

---

## 19. Suggested future cue ideas

Good next additions:

- `pong` — joystick paddle game.
- `breakout` — brick breaker.
- `maze` — generated maze explorer.
- `quiz` — TinyPi LLM generates a question, ESP shows choices.
- `rpg` — TinyPi generates a one-sentence quest, ESP shows a mini map.
- `status` — ESP shows TinyPi uptime, WiFi, battery/power info if available.
- `agent` — show Codex/Claude/build/test status from Mac.
- `paint save` — draw mode plus upload/serialize bitmap back to TinyPi.
- `mood` — display an animated face/NPC with TinyPi-generated dialogue.
- `radio` — launch audio/stream control if hardware supports it.

---

## 20. File inventory

### TinyPi

```text
/home/tinypi/usb_keyboard_display.py
  Main Bluetooth keyboard + framebuffer + local LLM + cue bridge app.

/home/tinypi/bt_keyboard_pair_wait_input.py
  Controlled Bluetooth keyboard pairing/re-pairing helper.

/home/tinypi/chatbot/tiny_terminal_chat.py
  Earlier framebuffer local chatbot app; not currently active.

/home/tinypi/chatbot/bin/llama-cli
  llama.cpp CLI binary.

/home/tinypi/chatbot/models/SmolLM2-135M-Instruct-Q2_K.gguf
  Local Hugging Face SmolLM2 135M instruct Q2_K model.

/home/tinypi/chatbot/bt_keyboard_agent.sh
  Keeps bluetoothctl KeyboardDisplay agent registered.

/home/tinypi/esp_bridge_url
  Explicit ESP bridge base URL.

/tmp/esp_bridge_url
  Cached/active ESP bridge base URL.

/tmp/bt_keyboard_status
  Status line rendered by TinyPi UI.
```

### TinyPi systemd

```text
/etc/systemd/system/usb-keyboard-display.service
/home/tinypi/.config/systemd/user/bt-keyboard-agent.service
```

### ESP project

```text
/Users/flo/esp32_flappy_st7789/platformio.ini
  PlatformIO config, TFT_eSPI build flags.

/Users/flo/esp32_flappy_st7789/src/main.cpp
  ESP LCD joystick launcher hub firmware.

/Users/flo/esp32_flappy_st7789/src/secrets.h
  Private WiFi/API credentials; do not publish.

/Users/flo/esp32_flappy_st7789/src/main_flappy.cpp.disabled
  Old disabled Flappy source.

/Users/flo/esp32_flappy_st7789/src/main_dino_portrait.cpp.disabled
  Old disabled Dino portrait source.
```

---

## 21. Important current commands cheat sheet

### SSH to TinyPi

```bash
ssh tinypi
```

### Restart TinyPi app

```bash
ssh tinypi 'sudo systemctl restart usb-keyboard-display.service'
```

### Check TinyPi app

```bash
ssh tinypi 'systemctl status usb-keyboard-display.service --no-pager'
```

### Check Bluetooth keyboard device

```bash
ssh tinypi 'cat /proc/bus/input/devices | grep -A8 -B2 -i keyboard'
```

### Set ESP bridge URL

```bash
ssh tinypi 'echo http://192.168.2.188:8765 > ~/esp_bridge_url; echo http://192.168.2.188:8765 > /tmp/esp_bridge_url'
```

### Test ESP from TinyPi

```bash
ssh tinypi 'curl -sS http://192.168.2.188:8765/health; echo'
```

### Launch Dino from TinyPi shell

```bash
ssh tinypi 'curl -sS -X POST http://192.168.2.188:8765/launch -H "Content-Type: application/json" -d "{\"cue\":\"dino\"}"; echo'
```

### Build ESP

```bash
cd /Users/flo/esp32_flappy_st7789
pio run
```

### Upload ESP

```bash
cd /Users/flo/esp32_flappy_st7789
pio run -t upload
```

### Monitor ESP serial

```bash
cd /Users/flo/esp32_flappy_st7789
pio device monitor
```

---

## 22. Design rationale

### Why TinyPi handles keyboard and LLM

The Pi has Linux, Bluetooth, filesystem, Python, and enough RAM/storage to run `llama-cli` with a small model. It is better suited to:

- Bluetooth HID handling
- Text input editing
- Local LLM invocation
- HTTP requests
- Weather fetches
- Command routing

### Why ESP handles display/game modes

The ESP has a directly connected ST7789 and joystick. It is better suited to:

- Low-latency joystick interaction
- Simple games
- Dedicated visual modes
- Always-on appliance-like display

### Why HTTP JSON bridge

HTTP JSON was chosen because:

- Easy to test with `curl`.
- Easy to implement on Arduino ESP32 using `WebServer`.
- Easy to call from Python using `urllib.request`.
- Human-readable payloads make debugging much easier.

### Why one-sentence answers

The TinyPi screen is small. Long LLM output is hard to read and slow to generate. The system prompt and output cleaner enforce one short sentence.

### Why 1-bit graphics on ESP

A full-screen 240x320 sprite at 16-bit color would use much more RAM. A 1-bit sprite is small, fast enough, and visually matches the black-and-white cyberdeck aesthetic.

---

## 23. Known limitations

- TinyPi local LLM is small and can be inaccurate.
- LLM generation is not instant on Pi Zero-class hardware.
- Weather depends on TinyPi internet access and `wttr.in` availability.
- ESP JSON parsing is intentionally lightweight/string-based, not a full JSON parser.
- Bluetooth keyboards may sleep and need a wake keypress.
- ESP IP can change unless DHCP reservation/static IP is set.
- Current chat mode is display-only on ESP; the input remains on TinyPi.
- Draw mode does not yet persist drawings.
- Timer completion flashes visually but no buzzer is documented.

---

## 24. Recommended next hardening steps

1. Add DHCP reservation for ESP at `192.168.2.188`.
2. Add DHCP reservation for TinyPi at `192.168.2.222`.
3. Add `.gitignore` for secrets and PlatformIO build output.
4. Consider mDNS hostname on ESP, e.g. `esp-lcd-joystick.local`.
5. Add `/status` endpoint on ESP returning active mode, uptime, free heap, IP, and last cue.
6. Add a TinyPi command `status` to query and display ESP status.
7. Add a local TinyPi log file for cue launches.
8. Add backoff/clearer UI messages for bridge failures.
9. Add battery/power status if hardware supports it.
10. Add screenshot/debug draw dump options for ESP draw mode.

---

## 25. Current project state in one paragraph

The system currently works as a two-device cyberdeck launcher hub: TinyPi boots into a white-background, black-text Bluetooth-keyboard interface; typed cue words are parsed locally; `dino`, `snake`, `clock`, `weather`, `draw`, `chat`, and `timer` are sent over WiFi to the ESP32 at `http://192.168.2.188:8765`; non-cue text is answered locally by Hugging Face SmolLM2-135M-Instruct via `llama-cli`; the ESP32 receives JSON launch commands and switches its portrait ST7789 display into the requested game/tool mode while keeping its HTTP server alive.
