import compat as hw
from compat import socket_module


def _errno(exc):
    if hasattr(exc, "errno") and exc.errno is not None:
        return exc.errno
    args = getattr(exc, "args", ())
    if args:
        first = args[0]
        if isinstance(first, int):
            return first
    return None


def _is_timeout(exc):
    err = _errno(exc)
    if err in (-203, 11, 110, 115, 116, 118):
        return True
    text = str(exc).lower()
    return "timed out" in text or "timeout" in text or "eagain" in text


def _is_retryable_send(exc):
    err = _errno(exc)
    if err in (-203, 11, 12, 110, 115, 116, 118):
        return True
    text = str(exc).lower()
    return (
        "timed out" in text
        or "timeout" in text
        or "eagain" in text
        or "memory" in text
        or "would block" in text
    )


def _to_bytes(value):
    if isinstance(value, bytes):
        return value
    return str(value).encode()


def _pack_u16(value):
    return bytes(((value >> 8) & 0xFF, value & 0xFF))


def _pack_str(value):
    raw = _to_bytes(value)
    return _pack_u16(len(raw)) + raw


def _encode_varlen(length):
    out = bytearray()
    while True:
        digit = length & 0x7F
        length >>= 7
        if length:
            digit |= 0x80
        out.append(digit)
        if not length:
            break
    return bytes(out)


