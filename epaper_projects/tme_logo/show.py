#!/usr/bin/env python3
from pathlib import Path
import sys

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
from common.epaper_display import Canvas, paint

asset = Path(__file__).with_name("logo.epd")
data = asset.read_bytes()
if len(data) != 4000:
    raise SystemExit(f"Invalid logo buffer size: {len(data)}")
canvas = Canvas()
canvas.buffer[:] = data
elapsed = paint(canvas)
print(f"TME.eu logo displayed in {elapsed:.2f}s")
