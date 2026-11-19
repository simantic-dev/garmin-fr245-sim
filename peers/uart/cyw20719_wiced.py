# Counterpart for the CYW20719 radio on the FR245's LPUART0 (reset line PTA26, BAUD OSR 13 / SBR 1).
# Frame, read off the firmware's own sender (0xbe074) and receive state machine (0xbe32c), v3.10:
#   19 | B1 | B2 | LEN16 | OPCODE16 | payload      (little endian; LEN = 2 + payload length; the host sends 00 13)
# Received frames are logged. The only frame sent is the one that opens the firmware's send gate:
# opcode 0x1b4a (firmware flag 0x20010079 is set by it, and its sender returns early until then).
#
# MODELED SIMPLIFICATION: this is NOT a WICED HCI Control or HCI implementation. No CYW image and no spec for
# Garmin's own opcodes exist here, so there is no reset/patch/version handling. The peer speaks when the DUT's
# LPUART0 receiver turns on (`on_rx_enable`, CTRL[RE]), not on timers. Advertising is bridged to the sim's BLE
# medium (`ctx.ble_*`): the 0x08 config command is parsed and put on the air by the sim's link layer.
HEADER = 0x19
# "Stack enabled" event. Read off the firmware, v3.10: the radio-event task (0xd18b0) hands opcodes 0x1984..0x1986
# to 0x31614, which forwards the payload as a message to 0x30f00. A message whose byte 0 is 0x24 sets the
# stack-enabled flag 0x1fffe948 and runs every callback registered through 0x30e7c. Until then that registration
# returns 5, and the BLE init 0x226774 leaves its state machine (0x1fffe988) at 1 for good. The callback 0x226588
# then runs the deferred init 0x2264dc. Layout (0x31498, case 0x24): [0]=type, [3..4]=body length, [6..7]=data
# length, [8..11]=data pointer slot, all zero here, so the 12-byte message carries no data.
# MODELED SIMPLIFICATION: which opcode in 0x1984..0x1986 the real radio uses, and the body of its 0x24 message
# (BD address, 27-byte max payload at 0x30f00), are not known; this sends the empty message under 0x1984.
STACK_UP_OPCODE = 0x1984
STACK_UP_MSG = bytes([0x24]) + bytes(11)


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
        self.handle = 0
        self.name = b""
        self.adv_on = False

    def _send(self, data):
        self.ctx.info(f"cyw tx t={self.ctx.now_us / 1e6:.4f} {data.hex()}")
        self.ctx.send(data)

    def on_rx_enable(self):
        self._send(frame(0x1B4A))
        self._send(frame(STACK_UP_OPCODE, STACK_UP_MSG))

    def advertise(self, cfg):
        """The 400-byte 0x08 config (offsets read off its builder 0x2233c0): [399] mode, [40] UUID count, [42..] the
        16-bit UUIDs, [113] company, [115] manufacturer data length, [117..] that data, [196] flags."""
        on = cfg[399] == 1
        if not on:
            if self.adv_on:
                self.ctx.ble_advertise(False)
            self.adv_on = False
            self.ctx.info(f"cyw adv off t={self.ctx.now_us / 1e6:.3f}s")
            return
        ad = bytes([2, 0x01, cfg[196]])
        n = cfg[40]
        if n:
            ad += bytes([1 + 2 * n, 0x03]) + cfg[42:42 + 2 * n]
        mlen = cfg[115] | cfg[116] << 8
        ad += bytes([3 + mlen, 0xFF]) + cfg[113:115] + cfg[117:117 + mlen]
        # MODELED SIMPLIFICATION: flags + UUID + manufacturer data leave 13 of the 31 AdvData bytes, so the full
        # name (0x16 command) goes in the scan response and a shortened name rides in the ADV_IND. Which of the
        # two the real radio uses is not known.
        room = 31 - len(ad) - 2
        nm = self.name[:room].rstrip()
        if nm:
            ad += bytes([1 + len(nm), 0x08 if len(self.name) > room else 0x09]) + nm
        self.ctx.ble_adv_data(ad)
        self.ctx.ble_scan_rsp(bytes([1 + len(self.name), 0x09]) + self.name)
        self.ctx.ble_advertise(True)
        self.adv_on = True
        self.ctx.info(f"cyw adv on t={self.ctx.now_us / 1e6:.3f}s ad={ad.hex()}")

    def on_byte(self, b):
        f = self.parser.feed(b)
        if f:
            self.ctx.info(f"cyw rx t={self.ctx.now_us / 1e6:.4f} opcode={f[0]:#06x} payload={f[1].hex()}")
            if f[0] == 0x1982 and f[1][:1] == b"\x16" and len(f[1]) >= 12:
                # Set device name: [6..7] length, name bytes from [12] (0x2233c0's neighbour; "Forerunner 245").
                self.name = f[1][12:12 + (f[1][6] | f[1][7] << 8)]
            if f[0] == 0x1982 and f[1][:1] == b"\x08" and len(f[1]) == 400:
                self.advertise(f[1])
            if f[0] == 0x1982 and f[1][:1] == b"\x37" and len(f[1]) >= 20:
                # Add-service command (37 <app id> 14 00 <16-byte UUID>), nine of them from the table at 0x223ccc.
                # The handler (0x223578 case 0x37 -> 0x2235ce) matches [10..25] against that table, stores [9]
                # as the service's handle and counts matches; the step machine moves on after the ninth.
                # MODELED SIMPLIFICATION: handles are numbered from 0x10 in arrival order; real values unknown.
                self.handle += 1
                msg = bytearray(26)
                msg[3] = f[1][1]
                msg[4] = 0x37
                msg[9] = 0x10 + self.handle
                msg[10:26] = f[1][4:20]
                self._send(frame(0x1983, msg))
            if f[0] == 0x1982 and f[1][:1] in (b"\x16", b"\x12", b"\x14", b"\x08") or (
                    f[0] == 0x1982 and f[1][:1] not in (b"\x37", b"\x42", b"\x01")):
                # Generic status-ok event: [3] app id, [4] = the command byte (pending op for 0x16, 0x12, 0x14, 8 per
                # 0x223578 case 0x223622). For 0x29, 0x2b, 0x2f (GATT table build, response handler 0x2250a0) the
                # firmware needs a non-zero u16 at [9..10]: 0x2253d0 sends nothing more while 0x1fffe888 is 0.
                # MODELED SIMPLIFICATION: handles are numbered from 0x0100 in arrival order; real values unknown.
                msg = bytearray(16)
                msg[3] = f[1][1]
                msg[4] = f[1][0]
                self.handle += 1
                msg[9] = self.handle
                msg[10] = 1
                self._send(frame(0x1983, msg))
            if f[0] == 0x1982 and f[1][:1] == b"\x42":
                # Second host command (42 <app id> 05 00 06). The step machine 0x223bd0 sets its pending-op byte
                # 0x1fffe971 to 6 (0x223c00) and its response handler 0x223578 (case 6 -> 0x223622) advances to the next step on an
                # event with [4] == 6 and [2] == 0 (status ok).
                # MODELED SIMPLIFICATION: that command 0x42 is answered by event type 6 is inferred from that
                # pairing, not from a spec; the other event bytes are zero.
                msg = bytearray(16)
                msg[3] = f[1][1]  # app id: 0x2261ac drops events whose [3] differs from the id in 0x1fffe986
                msg[4] = 6
                self._send(frame(0x1983, msg))
            if f[0] == 0x1982 and len(f[1]) >= 7 and f[1][:1] == b"\x01":
                # The host registered an app (0x1982: [4..6] = tag). Its handler 0x2261ac, run from opcode 0x1983
                # via 0x31614/0x30e44, takes [4]==1 as the registration reply, needs [10..12] equal to the tag
                # it sent and stores [9], the app id, in 0x1fffe986 (0xff = still waiting); the BLE state
                # machine waits on that byte in state 5 (0x22642c).
                # MODELED SIMPLIFICATION: app id 1 and the rest of the 0x1983 event (bytes 0..3, 5..8) are
                # not known; they are zero.
                msg = bytearray(16)
                msg[4] = 1
                msg[9] = 1
                msg[10:13] = f[1][4:7]
                self._send(frame(0x1983, msg))