class MiniMQTTClient:
    def __init__(
        self,
        server,
        port=1883,
        client_id="ks5002",
        connect_host=None,
        keepalive_s=20,
        socket_timeout_s=0.2,
        write_timeout_s=None,
        connect_timeout_s=8.0,
    ):
        self.server = str(server or "").strip()
        self.port = int(port or 1883)
        self.client_id = str(client_id or "ks5002").strip() or "ks5002"
        self.connect_host = str(connect_host or "").strip() or self.server
        self.keepalive_s = int(keepalive_s or 20)
        self.socket_timeout_s = float(socket_timeout_s or 0.2)
        if write_timeout_s is None:
            write_timeout_s = max(self.socket_timeout_s * 4.0, 2.0)
        self.write_timeout_s = float(write_timeout_s or self.socket_timeout_s)
        self.connect_timeout_s = float(connect_timeout_s or 8.0)
        self.sock = None
        self.packet_id = 0
        self.last_io_ms = hw.ticks_ms()

    def _set_timeout(self, timeout_s):
        if self.sock is not None and hasattr(self.sock, "settimeout"):
            self.sock.settimeout(timeout_s)

    def _next_packet_id(self):
        self.packet_id = (self.packet_id % 65535) + 1
        return self.packet_id

    def _recv_exact(self, size):
        chunks = bytearray()
        while len(chunks) < size:
            data = self.sock.recv(size - len(chunks))
            if not data:
                raise OSError("mqtt socket closed")
            chunks.extend(data)
        self.last_io_ms = hw.ticks_ms()
        return bytes(chunks)

    def _read_varlen(self):
        multiplier = 1
        value = 0
        while True:
            digit = self._recv_exact(1)[0]
            value += (digit & 0x7F) * multiplier
            if not (digit & 0x80):
                return value
            multiplier <<= 7
            if multiplier > 2097152:
                raise ValueError("mqtt length too large")

    def _send_all(self, packet, timeout_s=None, restore_timeout_s=None):
        if timeout_s is not None:
            self._set_timeout(timeout_s)
        total = len(packet)
        offset = 0
        deadline_ms = None
        if timeout_s is not None:
            deadline_ms = hw.ticks_add(hw.ticks_ms(), int(timeout_s * 1000))
        chunk_size = 128 if getattr(hw, "IS_MICROPYTHON", False) else 512
        try:
            while offset < total:
                chunk = packet[offset : offset + chunk_size]
                try:
                    if hasattr(self.sock, "send"):
                        sent = self.sock.send(chunk)
                    elif hasattr(self.sock, "write"):
                        sent = self.sock.write(chunk)
                    else:
                        raise OSError("mqtt socket send unavailable")
                except Exception as exc:
                    if not _is_retryable_send(exc):
                        raise
                    if deadline_ms is not None and hw.ticks_diff(hw.ticks_ms(), deadline_ms) >= 0:
                        raise
                    hw.sleep_ms(20)
                    continue
                if sent is None:
                    sent = len(chunk)
                if sent <= 0:
                    if deadline_ms is not None and hw.ticks_diff(hw.ticks_ms(), deadline_ms) >= 0:
                        raise OSError("mqtt socket send failed")
                    hw.sleep_ms(20)
                    continue
                offset += sent
            self.last_io_ms = hw.ticks_ms()
        finally:
            if timeout_s is not None:
                self._set_timeout(self.socket_timeout_s if restore_timeout_s is None else restore_timeout_s)

    def _packet(self, header, body=b""):
        return bytes((header,)) + _encode_varlen(len(body)) + body

    def connect(self, clean_session=True):
        self.close()
        address = socket_module.getaddrinfo(
            self.connect_host, self.port, 0, socket_module.SOCK_STREAM
        )[0][-1]
        self.sock = socket_module.socket()
        self._set_timeout(self.connect_timeout_s)
        self.sock.connect(address)

        flags = 0x02 if clean_session else 0x00
        variable = _pack_str("MQTT") + b"\x04" + bytes((flags,)) + _pack_u16(self.keepalive_s)
        payload = _pack_str(self.client_id)
        self._send_all(
            self._packet(0x10, variable + payload),
            timeout_s=self.connect_timeout_s,
            restore_timeout_s=self.connect_timeout_s,
        )

        header = self._recv_exact(1)[0]
        if header != 0x20:
            raise OSError("mqtt connack header")
        remaining = self._read_varlen()
        payload = self._recv_exact(remaining)
        if len(payload) < 2 or payload[1] != 0x00:
            raise OSError("mqtt connack rc=%s" % (payload[1] if len(payload) > 1 else -1))

        self._set_timeout(self.socket_timeout_s)
        return True

    def close(self):
        if self.sock is None:
            return
        try:
            self.sock.close()
        except Exception:
            pass
        self.sock = None

    def subscribe(self, topic):
        packet_id = self._next_packet_id()
        body = _pack_u16(packet_id) + _pack_str(topic) + b"\x00"
        self._set_timeout(self.connect_timeout_s)
        self._send_all(
            self._packet(0x82, body),
            timeout_s=self.connect_timeout_s,
            restore_timeout_s=self.connect_timeout_s,
        )

        header = self._recv_exact(1)[0]
        if (header >> 4) != 9:
            raise OSError("mqtt suback header")
        remaining = self._read_varlen()
        payload = self._recv_exact(remaining)
        self._set_timeout(self.socket_timeout_s)
        if len(payload) < 3 or payload[2] == 0x80:
            raise OSError("mqtt subscribe failed")
        return True

    def publish(self, topic, payload, retain=False):
        payload_bytes = _to_bytes(payload)
        body = _pack_str(topic) + payload_bytes
        header = 0x31 if retain else 0x30
        self._send_all(self._packet(header, body), timeout_s=self.write_timeout_s)

    def ping(self):
        self._send_all(b"\xC0\x00", timeout_s=self.write_timeout_s)

    def maybe_ping(self):
        if self.keepalive_s <= 0:
            return
        now = hw.ticks_ms()
        if hw.ticks_diff(now, self.last_io_ms) >= self.keepalive_s * 500:
            self.ping()

    def poll(self):
        if self.sock is None:
            return None
        self._set_timeout(self.socket_timeout_s)
        try:
            first = self.sock.recv(1)
        except Exception as exc:
            if _is_timeout(exc):
                return None
            raise
        if not first:
            raise OSError("mqtt socket closed")
        self.last_io_ms = hw.ticks_ms()
        header = first[0]
        remaining = self._read_varlen()
        payload = self._recv_exact(remaining) if remaining else b""
        packet_type = header >> 4

        if packet_type == 3:
            if len(payload) < 2:
                return None
            topic_len = (payload[0] << 8) | payload[1]
            index = 2
            topic = payload[index : index + topic_len].decode()
            index += topic_len
            qos = (header >> 1) & 0x03
            if qos:
                packet_id = (payload[index] << 8) | payload[index + 1]
                index += 2
                if qos == 1:
                    self._send_all(b"\x40\x02" + _pack_u16(packet_id))
            return {"type": "publish", "topic": topic, "payload": payload[index:]}

        if packet_type == 13:
            return {"type": "pingresp"}
        if packet_type == 9:
            return {"type": "suback", "payload": payload}
        if packet_type == 2:
            return {"type": "connack", "payload": payload}
        return {"type": packet_type, "payload": payload}
