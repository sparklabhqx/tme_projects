#!/usr/bin/env python3
"""Minimal 250x122 monochrome canvas and SPI driver for TinyPi's e-paper HAT."""

from __future__ import annotations

import time
import unicodedata

import RPi.GPIO as GPIO
import spidev

PANEL_WIDTH = 122
PANEL_HEIGHT = 250
BUFFER_WIDTH = (PANEL_WIDTH + 7) // 8
WIDTH = 250
HEIGHT = 122
RST = 17
DC = 25
BUSY = 24

FONT = {
    " ": [0, 0, 0, 0, 0],
    "!": [0, 0, 95, 0, 0],
    '"': [0, 7, 0, 7, 0],
    "#": [20, 127, 20, 127, 20],
    "$": [36, 42, 127, 42, 18],
    "%": [35, 19, 8, 100, 98],
    "&": [54, 73, 85, 34, 80],
    "'": [0, 5, 3, 0, 0],
    "(": [0, 28, 34, 65, 0],
    ")": [0, 65, 34, 28, 0],
    "*": [20, 8, 62, 8, 20],
    "+": [8, 8, 62, 8, 8],
    ",": [0, 160, 96, 0, 0],
    "-": [8, 8, 8, 8, 8],
    ".": [0, 96, 96, 0, 0],
    "/": [32, 16, 8, 4, 2],
    ":": [0, 54, 54, 0, 0],
    ";": [0, 86, 54, 0, 0],
    "<": [8, 20, 34, 65, 0],
    "=": [20, 20, 20, 20, 20],
    ">": [65, 34, 20, 8, 0],
    "?": [2, 1, 81, 9, 6],
    "@": [50, 73, 121, 65, 62],
    "[": [0, 127, 65, 65, 0],
    "\\": [2, 4, 8, 16, 32],
    "]": [0, 65, 65, 127, 0],
    "_": [64, 64, 64, 64, 64],
    "|": [0, 0, 127, 0, 0],
    "0": [62, 81, 73, 69, 62],
    "1": [0, 66, 127, 64, 0],
    "2": [66, 97, 81, 73, 70],
    "3": [33, 65, 69, 75, 49],
    "4": [24, 20, 18, 127, 16],
    "5": [39, 69, 69, 69, 57],
    "6": [60, 74, 73, 73, 48],
    "7": [1, 113, 9, 5, 3],
    "8": [54, 73, 73, 73, 54],
    "9": [6, 73, 73, 41, 30],
    "A": [126, 17, 17, 17, 126],
    "B": [127, 73, 73, 73, 54],
    "C": [62, 65, 65, 65, 34],
    "D": [127, 65, 65, 34, 28],
    "E": [127, 73, 73, 73, 65],
    "F": [127, 9, 9, 9, 1],
    "G": [62, 65, 73, 73, 122],
    "H": [127, 8, 8, 8, 127],
    "I": [0, 65, 127, 65, 0],
    "J": [32, 64, 65, 63, 1],
    "K": [127, 8, 20, 34, 65],
    "L": [127, 64, 64, 64, 64],
    "M": [127, 2, 12, 2, 127],
    "N": [127, 4, 8, 16, 127],
    "O": [62, 65, 65, 65, 62],
    "P": [127, 9, 9, 9, 6],
    "Q": [62, 65, 81, 33, 94],
    "R": [127, 9, 25, 41, 70],
    "S": [38, 73, 73, 73, 50],
    "T": [1, 1, 127, 1, 1],
    "U": [63, 64, 64, 64, 63],
    "V": [31, 32, 64, 32, 31],
    "W": [127, 32, 24, 32, 127],
    "X": [99, 20, 8, 20, 99],
    "Y": [7, 8, 112, 8, 7],
    "Z": [97, 81, 73, 69, 67],
}


def safe_text(value: object) -> str:
    text = str(value).replace("°", " DEG ").replace("–", "-").replace("—", "-")
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().upper()


def text_width(value: object, scale: int = 1) -> int:
    value = safe_text(value)
    return max(0, len(value) * 6 * scale - scale)


def ellipsize(value: object, max_chars: int) -> str:
    value = safe_text(value).strip()
    if len(value) <= max_chars:
        return value
    return value[: max(1, max_chars - 3)].rstrip() + "..."


