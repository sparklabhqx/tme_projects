# TME Reaction Lab — Pico W Reaction Game with 3D Web Scoreboard

A two-choice reaction tester on a Raspberry Pi Pico W with an SH1106 OLED and
two arcade buttons — plus a self-hosted scoreboard website in the TME house
style, served by the Pico itself, featuring a Three.js "start grid" where your
reaction time races a cat, an esports pro, an F1 driver, and more in 10x slow
motion.

## What this project does

- After a random 1.5–3.5 s wait the OLED flashes **LEFT/BLUE** or
  **RIGHT/RED**; hit the matching button as fast as you can.
- False starts, wrong buttons, and >3 s sleeps void the round.
- Millisecond timing starts only after the cue frame is fully pushed to the
  panel, so display latency never inflates a score.
- Every valid round is logged to flash (`scores.json`); the best time and
  top-10 survive power cycles.
- The Pico joins WiFi, syncs real time via NTP, and serves
  **http://reaction.local** — live stat tiles, a benchmark bar chart, top-10
  with timestamps, and the 3D start-grid race (lanes launch after their real
  reaction times, slowed 10x; your lane uses your live best).
- A stuck or shorted button is detected and named on the OLED instead of
  silently freezing the game. `pin_diag.py` is a standalone live GPIO monitor
  for wiring debugging.
- The game works fully offline too — WiFi only adds the scoreboard.

## Hardware

| Part | Connection |
|---|---|
| Raspberry Pi Pico W / WH | MicroPython v1.29+ (Pico W build) |
| SH1106 128x64 I2C OLED (1.3", addr 0x3C) | VCC → 3V3 (pin 36), GND → pin 38, SDA → GP4 (pin 6), SCL → GP5 (pin 7) |
| Button 1 (left / blue) | GP14 (pin 19) → GND (pin 18), internal pull-up |
| Button 2 (right / red) | GP15 (pin 20) → GND (pin 18), internal pull-up |

Notes:

- If SDA/SCL end up swapped, the code auto-detects and falls back to software
  I2C — the game still works, hardware I2C is just faster.
- The display is initialized with `rotate180=True` in `main.py`; flip it if
  your panel is mounted the other way up.
- Wire each tactile switch across **diagonally opposite** legs (same-side legs
  are internally connected and read as "always pressed").

## Folder layout

```text
reaction_game/
├── README.md
├── .gitignore
├── main.py               # game + asyncio web server (runs at boot)
├── sh1106.py             # minimal SH1106 framebuf driver (132-col offset)
├── pin_diag.py           # live GPIO monitor on the OLED (debug tool)
├── index.html            # TME-style scoreboard page with Three.js start grid
├── three.js.gz           # three.module.min.js r161, pre-gzipped (served as-is)
└── secrets.example.py    # copy to secrets.py with your WiFi credentials
```

## Install

1. Flash the MicroPython **Pico W** UF2 (hold BOOTSEL, copy to `RPI-RP2`).
2. `cp secrets.example.py secrets.py` and fill in your WiFi credentials.
3. Upload everything:

```bash
python3 -m mpremote connect <port> \
  fs cp main.py :main.py + \
  fs cp sh1106.py :sh1106.py + \
  fs cp secrets.py :secrets.py + \
  fs cp index.html :index.html + \
  fs cp three.js.gz :three.js.gz + \
  reset
```

4. Open **http://reaction.local** (the IP is also printed on the serial
   console at boot).

The Pico serves the ~660 KB Three.js library as a 167 KB pre-gzipped file with
`Content-Encoding: gzip` and a one-week immutable cache header, so browsers
fetch it once and the little board never breaks a sweat.
