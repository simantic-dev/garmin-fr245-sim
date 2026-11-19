#!/usr/bin/env python3
"""Headline GIF: the round watch (display frames, pressed button lit) next to the firmware's real traffic, one simulated clock.
Reads one scenario run: out/frames/*.png, out/run.log (peers log with timestamps), out/ble.pcap, sim/overlay.board (button script).
Usage: ./run.sh > out/run.log   (or: sim run --scenario sim/scenario.yaml > out/run.log), then python3 scripts/demo_gif.py [out_gif]
Starts at t = 0 (the display is dark until the firmware first draws). Dead time is skipped: a GIF frame is made when the display changes, a button moves or traffic arrives; the clock shows the real time.
The first-boot flash format (QuadSPI erase/program, see qspi_summary.py) is shown as one line every FLASH_EVERY s of simulated time."""
import glob, json, os, re, sys
from PIL import Image, ImageDraw, ImageFont
sys.path.insert(0, os.path.dirname(__file__))
from watch_render import BUTTONS, watch
from ble_phone import scan, ad_fields

OUT = sys.argv[1] if len(sys.argv) > 1 else "docs/screens/demo.gif"
W, H, WATCH_W, ROWS = 900, 500, 320, 14
COL = {"uart": (110, 200, 255), "link": (255, 214, 102), "air": (120, 230, 140), "btn": (255, 150, 40),
       "i2c": (255, 120, 190), "flash": (190, 150, 255)}
BG, FG, DIM = (18, 20, 24), (225, 225, 225), (130, 135, 145)
FLASH_EVERY = 4
PINS = ["PTC11", "PTD10", "PTD1", "PTA20", "PTA22"]  # overlay.board `btn` lines 0..4
CMD = {0x01: "register app", 0x42: "init step", 0x16: "set name", 0x12: "cmd", 0x14: "cmd", 0x09: "cmd", 0x0A: "cmd"}


def short(u):  # 6a4e4c80-667b-11e3-949a-0800200c9a66 -> 6a4e4c80-667b-..
    return u[:13] + ".."


def uuid128(le):  # the radio's 16 bytes are little endian
    h = le[::-1].hex()
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"


def uuid16(le, base="6a4e%04x-667b-11e3-949a-0800200c9a66"):
    return base % (le[0] | le[1] << 8)


def label_rx(p):
    c = p[0]
    if c == 0x37:
        return f"K28>CYW 0x37 add service {short(uuid128(p[4:20]))}"
    if c == 0x29:
        return f"K28>CYW 0x29 add GATT service {short(uuid16(p[4:6]))}"
    if c == 0x2B:
        return f"K28>CYW 0x2b add char {short(uuid16(p[12:14]))}"
    if c == 0x16:
        return f'K28>CYW 0x16 set name "{p[12:12 + (p[6] | p[7] << 8)].decode(errors="replace")}"'
    if c == 0x08 and len(p) == 400:
        return f"K28>CYW 0x08 adv config mode={p[399]} ({'on' if p[399] == 1 else 'off'})"
    return f"K28>CYW 0x{c:02x} {CMD.get(c, 'command')}"


def label_tx(h):
    op, msg = h[5] | h[6] << 8, h[7:]
    if op == 0x1B4A:
        return "CYW>K28 0x1b4a send gate open"
    if op == 0x1984 and msg[:1] == b"\x24":
        return "CYW>K28 0x24 stack enabled"
    return f"CYW>K28 ack 0x{msg[4]:02x}" + (f" handle 0x{msg[9]:02x}" if msg[4] in (0x37, 0x29, 0x2B) else "")


