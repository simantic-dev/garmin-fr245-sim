#!/usr/bin/env python3
"""Unpack a Garmin .gcd into one flat .bin per firmware stream + manifest.json.

Format: "GARMIN" u16 ver, then records {u16 id, u16 len, data} until id 0xFFFF.
Record 0x0007 describes a stream (16 B, LE): u8 erase, u8 xor, u16 rec_id,
u32 len, u16 hwid, u16 unk, u16 unk, u16 swver. Data records with id == rec_id
are concatenated and XORed with the descriptor's byte.

Usage: scripts/garmin_gcd_unpack.py <in.gcd> <outdir>
Never commit the .gcd or the extracted binaries (Garmin copyright).
"""

import hashlib
import json
import pathlib
import struct
import sys


def unpack(d):
    assert d[:6] == b"GARMIN", "not a GCD"
    p, descs, data = 8, [], {}
    while True:
        rid, n = struct.unpack_from("<HH", d, p)
        p += 4
        if rid == 0xFFFF:
            break
        rec = d[p:p + n]
        p += n
        if rid == 7:
            _, xor, sid, ln, hwid, _, _, swver = struct.unpack("<BBHIHHHH", rec)
            descs.append(dict(rec_id=sid, len=ln, xor=xor, hwid=hwid, swver=swver))
            data.setdefault(sid, bytearray())
        elif rid in data:
            data[rid] += rec
    out = []
    for s in descs:
        b = bytes(x ^ s["xor"] for x in data[s["rec_id"]])
        assert len(b) == s["len"], f"rec {s['rec_id']:#x}: {len(b)} != {s['len']}"
        out.append((s, b))
    return out


def main(argv):
    src, outdir = argv[1], pathlib.Path(argv[2])
    outdir.mkdir(parents=True, exist_ok=True)
    manifest = []
    for s, b in unpack(pathlib.Path(src).read_bytes()):
        (outdir / f"stream_{s['rec_id']:04x}.bin").write_bytes(b)
        manifest.append({**s, "sha256": hashlib.sha256(b).hexdigest()})
        sp, reset = struct.unpack_from("<II", b)
        print(f"{s['rec_id']:#06x} len={len(b)} SP={sp:#010x} reset={reset:#010x}")
    (outdir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    main(sys.argv)
