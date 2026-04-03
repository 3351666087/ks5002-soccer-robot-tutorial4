import json as _json
import random as _random
import socket as _socket
import sys
import time as _time

IS_MICROPYTHON = getattr(sys.implementation, "name", "") == "micropython"


try:
    import ujson as json_module
except ImportError:
    json_module = _json


try:
    import socket as socket_module
except ImportError:
    try:
        import usocket as socket_module
    except ImportError:
        socket_module = _socket


try:
    import network as network_module
except ImportError:
    network_module = None


def sleep_ms(value):
    if hasattr(_time, "sleep_ms"):
        _time.sleep_ms(value)
    else:
        _time.sleep(value / 1000.0)


def sleep_us(value):
    if hasattr(_time, "sleep_us"):
        _time.sleep_us(value)
    else:
        _time.sleep(value / 1000000.0)


def ticks_ms():
    if hasattr(_time, "ticks_ms"):
        return _time.ticks_ms()
    return int(_time.time() * 1000)


def ticks_us():
    if hasattr(_time, "ticks_us"):
        return _time.ticks_us()
    return int(_time.time() * 1000000)


def ticks_diff(current, previous):
    if hasattr(_time, "ticks_diff"):
        return _time.ticks_diff(current, previous)
    return current - previous


def ticks_diff_us(current, previous):
    if hasattr(_time, "ticks_diff"):
        return _time.ticks_diff(current, previous)
    return current - previous


def ticks_add(base, delta):
    if hasattr(_time, "ticks_add"):
        return _time.ticks_add(base, delta)
    return base + delta


def randbelow(limit):
    if limit <= 0:
        return 0
    try:
        import urandom as _urandom

        return _urandom.getrandbits(16) % limit
    except ImportError:
        return _random.randrange(0, limit)


def randbool():
    return bool(randbelow(2))


def randunit():
    return randbelow(10000) / 10000.0


try:
    from machine import I2C, Pin, PWM
except ImportError:
    class Pin:
        IN = 0
        OUT = 1

        def __init__(self, pin, mode=None, value=0):
            self.pin = pin
            self.mode = mode
            self._value = value

        def value(self, new_value=None):
            if new_value is None:
                return self._value
            self._value = new_value
            return self._value


    class PWM:
        def __init__(self, pin, freq=50, duty=0):
            self.pin = pin
            self._freq = freq
            self._duty = duty
            self._duty_u16 = duty << 6
            self._duty_ns = 0

        def duty(self, value=None):
            if value is None:
                return self._duty
            self._duty = value
            self._duty_u16 = int(value) << 6
            return self._duty

        def duty_u16(self, value=None):
            if value is None:
                return self._duty_u16
            self._duty_u16 = value
            self._duty = int(value) >> 6
            return self._duty_u16

        def duty_ns(self, value=None):
            if value is None:
                return self._duty_ns
            self._duty_ns = value
            return self._duty_ns

        def freq(self, value=None):
            if value is None:
                return self._freq
            self._freq = value
            return self._freq


    class I2C:
        def __init__(self, scl=None, sda=None, freq=400000):
            self.scl = scl
            self.sda = sda
            self.freq = freq
            self.memory = {}

        def writeto(self, address, data):
            self.memory[address] = bytes(data)

        def writeto_mem(self, address, register, data):
            self.memory[(address, register)] = bytes(data)


try:
    import neopixel as neopixel_module
except ImportError:
    class _NeoPixel:
        def __init__(self, pin, count):
            self.pin = pin
            self.count = count
            self.values = [(0, 0, 0)] * count

        def __setitem__(self, index, value):
            self.values[index] = value

        def __getitem__(self, index):
            return self.values[index]

        def write(self):
            return None

    class _NeoPixelModule:
        NeoPixel = _NeoPixel

    neopixel_module = _NeoPixelModule()


if network_module is None:
    class _WLAN:
        def __init__(self, mode):
            self.mode = mode
            self._active = False
            self._connected = False
            self._ip = "127.0.0.1"

        def active(self, value=None):
            if value is None:
                return self._active
            self._active = value
            return self._active

        def connect(self, ssid, password):
            del ssid, password
            self._connected = True

        def isconnected(self):
            return self._connected

        def ifconfig(self):
            return (self._ip, "255.255.255.0", self._ip, self._ip)

        def config(self, **kwargs):
            if "essid" in kwargs:
                self._ip = "192.168.4.1"

    class _NetworkModule:
        STA_IF = 0
        AP_IF = 1

        @staticmethod
        def WLAN(mode):
            return _WLAN(mode)

    network_module = _NetworkModule()
