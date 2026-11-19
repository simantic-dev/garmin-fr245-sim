#!/usr/bin/env python3
"""Headline GIF: the round watch (display frames, pressed button lit) next to the firmware's real traffic, one simulated clock.
Reads one scenario run: out/frames/*.png, out/run.log (peers log with timestamps), out/ble.pcap, sim/overlay.board (button script).
Usage: ./run.sh > out/run.log   (or: sim run --scenario sim/scenario.yaml > out/run.log), then python3 scripts/demo_gif.py [out_gif]
Starts at t = 0 (the display is dark until the firmware first draws). Dead time is skipped: a GIF frame is made when the display changes, a button moves or traffic arrives; the clock shows the real time.
Under it an IRQ panel: the top 8 interrupts in the trailing 0.5 s (bars, log scale, rate per second) and the total IRQ/s over the run with a cursor.
Reads out/irq_rates.json (made by run.sh from --trace-interrupts, binned at 100 ms; a temporary input, not kept). Without it the panel is left out.
Rows: I2C writes (one per 0.25 s), sensor hub SPI messages, radio UART, GPS UART handshake, one BLE advert per second, buttons."""
import glob, json, math, os, re, sys
from PIL import Image, ImageDraw, ImageFont
sys.path.insert(0, os.path.dirname(__file__))
from watch_render import BUTTONS, watch
from ble_phone import scan, ad_fields

OUT = sys.argv[1] if len(sys.argv) > 1 else "docs/screens/demo.gif"
W, H, WATCH_W, ROWS = 900, 500, 320, 13
PH = 170  # IRQ panel height under the traffic view
WIN = 0.5  # seconds of trailing window for the bar rates
COL = {"uart": (110, 200, 255), "gps": (255, 214, 102), "air": (120, 230, 140), "btn": (255, 150, 40),
       "i2c": (255, 120, 190), "hub": (190, 150, 255)}
BG, FG, DIM = (18, 20, 24), (225, 225, 225), (130, 135, 145)
GPS_SHOWN_S = 6.0  # the GPS handshake is listed up to here, then one note
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
    ev, last = [], {}  # (t, kind, text); last[kind] = time of the last kept row for the rate-limited kinds
    gps_rows = 0
    for l in open("out/run.log", errors="replace"):
        m = re.search(r"cyw rx t=([\d.]+) opcode=0x1982 payload=(\w+)", l)
        if m:
            ev.append((float(m[1]), "uart", label_rx(bytes.fromhex(m[2]))))
        m = re.search(r"cyw tx t=([\d.]+) (\w+)", l)
        if m:
            ev.append((float(m[1]), "uart", label_tx(bytes.fromhex(m[2]))))
        m = re.search(r"gnss rx t=([\d.]+) id=(0x\w+) msg=(0x\w+) data=(\w*)", l)
        if m and float(m[1]) < GPS_SHOWN_S:  # the handshake; the same exchange repeats every 11 s (README, GPS)
            ev.append((float(m[1]), "gps", f"K28>GPS id {m[2]} msg {m[3]} {m[4][:16]}"))
        m = re.search(r"\] (max17048|max20303) t=([\d.]+) (.*)", l)
        if m and float(m[2]) - last.get("i2c", -9) >= 0.25:  # the init burst is dozens of writes in a few ms
            last["i2c"] = float(m[2])
            ev.append((last["i2c"], "i2c", f"K28>{m[1].upper()} {m[3]}"))
        m = re.search(r"hub t=([\d.]+) (RESET_N \w+)", l)
        if m:
            ev.append((float(m[1]), "hub", f"K28>sensor hub {m[2]} (PTA27)"))
        m = re.search(r"hubev t=([\d.]+) (accel config .*|accel batch .*|hello .*)", l)
        if m:
            ev.append((float(m[1]), "hub", ("K28>hub " if m[2][:5] == "accel" and m[2][6] == "c" else "hub>K28 ") + m[2]))
    ev.append((GPS_SHOWN_S, "gps", "GPS parked: needs CPE.BIN (README)"))
    n_air = 0
    for ts, ch, pdu, _, ad in scan("out/ble.pcap"):
        n_air += 1
        if ts - last.get("air", -9) < 1.0:  # one row per second; the radio advertises every ~20 ms
            continue
        last["air"] = ts
        f = {t: v for t, v in ad_fields(ad)}
        s = f"air ch{ch} {pdu}"
        if 0x03 in f:
            s += f" uuid=0x{f[3][0] | f[3][1] << 8:04X}"
        if 0xFF in f:
            s += f" company=0x{f[0xFF][0] | f[0xFF][1] << 8:04x}"
        for t in (0x08, 0x09):
            if t in f:
                s += f' name={f[t].decode(errors="replace")}'
        ev.append((ts, "air", s))
    cfg = json.loads(re.search(r'btn:.*?config: "(.*?)"\n', open("sim/overlay.board").read(), re.S)[1].replace('\\"', '"'))
    presses = []
    for e in cfg["holds"]:
        presses.append((e["at_ms"] / 1000, PINS[e["line"]]))
        ev.append((e["at_ms"] / 1000, "btn", f"button {PINS[e['line']]} pressed ({BUTTONS[PINS[e['line']]][2].strip('?')})"))
    return sorted(ev, key=lambda e: e[0]), presses