class Canvas:
    def __init__(self, black: bool = False):
        self.buffer = bytearray([0x00 if black else 0xFF] * (BUFFER_WIDTH * PANEL_HEIGHT))

    def pixel(self, x: int, y: int, black: bool = True) -> None:
        if not (0 <= x < WIDTH and 0 <= y < HEIGHT):
            return
        panel_x = PANEL_WIDTH - 1 - y
        panel_y = x
        index = panel_y * BUFFER_WIDTH + panel_x // 8
        mask = 0x80 >> (panel_x % 8)
        if black:
            self.buffer[index] &= ~mask
        else:
            self.buffer[index] |= mask

    def fill_rect(self, x: int, y: int, width: int, height: int, black: bool = True) -> None:
        for yy in range(max(0, y), min(HEIGHT, y + height)):
            for xx in range(max(0, x), min(WIDTH, x + width)):
                self.pixel(xx, yy, black)

    def rect(self, x: int, y: int, width: int, height: int, black: bool = True, thickness: int = 1) -> None:
        self.fill_rect(x, y, width, thickness, black)
        self.fill_rect(x, y + height - thickness, width, thickness, black)
        self.fill_rect(x, y, thickness, height, black)
        self.fill_rect(x + width - thickness, y, thickness, height, black)

    def line(self, x0: int, y0: int, x1: int, y1: int, black: bool = True) -> None:
        dx, sx = abs(x1 - x0), 1 if x0 < x1 else -1
        dy, sy = -abs(y1 - y0), 1 if y0 < y1 else -1
        error = dx + dy
        while True:
            self.pixel(x0, y0, black)
            if x0 == x1 and y0 == y1:
                break
            twice = 2 * error
            if twice >= dy:
                error += dy
                x0 += sx
            if twice <= dx:
                error += dx
                y0 += sy

    def char(self, x: int, y: int, value: str, scale: int = 1, black: bool = True) -> None:
        for column_index, column in enumerate(FONT.get(value.upper(), FONT["?"])):
            for row in range(7):
                if column & (1 << row):
                    self.fill_rect(x + column_index * scale, y + row * scale, scale, scale, black)

    def text(self, x: int, y: int, value: object, scale: int = 1, black: bool = True) -> None:
        for character in safe_text(value):
            self.char(x, y, character, scale, black)
            x += 6 * scale

    def centered_text(self, y: int, value: object, scale: int = 1, black: bool = True) -> None:
        self.text(max(0, (WIDTH - text_width(value, scale)) // 2), y, value, scale, black)

    def right_text(self, right: int, y: int, value: object, scale: int = 1, black: bool = True) -> None:
        self.text(right - text_width(value, scale), y, value, scale, black)

    def progress(self, x: int, y: int, width: int, value: float) -> None:
        value = max(0.0, min(1.0, value))
        self.rect(x, y, width, 7, True)
        self.fill_rect(x + 2, y + 2, int((width - 4) * value), 3, True)


class EPaperDisplay:
    def __init__(self):
        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(RST, GPIO.OUT, initial=GPIO.HIGH)
        GPIO.setup(DC, GPIO.OUT, initial=GPIO.LOW)
        GPIO.setup(BUSY, GPIO.IN)
        self.spi = spidev.SpiDev()
        self.spi.open(0, 0)
        self.spi.max_speed_hz = 8_000_000
        self.spi.mode = 0
        self.closed = False

    def _write(self, data) -> None:
        self.spi.writebytes(list(data))

    def command(self, value: int) -> None:
        GPIO.output(DC, 0)
        self._write([value])

    def data(self, value) -> None:
        GPIO.output(DC, 1)
        if isinstance(value, int):
            self._write([value])
        else:
            for start in range(0, len(value), 4096):
                self._write(value[start : start + 4096])

    def wait(self, timeout: float = 30.0) -> float:
        started = time.monotonic()
        while GPIO.input(BUSY) == 1 and time.monotonic() - started < timeout:
            time.sleep(0.01)
        return time.monotonic() - started

    def initialize(self) -> None:
        GPIO.output(RST, 1)
        time.sleep(0.02)
        GPIO.output(RST, 0)
        time.sleep(0.01)
        GPIO.output(RST, 1)
        time.sleep(0.02)
        self.wait(5)
        self.command(0x12)
        self.wait(10)
        self.command(0x01)
        self.data([0xF9, 0, 0])
        self.command(0x11)
        self.data(0x03)
        self._window()
        self.command(0x3C)
        self.data(0x05)
        self.command(0x18)
        self.data(0x80)

    def _window(self) -> None:
        self.command(0x44)
        self.data([0, BUFFER_WIDTH - 1])
        self.command(0x45)
        self.data([0, 0, (PANEL_HEIGHT - 1) & 0xFF, (PANEL_HEIGHT - 1) >> 8])
        self.command(0x4E)
        self.data(0)
        self.command(0x4F)
        self.data([0, 0])

    def show(self, canvas: Canvas, fast: bool = False) -> float:
        self._window()
        self.command(0x24)
        self.data(canvas.buffer)
        self.command(0x22)
        self.data(0xFF if fast else 0xF7)
        self.command(0x20)
        return self.wait(30)

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        try:
            self.command(0x10)
            self.data(1)
        finally:
            self.spi.close()
            GPIO.cleanup()


def paint(canvas: Canvas, fast: bool = False) -> float:
    display = EPaperDisplay()
    try:
        display.initialize()
        return display.show(canvas, fast=fast)
    finally:
        display.close()
