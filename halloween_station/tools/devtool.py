#!/usr/bin/env python3
"""Talk to the Halloween Arcade over USB serial: screenshots + touch injection.

  devtool.py shot out.png              capture the displayed frame
  devtool.py tap X Y [--shot out.png]  tap, then optionally capture
  devtool.py hold X Y / release
  devtool.py info
  devtool.py film out_%02d.png N --delay 0.4   capture a sequence
"""
import sys, time, argparse, glob
import serial
from PIL import Image

W, H = 480, 800          # panel (portrait) framebuffer

def port():
    p = sorted(glob.glob("/dev/cu.usbmodem*"))
    if not p:
        sys.exit("no /dev/cu.usbmodem* found")
    return p[0]

def open_ser():
    s = serial.Serial(port(), 115200, timeout=6)
    time.sleep(0.15)
    s.reset_input_buffer()
    return s

def read_until(s, token, limit=400000):
    buf = b""
    while token not in buf:
        chunk = s.read(4096)
        if not chunk:
            return buf
        buf += chunk
        if len(buf) > limit:
            return buf
    return buf

def shot(s, path):
    s.reset_input_buffer()
    s.write(b"S\n")
    # header
    hdr = b""
    t0 = time.time()
    while b"FBSHOT" not in hdr:
        c = s.read(1)
        if not c:
            sys.exit("no FBSHOT header (is the sketch running?)")
        hdr += c
        if time.time() - t0 > 8:
            sys.exit("timeout waiting for header")
    while not hdr.endswith(b"\n"):
        hdr += s.read(1)
    need = W * H * 2
    data = b""
    while len(data) < need:
        chunk = s.read(need - len(data))
        if not chunk:
            break
        data += chunk
    if len(data) < need:
        sys.exit(f"short frame: {len(data)}/{need}")
    read_until(s, b"FBDONE", 64)

    img = Image.new("RGB", (W, H))
    px = img.load()
    for y in range(H):
        row = data[y * W * 2:(y + 1) * W * 2]
        for x in range(W):
            v = row[x * 2] | (row[x * 2 + 1] << 8)
            px[x, y] = (((v >> 11) & 0x1F) << 3, ((v >> 5) & 0x3F) << 2, (v & 0x1F) << 3)
    # portrait (px,py) = (479-y, x)  ->  landscape 800x480
    img = img.transpose(Image.Transpose.ROTATE_270).transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    img = img.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    img.save(path)
    print("saved", path, img.size)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd")
    ap.add_argument("args", nargs="*")
    ap.add_argument("--shot")
    ap.add_argument("--delay", type=float, default=0.4)
    a = ap.parse_args()
    s = open_ser()

    if a.cmd == "shot":
        shot(s, a.args[0] if a.args else "shot.png")
    elif a.cmd == "tap":
        s.write(f"T {a.args[0]} {a.args[1]}\n".encode())
        time.sleep(a.delay)
        if a.shot:
            shot(s, a.shot)
    elif a.cmd == "hold":
        s.write(f"H {a.args[0]} {a.args[1]}\n".encode())
        time.sleep(a.delay)
        if a.shot:
            shot(s, a.shot)
    elif a.cmd == "release":
        s.write(b"U\n")
    elif a.cmd == "info":
        s.reset_input_buffer()
        s.write(b"I\n")
        print(read_until(s, b"\n", 400).decode(errors="replace").strip())
    elif a.cmd == "film":
        pat, n = a.args[0], int(a.args[1])
        for i in range(n):
            shot(s, pat % i)
            time.sleep(a.delay)
    else:
        sys.exit("unknown command")

if __name__ == "__main__":
    main()
