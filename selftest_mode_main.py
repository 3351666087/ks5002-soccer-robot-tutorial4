import compat as hw
import config
from soccer_bot import SoccerRobot


def main():
    robot = SoccerRobot(config)
    pulse = 0
    direction = 1

    try:
        print("== KS5002 自检模式 ==")
        print("当前固件入口: selftest_mode_main.py")
        print("请将小车抬起后，再进行电机类测试。")
        print(robot.self_check())

        while True:
            robot.face.set("thinking")
            robot.set_led(pulse, pulse, 0)
            robot.face.tick()
            pulse += direction * 4
            if pulse >= 28:
                pulse = 28
                direction = -1
            elif pulse <= 4:
                pulse = 4
                direction = 1
            hw.sleep_ms(100)
    finally:
        robot.shutdown()


if __name__ == "__main__":
    main()
