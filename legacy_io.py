import compat as hw
from compat import network_module, socket_module


class RemoteServer:
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.sock = None
        self._open()

    def _open(self):
        bind_hosts = [self.host, "0.0.0.0", ""]
        last_error = None
        attempt = 0
        while attempt < 6:
            for bind_host in bind_hosts:
                sock = socket_module.socket()
                try:
                    sock.setsockopt(socket_module.SOL_SOCKET, socket_module.SO_REUSEADDR, 1)
                except Exception:
                    pass
                try:
                    address = socket_module.getaddrinfo(
                        bind_host,
                        self.port,
                        0,
                        socket_module.SOCK_STREAM,
                    )[0][-1]
                    sock.bind(address)
                    sock.listen(1)
                    try:
                        sock.setblocking(False)
                    except Exception:
                        pass
                    self.sock = sock
                    return
                except OSError as exc:
                    last_error = exc
                    try:
                        sock.close()
                    except Exception:
                        pass
            hw.sleep_ms(350)
            attempt += 1
        raise last_error

    def poll_path(self, responder=None):
        try:
            client, _address = self.sock.accept()
        except OSError:
            return None

        path = None
        dispatch_path = True
        try:
            try:
                client.settimeout(0.35)
            except Exception:
                pass
            raw = client.recv(512)
            if raw:
                first_line = raw.split(b"\r\n", 1)[0]
                pieces = first_line.split()
                if len(pieces) >= 2:
                    path = pieces[1].decode()
                else:
                    path = "/"

            status_code = 200
            content_type = "text/plain"
            body = "ok\r\n"
            if callable(responder):
                try:
                    custom = responder(path)
                except Exception:
                    custom = None
                if custom is not None:
                    dispatch_path = False
                    if len(custom) == 3:
                        status_code, content_type, body = custom
                    elif len(custom) == 2:
                        content_type, body = custom

            if isinstance(body, bytes):
                body_bytes = body
            else:
                body_bytes = str(body).encode()

            reason = "OK" if status_code == 200 else "ERROR"
            header = (
                "HTTP/1.1 %d %s\r\n"
                "Content-Type: %s\r\n"
                "Content-Length: %d\r\n"
                "Connection: close\r\n"
                "\r\n"
            ) % (status_code, reason, content_type, len(body_bytes))
            packet = header.encode() + body_bytes
            if hasattr(client, "sendall"):
                client.sendall(packet)
            else:
                index = 0
                while index < len(packet):
                    sent = client.send(packet[index:])
                    if sent is None or sent <= 0:
                        raise OSError("socket send failed")
                    index += sent
            hw.sleep_ms(25)
        except Exception as exc:
            print("HTTP response failed:", exc)
        finally:
            try:
                client.close()
            except Exception:
                pass

        if dispatch_path:
            return path
        return None

    def close(self):
        try:
            self.sock.close()
        except Exception:
            pass


def connect_wifi_snapshot(config):
    snapshot = {
        "network_mode": "offline",
        "ip_address": "0.0.0.0",
        "station_connected": False,
        "station_raw_connected": False,
        "station_ip": "",
        "ap_ip": "0.0.0.0",
        "sta_ssid": getattr(config, "STA_SSID", ""),
        "ap_ssid": getattr(config, "AP_SSID", ""),
    }
    if network_module is None:
        return snapshot

    sta = network_module.WLAN(network_module.STA_IF)
    ap = network_module.WLAN(network_module.AP_IF)
    sta.active(True)
    try:
        ap.active(False)
    except Exception:
        pass

    sta_ip = ""
    if snapshot["sta_ssid"]:
        if not sta.isconnected():
            sta.connect(snapshot["sta_ssid"], getattr(config, "STA_PASSWORD", ""))
            started = hw.ticks_ms()
            while not sta.isconnected():
                if hw.ticks_diff(hw.ticks_ms(), started) > 12000:
                    break
                hw.sleep_ms(250)
        if sta.isconnected():
            try:
                sta_ip = sta.ifconfig()[0]
            except Exception:
                sta_ip = ""

    if sta_ip:
        try:
            ap.active(False)
        except Exception:
            pass
        snapshot["network_mode"] = "station"
        snapshot["ip_address"] = sta_ip
        snapshot["station_connected"] = True
        snapshot["station_raw_connected"] = True
        snapshot["station_ip"] = sta_ip
        return snapshot

    try:
        ap.active(True)
        if config.AP_PASSWORD and len(config.AP_PASSWORD) >= 8:
            ap.config(essid=config.AP_SSID, password=config.AP_PASSWORD)
        else:
            ap.config(essid=config.AP_SSID)
    except Exception:
        try:
            ap.config(essid=config.AP_SSID)
        except Exception:
            pass

    try:
        snapshot["ap_ip"] = ap.ifconfig()[0]
    except Exception:
        snapshot["ap_ip"] = "192.168.4.1"
    snapshot["network_mode"] = "ap_fallback"
    snapshot["ip_address"] = snapshot["ap_ip"]
    return snapshot
