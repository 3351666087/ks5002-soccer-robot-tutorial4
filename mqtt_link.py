import compat as hw
from compat import json_module
from mini_mqtt import MiniMQTTClient


def _ticks_due(now, target):
    return target is not None and hw.ticks_diff(now, target) >= 0


class MqttRelayClient:
    def __init__(
        self,
        broker_host,
        namespace,
        broker_port=1883,
        connect_host=None,
        report_interval_ms=650,
        keepalive_s=20,
        status_enabled=True,
        socket_timeout_s=0.25,
        write_timeout_s=4.0,
        connect_timeout_s=12.0,
        reconnect_delay_ms=900,
    ):
        self.broker_host = str(broker_host or "").strip()
        self.namespace = str(namespace or "").strip().strip("/")
        self.broker_port = int(broker_port or 1883)
        self.connect_host = str(connect_host or "").strip() or self.broker_host
        self.report_interval_ms = int(report_interval_ms or 650)
        self.keepalive_s = int(keepalive_s or 20)
        self.status_enabled = bool(status_enabled)
        self.socket_timeout_s = float(socket_timeout_s or 0.25)
        self.write_timeout_s = float(write_timeout_s or max(self.socket_timeout_s * 2.5, 4.0))
        self.connect_timeout_s = float(connect_timeout_s or 12.0)
        self.reconnect_delay_ms = int(reconnect_delay_ms or 900)
        self.status_error = ""
        self.enabled = bool(self.broker_host and self.namespace)
        self.command_topic = self.namespace + "/cmd"
        self.status_topic = self.namespace + "/status"
        self.client = None
        self.seq = 0
        self.last_error = ""
        self.last_report_due_ms = 0
        self.reconnect_due_ms = 0
        self.client_id = "ks5002-%d" % (hw.ticks_ms() & 0xFFFF)

    def _robot_motion_active(self, robot):
        try:
            summary = robot.mqtt_summary() if hasattr(robot, "mqtt_summary") else robot.summary()
        except Exception:
            return False
        control_state = str(summary.get("control_state") or "")
        if control_state in ("manual-forward", "manual-backward", "manual-left", "manual-right"):
            return True
        if str(summary.get("script") or ""):
            return True
        left = int(summary.get("current_left_speed") or 0)
        right = int(summary.get("current_right_speed") or 0)
        return bool(left or right)

    def _compact_summary(self, robot):
        if hasattr(robot, "mqtt_summary"):
            summary = robot.mqtt_summary()
        else:
            summary = robot.summary()
        keys = (
            "mode",
            "control_state",
            "auto_state",
            "auto_paused",
            "manual_left_speed",
            "manual_right_speed",
            "current_left_speed",
            "current_right_speed",
            "display_face",
            "head_pose",
            "head_angle",
            "lights",
            "lights_scene",
            "lights_mode",
            "lights_hw_enabled",
            "lights_guard_state",
            "lights_guard_reason",
            "lights_preview",
            "captured_ball",
            "sonar_cm",
            "forward_guard_state",
            "forward_limit_pwm",
            "manual_release_decel_active",
            "ball_visible",
            "ball_direction",
            "ball_distance_cm",
            "script",
            "script_phase",
        )
        payload = {}
        for key in keys:
            if key in summary:
                payload[key] = summary[key]
        return payload

    def _status_payload(self, robot, network_state):
        return {
            "ok": True,
            "service": "ks5002-http",
            "network_mode": network_state["network_mode"],
            "ip_address": network_state["ip_address"],
            "station_connected": network_state["station_connected"],
            "station_ip": network_state["station_ip"],
            "ap_ip": network_state["ap_ip"],
            "sta_ssid": network_state["sta_ssid"],
            "ap_ssid": network_state["ap_ssid"],
            "port": getattr(robot.cfg, "PORT", 80),
            "uptime_ms": hw.ticks_ms(),
            "summary": self._compact_summary(robot),
            "relay_online": True,
            "transport": "mqtt",
        }

    def _disconnect(self):
        if self.client is None:
            return
        try:
            self.client.close()
        except Exception:
            pass
        self.client = None

    def _connect(self):
        client = MiniMQTTClient(
            self.broker_host,
            port=self.broker_port,
            client_id=self.client_id,
            connect_host=self.connect_host,
            keepalive_s=self.keepalive_s,
            socket_timeout_s=self.socket_timeout_s,
            write_timeout_s=self.write_timeout_s,
            connect_timeout_s=self.connect_timeout_s,
        )
        client.connect()
        client.subscribe(self.command_topic)
        self.client = client
        self.last_report_due_ms = 0
        self.last_error = ""
        self.status_error = ""

    def _publish_status(self, robot, network_state):
        payload = json_module.dumps(self._status_payload(robot, network_state))
        self.client.publish(self.status_topic, payload)

    def prime_connection(self):
        if not self.enabled:
            return False
        if self.client is not None:
            return True
        self._connect()
        return True

    def _handle_publish(self, robot, payload_bytes):
        try:
            payload = json_module.loads(payload_bytes.decode())
        except Exception:
            return None
        seq = int(payload.get("seq") or 0)
        path = str(payload.get("path") or "")
        if seq <= self.seq:
            return None
        self.seq = seq
        if not path:
            return None
        return robot.handle_path(path)

    def tick(self, robot, network_state):
        if not self.enabled:
            return None
        now = hw.ticks_ms()
        result = None
        try:
            if self.client is None:
                if self.reconnect_due_ms and hw.ticks_diff(now, self.reconnect_due_ms) < 0:
                    return None
                self._connect()

            self.client.maybe_ping()
            count = 0
            while count < 3:
                message = self.client.poll()
                if not message:
                    break
                if message.get("type") == "publish" and message.get("topic") == self.command_topic:
                    result = self._handle_publish(robot, message.get("payload") or b"") or result
                count += 1
            motion_active = self._robot_motion_active(robot)
            if self.status_enabled and (not motion_active) and _ticks_due(now, self.last_report_due_ms):
                self._publish_status(robot, network_state)
                self.last_report_due_ms = hw.ticks_add(now, self.report_interval_ms)
                self.status_error = ""
            elif result is not None and self.status_enabled and (not self._robot_motion_active(robot)):
                self._publish_status(robot, network_state)
                self.last_report_due_ms = hw.ticks_add(now, self.report_interval_ms)
                self.status_error = ""
            self.last_error = ""
        except Exception as exc:
            self.last_error = str(exc)
            self.status_error = str(exc)
            self._disconnect()
            self.reconnect_due_ms = hw.ticks_add(now, self.reconnect_delay_ms)
        return result
