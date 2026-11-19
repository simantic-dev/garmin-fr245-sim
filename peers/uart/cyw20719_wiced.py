# Counterpart for the CYW20719 radio on the FR245's LPUART0 (reset line PTA26, BAUD OSR 13 / SBR 1).
# Frame, read off the firmware's own sender (0xbe074) and receive state machine (0xbe32c), v3.10:
#   19 | B1 | B2 | LEN16 | OPCODE16 | payload      (little endian; LEN = 2 + payload length; the host sends 00 13)
# Received frames are logged. The only frame sent is the one that opens the firmware's send gate:
# opcode 0x1b4a (firmware flag 0x20010079 is set by it, and its sender returns early until then).
#
# MODELED SIMPLIFICATION: this is NOT a WICED HCI Control or HCI implementation. No CYW image and no spec for
# Garmin's own opcodes exist here, so there is no reset/patch/version/advertising handling and no BLE medium
# bridge. After 0x1b4a the firmware still sent nothing in 40 s of virtual time. The 5.0 s send time is a stand-in
# for "after the reset line is released" (the firmware releases PTA26 at about 4.86 s).
START_US = 5_000_000
PERIOD_US = 1_000_000
HEADER = 0x19


def frame(opcode, payload=b"", b1=0x00, b2=0x13):
    n = 2 + len(payload)
    return bytes([HEADER, b1, b2, n & 255, n >> 8, opcode & 255, opcode >> 8]) + bytes(payload)


class Parser:
    """Byte-at-a-time decoder; feed() returns (opcode, payload) when a frame completes, else None."""

    def __init__(self):
        self.buf = bytearray()

    def feed(self, b):
        self.buf.append(b)
        if self.buf[0] != HEADER:
            self.buf.clear()
            return None
        if len(self.buf) < 7:
            return None
        n = self.buf[3] | self.buf[4] << 8
        if len(self.buf) < 5 + n:
            return None
        out = (self.buf[5] | self.buf[6] << 8, bytes(self.buf[7:5 + n]))
        self.buf.clear()
        return out


class Peer:
    def __init__(self, ctx):
        self.ctx = ctx
        self.parser = Parser()
        self.heard = False
        ctx.schedule_oneshot(START_US)

    def on_timer(self):
        # MODELED SIMPLIFICATION: the sim has no radio-ready event for this UART, and bytes sent while the
        # firmware's LPUART0 is still disabled are dropped, so repeat the gate-opener once a second until
        # the host sends its first byte.
        if not self.heard:
            self.ctx.send(frame(0x1B4A))
            self.ctx.schedule_oneshot(PERIOD_US)

    def on_byte(self, b):
        self.heard = True
        f = self.parser.feed(b)
        if f:
            self.ctx.info(f"cyw rx opcode={f[0]:#06x} payload={f[1].hex()}")
