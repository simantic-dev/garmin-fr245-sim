# Sony CXD5603 GNSS behind LPUART3 (MCU 0x400C7000, 115200). Framing, command queue and ACK check are read
# off the firmware, not a datasheet: Garmin DLE frames  10 id len payload cksum 10 03  (DLE doubled in the
# body, cksum = -(id+len+payload)). RX parser 0xAC874; id 0x7b is a wrapper
#   payload = u32 data_len | u16 inner_id | data      (the firmware's own TX and the RX parser agree).
# Command queue 0xAC3D4: send, wait 3000 ms for the ACK, resend once, then move on.
# The ACK it waits for is inner id 0xBD5 sub-id 8 (parser 0xAC9xx, check at 0xACA58), data layout
#   u16 sub=8 | u16 - | u32 - | u16 inst_id | u16 ack_sub | u32 data_size | u32 status
# and it matches inst_id == sent message id, ack_sub == 0xFFFF (0x0A and 0xBD5: first u16 of the data),
# data_size == len(data of the sent message) (set by 0xAC27C). status is printed only, except for 0x0A/0x3A.
import struct

DLE, ETX = 0x10, 0x03


def frame(pid, data=b""):
    body = bytes([pid, len(data)]) + bytes(data)
    ck = (-sum(body)) & 0xFF
    esc = lambda b: b"\x10\x10" if b == DLE else bytes([b])
    return bytes([DLE]) + b"".join(esc(b) for b in body + bytes([ck])) + bytes([DLE, ETX])


def wrapped(inner_id, data=b""):
    return frame(0x7B, struct.pack("<IH", len(data), inner_id) + bytes(data))


def bd5(sub, data=b""):
    """BD5 message body (same struct the firmware queues): u16 sub | u16 0 | u32 data_size | data."""
    return wrapped(0xBD5, struct.pack("<HHI", sub, 0, len(data)) + bytes(data))


def ack(inst_id, sub, size, status=0):
    return bd5(8, struct.pack("<HHII", inst_id, sub, size, status))


class Peer:
    def __init__(self, ctx):
        self.ctx = ctx
        cfg = getattr(ctx, "config", None) or {}
        self.log = bool(cfg.get("log", True))
        self.acks = bool(cfg.get("ack", True))
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
            self.ctx.info(f"gnss bad frame {body.hex()}")
            return
        pid, data = body[0], body[2:-1]
        if pid == 0x7B and len(data) >= 6:
            mid, data = struct.unpack_from("<H", data, 4)[0], data[6:]
        else:
            mid = pid
        if self.log:
            self.ctx.info(f"gnss rx t={self.ctx.now_us / 1e6:.4f} id={pid:#04x} msg={mid:#06x} data={data.hex()}")
        if not self.acks or mid == 0xBD5 and data[:2] == b"\x08\x00":
            return
        if mid == 0xBD5 and data[:2] == b"\x01\x00":
            # sub 1 = device config (32 bytes): the firmware compares the chip's reply with the config it wants (0xAE8D8)
            self.ctx.info("gnss tx echo cfg"); self.ctx.send(bd5(1, data[8:]))
        sub = struct.unpack_from("<H", data, 0)[0] if mid in (0x0A, 0xBD5) and len(data) >= 2 else 0xFFFF
        self.ctx.send(ack(mid, sub, len(data)))
