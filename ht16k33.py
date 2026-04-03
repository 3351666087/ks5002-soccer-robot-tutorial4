class HT16K33:
    def __init__(self, i2c, address=0x70):
        self.i2c = i2c
        self.address = address
        self.buffer = bytearray(16)
        self.power_on()
        self.blink_rate(0)
        self.set_brightness(8)
        self.clear()

    def _write_cmd(self, value):
        try:
            self.i2c.writeto(self.address, bytes([value]))
        except Exception:
            pass

    def _write_buffer(self):
        data = bytearray(17)
        data[0] = 0x00
        data[1:] = self.buffer
        try:
            self.i2c.writeto(self.address, data)
        except Exception:
            pass

    def power_on(self):
        self._write_cmd(0x21)

    def power_off(self):
        self._write_cmd(0x20)

    def blink_rate(self, rate=0):
        rate = 0 if rate < 0 else 3 if rate > 3 else rate
        self._write_cmd(0x80 | 0x01 | (rate << 1))
        return self

    def set_brightness(self, brightness=8):
        brightness = 0 if brightness < 0 else 15 if brightness > 15 else brightness
        self._write_cmd(0xE0 | brightness)
        return self

    def clear(self):
        index = 0
        while index < len(self.buffer):
            self.buffer[index] = 0
            index += 1
        return self

    def draw(self):
        self._write_buffer()
        return self
