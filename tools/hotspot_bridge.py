from __future__ import annotations

import argparse
import json
import socketserver
import subprocess
import sys
import threading
import time
import urllib.parse
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import config as project_config  # noqa: E402
from mini_mqtt import MiniMQTTClient  # noqa: E402
from common import load_saved_profile  # noqa: E402

try:  # noqa: E402
    import paho.mqtt.client as paho_mqtt
except Exception:  # pragma: no cover - optional desktop dependency
    paho_mqtt = None


MOTION_COMMANDS = {"/btn/F", "/btn/B", "/btn/L", "/btn/R", "/btn/S"}
PAN_COMMANDS = {"/btn/l", "/btn/m", "/btn/n", "/btn/3", "/btn/3#", "/btn/4", "/btn/4#", "/btn/5", "/btn/5#"}


def _command_family(path: str) -> str:
    path = str(path or "")
    if path in MOTION_COMMANDS:
        return "motion"
    if path.startswith("/btn/u"):
        return "speed-left"
    if path.startswith("/btn/v"):
        return "speed-right"
    if path in PAN_COMMANDS:
        return "pan"
    return ""


class RelayState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.seq = 0
        self.pending: deque[tuple[int, str, float]] = deque()
        self.last_status: dict = {
            "ok": False,
            "service": "ks5002-http",
            "network_mode": "relay-wait",
            "ip_address": "",
            "station_connected": False,
            "station_ip": "",
            "ap_ip": "",
            "sta_ssid": "",
            "ap_ssid": "",
            "port": 80,
            "uptime_ms": 0,
            "summary": {
                "control_state": "waiting-relay",
                "lights": False,
                "lights_scene": "off",
                "display_face": "cry",
            },
        }
        self.last_status_at = 0.0
        self.last_ping_at = 0.0
        self.last_pull_at = 0.0
        self.last_pull_since = 0
        self.last_pull_seq = 0
        self.last_pull_path = ""
        self.pull_count = 0
        self.transport_name = "idle"
        self.transport_error = ""
        self.transport_online = False
        self.status_predicted = False
        self.last_hint_at = 0.0
        self.status_source = "boot"

    def push_command(self, path: str) -> int:
        with self.lock:
            self.seq += 1
            family = _command_family(path)
            if family:
                kept: deque[tuple[int, str, float]] = deque()
                for seq, queued_path, created_at in self.pending:
                    if _command_family(queued_path) == family:
                        continue
                    kept.append((seq, queued_path, created_at))
                self.pending = kept
            self.pending.append((self.seq, path, time.time()))
            while len(self.pending) > 128:
                self.pending.popleft()
            return self.seq

    def pull_command(self, since: int) -> dict:
        with self.lock:
            payload = None
            for seq, path, _created_at in self.pending:
                if seq > since:
                    payload = {"ok": True, "seq": seq, "path": path}
                    break
            if payload is None:
                payload = {"ok": True, "seq": self.seq, "path": ""}
            self.last_pull_at = time.time()
            self.last_pull_since = int(since or 0)
            self.last_pull_seq = int(payload.get("seq") or 0)
            self.last_pull_path = str(payload.get("path") or "")
            self.pull_count += 1
            return payload

    def update_status(self, payload: dict) -> None:
        with self.lock:
            self.last_status = payload
            self.last_status_at = time.time()
            self.status_predicted = False
            self.status_source = str(payload.get("transport") or "board")

    def update_ping(self, payload: dict) -> None:
        with self.lock:
            self.last_ping_at = time.time()
            summary = dict(self.last_status.get("summary") or {})
            summary["mode"] = str(payload.get("mode") or summary.get("mode") or "manual")
            summary["control_state"] = str(payload.get("control_state") or summary.get("control_state") or "manual")
            summary["display_face"] = str(payload.get("display_face") or summary.get("display_face") or "manual")
            summary["lights_scene"] = str(payload.get("lights_scene") or summary.get("lights_scene") or "manual_idle")
            summary["lights"] = bool(summary.get("lights_scene"))
            self.last_status = {
                "ok": True,
                "service": "ks5002-http",
                "network_mode": str(payload.get("network_mode") or "station"),
                "ip_address": str(payload.get("station_ip") or ""),
                "station_connected": bool(payload.get("station_ip")),
                "station_ip": str(payload.get("station_ip") or ""),
                "ap_ip": "",
                "sta_ssid": "",
                "ap_ssid": "KS5002-SoccerBot",
                "port": 80,
                "uptime_ms": 0,
                "summary": summary,
            }
            self.last_status_at = time.time()
            self.status_predicted = False
            self.status_source = "board-ping"

    def note_command(self, path: str) -> None:
        path = str(path or "")
        if not path.startswith("/btn/"):
            return
        with self.lock:
            summary = dict(self.last_status.get("summary") or {})
            summary.setdefault("mode", "manual")
            summary.setdefault("lights", False)
            summary.setdefault("lights_scene", "manual_idle")
            summary.setdefault("display_face", "manual")
            summary.setdefault("manual_left_speed", 760)
            summary.setdefault("manual_right_speed", 760)
            summary.setdefault("current_left_speed", 0)
            summary.setdefault("current_right_speed", 0)
            if path == "/btn/F":
                speed = int(summary.get("manual_left_speed") or 760)
                summary["control_state"] = "manual-forward"
                summary["display_face"] = "front"
                summary["current_left_speed"] = speed
                summary["current_right_speed"] = int(summary.get("manual_right_speed") or speed)
            elif path == "/btn/B":
                speed = int(summary.get("manual_left_speed") or 760)
                summary["control_state"] = "manual-backward"
                summary["display_face"] = "back"
                summary["current_left_speed"] = -speed
                summary["current_right_speed"] = -int(summary.get("manual_right_speed") or speed)
            elif path == "/btn/L":
                speed = int(summary.get("manual_left_speed") or 760)
                summary["control_state"] = "manual-left"
                summary["display_face"] = "left"
                summary["current_left_speed"] = -speed
                summary["current_right_speed"] = int(summary.get("manual_right_speed") or speed)
            elif path == "/btn/R":
                speed = int(summary.get("manual_left_speed") or 760)
                summary["control_state"] = "manual-right"
                summary["display_face"] = "right"
                summary["current_left_speed"] = speed
                summary["current_right_speed"] = -int(summary.get("manual_right_speed") or speed)
            elif path == "/btn/S":
                summary["control_state"] = "manual-idle"
                summary["display_face"] = "manual"
                summary["current_left_speed"] = 0
                summary["current_right_speed"] = 0
            elif path.startswith("/btn/u"):
                try:
                    value = int(path[6:])
                except Exception:
                    value = None
                if value is not None:
                    summary["manual_left_speed"] = value
            elif path.startswith("/btn/v"):
                try:
                    value = int(path[6:])
                except Exception:
                    value = None
                if value is not None:
                    summary["manual_right_speed"] = value
            elif path in ("/btn/l", "/btn/3", "/btn/3#"):
                summary["head_pose"] = "left"
                summary["head_angle"] = 65
                summary["display_face"] = "left"
            elif path in ("/btn/m", "/btn/5", "/btn/5#"):
                summary["head_pose"] = "center"
                summary["head_angle"] = 5
                summary["display_face"] = "manual"
            elif path in ("/btn/n", "/btn/4", "/btn/4#"):
                summary["head_pose"] = "right"
                summary["head_angle"] = -12
                summary["display_face"] = "right"
            elif path == "/btn/p":
                summary["captured_ball"] = True
                summary["display_face"] = "capture"
            elif path in ("/btn/q", "/btn/x"):
                summary["captured_ball"] = False
                summary["display_face"] = "manual"
            self.last_status["summary"] = summary
            self.status_predicted = True
            self.last_hint_at = time.time()
            self.status_source = "bridge-predicted"

    def set_transport_status(self, name: str, online: bool, error: str = "") -> None:
        with self.lock:
            self.transport_name = name
            self.transport_online = bool(online)
            self.transport_error = str(error or "")

    def current_status(self) -> dict:
        with self.lock:
            payload = dict(self.last_status)
            payload["relay_online"] = True
            payload["transport"] = self.transport_name
            payload["transport_online"] = self.transport_online
            payload["transport_error"] = self.transport_error
            if self.last_status_at:
                payload["relay_status_age_ms"] = int(max(0.0, (time.time() - self.last_status_at) * 1000.0))
            else:
                payload["relay_status_age_ms"] = -1
            payload["board_ping_age_ms"] = (
                int(max(0.0, (time.time() - self.last_ping_at) * 1000.0)) if self.last_ping_at else -1
            )
            payload["relay_pull_age_ms"] = (
                int(max(0.0, (time.time() - self.last_pull_at) * 1000.0)) if self.last_pull_at else -1
            )
            payload["bridge_hint_age_ms"] = (
                int(max(0.0, (time.time() - self.last_hint_at) * 1000.0)) if self.last_hint_at else -1
            )
            payload["summary_predicted"] = self.status_predicted
            payload["status_source"] = self.status_source
            payload["relay_pull_count"] = self.pull_count
            payload["relay_last_pull_since"] = self.last_pull_since
            payload["relay_last_pull_seq"] = self.last_pull_seq
            payload["relay_last_pull_path"] = self.last_pull_path
            return payload


