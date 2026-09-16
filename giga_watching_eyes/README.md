# GIGA Watching Eyes

A pair of eyes on the Arduino GIGA Display Shield that turn and follow the nearest person,
using an OV7675 camera and a TensorFlow Lite Micro person classifier running entirely on the
GIGA's own M7 core. No Wi-Fi, no laptop, no cloud — the camera image never leaves the board.

Companion project to `halloween_station`, which uses the same display engine for games.

## Hardware

- Arduino GIGA R1 WiFi
- Arduino GIGA Display Shield (800x480 landscape on a 480x800 portrait panel)
- OV7675 DVP camera module, plugged into the camera connector on the back of the shield
- Optional: a 3D-printed housing with a stand, so the camera sits above the screen at face height

No jumper wires, level shifters or extra power are needed. The camera is a direct plug, but the
socket will physically accept the module the wrong way round — check the pin labels first.

## What it does

- Renders only two eyes at 800x480 on a pure black (`0x0000`) background. No face, skin, border,
  text or camera preview.
- Unequal organic lid contours, off-white bloodshot sclera, branching capillaries and dark wet
  margins inside the eye apertures. Amber/olive irises with irregular radial fibers, crypts,
  freckles, a scalloped gold collarette and dark limbal rings; deep-black pupils under corneal
  reflections.
- With nobody there, the eyes rest near center, make tiny saccades and occasionally narrow.
  When a person is detected they ease open, briefly dilate, and settle into a tracking stare
  over about 2.4 seconds.
- Blinks close in 72 ms, stay fully shut for ~48 ms, then reopen over 145 ms. The second lid
  trails the first by 17 ms. Closed regions are masked with black, never skin-colored pixels.

## How the tracking works

Two independent methods share the same 320x240 grayscale frame and cover each other's weaknesses.

**Motion** boils the frame down to a 40x30 grid and diffs it against the previous grid. Cells that
changed beyond a threshold are weighted and averaged into a centroid. The mean change across the
whole grid is subtracted first, so the camera's auto-exposure cannot be mistaken for the whole
room moving. This is precise, but only while the subject is moving.

**Classification** runs the 96x96 person model on three overlapping crops in the rotation
`full, left, full, right`. When the subject stands still and motion has gone stale, the difference
between the left and right scores gives a coarse but stable direction.

Only the full-frame view may acquire a person, and it has to earn it: either an unambiguous score
(`> 0.78`, clearly ahead of the no-person score, on two consecutive checks) or a good score
(`> 0.62`) agreeing with fresh, substantial motion. A tiny classifier gives plain low-contrast
walls moderately person-ish scores, so a moderate score alone is never enough. Acquisitions are
ignored for the first ~7 seconds while exposure settles. Once acquired, a lower score keeps a
stationary person locked; after 3.2 seconds with no confirmation the eyes let go.

Whichever method is in charge, the gaze eases towards its target exponentially — faster when
somebody is present — so the eyes never snap and the handover between methods is invisible.

| Step | How often | How long |
| --- | --- | --- |
| Camera frame, 320x240 grayscale | every 160 ms | - |
| Motion grid, 40x30 cells | every frame | under 1 ms |
| Person classifier, 96x96 input | every 560 ms | about 47 ms |
| Eye animation and redraw | every loop | the rest |

**Model input must remain `(int8_t)((int)pixel - 128)`.** Do not apply the tensor scale to raw
camera bytes — that saturates the input and silently breaks inference while everything still runs
at full speed. The animation reads `humanPresent`; it never feeds back into the classifier.

## Rendering notes

The black backdrop, the static sclera/veins/margins and the iris textures are built once at boot
and cached in SDRAM. DMA2D copies the full base into the back buffer each frame; organic contour
curves and iris texture noise are computed once at startup, and iris columns are pre-rotated into
panel-native order so they can be copied as contiguous, lid-clipped spans. No per-pixel
trigonometry runs in the animation loop. A 60-second hardware test reported 16.7 median FPS
(15.9-17.8 sampled) with 47 ms median inference.

The M7 CPU, DMA2D and the LTDC display controller do not share a coherent cache, so the renderer
hands memory over explicitly: it cleans the immutable SDRAM bases once before DMA reads them,
invalidates the back-buffer cache around DMA writes, and cleans the data cache before presenting.
Without that, pixels drawn last can sit in CPU cache while the panel reads stale SDRAM — a defect
that is invisible to an `S` framebuffer dump, because that dump is taken by the CPU.

## Camera orientation

The defaults match a camera facing the viewer:

```cpp
CAMERA_MIRROR_X = true;
CAMERA_FLIP_Y   = false;
```

If the eyes look left when you step right, change these constants near the top of the sketch —
not the tracking code.

## Build and upload

Requires the `arduino:mbed_giga` core (4.5.0) and a TensorFlow Lite Micro library for Arduino
(developed against `Chirale_TensorFLowLite` 2.0.0).

```bash
cd giga_watching_eyes
./build.sh                          # compile only
./build.sh /dev/cu.usbmodemXXXXX    # compile and upload
```

Use `arduino-cli board list` to confirm the GIGA's port; macOS renumbers it regularly. The first
build is slow, later ones are not. Current size: 534,512 bytes of flash, 223,544 bytes of static RAM.

## Serial diagnostics (115200 baud)

| Send | What you get back |
| --- | --- |
| `I` | Status, detector scores, motion center, gaze, inference time, FPS |
| `S` | Active display framebuffer dump (480x800, RGB565, panel-native) |
| `C` | Camera frame dump (320x240, grayscale) |
| `G x y` | Force the gaze to a fixed direction, each value -100..100; eases the eyes fully open and suppresses micro-saccades for clipping checks (natural blinking continues) |
| `G 999 999` | Return to camera tracking |

Classifier `views` in the status line are printed as `left/full/right`.

### Serial capture and validation

Needs Python `pyserial` and `Pillow`. With the GIGA connected and the camera facing a blank wall:

```bash
python3 tools/eyes_serial.py info
python3 tools/eyes_serial.py validate --seconds 60
python3 tools/eyes_serial.py screen --out screen.png
python3 tools/eyes_serial.py camera --out camera.png
python3 tools/eyes_serial.py gaze -100 100
python3 tools/eyes_serial.py gaze 999 999
```

The validator checks that the camera and model came up, that a blank wall produces no
acquisitions, that inference lands near 47 ms and reported FPS stays at 16 or above, that all
nine manual gaze positions settle where asked, and that every pixel outside the eye contours is
exactly black. It retries captures caught mid-blink, saves binary dumps, landscape PNGs, serial
logs and a `report.json` under `build/validation/`, then restores camera tracking. Framebuffer
dumps pause rendering briefly, so performance samples are taken before dumping.

There is also a host-side test that compiles the sketch's real renderer with only hardware and
time calls stubbed (needs `clang++` and Pillow):

```bash
python3 tools/test_renderer.py
```

It runs under AddressSanitizer and UndefinedBehaviorSanitizer and checks 189 aperture/gaze/pupil
combinations, the gaze easing and manual `G` control, synthetic acquisition and blink behaviour,
and the cache handoff ordering.

## Model attribution

`person_detect_model_data.cpp` is the TensorFlow Lite Micro person-detection example model from
`tensorflow/tflite-micro-arduino-examples`, distributed under Apache-2.0. The generated model
source retains its original license header.
