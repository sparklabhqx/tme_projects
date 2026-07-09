#!/usr/bin/env bash
# Keep bluetoothctl alive so the KeyboardDisplay pairing agent remains registered.
{ sleep infinity; } | /usr/bin/bluetoothctl --agent=KeyboardDisplay