class MqttBridgeTransport(threading.Thread):
    def __init__(
        self,
        state: RelayState,
        broker_host: str,
        namespace: str,
        broker_port: int = 1883,
        connect_host: str = "",
        keepalive_s: int = 20,
    ) -> None:
        super().__init__(daemon=True)
        self.state = state
        self.broker_host = str(broker_host or "").strip()
        self.namespace = str(namespace or "").strip().strip("/")
        self.broker_port = int(broker_port or 1883)
        self.connect_host = str(connect_host or "").strip() or self.broker_host
        self.keepalive_s = int(keepalive_s or 20)
        self.command_topic = self.namespace + "/cmd"
        self.status_topic = self.namespace + "/status"
        self.client_id = "ks5002-bridge-%d" % (int(time.time()) % 100000)
        self.client = None
        self.stop_event = threading.Event()
        self.commands: deque[dict] = deque()
        self.commands_lock = threading.Lock()

    def publish_command(self, seq: int, path: str) -> None:
        payload = {"seq": int(seq), "path": str(path or "")}
        family = _command_family(payload["path"])
        with self.commands_lock:
            if family:
                kept = deque()
                for item in self.commands:
                    if _command_family(item.get("path", "")) == family:
                        continue
                    kept.append(item)
                self.commands = kept
            self.commands.append(payload)

    def stop(self) -> None:
        self.stop_event.set()
        if self.client is not None:
            try:
                self.client.close()
            except Exception:
                pass
            self.client = None

    def _disconnect(self) -> None:
        if self.client is None:
            return
        try:
            self.client.close()
        except Exception:
            pass
        self.client = None

    def _connect(self) -> None:
        client = MiniMQTTClient(
            self.broker_host,
            port=self.broker_port,
            client_id=self.client_id,
            connect_host=self.connect_host,
            keepalive_s=self.keepalive_s,
            socket_timeout_s=0.08,
        )
        client.connect()
        client.subscribe(self.status_topic)
        self.client = client
        self.state.set_transport_status("mqtt", True, "")

    def _drain_commands(self) -> None:
        if self.client is None:
            return
        while True:
            with self.commands_lock:
                if not self.commands:
                    payload = None
                else:
                    payload = self.commands.popleft()
            if payload is None:
                return
            packet = json.dumps(payload, ensure_ascii=False)
            self.client.publish(self.command_topic, packet)

    def _poll_messages(self) -> None:
        if self.client is None:
            return
        for _index in range(4):
            message = self.client.poll()
            if not message:
                break
            if message.get("type") != "publish" or message.get("topic") != self.status_topic:
                continue
            try:
                payload = json.loads((message.get("payload") or b"").decode() or "{}")
            except Exception:
                continue
            if isinstance(payload, dict):
                self.state.update_status(payload)

    def run(self) -> None:
        while not self.stop_event.is_set():
            try:
                if self.client is None:
                    self._connect()
                self._drain_commands()
                self.client.maybe_ping()
                self._poll_messages()
                time.sleep(0.03)
            except Exception as exc:
                self.state.set_transport_status("mqtt", False, str(exc))
                self._disconnect()
                time.sleep(1.0)


