"""Self-tests for the framing and accel batch of peers/spi/garmin_sensor_hub_spi.py with a fake ctx.

    python3 -m pytest peers/tests/test_garmin_sensor_hub_spi.py
"""
import importlib.util
from pathlib import Path

PEER = Path(__file__).resolve().parents[1] / "spi" / "garmin_sensor_hub_spi.py"


class FakeGpio:
    def set(self, level):
        pass


class FakeCtx:
    now_us = 5_000_000
    config = {}

    def log(self, *a):
        pass

    def gpio(self, n):
        return FakeGpio()

    def schedule_oneshot(self, us):
        pass

    info = warning = error = debug = noisy = log


def make():
    spec = importlib.util.spec_from_file_location("hubspi", PEER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod, mod.Slave(FakeCtx())


def test_header_checksum_and_message():
    mod, _ = make()
    assert mod.valid(mod.header(0x188D, 12, 12, 1))
    assert mod.message(0x1890, b"abc")[14:] == b"abc"


def test_accel_config_is_echoed_and_batch_matches_handler_layout():
    mod, hub = make()
    cfg = bytes(4) + (25).to_bytes(4, "little") + (1000).to_bytes(2, "little") + (8).to_bytes(2, "little")
    hub.payload(0x188D, 12, cfg)
    assert hub.outbox[0][14:] == cfg                     # 0xb38c8 takes the echo as the ack
    p = hub.accel_batch()
    n = int.from_bytes(p[2:4], "little")
    assert (p[1], n, len(p)) == (20, 25, 20 + 6 * 25)    # offset, count and the 3 x int16 stride read by 0xb42bc
    z = [int.from_bytes(p[20 + 6 * i + 4:22 + 6 * i + 4], "little", signed=True) for i in range(n)]
    assert all(3900 < v < 4300 for v in z)               # 1 g at +-8 g full scale = 4096 LSB
