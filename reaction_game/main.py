# main.py — Reaction game + WiFi scoreboard: Pico W + SH1106 OLED + 2 buttons
#
# LEFT button:  GP14 (physical pin 19) -> GND  (BLUE cap)
# RIGHT button: GP15 (physical pin 20) -> GND  (RED cap)
# GP16 (pin 21) is retired: it reads grounded even with nothing attached.
# OLED on GP4/GP5, SDA/SCL orientation auto-detected, panel mounted upside-down.
#
# Serves the scoreboard at http://reaction.local (mDNS) / the printed IP.
# Valid round times go to scores.json on flash; the game works offline too.
from machine import Pin, I2C, SoftI2C
import framebuf
import json
import network
import random
import time
import asyncio
import sh1106
import secrets

SCORES_FILE = "scores.json"
TZ_OFFSET = 2 * 3600  # Europe/Berlin (summer time; adjust in winter)
RESPONSE_CAP_MS = 3000


def make_bus():
    i2c = I2C(0, sda=Pin(4), scl=Pin(5), freq=400_000)
    if 0x3C in i2c.scan():
        return i2c
    s = SoftI2C(sda=Pin(5), scl=Pin(4), freq=400_000)
    if 0x3C in s.scan():
        return s
    raise RuntimeError("no OLED found on GP4/GP5")


def big_text(oled, s, x, y, scale=3, c=1):
    w = len(s) * 8
    buf = bytearray(w)
    fb = framebuf.FrameBuffer(buf, w, 8, framebuf.MONO_VLSB)
    fb.text(s, 0, 0, 1)
    for cx in range(w):
        col = buf[cx]
        for cy in range(8):
            if col & (1 << cy):
                oled.fill_rect(x + cx * scale, y + cy * scale, scale, scale, c)


oled = sh1106.SH1106_I2C(make_bus(), rotate180=True)
btn_l = Pin(14, Pin.IN, Pin.PULL_UP)
btn_r = Pin(15, Pin.IN, Pin.PULL_UP)
led = Pin("LED", Pin.OUT)

wlan = None
net_ip = None

# ---------- score keeping ----------

scores = {"best": None, "count": 0, "sum": 0, "top": []}
recent = []  # last 30 valid rounds, newest first: [ms, "dd.mm hh:mm"]


def load_scores():
    global scores
    try:
        with open(SCORES_FILE) as f:
            scores = json.load(f)
    except (OSError, ValueError):
        try:  # migrate the old best.txt
            with open("best.txt") as f:
                b = int(f.read().strip())
            scores["best"] = b
            scores["top"] = [[b, "-"]]
        except (OSError, ValueError):
            pass


def save_scores():
    try:
        with open(SCORES_FILE, "w") as f:
            json.dump(scores, f)
    except OSError:
        pass


def timestamp():
    if time.time() < 1_000_000_000:  # clock never synced
        return "-"
    t = time.localtime(time.time() + TZ_OFFSET)
    return "%02d.%02d. %02d:%02d" % (t[2], t[1], t[3], t[4])


def record(ms):
    ts = timestamp()
    scores["count"] += 1
    scores["sum"] += ms
    recent.insert(0, [ms, ts])
    del recent[30:]
    top = scores["top"]
    top.append([ms, ts])
    top.sort(key=lambda e: e[0])
    del top[10:]
    new_best = scores["best"] is None or ms < scores["best"]
    if new_best:
        scores["best"] = ms
    save_scores()
    return new_best


# ---------- game ----------

def pressed():
    l, r = not btn_l.value(), not btn_r.value()
    return l or r, l, r


async def wait_release():
    t0 = time.ticks_ms()
    shown = None
    while True:
        p, l, r = pressed()
        if not p:
            break
        # held >1.5 s: almost certainly a wiring short, not a finger
        if time.ticks_diff(time.ticks_ms(), t0) > 1500 and shown != (l, r):
            shown = (l, r)
            oled.fill(0)
            oled.text("BUTTON STUCK!", 12, 8)
            if l:
                oled.text("BLUE (GP14) low", 0, 26)
            if r:
                oled.text("RED (GP15) low", 0, 36)
            oled.text("check the wiring", 0, 52)
            oled.show()
        await asyncio.sleep_ms(20)
    await asyncio.sleep_ms(30)  # debounce
    if shown:
        await message(["OK - fixed!"], 800)


async def wait_press():
    while True:
        p, l, r = pressed()
        if p:
            await asyncio.sleep_ms(20)
            return l
        await asyncio.sleep_ms(10)