IRQ_NAME = {"30": "LPUART0 (radio)", "31": "LPUART1", "32": "LPUART2", "33": "LPUART3 (GPS)", "34": "LPUART4", "24": "I2C0", "25": "I2C1",
            "74": "I2C2", "91": "I2C3 (power)", "26": "SPI0", "27": "SPI1", "65": "SPI2 (hub)", "46": "RTC alarm", "47": "RTC seconds",
            "48": "PIT0", "49": "PIT1", "50": "PIT2", "51": "PIT3", "58": "LPTMR0", "59": "PORTA", "60": "PORTB", "61": "PORTC",
            "62": "PORTD", "63": "PORTE", "70": "FlexIO0 (display)", "100": "QuadSPI0", "39": "ADC0", "13": "DMA ch13/29", "15": "DMA ch15/31",
            "PendSV": "PendSV", "SysTick": "SysTick"}  # the chip's own NVIC wiring (mk28fn2m0.rs); DMA channel n and n+16 share IRQ n


def load_irq():
    if not os.path.exists("out/irq_rates.json"):
        return None
    b = {k: {int(i): c for i, c in v.items()} for k, v in json.load(open("out/irq_rates.json"))["bins"].items()}
    n = max(i for v in b.values() for i in v) + 1
    return b, n


def irq_name(k):
    return IRQ_NAME.get(k) or IRQ_NAME.get(k.removeprefix("IRQ"), k)


def irq_panel(d, irq, t, fnt):
    bins, n = irq
    y0, x0 = H, 12
    d.line((0, y0, W, y0), fill=(60, 64, 72))
    lo, hi = max(0, int((t - WIN) * 10)), int(t * 10) + 1
    rate = sorted(((sum(v.get(i, 0) for i in range(lo, hi)) / ((hi - lo) / 10), k) for k, v in bins.items()), reverse=True)[:8]
    rate = [r for r in rate if r[0]]
    d.text((x0, y0 + 6), f"IRQ entries/s, last {WIN:g} s (log bars)", font=fnt, fill=DIM)
    for r, (v, k) in enumerate(rate):
        y = y0 + 24 + r * 17
        d.text((x0, y), irq_name(k)[:18], font=fnt, fill=FG)
        d.rectangle((x0 + 150, y + 2, x0 + 150 + 250 * math.log10(1 + v) / 3.5, y + 11), fill=COL["btn"])
        d.text((x0 + 410, y), f"{v:6.0f}", font=fnt, fill=FG)
    sx, sw, sy, sh = 520, W - 530, y0 + 40, PH - 56
    tot = [sum(v.get(i, 0) for v in bins.values()) * 10 for i in range(n)]  # per 100 ms bin -> per s
    sm = [sum(tot[max(0, i - 2):i + 3]) / len(tot[max(0, i - 2):i + 3]) for i in range(n)]
    top = math.log10(1 + max(sm)) * 1.05
    d.text((sx, y0 + 6), f"total IRQ/s over the run, log (peak {max(sm):.0f}/s)", font=fnt, fill=DIM)
    d.rectangle((sx, sy, sx + sw, sy + sh), outline=(60, 64, 72))
    d.line([(sx + sw * i / n, sy + sh - sh * math.log10(1 + sm[i]) / top) for i in range(n)], fill=COL["hub"], width=1)
    cx = sx + sw * min(t * 10, n) / n
    d.line((cx, sy - 4, cx, sy + sh + 4), fill=COL["btn"], width=2)
    d.text((sx, sy + sh + 4), "0 s", font=fnt, fill=DIM); d.text((sx + sw - 42, sy + sh + 4), f"{n / 10:.0f} s", font=fnt, fill=DIM)


