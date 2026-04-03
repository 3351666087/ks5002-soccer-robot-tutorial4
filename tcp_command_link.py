import compat as hw
from compat import json_module, socket_module

try:
    import gc as _gc
except ImportError:
    _gc = None


class TcpCommandLink:
    def __init__(self, host, port=8766, poll_interval_ms=140, status_interval_ms=700):
        self.host = str(host or "").strip()
        self.port = int(port or 8766)
        self.poll_interval_ms = int(poll_interval_ms or 140)
        self.status_interval_ms = int(status_interval_ms or 0)
        self.enabled = bool(self.host)
        self.address = None
        self.sock = None
        self.seq = 0
        self.last_error = ""
        self.last_poll_due_ms = 0
        self.last_status_due_ms = 0
        self._recv_buffer = b""

    def prime_connection(self):
        if not self.enabled:
            return False
        return self._ensure_connected()

    def _compact_summary(self, robot):
        if hasattr(robot, "mqtt_summary"):
            try:
                return robot.mqtt_summary()
            except Exception:
                pass
        if hasattr(robot, "summary"):
            try:
                return robot.summary()
            except Exception:
                pass
        return {}

    def _ensure_connected(self):
        if self.sock is not None:
            return True
        try:
            if _gc is not None:
                _gc.collect()
        except Exception:
            pass
        try:
            if self.address is None:
                self.address = socket_module.getaddrinfo(self.host, self.port, 0, socket_module.SOCK_STREAM)[0][-1]
            sock = socket_module.socket()
            if hasattr(sock, "settimeout"):
                sock.settimeout(0.5)
            sock.connect(self.address)
            self.sock = sock
            self._recv_buffer = b""
            self.last_error = ""
            return True
        except Exception as exc:
            self._close()
            self.last_error = str(exc)
            return False

    def _close(self):
        if self.sock is not None:
            try:
                self.sock.close()
            except Exception:
                pass
        self.sock = None
        self._recv_buffer = b""
        try:
            if _gc is not None:
                _gc.collect()
        except Exception:
            pass

    def _send_line(self, text):
        packet = (str(text) + "\n").encode()
        offset = 0
        total = len(packet)
        while offset < total:
            sent = self.sock.send(packet[offset:])  # type: ignore[union-attr]
            if sent is None:
                sent = total - offset
            if sent <= 0:
                raise OSError("tcp bridge send failed")
            offset += sent

    def _recv_line(self):
        while True:
            marker = self._recv_buffer.find(b"\n")
            if marker >= 0:
                line = self._recv_buffer[:marker]
                self._recv_buffer = self._recv_buffer[marker + 1 :]
                return line
            chunk = self.sock.recv(256)  # type: ignore[union-attr]
            if not chunk:
                raise OSError("tcp bridge closed")
            self._recv_buffer += chunk

    def tick(self, robot, network_state):
        if not self.enabled:
            return None
        now = hw.ticks_ms()
        if self.last_poll_due_ms and hw.ticks_diff(now, self.last_poll_due_ms) < 0:
            return None
        if not self._ensure_connected():
            self.last_poll_due_ms = hw.ticks_add(now, max(400, self.poll_interval_ms * 4))
            return None
        summary = {}
        include_status = (not self.last_status_due_ms) or hw.ticks_diff(now, self.last_status_due_ms) >= 0
        if include_status:
            summary = self._compact_summary(robot)
        payload = {"since": self.seq}
        if include_status:
            payload.update(
                {
                    "network_mode": str(network_state.get("network_mode") or ""),
                    "station_ip": str(network_state.get("station_ip") or ""),
                    "mode": str(summary.get("mode") or ""),
                    "control_state": str(summary.get("control_state") or ""),
                    "display_face": str(summary.get("display_face") or ""),
                    "lights_scene": str(summary.get("lights_scene") or ""),
                }
            )
        try:
            self._send_line(json_module.dumps(payload))
            raw = self._recv_line()
            self.last_error = ""
            self.last_poll_due_ms = hw.ticks_add(now, self.poll_interval_ms)
            if include_status and self.status_interval_ms > 0:
                self.last_status_due_ms = hw.ticks_add(now, self.status_interval_ms)
        except Exception as exc:
            self._close()
            self.last_error = str(exc)
            self.last_poll_due_ms = hw.ticks_add(now, max(400, self.poll_interval_ms * 4))
            return None
        if not raw:
            return None
        try:
            message = json_module.loads(raw.decode())
        except Exception:
            return None
        seq = int(message.get("seq") or self.seq)
        path = str(message.get("path") or "")
        if seq > self.seq:
            self.seq = seq
        if not path:
            return None
        return robot.handle_path(path)
