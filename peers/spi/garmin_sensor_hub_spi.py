# Garmin FR245 sensor hub (Ambiq Apollo2 per the iFixit teardown) as ONE SPI slave peer on the K28's SPI2,
# PCS0: it owns the SPI bus side and the two handshake pads. Lines: output 0 = SRDY (MCU PTB5, active low),
# input 1 = RESET_N (MCU PTA27). Wire: `hubspi: SPI.ScriptedSpiSlave @ spi2 0`, `0 -> gpiob@5`, `gpioa: 27 -> hubspi@1`.
#
# What the K28 does (observed with --trace-memory on SPI2 PUSHR, not from a datasheet):
#   hub reset (PTA27 low 20 ms), 500 ms wait, SRDY falling-edge interrupt armed (driver 0xcf58c, descriptor
#   0xcf6f0, polarity byte 0 = active low, 1 s give-up then one more hard reset). On each SRDY assertion it runs
#   a CS window  [0x80, 0x24]   (write, one data byte) and, on the next assertion, [0x7f, 14 reads] (read).
#   The instruction byte matches the Apollo2 IOS host interface (bit 7 = write, 6:0 = address, 0x7f = FIFO).
#   Header validator in the firmware (0xce688): b[0] == 0x24, b[1] == -(b[2]+...+b[12]) & 0xFF, then b[12] has bit 7 set
#   or b[13] == 0x24. The K28's own request is 24 FA 06 00*10 24 (type/id 0x0006). Its parser then compares the
#   halfword b[2..3] with an expected value (0xced28) and stores the word at b[8..11].
# NOT YET WORKING: with the echo header below the firmware still takes its hub-missing path (0xbc484 at +0.4 s after
# the first SRDY); what the reply must contain beyond the validated header is unresolved.
# MODELED SIMPLIFICATION: SRDY cadence and the reply header are guesses; config "trace": true logs every byte
# as "hubspi t=<us> mosi=<hex> miso=<hex>", "header": "<28 hex digits>" overrides the reply.
BOOT_US, PERIOD_US, PULSE_US = 100_000, 100_000, 1_000
FILL = 0xFF
HEADER = bytes([0x24, 0xFA, 0x06]) + bytes(10) + bytes([0x24])
GAP_US = 20  # CS windows are told apart by a pause; on_select is not delivered for this bus


class Slave:
    def __init__(self, ctx):
        self.ctx = ctx
        cfg = getattr(ctx, "config", {})
        self.trace = bool(cfg.get("trace", False))
        self.boot_us = int(cfg.get("boot_us", BOOT_US))
        self.period_us = int(cfg.get("period_us", PERIOD_US))
        self.pulse_us = int(cfg.get("pulse_us", PULSE_US))
        self.header = bytes.fromhex(cfg["header"]) if "header" in cfg else HEADER
        self.running = self.low = False
        self.last = -1000
        self.mosi, self.miso = bytearray(), bytearray()
        ctx.gpio(0).set(True)

    def on_gpio(self, line, level):
        if line != 1:
            return
        self.running, self.low = bool(level), False
        self.ctx.gpio(0).set(True)
        if self.running:
            self.ctx.schedule_oneshot(self.boot_us)

    def on_timer(self):
        if not self.running:
            return
        self.low = not self.low
        self.ctx.gpio(0).set(not self.low)
        self.ctx.schedule_oneshot(self.pulse_us if self.low else self.period_us - self.pulse_us)

    def on_select(self):
        self.mosi, self.miso = bytearray(), bytearray()

    def on_transmit(self, b):
        now = self.ctx.now_us
        if now - self.last > GAP_US:
            self.mosi, self.miso = bytearray(), bytearray()
        self.last = now
        i = len(self.mosi)
        self.mosi.append(b)
        out = FILL
        if self.mosi[0] == 0x7F and 1 <= i <= len(self.header):
            out = self.header[i - 1]
        self.miso.append(out)
        if self.trace:
            self.ctx.info(f"hubspi t={self.ctx.now_us} mosi={b:02x} miso={out:02x}")
        return out

    def on_deselect(self):
        if self.trace and self.mosi:
            self.ctx.info(f"hubspi t={self.ctx.now_us} mosi={self.mosi.hex()} miso={self.miso.hex()}")
