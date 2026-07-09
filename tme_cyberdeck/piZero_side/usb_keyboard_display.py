#!/usr/bin/env python3
"""Bluetooth keyboard prompt-to-local-LLM display for the TinyPi TFT."""
from __future__ import annotations

import concurrent.futures
import fcntl
import ipaddress
import json
import os
import re
import selectors
import struct
import subprocess
import textwrap
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
import pygame  # noqa: E402

EV_KEY = 0x01
KEY_RELEASE = 0
KEY_PRESS = 1
KEY_REPEAT = 2
EVENT_STRUCT = struct.Struct("llHHI")
EVIOCGNAME = lambda length: 0x80004506 | (length << 16)  # noqa: E731

KEY_NAMES = {
    1: "ESC", 14: "BACKSPACE", 15: "TAB", 28: "ENTER", 57: "SPACE",
    42: "LSHIFT", 54: "RSHIFT", 29: "LCTRL", 97: "RCTRL", 56: "LALT", 100: "RALT",
    58: "CAPSLOCK", 103: "UP", 108: "DOWN", 105: "LEFT", 106: "RIGHT",
    111: "DELETE", 102: "HOME", 107: "END",
}
NORMAL = {
    2: "1", 3: "2", 4: "3", 5: "4", 6: "5", 7: "6", 8: "7", 9: "8", 10: "9", 11: "0",
    12: "-", 13: "=", 16: "q", 17: "w", 18: "e", 19: "r", 20: "t", 21: "y", 22: "u", 23: "i", 24: "o", 25: "p",
    26: "[", 27: "]", 30: "a", 31: "s", 32: "d", 33: "f", 34: "g", 35: "h", 36: "j", 37: "k", 38: "l",
    39: ";", 40: "'", 41: "`", 43: "\\", 44: "z", 45: "x", 46: "c", 47: "v", 48: "b", 49: "n", 50: "m",
    51: ",", 52: ".", 53: "/", 57: " ", 86: "<",
}
SHIFTED = {
    2: "!", 3: "@", 4: "#", 5: "$", 6: "%", 7: "^", 8: "&", 9: "*", 10: "(", 11: ")",
    12: "_", 13: "+", 16: "Q", 17: "W", 18: "E", 19: "R", 20: "T", 21: "Y", 22: "U", 23: "I", 24: "O", 25: "P",
    26: "{", 27: "}", 30: "A", 31: "S", 32: "D", 33: "F", 34: "G", 35: "H", 36: "J", 37: "K", 38: "L",
    39: ":", 40: "\"", 41: "~", 43: "|", 44: "Z", 45: "X", 46: "C", 47: "V", 48: "B", 49: "N", 50: "M",
    51: "<", 52: ">", 53: "?", 57: " ", 86: ">",
}
LETTERS = set(range(16, 26)) | set(range(30, 39)) | set(range(44, 51))


ROOT = Path.home() / "chatbot"
LLAMA = ROOT / "bin" / "llama-cli"
MODEL = ROOT / "models" / "SmolLM2-135M-Instruct-Q2_K.gguf"
SYSTEM_PROMPT = (
    "You are TinyPi, a tiny local assistant on a small screen. "
    "Answer with exactly one short, helpful sentence under 20 words."
)
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


CUE_ALIASES = {
    "dino": "dino",
    "/dino": "dino",
    "runner": "dino",
    "trex": "dino",
    "snake": "snake",
    "/snake": "snake",
    "clock": "clock",
    "/clock": "clock",
    "time": "clock",
    "weather": "weather",
    "/weather": "weather",
    "draw": "draw",
    "/draw": "draw",
    "paint": "draw",
    "sketch": "draw",
    "chat": "chat",
    "/chat": "chat",
    "talk": "chat",
    "timer": "timer",
    "/timer": "timer",
    "countdown": "timer",
}
BRIDGE_PORT = 8765
BRIDGE_CONFIG_FILES = [
    Path.home() / "esp_bridge_url",
    Path.home() / "esp_bridge.txt",
    Path("/tmp/esp_bridge_url"),
]
BRIDGE_CACHE_FILE = Path("/tmp/esp_bridge_url")
BRIDGE_HOST_CANDIDATES = [
    "esp-lcd-joystick.local",
    "lcd-joystick.local",
    "esp32.local",
    "esp.local",
]


