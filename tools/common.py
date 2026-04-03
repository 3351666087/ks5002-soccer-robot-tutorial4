from __future__ import annotations

import argparse
import concurrent.futures
import importlib.util
import ipaddress
import json
import os
import re
import signal
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path
from pprint import pformat

from serial.tools import list_ports


def _resource_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parent.parent


def _user_data_root() -> Path:
    if getattr(sys, "frozen", False):
        path = Path.home() / "Library" / "Application Support" / "KS5002Studio"
        path.mkdir(parents=True, exist_ok=True)
        return path
    return Path(__file__).resolve().parent.parent


ROOT = _resource_root()
USER_DATA_ROOT = _user_data_root()
TOOLS_DIR = Path(__file__).resolve().parent
REPORTS_DIR = USER_DATA_ROOT / "test_reports"
PROFILE_PATH = USER_DATA_ROOT / ".studio_profile.json"
PRESETS_DIR = USER_DATA_ROOT / "presets"
LAST_GENERATED_CONFIG_PATH = USER_DATA_ROOT / ".last_generated_config.py"
LAST_FLASH_PROFILE_PATH = USER_DATA_ROOT / ".last_flash_profile.json"
DESKTOP_ONLY_KEYS = {"CONTROL_BASE_URL", "LAST_FIRMWARE_PATH", "FLASH_FIRMWARE"}
FIRMWARE_SCAN_DIRS = (
    USER_DATA_ROOT / "firmware",
    ROOT / "firmware",
    USER_DATA_ROOT,
    ROOT,
    Path.home() / "Downloads",
    Path.home() / "Desktop",
)
MICROPYTHON_ESP32_GENERIC_PAGE = "https://micropython.org/download/ESP32_GENERIC/"
NO_PROXY_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def preferred_python_executable() -> str:
    if getattr(sys, "frozen", False):
        return sys.executable
    venv_python = ROOT / ".venv" / "bin" / "python"
    if venv_python.exists():
        return str(venv_python)
    return sys.executable


def _should_bypass_proxy(url: str) -> bool:
    try:
        parsed = urllib.parse.urlparse(str(url or ""))
    except Exception:
        return False
    host = str(parsed.hostname or "").strip().lower()
    if not host:
        return False
    if host in ("127.0.0.1", "localhost", "::1"):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return host.endswith(".local")
    return bool(address.is_private or address.is_loopback or address.is_link_local)


def open_url(url: str, timeout: float = 1.0):
    if _should_bypass_proxy(url):
        return NO_PROXY_OPENER.open(url, timeout=timeout)
    return urllib.request.urlopen(url, timeout=timeout)

STATIC_FILES = [
    "car_runtime.py",
    "compat.py",
    "ht16k33.py",
    "ht16k33matrix.py",
    "legacy_io.py",
    "mini_mqtt.py",
    "mqtt_command_link.py",
    "mqtt_link.py",
    "relay_command_link.py",
    "relay_link.py",
    "remote_mqtt_safe_runtime.py",
    "remote_mqtt_runtime.py",
    "smart_drive.py",
    "soccer_bot.py",
    "tcp_command_link.py",
    "self_test.py",
]

BOOT_SOURCES = {
    "main": ROOT / "main.py",
    "selftest": ROOT / "selftest_mode_main.py",
}

