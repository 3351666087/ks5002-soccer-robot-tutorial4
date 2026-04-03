import compat as hw
from compat import json_module
from mini_mqtt import MiniMQTTClient


class MqttCommandLink:
    def __init__(
        self,
        broker_host,
        namespace,
        broker_port=1883,
        connect_host=None,
        keepalive_s=0,
    ):
        self.broker_host = str(broker_host or "").strip()
        self.namespace = str(namespace or "").strip().strip("/")
        self.broker_port = int(broker_port or 1883)
        self.connect_host = str(connect_host or "").strip() or self.broker_host
        self.keepalive_s = int(keepalive_s or 0)
        self.enabled = bool(self.broker_host and self.namespace)
        self.command_topic = self.namespace + "/cmd"
        self.client = None
        self.seq = 0
        self.last_error = ""
        self.reconnect_due_ms = 0
        self.client_id = "ks5002-cmd-%d" % (hw.ticks_ms() & 0xFFFF)

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
            socket_timeout_s=0.18,
        )
        client.connect()
        client.subscribe(self.command_topic)
        self.client = client
        self.last_error = ""

    def prime_connection(self):
        if not self.enabled:
            return False
        if self.client is None:
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
        del network_state
        if not self.enabled:
            return None
        now = hw.ticks_ms()
        result = None
        try:
            if self.client is None:
                if self.reconnect_due_ms and hw.ticks_diff(now, self.reconnect_due_ms) < 0:
                    return None
                self._connect()

            if self.keepalive_s > 0:
                self.client.maybe_ping()

            count = 0
            while count < 4:
                message = self.client.poll()
                if not message:
                    break
                if message.get("type") == "publish" and message.get("topic") == self.command_topic:
                    result = self._handle_publish(robot, message.get("payload") or b"") or result
                count += 1
            self.last_error = ""
        except Exception as exc:
            self.last_error = str(exc)
            self._disconnect()
            self.reconnect_due_ms = hw.ticks_add(now, 900)
        return result