def parse_duration_seconds(value: str) -> tuple[int, str]:
    """Parse a small timer duration; bare numbers are minutes."""
    text = value.strip()
    if not text:
        return 300, "5 minutes"

    mmss = re.search(r"\b(\d{1,2}):(\d{2})\b", text)
    if mmss:
        seconds = int(mmss.group(1)) * 60 + int(mmss.group(2))
        label = (text[:mmss.start()] + text[mmss.end():]).strip(" -,:;")
        return max(1, seconds), label or f"{seconds} seconds"

    total = 0
    first_span: tuple[int, int] | None = None
    for match in re.finditer(r"\b(\d+)\s*(hours?|hrs?|h|minutes?|mins?|m|seconds?|secs?|s)?\b", text, re.I):
        number = int(match.group(1))
        unit = (match.group(2) or "m").lower()
        if unit.startswith("h"):
            total += number * 3600
        elif unit.startswith("s"):
            total += number
        else:
            total += number * 60
        if first_span is None:
            first_span = match.span()
    if total <= 0:
        return 300, text
    label = text
    if first_span:
        label = (text[:first_span[0]] + text[first_span[1]:]).strip(" -,:;")
    if not label:
        if total % 3600 == 0:
            label = f"{total // 3600} hour timer"
        elif total % 60 == 0:
            label = f"{total // 60} minute timer"
        else:
            label = f"{total} second timer"
    return min(total, 24 * 3600), label


def cue_command_for_text(value: str) -> tuple[str, dict] | None:
    stripped = value.strip()
    if not stripped:
        return None
    head, _, rest = stripped.partition(" ")
    cue = CUE_ALIASES.get(head.lower())
    if not cue:
        return None

    payload: dict = {"cue": cue}
    rest = rest.strip()
    if cue == "clock":
        payload.update({
            "epoch": int(time.time()),
            "time": time.strftime("%H:%M"),
            "date": time.strftime("%Y-%m-%d"),
            "timezone": time.tzname[0] if time.tzname else "local",
        })
    elif cue == "weather":
        payload["location"] = rest or "Greenwich"
    elif cue == "chat":
        if rest:
            payload["prompt"] = rest
    elif cue == "timer":
        seconds, label = parse_duration_seconds(rest)
        payload.update({"seconds": seconds, "label": label})
    elif rest:
        payload["arg"] = rest
    return cue, payload


def normalize_bridge_url(value: str) -> str:
    value = value.strip().rstrip("/")
    if not value:
        return ""
    if not value.startswith(("http://", "https://")):
        value = "http://" + value
    if re.match(r"^https?://[^/:]+$", value):
        value += f":{BRIDGE_PORT}"
    return value


def configured_bridge_urls() -> list[str]:
    urls: list[str] = []
    env = normalize_bridge_url(os.environ.get("ESP_BRIDGE_URL", ""))
    if env:
        urls.append(env)
    for path in BRIDGE_CONFIG_FILES:
        try:
            value = normalize_bridge_url(path.read_text().splitlines()[0])
        except (OSError, IndexError):
            continue
        if value:
            urls.append(value)
    for host in BRIDGE_HOST_CANDIDATES:
        urls.append(f"http://{host}:{BRIDGE_PORT}")
    out: list[str] = []
    for url in urls:
        if url not in out:
            out.append(url)
    return out


def bridge_request(url: str, path: str, payload: dict | None = None, timeout: float = 1.0) -> dict | None:
    full_url = url.rstrip("/") + path
    data = None
    headers = {"Accept": "application/json"}
    method = "GET"
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
        method = "POST"
    req = urllib.request.Request(full_url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            body = response.read(4096).decode("utf-8", "replace")
    except (OSError, urllib.error.URLError):
        return None
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def bridge_is_healthy(url: str) -> bool:
    payload = bridge_request(url, "/health", timeout=0.6)
    return bool(payload and payload.get("ok"))


def local_subnet_bridge_urls() -> list[str]:
    try:
        proc = subprocess.run(
            ["ip", "-o", "-4", "addr", "show", "scope", "global"],
            text=True,
            capture_output=True,
            timeout=3,
        )
    except Exception:
        return []
    urls: list[str] = []
    seen: set[str] = set()
    for match in re.finditer(r"inet\s+(\d+\.\d+\.\d+\.\d+)/(\d+)", proc.stdout):
        ip = match.group(1)
        prefix = int(match.group(2))
        try:
            net = ipaddress.ip_network(f"{ip}/{prefix}", strict=False)
        except ValueError:
            continue
        if net.num_addresses > 512:
            continue
        for host in net.hosts():
            host_s = str(host)
            if host_s == ip or host_s in seen:
                continue
            seen.add(host_s)
            urls.append(f"http://{host_s}:{BRIDGE_PORT}")
    return urls


def discover_bridge_url() -> str:
    for url in configured_bridge_urls():
        if bridge_is_healthy(url):
            try:
                BRIDGE_CACHE_FILE.write_text(url + "\n")
            except OSError:
                pass
            return url

    candidates = local_subnet_bridge_urls()
    if not candidates:
        return ""

    def check(url: str) -> str:
        return url if bridge_is_healthy(url) else ""

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=32) as pool:
            futures = [pool.submit(check, url) for url in candidates]
            for future in concurrent.futures.as_completed(futures, timeout=8):
                url = future.result()
                if url:
                    try:
                        BRIDGE_CACHE_FILE.write_text(url + "\n")
                    except OSError:
                        pass
                    return url
    except Exception:
        return ""
    return ""


