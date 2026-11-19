"""pin_script peer self-tests: no firmware, no simulator.

    python3 -m pytest peers/tests/test_pin_script.py
"""
import importlib.util
from pathlib import Path

PEER = Path(__file__).resolve().parent.parent / "gpio" / "pin_script.py"
spec = importlib.util.spec_from_file_location("pin_script", PEER)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class Pin:
    def __init__(self, ctx, line):
        self.ctx, self.line = ctx, line

    def set(self, level=True):
        self.ctx.log.append((self.ctx.now_us, self.line, bool(level)))

    def release(self):
        self.ctx.log.append((self.ctx.now_us, self.line, None))


class Ctx:
    def __init__(self, config):
        self.config = config
        self.now_us = 0
        self.log = []
        self.next_us = None

    def gpio(self, line):
        return Pin(self, line)

    def schedule_oneshot(self, us, fn=None):
        self.next_us = self.now_us + us


def run(config, until_us):
    ctx = Ctx(config)
    p = mod.Slave(ctx)
    while ctx.next_us is not None and ctx.next_us <= until_us:
        ctx.now_us, ctx.next_us = ctx.next_us, None
        p.on_timer()
    return ctx, p


def test_hold_is_a_press_between_two_times():
    ctx, _ = run({"idle": {"0": "release"}, "holds": [{"line": 0, "at_ms": 100, "for_ms": 200, "level": 0}]}, 1_000_000)
    assert ctx.log == [(0, 0, None), (100_000, 0, False), (300_000, 0, None)]


def test_hold_returns_to_a_driven_idle_level():
    ctx, _ = run({"idle": {"1": 1}, "holds": [{"line": 1, "at_ms": 5, "for_ms": 1, "level": 0}]}, 1_000_000)
    assert ctx.log == [(0, 1, True), (5_000, 1, False), (6_000, 1, True)]


def test_events_apply_in_time_order_and_stop_when_done():
    ctx, _ = run({"events": [{"at_ms": 20, "line": 2, "level": 1}, {"at_ms": 10, "line": 2, "level": 0}]}, 1_000_000)
    assert ctx.log == [(10_000, 2, False), (20_000, 2, True)]
    assert ctx.next_us is None


def test_simultaneous_events_share_one_wakeup_and_microsecond_keys_work():
    ctx, _ = run({"events": [{"at_us": 7, "line": 0, "level": 1}, {"at_us": 7, "line": 1, "level": 0}]}, 1_000_000)
    assert ctx.log == [(7, 0, True), (7, 1, False)]


def test_no_config_is_inert():
    ctx, _ = run({}, 1_000_000)
    assert ctx.log == [] and ctx.next_us is None


def test_input_lines_are_recorded():
    ctx, p = run({}, 0)
    ctx.now_us = 42
    p.on_gpio(0, 1)
    assert p.seen == [(42, 0, True)]
