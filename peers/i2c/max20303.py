# Maxim MAX20303 wearable PMIC, power-management I2C slave at 7-bit 0x28 (Garmin FR245 board, I2C3).
# Registers: 0x00 HardwareID = 0x02 and 0x01 FirmwareID = 0x02 (MAX20303EVKIT default-values table);
# 0x03..0x05 INT0..INT2, read-to-clear. INTB (ctx.gpio(0), active low, open drain) is low while any
# INT bit is set and high otherwise; wire it to the MCU pad (`0 -> gpioa@21`).
# MODELED SIMPLIFICATION: the datasheet was not reachable, so addresses other than 0x00/0x01 follow the
# FR245 firmware's accesses (it reads 3 bytes at register 3 while INTB is low), not the datasheet. Other
# registers are plain storage; no buck/LDO/charger/AP_CMD behaviour, no interrupt sources (use raise()).
class Slave:
    def __init__(self, ctx):
        self.ctx = ctx
        self.regs = bytearray(256)
        self.regs[0x00] = self.regs[0x01] = 0x02
        self.ptr = 0
        ctx.gpio(0).set(True)

    def raise_int(self, reg, bits):
        self.regs[reg] |= bits
        self._intb()

    def _intb(self):
        self.ctx.gpio(0).set(not any(self.regs[0x03:0x06]))

    def on_address(self, addr, is_read):
        return True

    def on_write(self, data):
        if not data:
            return 0
        self.ptr = data[0]
        for b in data[1:]:
            if self.ptr > 5:
                self.regs[self.ptr] = b
            self.ptr += 1
        return len(data)

    def on_read(self, count):
        out = bytearray()
        for _ in range(count):
            out.append(self.regs[self.ptr & 0xFF])
            if 3 <= self.ptr <= 5:
                self.regs[self.ptr] = 0
            self.ptr += 1
        self._intb()
        return bytes(out)