def weather_summary(location: str) -> str:
    location = (location or "Greenwich").strip()
    quoted = urllib.parse.quote(location)
    url = f"https://wttr.in/{quoted}?format=%l:+%c+%t,+%C,+wind+%w"
    try:
        with urllib.request.urlopen(url, timeout=6) as response:
            text = response.read(240).decode("utf-8", "replace").strip()
    except Exception:
        return ""
    return one_sentence(text)


def launch_cue(cue: str, request_payload: dict | None = None) -> str:
    payload_to_send = dict(request_payload or {"cue": cue})
    payload_to_send["cue"] = cue

    local_answer = ""
    if cue == "weather":
        summary = weather_summary(str(payload_to_send.get("location") or "Greenwich"))
        if summary:
            payload_to_send["summary"] = summary
            local_answer = summary
    elif cue == "chat" and payload_to_send.get("prompt"):
        local_answer = ask_local_model(str(payload_to_send["prompt"]))
        payload_to_send["answer"] = local_answer

    url = discover_bridge_url()
    if not url:
        return "I cannot find the launcher bridge yet."
    payload = bridge_request(url, "/launch", payload_to_send, timeout=5.0)
    if not payload:
        return "The launcher bridge did not answer."
    if payload.get("ok"):
        launched = str(payload.get("launched") or cue).strip() or cue
        if cue in ("weather", "chat") and local_answer:
            return local_answer
        if cue == "timer":
            seconds = int(payload_to_send.get("seconds") or 0)
            if seconds:
                return one_sentence(f"Started a {seconds} second timer.")
        return one_sentence(f"Opening {launched}.")
    error = str(payload.get("error") or "unknown cue")
    return one_sentence(f"Launcher bridge error: {error}.")


def one_sentence(text: str) -> str:
    text = ANSI_RE.sub("", text.replace("\r", " ").replace("\n", " "))
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"^(assistant|ai|answer)\s*[:\-]\s*", "", text, flags=re.I).strip()
    if not text:
        return "I could not produce an answer."
    match = re.search(r"(.{1,220}?[.!?])(?:\s|$)", text)
    if match:
        sentence = match.group(1).strip()
    else:
        sentence = " ".join(text.split()[:22]).strip(" ,;:")
    if len(sentence) > 180:
        sentence = sentence[:177].rsplit(" ", 1)[0].rstrip(" ,;:") + "..."
    elif sentence and sentence[-1] not in ".!?":
        sentence += "."
    return sentence or "I could not produce an answer."


def clean_model_output(raw: str) -> str:
    raw = ANSI_RE.sub("", raw.replace("\r", ""))
    lines = raw.splitlines()
    after_prompt = False
    kept: list[str] = []
    for line in lines:
        stripped = line.strip("\x00 ")
        if not stripped:
            continue
        if stripped.startswith(">"):
            after_prompt = True
            continue
        if not after_prompt:
            continue
        low = stripped.lower()
        if stripped.startswith("[") and "generation:" in low:
            break
        if low.startswith(("exiting", "loading model", "build", "model", "ftype", "modalities", "using custom")):
            continue
        if "available commands" in low or stripped.startswith("/"):
            continue
        if set(stripped) <= set("▄█▀ ██\t"):
            continue
        kept.append(stripped)
    return one_sentence(" ".join(kept) if kept else raw)


