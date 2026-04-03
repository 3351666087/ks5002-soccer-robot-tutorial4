import compat as hw
from compat import json_module, socket_module

try:
    import gc as _gc
except ImportError:
    _gc = None


def _ticks_due(now, target):
    return target is not None and hw.ticks_diff(now, target) >= 0


def _dump_json(payload):
    try:
        return json_module.dumps(payload, separators=(",", ":"))
    except TypeError:
        return json_module.dumps(payload)


def _gc_collect():
    if _gc is None:
        return
    try:
        _gc.collect()
    except Exception:
        pass


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


class RelayClient:
    def __init__(self, base_url, report_interval_ms=450, pull_interval_ms=80, connect_host=None):
        self.base_url = str(base_url or "").strip().rstrip("/")
        self.report_interval_ms = int(report_interval_ms)
        self.pull_interval_ms = int(pull_interval_ms)
        self.seq = 0
        self.last_error = ""
        self.last_report_due_ms = 0
        self.last_pull_due_ms = 0
        self.enabled = self.base_url.startswith("http://")
        self.host = ""
        self.port = 80
        self.base_path = ""
        if self.enabled:
            self.host, self.port, self.base_path = self._parse_http_url(self.base_url)
        self.connect_host = str(connect_host or "").strip() or self.host

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

    def _request(self, method, path, body=None, content_type="application/json", response_mode="body"):
        address = socket_module.getaddrinfo(self.connect_host, self.port, 0, socket_module.SOCK_STREAM)[0][-1]
        sock = socket_module.socket()
        try:
            if hasattr(sock, "settimeout"):
                sock.settimeout(4)
            sock.connect(address)
            body_bytes = b""
            if body is not None:
                if isinstance(body, bytes):
                    body_bytes = body
                else:
                    body_bytes = str(body).encode()
            request = [
                "%s %s HTTP/1.1" % (method, path),
                "Host: %s" % self.host,
                "Connection: close",
            ]
            if body_bytes:
                request.append("Content-Type: %s" % content_type)
                request.append("Content-Length: %d" % len(body_bytes))
            packet = ("\r\n".join(request) + "\r\n\r\n").encode() + body_bytes
            offset = 0
            total = len(packet)
            while offset < total:
                chunk = packet[offset : offset + 512]
                if hasattr(sock, "send"):
                    sent = sock.send(chunk)
                elif hasattr(sock, "write"):
                    sent = sock.write(chunk)
                else:
                    raise OSError("relay socket send unavailable")
                if sent is None:
                    sent = len(chunk)
                if sent <= 0:
                    raise OSError("relay socket send failed")
                offset += sent

            if response_mode == "none":
                return b""

            chunks = bytearray()
            header_end = -1
            expected_body = None
            partial_headers = {}
            while True:
                data = sock.recv(512)
                if not data:
                    break
                chunks.extend(data)
                if response_mode == "headers":
                    lines = bytes(chunks).split(b"\r\n")
                    scan_lines = lines[:-1]
                    if bytes(chunks).endswith(b"\r\n"):
                        scan_lines = lines
                    for line in scan_lines[1:]:
                        if b":" not in line:
                            continue
                        key, value = line.split(b":", 1)
                        try:
                            partial_headers[key.decode().strip().lower()] = value.decode().strip()
                        except Exception:
                            pass
                    if "x-ks5002-seq" in partial_headers and "x-ks5002-path" in partial_headers:
                        break
                if header_end < 0:
                    marker = chunks.find(b"\r\n\r\n")
                    if marker >= 0:
                        header_end = marker + 4
                        header_block = bytes(chunks[:marker]).split(b"\r\n")
                        for line in header_block[1:]:
                            lowered = line.lower()
                            if not lowered.startswith(b"content-length:"):
                                continue
                            try:
                                expected_body = int(line.split(b":", 1)[1].strip() or b"0")
                            except Exception:
                                expected_body = None
                            break
                if header_end >= 0:
                    if response_mode == "headers":
                        break
                    if expected_body is not None and len(chunks) - header_end >= expected_body:
                        break
            raw = bytes(chunks)
        finally:
            try:
                sock.close()
            except Exception:
                pass

        header_lines = []
        if header_end >= 0:
            header_lines = raw[: header_end - 4].split(b"\r\n")
            body_bytes = raw[header_end:]
            if expected_body is not None:
                body_bytes = body_bytes[:expected_body]
        else:
            parts = raw.split(b"\r\n\r\n", 1)
            if len(parts) == 2:
                header_lines = parts[0].split(b"\r\n")
                body_bytes = parts[1]
            else:
                body_bytes = b""
                header_lines = []
        if response_mode == "headers":
            headers = {}
            for line in header_lines[1:]:
                if b":" not in line:
                    continue
                key, value = line.split(b":", 1)
                try:
                    headers[key.decode().strip().lower()] = value.decode().strip()
                except Exception:
                    pass
            if partial_headers:
                headers.update(partial_headers)
            return {"headers": headers, "body": body_bytes}
        return body_bytes

    def _relay_path(self, suffix):
        return "%s%s" % (self.base_path, suffix)

    def _send_packet(self, sock, packet):
        offset = 0
        total = len(packet)
        while offset < total:
            chunk = packet[offset : offset + 512]
            if hasattr(sock, "send"):
                sent = sock.send(chunk)
            elif hasattr(sock, "write"):
                sent = sock.write(chunk)
            else:
                raise OSError("relay socket send unavailable")
            if sent is None:
                sent = len(chunk)
            if sent <= 0:
                raise OSError("relay socket send failed")
            offset += sent

    def _open_socket(self):
        _gc_collect()
        address = socket_module.getaddrinfo(self.connect_host, self.port, 0, socket_module.SOCK_STREAM)[0][-1]
        _gc_collect()
        sock = socket_module.socket()
        if hasattr(sock, "settimeout"):
            sock.settimeout(2)
        sock.connect(address)
        return sock

    def _get_headers_once(self, path):
        packet = (
            "GET %s HTTP/1.1\r\nHost: %s\r\nConnection: close\r\n\r\n"
            % (path, self.host)
        ).encode()
        sock = self._open_socket()
        try:
            self._send_packet(sock, packet)
            raw = sock.recv(640)
        finally:
            try:
                sock.close()
            except Exception:
                pass
        headers = {}
        lines = raw.split(b"\r\n")
        for line in lines[1:]:
            if b":" not in line:
                continue
            key, value = line.split(b":", 1)
            try:
                headers[key.decode().strip().lower()] = value.decode().strip()
            except Exception:
                pass
        return headers, raw

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

    def _compact_summary(self, robot):
        summary = robot.summary()
        keys = (
            "mode",
            "control_state",
            "auto_state",
            "auto_paused",
            "manual_left_speed",
            "manual_right_speed",
            "display_face",
            "lights",
            "lights_scene",
            "captured_ball",
            "sonar_cm",
            "forward_guard_state",
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
        }

    def _report_status(self, robot, network_state):
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

    def _pull_command(self):
        headers, raw = self._get_headers_once(self._relay_path("/relay/pull?since=%d" % self.seq))
        if "x-ks5002-seq" in headers or "x-ks5002-path" in headers:
            try:
                seq = int(headers.get("x-ks5002-seq") or self.seq)
            except Exception:
                seq = self.seq
            return {"ok": True, "seq": seq, "path": headers.get("x-ks5002-path") or ""}
        parts = raw.split(b"\r\n\r\n", 1)
        body = parts[1] if len(parts) == 2 else b""
        if not body:
            return None
        return json_module.loads(body.decode())

    def tick(self, robot, network_state):
        if not self.enabled:
            return None
        now = hw.ticks_ms()
        result = None
        try:
            if self.report_interval_ms > 0 and _ticks_due(now, self.last_report_due_ms):
                self._report_status(robot, network_state)
                self.last_report_due_ms = hw.ticks_add(now, self.report_interval_ms)
            if _ticks_due(now, self.last_pull_due_ms):
                payload = self._pull_command()
                self.last_pull_due_ms = hw.ticks_add(now, self.pull_interval_ms)
                if payload:
                    seq = int(payload.get("seq") or self.seq)
                    path = str(payload.get("path") or "")
                    if seq > self.seq:
                        self.seq = seq
                    if path:
                        result = robot.handle_path(path)
                        self.last_report_due_ms = 0
            self.last_error = ""
        except Exception as exc:
            self.last_error = str(exc)
            backoff_ms = max(self.pull_interval_ms, 350)
            self.last_report_due_ms = hw.ticks_add(now, backoff_ms)
            self.last_pull_due_ms = hw.ticks_add(now, backoff_ms)
        return result
