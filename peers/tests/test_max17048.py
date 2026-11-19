"""Self-tests for peers/i2c/max17048.py with a fake ctx. No firmware, no simulator.

    python3 -m pytest peers/tests/test_max17048.py
"""
import importlib.util
from pathlib import Path

PEER = Path(__file__).resolve().parents[1] / "i2c" / "max17048.py"


class FakeCtx:
    now_us = 0

    def log(self, *a):
        pass

    info = warning = error = debug = noisy = log


def make(**stimulus):
    spec = importlib.util.spec_from_file_location("max17048", PEER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.__dict__.update(stimulus)   # the stimulus constants are module globals read at call time
    return mod.Slave(FakeCtx())


def rd(d, reg, n=2):
    d.on_write(bytes([reg]))
    return d.on_read(n)


def rw(d, reg):
    b = rd(d, reg)
    return b[0] << 8 | b[1]


def test_reset_values():
    d = make()
    assert rw(d, 0x08) == 0x0012
    assert rw(d, 0x0C) == 0x971C
    assert rw(d, 0x0A) == 0x1930
    assert rw(d, 0x14) == 0x00FF
    assert rw(d, 0x06) == 0
    assert rw(d, 0x16) == 0
    assert rw(d, 0x1A) == 0x0100   # RI set after power-on


def test_vcell_and_soc_follow_the_stimulus():
    d = make(CELL_V=4.0, SOC_PERCENT=50.5)
    assert rw(d, 0x02) == round(4.0 / 78.125e-6)
    assert rw(d, 0x02) >> 4 == 3200   # 1.25 mV per count in bits 15:4
    assert rd(d, 0x04) == bytes([50, 128])


def test_burst_read_walks_the_registers():
    d = make()
    b = rd(d, 0x02, 6)
    assert b[2:4] == rd(d, 0x04) and b[4:6] == bytes([0, 0])


def test_write_masks_and_ro_registers():
    d = make()
    d.on_write(bytes([0x0C, 0x12, 0x3F]))   # RCOMP 0x12, ATHD 0x1F; ALRT (bit 5) is not written
    assert rw(d, 0x0C) == 0x123F & ~0x20
    d.on_write(bytes([0x08, 0xFF, 0xFF]))
    d.on_write(bytes([0x02, 0xFF, 0xFF]))
    assert rw(d, 0x08) == 0x0012
    d.on_write(bytes([0x06, 0x40, 0x00]))   # QuickStart
    assert rw(d, 0x06) == 0x4000


def test_status_ri_cleared_by_host():
    d = make()
    d.on_write(bytes([0x1A, 0x00, 0x00]))
    assert rw(d, 0x1A) == 0


def test_por_command_restores_reset_values():
    d = make()
    d.on_write(bytes([0x0C, 0x12, 0x3F]))
    d.on_write(bytes([0xFE, 0x54, 0x00]))
    assert rw(d, 0x0C) == 0x971C


def test_alerts():
    d = make(CELL_V=3.0, SOC_PERCENT=3.0)
    d.on_write(bytes([0x14, 0x50, 0xFF]))   # VALRT.MIN = 80 * 20 mV = 1.6 V; cell above it
    assert rw(d, 0x0C) & 0x20                          # SOC <= 32 - 0x1C = 4 %
    assert rw(d, 0x1A) & 0x0400 == 0
    d = make(CELL_V=3.0, SOC_PERCENT=90.0)
    d.on_write(bytes([0x14, 0xB4, 0xFF]))             # MIN = 180 * 20 mV = 3.6 V
    assert rw(d, 0x1A) & 0x0400                        # VL
    assert rw(d, 0x0C) & 0x20


def test_discharge_is_slow_and_monotonic():
    d = make()
    d.ctx.now_us = 0
    v0, s0 = int.from_bytes(rd(d, 0x02), "big") * 78.125e-6, rd(d, 0x04)[0]
    d.ctx.now_us = 3_600_000_000
    v1, s1 = int.from_bytes(rd(d, 0x02), "big") * 78.125e-6, rd(d, 0x04)[0]
    assert (s0, s1) == (80, 78) and 3.89 < v0 < 3.91 and v1 < v0
