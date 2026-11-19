#!/usr/bin/env python3
"""Build a pyrite-loadable ELF of Garmin Forerunner 245 firmware v3.10.

Downloads the .gcd from Garmin's own server (never committed: Garmin copyright),
checks its sha256, unpacks stream 0x02bd and writes fr245.elf:
  - first 0x1fd000 B -> internal flash at 0x3000 (firmware sets VTOR=0x3000)
  - rest             -> QuadSPI code alias at 0x04617000 (fitted from literal
                        pointers landing on Thumb prologues: 2811 hits vs 1740)

Usage: scripts/garmin_fr245_image.py <outdir>
Run:   sim MK28FN2M0VMI15 run --elf <outdir>/fr245.elf
"""

import hashlib
import pathlib
import struct
import sys
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from garmin_gcd_unpack import unpack

URL = "https://download.garmin.com/software/Forerunner245_310.gcd"
SHA256 = "ffc802fd505cb62fe680dd50935654ef8177c8a0c74d20de3a6b32a4d185ff43"
FLASH_BASE, SPLIT, QSPI_BASE, ENTRY = 0x3000, 0x1FD000, 0x04617000, 0x31F1


def elf(segs, entry):
    off = 52 + 32 * len(segs)
    out = b"\x7fELF\x01\x01\x01" + bytes(9) + struct.pack(
        "<HHIIIIIHHHHHH", 2, 40, 1, entry, 52, 0, 0x5000000, 52, 32, len(segs), 40, 0, 0)
    body = b""
    for addr, data in segs:
        out += struct.pack("<8I", 1, off + len(body), addr, addr, len(data), len(data), 7, 4)
        body += data
    return out + body


def main(outdir):
    outdir.mkdir(parents=True, exist_ok=True)
    gcd = outdir / "Forerunner245_310.gcd"
    if not gcd.exists():
        urllib.request.urlretrieve(URL, gcd)
    raw = gcd.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == SHA256, "unexpected .gcd contents"
    fw = next(b for s, b in unpack(raw) if s["rec_id"] == 0x02BD)
    (outdir / "fr245.elf").write_bytes(
        elf([(FLASH_BASE, fw[:SPLIT]), (QSPI_BASE, fw[SPLIT:])], ENTRY))
    print(outdir / "fr245.elf")


if __name__ == "__main__":
    main(pathlib.Path(sys.argv[1]))