def ask_local_model(question: str) -> str:
    if not LLAMA.exists():
        return "The local model runner is missing."
    if not MODEL.exists():
        return "The local model file is missing."
    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = str(ROOT / "bin") + ":" + env.get("LD_LIBRARY_PATH", "")
    cmd = [
        str(LLAMA),
        "-m", str(MODEL),
        "-t", "2", "-tb", "2",
        "-c", "256", "-n", "48",
        "--temp", "0.6", "--top-k", "30", "--top-p", "0.9",
        "--repeat-penalty", "1.08",
        "--log-disable", "--no-display-prompt", "--no-perf", "--no-warmup",
        "-st", "--simple-io",
        "-sys", SYSTEM_PROMPT,
        "-p", question,
    ]
    try:
        proc = subprocess.run(cmd, cwd=str(ROOT), text=True, capture_output=True, timeout=120, env=env)
    except subprocess.TimeoutExpired:
        return "I timed out, so try a shorter question."
    except Exception as exc:
        return one_sentence(f"Model error: {exc}")
    return clean_model_output((proc.stdout or "") + "\n" + (proc.stderr or ""))


def pick_fbdev() -> str:
    env = os.environ.get("TYPEPAD_FBDEV") or os.environ.get("CHATBOT_FBDEV")
    if env and Path(env).exists():
        return env
    for fb in sorted(Path("/sys/class/graphics").glob("fb[0-9]*")):
        try:
            name = (fb / "name").read_text().strip()
        except OSError:
            name = ""
        if name.startswith(("fb_", "fbtft")):
            return "/dev/" + fb.name
    return "/dev/fb0"


def fb_size(fbdev: str) -> tuple[int, int]:
    try:
        w, h = (Path("/sys/class/graphics") / Path(fbdev).name / "virtual_size").read_text().strip().split(",")[:2]
        return int(w), int(h)
    except Exception:
        return 320, 240