class PahoMqttBridgeTransport(threading.Thread):
    def __init__(
        self,
        state: RelayState,
        broker_host: str,
        namespace: str,
        broker_port: int = 1883,
        connect_host: str = "",
        keepalive_s: int = 20,
    ) -> None:
        super().__init__(daemon=True)
        self.state = state
        self.broker_host = str(broker_host or "").strip()
        self.namespace = str(namespace or "").strip().strip("/")
        self.broker_port = int(broker_port or 1883)
        self.connect_host = str(connect_host or "").strip() or self.broker_host
        self.keepalive_s = int(keepalive_s or 20)
        self.command_topic = self.namespace + "/cmd"
        self.status_topic = self.namespace + "/status"
        self.client_id = "ks5002-bridge-paho-%d" % (int(time.time()) % 100000)
        self.client = None
        self.stop_event = threading.Event()
        self.commands: deque[dict] = deque()
        self.commands_lock = threading.Lock()
        self.connected = False

    def publish_command(self, seq: int, path: str) -> None:
        payload = {"seq": int(seq), "path": str(path or "")}
        family = _command_family(payload["path"])
        with self.commands_lock:
            if family:
                kept = deque()
                for item in self.commands:
                    if _command_family(item.get("path", "")) == family:
                        continue
                    kept.append(item)
                self.commands = kept
            self.commands.append(payload)

    def stop(self) -> None:
        self.stop_event.set()
        self._disconnect()

    def _disconnect(self) -> None:
        client = self.client
        self.client = None
        self.connected = False
        if client is None:
            return
        try:
            client.loop_stop()
        except Exception:
            pass
        try:
            client.disconnect()
        except Exception:
            pass

    def _on_connect(self, client, _userdata, _flags, reason_code, _properties=None) -> None:
        try:
            client.subscribe(self.status_topic)
            self.connected = True
            self.state.set_transport_status("mqtt", True, "")
        except Exception as exc:
            self.connected = False
            self.state.set_transport_status("mqtt", False, str(exc))

    def _on_disconnect(self, _client, _userdata, _flags, reason_code, _properties=None) -> None:
        self.connected = False
        if self.stop_event.is_set():
            self.state.set_transport_status("mqtt", False, "")
            return
        error = ""
        if reason_code not in (0, None):
            error = str(reason_code)
        self.state.set_transport_status("mqtt", False, error or "disconnected")

    def _on_message(self, _client, _userdata, message) -> None:
        if getattr(message, "topic", "") != self.status_topic:
            return
        try:
            payload = json.loads((getattr(message, "payload", b"") or b"").decode("utf-8", errors="ignore") or "{}")
        except Exception:
            return
        if isinstance(payload, dict):
            self.state.update_status(payload)

    def _connect(self) -> None:
        if paho_mqtt is None:
            raise RuntimeError("paho-mqtt unavailable")
        callback_api = getattr(getattr(paho_mqtt, "CallbackAPIVersion", None), "VERSION2", None)
        if callback_api is not None:
            client = paho_mqtt.Client(callback_api, client_id=self.client_id)
        else:
            client = paho_mqtt.Client(client_id=self.client_id)
        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.on_message = self._on_message
        if hasattr(client, "reconnect_delay_set"):
            client.reconnect_delay_set(min_delay=1, max_delay=5)
        client.connect(self.connect_host, self.broker_port, self.keepalive_s)
        client.loop_start()
        self.client = client
        self.connected = False

    def _drain_commands(self) -> None:
        if self.client is None or not self.connected:
            return
        while True:
            with self.commands_lock:
                if not self.commands:
                    payload = None
                else:
                    payload = self.commands.popleft()
            if payload is None:
                return
            packet = json.dumps(payload, ensure_ascii=False)
            info = self.client.publish(self.command_topic, packet)
            result_code = getattr(info, "rc", 0)
            success_code = getattr(paho_mqtt, "MQTT_ERR_SUCCESS", 0)
            if int(result_code) != int(success_code):
                raise RuntimeError("mqtt publish rc=%s" % result_code)

    def run(self) -> None:
        while not self.stop_event.is_set():
            try:
                if self.client is None:
                    self._connect()
                self._drain_commands()
                time.sleep(0.03)
            except Exception as exc:
                self.state.set_transport_status("mqtt", False, str(exc))
                self._disconnect()
                time.sleep(1.0)


class BoardTcpHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        state = self.server.relay_state  # type: ignore[attr-defined]
        error = ""
        state.set_transport_status("tcp", True, "")
        try:
            self.connection.settimeout(2.0)
        except Exception:
            pass
        try:
            while True:
                raw = self.rfile.readline(1024)
                if not raw:
                    break
                try:
                    payload = json.loads(raw.decode("utf-8", errors="ignore").strip() or "{}")
                except Exception:
                    payload = {}
                if isinstance(payload, dict):
                    state.update_ping(
                        {
                            "network_mode": payload.get("network_mode"),
                            "station_ip": payload.get("station_ip"),
                            "mode": payload.get("mode"),
                            "control_state": payload.get("control_state"),
                            "display_face": payload.get("display_face"),
                            "lights_scene": payload.get("lights_scene"),
                        }
                    )
                    try:
                        since = int(payload.get("since") or 0)
                    except Exception:
                        since = 0
                else:
                    since = 0
                reply = state.pull_command(since)
                packet = (json.dumps(reply, ensure_ascii=False) + "\n").encode("utf-8")
                self.wfile.write(packet)
                self.wfile.flush()
        except Exception as exc:
            error = str(exc)
        state.set_transport_status("tcp", False, error)


class ThreadedBoardTcpServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


