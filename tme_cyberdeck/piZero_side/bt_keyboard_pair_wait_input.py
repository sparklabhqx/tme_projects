#!/usr/bin/env python3
from __future__ import annotations

import os
import re
import select
import subprocess
import time
from pathlib import Path

STATUS = Path("/tmp/bt_keyboard_status")
LOG = Path("/tmp/bt_keyboard_pair_wait_input.log")
MAC_RE = re.compile(r"([0-9A-F]{2}(?::[0-9A-F]{2}){5})", re.I)
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
KEYWORDS = ("keyboard", "keys", "keychron", "k380", "k480", "logi", "magic keyboard", "bluetooth keyboard")


def clean(s: str) -> str:
    return ANSI_RE.sub("", s).replace("\r", "\n")


def status(msg: str):
    STATUS.write_text(msg[:120])
    with LOG.open("a") as f:
        f.write(time.strftime("%H:%M:%S STATUS ") + msg + "\n")


def log(msg: str):
    with LOG.open("a") as f:
        f.write(time.strftime("%H:%M:%S ") + msg.rstrip() + "\n")


def input_ready() -> str | None:
    try:
        blocks = Path("/proc/bus/input/devices").read_text(errors="ignore").split("\n\n")
    except OSError:
        return None
    for block in blocks:
        low = block.lower()
        if "handlers=" not in low or "event" not in low:
            continue
        name = ""
        handlers = ""
        for line in block.splitlines():
            if line.startswith("N: Name="):
                name = line.split("=", 1)[1].strip().strip('"')
            elif line.startswith("H: Handlers="):
                handlers = line
        nlow = name.lower()
        if "vc4-hdmi" in nlow or "touchscreen" in nlow:
            continue
        if "keyboard" in nlow or "kbd" in handlers.lower():
            return name or handlers
    return None


def run_cmd(args: list[str], timeout=8) -> str:
    try:
        return subprocess.run(args, text=True, capture_output=True, timeout=timeout).stdout
    except Exception as e:
        return str(e)


def main() -> int:
    LOG.write_text("")
    status("Put Bluetooth keyboard in pairing mode.")
    subprocess.run(["systemctl", "--user", "stop", "bt-keyboard-agent.service"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # Remove stale bonded keyboards so we get a fresh HID setup/input device.
    devices = run_cmd(["bluetoothctl", "devices"], timeout=8)
    for line in devices.splitlines():
        mm = MAC_RE.search(line)
        if mm and any(k in line.lower() for k in KEYWORDS):
            mac = mm.group(1).upper()
            log(f"removing stale {line}")
            run_cmd(["bluetoothctl", "remove", mac], timeout=8)

    proc = subprocess.Popen(
        ["stdbuf", "-oL", "-eL", "bluetoothctl", "--agent=KeyboardDisplay"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    def send(cmd: str):
        if proc.poll() is not None or proc.stdin is None:
            return
        log("> " + cmd)
        proc.stdin.write(cmd + "\n")
        proc.stdin.flush()

    for cmd in ("power on", "agent KeyboardDisplay", "default-agent", "pairable on", "discoverable on", "scan on"):
        send(cmd)
        time.sleep(0.25)

    candidate: str | None = None
    paired_or_connected = False
    start = time.time()
    timeout = int(os.environ.get("BT_PAIR_TIMEOUT", "300"))
    next_devices = time.time() + 3
    next_ready_check = time.time()

    try:
        while time.time() - start < timeout and proc.poll() is None:
            now = time.time()
            if now >= next_ready_check:
                ready = input_ready()
                if ready:
                    status(f"BT keyboard ready: {ready}. Type now.")
                    return 0
                if paired_or_connected:
                    status("BT connected; waiting for Linux input device. Press a key.")
                next_ready_check = now + 2
            if now >= next_devices:
                send("devices")
                if candidate:
                    send("info " + candidate)
                next_devices = now + 6

            r, _, _ = select.select([proc.stdout], [], [], 0.5) if proc.stdout else ([], [], [])
            if not r:
                continue
            raw = proc.stdout.readline()
            if not raw:
                continue
            for line in clean(raw).splitlines():
                line = line.strip(" \b")
                if not line:
                    continue
                log(line)

                pin = re.search(r"(?:Passkey|PIN code)[: ]+(\d{4,8})", line, re.I)
                if pin:
                    status(f"Type PIN {pin.group(1)} on keyboard, then Enter.")
                    continue
                if "Confirm passkey" in line or "Authorize service" in line or "Accept pairing" in line:
                    send("yes")
                    status("Confirming Bluetooth pairing...")
                    continue
                if "Pairing successful" in line or "Paired: yes" in line:
                    paired_or_connected = True
                    status("Paired. Connecting...")
                    if candidate:
                        send("trust " + candidate)
                        time.sleep(0.2)
                        send("connect " + candidate)
                    continue
                if "ServicesResolved: yes" in line or "Connection successful" in line or "Connected: yes" in line:
                    paired_or_connected = True
                    status("BT connected; waiting for input device. Press a key.")
                    if candidate:
                        send("trust " + candidate)
                    continue
                if "Failed to pair" in line or "AuthenticationFailed" in line or "AuthenticationCanceled" in line:
                    status("Pairing failed. Put keyboard in pairing mode again.")
                    candidate = None
                    send("scan on")
                    continue

                if "Device " in line:
                    mm = MAC_RE.search(line)
                    if not mm:
                        continue
                    mac = mm.group(1).upper()
                    name = line.split(mac, 1)[-1].strip()
                    if any(k in name.lower() for k in KEYWORDS):
                        if candidate != mac:
                            candidate = mac
                            status(f"Found {name or mac}. Pairing...")
                            send("scan off")
                            time.sleep(0.3)
                            send("pair " + mac)
    finally:
        try:
            send("scan off")
            send("quit")
            proc.terminate()
            proc.wait(timeout=3)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        subprocess.run(["systemctl", "--user", "start", "bt-keyboard-agent.service"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    status("No keyboard input device yet. Put keyboard in pairing mode and retry.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
