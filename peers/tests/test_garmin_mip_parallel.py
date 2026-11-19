"""garmin_mip_parallel peer self-tests: a synthetic FlexIO pin stream, no firmware, no simulator.

    python3 -m pytest peers/tests/test_garmin_mip_parallel.py
"""
import importlib.util
import struct
import zlib
from pathlib import Path

PEER = Path(__file__).resolve().parent.parent / "display" / "garmin_mip_parallel.py"
spec = importlib.util.spec_from_file_location("garmin_mip_parallel", PEER)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class Ctx:
    def __init__(self, config):
        self.config = config
        self.now_us = 10_000


def drive(p, ctx, pixels, lines=2, stride=4):
    """Line clock, frame window, one HST pulse, then `pixels` on the data pins at each clock fall."""
    p.on_gpio(mod.LINE, True)
    p.on_gpio(mod.FRAME, True)
    ctx.now_us += 26
    p.on_gpio(mod.LINE, False)
    p.on_gpio(mod.HST, True)
    p.on_gpio(mod.HST, False)
    for v in pixels:
        p.on_gpio(mod.PIXCLK, True)
        for i in range(6):
            p.on_gpio(mod.DATA0 + i, bool(v >> i & 1))
        p.on_gpio(mod.PIXCLK, False)


def test_stream_assembles_rows_and_crops_pad_pixels(tmp_path):
    ctx = Ctx({"width": 2, "height": 1, "stride": 244, "lines": 1, "png_dir": str(tmp_path)})
    p = mod.Slave(ctx)
    pixels = [0b110000, 0b001100]  # R, G
    drive(p, ctx, list(mod.pack_line(pixels)))
    assert p.pixels(0) == pixels
    assert p.frames == 1
    png = next(tmp_path.glob("frame_001_*.png")).read_bytes()
    w, h, depth, ctype = struct.unpack(">IIBB", png[16:26])
    assert (w, h, depth, ctype) == (2, 1, 8, 2)
    start = png.index(b"IDAT") + 4
    raw = zlib.decompress(png[start:png.index(b"IEND") - 8])
    assert raw[1:7] == bytes([255, 0, 0, 0, 255, 0])


def test_pixels_ignored_before_hst_while_frame_window_high():
    ctx = Ctx({"stride": 4, "lines": 2})
    p = mod.Slave(ctx)
    p.on_gpio(mod.LINE, True)
    for v in (5, 6):
        p.on_gpio(mod.PIXCLK, True)
        p.on_gpio(mod.DATA0, bool(v & 1))
        p.on_gpio(mod.PIXCLK, False)
    assert p.pix is None and not any(p.fb)


def test_new_session_after_line_clock_gap_restarts_frame():
    ctx = Ctx({"width": 3, "stride": 4, "lines": 2})
    p = mod.Slave(ctx)
    drive(p, ctx, list(range(8)))
    assert p.done
    ctx.now_us += 5000
    p.on_gpio(mod.LINE, False)
    assert not p.done and p.pix is None
    drive(p, ctx, [7] * 8)
    assert p.frames == 2 and list(p.fb) == [7] * 8
