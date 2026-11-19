# Garmin FR245 "Sensor Hub" SPI side (MCU SPI2 at 0x400AC000, PCS0; the firmware calls it SPI 0). The
# protocol is unpublished (14-byte headers starting 0x24), so this device does not answer: it reads
# the line as an absent or unresponsive slave would, MISO undriven and pulled up -> 0xFF, and
# optionally logs each byte it was sent (config {"trace": true, "name": "<label>"}) as "<label> <time_us> <hex>" on stderr.
# MODELED SIMPLIFICATION: idle 0xFF is a choice, not a measurement.
import sys

IDLE = 0xFF


class Slave:
    def __init__(self, ctx):
        self.ctx = ctx
        cfg = getattr(ctx, "config", {})
        self.trace = bool(cfg.get("trace", False))
        self.name = cfg.get("name", "hubspi")

    last = -10**9

    def on_transmit(self, b):
        if self.ctx.now_us - self.last > 1000:  # first byte of a burst
            self.ctx.info(f"hubspi t={self.ctx.now_us / 1e6:.4f} SPI transfer starts, first byte {b:02x}, hub does not answer")
        self.last = self.ctx.now_us
        if self.trace:
            print(f"{self.name} {self.ctx.now_us} {b:02x}", file=sys.stderr)
        return IDLE
