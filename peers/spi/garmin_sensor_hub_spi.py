# Garmin FR245 sensor hub (Apollo-class MCU per the teardown) as ONE SPI slave peer on the K28's SPI2, PCS0.
# Wire: `hubspi: SPI.ScriptedSpiSlave @ spi2 0`, `numberOfGpios: 3`, `0 -> gpiob@5` (SRDY, PTB5),
# `2 -> gpioa@11` (ATTN, PTA11), `gpioa: 27 -> hubspi@1` (RESET_N, PTA27).
#
# Everything below is read off the K28 firmware (v3.10, driver 0xcea60/0xcebb0/0xcef60, descriptor 0xcf6f0), not a datasheet.
#   Lines: PTB5 = SRDY, active low (descriptor byte 20 = 0). The driver waits for its FALLING edge before every SPI window;
#          if PTB5 is low when it wants to start it first waits for it to go high (PORTB IRQC 0xC, level high), then arms IRQC 0xA.
#          PTA11 = ATTN, active LOW (descriptor 0xcf6f0 byte 21 = 0, read back by 0xcf65c at run time): the hub pulls it low when it has a message; the receive thread
#          then runs the poll below and waits for it to drop (PORTA IRQC 0x8).
#   Frame: 14-byte header  b0 0x24 | b1 -(b2..b12)&0xFF | b2..b3 id LE | b4..b7 A | b8..b11 B | b12 flags/len | b13 0x24.
#   Write window  [0x80, header]   (bit 7 = write, Apollo IOS style); read window [0x7f, 14 header bytes, payload ...].
#   K28 request:  id, A/B/b12 = inline payload (b12 & 15 = inline length, <= 8 bytes) or A = length of a streamed payload.
#   Hub reply to a request: header with the SAME id and b12 low nibble (0xcf480 checks both); for a streamed request B (b8..b11)
#          must be non-zero (0xced28 path, B = bytes the hub accepts per write window).
#   Poll: when ATTN is low the K28 sends a request with id 3; the reply header carries the hub's message: id, A = B = payload length,
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
ID_ACCEL_CFG, ID_ACCEL_ACK, ID_ACCEL_DATA = 0x188D, 0x188D, 0x1890   # tbb table at 0xb38dc: 0x188d = config echo, 0x1890 = samples


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
        self.pend = None          # (id, length) of a streamed request whose payload window follows
        self.accel = None         # (rate_hz, batch_ms, range_g) from the K28's 0x188d
        self.rng = 1
        self.log = []             # (t_us, kind, id) per decoded request, for tests and tracing
        ctx.gpio(SRDY).set(True)
        ctx.gpio(ATTN).set(True)

    def at(self, delay_us, name):
        self.seq += 1
        heapq.heappush(self.events, (self.ctx.now_us + delay_us, self.seq, name))
        self.ctx.schedule_oneshot(max(1, int(delay_us)))

    def drop(self, name):
        self.events = [e for e in self.events if e[2] != name]
        heapq.heapify(self.events)

    def queue(self, mid, payload):
        self.outbox.append(message(mid, payload))
        self.ctx.gpio(ATTN).set(False)
        self.trace and self.ctx.info(f"ATTN asserted {self.ctx.now_us} id={mid:#x}")

    def on_gpio(self, line, level):
        if line != RESET:
            return
        self.running = bool(level)
        self.events, self.outbox, self.reply, self.low = [], [], b"", False
        self.ctx.gpio(SRDY).set(True)
        self.ctx.gpio(ATTN).set(True)
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
                self.trace and self.ctx.info(f"SRDY low {now}")
                self.at(self.pulse_us, "release")
            elif name == "accel" and self.accel:
                self.queue(ID_ACCEL_DATA, self.accel_batch())
                self.at(self.accel[1] * 1000, "accel")
            elif name == "release":
                self.ctx.gpio(SRDY).set(True)
                self.trace and self.ctx.info(f"SRDY high {now}")
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
        self.drop("release")
        self.ctx.gpio(SRDY).set(True)     # end of window: SRDY goes inactive and stays so until the next offer (0xce75c)
        if w[:1] == b"\x7f":
            if self.outbox and self.reply is self.outbox[0]:
                self.outbox.pop(0)
            if not self.outbox:
                self.ctx.gpio(ATTN).set(True)
                self.trace and self.ctx.info(f"ATTN released {self.ctx.now_us}")
            self.reply = b""
            self.at(self.ready_us, "strobe")
        elif w[:1] == b"\x80" and self.pend:
            self.payload(*self.pend, w[1:])
            self.pend = None
            self.at(self.lat_us, "strobe")
        elif w[:1] == b"\x80" and valid(w[1:15]):
            self.request(w[1:15])
            self.at(self.lat_us, "strobe")
        else:
            self.at(self.ready_us, "strobe")

    def payload(self, mid, n, data):
        if mid == ID_ACCEL_CFG and n == 12 and len(data) >= 12:
            rate, lat_ms, rng = int.from_bytes(data[4:8], "little"), *(int.from_bytes(data[i:i + 2], "little") for i in (8, 10))
            self.accel = (rate, lat_ms, rng)
            self.queue(ID_ACCEL_ACK, bytes(data[:12]))      # the K28 (0xb38c8 id 0x188d) takes the echo as the ack: rate equal, range >= asked
            self.drop("accel")
            self.at(lat_ms * 1000, "accel")

    def accel_batch(self):
        """0x1890 payload as 0xb38c8/0xb42bc read it: u8 type, u8 sample offset (20), u16 count n, u32 end time ms (+0x98),
        u32 0 (+0x9c, derived by the K28), u32 end time in 32768 Hz ticks (+0xa0), u32 0 (+0xa4), then n x int16 x,y,z.
        MODELED SIMPLIFICATION: flat wrist, +1 g on Z, +-0.012 g uniform noise; LSB = range/32768 g (the K28 scales by the range it asked for)."""
        rate, lat_ms, rng = self.accel
        n = max(1, min(39, rate * lat_ms // 1000))          # 39 = largest batch that fits the K28's 256 byte message buffer
        lsb_per_g = 32768 / rng
        samples = bytearray()
        for _ in range(n):
            for g in (0.0, 0.0, 1.0):
                self.rng = (self.rng * 1103515245 + 12345) & 0x7FFFFFFF
                v = int(lsb_per_g * (g + ((self.rng >> 16) % 25 - 12) / 1000))
                samples += v.to_bytes(2, "little", signed=True)
        ms = int(self.ctx.now_us // 1000)
        return bytes([0, 20]) + n.to_bytes(2, "little") + ms.to_bytes(4, "little") + bytes(4) + (ms * 32768 // 1000).to_bytes(4, "little") + bytes(4) + bytes(samples)

    def request(self, h):
        mid = h[2] | h[3] << 8
        if h[12] & 0x0F == 0 and mid != ID_POLL and int.from_bytes(h[4:8], "little"):
            self.pend = (mid, int.from_bytes(h[4:8], "little"))
        self.log.append((self.ctx.now_us, "req", mid))
        if mid == ID_POLL:
            self.reply = self.outbox[0] if self.outbox else header(ID_POLL)
            return
        if mid == ID_HELLO:
            self.queue(ID_HUB_INFO, self.hubid.to_bytes(2, "little") + bytes(6))
            self.queue(ID_HUB_VERSION, self.version)
        self.reply = header(mid, int.from_bytes(h[4:8], "little"), (int.from_bytes(h[8:12], "little") or 0x100) if h[12] & 0x0F == 0 and h[4:8] != bytes(4) else int.from_bytes(h[8:12], "little"), h[12] & 0x0F)
