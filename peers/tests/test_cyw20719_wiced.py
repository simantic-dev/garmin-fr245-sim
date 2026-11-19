"""Self-tests for peers/uart/cyw20719_wiced.py framing with a fake ctx. No firmware, no simulator.

    python3 -m pytest peers/tests/test_cyw20719_wiced.py
"""
import importlib.util
from pathlib import Path

PEER = Path(__file__).resolve().parents[1] / "uart" / "cyw20719_wiced.py"
spec = importlib.util.spec_from_file_location("cyw", PEER)
cyw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cyw)


class Ctx:
    def __init__(self):
        self.sent, self.lines = [], []

    def send(self, d):
        self.sent.append(bytes(d))

    def info(self, m):
        self.lines.append(m)

    def schedule_oneshot(self, us):
        self.us = us


def test_frame_layout():
    assert cyw.frame(0x1B4A) == bytes.fromhex("19 00 13 02 00 4a 1b")
    assert cyw.frame(0x0BD6, b"\xaa\xbb") == bytes.fromhex("19 00 13 04 00 d6 0b aa bb")


def test_parser_roundtrip_and_resync():
    p = cyw.Parser()
    assert p.feed(0x55) is None  # junk before a header is dropped
    out = None
    for b in cyw.frame(0x1AF4, b"\x01\x02\x03"):
        out = p.feed(b)
    assert out == (0x1AF4, b"\x01\x02\x03")


def test_peer_opens_the_gate_and_logs():
    c = Ctx()
    peer = cyw.Peer(c)
    assert c.us == cyw.START_US
    peer.on_timer()
    assert c.sent == [bytes.fromhex("19 00 13 02 00 4a 1b")]
    assert c.us == cyw.PERIOD_US  # repeats until the host speaks
    for b in cyw.frame(0x0BD6):
        peer.on_byte(b)
    assert c.lines == ["cyw rx opcode=0x0bd6 payload="]


def test_gate_opener_stops_once_host_speaks():
    c = Ctx()
    peer = cyw.Peer(c)
    peer.on_byte(0x19)
    peer.on_timer()
    assert c.sent == []
