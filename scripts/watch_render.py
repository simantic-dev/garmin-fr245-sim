#!/usr/bin/env python3
"""Render out/frames/*.png (240x240) as round frames and a Forerunner 245 hero GIF/PNG. Pillow only.
Usage: python3 scripts/watch_render.py [frames_dir] [out_dir]"""
import glob, os, re, sys
from PIL import Image, ImageDraw

FR, OUT = (sys.argv + [None, None])[1:3]
FR, OUT = FR or "out/frames", OUT or "docs/screens"
W, H, CX, CY = 480, 600, 240, 300
# Button order is a GUESS from firmware behaviour: PTD10 scrolls the list down (DOWN), PTD1 scrolls back (UP);
# the rest follow the FR245 layout (left: LIGHT, UP, DOWN; right: START, BACK) and are unconfirmed.
BUTTONS = {  # name: (side, dy, label)
    "PTC11": ("L", -70, "LIGHT?"), "PTD1": ("L", 0, "UP"), "PTD10": ("L", 70, "DOWN"),
    "PTA20": ("R", -45, "START?"), "PTA22": ("R", 45, "BACK?")}
# (name, scenario time in s): the last display frame at or before that time. Times are from sim/overlay.board's button script.
SCREENS = [("boot-logo", 2.8), ("language", 6.3), ("pair-with-phone", 9.8), ("download-garmin-connect-mobile", 11.5),
           ("pair-with-phone-back", 13.5), ("pair-no-highlighted", 16.6), ("distance-units", 20.5), ("time-format", 22.8),
           ("gender", 25.5), ("birth-year", 30.0), ("height", 37.0), ("weight", 42.0), ("set-time-use-gps", 50.5),
           ("set-time-manual", 52.9), ("set-hours", 55.0), ("set-minutes", 57.5), ("set-year", 67.0), ("set-month", 72.8),
           ("set-day", 75.0), ("watch-face", 80.0), ("run-glance", 86.0)]

def circle(img, d):
    img = img.convert("RGB").resize((d, d), Image.NEAREST)
    m = Image.new("L", (d * 4, d * 4), 0); ImageDraw.Draw(m).ellipse((0, 0, d * 4 - 1, d * 4 - 1), fill=255)
    out = Image.new("RGBA", (d, d)); out.paste(img, mask=m.resize((d, d), Image.LANCZOS)); return out

def watch(frame, pressed=None):
    bg = (245, 245, 245, 255)
    im = Image.new("RGBA", (W, H), bg); d = ImageDraw.Draw(im)
    d.rounded_rectangle((CX - 70, 0, CX + 70, CY - 190), 12, fill=(60, 62, 66))        # strap stubs
    d.rounded_rectangle((CX - 70, CY + 190, CX + 70, H), 12, fill=(60, 62, 66))
    for n, (side, dy, _) in BUTTONS.items():
        x = CX - 205 if side == "L" else CX + 190
        col = (255, 140, 0) if n == pressed else (95, 98, 104)
        d.rounded_rectangle((x, CY + dy - 14, x + 15, CY + dy + 14), 5, fill=col)
    d.ellipse((CX - 200, CY - 200, CX + 200, CY + 200), fill=(38, 40, 44))              # case
    d.ellipse((CX - 178, CY - 178, CX + 178, CY + 178), fill=(14, 14, 16))              # bezel
    sc = circle(frame, 300)
    im.alpha_composite(sc, (CX - 150, CY - 150))
    return im.convert("RGB")

if __name__ == "__main__":
    fs = sorted(glob.glob(f"{FR}/*.png"))
    t = [int(re.search(r"_(\d+)ms", f).group(1)) / 1000 for f in fs]
    pick = lambda ts: Image.open(fs[max(i for i in range(len(fs)) if t[i] <= ts)])
    os.makedirs(OUT, exist_ok=True)
    seq = []
    for n, (name, ts) in enumerate(SCREENS, 1):
        circle(pick(ts), 240).save(f"{OUT}/{n:02d}-{name}-{ts:.0f}s.png")
        seq.append(watch(pick(ts)).quantize(64))
    watch(pick(80.0)).save(f"{OUT}/hero.png")
    seq[0].save(f"{OUT}/hero.gif", save_all=True, append_images=seq[1:], duration=[1000] * len(seq), loop=0, optimize=True)
