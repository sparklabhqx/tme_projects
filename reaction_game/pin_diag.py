# pin_diag.py — live GPIO monitor on the OLED.
# Shows which pins read LOW right now and which were LOW last.
# All external GPIOs get internal pull-ups; the I2C pair (GP4/GP5) is excluded.
from machine import Pin, SoftI2C
import time
import sh1106

bus = SoftI2C(sda=Pin(5), scl=Pin(4), freq=400_000)
oled = sh1106.SH1106_I2C(bus, rotate180=True)
watch = [g for g in list(range(0, 23)) + [26, 27, 28] if g not in (4, 5)]
pins = {g: Pin(g, Pin.IN, Pin.PULL_UP) for g in watch}
time.sleep_ms(50)

last = []
while True:
    # sample tightly between screen redraws so short taps get caught
    low = set()
    t_end = time.ticks_add(time.ticks_ms(), 120)
    while time.ticks_diff(t_end, time.ticks_ms()) > 0:
        for g, p in pins.items():
            if not p.value():
                low.add(g)
    low = sorted(low)
    if low:
        last = low[:]
        print("low:", low)
    oled.fill(0)
    oled.text("PIN DIAGNOSTIC", 8, 0)
    oled.text("low now:", 0, 16)
    oled.text(" ".join("GP%d" % g for g in low) or "-", 0, 26)
    oled.text("last low:", 0, 42)
    oled.text(" ".join("GP%d" % g for g in last) or "-", 0, 52)
    oled.show()