async def message(lines, hold_ms=0):
    oled.fill(0)
    y = (64 - len(lines) * 12) // 2
    for i, ln in enumerate(lines):
        oled.text(ln, (128 - len(ln) * 8) // 2, y + i * 12)
    oled.show()
    if hold_ms:
        await asyncio.sleep_ms(hold_ms)


def idle_screen():
    oled.fill(0)
    big_text(oled, "REACTION", 0, 2, 2)
    oled.text("BLUE=L  RED=R", 0, 24)
    if scores["best"] is not None:
        oled.text("best: %d ms" % scores["best"], 0, 36)
    if recent:
        n = min(5, len(recent))
        avg = sum(e[0] for e in recent[:n]) // n
        oled.text("avg: %d ms" % avg, 0, 45)
    oled.text("press to play", 0, 56)
    oled.show()


async def play_round():
    oled.fill(0)
    oled.text("wait for it...", 8, 28)
    oled.show()
    delay = random.randint(1500, 3500)
    t_end = time.ticks_add(time.ticks_ms(), delay)
    while time.ticks_diff(t_end, time.ticks_ms()) > 0:
        if pressed()[0]:
            await message(["TOO EARLY!"], 900)
            await wait_release()
            return
        await asyncio.sleep_ms(5)

    side_left = random.getrandbits(1)
    oled.fill(0)
    if side_left:
        oled.fill_rect(0, 0, 64, 64, 1)
        big_text(oled, "L", 14, 12, 5, 0)
        oled.text("BLUE", 80, 22, 1)
        oled.text("<--", 84, 34, 1)
    else:
        oled.fill_rect(64, 0, 64, 64, 1)
        big_text(oled, "R", 78, 12, 5, 0)
        oled.text("RED", 24, 22, 1)
        oled.text("-->", 20, 34, 1)
    led.on()
    oled.show()

    # tight blocking wait for timing precision (capped at RESPONSE_CAP_MS)
    t0 = time.ticks_us()
    hit_left = None
    while hit_left is None:
        if not btn_l.value():
            hit_left = True
        elif not btn_r.value():
            hit_left = False
        elif time.ticks_diff(time.ticks_us(), t0) > RESPONSE_CAP_MS * 1000:
            break
    dt_ms = time.ticks_diff(time.ticks_us(), t0) // 1000
    led.off()

    if hit_left is None:
        await message(["TOO SLOW!", "(>3 s)"], 900)
        return
    if hit_left != bool(side_left):
        await message(["WRONG SIDE!"], 900)
        await wait_release()
        return

    new_best = record(dt_ms)

    oled.fill(0)
    digits = "%d" % dt_ms
    x0 = max(0, (128 - (len(digits) * 24 + 18)) // 2)
    big_text(oled, digits, x0, 8, 3)
    oled.text("ms", x0 + len(digits) * 24 + 2, 24)
    if new_best:
        oled.text("NEW BEST!", 28, 40)
    elif scores["best"] is not None:
        oled.text("best: %d ms" % scores["best"], 16, 40)
    oled.text("press: go again", 4, 56)
    oled.show()
    await wait_release()
    await wait_press()
    await wait_release()


async def game_task():
    await message(["REACTION GAME", "", "get ready"], 800)
    await wait_release()
    while True:
        idle_screen()
        await wait_press()
        random.seed(time.ticks_us())  # human press timing = entropy
        await wait_release()
        await play_round()


# ---------- network + web server ----------

async def net_task():
    global wlan, net_ip
    try:
        network.hostname("reaction")
    except (AttributeError, ValueError):
        pass
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    wlan.connect(secrets.WIFI_SSID, secrets.WIFI_PASS)
    for _ in range(40):
        if wlan.isconnected():
            break
        await asyncio.sleep_ms(500)
    if not wlan.isconnected():
        print("wifi: offline (game still works)")
        return
    net_ip = wlan.ifconfig()[0]
    print("wifi: connected,", net_ip, "-> http://reaction.local")
    try:
        import ntptime
        ntptime.settime()
        print("time synced:", timestamp())
    except OSError:
        print("ntp sync failed")
    await asyncio.start_server(handle_client, "0.0.0.0", 80)


def data_json():
    avg = scores["sum"] // scores["count"] if scores["count"] else None
    rssi = None
    try:
        rssi = wlan.status("rssi") if wlan and wlan.isconnected() else None
    except (OSError, ValueError):
        pass
    return json.dumps({
        "best": scores["best"],
        "avg": avg,
        "count": scores["count"],
        "top": scores["top"],
        "recent": recent,
        "rssi": rssi,
    })


async def send_file(writer, name):
    with open(name, "rb") as f:
        while True:
            chunk = f.read(1024)
            if not chunk:
                break
            writer.write(chunk)
            await writer.drain()


async def handle_client(reader, writer):
    try:
        req = await reader.readline()
        while True:
            line = await reader.readline()
            if not line or line == b"\r\n":
                break
        parts = req.split(b" ")
        path = parts[1] if len(parts) > 1 else b"/"
        if path == b"/data.json":
            body = data_json()
            writer.write(b"HTTP/1.0 200 OK\r\nContent-Type: application/json\r\n"
                         b"Cache-Control: no-store\r\n\r\n")
            writer.write(body.encode())
            await writer.drain()
        elif path in (b"/", b"/index.html"):
            writer.write(b"HTTP/1.0 200 OK\r\nContent-Type: text/html\r\n\r\n")
            await send_file(writer, "index.html")
        elif path == b"/three.js":
            # pre-gzipped on flash; browsers decompress transparently
            writer.write(b"HTTP/1.0 200 OK\r\nContent-Type: text/javascript\r\n"
                         b"Content-Encoding: gzip\r\n"
                         b"Cache-Control: public, max-age=604800, immutable\r\n\r\n")
            await send_file(writer, "three.js.gz")
        else:
            writer.write(b"HTTP/1.0 404 Not Found\r\n\r\nnope")
            await writer.drain()
    except OSError:
        pass
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except OSError:
            pass


async def main():
    load_scores()
    asyncio.create_task(net_task())
    await game_task()


asyncio.run(main())