def events():
    ev, last_q = [], -99  # (t, kind, text)
    for l in open("out/run.log", errors="replace"):
        m = re.search(r"cyw rx t=([\d.]+) opcode=0x1982 payload=(\w+)", l)
        if m:
            ev.append((float(m[1]), "uart", label_rx(bytes.fromhex(m[2]))))
        m = re.search(r"cyw tx t=([\d.]+) (\w+)", l)
        if m:
            ev.append((float(m[1]), "uart", label_tx(bytes.fromhex(m[2]))))
        m = re.search(r"garmin-link rx t=([\d.]+) id=(0x\w+) data=(\w*)", l)
        if m:
            body = bytes([int(m[2], 16), len(m[3]) // 2]) + bytes.fromhex(m[3])
            raw = bytes([0x10]) + body + bytes([-sum(body) & 255, 0x10, 3])
            ev.append((float(m[1]), "link", f"K28>host {raw.hex(' ')} (DLE {m[2]})"))
        m = re.search(r"\] (max17048|max20303) t=([\d.]+) (.*)", l)
        if m:
            ev.append((float(m[2]), "i2c", f"K28>{m[1].upper()} {m[3]}"))
        m = re.search(r"hub t=([\d.]+) (RESET_N \w+)", l)
        if m:
            ev.append((float(m[1]), "i2c", f"K28>sensor hub {m[2]} (PTA27)"))
        m = re.search(r"qspi t=([\d.]+) erase=(\d+) program=(\d+) last_erase=(\w+) last_program=(\w+)", l)
        if m and float(m[1]) - last_q >= FLASH_EVERY:
            last_q = float(m[1])
            e, pg = int(m[2]), int(m[3])
            ev.append((last_q, "flash", f"K28>QSPI NOR erase 64K block {m[4]} (n={e} this s)" if e else f"K28>QSPI NOR program page {m[5]} (n={pg} this s)"))
    for ts, ch, pdu, _, ad in scan("out/ble.pcap"):
        f = {t: v for t, v in ad_fields(ad)}
        s = f"air ch{ch} {pdu}"
        if 0x03 in f:
            s += f" uuid=0x{f[3][0] | f[3][1] << 8:04X}"
        if 0xFF in f:
            c = f[0xFF][0] | f[0xFF][1] << 8
            s += f" company=0x{c:04x}" + ("" if c == 0x87 else "")
        for t in (0x08, 0x09):
            if t in f:
                s += f' name={f[t].decode(errors="replace")}'
        ev.append((ts, "air", s))
    cfg = json.loads(re.search(r'btn:.*?config: "(.*?)"\n', open("sim/overlay.board").read(), re.S)[1].replace('\\"', '"'))
    presses = []
    for e in cfg["events"]:
        if e["level"] == 0:
            presses.append((e["at_ms"] / 1000, PINS[e["line"]]))
            ev.append((e["at_ms"] / 1000, "btn", f"button {PINS[e['line']]} pressed ({BUTTONS[PINS[e['line']]][2].strip('?')})"))
    return sorted(ev, key=lambda e: e[0]), presses


def font(sz):
    for p in ("/System/Library/Fonts/Menlo.ttc", "/System/Library/Fonts/Monaco.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"):
        if os.path.exists(p):
            return ImageFont.truetype(p, sz)
    return ImageFont.load_default(sz)


def main():
    ev, presses = events()
    fs = sorted(glob.glob("out/frames/*.png"))
    ft = [int(re.search(r"_(\d+)ms", f).group(1)) / 1000 for f in fs]
    t0, t1 = 0.0, ft[-1] + 0.2
    fnt, big = font(12), font(17)
    # candidate ticks: display frames, events, button edges; keep one per 0.3 s of simulated time, plus every button edge
    edges = {p for p, _ in presses} | {p + 0.3 for p, _ in presses}
    cand = sorted({t for t, _, _ in ev if t0 <= t <= t1} | set(ft) | edges | {0.0})
    ticks, last = [], -9
    for t in cand:
        if t - last >= 0.3 or t in edges:
            ticks.append(t); last = t
    frames, durs, fi, shown, prev_fi = [], [], 0, [], None
    ei = 0
    for t in ticks:
        while ei < len(ev) and ev[ei][0] <= t:
            shown.append(ev[ei]); ei += 1
        while fi + 1 < len(fs) and ft[fi + 1] <= t:
            fi += 1
        if t < ft[0]:
            fi = -1
        pressed = next((n for p, n in presses if p <= t < p + 0.3), None)
        w = watch(Image.open(fs[max(fi, 0)]) if fi >= 0 else Image.new("RGB", Image.open(fs[0]).size), pressed)
        w = w.resize((WATCH_W, WATCH_W * 600 // 480), Image.LANCZOS)
        im = Image.new("RGB", (W, H), BG)
        im.paste(w, (0, (H - w.height) // 2))
        d = ImageDraw.Draw(im)
        x0 = WATCH_W + 12
        d.text((x0, 10), f"t = {t:.2f} s (simulated)", font=big, fill=FG)
        d.text((x0, 34), "stock Garmin FR245 firmware: I2C, flash, UART, BLE", font=fnt, fill=DIM)
        d.line((x0, 54, W - 8, 54), fill=(60, 64, 72))
        for i, (t_e, k, text) in enumerate(shown[-ROWS:]):
            y = 62 + i * 29
            newest = i == len(shown[-ROWS:]) - 1
            if newest:
                d.rectangle((x0 - 4, y - 3, W - 6, y + 25), fill=(44, 50, 62))
            d.text((x0, y), f"{t_e:7.3f}s", font=fnt, fill=DIM)
            d.text((x0 + 62, y), text, font=fnt, fill=COL[k] if newest or True else FG)
            if newest:
                d.rectangle((x0 - 4, y - 3, x0 - 1, y + 25), fill=COL[k])
        lx = x0
        for k, name in (("i2c", "I2C/power"), ("flash", "QSPI flash"), ("uart", "radio UART"), ("link", "host link"), ("air", "BLE air"), ("btn", "button")):
            d.rectangle((lx, H - 22, lx + 9, H - 13), fill=COL[k]); d.text((lx + 14, H - 24), name, font=fnt, fill=DIM)
            lx += 14 + 7 * len(name) + 14
        frames.append(im)
        changed = fi != prev_fi; prev_fi = fi
        durs.append(300 if changed else 110)
    # one shared palette (sampled over the whole run) keeps the text colours stable between frames
    mosaic = Image.new("RGB", (W, H * 12))
    for k in range(12):
        mosaic.paste(frames[k * len(frames) // 12], (0, k * H))
    pal = mosaic.quantize(96, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    frames = [f.quantize(palette=pal, dither=Image.Dither.NONE) for f in frames]
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    frames[0].save(OUT, save_all=True, append_images=frames[1:], duration=durs, loop=0, optimize=True)
    print(f"{OUT}: {len(frames)} frames, {sum(durs) / 1000:.1f} s, {os.path.getsize(OUT) / 1e6:.2f} MB, sim {t0:.1f}-{t1:.1f} s")


if __name__ == "__main__":
    main()
