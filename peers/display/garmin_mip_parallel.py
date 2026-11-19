# Garmin FR245 memory-in-pixel display, 6-bit parallel interface, as a bus-less Scripted.ScriptedGpioPeer
# that samples the pads a FlexIO model drives and assembles the framebuffer.
#
# What the FR245 firmware programs (MK28 FLEXIO0, observed on the pyrite K28 model, not from a panel
# datasheet; the panel part is unidentified):
#   FXIO 2..7   six data pins, one 6-bit pixel per pixel clock (shifter 0, PWIDTH, timer 7)
#   FXIO 27     free-running pixel clock (timer 0, 32 FlexIO clocks per period)
#   FXIO 14     line clock: one period per 244 pixel clocks (timer 2)
#   FXIO 13     one pixel-clock-wide pulse at each line-clock edge (shifter 2)
#   FXIO 28     frame window: high for 31 line periods, low for 1, repeating (shifter 4, timer 5)
#   FXIO 12, 17 control (alternating-bit burst, ENB-like pulse): not used here
# The firmware DMAs the 244-byte-stride framebuffer (242 lines x 61 words, 4 pixels in the low 24 bits
# of each word, pixel 0 in bits 5:0) into the shifter, so the pixel stream is the framebuffer: pixel n
# of the frame is the n-th sample of the data pins taken on the pixel-clock edge.
#
# Framing (derived from the observed waveforms, not from a datasheet): a frame session starts at the
# first FXIO 14 edge after SESSION_GAP_US without one (the module was just enabled); pixel sampling
# starts at the first FXIO 13 rising edge while FXIO 28 is high, after `skip` clock edges, and ends after
# stride*lines samples.
#
# Wiring: ctx line number = FXIO pin number (numberOfGpios: 32), `flexio0: <32+n> -> disp@<n>`.
# config keys (all optional): "png_dir" (a PNG per frame, frame_<n>_<ms>ms.png), "width" 240, "height" 240,
#   "stride" 244, "lines" 242, "edge" 0 (sample on the pixel-clock falling edge; 1 = rising),
#   "skip" 0, "order" "rgb" (pixel bits 5:4, 3:2, 1:0 are R, G, B; "bgr" reverses).
# Not modelled: panel refresh timing, the data-pin/clock setup time, VCOM/polarity pins, the 4 pad pixels
# (dropped by the crop).
import os
import struct
import zlib

DATA0, HST, LINE, PIXCLK, FRAME = 2, 13, 14, 27, 28
SESSION_GAP_US = 1000


def png_rgb(width, height, rows):
    """8-bit RGB PNG from `rows`, one bytes object of width*3 per row."""
    raw = b"".join(b"\0" + r for r in rows)

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


# Line packing, from the firmware's packer at 0xbef5c (source 240 x 1 B/pixel -> 244 B/line): pixels are
# taken in pairs (a, b = pixels 2m, 2m+1) and each pair becomes one byte in each of two planes:
#   left plane  byte 1+m   : bit 2i = a.bit(2i+1), bit 2i+1 = b.bit(2i+1)   (the high bit of each channel)
#   right plane byte 123+m : bit 2i = a.bit(2i),   bit 2i+1 = b.bit(2i)     (the low bit of each channel)
# for i = 0..2; bytes 0, 121, 122, 243 are zero.
LEFT, RIGHT = 1, 123


def pack_line(pix):
    out = bytearray(244)
    for m in range(len(pix) // 2):
        a, b = pix[2 * m], pix[2 * m + 1]
        for i in range(3):
            out[LEFT + m] |= (a >> (2 * i + 1) & 1) << 2 * i | (b >> (2 * i + 1) & 1) << (2 * i + 1)
            out[RIGHT + m] |= (a >> 2 * i & 1) << 2 * i | (b >> 2 * i & 1) << (2 * i + 1)
    return bytes(out)


def unpack_line(line, w):
    pix = []
    for m in range(w // 2):
        l, r = line[LEFT + m], line[RIGHT + m]
        for k in range(2):
            pix.append(sum((l >> (2 * i + k) & 1) << (2 * i + 1) | (r >> (2 * i + k) & 1) << 2 * i for i in range(3)))
    return pix


def selftest():
    pix = [(7 * x + 3) & 63 for x in range(240)]
    line = pack_line(pix)
    assert unpack_line(line, 240) == pix
    assert not (line[0] or line[121] or line[122] or line[243])


class Slave:
    def __init__(self, ctx):
        cfg = getattr(ctx, "config", {})
        self.ctx = ctx
        self.w, self.h = int(cfg.get("width", 240)), int(cfg.get("height", 240))
        self.stride, self.lines = int(cfg.get("stride", 244)), int(cfg.get("lines", 242))
        self.edge, self.skip0 = bool(cfg.get("edge", 0)), int(cfg.get("skip", 0))
        self.bgr = cfg.get("order", "rgb") == "bgr"
        self.png_dir = cfg.get("png_dir")
        self.lv = [False] * 32
        self.t_line = -SESSION_GAP_US - 1
        self.fb = bytearray(self.stride * self.lines)
        self.frames = 0
        self._session()

    def _session(self):
        self.pix = None  # None: waiting for the stream to start
        self.skip = self.skip0
        self.done = False
        self.n = 0

    def on_gpio(self, line, level):
        level = bool(level)
        was = self.lv[line]
        self.lv[line] = level
        if line == LINE:
            if self.ctx.now_us - self.t_line > SESSION_GAP_US:
                self._session()
            self.t_line = self.ctx.now_us
        elif line == HST and level and not was and self.pix is None and not self.done and self.lv[FRAME]:
            self.pix = 0
        elif line == PIXCLK and level == self.edge and self.pix is not None:
            if self.skip:
                self.skip -= 1
                return
            self.fb[self.pix] = sum(self.lv[DATA0 + i] << i for i in range(6))
            self.pix += 1
            if self.pix == self.stride * self.lines:
                self.pix, self.done = None, True
                self._frame_done()

    def pixels(self, y):
        """The w pixels (6-bit RGB222 each) of line y, undoing the firmware's packer."""
        return unpack_line(self.fb[y * self.stride:(y + 1) * self.stride], self.w)

    def rgb_rows(self):
        out = []
        for y in range(min(self.h, self.lines)):
            row = bytearray()
            for v in self.pixels(y):
                r, g, b = (v >> 4 & 3) * 85, (v >> 2 & 3) * 85, (v & 3) * 85
                row += bytes((b, g, r) if self.bgr else (r, g, b))
            out.append(bytes(row))
        return out

    def _frame_done(self):
        self.frames += 1
        if self.png_dir:
            name = "frame_%03d_%dms.png" % (self.frames, self.ctx.now_us // 1000)
            with open(os.path.join(self.png_dir, name), "wb") as f:
                f.write(png_rgb(self.w, min(self.h, self.lines), self.rgb_rows()))


if __name__ == "__main__":
    selftest()
    print("ok")
