#!/usr/bin/env python3
"""Run the e-paper app named in active_app."""

import os
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
ALLOWED = {"spotify": "spotify_player", "weather": "weather_station", "calendar": "calendar"}
selection_file = BASE / "active_app"
selection = selection_file.read_text().strip().lower() if selection_file.exists() else "calendar"
if selection not in ALLOWED:
    raise SystemExit(f"Unknown e-paper app: {selection}")
app = BASE / ALLOWED[selection] / "app.py"
os.execv(sys.executable, [sys.executable, str(app)])
