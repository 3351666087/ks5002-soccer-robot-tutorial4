from ht16k33 import HT16K33


class HT16K33Matrix(HT16K33):
    def __init__(self, i2c, address=0x70):
        super().__init__(i2c, address=address)
        self.angle = 0

    def set_angle(self, angle):
        self.angle = angle % 360
        return self

    def _icon_to_pixels(self, icon):
        pixels = [[0] * 8 for _ in range(8)]
        row = 0
        while row < 8:
            value = icon[row]
            column = 0
            while column < 8:
                pixels[row][column] = 1 if (value & (1 << (7 - column))) else 0
                column += 1
            row += 1
        return pixels

    def _rotate_pixels(self, pixels):
        angle = self.angle % 360
        if angle == 0:
            return pixels

        rotated = [[0] * 8 for _ in range(8)]
        y = 0
        while y < 8:
            x = 0
            while x < 8:
                value = pixels[y][x]
                if angle == 90:
                    new_x = y
                    new_y = 7 - x
                elif angle == 180:
                    new_x = 7 - x
                    new_y = 7 - y
                elif angle == 270:
                    new_x = 7 - y
                    new_y = x
                else:
                    new_x = x
                    new_y = y
                rotated[new_y][new_x] = value
                x += 1
            y += 1
        return rotated

    def set_icon(self, icon):
        self.clear()
        if isinstance(icon, (bytes, bytearray)) and len(icon) >= 8:
            pixels = self._rotate_pixels(self._icon_to_pixels(icon))
            row = 0
            while row < 8:
                value = 0
                column = 0
                while column < 8:
                    if pixels[row][column]:
                        value |= 1 << (7 - column)
                    column += 1
                self.buffer[row * 2] = value
                row += 1
        return self

    def set_pixel(self, x, y, value=1):
        if x < 0 or x > 7 or y < 0 or y > 7:
            return self
        index = y * 2
        mask = 1 << (7 - x)
        if value:
            self.buffer[index] |= mask
        else:
            self.buffer[index] &= ~mask
        return self
