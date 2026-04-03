import compat as hw
from compat import json_module

import config
from soccer_bot import SoccerRobot


def _new_robot():
    return SoccerRobot(config)


def _emit(name, payload):
    print("SELF_TEST:%s" % name)
    try:
        print(json_module.dumps(payload))
    except Exception:
        print(str(payload))


def run_named(name):
    if name == "self_check":
        return self_check()
    if name == "display":
        return test_display()
    if name == "rgb":
        return test_rgb()
    if name == "head_servo":
        return test_head_servo()
    if name == "claw_servo":
        return test_claw_servo()
    if name == "ultrasonic":
        return test_ultrasonic()
    if name == "left_motor":
        return test_left_motor()
    if name == "right_motor":
        return test_right_motor()
    if name == "drive_pair":
        return test_drive_pair()
    if name == "ram_kick":
        return test_ram_kick()
    if name == "auto_brain":
        return test_auto_brain()
    raise ValueError("unknown test: %s" % name)


def self_check():
    robot = _new_robot()
    try:
        payload = robot.self_check()
        _emit("self_check", payload)
        return payload
    finally:
        robot.shutdown()


def test_display():
    robot = _new_robot()
    try:
        robot.face.demo()
        payload = {"display_available": robot.face.available(), "status": "ok"}
        _emit("display", payload)
        return payload
    finally:
        robot.shutdown()


def test_rgb():
    robot = _new_robot()
    try:
        robot.set_led(20, 0, 0)
        hw.sleep_ms(180)
        robot.set_led(0, 20, 0)
        hw.sleep_ms(180)
        robot.set_led(0, 0, 20)
        hw.sleep_ms(180)
        robot.set_led(20, 20, 20)
        hw.sleep_ms(180)
        payload = {"status": "ok"}
        _emit("rgb", payload)
        return payload
    finally:
        robot.shutdown()


def test_head_servo():
    robot = _new_robot()
    try:
        robot.head_left()
        hw.sleep_ms(300)
        robot.center_head()
        hw.sleep_ms(300)
        robot.head_right()
        hw.sleep_ms(300)
        robot.center_head()
        payload = {"angles": [config.HEAD_LEFT_ANGLE, config.HEAD_CENTER_ANGLE, config.HEAD_RIGHT_ANGLE]}
        _emit("head_servo", payload)
        return payload
    finally:
        robot.shutdown()


def test_claw_servo():
    robot = _new_robot()
    try:
        robot.open_claw_wide()
        hw.sleep_ms(320)
        robot.close_claw()
        hw.sleep_ms(320)
        robot.open_claw()
        payload = {
            "angles": [
                config.CLAW_WIDE_OPEN_ANGLE,
                config.CLAW_CLOSED_ANGLE,
                config.CLAW_OPEN_ANGLE,
            ]
        }
        _emit("claw_servo", payload)
        return payload
    finally:
        robot.shutdown()


def test_ultrasonic():
    robot = _new_robot()
    try:
        values = []
        count = 0
        while count < 5:
            values.append(robot.measure_distance_filtered(2))
            count += 1
        payload = {"distances_cm": values}
        _emit("ultrasonic", payload)
        return payload
    finally:
        robot.shutdown()


def test_left_motor():
    robot = _new_robot()
    try:
        robot.drive(560, 0)
        hw.sleep_ms(260)
        robot.stop()
        payload = {"expected": "left wheel spin only"}
        _emit("left_motor", payload)
        return payload
    finally:
        robot.shutdown()


def test_right_motor():
    robot = _new_robot()
    try:
        robot.drive(0, 560)
        hw.sleep_ms(260)
        robot.stop()
        payload = {"expected": "right wheel spin only"}
        _emit("right_motor", payload)
        return payload
    finally:
        robot.shutdown()


def test_drive_pair():
    robot = _new_robot()
    try:
        robot.forward(620)
        hw.sleep_ms(240)
        robot.stop()
        hw.sleep_ms(100)
        robot.backward(520)
        hw.sleep_ms(220)
        robot.stop()
        payload = {"expected": "both wheels forward then backward"}
        _emit("drive_pair", payload)
        return payload
    finally:
        robot.shutdown()


def test_ram_kick():
    robot = _new_robot()
    try:
        robot.close_claw()
        hw.sleep_ms(120)
        payload = robot.perform_ram_kick()
        _emit("ram_kick", payload)
        return payload
    finally:
        robot.shutdown()


def test_auto_brain():
    robot = _new_robot()
    try:
        robot.start_auto()
        started = hw.ticks_ms()
        while hw.ticks_diff(hw.ticks_ms(), started) < 2000:
            robot.update()
            hw.sleep_ms(20)
        payload = robot.summary()
        _emit("auto_brain", payload)
        return payload
    finally:
        robot.shutdown()
