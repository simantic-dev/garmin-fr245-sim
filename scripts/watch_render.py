#!/usr/bin/env python3
"""Render out/frames/*.png (240x240) as round frames and a Forerunner 245 hero GIF/PNG. Pillow only.
Usage: python3 scripts/watch_render.py [frames_dir] [out_dir]"""
import glob, math, os, re, sys
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

FR, OUT = (sys.argv + [None, None])[1:3]
FR, OUT = FR or "out/frames", OUT or "docs/screens"
W, H, CX, CY = 522, 678, 261, 339  # case 400 px = 42 mm (9.5 px/mm), display 288 px = 1.2 in, strap 20 mm
# Buttons in the Forerunner 245 layout: left LIGHT (top), UP, DOWN (bottom); right START (top, coloured ring), BACK (bottom).
# name: (side, angle in degrees above the horizontal axis, label, bezel word, confirmed)
# PTD10, PTA20 and PTD1 are assigned from the firmware's behaviour: PTD10 selects (and opens the run glance from the watch
# face) = START, PTA20 moves the highlight down = DOWN, PTD1 goes back (nothing on the watch face) = BACK. PTA22 (UP) and
# PTC11 (LIGHT) are the two left over and are guesses.
BUTTONS = {
    "PTC11": ("L", 28, "LIGHT?", "LIGHT"), "PTA22": ("L", 0, "UP?", "UP"), "PTA20": ("L", -28, "DOWN", "DOWN"),
    "PTD10": ("R", 30, "START", "START"), "PTD1": ("R", -30, "BACK", "BACK")}
# (name, scenario time in s): the last display frame at or before that time. Times are from sim/overlay.board's button script.
SCREENS = [("boot-logo", 2.8), ("language", 6.3), ("pair-with-phone", 9.8), ("download-garmin-connect-mobile", 11.5),
           ("pair-with-phone-back", 13.5), ("pair-no-highlighted", 16.6), ("distance-units", 20.5), ("time-format", 22.8),
           ("gender", 25.5), ("birth-year", 30.0), ("height", 37.0), ("weight", 42.0), ("set-time-use-gps", 50.5),
           ("set-time-manual", 52.9), ("set-hours", 55.0), ("set-minutes", 57.5), ("set-year", 67.0), ("set-month", 72.8),
           ("set-day", 75.0), ("watch-face", 80.0), ("run-glance", 86.0)]

S, R, FW, FH = 3, 1, W, H  # S: body drawn at S x design size (design = 522x678 units); R: output scale; FW x FH: output size


def configure(r=1, ss=3):
    """Output scale r (1 = GIF size, 5/3 = HD: the 288-unit display is then exactly 480 px = 2 x 240). Drops cached bodies."""
    global S, R, FW, FH
    R, S, FW, FH = r, round(r * ss), round(W * r), round(H * r)
    _cache.clear()


def Zi(v):
    return int(round(v))
ACCENT = (255, 150, 40)
START_RING = (40, 190, 175)  # START's coloured ring (generic accent)


def circle(img, d):
    img = img.convert("RGB").resize((d, d), Image.NEAREST)
    m = Image.new("L", (d * 4, d * 4), 0); ImageDraw.Draw(m).ellipse((0, 0, d * 4 - 1, d * 4 - 1), fill=255)
    out = Image.new("RGBA", (d, d)); out.paste(img, mask=m.resize((d, d), Image.LANCZOS)); return out


