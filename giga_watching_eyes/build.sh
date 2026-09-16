#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
FQBN="arduino:mbed_giga:giga"

arduino-cli compile --fqbn "$FQBN" "$ROOT"

if [[ $# -gt 0 ]]; then
  arduino-cli upload --fqbn "$FQBN" -p "$1" "$ROOT"
fi
