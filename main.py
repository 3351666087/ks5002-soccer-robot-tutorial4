import config
import compat as hw
from compat import network_module, socket_module

try:
    import gc as _gc
except ImportError:
    _gc = None


def _gc_collect():
    if _gc is None:
        return
    try:
        _gc.collect()
    except Exception:
        pass


def _status_response(robot, network_state):
    payload = {
        "ok": True,
        "service": "ks5002-http",
        "network_mode": network_state["network_mode"],
        "ip_address": network_state["ip_address"],
        "station_connected": network_state["station_connected"],
        "station_ip": network_state["station_ip"],
        "ap_ip": network_state["ap_ip"],
        "sta_ssid": network_state["sta_ssid"],
        "ap_ssid": network_state["ap_ssid"],
        "port": config.PORT,
        "uptime_ms": hw.ticks_ms(),
        "summary": robot.summary(),
    }
    return "application/json; charset=utf-8", hw.json_module.dumps(payload)


def _connect_wifi_snapshot(config_module, connect_timeout_ms=None, connect_if_needed=True):
    snapshot = {
        "network_mode": "offline",
        "ip_address": "0.0.0.0",
        "station_connected": False,
        "station_ip": "",
        "ap_ip": "",
        "sta_ssid": getattr(config_module, "STA_SSID", ""),
        "ap_ssid": getattr(config_module, "AP_SSID", ""),
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

    if snapshot["sta_ssid"]:
        if not sta.isconnected() and connect_if_needed:
            try:
                sta.connect(snapshot["sta_ssid"], getattr(config_module, "STA_PASSWORD", ""))
            except Exception:
                pass
            timeout_ms = (
                int(connect_timeout_ms)
                if connect_timeout_ms is not None
                else int(getattr(config_module, "WIFI_CONNECT_TIMEOUT_MS", 12000) or 12000)
            )
            if timeout_ms > 0:
                started = hw.ticks_ms()
                while not sta.isconnected():
                    if hw.ticks_diff(hw.ticks_ms(), started) > timeout_ms:
                        break
                    hw.sleep_ms(250)
        if sta.isconnected():
            try:
                snapshot["station_ip"] = sta.ifconfig()[0]
            except Exception:
                snapshot["station_ip"] = ""

    if snapshot["station_ip"]:
        snapshot["station_connected"] = True
        snapshot["network_mode"] = "station"
        snapshot["ip_address"] = snapshot["station_ip"]
        try:
            ap.active(False)
        except Exception:
            pass
        return snapshot

    try:
        ap.active(True)
        if getattr(config_module, "AP_PASSWORD", "") and len(getattr(config_module, "AP_PASSWORD", "")) >= 8:
            ap.config(essid=config_module.AP_SSID, password=config_module.AP_PASSWORD)
        else:
            ap.config(essid=config_module.AP_SSID)
    except Exception:
        pass
    try:
        snapshot["ap_ip"] = ap.ifconfig()[0]
    except Exception:
        snapshot["ap_ip"] = "192.168.4.1"
    snapshot["network_mode"] = "ap_fallback"
    snapshot["ip_address"] = snapshot["ap_ip"]
    return snapshot


def _open_http_server(host, port):
    bind_hosts = [str(host or "").strip() or "0.0.0.0", "0.0.0.0", ""]
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
                address = socket_module.getaddrinfo(bind_host, port, 0, socket_module.SOCK_STREAM)[0][-1]
                sock.bind(address)
                sock.listen(1)
                try:
                    sock.setblocking(False)
                except Exception:
                    pass
                return sock
            except OSError as exc:
                last_error = exc
                try:
                    sock.close()
                except Exception:
                    pass
        hw.sleep_ms(350)
        attempt += 1
    raise last_error


def _poll_http_path(sock, responder=None):
    try:
        client, _address = sock.accept()
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
        packet = (
            (
                "HTTP/1.1 %d %s\r\n"
                "Content-Type: %s\r\n"
                "Content-Length: %d\r\n"
                "Connection: close\r\n"
                "\r\n"
            )
            % (status_code, reason, content_type, len(body_bytes))
        ).encode() + body_bytes
        if hasattr(client, "sendall"):
            client.sendall(packet)
        else:
            offset = 0
            while offset < len(packet):
                sent = client.send(packet[offset:])
                if sent is None or sent <= 0:
                    raise OSError("socket send failed")
                offset += sent
        hw.sleep_ms(20)
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


def main():
    network_state = _connect_wifi_snapshot(config)
    station_connected = bool(network_state.get("station_connected"))
    network_mode = str(network_state.get("network_mode") or "offline")
    ip_address = str(network_state.get("ip_address") or "0.0.0.0")
    station_ip = str(network_state.get("station_ip") or "")
    ap_ip = str(network_state.get("ap_ip") or "")
    sta_ssid = str(network_state.get("sta_ssid") or "")
    ap_ssid = str(network_state.get("ap_ssid") or "")
    print("WiFi mode:", network_mode)
    print("Control IP:", ip_address)

    mqtt_host = str(getattr(config, "MQTT_BROKER_HOST", "") or "").strip()
    mqtt_namespace = str(getattr(config, "MQTT_NAMESPACE", "") or "").strip()
    runtime_profile = str(getattr(config, "RUNTIME_PROFILE", "lite_remote") or "lite_remote").strip().lower()

    relay = None
    if mqtt_host and mqtt_namespace:
        _gc_collect()
        mqtt_status_enabled = bool(getattr(config, "MQTT_STATUS_PUBLISH_ENABLED", True))
        if mqtt_status_enabled:
            from mqtt_link import MqttRelayClient

            relay = MqttRelayClient(
                mqtt_host,
                mqtt_namespace,
                broker_port=int(getattr(config, "MQTT_BROKER_PORT", 1883) or 1883),
                connect_host=str(getattr(config, "MQTT_CONNECT_HOST", "") or "").strip() or None,
                report_interval_ms=int(getattr(config, "MQTT_REPORT_MS", 650) or 650),
                keepalive_s=int(getattr(config, "MQTT_KEEPALIVE_S", 20) or 20),
                status_enabled=mqtt_status_enabled,
                socket_timeout_s=float(getattr(config, "MQTT_SOCKET_TIMEOUT_S", 0.25) or 0.25),
                write_timeout_s=float(getattr(config, "MQTT_WRITE_TIMEOUT_S", 4.0) or 4.0),
                connect_timeout_s=float(getattr(config, "MQTT_CONNECT_TIMEOUT_S", 12.0) or 12.0),
                reconnect_delay_ms=int(getattr(config, "MQTT_RECONNECT_DELAY_MS", 900) or 900),
            )
        else:
            from mqtt_command_link import MqttCommandLink

            relay = MqttCommandLink(
                mqtt_host,
                mqtt_namespace,
                broker_port=int(getattr(config, "MQTT_BROKER_PORT", 1883) or 1883),
                connect_host=str(getattr(config, "MQTT_CONNECT_HOST", "") or "").strip() or None,
                keepalive_s=int(getattr(config, "MQTT_KEEPALIVE_S", 0) or 0),
            )
        if bool(getattr(config, "MQTT_PRECONNECT_BEFORE_ACTUATORS", False)):
            try:
                relay.prime_connection()
                print("MQTT preconnect: ready")
            except Exception as exc:
                print("MQTT preconnect failed:", exc)
                relay = None

    relay_url = str(getattr(config, "RELAY_BASE_URL", "") or "").strip()
    lan_bridge_host = str(getattr(config, "LAN_BRIDGE_HOST", "") or "").strip()
    if relay is None and not relay_url and lan_bridge_host:
        _gc_collect()
        from tcp_command_link import TcpCommandLink

        relay = TcpCommandLink(
            lan_bridge_host,
            port=int(getattr(config, "LAN_BRIDGE_PORT", 8766) or 8766),
            poll_interval_ms=int(getattr(config, "LAN_POLL_MS", 140) or 140),
            status_interval_ms=int(getattr(config, "LAN_STATUS_MS", 700) or 700),
        )

    if relay is None and relay_url:
        _gc_collect()
        relay_report_ms = getattr(config, "RELAY_REPORT_MS", 450)
        if relay_report_ms in (None, ""):
            relay_report_ms = 450
        relay_report_ms = int(relay_report_ms)
        relay_connect_host = str(getattr(config, "RELAY_CONNECT_HOST", "") or "").strip() or None
        if relay_report_ms > 0:
            from relay_link import RelayClient

            relay = RelayClient(
                relay_url,
                report_interval_ms=relay_report_ms,
                pull_interval_ms=int(getattr(config, "RELAY_PULL_MS", 80) or 80),
                connect_host=relay_connect_host,
            )
        else:
            from relay_command_link import RelayCommandLink

            relay = RelayCommandLink(
                relay_url,
                pull_interval_ms=int(getattr(config, "RELAY_PULL_MS", 80) or 80),
                connect_host=relay_connect_host,
                report_interval_ms=int(getattr(config, "RELAY_PING_MS", 1200) or 0),
            )

    network_state = None
    network_mode = ""
    ip_address = ""
    station_ip = ""
    ap_ip = ""
    sta_ssid = ""
    ap_ssid = ""
    mqtt_host = ""
    mqtt_namespace = ""
    relay_url = ""
    _gc_collect()
    if runtime_profile == "full":
        from car_runtime import RemoteCar
    else:
        from remote_mqtt_safe_runtime import RemoteCar
    runtime_profile = ""

    _gc_collect()
    robot = RemoteCar(config)
    robot.set_network_connected(station_connected)

    network_state = _connect_wifi_snapshot(config)

    disable_onboard_http = bool(getattr(config, "REMOTE_TRANSPORT_DISABLE_ONBOARD_HTTP", True))
    server_sock = None
    if relay is None or not disable_onboard_http:
        _gc_collect()
        server_sock = _open_http_server(config.HOST, config.PORT)

    print("Buttons:")
    print("  auto mode   :", config.BUTTON_AUTO_MODE_ALIASES)
    print("  manual mode :", config.BUTTON_MANUAL_MODE_ALIASES)
    print("  ok/toggle   :", config.BUTTON_OK_ALIASES)
    print("  auto stop   :", config.BUTTON_STOP_AUTO_ALIASES)
    print("  ram kick    :", config.BUTTON_RAM_KICK_ALIASES)
    if relay is not None and relay.enabled:
        if hasattr(relay, "base_url"):
            print("Relay URL     :", relay.base_url)
        elif hasattr(relay, "host"):
            print("Bridge TCP    : %s:%s" % (relay.host, relay.port))
        else:
            print("MQTT Broker   :", mqtt_host)
            print("MQTT Namespace:", mqtt_namespace)

    loop_count = 0
    last_relay_error = ""
    wifi_poll_due_ms = 0
    last_wifi_retry_ms = 0
    try:
        while True:
            now = hw.ticks_ms()
            if not wifi_poll_due_ms or hw.ticks_diff(now, wifi_poll_due_ms) >= 0:
                retry_interval_ms = int(getattr(config, "WIFI_RETRY_INTERVAL_MS", 9000) or 9000)
                retry_due = (not last_wifi_retry_ms) or hw.ticks_diff(now, last_wifi_retry_ms) >= retry_interval_ms
                network_state = _connect_wifi_snapshot(
                    config,
                    connect_timeout_ms=0,
                    connect_if_needed=retry_due,
                )
                station_connected = bool(network_state.get("station_connected"))
                if station_connected:
                    last_wifi_retry_ms = 0
                elif retry_due:
                    last_wifi_retry_ms = now
                robot.set_network_connected(station_connected)
                wifi_poll_due_ms = hw.ticks_add(
                    now,
                    int(getattr(config, "WIFI_STATUS_POLL_MS", 700) or 700),
                )
            if server_sock is not None:
                path = _poll_http_path(
                    server_sock,
                    responder=lambda request_path: _status_response(robot, network_state)
                    if request_path in ("/", "/status", "/status.json", "/health")
                    else None,
                )
                if path is not None:
                    result = robot.handle_path(path)
                    print("request:", path, "=>", result)
            if relay is not None and relay.enabled:
                relay_result = relay.tick(robot, network_state)
                if relay_result is not None:
                    print("relay:", relay_result)
                if relay.last_error and relay.last_error != last_relay_error:
                    last_relay_error = relay.last_error
                    print("relay error:", relay.last_error)
                elif not relay.last_error:
                    last_relay_error = ""
                if hasattr(robot, "note_transport_state"):
                    transport_online = bool(
                        (getattr(relay, "client", None) is not None or getattr(relay, "sock", None) is not None)
                        and not relay.last_error
                    )
                    robot.note_transport_state(transport_online, relay.last_error)
            elif hasattr(robot, "note_transport_state"):
                robot.note_transport_state(True, "")
            robot.update()
            loop_count += 1
            if (loop_count % 24) == 0:
                _gc_collect()
            if hasattr(robot, "idle_window"):
                robot.idle_window(20)
            else:
                hw.sleep_ms(20)
    finally:
        if server_sock is not None:
            try:
                server_sock.close()
            except Exception:
                pass
        robot.shutdown()


if __name__ == "__main__":
    main()
