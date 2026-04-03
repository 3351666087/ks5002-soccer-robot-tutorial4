import compat as hw
from compat import json_module, socket_module

try:
    import gc as _gc
except ImportError:
    _gc = None


def _quote(value):
    text = str(value or "")
    safe = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.~"
    out = []
    index = 0
    while index < len(text):
        char = text[index]
        if char in safe:
            out.append(char)
        else:
            code = ord(char)
            if code < 256:
                out.append("%%%02X" % code)
            else:
                out.append("_")
        index += 1
    return "".join(out)


class RelayCommandLink:
    def __init__(self, base_url, pull_interval_ms=120, connect_host=None, report_interval_ms=1200):
        self.base_url = str(base_url or "").strip().rstrip("/")
        self.pull_interval_ms = int(pull_interval_ms or 120)
        self.report_interval_ms = int(report_interval_ms or 0)
        self.enabled = self.base_url.startswith("http://")
        self.host = ""
        self.port = 80
        self.base_path = ""
        if self.enabled:
            self.host, self.port, self.base_path = self._parse_http_url(self.base_url)
        self.connect_host = str(connect_host or "").strip() or self.host
        self.address = None
        self.seq = 0
        self.last_error = ""
        self.last_pull_due_ms = 0
        self.last_report_due_ms = 0

    def prime_connection(self):
        return self.enabled

    def _parse_http_url(self, url):
        if not url.startswith("http://"):
            raise ValueError("relay only supports plain http")
        remainder = url[7:]
        slash = remainder.find("/")
        if slash >= 0:
            host_part = remainder[:slash]
            base_path = remainder[slash:]
        else:
            host_part = remainder
            base_path = ""
        if ":" in host_part:
            host, port_text = host_part.rsplit(":", 1)
            port = int(port_text or "80")
        else:
            host = host_part
            port = 80
        return host, port, base_path.rstrip("/")

    def _relay_path(self, suffix):
        return "%s%s" % (self.base_path, suffix)

    def _send_packet(self, sock, packet):
        offset = 0
        total = len(packet)
        while offset < total:
            chunk = packet[offset : offset + 512]
            if hasattr(sock, "send"):
                sent = sock.send(chunk)
            else:
                sent = sock.write(chunk)
            if sent is None:
                sent = len(chunk)
            if sent <= 0:
                raise OSError("relay socket send failed")
            offset += sent

    def _open_socket(self):
        if _gc is not None:
            try:
                _gc.collect()
            except Exception:
                pass
        if self.address is None:
            self.address = socket_module.getaddrinfo(self.connect_host, self.port, 0, socket_module.SOCK_STREAM)[0][-1]
        sock = socket_module.socket()
        if hasattr(sock, "settimeout"):
            sock.settimeout(0.45)
        sock.connect(self.address)
        return sock

    def _recv_once(self, path):
        packet = (
            "GET %s HTTP/1.1\r\nHost: %s\r\nConnection: close\r\n\r\n"
            % (path, self.host)
        ).encode()
        sock = self._open_socket()
        try:
            self._send_packet(sock, packet)
            return sock.recv(640)
        finally:
            try:
                sock.close()
            except Exception:
                pass
            if _gc is not None:
                try:
                    _gc.collect()
                except Exception:
                    pass

    def _fire_and_forget_get(self, path):
        packet = (
            "GET %s HTTP/1.1\r\nHost: %s\r\nConnection: close\r\n\r\n"
            % (path, self.host)
        ).encode()
        sock = self._open_socket()
        try:
            self._send_packet(sock, packet)
        finally:
            try:
                sock.close()
            except Exception:
                pass
            if _gc is not None:
                try:
                    _gc.collect()
                except Exception:
                    pass

    def _pull_command(self):
        raw = self._recv_once(self._relay_path("/relay/pull?since=%d" % self.seq))
        header_blob, _, body = raw.partition(b"\r\n\r\n")
        headers = {}
        for line in header_blob.split(b"\r\n")[1:]:
            if b":" not in line:
                continue
            key, value = line.split(b":", 1)
            try:
                headers[key.decode().strip().lower()] = value.decode().strip()
            except Exception:
                pass
        if "x-ks5002-seq" in headers or "x-ks5002-path" in headers:
            try:
                seq = int(headers.get("x-ks5002-seq") or self.seq)
            except Exception:
                seq = self.seq
            return {"ok": True, "seq": seq, "path": headers.get("x-ks5002-path") or ""}
        if not body:
            return None
        return json_module.loads(body.decode())

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

    def _report_ping(self, robot, network_state):
        summary = self._compact_summary(robot)
        parts = [
            "n=%s" % _quote(network_state.get("network_mode", "")),
            "i=%s" % _quote(network_state.get("station_ip", "")),
            "m=%s" % _quote(summary.get("mode", "")),
            "c=%s" % _quote(summary.get("control_state", "")),
            "f=%s" % _quote(summary.get("display_face", "")),
            "l=%s" % _quote(summary.get("lights_scene", "")),
        ]
        self._fire_and_forget_get(self._relay_path("/relay/ping?" + "&".join(parts)))

    def tick(self, robot, network_state):
        if not self.enabled:
            return None
        now = hw.ticks_ms()
        if self.report_interval_ms > 0:
            due = (not self.last_report_due_ms) or hw.ticks_diff(now, self.last_report_due_ms) >= 0
            if due:
                try:
                    self._report_ping(robot, network_state)
                    self.last_error = ""
                except Exception as exc:
                    self.last_error = str(exc)
                self.last_report_due_ms = hw.ticks_add(now, self.report_interval_ms)
        if self.last_pull_due_ms and hw.ticks_diff(now, self.last_pull_due_ms) < 0:
            return None
        try:
            payload = self._pull_command()
            self.last_pull_due_ms = hw.ticks_add(now, self.pull_interval_ms)
            self.last_error = ""
        except Exception as exc:
            self.last_error = str(exc)
            self.last_pull_due_ms = hw.ticks_add(now, max(320, self.pull_interval_ms * 3))
            return None
        if not payload:
            return None
        seq = int(payload.get("seq") or self.seq)
        path = str(payload.get("path") or "")
        if seq > self.seq:
            self.seq = seq
        if not path:
            return None
        return robot.handle_path(path)