def grad(size, stops, angle=0):
    """Linear gradient: stops = [(pos 0..1, (r,g,b))]; angle 0 = top to bottom, 90 = left to right, 45 = diagonal."""
    n = 256
    strip = Image.new("RGB", (1, n))
    for i in range(n):
        t = i / (n - 1)
        for (p0, c0), (p1, c1) in zip(stops, stops[1:]):
            if p0 <= t <= p1:
                u = (t - p0) / (p1 - p0 or 1)
                strip.putpixel((0, i), tuple(round(a + (b - a) * u) for a, b in zip(c0, c1))); break
    big = max(size) * 2
    g = strip.resize((big, big), Image.BILINEAR)
    g = g.rotate(-angle, resample=Image.BICUBIC)
    return g.crop(((big - size[0]) // 2, (big - size[1]) // 2, (big + size[0]) // 2, (big + size[1]) // 2))


def disc(size, r, cx=CX, cy=CY, k=None):
    k = k or S
    m = Image.new("L", size, 0); ImageDraw.Draw(m).ellipse(((cx - r) * k, (cy - r) * k, (cx + r) * k, (cy + r) * k), fill=255); return m


def ring(size, r0, r1, k=None):
    k = k or S
    m = disc(size, r1, k=k); ImageDraw.Draw(m).ellipse(((CX - r0) * k, (CY - r0) * k, (CX + r0) * k, (CY + r0) * k), fill=0); return m


def paste_blur(im, color, mask, blur, alpha=255):
    m = mask.filter(ImageFilter.GaussianBlur(blur)) if blur else mask
    if alpha != 255:
        m = m.point(lambda v: v * alpha // 255)
    im.paste(Image.new("RGB", im.size, color), mask=m)


def button_rect(side, inset=0):
    """A button at 9 or 3 o'clock, 54 px (5.7 mm) long, sticking out 13 px; it is rotated about the case centre afterwards."""
    x = CX - 213 + inset if side == "L" else CX + 196 - inset
    return (x, CY - 27, x + 17, CY + 27)


def rot(im, side, angle, k=None):
    k = k or S
    return im.rotate(-angle if side == "L" else angle, resample=Image.BICUBIC, center=(CX * k, CY * k))


def button_layer(pressed):
    """RGBA buttons at final size, drawn over the case edge; a pressed one sits 4 px deeper with a soft accent glow."""
    k = S
    big = (Zi(W * k), Zi(H * k))
    out = Image.new("RGBA", big, (0, 0, 0, 0))
    outside = Image.eval(disc(big, 199), lambda v: 255 - v)  # keep only the part sticking out of the case
    for n, (side, ang, _, _) in BUTTONS.items():
        on = n == pressed
        lay = Image.new("RGBA", big, (0, 0, 0, 0))
        x0, y0, x1, y1 = (Zi(v * k) for v in button_rect(side, 4 if on else 0))
        w, h = x1 - x0, y1 - y0
        msk = Image.new("L", big, 0); ImageDraw.Draw(msk).rounded_rectangle((x0, y0, x1, y1), 6 * k, fill=255)
        msk = ImageChops.multiply(msk, outside)
        if on:  # glow behind and around the pressed button
            glow = Image.new("L", big, 0); ImageDraw.Draw(glow).rounded_rectangle((x0 - 4 * k, y0 - 4 * k, x1 + 4 * k, y1 + 4 * k), 9 * k, fill=255)
            glow = glow.filter(ImageFilter.GaussianBlur(9 * k)).point(lambda v: min(255, v * 3))
            lay.paste(Image.new("RGBA", big, ACCENT + (255,)), mask=glow)
        base = grad((w, h), [(0, (120, 124, 132)), (0.5, (74, 77, 84)), (1, (40, 42, 47))], 90 if side == "L" else -90)
        if on:
            base = Image.blend(base, Image.new("RGB", base.size, ACCENT), 0.3)
        face = Image.new("RGB", big); face.paste(base, (x0, y0))
        hl = grad((w, h), [(0, (255, 255, 255)), (1, (0, 0, 0))], 0).convert("L").point(lambda v: v * (40 if on else 90) // 255)
        face.paste(Image.new("RGB", (w, h), (255, 255, 255)), (x0, y0), hl)  # top edge light
        if n == "PTD10":  # START: the coloured ring
            ImageDraw.Draw(face).rounded_rectangle((x0, y0, x1, y1), 6 * k, outline=START_RING, width=3 * k)
        sh = msk.filter(ImageFilter.GaussianBlur(2 * k)).point(lambda v: v * (150 if on else 110) // 255)
        sh = Image.composite(Image.new("L", big, 0), sh, msk)  # shadow only outside the button
        lay.paste(Image.new("RGBA", big, (0, 0, 0, 255)), mask=ImageChops.offset(sh, 0, Zi(2 * k)))
        lay.paste(face.convert("RGBA"), mask=msk)
        out.alpha_composite(rot(lay, side, ang))
    return out.resize((FW, FH), Image.LANCZOS)


def font(sz):
    for f in ("/System/Library/Fonts/Helvetica.ttc", "/System/Library/Fonts/Menlo.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        if os.path.exists(f):
            return ImageFont.truetype(f, sz)
    return ImageFont.load_default(sz)


def build_base():
    """Static watch body, no screen: background, shadow, straps, case, bezel, mask ring. Returns (base RGB, glass RGBA)."""
    k = S; big = (Zi(W * k), Zi(H * k))
    im = grad(big, [(0, (240, 241, 243)), (1, (222, 224, 228))], 0)
    # straps (silhouette reused for the shadow)
    strap = Image.new("L", big, 0); sd = ImageDraw.Draw(strap)
    top = [(CX - 90, CY - 215), (CX + 90, CY - 215), (CX + 80, -10), (CX - 80, -10)]
    bot = [(CX - 90, CY + 215), (CX + 90, CY + 215), (CX + 80, H + 10), (CX - 80, H + 10)]
    for p in (top, bot):
        sd.polygon([(x * k, y * k) for x, y in p], fill=255)
    lugs = Image.new("L", big, 0)
    for y0, y1 in ((CY - 232, CY - 160), (CY + 160, CY + 232)):
        ImageDraw.Draw(lugs).rounded_rectangle(((CX - 96) * k, y0 * k, (CX + 96) * k, y1 * k), 24 * k, fill=255)
    sil = ImageChops.lighter(strap, lugs); ImageDraw.Draw(sil).ellipse(((CX - 200) * k, (CY - 200) * k, (CX + 200) * k, (CY + 200) * k), fill=255)
    for n, (side, ang, _, _) in BUTTONS.items():
        bm = Image.new("L", big, 0); ImageDraw.Draw(bm).rounded_rectangle(tuple(v * k for v in button_rect(side)), 6 * k, fill=255)
        sil = ImageChops.lighter(sil, rot(bm, side, ang))
    sh = ImageChops.offset(sil.resize((FW, FH), Image.LANCZOS), 0, Zi(12 * R)).filter(ImageFilter.GaussianBlur(13 * R)).point(lambda v: v * 120 // 255)
    sh2 = ImageChops.offset(sil.resize((FW, FH), Image.LANCZOS), 0, Zi(3 * R)).filter(ImageFilter.GaussianBlur(3 * R)).point(lambda v: v * 90 // 255)
    im = im.resize((FW, FH), Image.LANCZOS)
    for m in (sh, sh2):
        im.paste(Image.new("RGB", (FW, FH), (30, 32, 38)), mask=m)
    im = im.resize(big, Image.BICUBIC)
    # silicone: darker at the edges, lit in the middle, a fine vertical sheen
    sg = grad(big, [(0, (34, 36, 40)), (0.22, (62, 65, 70)), (0.45, (78, 81, 87)), (0.7, (56, 58, 63)), (1, (30, 32, 36))], 90)
    sg2 = grad(big, [(0, (255, 255, 255)), (0.2, (0, 0, 0)), (0.8, (0, 0, 0)), (1, (255, 255, 255))], 0).convert("L").point(lambda v: v // 6)
    sg.paste(Image.new("RGB", big, (0, 0, 0)), mask=sg2)  # darken toward where the strap meets the case
    im.paste(sg, mask=strap)
    # strap edge (thin dark outline) and holes on the bottom strap
    d = ImageDraw.Draw(im)
    for dy in (262, 294, 326):
        y = CY + dy
        d.ellipse(((CX - 6) * k, (y - 6) * k, (CX + 6) * k, (y + 6) * k), fill=(88, 91, 97))  # lit lower rim
        d.ellipse(((CX - 6) * k, (y - 7) * k, (CX + 6) * k, (y + 4) * k), fill=(17, 18, 20))
    # case: dark polymer, radial gradient lit from upper left
    case = ImageChops.lighter(disc(big, 200), lugs)
    cg = grad(big, [(0, (62, 65, 70)), (0.5, (38, 40, 44)), (1, (22, 23, 26))], 40)
    im.paste(cg, mask=case)
    lo = Image.new("L", big, 0)
    for y0, y1 in ((CY - 232, CY - 160), (CY + 160, CY + 232)):  # lug outline, only where it is outside the case
        ImageDraw.Draw(lo).rounded_rectangle(((CX - 96) * k, y0 * k, (CX + 96) * k, y1 * k), 24 * k, outline=255, width=2 * k)
    im.paste(Image.new("RGB", big, (12, 12, 14)), mask=ImageChops.multiply(lo, Image.eval(disc(big, 199), lambda v: 255 - v)))
    d = ImageDraw.Draw(im)
    d.ellipse(((CX - 200) * k, (CY - 200) * k, (CX + 200) * k, (CY + 200) * k), outline=(12, 12, 14), width=2 * k)
    # soft specular on the upper-left of the case rim, clipped to the rim
    spec = Image.new("L", big, 0)
    ImageDraw.Draw(spec).arc(((CX - 190) * k, (CY - 190) * k, (CX + 190) * k, (CY + 190) * k), 205, 265, fill=255, width=9 * k)
    spec = spec.filter(ImageFilter.GaussianBlur(6 * k)).point(lambda v: v * 150 // 255)
    im.paste(Image.new("RGB", big, (225, 230, 240)), mask=ImageChops.multiply(spec, ring(big, 172, 199)))
    # inner bezel with a bevel: light top edge, dark bottom edge
    bz = grad(big, [(0, (118, 122, 130)), (0.35, (48, 50, 55)), (0.65, (24, 25, 28)), (1, (8, 8, 10))], 0)
    im.paste(bz, mask=ring(big, 162, 172))
    bz2 = grad(big, [(0, (4, 4, 5)), (1, (70, 72, 78))], 0)  # inner lip: reversed, so the bevel reads as a step down
    im.paste(bz2, mask=ring(big, 156, 162))
    # black glass mask ring between the bezel and the display
    im.paste(Image.new("RGB", big, (5, 5, 6)), mask=ring(big, 144, 156))
    d = ImageDraw.Draw(im)
    # thin glass-edge highlight
    glass = Image.new("L", big, 0)
    ImageDraw.Draw(glass).arc(((CX - 157) * k, (CY - 157) * k, (CX + 157) * k, (CY + 157) * k), 195, 285, fill=255, width=2 * k)
    glass = glass.filter(ImageFilter.GaussianBlur(1.2 * k))
    im.paste(Image.new("RGB", big, (210, 218, 232)), mask=glass.point(lambda v: v * 190 // 255))
    full = Image.new("L", big, 0); ImageDraw.Draw(full).ellipse(((CX - 157) * k, (CY - 157) * k, (CX + 157) * k, (CY + 157) * k), outline=255, width=k)
    im.paste(Image.new("RGB", big, (160, 166, 178)), mask=full.point(lambda v: v * 60 // 255))
    # the bezel's button words, small and printed on the flat part
    f = font(Zi(8 * k)); d = ImageDraw.Draw(im)
    for n, (side, ang, _, word) in BUTTONS.items():
        a = math.radians(180 - ang if side == "L" else ang)
        x, y = CX + 186 * math.cos(a), CY - 186 * math.sin(a)
        d.text((x * k, y * k), word, font=f, fill=(128, 132, 140), anchor="mm")
    im = im.resize((FW, FH), Image.LANCZOS)
    # glass reflection over the display: diagonal gradient, soft-edged band cut
    G = (FW * 2, FH * 2); k2 = 2 * R
    g = Image.new("L", G, 0)
    ImageDraw.Draw(g).polygon([((CX - 150) * k2, (CY - 150) * k2), ((CX + 40) * k2, (CY - 150) * k2), ((CX - 150) * k2, (CY + 40) * k2)], fill=255)
    g = g.filter(ImageFilter.GaussianBlur(14 * R)).point(lambda v: v * 46 // 255)
    wash = grad(G, [(0, (255, 255, 255)), (0.5, (0, 0, 0)), (1, (0, 0, 0))], 45).convert("L").point(lambda v: v // 14)
    gl = ImageChops.multiply(ImageChops.add(g, wash), disc(G, 144, k=k2))
    glass_rgba = Image.new("RGBA", G, (255, 255, 255, 0)); glass_rgba.putalpha(gl)
    return im, glass_rgba.resize((FW, FH), Image.LANCZOS)


_cache = {}


def watch(frame, pressed=None):
    if "base" not in _cache:
        _cache["base"], _cache["glass"] = build_base()
    if pressed not in _cache:
        b = _cache["base"].convert("RGBA"); b.alpha_composite(button_layer(pressed)); _cache[pressed] = b
    im = _cache[pressed].copy()
    im.alpha_composite(circle(frame, Zi(288 * R)), (Zi((CX - 144) * R), Zi((CY - 144) * R)))
    im.alpha_composite(_cache["glass"])
    return im.convert("RGB")


if __name__ == "__main__":
    fs = sorted(glob.glob(f"{FR}/*.png"))
    t = [int(re.search(r"_(\d+)ms", f).group(1)) / 1000 for f in fs]
    pick = lambda ts: Image.open(fs[max(i for i in range(len(fs)) if t[i] <= ts)])
    os.makedirs(OUT, exist_ok=True)
    seq = []
    configure(1)
    for n, (name, ts) in enumerate(SCREENS, 1):
        circle(pick(ts), 240).save(f"{OUT}/{n:02d}-{name}-{ts:.0f}s.png")
        seq.append(watch(pick(ts)).quantize(128, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE))
    configure(5 / 3)  # HD body for the still; the display is the 240 px panel at exactly 2x
    watch(pick(80.0)).save(f"{OUT}/hero.png")
    seq[0].save(f"{OUT}/hero.gif", save_all=True, append_images=seq[1:], duration=[1000] * len(seq), loop=0, optimize=True)
