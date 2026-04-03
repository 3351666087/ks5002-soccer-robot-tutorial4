from __future__ import annotations

from common import board_exec, deploy_runtime, detect_port, load_saved_profile, parse_common_args, soft_reset, write_report


TESTS = [
    {
        "name": "self_check",
        "title": "基础自检",
        "theory": "串口应返回显示屏状态、超声波距离、策略统计。",
        "lifted": False,
    },
    {
        "name": "display",
        "title": "点阵表情",
        "theory": "前脸 8x8 点阵应轮流显示多组表情动画。",
        "lifted": False,
    },
    {
        "name": "rgb",
        "title": "RGB 灯",
        "theory": "板载 RGB 应依次显示红、绿、蓝、白。",
        "lifted": False,
    },
    {
        "name": "head_servo",
        "title": "超声波舵机",
        "theory": "超声波云台应左转、回中、右转、回中。",
        "lifted": False,
    },
    {
        "name": "claw_servo",
        "title": "夹爪舵机",
        "theory": "夹爪应张大、闭合、回到常规打开位置。",
        "lifted": False,
    },
    {
        "name": "ultrasonic",
        "title": "超声波测距",
        "theory": "串口应输出 5 次距离采样值。",
        "lifted": False,
    },
    {
        "name": "left_motor",
        "title": "左轮空转",
        "theory": "只有左轮空转，右轮不动。",
        "lifted": True,
    },
    {
        "name": "right_motor",
        "title": "右轮空转",
        "theory": "只有右轮空转，左轮不动。",
        "lifted": True,
    },
    {
        "name": "drive_pair",
        "title": "双轮前后转",
        "theory": "双轮先正转再反转，小车必须悬空。",
        "lifted": True,
    },
    {
        "name": "ram_kick",
        "title": "撞球踢球动作",
        "theory": "夹爪先松球，随后小车短暂后退再高速前冲。请务必悬空。",
        "lifted": True,
    },
    {
        "name": "auto_brain",
        "title": "自动策略预热",
        "theory": "串口应输出自动模式统计，前脸表情会切换。",
        "lifted": True,
    },
]


def _confirm_lifted() -> None:
    print()
    print("安全提醒：接下来要测试电机/冲撞动作。")
    print("请先把小车抬起来，让轮子完全悬空，避免突然冲出去。")
    while True:
        value = input("确认后输入 LIFTED 继续: ").strip()
        if value == "LIFTED":
            return
        print("输入不匹配，测试未继续。")


def _ask_observation() -> tuple[str, bool]:
    observation = input("实际动作描述: ").strip()
    verdict = input("是否符合理论动作？[Y/n]: ").strip().lower()
    passed = verdict not in ("n", "no")
    return observation, passed


def main() -> None:
    parser = parse_common_args("自动烧录并执行 KS5002 自检/功能测试。")
    args = parser.parse_args()

    port = detect_port(args.port)
    print("使用串口:", port)
    profile = load_saved_profile()
    deploy_runtime(port, boot_mode="main", profile=profile, firmware=args.firmware, logger=print)

    report = {
        "port": port,
        "firmware": args.firmware or "",
        "tests": [],
    }

    lifted_confirmed = False

    for test in TESTS:
        if test["lifted"] and not lifted_confirmed:
            _confirm_lifted()
            lifted_confirmed = True

        print()
        print("== %s ==" % test["title"])
        print("理论动作:", test["theory"])
        output = board_exec(port, "import self_test; self_test.run_named(%r)" % test["name"])
        print("板端输出:")
        print(output or "<empty>")

        observation, passed = _ask_observation()
        report["tests"].append(
            {
                "name": test["name"],
                "title": test["title"],
                "theory": test["theory"],
                "board_output": output,
                "observation": observation,
                "passed": passed,
            }
        )

    print()
    print("测试结束，重新启动主程序...")
    soft_reset(port)
    report_path = write_report(report)
    print("测试报告已保存到:", report_path)


if __name__ == "__main__":
    main()
