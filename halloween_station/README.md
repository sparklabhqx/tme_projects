# Halloween Arcade

A three-game handheld arcade for the Arduino GIGA R1 WiFi and the GIGA Display Shield:
**Pumpkin Whack**, **Flappy Bat** and **Cauldron Catch**, behind a live graveyard menu that
remembers your best score for each. No SD card, no Wi-Fi, no second computer — all artwork is
generated on a laptop, baked into the sketch, and drawn by the board itself.

Companion project to `giga_watching_eyes`, which uses the same display engine for camera tracking.

## Hardware

- Arduino GIGA R1 WiFi
- Arduino GIGA Display Shield
- USB-C cable

Press the shield onto the GIGA until both high-density connectors are fully seated. There are no
jumper wires. After uploading, any USB power supply will do.

## The games

| Game | What you do | How it ends |
| --- | --- | --- |
| Pumpkin Whack | Tap pumpkins, spare ghosts, keep the combo alive | The 45-second clock runs out |
| Flappy Bat | Tap to flap through the gates, grab the sweets | You touch a pillar or the ground |
| Cauldron Catch | Drag the cauldron, catch treats, dodge skulls | Three skulls land in the pot |

**Pumpkin Whack** — six graves, a 45-second round. A pumpkin scores 10 points times the combo,
which climbs to 9 with clean hits. A ghost resets the combo and costs 3 seconds; so does letting a
pumpkin sink back. Over the first 35 seconds the spawn gap tightens from 0.95 s to 0.45 s, time
up shortens from 1.25 s to 0.60 s, and the ghost share rises from 14% to 30%.

**Flappy Bat** — a flap sets -455 px/s, gravity pulls at 1500 px/s². Gate gaps start at 190 px and
narrow with time while the world speeds from 210 to 360 px/s. A gate is 1 point, a sweet in the
gap is 3.

**Cauldron Catch** — hold your finger down and the cauldron follows it. Treats are 5 points, and
every fourth catch in a row raises the multiplier to a maximum of 25 points per treat. Skulls cost
one of three lives. A witch crosses the sky every 12 seconds.

The menu's left 400 px is a live diorama (bats, a witch, a rising ghost, two flickering
jack-o'-lanterns, lightning every 6-15 s); the right half is a static panel of three cards showing
the current best scores. The skull button in the top-left corner of any game returns to the menu.

## How the engine works

The panel is physically 480x800 portrait; the arcade runs 800x480 landscape and **rotates nothing
at runtime**. `tools/gen_assets.py` draws every sprite and font with pycairo and emits them
already turned sideways, in the panel's memory order. In the game, landscape `(x, y)` is simply
memory position `(479 - y, x)`, so a rectangle stays a rectangle.

That mapping has a bonus: a landscape column is a whole row of display memory, so a horizontal
scroll is just a wrapped row-range copy. Flappy Bat's parallax graveyard costs nothing extra.

Each scene composes its complete static background once at boot into its own SDRAM layer — sky
gradient, stars, moon, hills, trees, fence, tombstones, grave pits. A frame then starts by
DMA2D-copying that layer over the back buffer, which erases the previous frame in one move, and
only the things that actually move are drawn on top.

| What | Size | How often it is drawn |
| --- | --- | --- |
| Four background layers | 4 x 750 KB | Once, at boot |
| Transparency mask for dimming | 375 KB | Once, at boot |
| Visible and hidden framebuffer | 2 x 750 KB | Every frame |
| Sprites and fonts in program flash | - | Never, read in place |

Drawing goes through the STM32's DMA2D graphics accelerator in three modes: fill a rectangle with
one colour, copy a rectangle, and alpha-blend a rectangle over what is there.

### Gotchas worth knowing

- **DMA2D register-to-memory fills want ARGB8888.** `HAL_DMA2D_Start` packs the colour down to
  RGB565 itself. Hand it a raw RGB565 word and every solid fill is silently wrong (`0x1883` dark
  brown rendered as blue) while sprite blits stay correct.
- **`LayerCfg.InputAlpha` has two conventions.** For A8 sources it takes the full ARGB word
  (`alpha << 24 | rgb`); for every other format it takes a plain 0-255 alpha.
- **`SDRAM.begin()` runs inside `Display.begin()`** before the video mode is known, so the
  allocator's heap starts about 5 MB into the 8 MB SDRAM and only ~3 MB is usable. Over-allocating
  wraps and silently corrupts earlier buffers.
- A full-screen redraw from an SDRAM layer costs roughly 17 ms, and `present()` blocks on vblank.
  Bake everything static into the background layer.

## Build and upload

Needs the `arduino:mbed_giga` core and the `Arduino_H7_Video` and `Arduino_GigaDisplayTouch`
libraries from the Library Manager. Open `halloween_station.ino`, select **Arduino GIGA R1 WiFi**
and your port, and upload. The first build is slow because the generated artwork is a large source
file; later builds are fast.

On boot the board shows `SUMMONING` while it paints the four background layers, then the menu
appears.

## Regenerating the artwork

```bash
python3 tools/gen_assets.py
```

This rewrites `assets.h` and `assets_data.cpp`, and drops PNG previews of every sprite into
`tools/preview/` so you can see what you changed. Every sprite is a few lines of pycairo — nothing
is a photograph — so this is the interesting file to change if you want a different theme.

## Serial debug protocol (115200 baud)

| Send | What happens |
| --- | --- |
| `S` | Dumps the displayed framebuffer as raw RGB565 (480x800, panel-native) |
| `T x y` | Injects a single tap at landscape (x, y) |
| `H x y` / `U` | Press and hold, then release |
| `I` | Prints FPS, per-phase milliseconds, frame number and touch state |

`tools/devtool.py` wraps these (needs `pyserial` and `Pillow`). It picks the first
`/dev/cu.usbmodem*` it finds, so unplug other boards first.

```bash
python3 tools/devtool.py info                        # fps and touch state
python3 tools/devtool.py shot out.png                # screenshot the running game
python3 tools/devtool.py tap 500 300 --shot after.png
python3 tools/devtool.py hold 500 300                # then: release
python3 tools/devtool.py film frame_%02d.png 20 --delay 0.4
```

Being able to screenshot a running game and tap a menu entry without touching the hardware is
twenty lines of firmware that pay for themselves the first evening.
