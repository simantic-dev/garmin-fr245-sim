import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("m", Path(__file__).resolve().parent.parent / "i2c" / "max20303.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class Ctx:
    def __init__(self):
        self.lines = {}
        self.now_us = 0

    def info(self, s):
        pass

    def gpio(self, n):
        c = self

        class G:
            def set(self, v):
                c.lines[n] = bool(v)
        return G()


def test_ids_and_intb_clear_on_read():
    c = Ctx()
    s = m.Slave(c)
    assert c.lines[0] is True
    s.on_write(bytes([0]))
    assert s.on_read(2) == bytes([2, 2])
    s.raise_int(0x04, 0x08)
    assert c.lines[0] is False
    s.on_write(bytes([3]))
    assert s.on_read(3) == bytes([0, 0x08, 0])
    assert c.lines[0] is True


if __name__ == "__main__":
    test_ids_and_intb_clear_on_read()
    print("ok")