CONFIG_RENDER_ORDER = [
    "PROJECT_NAME",
    "WIFI_MODE",
    "STA_SSID",
    "STA_PASSWORD",
    "AP_SSID",
    "AP_PASSWORD",
    "HOST",
    "PORT",
    "RELAY_BASE_URL",
    "RELAY_CONNECT_HOST",
    "RELAY_PULL_MS",
    "RELAY_REPORT_MS",
    "RELAY_PING_MS",
    "LAN_BRIDGE_HOST",
    "LAN_BRIDGE_PORT",
    "LAN_POLL_MS",
    "LAN_STATUS_MS",
    "MQTT_BROKER_HOST",
    "MQTT_CONNECT_HOST",
    "MQTT_BROKER_PORT",
    "MQTT_NAMESPACE",
    "MQTT_REPORT_MS",
    "MQTT_KEEPALIVE_S",
    "LEFT_DIR_PIN",
    "LEFT_PWM_PIN",
    "RIGHT_DIR_PIN",
    "RIGHT_PWM_PIN",
    "HEAD_SERVO_PIN",
    "CLAW_SERVO_PIN",
    "SONAR_TRIG_PIN",
    "SONAR_ECHO_PIN",
    "RGB_PIN",
    "DISPLAY_SDA_PIN",
    "DISPLAY_SCL_PIN",
    "DISPLAY_I2C_ADDR",
    "DISPLAY_BRIGHTNESS",
    "DISPLAY_ROTATION",
    "MOTOR_FREQ",
    "SERVO_FREQ",
    "MAX_PWM",
    "MANUAL_SPEED",
    "TURN_SPEED",
    "SEARCH_SPEED",
    "APPROACH_SPEED",
    "REVERSE_SPEED",
    "RAM_PREP_SPEED",
    "HEAD_LEFT_ANGLE",
    "HEAD_CENTER_ANGLE",
    "HEAD_RIGHT_ANGLE",
    "CLAW_CLOSED_ANGLE",
    "CLAW_HOLD_ANGLE",
    "CLAW_OPEN_ANGLE",
    "CLAW_WIDE_OPEN_ANGLE",
    "SCAN_SETTLE_MS",
    "MEASURE_GAP_MS",
    "MANUAL_COMMAND_TIMEOUT_MS",
    "APPROACH_TIMEOUT_MS",
    "SEARCH_SCAN_INTERVAL_MS",
    "EMOTION_FRAME_MS",
    "OBSTACLE_STOP_CM",
    "OBSTACLE_ESCAPE_CM",
    "BALL_DETECT_MIN_CM",
    "BALL_DETECT_MAX_CM",
    "CAPTURE_DISTANCE_CM",
    "RAM_SAFE_FRONT_CM",
    "FREE_SPACE_GOOD_CM",
    "CAPTURE_PROFILES",
    "RAM_KICK_PROFILES",
    "SCAN_PROFILES",
    "POLICY_FILE",
    "RL_ALPHA",
    "RL_EPSILON",
    "RL_SAVE_EVERY",
    "BUTTON_FORWARD",
    "BUTTON_BACKWARD",
    "BUTTON_LEFT",
    "BUTTON_RIGHT",
    "BUTTON_STOP",
    "BUTTON_OK_ALIASES",
    "BUTTON_GRAB_ALIASES",
    "BUTTON_AUTO_MODE_ALIASES",
    "BUTTON_MANUAL_MODE_ALIASES",
    "BUTTON_STOP_AUTO_ALIASES",
    "BUTTON_RAM_KICK_ALIASES",
    "BUTTON_PAN_LEFT_ALIASES",
    "BUTTON_PAN_CENTER_ALIASES",
    "BUTTON_PAN_RIGHT_ALIASES",
    "BUTTON_RELEASE_ALIASES",
    "BUTTON_POLICY_RESET_ALIASES",
    "BUTTON_FACE_DEMO_ALIASES",
    "BUTTON_FACE_NEXT_ALIASES",
    "BUTTON_FACE_CLEAR_ALIASES",
    "BUTTON_FACE_PREV_ALIASES",
]

PROFILE_GROUPS = [
    {
        "title": "连接与网络",
        "fields": [
            {"key": "STA_SSID", "label": "当前 Wi-Fi SSID", "type": "text"},
            {"key": "STA_PASSWORD", "label": "当前 Wi-Fi 密码", "type": "password"},
        ],
    },
    {
        "title": "手动驾驶",
        "fields": [
            {"key": "MANUAL_SPEED", "label": "手动前进速度", "type": "int", "min": 0, "max": 1023},
            {"key": "TURN_SPEED", "label": "原地旋转速度", "type": "int", "min": 0, "max": 1023},
            {"key": "REVERSE_SPEED", "label": "后退速度", "type": "int", "min": 0, "max": 1023},
            {"key": "MANUAL_COMMAND_TIMEOUT_MS", "label": "手动指令保持 ms", "type": "int", "min": 100, "max": 5000},
        ],
    },
    {
        "title": "云台与夹爪",
        "fields": [
            {"key": "HEAD_LEFT_ANGLE", "label": "云台左角度", "type": "int", "min": 0, "max": 180},
            {"key": "HEAD_CENTER_ANGLE", "label": "云台中角度", "type": "int", "min": 0, "max": 180},
            {"key": "HEAD_RIGHT_ANGLE", "label": "云台右角度", "type": "int", "min": 0, "max": 180},
            {"key": "CLAW_CLOSED_ANGLE", "label": "夹爪闭合角度", "type": "int", "min": 0, "max": 180},
            {"key": "CLAW_HOLD_ANGLE", "label": "夹爪保持角度", "type": "int", "min": 0, "max": 180},
            {"key": "CLAW_OPEN_ANGLE", "label": "夹爪松球角度", "type": "int", "min": 0, "max": 180},
            {"key": "CLAW_WIDE_OPEN_ANGLE", "label": "夹爪大开角度", "type": "int", "min": 0, "max": 180},
        ],
    },
    {
        "title": "自动模式",
        "fields": [
            {"key": "SEARCH_SPEED", "label": "搜索速度", "type": "int", "min": 0, "max": 1023},
            {"key": "APPROACH_SPEED", "label": "靠近速度", "type": "int", "min": 0, "max": 1023},
            {"key": "RAM_PREP_SPEED", "label": "撞球预备速度", "type": "int", "min": 0, "max": 1023},
            {"key": "APPROACH_TIMEOUT_MS", "label": "追踪超时 ms", "type": "int", "min": 500, "max": 12000},
            {"key": "SEARCH_SCAN_INTERVAL_MS", "label": "扫描间隔 ms", "type": "int", "min": 100, "max": 5000},
            {"key": "OBSTACLE_STOP_CM", "label": "避障阈值 cm", "type": "int", "min": 2, "max": 100},
            {"key": "OBSTACLE_ESCAPE_CM", "label": "紧急避障 cm", "type": "int", "min": 2, "max": 100},
            {"key": "CAPTURE_DISTANCE_CM", "label": "抓球距离 cm", "type": "int", "min": 2, "max": 50},
            {"key": "FREE_SPACE_GOOD_CM", "label": "空间充足阈值 cm", "type": "int", "min": 5, "max": 100},
        ],
    },
    {
        "title": "云台扫描策略",
        "fields": [
            {"key": "SCAN_SETTLE_MS", "label": "扫描驻留 ms", "type": "int", "min": 50, "max": 1000},
            {"key": "MEASURE_GAP_MS", "label": "测距间隔 ms", "type": "int", "min": 10, "max": 500},
        ],
    },
    {
        "title": "表情与学习",
        "fields": [
            {"key": "DISPLAY_BRIGHTNESS", "label": "点阵亮度", "type": "int", "min": 0, "max": 15},
            {"key": "DISPLAY_ROTATION", "label": "点阵旋转角度", "type": "int", "min": 0, "max": 270, "step": 90},
            {"key": "EMOTION_FRAME_MS", "label": "表情帧间隔 ms", "type": "int", "min": 30, "max": 1000},
            {"key": "RL_ALPHA", "label": "学习率", "type": "float", "min": 0.01, "max": 1.0, "step": 0.01},
            {"key": "RL_EPSILON", "label": "探索率", "type": "float", "min": 0.0, "max": 1.0, "step": 0.01},
            {"key": "RL_SAVE_EVERY", "label": "策略保存步数", "type": "int", "min": 1, "max": 100},
        ],
    },
]