class BridgeHandler(BaseHTTPRequestHandler):
    server_version = "HotspotBridge/1.0"

    @property
    def state(self) -> RelayState:
        return self.server.relay_state  # type: ignore[attr-defined]

    def log_message(self, fmt: str, *args) -> None:
        print("[%s] %s" % (self.log_date_time_string(), fmt % args))

    def _send_json(self, payload: dict, status: int = 200, extra_headers: dict | None = None) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        if extra_headers:
            for key, value in extra_headers.items():
                self.send_header(str(key), str(value))
        self.end_headers()
        self.wfile.write(body)

    def _send_text(self, text: str, status: int = 200) -> None:
        body = text.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/relay/report":
            self._send_text("not-found", 404)
            return
        length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode() or "{}")
        except Exception:
            self._send_text("bad-json", 400)
            return
        self.state.update_status(payload)
        self._send_json({"ok": True})

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)

        if parsed.path == "/status":
            self._send_json(self.state.current_status())
            return

        if parsed.path in ("/", "/health"):
            self._send_json({"ok": True, "service": "ks5002-hotspot-bridge"})
            return

        if parsed.path == "/relay/pull":
            try:
                since = int((query.get("since") or ["0"])[0] or "0")
            except ValueError:
                since = 0
            payload = self.state.pull_command(since)
            self._send_json(
                payload,
                extra_headers={
                    "X-KS5002-Seq": payload.get("seq", 0),
                    "X-KS5002-Path": payload.get("path", ""),
                },
            )
            return

        if parsed.path == "/relay/ping":
            self.state.update_ping(
                {
                    "network_mode": (query.get("n") or ["station"])[0],
                    "station_ip": (query.get("i") or [""])[0],
                    "mode": (query.get("m") or ["manual"])[0],
                    "control_state": (query.get("c") or ["manual"])[0],
                    "display_face": (query.get("f") or ["manual"])[0],
                    "lights_scene": (query.get("l") or ["manual_idle"])[0],
                }
            )
            self._send_json({"ok": True})
            return

        if parsed.path.startswith("/btn/"):
            seq = self.state.push_command(parsed.path)
            self.state.note_command(parsed.path)
            transport = getattr(self.server, "transport", None)  # type: ignore[attr-defined]
            if transport is not None:
                transport.publish_command(seq, parsed.path)
            self._send_json({"ok": True, "queued": True, "seq": seq, "path": parsed.path})
            return

        self._send_text("unknown", 404)


def start_tunnel(local_port: int) -> tuple[subprocess.Popen[str], str]:
    command = [
        "ssh",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "ServerAliveInterval=30",
        "-R",
        "80:localhost:%d" % local_port,
        "nokey@localhost.run",
    ]
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    public_url = ""
    start = time.time()
    while time.time() - start < 20:
        line = process.stdout.readline()  # type: ignore[union-attr]
        if not line:
            if process.poll() is not None:
                break
            continue
        print(line.rstrip())
        if "https://" in line:
            for token in line.split():
                if token.startswith("https://"):
                    public_url = token.strip()
                    break
        if public_url:
            break
    if not public_url:
        raise RuntimeError("没有拿到公网隧道地址")
    return process, public_url


