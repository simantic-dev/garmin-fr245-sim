# Garmin FR245 sensor hub (Apollo-class MCU per the teardown) as ONE SPI slave peer on the K28's SPI2, PCS0.
# Wire: `hubspi: SPI.ScriptedSpiSlave @ spi2 0`, `numberOfGpios: 3`, `0 -> gpiob@5` (SRDY, PTB5),
# `2 -> gpioa@11` (ATTN, PTA11), `gpioa: 27 -> hubspi@1` (RESET_N, PTA27).
#
# Everything below is read off the K28 firmware (v3.10, driver 0xcea60/0xcebb0/0xcef60, descriptor 0xcf6f0), not a datasheet.
#   Lines: PTB5 = SRDY, active low (descriptor byte 20 = 0). The driver waits for its FALLING edge before every SPI window;
#          if PTB5 is low when it wants to start it first waits for it to go high (PORTB IRQC 0xC, level high), then arms IRQC 0xA.
#          PTA11 = ATTN, active high (descriptor byte 21 = 1): the hub raises it when it has a message; the receive thread
#          then runs the poll below and waits for it to drop (PORTA IRQC 0x8).
#   Frame: 14-byte header  b0 0x24 | b1 -(b2..b12)&0xFF | b2..b3 id LE | b4..b7 A | b8..b11 B | b12 flags/len | b13 0x24.
#   Write window  [0x80, header]   (bit 7 = write, Apollo IOS style); read window [0x7f, 14 header bytes, payload ...].
#   K28 request:  id, A/B/b12 = inline payload (b12 & 15 = inline length, <= 8 bytes) or A = length of a streamed payload.
#   Hub reply to a request: header with the SAME id and b12 low nibble (0xcf480 checks both); for a streamed request B (b8..b11)
#          must be non-zero (0xced28 path, B = bytes the hub accepts per write window).
#   Poll: when ATTN is high the K28 sends a request with id 3; the reply header carries the hub's message: id, A = B = payload length,
#          b12 bit 0 set = payload follows in the SAME read window (0xcf084: A must equal B; callbacks 0xbc2c8 alloc / 0xbc2e4 done).
#   Hub present (0xbc188): the K28 sends id 0x0a with payload 84 06, then needs a hub message 0x186c (first u16 non-zero, stored at
#          0x20010040) and a message 0x1876 (ASCII text, <= 40 bytes, stored at 0x200015ac). 0x186c also starts every sensor manager.
#
# MODELED SIMPLIFICATIONS: LAT_US (hub processing time between the end of a K28 window and its SRDY), READY_US (SRDY falling edge
# offering the next command window) and IDLE_US (an offer every IDLE_US while the bus is idle: the K28 starts a command by waiting
# for an edge and sends nothing the hub could react to first) are guesses; PULSE_US is the low time of an SRDY edge.
# Config keys: "trace", "boot_us", "lat_us", "ready_us", "idle_us", "pulse_us", "hubid", "version", "streams".
import heapq

BOOT_US, LAT_US, READY_US, IDLE_US, PULSE_US = 20_000, 300, 100, 100_000, 100
GAP_US = 30          # a CS window ends when no byte follows for this long (on_select/on_deselect are not delivered)
SRDY, ATTN, RESET = 0, 2, 1
ID_POLL, ID_HELLO, ID_HUB_INFO, ID_HUB_VERSION = 3, 0x0A, 0x186C, 0x1876


def header(mid, a=0, b=0, flags=0):
    h = bytearray([0x24, 0, mid & 0xFF, mid >> 8]) + a.to_bytes(4, "little") + b.to_bytes(4, "little") + bytes([flags, 0x24])
    h[1] = -sum(h[2:13]) & 0xFF
    return bytes(h)


def valid(h):
    return len(h) == 14 and h[0] == 0x24 and h[1] == -sum(h[2:13]) & 0xFF and (h[12] & 0x80 or h[13] == 0x24)


def message(mid, payload):
    """A hub-to-K28 message: streamed header (flags bit 0) and the payload in the same read window."""
    return header(mid, len(payload), len(payload), 1) + bytes(payload)


