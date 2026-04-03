from __future__ import annotations

import subprocess
from typing import Callable

try:
    import objc
    import Security
    from AppKit import NSWorkspace
    from CoreLocation import CLLocationManager
    from Foundation import NSBundle, NSObject, NSURL
except Exception:  # pragma: no cover - macOS only
    objc = None
    Security = None
    NSWorkspace = None
    CLLocationManager = None
    NSBundle = None
    NSObject = object
    NSURL = None


STATUS_MAP = {
    0: "not_determined",
    1: "restricted",
    2: "denied",
    3: "authorized_always",
    4: "authorized_when_in_use",
}

KEYCHAIN_STATUS_MAP = {
    0: "success",
    -128: "user_canceled",
    -25293: "auth_failed",
    -25300: "item_not_found",
    -25308: "interaction_not_allowed",
}

_ACTIVE_LOCATION_REQUESTS = []


def is_available() -> bool:
    return all(item is not None for item in (objc, Security, NSWorkspace, CLLocationManager, NSBundle, NSURL))


def is_packaged_app() -> bool:
    if NSBundle is None:
        return False
    try:
        bundle_path = str(NSBundle.mainBundle().bundlePath() or "")
        bundle_identifier = str(NSBundle.mainBundle().bundleIdentifier() or "")
    except Exception:
        return False
    if bundle_identifier == "com.apple.python3":
        return False
    return bundle_path.endswith(".app")


def bundle_identifier() -> str:
    if NSBundle is None:
        return ""
    try:
        return str(NSBundle.mainBundle().bundleIdentifier() or "")
    except Exception:
        return ""


def bundle_has_location_usage_description() -> bool:
    if NSBundle is None:
        return False
    try:
        info = NSBundle.mainBundle().infoDictionary() or {}
    except Exception:
        return False
    return bool(info.get("NSLocationWhenInUseUsageDescription") or info.get("NSLocationUsageDescription"))


def _location_status_code() -> int:
    if CLLocationManager is None:
        return -1
    try:
        return int(CLLocationManager.authorizationStatus())
    except Exception:
        return -1


def location_status() -> dict:
    code = _location_status_code()
    return {
        "available": CLLocationManager is not None,
        "code": code,
        "name": STATUS_MAP.get(code, "unknown"),
        "services_enabled": bool(CLLocationManager.locationServicesEnabled()) if CLLocationManager else False,
        "packaged_app": is_packaged_app(),
        "bundle_identifier": bundle_identifier(),
        "bundle_has_usage_description": bundle_has_location_usage_description(),
    }


class _LocationDelegate(NSObject):
    def initWithCallback_(self, callback: Callable[[dict], None] | None):
        self = objc.super(_LocationDelegate, self).init()
        if self is None:
            return None
        self.callback = callback
        self.manager = None
        return self

    def _emit(self):
        if self.callback is not None:
            self.callback(location_status())

    def locationManagerDidChangeAuthorization_(self, manager):
        self._emit()
        status_code = _location_status_code()
        if status_code in (1, 2, 3, 4):
            try:
                manager.stopUpdatingLocation()
            except Exception:
                pass

    def locationManager_didUpdateLocations_(self, manager, locations):
        del locations
        self._emit()
        try:
            manager.stopUpdatingLocation()
        except Exception:
            pass

    def locationManager_didFailWithError_(self, manager, error):
        del error
        self._emit()
        try:
            manager.stopUpdatingLocation()
        except Exception:
            pass


def request_location_permission(callback: Callable[[dict], None] | None = None) -> dict:
    if CLLocationManager is None or objc is None:
        return {"ok": False, "reason": "corelocation_unavailable", "status": location_status()}

    manager = CLLocationManager.alloc().init()
    delegate = _LocationDelegate.alloc().initWithCallback_(callback)
    delegate.manager = manager
    manager.setDelegate_(delegate)
    _ACTIVE_LOCATION_REQUESTS.append((manager, delegate))

    try:
        manager.requestWhenInUseAuthorization()
    except Exception:
        pass

    try:
        manager.startUpdatingLocation()
    except Exception:
        pass

    return {"ok": True, "status": location_status()}


def _decode_keychain_result(result) -> str:
    if result is None:
        return ""
    if isinstance(result, bytes):
        return result.decode("utf-8", errors="ignore")
    try:
        return bytes(result).decode("utf-8", errors="ignore")
    except Exception:
        return str(result)


def _query_wifi_password(query: dict) -> tuple[int, str]:
    if Security is None:
        return -1, ""
    status, result = Security.SecItemCopyMatching(query, None)
    if int(status) == 0:
        return int(status), _decode_keychain_result(result)
    return int(status), ""


def request_wifi_password(ssid: str) -> dict:
    if Security is None:
        return {"ok": False, "status": "security_unavailable", "password": "", "code": -1}
    if not ssid:
        return {"ok": False, "status": "missing_ssid", "password": "", "code": -1}

    base_query = {
        Security.kSecClass: Security.kSecClassGenericPassword,
        Security.kSecReturnData: True,
        Security.kSecMatchLimit: Security.kSecMatchLimitOne,
        Security.kSecUseAuthenticationUI: Security.kSecUseAuthenticationUIAllow,
    }
    variants = [
        {Security.kSecAttrAccount: ssid, Security.kSecAttrDescription: "AirPort network password"},
        {Security.kSecAttrLabel: ssid, Security.kSecAttrDescription: "AirPort network password"},
        {Security.kSecAttrService: ssid, Security.kSecAttrDescription: "AirPort network password"},
        {Security.kSecAttrAccount: ssid},
    ]

    last_status = -25300
    for extra in variants:
        query = dict(base_query)
        query.update(extra)
        status, password = _query_wifi_password(query)
        last_status = status
        if status == 0 and password:
            return {"ok": True, "status": "success", "password": password, "code": status}
        if status in (-128, -25293):
            return {"ok": False, "status": KEYCHAIN_STATUS_MAP.get(status, "auth_failed"), "password": "", "code": status}

    return {
        "ok": False,
        "status": KEYCHAIN_STATUS_MAP.get(last_status, "unknown"),
        "password": "",
        "code": last_status,
    }


def open_privacy_settings(section: str = "location") -> bool:
    url_map = {
        "location": "x-apple.systempreferences:com.apple.preference.security?Privacy_LocationServices",
        "network": "x-apple.systempreferences:com.apple.preference.security?Privacy_LocalNetwork",
        "privacy": "x-apple.systempreferences:com.apple.preference.security?Privacy",
    }
    target = url_map.get(section, url_map["privacy"])
    if NSWorkspace is not None and NSURL is not None:
        try:
            return bool(NSWorkspace.sharedWorkspace().openURL_(NSURL.URLWithString_(target)))
        except Exception:
            pass
    try:
        subprocess.Popen(["open", target])
        return True
    except Exception:
        return False