def rgb565_bytes(surf: pygame.Surface) -> bytes:
    rgb = pygame.image.tostring(surf, "RGB")
    out = bytearray((len(rgb) // 3) * 2)
    j = 0
    for i in range(0, len(rgb), 3):
        r, g, b = rgb[i], rgb[i + 1], rgb[i + 2]
        v = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
        out[j] = v & 0xFF
        out[j + 1] = (v >> 8) & 0xFF
        j += 2
    return bytes(out)


class Display:
    def __init__(self, fbdev: str):
        pygame.init()
        pygame.font.init()
        self.fbdev = fbdev
        self.w, self.h = fb_size(fbdev)
        self.surface = pygame.Surface((self.w, self.h))
        mono = pygame.font.match_font("dejavusansmono,liberationmono,monospace")
        # High contrast, larger text for the small TFT.
        self.font = pygame.font.Font(mono, 20) if mono else pygame.font.Font(None, 22)
        self.bold = pygame.font.Font(mono, 17) if mono else pygame.font.Font(None, 19)
        self.bold.set_bold(True)
        self.small = pygame.font.Font(mono, 12) if mono else pygame.font.Font(None, 13)
        self.line_h = self.font.get_linesize()
        self.char_w = max(8, self.font.size("M")[0])
        self.cols = max(12, (self.w - 16) // self.char_w)
        self._fb = open(fbdev, "wb", buffering=0)

    def write_text(self, text: str, x: int, y: int, color, font=None):
        img = (font or self.font).render(text, True, color)
        self.surface.blit(img, (x, y))

    def render(self, text: str, cursor: int, status: str):
        self.surface.fill((255, 255, 255))
        try:
            hint = Path("/tmp/bt_keyboard_status").read_text().strip() or "BT keyboard ready. Type now."
        except OSError:
            hint = "BT keyboard ready. Type now."
        self.write_text(hint[: self.cols], 5, 5, (0, 0, 0), self.small)
        pygame.draw.line(self.surface, (0, 0, 0), (0, 22), (self.w, 22))

        text_area_top = 32
        max_lines = max(4, (self.h - text_area_top - 8) // self.line_h)
        wrapped = []
        for raw in text.split("\n"):
            wrapped.extend(textwrap.wrap(raw, self.cols, replace_whitespace=False, drop_whitespace=False) or [""])
        visible = wrapped[-max_lines:]
        y = text_area_top
        for line in visible:
            self.write_text(line, 7, y, (0, 0, 0), self.font)
            y += self.line_h

        if cursor >= 0 and int(time.time() * 2) % 2 == 0:
            tail = text[:cursor].split("\n")[-1]
            tail = tail[-self.cols:]
            cx = 7 + self.font.size(tail)[0]
            cy = min(self.h - self.line_h - 4, max(text_area_top, y - self.line_h))
            pygame.draw.line(self.surface, (0, 0, 0), (cx, cy), (cx, cy + self.line_h - 3), 2)
        self._fb.seek(0)
        self._fb.write(rgb565_bytes(self.surface))


class Keyboard:
    def __init__(self):
        self.sel = selectors.DefaultSelector()
        self.files = {}
        self.shift_keys = set()
        self.ctrl = False
        self.caps = False
        self.last_scan = 0.0
        self.last_bt_connect = 0.0
        self.bt_connecting = False
        self.names = []
        self.rescan()

    def _event_name(self, fd) -> str:
        buf = bytearray(256)
        try:
            fcntl.ioctl(fd, EVIOCGNAME(len(buf)), buf, True)
            return bytes(buf).split(b"\0", 1)[0].decode("utf-8", "replace")
        except OSError:
            return "input"

    def rescan(self):
        self.last_scan = time.time()

        # Bluetooth HID devices can disappear and reappear at the same
        # /dev/input/eventN path.  Drop stale/deleted fds so the new keyboard
        # event node is opened and typing resumes after reconnects/restarts.
        for key, f in list(self.files.items()):
            stale = not Path(key).exists()
            try:
                target = os.readlink(f"/proc/self/fd/{f.fileno()}")
                if "(deleted)" in target:
                    stale = True
            except OSError:
                stale = True
            if stale:
                try:
                    self.sel.unregister(f)
                except Exception:
                    pass
                try:
                    f.close()
                except Exception:
                    pass
                self.files.pop(key, None)

        for dev in sorted(Path("/dev/input").glob("event*")):
            key = str(dev)
            if key in self.files:
                continue
            try:
                f = open(dev, "rb", buffering=0)
                os.set_blocking(f.fileno(), False)
                name = self._event_name(f.fileno())
                self.sel.register(f, selectors.EVENT_READ, data=name)
                self.files[key] = f
                if name not in self.names:
                    self.names.append(name)
            except OSError:
                pass

        self.maybe_reconnect_bluetooth()

    def bluetooth_keyboard_present(self) -> bool:
        try:
            blocks = Path("/proc/bus/input/devices").read_text(errors="ignore").split("\n\n")
        except OSError:
            return False
        for block in blocks:
            low = block.lower()
            if "bluetooth keyboard" in low and "handlers=" in low and "event" in low:
                return True
        return False

    def maybe_reconnect_bluetooth(self):
        if self.bluetooth_keyboard_present():
            return
        now = time.time()
        if self.bt_connecting or now - self.last_bt_connect < 12:
            return
        self.last_bt_connect = now
        self.bt_connecting = True

        def worker():
            try:
                devices = subprocess.run(
                    ["bluetoothctl", "devices"],
                    text=True,
                    capture_output=True,
                    timeout=5,
                ).stdout
                for line in devices.splitlines():
                    if "keyboard" not in line.lower():
                        continue
                    parts = line.split()
                    if len(parts) < 2:
                        continue
                    mac = parts[1]
                    subprocess.run(
                        ["timeout", "8", "bluetoothctl", "connect", mac],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=10,
                    )
            except Exception:
                pass
            finally:
                self.bt_connecting = False

        threading.Thread(target=worker, daemon=True).start()

    def char_for(self, code: int) -> str | None:
        shifted = bool(self.shift_keys)
        if code in LETTERS and self.caps:
            shifted = not shifted
        return (SHIFTED if shifted else NORMAL).get(code)

    def poll(self, timeout=0.05):
        if time.time() - self.last_scan > 2:
            self.rescan()
        out = []
        for key, _ in self.sel.select(timeout):
            try:
                data = key.fileobj.read(EVENT_STRUCT.size * 16)
            except (BlockingIOError, OSError):
                continue
            for off in range(0, len(data) - EVENT_STRUCT.size + 1, EVENT_STRUCT.size):
                _, _, typ, code, value = EVENT_STRUCT.unpack(data[off: off + EVENT_STRUCT.size])
                if typ != EV_KEY:
                    continue
                if code in (42, 54):
                    if value == KEY_RELEASE:
                        self.shift_keys.discard(code)
                    else:
                        self.shift_keys.add(code)
                    continue
                if code in (29, 97):
                    self.ctrl = value != KEY_RELEASE
                    continue
                if value not in (KEY_PRESS, KEY_REPEAT):
                    continue
                if code == 58 and value == KEY_PRESS:
                    self.caps = not self.caps
                    continue
                name = KEY_NAMES.get(code)
                if name:
                    out.append((name, None))
                else:
                    ch = self.char_for(code)
                    if ch:
                        out.append(("CHAR", ch))
        return out



def main():
    fbdev = pick_fbdev()
    display = Display(fbdev)
    keyboard = Keyboard()
    lock = threading.RLock()
    state = {
        "input": "",
        "cursor": 0,
        "answer": "",
        "thinking": False,
        "dirty": True,
    }
    last_blink = 0.0

    def start_generation(question: str):
        def worker():
            answer = ask_local_model(question)
            with lock:
                state["answer"] = answer
                state["thinking"] = False
                state["dirty"] = True
        with lock:
            state["input"] = ""
            state["cursor"] = 0
            state["answer"] = "thinking..."
            state["thinking"] = True
            state["dirty"] = True
        threading.Thread(target=worker, daemon=True).start()

    def start_cue_launch(cue: str, payload: dict):
        def worker():
            answer = launch_cue(cue, payload)
            with lock:
                state["answer"] = answer
                state["thinking"] = False
                state["dirty"] = True
        with lock:
            state["input"] = ""
            state["cursor"] = 0
            if cue == "chat" and payload.get("prompt"):
                state["answer"] = "thinking..."
            elif cue == "weather":
                state["answer"] = "checking weather..."
            else:
                state["answer"] = f"launching {cue}..."
            state["thinking"] = True
            state["dirty"] = True
        threading.Thread(target=worker, daemon=True).start()

    while True:
        events = keyboard.poll(0.04)
        with lock:
            for kind, ch in events:
                if state["thinking"]:
                    continue
                if kind == "CHAR" and ch is not None:
                    if state["answer"] and not state["input"]:
                        state["answer"] = ""
                        state["cursor"] = 0
                    i = state["input"]
                    c = state["cursor"]
                    state["input"] = i[:c] + ch + i[c:]
                    state["cursor"] = c + len(ch)
                    state["dirty"] = True
                elif kind == "SPACE":
                    if state["answer"] and not state["input"]:
                        state["answer"] = ""
                    i = state["input"]
                    c = state["cursor"]
                    state["input"] = i[:c] + " " + i[c:]
                    state["cursor"] = c + 1
                    state["dirty"] = True
                elif kind == "TAB":
                    i = state["input"]
                    c = state["cursor"]
                    state["input"] = i[:c] + "  " + i[c:]
                    state["cursor"] = c + 2
                    state["dirty"] = True
                elif kind == "ENTER":
                    question = state["input"].strip()
                    cue_command = cue_command_for_text(question)
                    if cue_command:
                        cue, payload = cue_command
                        start_cue_launch(cue, payload)
                    elif question:
                        start_generation(question)
                    else:
                        state["dirty"] = True
                elif kind == "BACKSPACE":
                    if state["input"] and state["cursor"] > 0:
                        i = state["input"]
                        c = state["cursor"]
                        state["input"] = i[:c - 1] + i[c:]
                        state["cursor"] = c - 1
                    elif state["answer"]:
                        state["answer"] = ""
                        state["cursor"] = 0
                    state["dirty"] = True
                elif kind == "DELETE" and state["cursor"] < len(state["input"]):
                    i = state["input"]
                    c = state["cursor"]
                    state["input"] = i[:c] + i[c + 1:]
                    state["dirty"] = True
                elif kind == "LEFT":
                    state["cursor"] = max(0, state["cursor"] - 1)
                    state["dirty"] = True
                elif kind == "RIGHT":
                    state["cursor"] = min(len(state["input"]), state["cursor"] + 1)
                    state["dirty"] = True
                elif kind == "HOME":
                    state["cursor"] = 0
                    state["dirty"] = True
                elif kind == "END":
                    state["cursor"] = len(state["input"])
                    state["dirty"] = True
                elif kind == "ESC":
                    state["input"] = ""
                    state["answer"] = ""
                    state["cursor"] = 0
                    state["dirty"] = True
                state["input"] = state["input"][-500:]
                state["cursor"] = min(state["cursor"], len(state["input"]))

            now = time.time()
            should_render = state["dirty"] or now - last_blink > 0.5
            if should_render:
                if state["input"] or not state["answer"]:
                    shown = state["input"]
                    shown_cursor = state["cursor"]
                else:
                    shown = state["answer"]
                    shown_cursor = -1
                state["dirty"] = False
            else:
                shown = None
                shown_cursor = 0
        if should_render and shown is not None:
            display.render(shown, shown_cursor, "")
            last_blink = now


if __name__ == "__main__":
    main()
