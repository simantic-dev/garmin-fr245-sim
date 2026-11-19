# Analog Devices (Maxim) MAX17048 single-cell ModelGauge fuel gauge, as a scripted I2C peer.
# Source: MAX17048/MAX17049 datasheet 19-6358: register map and reset values, "VCELL", "SOC",
# "MODE", "VERSION", "HIBRT", "CONFIG", "VALRT", "CRATE", "VRESET/ID", "STATUS", "CMD" register
# descriptions. Address 0x36 (fixed): give it with `address:` in the board file.
# Framing: 16-bit registers at even addresses, MSB first. A write's first byte is the register
# address, then zero or more data bytes; a read returns the bytes at the address, which advances
# one byte per byte read, so a burst walks VCELL, SOC, MODE...
#
# Stimulus: the cell. CELL_V (volts) and SOC_PERCENT are board/battery facts the chip estimates
# from; edit them from a bench measurement or set them from the overlay script line.
# MODELED SIMPLIFICATION: SOC is the stimulus value, not a ModelGauge computation from VCELL
# (the algorithm and its battery model are not published); CRATE reads 0 (no load history).
# Not modelled: sleep/hibernate timing (HibStat stays 0), the ALRT pin, the ID byte of VRESET/ID
# (the datasheet gives none, reads 0), the voltage-reset (VR) comparator.
CELL_V = 3.9          # volts at the cell at t = 0
SOC_PERCENT = 80.0    # state of charge at t = 0, percent
# MODELED SIMPLIFICATION: a slow linear discharge (nothing in the firmware supplies a load profile): SOC falls
# DRAIN_PCT_PER_H, the cell falls V_PER_PCT per percent lost.
DRAIN_PCT_PER_H = 2.0
V_PER_PCT = 0.004

VCELL, SOC, MODE, VERSION, HIBRT, CONFIG = 0x02, 0x04, 0x06, 0x08, 0x0A, 0x0C
VALRT, CRATE, VRESET, STATUS, CMD = 0x14, 0x16, 0x18, 0x1A, 0xFE
VCELL_LSB_V = 78.125e-6   # VCELL, all 16 bits (datasheet: 1.25 mV per bit in 15:4)
VALRT_LSB_V = 0.020       # VALRT.MIN/MAX
ATHD_MASK, ALRT, ENVR = 0x001F, 0x0020, 0x4000
RI, VH, VL = 0x0100, 0x0200, 0x0400
POR_CMD = 0x5400
RESET = {MODE: 0x0000, HIBRT: 0x1930, CONFIG: 0x971C, VALRT: 0x00FF, VRESET: 0x9600, STATUS: RI}
WRITABLE = {MODE: 0x6000, HIBRT: 0xFFFF, CONFIG: 0xFFDF, VALRT: 0xFFFF, VRESET: 0xFE00, STATUS: 0x7F00}


NAMES = {VCELL: "VCELL", SOC: "SOC", MODE: "MODE", VERSION: "VERSION", HIBRT: "HIBRT", CONFIG: "CONFIG",
         VALRT: "VALRT", 0x3E: "LOCK/UNLOCK", CRATE: "CRATE", VRESET: "VRESET/ID", STATUS: "STATUS", CMD: "CMD"}


class Slave:
    def __init__(self, ctx):
        self.ctx = ctx
        self.ptr = 0
        self.regs = dict(RESET)

    def _soc_pct(self):
        return max(0.0, SOC_PERCENT - DRAIN_PCT_PER_H * self.ctx.now_us / 3.6e9)

    def _cell_v(self):
        return CELL_V - V_PER_PCT * (SOC_PERCENT - self._soc_pct())

    def _vcell(self):
        return min(0xFFFF, round(self._cell_v() / VCELL_LSB_V))

    def _soc(self):
        return min(0xFFFF, round(self._soc_pct() * 256))

    def _update_alerts(self):
        """CONFIG.ALRT and STATUS.VH/VL follow the cell against the thresholds."""
        v20 = round(self._cell_v() / VALRT_LSB_V)
        lo, hi = self.regs[VALRT] >> 8, self.regs[VALRT] & 0xFF
        st = self.regs[STATUS]
        if v20 > hi:
            st |= VH
        if v20 < lo:
            st |= VL
        self.regs[STATUS] = st
        low_soc = self._soc_pct() <= 32 - (self.regs[CONFIG] & ATHD_MASK)
        if low_soc or st & (VH | VL):
            self.regs[CONFIG] |= ALRT

    def _word(self, a):
        if a == VCELL:
            return self._vcell()
        if a == SOC:
            return self._soc()
        if a == VERSION:
            return 0x0012
        if a == CRATE:
            return 0
        if a in self.regs:
            self._update_alerts()
            return self.regs[a]
        return 0

    def _log(self, verb, a, w):
        n = NAMES.get(a & ~1, "TABLE (battery model)" if 0x40 <= a < 0xA0 else f"reg {a:#04x}")
        val = {VCELL: f"{w * VCELL_LSB_V:.2f} V", SOC: f"{w / 256:.0f} %"}.get(a & ~1, f"{w:#06x}")
        self.ctx.info(f"max17048 t={self.ctx.now_us / 1e6:.4f} {verb} {n} = {val}")

    def on_write(self, data):
        if not data:
            return
        self.ptr = data[0]
        for i in range(1, len(data) - 1, 2):
            self._log("write", self.ptr + i - 1, (data[i] << 8) | data[i + 1])
        rest = data[1:]
        for i in range(0, len(rest) - 1, 2):
            a, v = (self.ptr & ~1) & 0xFF, (rest[i] << 8) | rest[i + 1]
            if a == CMD:
                if v == POR_CMD:
                    self.regs = dict(RESET)
            elif a in WRITABLE:
                m = WRITABLE[a]
                self.regs[a] = (self.regs[a] & ~m) | (v & m)
            self.ptr = (self.ptr + 2) & 0xFF

    def on_read(self, count):
        out = bytearray()
        if self.ptr % 2 == 0 and count >= 2:
            self._log("read", self.ptr, self._word(self.ptr))
        for _ in range(count):
            w = self._word(self.ptr & ~1)
            out.append(w >> 8 if self.ptr % 2 == 0 else w & 0xFF)
            self.ptr = (self.ptr + 1) & 0xFF
        return bytes(out)
