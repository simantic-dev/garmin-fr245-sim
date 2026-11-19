#!/usr/bin/env python3
"""USB host for the FR245 firmware's USB device, over pyrite's `--usb-raw` JSON-lines protocol.

Does what a host does on plug-in: GET_DESCRIPTOR device, SET_ADDRESS, GET_DESCRIPTOR configuration and strings,
SET_CONFIGURATION; prints the descriptors and writes the transfers as a Linux usbmon pcap (open with Wireshark).
Pcap timestamps are this script's wall clock, not guest time.
Usage: usb_host.py <port> <out.pcap> [seconds to wait before the first request, default 11]
"""
import json, socket, struct, sys, time

DEVICE, CONFIG, STRING = 1, 2, 3


class Host:
    def __init__(self, port, pcap):
        deadline = time.monotonic() + 60
        while True:
            try:
                self.sock = socket.create_connection(("127.0.0.1", port), timeout=120)
                break
            except OSError:
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.2)
        self.f = self.sock.makefile("rw", encoding="utf-8", newline="\n")
        self.n = 0
        self.addr = 0
        self.t0 = time.time()
        self.pcap = open(pcap, "wb")
        self.pcap.write(struct.pack("<IHHiIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, 220))  # LINKTYPE_USB_LINUX_MMAPPED

    def _rec(self, kind, urb, ep, setup, status, length, data):
        t = time.time() - self.t0
        sec, usec = int(t), int(t % 1 * 1e6)
        h = struct.pack("<QBBBBHBBqiiII", urb, ord(kind), 2, ep, self.addr, 1, 0 if setup else ord("-"),
                        0 if data else (ord("<") if kind == "S" else ord(">")), sec, usec, status, length, len(data))
        h += (setup or bytes(8)) + bytes(16)  # interval, start_frame, xfer_flags, ndesc
        rec = h + data
        self.pcap.write(struct.pack("<IIII", sec, usec, len(rec), len(rec)) + rec)

    def setup(self, bm, req, val=0, idx=0, length=0, data=b""):
        """Control transfer: reply data, or None on STALL."""
        self.n += 1
        raw = struct.pack("<BBHHH", bm, req, val, idx, length)
        ep = 0x80 if bm & 0x80 else 0
        self._rec("S", self.n, ep, raw, -115, length, data)
        self.f.write(json.dumps({"op": "setup", "bmRequestType": bm, "bRequest": req, "wValue": val, "wIndex": idx,
                                 "wLength": length, "data": data.hex(), "id": self.n}) + "\n")
        self.f.flush()
        while True:
            line = self.f.readline()
            assert line, "bridge closed the connection"
            r = json.loads(line)
            if r.get("id") == self.n:
                break
        assert "error" not in r, r
        print(f"  [{time.time() - self.t0:6.1f}s] setup {raw.hex()} -> {len(bytes.fromhex(r['data'])) if 'data' in r else r}", file=sys.stderr)
        got = None if r.get("stall") else bytes.fromhex(r["data"])
        self._rec("C", self.n, ep, None, -32 if got is None else 0, len(got or b""), got if bm & 0x80 and got else b"")
        return got

    def desc(self, kind, index=0, length=255, lang=0):
        return self.setup(0x80, 6, kind << 8 | index, lang, length)


def string(h, i, lang=0x0409):
    d = h.desc(STRING, i, 255, lang) if i else None
    return d[2:].decode("utf-16-le") if d else None


def main(port, pcap, wait=11):
    h = Host(int(port), pcap)
    # The bridge runs on wall clock against real-time emulation; a request sent before the firmware enables the
    # controller and the bus reset completes is dropped by the reset. The VBUS stand-in fires at 8 s of guest time.
    time.sleep(float(wait))
    dev = h.desc(DEVICE, 0, 18)
    assert dev and len(dev) == 18, dev
    bcd, cls, sub, proto, mps, vid, pid, rel, im, ip, isn, ncfg = struct.unpack_from("<HBBBBHHHBBBB", dev, 2)
    print(f"device descriptor: {dev.hex()}")
    print(f"  USB {bcd >> 8}.{bcd >> 4 & 15}{bcd & 15}  class {cls:#04x}/{sub:#04x}/{proto:#04x}  ep0 max packet {mps}"
          f"  VID:PID {vid:04x}:{pid:04x}  bcdDevice {rel:04x}  configurations {ncfg}")
    assert h.setup(0x00, 5, 5) == b"", "SET_ADDRESS"
    h.addr = 5
    time.sleep(1)  # USB 2.0 9.2.6.3: the device gets 2 ms after the SET_ADDRESS status stage
    lang = 0x0409
    if im or ip or isn:
        langs = h.desc(STRING, 0, 255)
        lang = struct.unpack_from("<H", langs, 2)[0] if langs and len(langs) > 3 else lang
        for name, i in (("manufacturer", im), ("product", ip), ("serial", isn)):
            print(f"  {name}: {string(h, i, lang)!r}")
    else:
        print("  no string descriptors (iManufacturer, iProduct, iSerialNumber are all 0)")
    hdr = h.desc(CONFIG, 0, 9)
    total = struct.unpack_from("<H", hdr, 2)[0]
    cfg = h.desc(CONFIG, 0, total)
    print(f"configuration descriptor ({len(cfg)} bytes): {cfg.hex()}")
    i = 0
    while i < len(cfg):
        n, t = cfg[i], cfg[i + 1]
        b = cfg[i:i + n]
        if t == 2:
            print(f"  configuration {b[5]}: {b[4]} interface(s), attributes {b[7]:#04x}, max power {b[8] * 2} mA")
        elif t == 4:
            print(f"  interface {b[2]} alt {b[3]}: {b[4]} endpoint(s), class {b[5]:#04x}/{b[6]:#04x}/{b[7]:#04x}"
                  f"  string {string(h, b[8], lang)!r}" if b[8] else
                  f"  interface {b[2]} alt {b[3]}: {b[4]} endpoint(s), class {b[5]:#04x}/{b[6]:#04x}/{b[7]:#04x}")
        elif t == 5:
            kind = ("control", "isochronous", "bulk", "interrupt")[b[3] & 3]
            print(f"    endpoint {b[2]:#04x} {'IN' if b[2] & 0x80 else 'OUT'} {kind}, max packet {struct.unpack_from('<H', b, 4)[0]}")
        else:
            print(f"  descriptor type {t:#04x}: {b.hex()}")
        i += n
    assert h.setup(0x00, 9, cfg[5]) == b"", "SET_CONFIGURATION"
    print(f"SET_CONFIGURATION {cfg[5]} accepted; device enumerated")
    h.pcap.close()


if __name__ == "__main__":
    main(*sys.argv[1:4])
