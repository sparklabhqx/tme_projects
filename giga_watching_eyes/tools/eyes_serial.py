#!/usr/bin/env python3
"""GIGA eyes diagnostics; never auto-selects another board's port.

Requires pyserial and Pillow. Examples:
  python3 tools/eyes_serial.py info
  python3 tools/eyes_serial.py screen --out build/screen.png
  python3 tools/eyes_serial.py camera --out build/camera.png
  python3 tools/eyes_serial.py gaze -100 100
  python3 tools/eyes_serial.py gaze 999 999
  python3 tools/eyes_serial.py validate --seconds 60

validate requires the camera to face a blank wall. It records live diagnostics,
checks camera/ML/person state, captures S/C binary dumps, tests all gaze extrema,
and always restores G 999 999. It does not upload or simulate detector input.
"""
import argparse
import json
from pathlib import Path
import re
import statistics
import time

from PIL import Image
import serial

from test_renderer import decode_rgb565

ROOT = Path(__file__).resolve().parents[1]


def command(s, text):
    s.write((text + "\n").encode("ascii"))
    s.flush()


def status(s):
    s.reset_input_buffer()
    command(s, "I")
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        line = s.readline().decode("ascii", errors="replace").strip()
        if line.startswith("[status]"):
            return line
    raise RuntimeError("No I status response from the GIGA")


def read_exact(s, count):
    data = bytearray()
    deadline = time.monotonic() + 30
    while len(data) < count and time.monotonic() < deadline:
        data.extend(s.read(count - len(data)))
    if len(data) != count:
        raise RuntimeError(f"Short binary dump: {len(data)}/{count}")
    return bytes(data)


def capture(s, camera, path):
    s.reset_input_buffer()
    command(s, "C" if camera else "S")
    expected = b"CAMSHOT 320 240 GRAY8" if camera else b"FBSHOT 480 800 RGB565"
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if s.readline().strip() == expected:
            break
    else:
        raise RuntimeError(f"No {expected!r} header")
    data = read_exact(s, 320 * 240 if camera else 480 * 800 * 2)
    trailer = b"CAMDONE" if camera else b"FBDONE"
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if s.readline().strip() == trailer:
            break
    else:
        raise RuntimeError("Missing dump trailer")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.with_suffix(".gray8" if camera else ".rgb565").write_bytes(data)
    image = Image.frombytes("L", (320, 240), data) if camera else decode_rgb565(data)
    image.save(path)
    print(f"Saved hardware {'C' if camera else 'S'} capture: {path}")
    return data


def check_background(data):
    # Conservative eye-only rectangles. Exact contour/mask checks are performed
    # by test_renderer.py; this independently checks the actual hardware dump.
    nonzero = 0
    outside = 0
    for x in range(800):
        for y in range(480):
            offset = ((479 - y) + 480 * x) * 2
            lit = data[offset] != 0 or data[offset + 1] != 0
            nonzero += lit
            if not (155 <= y <= 310 and (50 <= x <= 360 or 440 <= x <= 750)):
                outside += lit
    if outside:
        raise RuntimeError(f"{outside} non-black pixels outside the eye-only regions")
    return {"nonblack_pixels": nonzero, "black_percent": round(100 * (1 - nonzero / 384000), 2),
            "nonblack_outside_eyes": outside}


def validate(s, seconds, out):
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    # Let camera exposure settle. Do not use manual gaze to falsify presence.
    command(s, "G 999 999")
    time.sleep(8)
    deadline = time.monotonic() + seconds
    with (out / "status.log").open("w") as log:
        while time.monotonic() < deadline:
            line = status(s)
            print(line)
            log.write(line + "\n")
            log.flush()
            values = dict(re.findall(r"(\w+)=([^ ]+)", line))
            rows.append(values)
            if values.get("camera") != "1" or values.get("ml") != "1":
                raise RuntimeError("Camera/ML not ready; see status.log")
            if values.get("human") != "0":
                raise RuntimeError("Human acquisition during blank-wall test; see status.log")
            time.sleep(min(2, max(0, deadline - time.monotonic())))
    inference = [float(r["infer_ms"]) for r in rows]
    fps = [float(r["fps"]) for r in rows]
    report = {"source": "live GIGA USB serial", "status_samples": len(rows),
              "blank_wall_seconds": seconds, "camera": 1, "ml": 1, "human_acquisitions": 0,
              "inference_ms_median": statistics.median(inference),
              "fps_median": statistics.median(fps), "fps_min": min(fps), "screens": {}}
    capture(s, True, out / "camera.png")
    report["screens"]["idle"] = check_background(capture(s, False, out / "idle.png"))
    try:
        # Start with center, then both axes and all four diagonal extremes.
        for x, y in [(0, 0), (-100, 0), (100, 0), (0, -100), (0, 100),
                     (-100, -100), (-100, 100), (100, -100), (100, 100)]:
            command(s, f"G {x} {y}")
            time.sleep(1.6)
            name = f"gaze_{x}_{y}"
            gaze_status = status(s)
            gaze_match = re.search(r"gaze=([-\d.]+),([-\d.]+)", gaze_status)
            if not gaze_match or any(abs(float(actual) - expected / 100) > 0.04
                                     for actual, expected in zip(gaze_match.groups(), (x, y))):
                raise RuntimeError(f"Manual gaze did not settle: {gaze_status}")
            data = capture(s, False, out / f"{name}.png")
            # Reject partial blinks too: full-open eyes have ~50–56k lit pixels.
            if check_background(data)["nonblack_pixels"] < 45000:
                time.sleep(0.4)
                data = capture(s, False, out / f"{name}.png")
            report["screens"][name] = check_background(data)
            report["screens"][name]["status"] = gaze_status
            if report["screens"][name]["nonblack_pixels"] < 45000:
                raise RuntimeError(f"Eyes unexpectedly dark/closed in {name}")
    finally:
        command(s, "G 999 999")
    # Screen dumps pause the main loop: allow the existing FPS filter to settle.
    time.sleep(8)
    report["restored_status"] = status(s)
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    if not 40 <= report["inference_ms_median"] <= 55:
        raise RuntimeError("Inference timing is not near the expected 47ms")
    if report["fps_median"] < 16:
        raise RuntimeError("Display FPS is below the existing 16–18 FPS baseline")
    print("PASS live blank-wall/status/background/gaze diagnostics; inspect PNGs for appearance")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["info", "screen", "camera", "gaze", "validate"])
    parser.add_argument("values", nargs="*", type=int)
    parser.add_argument("--port", default="/dev/cu.usbmodem214301")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--seconds", type=float, default=60)
    args = parser.parse_args()
    if not Path(args.port).exists():
        parser.error(f"GIGA port is absent: {args.port}; reconnect it (no other port will be guessed)")
    if args.command == "gaze" and len(args.values) != 2:
        parser.error("gaze requires x y (-100..100 or 999 999)")
    if args.command == "validate" and args.seconds < 10:
        parser.error("validate requires at least 10 seconds")
    with serial.Serial(args.port, 115200, timeout=0.5) as s:
        time.sleep(0.2)
        if args.command == "info":
            print(status(s))
        elif args.command == "gaze":
            command(s, f"G {args.values[0]} {args.values[1]}")
            time.sleep(1.5)
            print(status(s))
        elif args.command == "validate":
            validate(s, args.seconds, args.out or ROOT / "build/validation/hardware")
        else:
            camera = args.command == "camera"
            path = args.out or ROOT / "build/validation" / ("camera.png" if camera else "screen.png")
            data = capture(s, camera, path)
            if not camera:
                print(json.dumps(check_background(data)))


if __name__ == "__main__":
    main()