def _load_config_module():
    spec = importlib.util.spec_from_file_location("project_config", ROOT / "config.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("无法加载项目配置模块")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _score_port(port) -> tuple[int, str]:
    device = port.device or ""
    text = " ".join(
        [
            device,
            str(port.description or ""),
            str(port.manufacturer or ""),
            str(port.hwid or ""),
        ]
    ).lower()

    score = 0
    if device.startswith("/dev/cu."):
        score += 3
    if "usb" in text:
        score += 3
    if "uart" in text or "serial" in text:
        score += 2
    if "cp210" in text or "wch" in text or "ch340" in text or "ftdi" in text or "esp32" in text:
        score += 4
    if "bluetooth" in text:
        score -= 5
    return score, device


def list_serial_ports_info() -> list[dict]:
    infos = []
    for port in list_ports.comports():
        score, device = _score_port(port)
        infos.append(
            {
                "device": device,
                "description": str(port.description or ""),
                "manufacturer": str(port.manufacturer or ""),
                "hwid": str(port.hwid or ""),
                "score": score,
                "is_likely_esp32": score > 0,
            }
        )
    infos.sort(key=lambda item: (item["score"], item["device"]), reverse=True)
    return infos


def detect_port(explicit_port: str | None = None) -> str:
    if explicit_port:
        return explicit_port

    infos = list_serial_ports_info()
    if not infos or infos[0]["score"] <= 0:
        raise SystemExit("没有检测到明显可用的 ESP32 串口，请用 --port 手动指定。")
    return infos[0]["device"]


def _tool_path(name: str) -> str:
    by_python = Path(sys.executable).with_name(name)
    if by_python.exists():
        return str(by_python)
    found = shutil.which(name)
    if found:
        return found
    raise SystemExit("缺少工具 %s，请先激活 .venv。" % name)


def _run_best_effort(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def mpremote_cmd() -> list[str]:
    return [_tool_path("mpremote")]


def esptool_cmd() -> list[str]:
    return [_tool_path("esptool.py")]


class CommandError(RuntimeError):
    pass


def run_command(
    command: list[str],
    capture: bool = False,
    logger=None,
) -> subprocess.CompletedProcess[str]:
    if logger is not None:
        logger("$ " + " ".join(command))
    result = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if logger is not None and result.stdout:
        logger(result.stdout.rstrip())
    if logger is not None and result.stderr:
        logger(result.stderr.rstrip())
    if result.returncode != 0:
        details = "命令失败:\n%s" % " ".join(command)
        if result.stdout:
            details += "\n\nstdout:\n%s" % result.stdout
        if result.stderr:
            details += "\n\nstderr:\n%s" % result.stderr
        if capture:
            raise CommandError(details)
        raise CommandError(details)
    if capture:
        return result
    result.stdout = result.stdout or ""
    return result


def board_exec(port: str, code: str, logger=None) -> str:
    command = mpremote_cmd() + ["connect", port, "exec", code]
    result = run_command(command, capture=True, logger=logger)
    return result.stdout.strip()


def normalize_control_base_url(base_url: str) -> str:
    normalized = str(base_url or "").strip() or "http://192.168.4.1"
    if not normalized.startswith("http://") and not normalized.startswith("https://"):
        normalized = "http://" + normalized
    return normalized.rstrip("/")


def probe_robot_status(base_url: str, timeout_s: float = 1.0) -> dict | None:
    normalized = normalize_control_base_url(base_url)
    request_url = normalized + "/status"
    try:
        with open_url(request_url, timeout=timeout_s) as response:
            payload_text = response.read().decode("utf-8", errors="ignore").strip()
            status_code = int(getattr(response, "status", 200) or 200)
    except Exception:
        return None

    try:
        payload = json.loads(payload_text)
    except Exception:
        return None

    if not isinstance(payload, dict):
        return None
    if not payload.get("ok"):
        return None
    if payload.get("service") != "ks5002-http":
        return None

    return {
        "base_url": normalized,
        "status_url": request_url,
        "status_code": status_code,
        "payload": payload,
    }


def _normalize_candidate_host(raw_value: str) -> str:
    host = str(raw_value or "").strip()
    if not host:
        return ""
    if "://" in host:
        host = urllib.parse.urlparse(host).netloc or host.split("://", 1)[-1]
    host = host.split("/", 1)[0].strip()
    if ":" in host:
        host = host.split(":", 1)[0].strip()
    return host


def _candidate_hosts_for_subnet(local_ip: str, prefer_hosts: list[str] | None = None) -> list[str]:
    hosts = []
    seen = set()
    local_ip = str(local_ip or "").strip()

    for raw_value in prefer_hosts or []:
        host = _normalize_candidate_host(raw_value)
        if not host or host == local_ip or host in seen:
            continue
        seen.add(host)
        hosts.append(host)

    try:
        network = ipaddress.ip_network("%s/24" % local_ip, strict=False)
    except ValueError:
        return hosts

    for address in network.hosts():
        host = str(address)
        if host == local_ip or host in seen:
            continue
        seen.add(host)
        hosts.append(host)
    return hosts


def discover_robot_on_subnet(
    local_ip: str,
    prefer_hosts: list[str] | None = None,
    port: int = 80,
    timeout_s: float = 0.35,
    max_workers: int = 48,
) -> dict | None:
    candidates = _candidate_hosts_for_subnet(local_ip, prefer_hosts=prefer_hosts)
    if not candidates:
        return None

    def _probe(host: str):
        base_url = "http://%s" % host
        if port and int(port) != 80:
            base_url = "%s:%d" % (base_url, int(port))
        return probe_robot_status(base_url, timeout_s=timeout_s)

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(_probe, host) for host in candidates]
        try:
            for future in concurrent.futures.as_completed(futures):
                result = future.result()
                if result is not None:
                    return result
        finally:
            for future in futures:
                future.cancel()

    return None


def board_network_snapshot(port: str, logger=None, retries: int = 4, retry_delay_s: float = 0.9) -> dict:
    code = """
import json
payload = {
    "ok": False,
    "network_mode": "offline",
    "ip_address": "0.0.0.0",
    "station_connected": False,
    "station_ip": "",
    "ap_ip": "",
    "port": 80,
}
try:
    import config
    payload["port"] = getattr(config, "PORT", 80)
    try:
        import network
        sta = network.WLAN(network.STA_IF)
        ap = network.WLAN(network.AP_IF)
        station_connected = False
        station_ip = ""
        ap_ip = ""
        try:
            station_connected = sta.isconnected()
        except Exception:
            station_connected = False
        if station_connected:
            try:
                station_ip = sta.ifconfig()[0]
            except Exception:
                station_ip = ""
        try:
            ap_ip = ap.ifconfig()[0]
        except Exception:
            ap_ip = ""
        payload["station_connected"] = bool(station_connected and station_ip and station_ip != "0.0.0.0")
        payload["station_ip"] = station_ip or ""
        payload["ap_ip"] = ap_ip or "192.168.4.1"
        if payload["station_connected"]:
            payload["network_mode"] = "station"
            payload["ip_address"] = payload["station_ip"]
        elif ap_ip:
            payload["network_mode"] = "ap_fallback"
            payload["ip_address"] = payload["ap_ip"]
        payload["ok"] = True
    except Exception as exc:
        payload["error"] = str(exc)
except Exception as exc:
    payload["error"] = str(exc)
print("BOARD_NET:" + json.dumps(payload))
""".strip()

    last_error = None
    for attempt in range(1, max(1, retries) + 1):
        try:
            output = board_exec(port, code, logger=logger)
            for line in reversed(output.splitlines()):
                if line.startswith("BOARD_NET:"):
                    return json.loads(line[len("BOARD_NET:") :].strip())
            raise RuntimeError("板端网络快照输出缺少 BOARD_NET 标记。")
        except Exception as exc:
            last_error = exc
            if attempt >= max(1, retries):
                break
            time.sleep(max(0.1, retry_delay_s))

    raise RuntimeError("读取板端网络快照失败：%s" % last_error)


def _uppercase_config_values(module) -> dict:
    data = {}
    for name, value in vars(module).items():
        if name.isupper():
            data[name] = value
    return data


def load_default_profile() -> dict:
    module = _load_config_module()
    defaults = _uppercase_config_values(module)
    mqtt_host = str(defaults.get("MQTT_BROKER_HOST") or "").strip()
    relay_url = str(defaults.get("RELAY_BASE_URL") or "").strip()
    lan_host = str(defaults.get("LAN_BRIDGE_HOST") or "").strip()
    if mqtt_host or relay_url or lan_host:
        defaults["CONTROL_BASE_URL"] = "http://127.0.0.1:8765"
    else:
        defaults["CONTROL_BASE_URL"] = relay_url or "http://192.168.4.1"
    defaults["WIFI_MODE"] = "apsta"
    profile = {}
    for group in PROFILE_GROUPS:
        for field in group["fields"]:
            key = field["key"]
            profile[key] = defaults[key]
    for key in (
        "WIFI_MODE",
        "STA_SSID",
        "AP_SSID",
        "AP_PASSWORD",
        "HOST",
        "PORT",
        "RELAY_BASE_URL",
        "RELAY_CONNECT_HOST",
        "LAN_BRIDGE_HOST",
        "LAN_BRIDGE_PORT",
        "LAN_POLL_MS",
        "LAN_STATUS_MS",
        "MQTT_BROKER_HOST",
        "MQTT_CONNECT_HOST",
        "MQTT_BROKER_PORT",
        "MQTT_NAMESPACE",
        "MQTT_REPORT_MS",
        "MQTT_KEEPALIVE_S",
    ):
        profile[key] = defaults[key]
    profile["CONTROL_BASE_URL"] = defaults["CONTROL_BASE_URL"]
    profile["LAST_FIRMWARE_PATH"] = ""
    profile["FLASH_FIRMWARE"] = False
    return profile


def load_saved_profile() -> dict:
    profile = load_default_profile()
    if PROFILE_PATH.exists():
        try:
            saved = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
        except Exception:
            saved = {}
        if isinstance(saved, dict):
            profile.update(saved)
    return profile


def save_profile(profile: dict) -> None:
    PROFILE_PATH.write_text(json.dumps(profile, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def ensure_local_bridge(logger=None, host: str = "0.0.0.0", port: int = 8765) -> bool:
    probe_host = "127.0.0.1"
    health_url = "http://%s:%d/health" % (probe_host, port)
    status_url = "http://%s:%d/status" % (probe_host, port)

    profile = load_saved_profile()
    mqtt_host = str(profile.get("MQTT_BROKER_HOST") or "").strip()
    mqtt_namespace = str(profile.get("MQTT_NAMESPACE") or "").strip()
    relay_url = str(profile.get("RELAY_BASE_URL") or "").strip()
    lan_host = str(profile.get("LAN_BRIDGE_HOST") or "").strip()
    expect_transport = "mqtt" if mqtt_host and mqtt_namespace else ("tcp" if lan_host else ("relay" if relay_url else ""))

    def _healthy():
        try:
            with open_url(health_url, timeout=0.35) as response:
                payload = json.loads(response.read().decode("utf-8", errors="ignore"))
            return bool(isinstance(payload, dict) and payload.get("ok"))
        except Exception:
            return False

    def _bridge_matches_expected():
        if not expect_transport:
            return True
        try:
            with open_url(status_url, timeout=0.45) as response:
                payload = json.loads(response.read().decode("utf-8", errors="ignore"))
        except Exception:
            return False
        if not isinstance(payload, dict):
            return False
        transport = str(payload.get("transport") or "").strip()
        if expect_transport == "relay":
            return transport in ("idle", "relay")
        if expect_transport == "tcp":
            return transport in ("idle", "tcp")
        return transport == expect_transport

    def _terminate_listener():
        if shutil.which("lsof") is None:
            return
        result = _run_best_effort(["lsof", "-tiTCP:%d" % int(port), "-sTCP:LISTEN"])
        pids = []
        for line in (result.stdout or "").splitlines():
            line = line.strip()
            if not line.isdigit():
                continue
            pids.append(int(line))
        for pid in pids:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                continue
        if pids:
            time.sleep(0.6)

    if _healthy() and _bridge_matches_expected():
        return True
    if _healthy():
        if logger is not None:
            logger("本地热点桥当前模式与烧录配置不一致，准备重启桥接进程。")
        _terminate_listener()

    command = [preferred_python_executable(), str(TOOLS_DIR / "hotspot_bridge.py"), "--host", host, "--port", str(port)]
    if lan_host:
        command.extend(
            [
                "--tcp-port",
                str(int(profile.get("LAN_BRIDGE_PORT", 8766) or 8766)),
            ]
        )
    if mqtt_host and mqtt_namespace:
        command.extend(
            [
                "--mqtt-host",
                mqtt_host,
                "--mqtt-port",
                str(int(profile.get("MQTT_BROKER_PORT", 1883) or 1883)),
                "--mqtt-namespace",
                mqtt_namespace,
                "--mqtt-keepalive",
                str(int(profile.get("MQTT_KEEPALIVE_S", 20) or 20)),
            ]
        )
        mqtt_connect_host = str(profile.get("MQTT_CONNECT_HOST") or "").strip()
        if mqtt_connect_host:
            command.extend(["--mqtt-connect-host", mqtt_connect_host])
    else:
        command.extend(
            [
                "--no-tunnel",
                "--mqtt-host",
                "",
                "--mqtt-namespace",
                "",
                "--mqtt-connect-host",
                "",
            ]
        )
    if logger is not None:
        logger("启动本地热点桥接: %s" % " ".join(command))
    subprocess.Popen(
        command,
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )

    deadline = time.time() + 4.0
    while time.time() < deadline:
        if _healthy():
            return True
        time.sleep(0.2)
    return False


def current_hotspot_relay_base_url(port: int = 8765) -> str:
    wifi = detect_wifi_environment(include_password=False)
    local_ip = str(wifi.get("ip") or "").strip()
    if not local_ip:
        raise RuntimeError("当前电脑没有拿到热点 IP，无法生成本地 relay 地址。")
    return "http://%s:%d" % (local_ip, int(port))


def list_presets() -> list[str]:
    PRESETS_DIR.mkdir(parents=True, exist_ok=True)
    names = []
    for file_path in PRESETS_DIR.glob("*.json"):
        names.append(file_path.stem)
    return sorted(names)


def save_named_preset(name: str, profile: dict) -> Path:
    PRESETS_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = "".join(ch for ch in name if ch.isalnum() or ch in ("-", "_", " ")).strip()
    if not safe_name:
        raise SystemExit("预设名称不能为空。")
    preset_path = PRESETS_DIR / ("%s.json" % safe_name)
    preset_path.write_text(json.dumps(profile, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return preset_path


def load_named_preset(name: str) -> dict:
    preset_path = PRESETS_DIR / ("%s.json" % name)
    if not preset_path.exists():
        raise SystemExit("找不到预设：%s" % name)
    payload = json.loads(preset_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit("预设文件格式无效：%s" % name)
    return payload


def delete_named_preset(name: str) -> None:
    preset_path = PRESETS_DIR / ("%s.json" % name)
    if preset_path.exists():
        preset_path.unlink()


def _iter_bin_files(base_dir: Path, max_depth: int = 2):
    if not base_dir.exists():
        return

    stack = [(base_dir, 0)]
    while stack:
        current, depth = stack.pop()
        try:
            entries = list(current.iterdir())
        except OSError:
            continue

        for entry in entries:
            if entry.name.startswith(".") and entry.name not in (".", ".."):
                continue
            if entry.is_dir():
                if depth < max_depth and entry.name not in {"__pycache__", ".git", ".venv"}:
                    stack.append((entry, depth + 1))
                continue
            if entry.is_file() and entry.suffix.lower() == ".bin":
                yield entry


def _score_firmware_candidate(path: Path) -> tuple[int, float]:
    lower_name = path.name.lower()
    lower_parent = str(path.parent).lower()
    score = 0

    if "micropython" in lower_name:
        score += 60
    if "esp32" in lower_name:
        score += 35
    if "generic" in lower_name:
        score += 18
    if "firmware" in lower_parent or "micropython" in lower_parent:
        score += 10
    if any(token in lower_name for token in ("bootloader", "partition", "otadata", "ota", "spiffs")):
        score -= 120

    try:
        stat = path.stat()
    except OSError:
        return -999, 0.0

    if stat.st_size >= 700_000:
        score += 24
    elif stat.st_size < 200_000:
        score -= 30

    return score, stat.st_mtime


def fetch_latest_official_firmware_url() -> str | None:
    try:
        with urllib.request.urlopen(MICROPYTHON_ESP32_GENERIC_PAGE, timeout=12) as response:
            html = response.read().decode("utf-8", errors="ignore")
    except Exception:
        return None

    matches = re.findall(r'href="([^"]+ESP32_GENERIC[^"]+?\.bin)"', html, flags=re.IGNORECASE)
    for href in matches:
        lower_href = href.lower()
        if "app-bin" in lower_href or "preview" in lower_href:
            continue
        return urllib.parse.urljoin(MICROPYTHON_ESP32_GENERIC_PAGE, href)
    if matches:
        return urllib.parse.urljoin(MICROPYTHON_ESP32_GENERIC_PAGE, matches[0])
    return None


def download_latest_official_firmware() -> str | None:
    firmware_url = fetch_latest_official_firmware_url()
    if not firmware_url:
        return None

    destination_dir = USER_DATA_ROOT / "firmware"
    destination_dir.mkdir(parents=True, exist_ok=True)
    filename = Path(urllib.parse.urlparse(firmware_url).path).name or "esp32-micropython.bin"
    destination = destination_dir / filename
    if destination.exists() and destination.stat().st_size > 0:
        return str(destination)

    try:
        with urllib.request.urlopen(firmware_url, timeout=20) as response:
            destination.write_bytes(response.read())
    except Exception:
        return None
    return str(destination)


def discover_firmware_bin(auto_download: bool = False) -> str | None:
    candidates = []
    seen = set()

    for base_dir in FIRMWARE_SCAN_DIRS:
        for path in _iter_bin_files(base_dir):
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            score, mtime = _score_firmware_candidate(resolved)
            if score <= -50:
                continue
            candidates.append((score, mtime, resolved))

    if not candidates:
        if auto_download:
            return download_latest_official_firmware()
        return None

    candidates.sort(key=lambda item: (item[0], item[1], str(item[2])), reverse=True)
    return str(candidates[0][2])


def _wifi_devices() -> list[str]:
    result = _run_best_effort(["networksetup", "-listallhardwareports"])
    if result.returncode != 0:
        return []

    devices = []
    current_port = ""
    for raw_line in result.stdout.splitlines():
        line = raw_line.strip()
        if line.startswith("Hardware Port:"):
            current_port = line.split(":", 1)[1].strip()
            continue
        if line.startswith("Device:") and current_port == "Wi-Fi":
            devices.append(line.split(":", 1)[1].strip())
    return devices


def _corewlan_details() -> dict:
    try:
        from CoreWLAN import CWWiFiClient
    except Exception:
        return {}

    try:
        client = CWWiFiClient.sharedWiFiClient()
        interface = client.interface()
    except Exception:
        return {}

    if interface is None:
        return {}

    try:
        return {
            "interface": str(interface.interfaceName() or ""),
            "ssid": str(interface.ssid() or ""),
            "bssid": str(interface.bssid() or ""),
        }
    except Exception:
        return {}


def detect_wifi_environment(include_password: bool = False) -> dict:
    info = {
        "interface": "",
        "connected": False,
        "ip": "",
        "ssid": "",
        "ssid_visible": False,
        "ssid_hidden": False,
        "password": "",
        "password_available": False,
        "password_requested": include_password,
        "security": "",
        "status": "offline",
        "message": "",
    }

    devices = _wifi_devices()
    corewlan = _corewlan_details()
    if not devices:
        info["status"] = "unavailable"
        info["message"] = "没有检测到可用的 Wi-Fi 网卡，请手动填写路由器信息。"
        return info

    for device in devices:
        ip_result = _run_best_effort(["ipconfig", "getifaddr", device])
        ip_value = ip_result.stdout.strip()

        summary_result = _run_best_effort(["ipconfig", "getsummary", device])
        summary_text = summary_result.stdout or ""

        ssid_value = ""
        ssid_visible = False
        ssid_hidden = False
        security_mode = ""

        network_result = _run_best_effort(["networksetup", "-getairportnetwork", device])
        network_text = (network_result.stdout or "").strip()
        if network_text.startswith("Current Wi-Fi Network:"):
            ssid_value = network_text.split(":", 1)[1].strip()
            ssid_visible = bool(ssid_value)

        for raw_line in summary_text.splitlines():
            line = raw_line.strip()
            if line.startswith("SSID :") and not ssid_visible:
                candidate = line.split(":", 1)[1].strip()
                if candidate == "<redacted>":
                    ssid_hidden = True
                elif candidate:
                    ssid_value = candidate
                    ssid_visible = True
            if line.startswith("Security :"):
                security_mode = line.split(":", 1)[1].strip()

        if corewlan.get("interface") == device and corewlan.get("ssid"):
            ssid_value = corewlan["ssid"]
            ssid_visible = True
            ssid_hidden = False

        if not ip_value and not ssid_value and not ssid_hidden:
            continue

        info["interface"] = device
        info["connected"] = bool(ip_value)
        info["ip"] = ip_value
        info["ssid"] = ssid_value
        info["ssid_visible"] = ssid_visible
        info["ssid_hidden"] = ssid_hidden
        info["security"] = security_mode
        break

    if not info["interface"]:
        info["status"] = "offline"
        info["message"] = "当前没有连接到 Wi-Fi，可手动填写 SSID 和密码后继续烧录。"
        return info

    if include_password and info["ssid_visible"] and info["ssid"]:
        password_result = _run_best_effort(
            [
                "security",
                "find-generic-password",
                "-D",
                "AirPort network password",
                "-a",
                info["ssid"],
                "-w",
            ]
        )
        password_value = password_result.stdout.strip()
        if password_result.returncode == 0 and password_value:
            info["password"] = password_value
            info["password_available"] = True

    if not info["connected"]:
        info["status"] = "offline"
        info["message"] = "已检测到 Wi-Fi 网卡，但当前没有联网，请手动输入路由器信息。"
    elif info["password_available"]:
        info["status"] = "ready"
        info["message"] = "已自动读取到当前 Wi-Fi 信息，烧录时可直接同步到板子。"
    elif info["ssid_hidden"]:
        info["status"] = "needs_manual"
        info["message"] = "已检测到本机 Wi-Fi IP，但 macOS 隐藏了当前 SSID，请手动确认 SSID 和密码。"
    elif info["ssid_visible"]:
        info["status"] = "needs_password"
        info["message"] = "已检测到当前 Wi-Fi 和本机 IP，但密码受系统安全限制，可能仍需手动输入。"
    else:
        info["status"] = "needs_manual"
        info["message"] = "已检测到本机 Wi-Fi IP，但没有拿到当前网络名称，请手动填写 SSID 和密码。"

    return info


def render_config(profile: dict | None = None) -> str:
    module = _load_config_module()
    values = _uppercase_config_values(module)
    if profile:
        values.update(profile)

    lines = [
        "# Auto-generated by the KS5002 desktop studio.",
        "# Generated values override the default desktop template when flashing.",
        "",
    ]
    used = set()
    for name in CONFIG_RENDER_ORDER:
        if name not in values:
            continue
        if name in DESKTOP_ONLY_KEYS:
            continue
        used.add(name)
        lines.append("%s = %s" % (name, pformat(values[name], width=88, sort_dicts=False)))

    for name in sorted(values):
        if name in used:
            continue
        if name in DESKTOP_ONLY_KEYS:
            continue
        lines.append("%s = %s" % (name, pformat(values[name], width=88, sort_dicts=False)))

    lines.append("")
    return "\n".join(lines)


def persist_generated_artifacts(profile: dict, config_text: str) -> None:
    LAST_GENERATED_CONFIG_PATH.write_text(config_text, encoding="utf-8")
    LAST_FLASH_PROFILE_PATH.write_text(
        json.dumps(profile, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def build_stage_directory(boot_mode: str = "main", profile: dict | None = None) -> tuple[tempfile.TemporaryDirectory, Path]:
    if boot_mode not in BOOT_SOURCES:
        raise SystemExit("未知启动模式: %s" % boot_mode)

    tempdir = tempfile.TemporaryDirectory()
    stage_dir = Path(tempdir.name)

    for relative in STATIC_FILES:
        source = ROOT / relative
        shutil.copy2(source, stage_dir / source.name)

    effective_profile = profile or load_saved_profile()
    config_text = render_config(effective_profile)
    persist_generated_artifacts(effective_profile, config_text)
    (stage_dir / "config.py").write_text(config_text, encoding="utf-8")
    shutil.copy2(BOOT_SOURCES[boot_mode], stage_dir / "main.py")
    return tempdir, stage_dir


def upload_project(port: str, stage_dir: Path, logger=None) -> None:
    files = [source for source in stage_dir.iterdir() if source.is_file()]
    files.sort(key=lambda source: (source.name == "main.py", source.name))
    for source in files:
        if not source.is_file():
            continue
        target = ":" + source.name
        command = mpremote_cmd() + ["connect", port, "fs", "cp", str(source), target]
        attempts = 2
        for attempt in range(1, attempts + 1):
            try:
                run_command(command, capture=False, logger=logger)
                break
            except CommandError:
                if attempt >= attempts:
                    raise
                if logger is not None:
                    logger("上传 %s 失败，准备重试一次..." % source.name)
                time.sleep(0.8)


def soft_reset(port: str, logger=None) -> None:
    command = mpremote_cmd() + ["connect", port, "reset"]
    run_command(command, capture=False, logger=logger)


def flash_firmware(port: str, firmware: str, logger=None) -> None:
    firmware_path = str(Path(firmware).expanduser().resolve())
    run_command(esptool_cmd() + ["--chip", "esp32", "--port", port, "erase_flash"], capture=False, logger=logger)
    run_command(
        esptool_cmd()
        + ["--chip", "esp32", "--port", port, "--baud", "460800", "write_flash", "-z", "0x1000", firmware_path],
        capture=False,
        logger=logger,
    )


def wait_for_device_ready(port: str, logger=None, timeout_s: float = 10.0) -> None:
    started = time.time()
    while time.time() - started < timeout_s:
        ports = {item.device for item in list_ports.comports()}
        if port in ports:
            time.sleep(1.2)
            return
        time.sleep(0.35)
    if logger is not None:
        logger("串口 %s 在 %.1f 秒内没有稳定回来，继续尝试连接。" % (port, timeout_s))


def deploy_runtime(
    port: str,
    boot_mode: str = "main",
    profile: dict | None = None,
    firmware: str | None = None,
    logger=None,
) -> None:
    if firmware:
        if logger:
            logger("先刷写固件：%s" % firmware)
        flash_firmware(port, firmware, logger=logger)
        if logger:
            logger("等待开发板在刷固件后重新上线...")
        wait_for_device_ready(port, logger=logger)

    tempdir, stage_dir = build_stage_directory(boot_mode=boot_mode, profile=profile)
    try:
        if logger:
            logger("上传 %s 模式文件..." % ("主程序" if boot_mode == "main" else "自检"))
            logger("本次烧录配置预览：%s" % LAST_GENERATED_CONFIG_PATH)
            logger("本次烧录参数快照：%s" % LAST_FLASH_PROFILE_PATH)
        upload_project(port, stage_dir, logger=logger)
    finally:
        tempdir.cleanup()

    if logger:
        logger("重启开发板...")
    soft_reset(port, logger=logger)


def parse_common_args(description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--port", help="串口，例如 /dev/cu.usbserial-0001")
    parser.add_argument("--firmware", help="可选，先用 esptool 烧录 MicroPython 固件 bin")
    return parser


def write_report(payload: dict) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = __import__("datetime").datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = REPORTS_DIR / ("report_%s.json" % stamp)
    report_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report_path