def main() -> None:
    try:
        saved_profile = load_saved_profile()
    except Exception:
        saved_profile = {}

    def _default_value(key: str, fallback):
        value = saved_profile.get(key)
        if value in (None, ""):
            return fallback
        return value

    parser = argparse.ArgumentParser(description="Run the KS5002 hotspot relay bridge.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--tcp-port", type=int, default=8766)
    parser.add_argument("--no-tunnel", action="store_true")
    parser.add_argument(
        "--mqtt-host",
        default=str(_default_value("MQTT_BROKER_HOST", getattr(project_config, "MQTT_BROKER_HOST", "") or "")),
    )
    parser.add_argument(
        "--mqtt-port",
        type=int,
        default=int(_default_value("MQTT_BROKER_PORT", getattr(project_config, "MQTT_BROKER_PORT", 1883) or 1883) or 1883),
    )
    parser.add_argument(
        "--mqtt-connect-host",
        default=str(_default_value("MQTT_CONNECT_HOST", getattr(project_config, "MQTT_CONNECT_HOST", "") or "")),
    )
    parser.add_argument(
        "--mqtt-namespace",
        default=str(_default_value("MQTT_NAMESPACE", getattr(project_config, "MQTT_NAMESPACE", "") or "")),
    )
    parser.add_argument(
        "--mqtt-keepalive",
        type=int,
        default=int(_default_value("MQTT_KEEPALIVE_S", getattr(project_config, "MQTT_KEEPALIVE_S", 20) or 20) or 20),
    )
    args = parser.parse_args()

    state = RelayState()
    server = ThreadingHTTPServer((args.host, args.port), BridgeHandler)
    server.relay_state = state  # type: ignore[attr-defined]
    board_server = None
    board_thread = None
    transport = None
    mqtt_enabled = bool(str(args.mqtt_host or "").strip() and str(args.mqtt_namespace or "").strip())
    if mqtt_enabled:
        transport_cls = PahoMqttBridgeTransport if paho_mqtt is not None else MqttBridgeTransport
        transport = transport_cls(
            state,
            args.mqtt_host,
            args.mqtt_namespace,
            broker_port=args.mqtt_port,
            connect_host=args.mqtt_connect_host,
            keepalive_s=args.mqtt_keepalive,
        )
        server.transport = transport  # type: ignore[attr-defined]
    elif int(args.tcp_port or 0) > 0:
        board_server = ThreadedBoardTcpServer((args.host, int(args.tcp_port)), BoardTcpHandler)
        board_server.relay_state = state  # type: ignore[attr-defined]
        state.set_transport_status("tcp", False, "")
        board_thread = threading.Thread(target=board_server.serve_forever, daemon=True)

    tunnel_process = None
    try:
        if transport is not None:
            transport.start()
            transport_label = "paho" if paho_mqtt is not None else "mini"
            print(
                "MQTT_BRIDGE=%s @ %s:%d (%s)"
                % (args.mqtt_namespace, args.mqtt_host, args.mqtt_port, transport_label)
            )
        elif board_thread is not None:
            board_thread.start()
            print("BOARD_TCP_URL=tcp://%s:%d" % (args.host, args.tcp_port))
        if not args.no_tunnel and transport is None and board_thread is None:
            tunnel_process, public_url = start_tunnel(args.port)
            print("PUBLIC_RELAY_URL=%s" % public_url.replace("https://", "http://", 1))
        print("LOCAL_BRIDGE_URL=http://%s:%d" % (args.host, args.port))
        server.serve_forever()
    finally:
        server.server_close()
        if board_server is not None:
            try:
                board_server.shutdown()
            except Exception:
                pass
            board_server.server_close()
        if transport is not None:
            transport.stop()
        if tunnel_process is not None and tunnel_process.poll() is None:
            tunnel_process.terminate()


if __name__ == "__main__":
    main()
