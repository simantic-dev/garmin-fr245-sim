#!/usr/bin/env python3
"""The simulated phone: lists every BLE advertisement the sim's BLE medium carried (its pcap, linktype 256).

Usage: ble_phone.py out/ble.pcap
"""
import struct
import sys

PDU = {0: "ADV_IND", 3: "SCAN_REQ", 4: "SCAN_RSP", 5: "CONNECT_IND"}


def records(path):
    d = open(path, "rb").read()
    off = 24
    while off + 16 <= len(d):
        sec, usec, n, _ = struct.unpack_from("<IIII", d, off)
        yield sec + usec / 1e6, d[off + 16:off + 16 + n]
        off += 16 + n


def ad_fields(data):
    i = 0
    while i < len(data) and data[i]:
        yield data[i + 1], data[i + 2:i + 1 + data[i]]
        i += 1 + data[i]


def describe(ad):
    out = []
    for t, v in ad_fields(ad):
        if t == 0x01:
            out.append(f"flags=0x{v[0]:02x}")
        elif t in (0x02, 0x03):
            out.append("uuids=" + ",".join(f"0x{v[i] | v[i + 1] << 8:04X}" for i in range(0, len(v), 2)))
        elif t in (0x08, 0x09):
            out.append(f'name="{v.decode(errors="replace")}"' + (" (shortened)" if t == 0x08 else ""))
        elif t == 0xFF:
            out.append(f"company=0x{v[0] | v[1] << 8:04X} mfg={v[2:].hex()}")
        else:
            out.append(f"ad{t:#04x}={v.hex()}")
    return "  ".join(out)


CH = {0: 37, 12: 38, 39: 39}


def scan(path):
    """Every ADV_IND/SCAN_RSP in the pcap: (time, channel, pdu name, advertiser address, AdvData bytes)."""
    out = []
    for ts, rec in records(path):
        if rec[4:8] != bytes.fromhex("d6be898e"):
            continue
        coff = 14  # rf channel, 3 power/noise bytes, AA, flags, AA, then the PDU
        h, n = rec[coff], rec[coff + 1]
        if h & 15 not in (0, 4):
            continue
        adv_a = ":".join(f"{b:02X}" for b in rec[coff + 2:coff + 8][::-1])
        out.append((ts, CH.get(rec[0], rec[0]), PDU[h & 15], adv_a, rec[coff + 8:coff + 2 + n]))
    return out


def main():
    seen = [(ts, f"ch{ch} {pdu:8} {a}  {describe(ad)}") for ts, ch, pdu, a, ad in scan(sys.argv[1])]

    if "--all" in sys.argv:
        for ts, line in seen:
            print(f"[{ts:9.4f}s] {line}")
    else:
        # One line per advertising window (gap over 1 s starts a new one), with its first advertisement.
        for k, (ts, line) in enumerate(seen):
            if k == 0 or ts - seen[k - 1][0] > 1:
                start = k
                print(f"[{ts:9.4f}s] {line}")
            if k + 1 == len(seen) or seen[k + 1][0] - ts > 1:
                print(f"   ... until {ts:.4f}s: {k - start + 1} advertisements")


if __name__ == "__main__":
    main()
