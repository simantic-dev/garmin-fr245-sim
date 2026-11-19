#!/usr/bin/env python3
"""Filter for the run log: reads `sim run --trace-memory 0x400da100:4 --trace-memory 0x400da008:4` output on stdin
(QuadSPI0 SFAR and IPCR), drops the (MEM) records and prints one `qspi t=<s> ...` line per second of virtual time that
had flash activity. IPCR write: SEQID = bits 27:24, IDATSZ = bits 15:0. Read off the firmware's own LUT use, not a datasheet:
SEQID 8 with no data = 64 KiB block erase, SEQID 5 with 0x100 data bytes = page program; the address is the last SFAR write."""
import re, sys

T = re.compile(r"^\[([\d.]+)s\] \(MEM\) 0x400da(100|008):4 write .*value=0x([0-9a-f]+)")
sec, n_erase, n_prog, addr, last_e, last_p = -1, 0, 0, 0, 0, 0


def flush():
    if n_erase or n_prog:
        print(f"[qspi] qspi t={sec}.0 erase={n_erase} program={n_prog} last_erase={last_e:#010x} last_program={last_p:#010x}")


for l in sys.stdin:
    if "(MEM)" not in l:
        sys.stdout.write(l)
        continue
    m = T.match(l)
    if not m:
        continue
    t, reg, v = float(m[1]), m[2], int(m[3], 16)
    if int(t) != sec:
        flush()
        sec, n_erase, n_prog = int(t), 0, 0
    if reg == "100":
        addr = v
    elif v >> 24 == 8 and not v & 0xFFFF:
        n_erase, last_e = n_erase + 1, addr
    elif v >> 24 == 5 and v & 0xFFFF == 0x100:
        n_prog, last_p = n_prog + 1, addr
flush()
