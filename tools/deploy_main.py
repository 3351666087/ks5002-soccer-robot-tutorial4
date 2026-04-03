from __future__ import annotations

from common import deploy_runtime, detect_port, load_saved_profile, parse_common_args


def main() -> None:
    parser = parse_common_args("自动烧录 KS5002 主程序到 ESP32。")
    args = parser.parse_args()

    port = detect_port(args.port)
    print("使用串口:", port)
    profile = load_saved_profile()
    deploy_runtime(port, boot_mode="main", profile=profile, firmware=args.firmware, logger=print)
    print("完成。现在板子会从 main.py 启动。")


if __name__ == "__main__":
    main()
