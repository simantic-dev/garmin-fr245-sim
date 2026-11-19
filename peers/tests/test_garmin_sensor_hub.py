"""python3 peers/tests/test_garmin_sensor_hub.py"""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("hub", Path(__file__).resolve().parent.parent / "gpio" / "garmin_sensor_hub.py")
hub = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hub)


class Pin:
    def __init__(self, ctx): self.ctx = ctx
    def set(self, v): self.ctx.srdy = bool(v)


class Ctx:
    def __init__(self):
        self.now_us, self.srdy, self.timers, self.config = 0, None, [], {"boot_us": 1000, "period_us": 5000, "pulse_us": 100}
    def gpio(self, n): return Pin(self)
    def info(self, s): pass
    def schedule_oneshot(self, us): self.timers.append(self.now_us + us)


def test_srdy_idles_high_then_pulses_low_after_reset_release():
    c = Ctx(); s = hub.Slave(c)
    assert c.srdy is True
    s.on_gpio(hub.RESET_LINE, False)
    s.on_gpio(hub.RESET_LINE, True)
    assert c.srdy is True and c.timers == [1000]
    s.on_timer()
    assert c.srdy is False
    s.on_timer()
    assert c.srdy is True
    s.on_gpio(hub.RESET_LINE, False)
    s.on_timer()
    assert c.srdy is True, "no pulses while in reset"


if __name__ == "__main__":
    test_srdy_idles_high_then_pulses_low_after_reset_release(); print("ok")
