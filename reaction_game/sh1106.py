# sh1106.py — minimal SH1106 128x64 I2C driver (framebuf-based)
# SH1106 RAM is 132 columns; the 128px panel sits at offset 2.
import framebuf
import time


class SH1106_I2C(framebuf.FrameBuffer):
    def __init__(self, i2c, addr=0x3C, width=128, height=64, rotate180=False):
        self.i2c = i2c
        self.addr = addr
        self.width = width
        self.height = height
        self.pages = height // 8
        self.buffer = bytearray(self.pages * width)
        super().__init__(self.buffer, width, height, framebuf.MONO_VLSB)
        for c in (
            0xAE,        # display off
            0xD5, 0x80,  # clock divide
            0xA8, 0x3F,  # multiplex 64
            0xD3, 0x00,  # display offset 0
            0x40,        # start line 0
            0xAD, 0x8B,  # internal DC-DC on
            0xA0 if rotate180 else 0xA1,  # segment remap
            0xC0 if rotate180 else 0xC8,  # COM scan direction
            0xDA, 0x12,  # COM pins
            0x81, 0xCF,  # contrast
            0xD9, 0xF1,  # precharge
            0xDB, 0x40,  # VCOM deselect
            0xA4,        # display from RAM
            0xA6,        # non-inverted
        ):
            self.cmd(c)
        self.fill(0)
        self.show()
        self.cmd(0xAF)  # display on
        time.sleep_ms(100)

    def cmd(self, c):
        self.i2c.writeto(self.addr, bytes((0x00, c)))

    def contrast(self, v):
        self.cmd(0x81)
        self.cmd(v & 0xFF)

    def invert(self, on):
        self.cmd(0xA7 if on else 0xA6)

    def poweroff(self):
        self.cmd(0xAE)

    def poweron(self):
        self.cmd(0xAF)

    def show(self):
        w = self.width
        for page in range(self.pages):
            self.cmd(0xB0 | page)
            self.cmd(0x02)  # lower column nibble (offset 2)
            self.cmd(0x10)  # higher column nibble
            self.i2c.writeto(self.addr, b"\x40" + self.buffer[page * w:(page + 1) * w])