class Slave:
    def __init__(self, ctx):
        self.ctx = ctx
        cfg = getattr(ctx, "config", {})
        g = lambda k, d: int(cfg.get(k, d))
        self.trace = bool(cfg.get("trace", False))
        self.boot_us, self.lat_us, self.ready_us = g("boot_us", BOOT_US), g("lat_us", LAT_US), g("ready_us", READY_US)
        self.idle_us, self.pulse_us = g("idle_us", IDLE_US), g("pulse_us", PULSE_US)
        self.hubid = g("hubid", 0x0100)
        self.version = str(cfg.get("version", "SNSHUB 3.10 sim")).encode()[:40]
        self.running = False
        self.events = []          # heap of (due_us, seq, name)
        self.seq = 0
        self.outbox = []          # hub-to-K28 messages, each header + payload bytes
        self.reply = b""          # what the next read window returns
        self.mosi, self.miso, self.last = bytearray(), bytearray(), -10**9
        self.low = False
        self.log = []             # (t_us, kind, id) per decoded request, for tests and tracing
        ctx.gpio(SRDY).set(True)
        ctx.gpio(ATTN).set(False)

    def at(self, delay_us, name):
        self.seq += 1
        heapq.heappush(self.events, (self.ctx.now_us + delay_us, self.seq, name))
        self.ctx.schedule_oneshot(max(1, int(delay_us)))

    def drop(self, name):
        self.events = [e for e in self.events if e[2] != name]
        heapq.heapify(self.events)

    def queue(self, mid, payload):
        self.outbox.append(message(mid, payload))
        self.ctx.gpio(ATTN).set(True)

    def on_gpio(self, line, level):
        if line != RESET:
            return
        self.running = bool(level)
        self.events, self.outbox, self.reply, self.low = [], [], b"", False
        self.ctx.gpio(SRDY).set(True)
        self.ctx.gpio(ATTN).set(False)
        if self.running:
            self.at(self.boot_us, "strobe")

    def on_timer(self):
        now = self.ctx.now_us
        if self.mosi and now - self.last >= GAP_US:
            self.window_end()
        while self.events and self.events[0][0] <= now:
            _, _, name = heapq.heappop(self.events)
            if name == "strobe" and self.running:
                self.ctx.gpio(SRDY).set(False)
                self.at(self.pulse_us, "release")
            elif name == "release":
                self.ctx.gpio(SRDY).set(True)
                self.at(self.idle_us, "strobe")

    def on_transmit(self, b):
        now = self.ctx.now_us
        if now - self.last > GAP_US:
            self.mosi, self.miso = bytearray(), bytearray()
        self.last = now
        i = len(self.mosi)
        self.mosi.append(b)
        out = 0xFF
        if self.mosi[0] == 0x7F and 1 <= i <= len(self.reply):
            out = self.reply[i - 1]
        self.miso.append(out)
        self.at(GAP_US + 1, "gap")
        return out

    def window_end(self):
        w, self.mosi = bytes(self.mosi), bytearray()
        if self.trace:
            self.ctx.info(f"hubspi t={self.ctx.now_us} mosi={w.hex()} miso={bytes(self.miso).hex()}")
        self.drop("strobe")
        if w[:1] == b"\x7f":
            if self.outbox and self.reply is self.outbox[0]:
                self.outbox.pop(0)
            if not self.outbox:
                self.ctx.gpio(ATTN).set(False)
            self.reply = b""
            self.at(self.ready_us, "strobe")
        elif w[:1] == b"\x80" and valid(w[1:15]):
            self.request(w[1:15])
            self.at(self.lat_us, "strobe")
        else:
            self.at(self.ready_us, "strobe")

    def request(self, h):
        mid = h[2] | h[3] << 8
        self.log.append((self.ctx.now_us, "req", mid))
        if mid == ID_POLL:
            self.reply = self.outbox[0] if self.outbox else header(ID_POLL)
            return
        if mid == ID_HELLO:
            self.queue(ID_HUB_INFO, self.hubid.to_bytes(2, "little") + bytes(6))
            self.queue(ID_HUB_VERSION, self.version)
        self.reply = header(mid, int.from_bytes(h[4:8], "little"), (int.from_bytes(h[8:12], "little") or 0x100) if h[12] & 0x0F == 0 and h[4:8] != bytes(4) else int.from_bytes(h[8:12], "little"), h[12] & 0x0F)