def font(sz):
    for p in ("/System/Library/Fonts/Menlo.ttc", "/System/Library/Fonts/Monaco.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"):
        if os.path.exists(p):
            return ImageFont.truetype(p, sz)
    return ImageFont.load_default(sz)


def main():
    ev, presses = events()
    irq = load_irq()
    full = H + (PH if irq else 0)  # the traffic view keeps its size; the panel is added below it
    fs = sorted(glob.glob("out/frames/*.png"))
    ft = [int(re.search(r"_(\d+)ms", f).group(1)) / 1000 for f in fs]
    t0, t1 = 0.0, ft[-1] + 0.2
    fnt, big = font(12), font(17)
    # candidate ticks: display frames, events, button edges; keep one per 0.3 s of simulated time, plus every button edge
    edges = {p for p, _ in presses} | {p + 0.3 for p, _ in presses}
    cand = sorted({t for t, _, _ in ev if t0 <= t <= t1} | set(ft) | edges | {0.0} | ({float(x) for x in range(0, int(t1), 2)} if irq else set()))
    ticks, last = [], -9
    for t in cand:
        if t - last >= 0.35 or t in edges:
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
        im = Image.new("RGB", (W, full), BG)
        im.paste(w, (0, (H - w.height) // 2))
        d = ImageDraw.Draw(im)
        x0 = WATCH_W + 12
        d.text((x0, 10), f"t = {t:.2f} s (simulated)", font=big, fill=FG)
        d.text((x0, 34), "stock Garmin FR245 firmware: I2C, sensor hub SPI, UARTs, BLE", font=fnt, fill=DIM)
        d.line((x0, 54, W - 8, 54), fill=(60, 64, 72))
        for i, (t_e, k, text) in enumerate(shown[-ROWS:]):
            y = 62 + i * 29
            newest = i == len(shown[-ROWS:]) - 1
            if newest:
                d.rectangle((x0 - 4, y - 3, W - 6, y + 25), fill=(44, 50, 62))
            d.text((x0, y), f"{t_e:7.3f}s", font=fnt, fill=DIM)
            d.text((x0 + 62, y), text[:68], font=fnt, fill=COL[k] if newest or True else FG)
            if newest:
                d.rectangle((x0 - 4, y - 3, x0 - 1, y + 25), fill=COL[k])
        if t >= GPS_SHOWN_S:
            d.text((x0, H - 56), "GPS parked: start is gated on CPE.BIN, no fix is fed (README)", font=fnt, fill=COL["gps"])
        if t >= 1.2:
            d.text((x0, H - 42), "MAX17048 fuel gauge: configured by writes, never read", font=fnt, fill=COL["i2c"])
        lx = x0
        for k, name in (("i2c", "I2C power"), ("hub", "hub SPI"), ("uart", "radio UART"), ("gps", "GPS UART"), ("air", "BLE air"), ("btn", "button")):
            d.rectangle((lx, H - 22, lx + 9, H - 13), fill=COL[k]); d.text((lx + 14, H - 24), name, font=fnt, fill=DIM)
            lx += 14 + 7 * len(name) + 14
        if irq:
            irq_panel(d, irq, t, fnt)
        frames.append(im)
        changed = fi != prev_fi; prev_fi = fi
        durs.append(300 if changed else 110)
    # one shared palette (sampled over the whole run) keeps the text colours stable between frames
    mosaic = Image.new("RGB", (W, full * 12))
    for k in range(12):
        mosaic.paste(frames[k * len(frames) // 12], (0, k * full))
    pal = mosaic.quantize(64, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    frames = [f.quantize(palette=pal, dither=Image.Dither.NONE) for f in frames]
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    frames[0].save(OUT, save_all=True, append_images=frames[1:], duration=durs, loop=0, optimize=True)
    print(f"{OUT}: {len(frames)} frames, {sum(durs) / 1000:.1f} s, {os.path.getsize(OUT) / 1e6:.2f} MB, sim {t0:.1f}-{t1:.1f} s")


if __name__ == "__main__":
    main()
