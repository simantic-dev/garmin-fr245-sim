# Counterpart on the Garmin FR245's LPUART3 host link (MCU side 0x400C7000, IRQ 33), as the firmware
# drives it. Read off the firmware, not a datasheet: the driver (UART TX at 0xc26ac) sends Garmin
# Device-Interface frames, DLE(0x10) ID SIZE DATA.. CKSUM DLE ETX(0x03), with CKSUM = -(ID+SIZE+DATA)
# and a DLE inside the body doubled. The first frame is ID 0x2f SIZE 1 DATA 00; with no answer the
# firmware repeats it every 3.0 s and gives up after the third try (12.65 s).
#
# MODELED SIMPLIFICATION: the chip behind the link is unidentified and its command set unknown. Config
# "mode": "log" (default, answers nothing), "ack" (Device-Interface ACK, ID 0x06 DATA = acked ID) or "echo"
# (the same frame back). MEASURED 2026-11-18: neither "ack" nor "echo" stops the 3 s retry (the firmware reads
# the bytes from DATA and sends 0x2f again), so the answer the firmware waits for is still unknown. "log" prints
# each frame via ctx.info ("log": false silences it).
DLE, ETX = 0x10, 0x03


def frame(pid, data=b""):
    body = bytes([pid, len(data)]) + bytes(data)
    ck = (-sum(body)) & 0xFF
    esc = lambda b: b"\x10\x10" if b == DLE else bytes([b])
    return bytes([DLE]) + b"".join(esc(b) for b in body + bytes([ck])) + bytes([DLE, ETX])


class Peer:
    def __init__(self, ctx):
        self.ctx = ctx
        cfg = getattr(ctx, "config", None) or {}
        self.mode = cfg.get("mode", "log")
        self.log = bool(cfg.get("log", True))
        self.buf = bytearray()
        self.dle = False

    def on_byte(self, b):
        if self.dle:
            self.dle = False
            if b == ETX:
                self._frame(bytes(self.buf))
                self.buf.clear()
            else:  # DLE DLE is one data byte
                self.buf.append(b)
        elif b == DLE:
            self.dle = True
        else:
            self.buf.append(b)

    def _frame(self, body):
        if len(body) < 3 or body[1] != len(body) - 3 or sum(body) & 0xFF:
            self.ctx.info(f"garmin-link bad frame {body.hex()}")
            return
        pid, data = body[0], body[2:-1]
        if self.log:
            self.ctx.info(f"garmin-link rx id={pid:#04x} data={data.hex()}")
        mode = self.mode
        if mode == "ack" and pid not in (0x06, 0x15):
            self.ctx.send(frame(0x06, bytes([pid])))
        elif mode == "echo":
            self.ctx.send(frame(pid, data))
