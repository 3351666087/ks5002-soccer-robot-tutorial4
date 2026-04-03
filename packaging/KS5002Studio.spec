# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path


PROJECT_ROOT = Path(SPEC).resolve().parent.parent
TOOLS_DIR = PROJECT_ROOT / "tools"

datas = [
    (str(PROJECT_ROOT / ".mpyproject.json"), "."),
    (str(PROJECT_ROOT / "compat.py"), "."),
    (str(PROJECT_ROOT / "config.py"), "."),
    (str(PROJECT_ROOT / "ht16k33.py"), "."),
    (str(PROJECT_ROOT / "ht16k33matrix.py"), "."),
    (str(PROJECT_ROOT / "main.py"), "."),
    (str(PROJECT_ROOT / "self_test.py"), "."),
    (str(PROJECT_ROOT / "selftest_mode_main.py"), "."),
    (str(PROJECT_ROOT / "soccer_bot.py"), "."),
]

for firmware_file in (PROJECT_ROOT / "firmware").glob("*.bin"):
    datas.append((str(firmware_file), "firmware"))

hiddenimports = [
    "common",
    "studio_gui",
    "macos_permissions",
    "serial",
    "serial.tools",
    "serial.tools.list_ports",
    "CoreWLAN",
    "CoreLocation",
    "Security",
    "AppKit",
    "Foundation",
    "objc",
]

info_plist = {
    "CFBundleDisplayName": "KS5002 智控烧录台",
    "CFBundleName": "KS5002Studio",
    "CFBundleIdentifier": "com.null3351.ks5002studio",
    "LSMinimumSystemVersion": "12.0",
    "NSLocationWhenInUseUsageDescription": "用于识别当前 Wi-Fi 名称并自动同步到 ESP32 机器人。",
    "NSLocationUsageDescription": "用于识别当前 Wi-Fi 名称并自动同步到 ESP32 机器人。",
    "NSLocalNetworkUsageDescription": "用于发现、烧录和控制局域网中的 ESP32 足球机器人。",
    "NSBonjourServices": ["_http._tcp"],
}

a = Analysis(
    ['../studio.py'],
    pathex=[str(PROJECT_ROOT), str(TOOLS_DIR)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='KS5002Studio',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='KS5002Studio',
)
app = BUNDLE(
    coll,
    name='KS5002Studio.app',
    icon=None,
    bundle_identifier='com.null3351.ks5002studio',
    info_plist=info_plist,
)
