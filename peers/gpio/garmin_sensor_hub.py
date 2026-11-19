# Garmin FR245 "Sensor Hub" (the SNS Hub the firmware probes at boot; part unidentified, protocol
# unpublished) as the MCU sees its handshake lines. Lines: input 0 = RESET_N (MCU PTA27, active low,
# the 20 ms pulse the driver at 0xbc4cc sends); output 0 = SRDY (MCU PTB5, active low: the driver
# descriptor at 0xcf6f0 has polarity byte 0 and the driver arms a falling-edge interrupt on it at 0xcf58c
# after its 500 ms post-reset wait, giving up after 1 s and hard-resetting the hub).
# Wire: `0 -> gpiob@5` under the peer, and `gpioa:` / `27 -> hub@0`.
#
# MODELED SIMPLIFICATION (read off the firmware, not a datasheet): SRDY idles high; BOOT_US after RESET_N
# is released the hub starts asserting SRDY low for PULSE_US every PERIOD_US, as a hub with a frame
# ready would, so whichever instant the driver arms its edge interrupt sees one within PERIOD_US. What
# makes a real hub assert SRDY, and the SPI0 frames that follow (14-byte headers starting 0x24), are not
# modelled. Config keys "boot_us", "period_us", "pulse_us" override the guesses below.
BOOT_US, PERIOD_US, PULSE_US = 100_000, 100_000, 1_000
RESET_LINE, SRDY_LINE = 0, 0


class Slave:
    def __init__(self, ctx):
        self.ctx = ctx
        cfg = getattr(ctx, "config", {})
        self.boot_us = int(cfg.get("boot_us", BOOT_US))
        self.period_us = int(cfg.get("period_us", PERIOD_US))
        self.pulse_us = int(cfg.get("pulse_us", PULSE_US))
        self.running = False
        self.low = False
        ctx.gpio(SRDY_LINE).set(True)

    def on_gpio(self, line, level):
        if line != RESET_LINE:
            return
        self.running = bool(level)
        self.low = False
        self.ctx.gpio(SRDY_LINE).set(True)
        if self.running:
            self.ctx.schedule_oneshot(self.boot_us)

    def on_timer(self):
        if not self.running:
            return
        self.low = not self.low
        self.ctx.gpio(SRDY_LINE).set(not self.low)
        self.ctx.schedule_oneshot(self.pulse_us if self.low else self.period_us - self.pulse_us)
