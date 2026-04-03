from __future__ import annotations

import json
import sys
import time
import traceback
import urllib.error
from pathlib import Path

from PySide6.QtCore import QThread, QTimer, Qt, Signal
from PySide6.QtGui import QAction, QGuiApplication
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QInputDialog,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from common import (
    PROFILE_GROUPS,
    board_exec,
    board_network_snapshot,
    delete_named_preset,
    discover_robot_on_subnet,
    deploy_runtime,
    detect_wifi_environment,
    detect_port,
    discover_firmware_bin,
    ensure_local_bridge,
    list_serial_ports_info,
    list_presets,
    load_named_preset,
    load_saved_profile,
    normalize_control_base_url,
    open_url,
    save_profile,
    save_named_preset,
    soft_reset,
)

try:
    import macos_permissions
except Exception:  # pragma: no cover - optional on non-macOS
    macos_permissions = None


class WorkerThread(QThread):
    log = Signal(str)
    done = Signal(bool, str)

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs

    def run(self):
        try:
            self.kwargs["logger"] = self.log.emit
            self.fn(*self.args, **self.kwargs)
        except BaseException as exc:
            self.done.emit(False, "%s\n%s" % (exc, traceback.format_exc()))
            return
        self.done.emit(True, "操作完成")


class RobotStatusThread(QThread):
    done = Signal(str, bool, int, str)

    def __init__(self, request_url: str):
        super().__init__()
        self.request_url = request_url

    def run(self):
        try:
            with open_url(self.request_url, timeout=1.6) as response:
                payload = response.read().decode(errors="ignore").strip()
                status_code = int(getattr(response, "status", 200) or 200)
        except Exception as exc:
            self.done.emit(self.request_url, False, 0, str(exc))
            return
        self.done.emit(self.request_url, True, status_code, payload)


class RobotDiscoveryThread(QThread):
    done = Signal(bool, str, str)

    def __init__(self, local_ip: str, prefer_hosts: list[str] | None = None):
        super().__init__()
        self.local_ip = local_ip
        self.prefer_hosts = prefer_hosts or []

    def run(self):
        try:
            result = discover_robot_on_subnet(self.local_ip, prefer_hosts=self.prefer_hosts)
        except Exception as exc:
            self.done.emit(False, "", str(exc))
            return
        if not result:
            self.done.emit(False, "", "未在当前热点网段发现板子状态接口。")
            return
        payload_text = json.dumps(result.get("payload") or {}, ensure_ascii=False)
        self.done.emit(True, result.get("base_url", ""), payload_text)


class StatusDot(QLabel):
    def __init__(self):
        super().__init__()
        self.setFixedSize(16, 16)
        self.set_status("disconnected")

    def set_status(self, status: str):
        colors = {
            "connected": "#42d392",
            "warning": "#f6c453",
            "disconnected": "#ff6b6b",
            "busy": "#79b8ff",
        }
        color = colors.get(status, "#64748b")
        self.setStyleSheet(
            "border-radius: 8px; background: %s; border: 1px solid rgba(255,255,255,0.35);" % color
        )


class LightSwatch(QLabel):
    def __init__(self):
        super().__init__()
        self.setFixedSize(28, 28)
        self.set_color("#101820")

    def set_color(self, color: str):
        shade = str(color or "#101820")
        self.setStyleSheet(
            "border-radius: 14px; background: %s; border: 1px solid rgba(255,255,255,0.28);" % shade
        )


class GlassGroup(QGroupBox):
    def __init__(self, title: str):
        super().__init__(title)
        self.setObjectName("glassGroup")


class StudioWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("KS5002 智控烧录台")
        self.resize(1380, 920)
        self.setMinimumSize(980, 700)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.worker = None
        self.form_widgets = {}
        self.port_infos = []
        self.wifi_info = {}
        self.hidden_profile = {}
        self.console_layout_mode = ""
        self.pending_control_hint = ""
        self.worker_success_handler = None
        self.worker_failure_handler = None
        self.worker_kind = ""
        self.robot_status_request_inflight = False
        self.robot_status_pending = False
        self.robot_status_worker = None
        self.robot_discovery_worker = None
        self.last_announced_board_host = ""
        self.last_discovered_board_url = ""
        self.last_robot_discovery_at = 0.0

        self._build_ui()
        self._build_menu()
        self._load_profile()
        self._auto_fill_firmware()
        self.refresh_ports()
        self.refresh_wifi_status(fill_missing=True)
        self._refresh_permission_summary()
        self._ensure_local_bridge()

        self.port_timer = QTimer(self)
        self.port_timer.timeout.connect(self.refresh_ports)
        self.port_timer.start(1200)

        self.wifi_timer = QTimer(self)
        self.wifi_timer.timeout.connect(lambda: self.refresh_wifi_status(fill_missing=False))
        self.wifi_timer.start(8000)

        self.robot_status_timer = QTimer(self)
        self.robot_status_timer.timeout.connect(self.poll_robot_status)
        self.robot_status_timer.start(2200)
        QTimer.singleShot(800, self.poll_robot_status)

    def _build_menu(self):
        action_quit = QAction("退出", self)
        action_quit.triggered.connect(self.close)
        self.menuBar().addAction(action_quit)

    def _ensure_local_bridge(self):
        try:
            ensure_local_bridge(logger=self._append_log)
        except Exception as exc:
            self._append_log("本地热点桥启动失败：%s" % exc)

    def _build_ui(self):
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)

        outer = QVBoxLayout(root)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(18)

        hero = QFrame()
        hero.setObjectName("hero")
        hero_layout = QHBoxLayout(hero)
        hero_layout.setContentsMargins(24, 18, 24, 18)

        title_box = QVBoxLayout()
        title = QLabel("KS5002 智控烧录台")
        title.setObjectName("title")
        subtitle = QLabel("PySide6 桌面控制台 · 半透明磨砂玻璃风格 · 自检与主程序双入口")
        subtitle.setObjectName("subtitle")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        hero_layout.addLayout(title_box, 1)

        status_row = QHBoxLayout()
        self.status_dot = StatusDot()
        self.status_label = QLabel("正在检测 ESP32…")
        self.status_label.setObjectName("statusLabel")
        status_row.addWidget(self.status_dot)
        status_row.addWidget(self.status_label)
        status_row.addStretch(1)
        hero_layout.addLayout(status_row)

        outer.addWidget(hero)

        self.body_splitter = QSplitter(Qt.Horizontal)
        self.body_splitter.setChildrenCollapsible(False)
        self.body_splitter.setHandleWidth(10)
        outer.addWidget(self.body_splitter, 1)

        left_card = QFrame()
        left_card.setObjectName("card")
        left_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        left_layout = QVBoxLayout(left_card)
        left_layout.setContentsMargins(18, 18, 18, 18)
        left_layout.setSpacing(14)

        connection_group = GlassGroup("连接与烧录")
        connection_layout = QGridLayout(connection_group)

        self.port_combo = QComboBox()
        self.port_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.port_combo.currentIndexChanged.connect(self._update_port_hint)
        self.refresh_button = QPushButton("刷新串口")
        self.refresh_button.clicked.connect(self.refresh_ports)

        self.firmware_edit = QLineEdit()
        self.firmware_edit.setPlaceholderText("可选：选择 MicroPython 固件 bin")
        browse_button = QPushButton("选择固件")
        browse_button.clicked.connect(self._browse_firmware)
        self.auto_firmware_button = QPushButton("自动定位")
        self.auto_firmware_button.clicked.connect(self._auto_fill_firmware)
        self.flash_firmware_checkbox = QCheckBox("本次先刷固件 bin")

        self.deploy_main_button = QPushButton("烧录主程序")
        self.deploy_main_button.clicked.connect(lambda: self._start_deploy("main"))
        self.deploy_test_button = QPushButton("烧录自检模式")
        self.deploy_test_button.clicked.connect(lambda: self._start_deploy("selftest"))
        self.quick_check_button = QPushButton("执行快速自检")
        self.quick_check_button.clicked.connect(self._quick_self_check)
        self.save_profile_button = QPushButton("保存本机参数")
        self.save_profile_button.clicked.connect(self._save_profile_clicked)

        connection_layout.addWidget(QLabel("检测到的串口"), 0, 0)
        connection_layout.addWidget(self.port_combo, 0, 1)
        connection_layout.addWidget(self.refresh_button, 0, 2)
        connection_layout.addWidget(QLabel("固件路径"), 1, 0)
        connection_layout.addWidget(self.firmware_edit, 1, 1)
        connection_layout.addWidget(browse_button, 1, 2)
        connection_layout.addWidget(self.auto_firmware_button, 1, 3)
        connection_layout.addWidget(self.flash_firmware_checkbox, 2, 0, 1, 2)
        connection_layout.addWidget(self.deploy_main_button, 3, 0)
        connection_layout.addWidget(self.deploy_test_button, 3, 1)
        connection_layout.addWidget(self.quick_check_button, 3, 2)
        connection_layout.addWidget(self.save_profile_button, 4, 0, 1, 4)

        left_layout.addWidget(connection_group)

        preset_group = GlassGroup("参数预设")
        preset_layout = QGridLayout(preset_group)
        self.preset_combo = QComboBox()
        self.load_preset_button = QPushButton("加载预设")
        self.load_preset_button.clicked.connect(self._load_selected_preset)
        self.save_preset_button = QPushButton("另存为预设")
        self.save_preset_button.clicked.connect(self._save_named_preset_clicked)
        self.delete_preset_button = QPushButton("删除预设")
        self.delete_preset_button.clicked.connect(self._delete_selected_preset)
        preset_layout.addWidget(QLabel("预设列表"), 0, 0)
        preset_layout.addWidget(self.preset_combo, 0, 1, 1, 2)
        preset_layout.addWidget(self.load_preset_button, 1, 0)
        preset_layout.addWidget(self.save_preset_button, 1, 1)
        preset_layout.addWidget(self.delete_preset_button, 1, 2)
        left_layout.addWidget(preset_group)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        scroll_layout.setSpacing(14)

        for group in PROFILE_GROUPS:
            box = GlassGroup(group["title"])
            form = QFormLayout(box)
            form.setLabelAlignment(Qt.AlignRight)
            form.setFormAlignment(Qt.AlignTop)
            form.setHorizontalSpacing(18)
            form.setVerticalSpacing(10)
            for field in group["fields"]:
                widget = self._build_field(field)
                self.form_widgets[field["key"]] = (field, widget)
                form.addRow(field["label"], widget)
            scroll_layout.addWidget(box)

        if "WIFI_MODE" in self.form_widgets:
            self.form_widgets["WIFI_MODE"][1].setEnabled(False)

        scroll_layout.addStretch(1)
        scroll.setWidget(scroll_content)
        left_layout.addWidget(scroll, 1)

        right_card = QFrame()
        right_card.setObjectName("card")
        right_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        right_layout = QVBoxLayout(right_card)
        right_layout.setContentsMargins(18, 18, 18, 18)
        right_layout.setSpacing(14)

        hint_group = GlassGroup("当前说明")
        hint_layout = QVBoxLayout(hint_group)
        self.port_hint = QLabel("暂无设备")
        self.port_hint.setWordWrap(True)
        hint_text = QLabel(
            "主程序烧录：上传正常运行逻辑。\n"
            "自检模式烧录：上传自检入口，板子上电后直接进入检测模式。\n"
            "快速自检：不改入口，直接对当前板子执行一次自检。"
        )
        hint_text.setWordWrap(True)
        hint_layout.addWidget(self.port_hint)
        hint_layout.addWidget(hint_text)

        wifi_group = GlassGroup("本机 Wi-Fi")
        wifi_layout = QGridLayout(wifi_group)
        self.wifi_state_value = QLabel("检测中")
        self.wifi_state_value.setObjectName("metricValue")
        self.wifi_iface_value = QLabel("--")
        self.wifi_iface_value.setObjectName("metricValue")
        self.wifi_ip_value = QLabel("--")
        self.wifi_ip_value.setObjectName("metricValue")
        self.wifi_ssid_value = QLabel("自动检测中")
        self.wifi_ssid_value.setObjectName("metricValue")
        self.wifi_password_value = QLabel("未尝试")
        self.wifi_password_value.setObjectName("metricValue")
        self.wifi_message = QLabel("SSID 走系统自动探测，界面里只保留密码输入。")
        self.wifi_message.setObjectName("wifiTip")
        self.wifi_message.setWordWrap(True)
        self.permission_summary_value = QLabel("脚本模式")
        self.permission_summary_value.setObjectName("metricValue")
        self.wifi_detect_button = QPushButton("重新检测")
        self.wifi_detect_button.clicked.connect(lambda: self.refresh_wifi_status(fill_missing=False))
        self.wifi_sync_button = QPushButton("同步到板子参数")
        self.wifi_sync_button.clicked.connect(self._sync_wifi_to_profile)
        self.wifi_permission_button = QPushButton("请求系统权限")
        self.wifi_permission_button.clicked.connect(self._request_native_permissions)
        self.wifi_password_button = QPushButton("读取系统密码")
        self.wifi_password_button.clicked.connect(self._request_wifi_password_from_system)
        self.open_settings_button = QPushButton("打开隐私设置")
        self.open_settings_button.clicked.connect(self._open_privacy_settings)
        wifi_layout.addWidget(QLabel("状态"), 0, 0)
        wifi_layout.addWidget(self.wifi_state_value, 0, 1)
        wifi_layout.addWidget(QLabel("接口"), 0, 2)
        wifi_layout.addWidget(self.wifi_iface_value, 0, 3)
        wifi_layout.addWidget(QLabel("本机 IP"), 1, 0)
        wifi_layout.addWidget(self.wifi_ip_value, 1, 1)
        wifi_layout.addWidget(QLabel("当前 SSID"), 1, 2)
        wifi_layout.addWidget(self.wifi_ssid_value, 1, 3)
        wifi_layout.addWidget(QLabel("密码状态"), 2, 0)
        wifi_layout.addWidget(self.wifi_password_value, 2, 1, 1, 3)
        wifi_layout.addWidget(QLabel("权限模式"), 3, 0)
        wifi_layout.addWidget(self.permission_summary_value, 3, 1, 1, 3)
        wifi_layout.addWidget(self.wifi_message, 4, 0, 1, 4)
        wifi_layout.addWidget(self.wifi_detect_button, 5, 0)
        wifi_layout.addWidget(self.wifi_sync_button, 5, 1)
        wifi_layout.addWidget(self.wifi_permission_button, 5, 2)
        wifi_layout.addWidget(self.wifi_password_button, 5, 3)
        wifi_layout.addWidget(self.open_settings_button, 6, 2, 1, 2)

        self.control_group = GlassGroup("手动控制中控台")
        control_root = QVBoxLayout(self.control_group)
        control_root.setSpacing(12)

        control_header = QFrame()
        control_header.setObjectName("consolePanel")
        header_layout = QGridLayout(control_header)
        self.control_url_edit = QLineEdit()
        self.control_url_edit.setPlaceholderText("控制地址，例如 http://192.168.4.1")
        self.control_url_edit.textChanged.connect(lambda _text: QTimer.singleShot(250, self.poll_robot_status))
        self.local_ip_chip = QLabel("本机 Wi-Fi IP: --")
        self.local_ip_chip.setObjectName("chipLabel")
        self.robot_http_dot = StatusDot()
        self.robot_http_label = QLabel("WLAN 状态检测中")
        self.robot_http_label.setObjectName("statusLabel")
        self.robot_http_meta = QLabel("等待状态接口")
        self.robot_http_meta.setObjectName("wifiTip")
        self.robot_http_meta.setWordWrap(True)
        self.robot_refresh_button = QPushButton("刷新板端状态")
        self.robot_refresh_button.clicked.connect(self.poll_robot_status)
        self.control_use_ap_button = QPushButton("使用 AP 默认地址")
        self.control_use_ap_button.clicked.connect(lambda: self.control_url_edit.setText("http://192.168.4.1"))

        self.robot_snapshot_panel = QFrame()
        self.robot_snapshot_panel.setObjectName("consolePanel")
        snapshot_layout = QGridLayout(self.robot_snapshot_panel)
        self.board_ip_value = QLabel("--")
        self.board_ip_value.setObjectName("metricValue")
        self.board_mode_value = QLabel("--")
        self.board_mode_value.setObjectName("metricValue")
        self.board_control_state_value = QLabel("--")
        self.board_control_state_value.setObjectName("metricValue")
        self.board_capture_rate_value = QLabel("暂无数据")
        self.board_capture_rate_value.setObjectName("metricValue")
        self.board_lights_mode_value = QLabel("--")
        self.board_lights_mode_value.setObjectName("metricValue")
        self.board_lights_scene_value = QLabel("--")
        self.board_lights_scene_value.setObjectName("metricValue")
        self.board_light_swatches = [LightSwatch() for _index in range(4)]
        preview_frame = QFrame()
        preview_layout = QHBoxLayout(preview_frame)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(8)
        for swatch in self.board_light_swatches:
            preview_layout.addWidget(swatch)
        preview_layout.addStretch(1)
        self.board_light_preview_tip = QLabel("灯效安全回归：当前显示的是桌面影子预览，不会触碰板载 NeoPixel。")
        self.board_light_preview_tip.setObjectName("wifiTip")
        self.board_light_preview_tip.setWordWrap(True)
        self.board_capture_tip = QLabel("等待板端状态")
        self.board_capture_tip.setObjectName("wifiTip")
        self.board_capture_tip.setWordWrap(True)
        snapshot_layout.addWidget(QLabel("当前板子 IP"), 0, 0)
        snapshot_layout.addWidget(self.board_ip_value, 0, 1)
        snapshot_layout.addWidget(QLabel("网络模式"), 0, 2)
        snapshot_layout.addWidget(self.board_mode_value, 0, 3)
        snapshot_layout.addWidget(QLabel("自动/手动状态"), 1, 0)
        snapshot_layout.addWidget(self.board_control_state_value, 1, 1)
        snapshot_layout.addWidget(QLabel("最近抓球成功率"), 1, 2)
        snapshot_layout.addWidget(self.board_capture_rate_value, 1, 3)
        snapshot_layout.addWidget(QLabel("灯效模式"), 2, 0)
        snapshot_layout.addWidget(self.board_lights_mode_value, 2, 1)
        snapshot_layout.addWidget(QLabel("当前灯景"), 2, 2)
        snapshot_layout.addWidget(self.board_lights_scene_value, 2, 3)
        snapshot_layout.addWidget(QLabel("四灯预览"), 3, 0)
        snapshot_layout.addWidget(preview_frame, 3, 1, 1, 3)
        snapshot_layout.addWidget(self.board_light_preview_tip, 4, 0, 1, 4)
        snapshot_layout.addWidget(self.board_capture_tip, 5, 0, 1, 4)

        self.speed_left_slider = QSlider(Qt.Horizontal)
        self.speed_left_slider.setRange(0, 255)
        self.speed_left_slider.setValue(200)
        self.speed_left_value = QLabel("200")
        self.speed_left_value.setObjectName("metricValue")
        self.speed_left_slider.valueChanged.connect(
            lambda value: self.speed_left_value.setText(str(value))
        )
        self.speed_left_slider.sliderReleased.connect(
            lambda: self._send_http_path("/btn/u%d" % self.speed_left_slider.value())
        )
        self.speed_right_slider = QSlider(Qt.Horizontal)
        self.speed_right_slider.setRange(0, 255)
        self.speed_right_slider.setValue(200)
        self.speed_right_value = QLabel("200")
        self.speed_right_value.setObjectName("metricValue")
        self.speed_right_slider.valueChanged.connect(
            lambda value: self.speed_right_value.setText(str(value))
        )
        self.speed_right_slider.sliderReleased.connect(
            lambda: self._send_http_path("/btn/v%d" % self.speed_right_slider.value())
        )

        header_layout.addWidget(QLabel("控制地址"), 0, 0)
        header_layout.addWidget(self.control_url_edit, 0, 1, 1, 3)
        header_layout.addWidget(self.local_ip_chip, 0, 4)
        header_layout.addWidget(self.control_use_ap_button, 0, 5)
        header_layout.addWidget(self.robot_http_dot, 1, 0)
        header_layout.addWidget(self.robot_http_label, 1, 1, 1, 2)
        header_layout.addWidget(self.robot_http_meta, 1, 3, 1, 2)
        header_layout.addWidget(self.robot_refresh_button, 1, 5)

        self.console_grid = QGridLayout()
        self.console_grid.setHorizontalSpacing(12)
        self.console_grid.setVerticalSpacing(12)

        self.btn_forward = QPushButton("前进")
        self.btn_backward = QPushButton("后退")
        self.btn_left = QPushButton("左转")
        self.btn_right = QPushButton("右转")
        self.btn_stop = QPushButton("停止/刹停")
        self.btn_manual = QPushButton("切手动")
        self.btn_auto = QPushButton("切自动")
        self.btn_ok = QPushButton("OK")
        self.btn_grab = QPushButton("抓球")
        self.btn_release = QPushButton("松球")
        self.btn_ram = QPushButton("撞球")
        self.btn_pan_left = QPushButton("云台左")
        self.btn_pan_center = QPushButton("云台中")
        self.btn_pan_right = QPushButton("云台右")
        self.btn_face_prev = QPushButton("表情上一张")
        self.btn_face_clear = QPushButton("表情清空")
        self.btn_face_next = QPushButton("表情下一张")
        self.btn_shortcut_auto = QPushButton("0")
        self.btn_shortcut_manual = QPushButton("1")
        self.btn_shortcut_pan_left = QPushButton("3")
        self.btn_shortcut_pan_right = QPushButton("4")
        self.btn_shortcut_pan_center = QPushButton("5")

        button_map = [
            (self.btn_forward, "/btn/F"),
            (self.btn_backward, "/btn/B"),
            (self.btn_left, "/btn/L"),
            (self.btn_right, "/btn/R"),
            (self.btn_stop, "/btn/S"),
            (self.btn_manual, "/btn/1"),
            (self.btn_auto, "/btn/0"),
            (self.btn_ok, "/btn/o"),
            (self.btn_grab, "/btn/p"),
            (self.btn_release, "/btn/q"),
            (self.btn_ram, "/btn/rk"),
            (self.btn_pan_left, "/btn/l"),
            (self.btn_pan_center, "/btn/m"),
            (self.btn_pan_right, "/btn/n"),
            (self.btn_face_prev, "/btn/k"),
            (self.btn_face_clear, "/btn/j"),
            (self.btn_face_next, "/btn/i"),
            (self.btn_shortcut_auto, "/btn/0"),
            (self.btn_shortcut_manual, "/btn/1"),
            (self.btn_shortcut_pan_left, "/btn/l"),
            (self.btn_shortcut_pan_right, "/btn/n"),
            (self.btn_shortcut_pan_center, "/btn/m"),
        ]
        for button, path in button_map:
            button.clicked.connect(lambda checked=False, path_value=path: self._send_http_path(path_value))

        for button in (self.btn_forward, self.btn_backward, self.btn_left, self.btn_right):
            button.setProperty("controlRole", "dpad")
            button.setMinimumSize(88, 56)
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.btn_stop.setProperty("controlRole", "danger")
        self.btn_stop.setMinimumSize(96, 60)
        self.btn_stop.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.btn_ok.setProperty("controlRole", "primary")
        self.btn_ok.setMinimumSize(120, 72)
        self.btn_ok.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        for button in (
            self.btn_manual,
            self.btn_auto,
            self.btn_grab,
            self.btn_release,
            self.btn_ram,
            self.btn_pan_left,
            self.btn_pan_center,
            self.btn_pan_right,
            self.btn_face_prev,
            self.btn_face_clear,
            self.btn_face_next,
        ):
            button.setProperty("controlRole", "action")
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        for button in (
            self.btn_shortcut_auto,
            self.btn_shortcut_manual,
            self.btn_shortcut_pan_left,
            self.btn_shortcut_pan_right,
            self.btn_shortcut_pan_center,
        ):
            button.setProperty("controlRole", "round")
            button.setFixedSize(58, 58)

        self.drive_panel = QFrame()
        self.drive_panel.setObjectName("consolePanel")
        drive_layout = QGridLayout(self.drive_panel)
        drive_layout.addWidget(QLabel("方向盘"), 0, 0, 1, 3)
        drive_layout.addWidget(self.btn_forward, 1, 1)
        drive_layout.addWidget(self.btn_left, 2, 0)
        drive_layout.addWidget(self.btn_stop, 2, 1)
        drive_layout.addWidget(self.btn_right, 2, 2)
        drive_layout.addWidget(self.btn_backward, 3, 1)

        self.function_panel = QFrame()
        self.function_panel.setObjectName("consolePanel")
        function_layout = QGridLayout(self.function_panel)
        function_layout.addWidget(QLabel("右侧功能键"), 0, 0, 1, 3)
        function_layout.addWidget(self.btn_manual, 1, 0)
        function_layout.addWidget(self.btn_auto, 1, 1)
        function_layout.addWidget(self.btn_ok, 1, 2, 2, 1)
        function_layout.addWidget(self.btn_grab, 2, 0)
        function_layout.addWidget(self.btn_release, 2, 1)
        function_layout.addWidget(self.btn_ram, 3, 0)
        function_layout.addWidget(self.btn_pan_left, 3, 1)
        function_layout.addWidget(self.btn_pan_center, 3, 2)
        function_layout.addWidget(self.btn_pan_right, 4, 0)
        function_layout.addWidget(self.btn_face_prev, 4, 1)
        function_layout.addWidget(self.btn_face_clear, 4, 2)
        function_layout.addWidget(self.btn_face_next, 5, 0, 1, 3)

        self.speed_panel = QFrame()
        self.speed_panel.setObjectName("consolePanel")
        speed_layout = QGridLayout(self.speed_panel)
        speed_layout.addWidget(QLabel("ML"), 0, 0)
        speed_layout.addWidget(self.speed_left_slider, 0, 1)
        speed_layout.addWidget(self.speed_left_value, 0, 2)
        speed_layout.addWidget(QLabel("MR"), 1, 0)
        speed_layout.addWidget(self.speed_right_slider, 1, 1)
        speed_layout.addWidget(self.speed_right_value, 1, 2)

        self.shortcut_panel = QFrame()
        self.shortcut_panel.setObjectName("consolePanel")
        shortcut_layout = QGridLayout(self.shortcut_panel)
        shortcut_layout.addWidget(QLabel("快捷数字键"), 0, 0, 1, 5)
        shortcut_layout.addWidget(self.btn_shortcut_auto, 1, 0)
        shortcut_layout.addWidget(self.btn_shortcut_manual, 1, 1)
        shortcut_layout.addWidget(self.btn_shortcut_pan_left, 1, 2)
        shortcut_layout.addWidget(self.btn_shortcut_pan_center, 1, 3)
        shortcut_layout.addWidget(self.btn_shortcut_pan_right, 1, 4)

        shortcut_tip = QLabel("0 自动  1 手动  3 左扫  5 中位  4 右扫")
        shortcut_tip.setObjectName("wifiTip")
        shortcut_tip.setAlignment(Qt.AlignCenter)
        shortcut_layout.addWidget(shortcut_tip, 2, 0, 1, 5)

        control_root.addWidget(control_header)
        control_root.addWidget(self.robot_snapshot_panel)
        control_root.addLayout(self.console_grid)

        log_group = GlassGroup("运行日志")
        log_layout = QVBoxLayout(log_group)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        log_layout.addWidget(self.log_view, 1)

        right_layout.addWidget(hint_group)
        right_layout.addWidget(wifi_group)
        right_layout.addWidget(self.control_group)
        right_layout.addWidget(log_group, 1)

        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setFrameShape(QFrame.NoFrame)
        right_scroll.setWidget(right_card)

        self.body_splitter.addWidget(left_card)
        self.body_splitter.addWidget(right_scroll)
        self.body_splitter.setStretchFactor(0, 3)
        self.body_splitter.setStretchFactor(1, 2)
        self.body_splitter.setSizes([860, 560])

        self.setStyleSheet(
            """
            QMainWindow, QWidget#root {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 rgba(12, 18, 28, 245),
                    stop:0.45 rgba(23, 32, 48, 236),
                    stop:1 rgba(37, 50, 70, 228));
                color: #eef4ff;
                font-family: "PingFang SC", "SF Pro Display", "Hiragino Sans GB", sans-serif;
                font-size: 14px;
            }
            QFrame#hero, QFrame#card, QGroupBox#glassGroup {
                background: rgba(255, 255, 255, 0.08);
                border: 1px solid rgba(255, 255, 255, 0.14);
                border-radius: 24px;
            }
            QFrame#consolePanel {
                background: rgba(6, 14, 26, 0.34);
                border: 1px solid rgba(132, 206, 255, 0.14);
                border-radius: 20px;
            }
            QGroupBox#glassGroup {
                margin-top: 12px;
                padding-top: 18px;
            }
            QGroupBox#glassGroup::title {
                subcontrol-origin: margin;
                left: 18px;
                padding: 0 8px;
                color: #f7fbff;
                font-size: 15px;
                font-weight: 600;
            }
            QLabel#title {
                font-size: 30px;
                font-weight: 700;
                color: #ffffff;
            }
            QLabel#subtitle {
                font-size: 13px;
                color: rgba(239, 245, 255, 0.72);
            }
            QLabel#statusLabel {
                font-size: 14px;
                color: #e7f3ff;
                font-weight: 600;
            }
            QLabel#chipLabel {
                background: rgba(92, 180, 255, 0.12);
                border: 1px solid rgba(130, 208, 255, 0.18);
                border-radius: 13px;
                padding: 8px 12px;
                color: #dff2ff;
                font-weight: 600;
            }
            QLabel#metricValue {
                color: #ffffff;
                font-weight: 600;
            }
            QLabel#wifiTip {
                color: rgba(230, 241, 255, 0.72);
            }
            QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit {
                background: rgba(7, 13, 21, 0.38);
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 14px;
                padding: 9px 12px;
                color: #f7fbff;
                selection-background-color: rgba(99, 179, 255, 0.55);
            }
            QComboBox::drop-down {
                border: none;
                width: 26px;
            }
            QPushButton {
                background: rgba(255, 255, 255, 0.12);
                border: 1px solid rgba(255, 255, 255, 0.14);
                border-radius: 14px;
                padding: 10px 16px;
                color: #ffffff;
                font-weight: 600;
            }
            QPushButton:hover {
                background: rgba(255, 255, 255, 0.18);
            }
            QPushButton:pressed {
                background: rgba(255, 255, 255, 0.09);
            }
            QPushButton[controlRole="dpad"] {
                font-size: 15px;
                border-radius: 18px;
            }
            QPushButton[controlRole="primary"] {
                background: rgba(86, 170, 255, 0.2);
                border: 1px solid rgba(124, 204, 255, 0.25);
                font-size: 16px;
            }
            QPushButton[controlRole="danger"] {
                background: rgba(255, 103, 127, 0.18);
                border: 1px solid rgba(255, 141, 164, 0.26);
                font-size: 15px;
            }
            QPushButton[controlRole="round"] {
                border-radius: 29px;
                font-size: 18px;
                background: rgba(81, 154, 255, 0.16);
                border: 1px solid rgba(126, 201, 255, 0.22);
            }
            QSlider::groove:horizontal {
                height: 8px;
                background: rgba(255, 255, 255, 0.12);
                border-radius: 4px;
            }
            QSlider::sub-page:horizontal {
                background: rgba(114, 203, 255, 0.46);
                border-radius: 4px;
            }
            QSlider::handle:horizontal {
                width: 18px;
                margin: -6px 0;
                border-radius: 9px;
                background: #f3fbff;
                border: 1px solid rgba(255, 255, 255, 0.55);
            }
            QScrollArea {
                background: transparent;
            }
            QMenuBar {
                background: transparent;
                color: #eef4ff;
            }
            QMenuBar::item:selected {
                background: rgba(255, 255, 255, 0.1);
                border-radius: 8px;
            }
            """
        )
        QTimer.singleShot(0, self._relayout_console)
        self._set_board_runtime_snapshot()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._relayout_console()

    def _build_field(self, field):
        field_type = field["type"]
        if field_type == "choice":
            widget = QComboBox()
            widget.addItems(field["choices"])
            return widget
        if field_type == "password":
            widget = QLineEdit()
            widget.setEchoMode(QLineEdit.Password)
            return widget
        if field_type == "text":
            return QLineEdit()
        if field_type == "float":
            widget = QDoubleSpinBox()
            widget.setDecimals(3)
            widget.setSingleStep(field.get("step", 0.01))
            widget.setRange(field.get("min", -999999.0), field.get("max", 999999.0))
            return widget
        widget = QSpinBox()
        widget.setRange(field.get("min", -999999), field.get("max", 999999))
        widget.setSingleStep(field.get("step", 1))
        return widget

    def _relayout_console(self):
        if not hasattr(self, "console_grid"):
            return

        panel_width = self.control_group.width() if hasattr(self, "control_group") else 0
        if panel_width <= 0:
            panel_width = max(0, int(self.width() * 0.42))
        mode = "stack" if panel_width and panel_width < 570 else "wide"
        if mode == self.console_layout_mode:
            return

        self.console_layout_mode = mode
        while self.console_grid.count():
            self.console_grid.takeAt(0)

        if mode == "stack":
            self.console_grid.addWidget(self.drive_panel, 0, 0)
            self.console_grid.addWidget(self.speed_panel, 1, 0)
            self.console_grid.addWidget(self.function_panel, 2, 0)
            self.console_grid.addWidget(self.shortcut_panel, 3, 0)
            self.console_grid.setColumnStretch(0, 1)
            self.console_grid.setColumnStretch(1, 0)
        else:
            self.console_grid.addWidget(self.drive_panel, 0, 0)
            self.console_grid.addWidget(self.function_panel, 0, 1)
            self.console_grid.addWidget(self.speed_panel, 1, 0)
            self.console_grid.addWidget(self.shortcut_panel, 1, 1)
            self.console_grid.setColumnStretch(0, 1)
            self.console_grid.setColumnStretch(1, 1)

    def _auto_fill_firmware(self):
        if self.firmware_edit.text().strip() and Path(self.firmware_edit.text().strip()).exists():
            return
        firmware_path = discover_firmware_bin(auto_download=True)
        if not firmware_path:
            self._append_log("没有在本地或官方源中找到可用的 ESP32 MicroPython 固件 bin。")
            return
        self.firmware_edit.setText(firmware_path)
        self._append_log("已自动定位固件：%s" % firmware_path)

    def _normalized_control_base_url(self) -> str:
        return normalize_control_base_url(self.control_url_edit.text())

    def _persist_control_base_url(self, base_url: str):
        normalized = normalize_control_base_url(base_url)
        self.hidden_profile["CONTROL_BASE_URL"] = normalized
        profile = self._collect_profile()
        profile["CONTROL_BASE_URL"] = normalized
        save_profile(profile)

    def _set_control_base_url(self, base_url: str, persist: bool = True):
        normalized = normalize_control_base_url(base_url)
        if self._normalized_control_base_url() != normalized:
            self.control_url_edit.setText(normalized)
        if persist:
            self._persist_control_base_url(normalized)

    def _set_robot_http_status(self, level: str, title: str, details: str):
        status_name = {
            "online": "connected",
            "legacy": "warning",
            "offline": "disconnected",
            "checking": "busy",
        }.get(level, "disconnected")
        self.robot_http_dot.set_status(status_name)
        self.robot_http_label.setText(title)
        self.robot_http_meta.setText(details)

    def _set_board_runtime_snapshot(
        self,
        board_ip: str = "--",
        network_mode: str = "--",
        control_state: str = "--",
        capture_rate: str = "暂无数据",
        capture_tip: str = "等待板端状态",
    ):
        self.board_ip_value.setText(board_ip or "--")
        self.board_mode_value.setText(network_mode or "--")
        self.board_control_state_value.setText(control_state or "--")
        self.board_capture_rate_value.setText(capture_rate or "暂无数据")
        self.board_capture_tip.setText(capture_tip or "等待板端状态")

    def _set_light_preview(self, mode: str = "--", scene: str = "--", colors=None, tip: str = ""):
        self.board_lights_mode_value.setText(mode or "--")
        self.board_lights_scene_value.setText(scene or "--")
        palette = list(colors or [])
        while len(palette) < 4:
            palette.append("#101820")
        for index, swatch in enumerate(self.board_light_swatches):
            swatch.set_color(palette[index])
        if tip:
            self.board_light_preview_tip.setText(tip)
        elif mode == "影子预览":
            self.board_light_preview_tip.setText("灯效安全回归：当前显示的是桌面影子预览，不会触碰板载 NeoPixel。")
        elif mode == "物理灯":
            self.board_light_preview_tip.setText("当前是物理灯模式。桌面预览颜色会尽量跟随板端场景。")
        else:
            self.board_light_preview_tip.setText("等待板端灯效状态。")

    def _current_control_host(self) -> str:
        return self._normalized_control_base_url().split("://", 1)[-1]

    def _robot_discovery_hosts(self) -> list[str]:
        values = []
        seen = set()
        for raw_value in (
            self._current_control_host(),
            self.board_ip_value.text().strip(),
            self.last_announced_board_host,
            self.last_discovered_board_url,
        ):
            host = str(raw_value or "").strip()
            if not host:
                continue
            if "://" in host:
                host = host.split("://", 1)[-1]
            host = host.split("/", 1)[0].strip()
            if ":" in host:
                host = host.split(":", 1)[0].strip()
            if not host or host in seen:
                continue
            seen.add(host)
            values.append(host)
        return values

    def _friendly_network_mode(self, network_mode: str) -> str:
        mapping = {
            "station": "局域网",
            "ap": "热点",
            "ap_fallback": "AP 备用",
            "apsta": "AP+局域网",
        }
        return mapping.get(network_mode, network_mode or "--")

    def _friendly_control_state(self, summary: dict) -> str:
        mode = str(summary.get("mode") or "--")
        auto_state = str(summary.get("auto_state") or "idle")
        state_map = {
            "idle": "待机",
            "search": "搜索",
            "track": "跟踪",
            "ram": "撞球",
            "recover": "恢复",
        }
        if mode == "manual":
            if summary.get("captured_ball"):
                return "手动 · 已持球"
            return "手动"
        if mode == "auto":
            if summary.get("auto_paused"):
                return "自动 · 刹停"
            return "自动 · %s" % state_map.get(auto_state, auto_state)
        return mode

    def _friendly_capture_metrics(self, summary: dict):
        count = int(summary.get("recent_capture_count") or 0)
        successes = int(summary.get("recent_capture_successes") or 0)
        window = int(summary.get("recent_capture_window") or count or 0)
        rate = summary.get("recent_capture_rate")
        last_capture_success = summary.get("last_capture_success")

        if last_capture_success is True:
            last_result_text = "上次抓球成功"
        elif last_capture_success is False:
            last_result_text = "上次抓球失败"
        else:
            last_result_text = "还没有抓球记录"

        if count <= 0 or rate is None:
            return "暂无数据", last_result_text

        rate_value = float(rate)
        if abs(rate_value - int(rate_value)) < 0.05:
            rate_text = "%d%%" % int(round(rate_value))
        else:
            rate_text = "%.1f%%" % rate_value
        capture_value = "%s (%d/%d)" % (rate_text, successes, count)
        capture_tip = "最近 %d 次窗口统计 | %s" % (window or count, last_result_text)
        return capture_value, capture_tip

    def _is_using_robot_ap_target(self) -> bool:
        host = self._current_control_host().split(":", 1)[0]
        return host == "192.168.4.1"

    def _same_robot_ap_subnet(self) -> bool:
        local_ip = str(self.wifi_info.get("ip") or "").strip()
        return bool(local_ip.startswith("192.168.4."))

    def _ap_fallback_hint(self) -> str:
        ap_name = self.hidden_profile.get("AP_SSID") or "KS5002-SoccerBot"
        if self._same_robot_ap_subnet():
            return "当前正在使用机器人热点网段，板端状态接口暂无响应，可能是主程序还没完全启动。"
        return "当前 Mac 没有连接到机器人热点 %s；若板子走 AP 备用模式，需先切到这个热点后才能访问 192.168.4.1。" % ap_name

    def _maybe_start_robot_discovery(self, force: bool = False):
        local_ip = str(self.wifi_info.get("ip") or "").strip()
        if not local_ip or local_ip.startswith("192.168.4."):
            return
        if self.robot_discovery_worker is not None and self.robot_discovery_worker.isRunning():
            return
        now = time.monotonic()
        if not force and now - self.last_robot_discovery_at < 15.0:
            return

        self.last_robot_discovery_at = now
        self._append_log("正在扫描当前热点网段，自动查找小车 IP…")
        self.robot_discovery_worker = RobotDiscoveryThread(local_ip, prefer_hosts=self._robot_discovery_hosts())
        self.robot_discovery_worker.done.connect(self._on_robot_discovery_done)
        self.robot_discovery_worker.start()

    def _on_robot_discovery_done(self, found: bool, base_url: str, details: str):
        if self.robot_discovery_worker is not None:
            self.robot_discovery_worker.wait(2500)
            self.robot_discovery_worker.deleteLater()
            self.robot_discovery_worker = None

        if not found:
            self._append_log(details)
            return

        self.last_discovered_board_url = normalize_control_base_url(base_url)
        self._append_log("已在当前热点网段发现板子：%s" % self.last_discovered_board_url)
        self._set_control_base_url(self.last_discovered_board_url, persist=True)
        QTimer.singleShot(60, self.poll_robot_status)

    def poll_robot_status(self):
        if self.worker is not None:
            return
        if self.robot_status_request_inflight or (
            self.robot_status_worker is not None and self.robot_status_worker.isRunning()
        ):
            self.robot_status_pending = True
            return
        status_url = self._normalized_control_base_url() + "/status"
        self.robot_status_request_inflight = True
        self.robot_status_pending = False
        self._set_robot_http_status("checking", "正在检测 WLAN 端口", status_url)
        self.robot_status_worker = RobotStatusThread(status_url)
        self.robot_status_worker.done.connect(self._on_robot_status_reply)
        self.robot_status_worker.start()

    def _on_robot_status_reply(self, request_url: str, ok: bool, status_code: int, payload: str):
        self.robot_status_request_inflight = False
        current_status_url = self._normalized_control_base_url() + "/status"
        if self.robot_status_worker is not None:
            self.robot_status_worker.wait(2500)
            self.robot_status_worker.deleteLater()
            self.robot_status_worker = None

        if request_url != current_status_url:
            self.robot_status_pending = True

        if not ok:
            if request_url == current_status_url:
                hint = "板端状态接口暂无响应"
                detail_hint = payload
                if self._is_using_robot_ap_target():
                    hint = self._ap_fallback_hint()
                    detail_hint = "%s\n%s" % (payload, hint)
                self._set_board_runtime_snapshot(
                    board_ip=self._current_control_host(),
                    network_mode="未连通",
                    control_state="--",
                    capture_rate="--",
                    capture_tip=hint,
                )
                self._set_light_preview(mode="未连通", scene="--", colors=None, tip="等待板端灯效状态。")
                self._set_robot_http_status(
                    "offline",
                    "板端 WLAN 未连通",
                    "%s\nHTTP 端口没有响应，可能是小车未启动、未入网，或当前地址不对。\n%s" % (request_url, detail_hint),
                )
                self._maybe_start_robot_discovery(force=self._is_using_robot_ap_target())
            if self.robot_status_pending:
                QTimer.singleShot(50, self.poll_robot_status)
            return

        if request_url != current_status_url:
            if self.robot_status_pending:
                QTimer.singleShot(50, self.poll_robot_status)
            return

        try:
            data = json.loads(payload)
        except Exception:
            data = None

        if isinstance(data, dict) and data.get("ok"):
            summary = data.get("summary") or {}
            mode_text = summary.get("mode", "--")
            auto_state = summary.get("auto_state", "--")
            board_ip = data.get("ip_address", "")
            network_mode = data.get("network_mode", "")
            relay_online = bool(data.get("relay_online"))
            lights_mode_raw = str(summary.get("lights_mode") or "").strip()
            lights_scene = str(summary.get("lights_scene") or "--")
            lights_hw_enabled = bool(summary.get("lights_hw_enabled"))
            lights_guard_state = str(summary.get("lights_guard_state") or "").strip()
            lights_preview = summary.get("lights_preview") or []
            control_state_text = self._friendly_control_state(summary)
            capture_rate_text, capture_tip = self._friendly_capture_metrics(summary)
            details = "HTTP %s 已开放 | IP %s | 网络 %s | 模式 %s | 状态 %s" % (
                status_code or 200,
                board_ip or "--",
                network_mode or "--",
                mode_text,
                auto_state,
            )
            if relay_online:
                details += " | 中继在线"
            self._set_robot_http_status("online", "板端 WLAN 在线", details)
            self._set_board_runtime_snapshot(
                board_ip=board_ip or self._current_control_host(),
                network_mode=self._friendly_network_mode(network_mode),
                control_state=control_state_text,
                capture_rate=capture_rate_text,
                capture_tip=capture_tip,
            )
            if lights_hw_enabled:
                lights_mode_text = "物理灯"
            elif lights_mode_raw == "guarded":
                if lights_guard_state == "warming":
                    lights_mode_text = "护航预热"
                elif lights_guard_state == "cooldown":
                    lights_mode_text = "护航隔离"
                elif lights_guard_state == "locked":
                    lights_mode_text = "护航锁定"
                else:
                    lights_mode_text = "护航待机"
            elif lights_mode_raw == "shadow":
                lights_mode_text = "影子预览"
            else:
                lights_mode_text = lights_mode_raw or "未启用"
            self._set_light_preview(mode=lights_mode_text, scene=lights_scene, colors=lights_preview)
            if board_ip:
                normalized = self._normalized_control_base_url()
                current_host = normalized.split("://", 1)[-1]
                board_url = normalize_control_base_url("http://%s:%s" % (board_ip, data.get("port", 80)))
                board_host = board_url.split("://", 1)[-1]
                self.last_announced_board_host = board_host
                self.last_discovered_board_url = board_url
                if data.get("network_mode") == "station" and not relay_online:
                    current_host_only = current_host.split(":", 1)[0]
                    if current_host_only != board_ip:
                        self._append_log("检测到板子已加入热点/局域网，已自动切换控制地址：%s" % board_host)
                        self._set_control_base_url(board_url, persist=True)
            if self.robot_status_pending:
                QTimer.singleShot(50, self.poll_robot_status)
            return

        self._set_robot_http_status(
            "legacy",
            "HTTP 端口已开",
            "%s\n收到非 JSON 响应，说明端口在线，但当前固件还没暴露状态接口。" % request_url,
        )
        self._set_board_runtime_snapshot(
            board_ip=self._current_control_host(),
            network_mode="在线但固件旧",
            control_state="状态接口缺失",
            capture_rate="--",
            capture_tip="端口已打开，重烧当前主程序后才会显示实时抓球统计。",
        )
        self._set_light_preview(mode="旧固件", scene="--", colors=None, tip="当前固件还没暴露灯效预览状态。")
        if self.robot_status_pending:
            QTimer.singleShot(50, self.poll_robot_status)

    def _refresh_permission_summary(self):
        if macos_permissions is None or not macos_permissions.is_available():
            self.permission_summary_value.setText("当前环境不支持")
            return
        status = macos_permissions.location_status()
        if not status.get("packaged_app"):
            self.permission_summary_value.setText("脚本模式，系统弹窗不稳定")
            return
        if not status.get("bundle_has_usage_description"):
            self.permission_summary_value.setText("App 缺少定位说明")
            return
        if status.get("name") == "authorized_when_in_use":
            self.permission_summary_value.setText("App 已获定位权限")
            return
        if status.get("name") == "authorized_always":
            self.permission_summary_value.setText("App 已获持续定位权限")
            return
        if status.get("name") == "denied":
            self.permission_summary_value.setText("定位权限被拒绝")
            return
        self.permission_summary_value.setText("可请求系统权限")

    def _open_privacy_settings(self):
        if macos_permissions is None or not macos_permissions.is_available():
            QMessageBox.information(self, "当前不可用", "当前环境没有可用的 macOS 原生权限接口。")
            return
        ok = macos_permissions.open_privacy_settings("location")
        if ok:
            self._append_log("已尝试打开 macOS 隐私设置。")
        else:
            QMessageBox.warning(self, "打开失败", "没能打开系统隐私设置。")

    def _request_native_permissions(self):
        if macos_permissions is None or not macos_permissions.is_available():
            QMessageBox.information(self, "当前不可用", "当前环境没有可用的 macOS 原生权限接口。")
            return
        status = macos_permissions.location_status()
        self._refresh_permission_summary()
        if not status.get("packaged_app"):
            QMessageBox.information(
                self,
                "请使用 .app",
                "当前还是脚本模式，macOS 原生权限弹窗不稳定。\n请优先运行打包后的 .app 再点这个按钮。",
            )
            return
        if not status.get("bundle_has_usage_description"):
            QMessageBox.warning(self, "配置不完整", "这个 App 包里缺少定位用途说明，系统不会正常弹权限框。")
            return
        macos_permissions.request_location_permission()
        self._append_log("已请求系统定位权限；如果 macOS 弹出原生权限框，请选择允许。")
        QTimer.singleShot(2200, self._refresh_after_permission_prompt)

    def _refresh_after_permission_prompt(self):
        self.refresh_wifi_status(fill_missing=True)
        self._refresh_permission_summary()

    def _wifi_ssid_field(self):
        return self.form_widgets["STA_SSID"][1]

    def _wifi_password_field(self):
        return self.form_widgets["STA_PASSWORD"][1]

    def _set_wifi_field_lock_state(self, ssid_locked: bool, password_locked: bool):
        ssid_field = self._wifi_ssid_field()
        password_field = self._wifi_password_field()
        ssid_field.setEnabled(not ssid_locked)
        password_field.setEnabled(not password_locked)
        ssid_field.setPlaceholderText("自动检测不到时可手动输入 Wi-Fi 名称")
        password_field.setPlaceholderText("自动检测不到时可手动输入 Wi-Fi 密码")
        if ssid_locked:
            ssid_field.setToolTip("已自动检测到当前 Wi-Fi 名称，已锁定。")
        else:
            ssid_field.setToolTip("当前没有自动拿到 SSID，可手动输入。")
        if password_locked:
            password_field.setToolTip("已自动检测到当前 Wi-Fi 密码，已锁定。")
        else:
            password_field.setToolTip("当前没有自动拿到密码，可手动输入。")

    def _request_wifi_password_from_system(self):
        if macos_permissions is None or not macos_permissions.is_available():
            QMessageBox.information(self, "当前不可用", "当前环境没有可用的 macOS 原生权限接口。")
            return
        ssid = self._wifi_ssid_field().text().strip() or self.hidden_profile.get("STA_SSID") or self.wifi_info.get("ssid") or ""
        if not ssid:
            self.refresh_wifi_status(fill_missing=True)
            ssid = self._wifi_ssid_field().text().strip() or self.hidden_profile.get("STA_SSID") or self.wifi_info.get("ssid") or ""
        if not ssid:
            QMessageBox.information(
                self,
                "还没拿到 Wi-Fi 名称",
                "请先点“请求系统权限”，等系统放开定位后，再读取系统保存的 Wi-Fi 密码。",
            )
            return

        result_holder = {}

        def _task(logger=None):
            if logger is not None:
                logger("正在向系统钥匙串请求 %s 的 Wi-Fi 密码..." % ssid)
            result = macos_permissions.request_wifi_password(ssid)
            result_holder["result"] = result
            if not result.get("ok"):
                raise RuntimeError("系统未返回 Wi-Fi 密码：%s (%s)" % (result.get("status"), result.get("code")))
            if logger is not None:
                logger("系统已返回 Wi-Fi 密码。")

        def _success(_message: str):
            password = result_holder.get("result", {}).get("password", "")
            if password:
                self._wifi_password_field().setText(password)
                self._set_wifi_field_lock_state(
                    ssid_locked=bool(self._wifi_ssid_field().text().strip()),
                    password_locked=True,
                )
                self._append_log("已自动写入系统返回的 Wi-Fi 密码。")

        def _failure(_message: str):
            self._append_log("这次没有从系统钥匙串拿到 Wi-Fi 密码。")

        self._run_worker(_task, on_success=_success, on_failure=_failure, task_kind="wifi_password")

    def _apply_wifi_info_to_fields(self, info: dict, fill_missing: bool):
        ssid_field = self._wifi_ssid_field()
        password_field = self._wifi_password_field()
        detected_ssid = str(info.get("ssid", "") or "")
        detected_password = str(info.get("password", "") or "")

        if info.get("ssid_visible"):
            self.hidden_profile["STA_SSID"] = detected_ssid
            ssid_field.setText(detected_ssid)
        elif fill_missing and not ssid_field.text().strip() and self.hidden_profile.get("STA_SSID"):
            ssid_field.setText(str(self.hidden_profile.get("STA_SSID", "")))

        if info.get("password_available"):
            password_field.setText(detected_password)

        self._set_wifi_field_lock_state(
            ssid_locked=bool(info.get("ssid_visible") and detected_ssid),
            password_locked=bool(info.get("password_available") and detected_password),
        )

    def refresh_wifi_status(self, fill_missing: bool = False, attempt_password: bool = False):
        info = detect_wifi_environment(include_password=attempt_password)
        self.wifi_info = info
        self._refresh_permission_summary()
        manual_ssid = self._wifi_ssid_field().text().strip()
        manual_password = self._wifi_password_field().text().strip()
        self.wifi_state_value.setText(
            {
                "ready": "已就绪",
                "needs_password": "待补密码",
                "needs_manual": "待手填",
                "offline": "未连接",
                "unavailable": "不可用",
            }.get(info.get("status"), "未知")
        )
        self.wifi_iface_value.setText(info.get("interface") or "--")
        self.wifi_ip_value.setText(info.get("ip") or "--")
        display_ssid = info.get("ssid") or manual_ssid or self.hidden_profile.get("STA_SSID", "")
        if info.get("ssid_visible") and info.get("ssid"):
            self.hidden_profile["STA_SSID"] = str(info.get("ssid", ""))
        if display_ssid:
            self.wifi_ssid_value.setText(display_ssid)
        elif info.get("ssid_hidden"):
            self.wifi_ssid_value.setText("系统已隐藏")
        else:
            self.wifi_ssid_value.setText("未读取到")
        if info.get("password_available"):
            self.wifi_password_value.setText("已自动读取")
        elif manual_password:
            self.wifi_password_value.setText("已手动填写")
        elif attempt_password and info.get("connected"):
            self.wifi_password_value.setText("未读取到，请手动输入")
        else:
            self.wifi_password_value.setText("出于安全限制，可能需手动输入")
        self.wifi_message.setText(
            info.get("message") or "SSID 和密码支持自动探测；自动成功时会锁定输入框，探测不到时可手动填写。"
        )
        self.local_ip_chip.setText("本机 Wi-Fi IP: %s" % (info.get("ip") or "--"))
        self._apply_wifi_info_to_fields(info, fill_missing=fill_missing)

    def _sync_wifi_to_profile(self):
        self.refresh_wifi_status(fill_missing=True, attempt_password=True)
        ssid_text = self._wifi_ssid_field().text().strip()
        password_text = self._wifi_password_field().text().strip()
        profile = self._collect_profile()
        save_profile(profile)
        if not ssid_text:
            self._append_log("已保存你手动填写的 Wi-Fi 密码，但当前仍没拿到 SSID；这次烧录后板子会走机器人热点。")
            QMessageBox.information(
                self,
                "已保存密码，但还缺 Wi-Fi 名称",
                "密码已经同步到板子参数。\n\n但当前没有拿到路由器 SSID，所以 ESP32 不能加入家里局域网，只会启用热点 %s。\n如果你要访问 192.168.4.1，请先让 Mac 或手机连接这个热点。"
                % (profile.get("AP_SSID") or "KS5002-SoccerBot"),
            )
            return
        if not password_text:
            self._append_log("已经同步当前 Wi-Fi 名称，但密码还是空的；如果路由器有密码，请先手动填写再烧录。")
            QMessageBox.information(
                self,
                "还缺 Wi-Fi 密码",
                "当前已经拿到 Wi-Fi 名称，但密码还是空的。\n请在左侧输入框填上密码，再重新烧录主程序。",
            )
            return
        if self.wifi_info.get("password_available"):
            self._append_log("已同步当前 Wi-Fi 信息到板子参数区，密码来源：系统自动读取。")
        else:
            self._append_log("已同步当前 Wi-Fi 信息到板子参数区，密码来源：手动输入。")

    def _append_log(self, text: str):
        if not text:
            return
        self.log_view.appendPlainText(text)
        scrollbar = self.log_view.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _load_profile(self):
        profile = load_saved_profile()
        self.hidden_profile = dict(profile)
        for key, (field, widget) in self.form_widgets.items():
            value = profile.get(key)
            if field["type"] == "choice":
                index = widget.findText(str(value))
                if index >= 0:
                    widget.setCurrentIndex(index)
            elif field["type"] in ("text", "password"):
                widget.setText(str(value))
            else:
                widget.setValue(value)
        self.control_url_edit.setText(str(profile.get("CONTROL_BASE_URL", "http://192.168.4.1")))
        if "MANUAL_SPEED" in profile:
            speed_value = int(max(0, min(255, profile["MANUAL_SPEED"] // 4)))
            self.speed_left_slider.setValue(speed_value)
            self.speed_right_slider.setValue(speed_value)
        self.firmware_edit.setText(str(profile.get("LAST_FIRMWARE_PATH", "")))
        self.flash_firmware_checkbox.setChecked(bool(profile.get("FLASH_FIRMWARE", False)))
        self._refresh_presets()

    def _collect_profile(self) -> dict:
        data = load_saved_profile()
        data.update(self.hidden_profile)
        for key, (field, widget) in self.form_widgets.items():
            field_type = field["type"]
            if field_type == "choice":
                data[key] = widget.currentText()
            elif field_type in ("text", "password"):
                data[key] = widget.text()
            elif field_type == "float":
                data[key] = float(widget.value())
            else:
                data[key] = int(widget.value())
        data["CONTROL_BASE_URL"] = self.control_url_edit.text().strip() or "http://192.168.4.1"
        data["LAST_FIRMWARE_PATH"] = self.firmware_edit.text().strip()
        data["FLASH_FIRMWARE"] = bool(self.flash_firmware_checkbox.isChecked())
        return data

    def _save_profile_clicked(self):
        profile = self._collect_profile()
        save_profile(profile)
        self._append_log("已保存本机参数到 .studio_profile.json")

    def _refresh_presets(self):
        current = self.preset_combo.currentText()
        self.preset_combo.clear()
        self.preset_combo.addItems(list_presets())
        index = self.preset_combo.findText(current)
        if index >= 0:
            self.preset_combo.setCurrentIndex(index)

    def _apply_profile(self, profile: dict):
        self.hidden_profile.update(profile)
        for key, (field, widget) in self.form_widgets.items():
            if key not in profile:
                continue
            value = profile[key]
            if field["type"] == "choice":
                index = widget.findText(str(value))
                if index >= 0:
                    widget.setCurrentIndex(index)
            elif field["type"] in ("text", "password"):
                widget.setText(str(value))
            else:
                widget.setValue(value)
        self.control_url_edit.setText(str(profile.get("CONTROL_BASE_URL", "http://192.168.4.1")))
        self.firmware_edit.setText(str(profile.get("LAST_FIRMWARE_PATH", self.firmware_edit.text().strip())))
        self.flash_firmware_checkbox.setChecked(bool(profile.get("FLASH_FIRMWARE", False)))
        if "MANUAL_SPEED" in profile:
            speed_value = int(max(0, min(255, int(profile["MANUAL_SPEED"]) // 4)))
            self.speed_left_slider.setValue(speed_value)
            self.speed_right_slider.setValue(speed_value)
        self.refresh_wifi_status(fill_missing=False)

    def _save_named_preset_clicked(self):
        profile = self._collect_profile()
        name, ok = QInputDialog.getText(self, "保存预设", "输入预设名称")
        if not ok or not name.strip():
            return
        save_named_preset(name.strip(), profile)
        self._refresh_presets()
        self._append_log("已保存预设：%s" % name.strip())

    def _load_selected_preset(self):
        name = self.preset_combo.currentText().strip()
        if not name:
            QMessageBox.information(self, "暂无预设", "请先保存一个参数预设。")
            return
        profile = load_named_preset(name)
        self._apply_profile(profile)
        self._append_log("已加载预设：%s" % name)

    def _delete_selected_preset(self):
        name = self.preset_combo.currentText().strip()
        if not name:
            return
        delete_named_preset(name)
        self._refresh_presets()
        self._append_log("已删除预设：%s" % name)

    def _browse_firmware(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择 ESP32 固件", str(Path.home()), "固件 (*.bin);;所有文件 (*)")
        if path:
            self.firmware_edit.setText(path)
            self._append_log("已选择固件：%s" % path)

    def _send_http_path(self, path: str):
        base_url = self._normalized_control_base_url()
        url = base_url + path
        try:
            with open_url(url, timeout=2.5) as response:
                body = response.read().decode(errors="ignore").strip()
        except urllib.error.URLError as exc:
            fallback_url = ""
            if self.last_discovered_board_url and self.last_discovered_board_url != base_url:
                fallback_url = self.last_discovered_board_url
            elif self.board_ip_value.text().strip() not in ("", "--"):
                fallback_url = normalize_control_base_url("http://%s" % self.board_ip_value.text().strip())

            if fallback_url and fallback_url != base_url:
                retry_url = fallback_url + path
                try:
                    with open_url(retry_url, timeout=2.5) as response:
                        body = response.read().decode(errors="ignore").strip()
                    self._append_log("控制地址已自动切换到：%s" % fallback_url)
                    self._set_control_base_url(fallback_url, persist=True)
                    self._append_log("控制请求：%s -> %s" % (path, body or "ok"))
                    return
                except Exception:
                    pass
            QMessageBox.warning(
                self,
                "控制失败",
                "无法访问 %s\n%s\n\n可能原因：\n1. 板子还没完成烧录或启动\n2. 当前地址不是 192.168.4.1\n3. 板子已经加入局域网，地址变了"
                % (url, exc),
            )
            return
        self._append_log("控制请求：%s -> %s" % (path, body or "ok"))

    def _selected_port(self) -> str | None:
        device = self.port_combo.currentData()
        if device:
            return str(device)
        try:
            return detect_port(None)
        except SystemExit:
            return None

    def _set_busy(self, busy: bool):
        if busy:
            if hasattr(self, "port_timer"):
                self.port_timer.stop()
            if hasattr(self, "wifi_timer"):
                self.wifi_timer.stop()
            if hasattr(self, "robot_status_timer"):
                self.robot_status_timer.stop()
        else:
            if hasattr(self, "port_timer") and not self.port_timer.isActive():
                self.port_timer.start(1200)
            if hasattr(self, "wifi_timer") and not self.wifi_timer.isActive():
                self.wifi_timer.start(8000)
            if hasattr(self, "robot_status_timer") and not self.robot_status_timer.isActive():
                self.robot_status_timer.start(2200)
        for widget in (
            self.deploy_main_button,
            self.deploy_test_button,
            self.quick_check_button,
            self.save_profile_button,
            self.load_preset_button,
            self.save_preset_button,
            self.delete_preset_button,
            self.refresh_button,
            self.auto_firmware_button,
            self.flash_firmware_checkbox,
            self.wifi_detect_button,
            self.wifi_sync_button,
            self.wifi_permission_button,
            self.wifi_password_button,
            self.open_settings_button,
            self.robot_refresh_button,
        ):
            widget.setEnabled(not busy)
        self.status_dot.set_status("busy" if busy else ("connected" if self._selected_port() else "disconnected"))

    def refresh_ports(self):
        current = self.port_combo.currentData()
        self.port_infos = list_serial_ports_info()

        self.port_combo.blockSignals(True)
        self.port_combo.clear()
        for info in self.port_infos:
            label = "%s  ·  %s" % (info["device"], info["description"] or "未知设备")
            self.port_combo.addItem(label, info["device"])
        self.port_combo.blockSignals(False)

        selected_index = -1
        if current:
            for index, info in enumerate(self.port_infos):
                if info["device"] == current:
                    selected_index = index
                    break
        elif self.port_infos:
            selected_index = 0

        if selected_index >= 0:
            self.port_combo.setCurrentIndex(selected_index)

        self._update_port_hint()

    def _update_port_hint(self):
        device = self.port_combo.currentData()
        if not self.port_infos or not device:
            self.status_dot.set_status("disconnected")
            self.status_label.setText("未发现 ESP32 串口")
            self.port_hint.setText("请接入 ESP32 后等待自动检测，或手动点击“刷新串口”。")
            return

        for info in self.port_infos:
            if info["device"] == device:
                status = "connected" if info["is_likely_esp32"] else "warning"
                self.status_dot.set_status(status)
                self.status_label.setText("已检测到设备：%s" % device)
                self.port_hint.setText(
                    "当前串口：%s\n描述：%s\n制造商：%s\nHWID：%s"
                    % (
                        info["device"],
                        info["description"] or "未知",
                        info["manufacturer"] or "未知",
                        info["hwid"] or "未知",
                    )
                )
                return

    def _run_worker(self, fn, *args, on_success=None, on_failure=None, task_kind="generic", **kwargs):
        if self.worker is not None and self.worker.isRunning():
            QMessageBox.information(self, "请稍候", "当前已有任务正在运行，请先等待完成。")
            return
        self.worker_success_handler = on_success
        self.worker_failure_handler = on_failure
        self.worker_kind = task_kind
        self.worker = WorkerThread(fn, *args, **kwargs)
        self.worker.log.connect(self._append_log)
        self.worker.done.connect(self._on_worker_done)
        self._set_busy(True)
        self.worker.start()

    def _on_worker_done(self, success: bool, message: str):
        self._set_busy(False)
        self._append_log(message)
        if self.worker is not None:
            self.worker.wait(2500)
            self.worker.deleteLater()
            self.worker = None
        success_handler = self.worker_success_handler
        failure_handler = self.worker_failure_handler
        worker_kind = self.worker_kind
        self.worker_success_handler = None
        self.worker_failure_handler = None
        self.worker_kind = ""
        if success:
            if callable(success_handler):
                success_handler(message)
            if self.pending_control_hint:
                self._append_log(self.pending_control_hint)
            if worker_kind == "deploy":
                QTimer.singleShot(3500, self.poll_robot_status)
            QMessageBox.information(self, "完成", message)
        else:
            if callable(failure_handler):
                failure_handler(message)
            if worker_kind == "deploy":
                self._append_log("这次上传没有完整完成，所以板子端 HTTP 服务可能还没起来；此时访问 192.168.4.1 超时是正常现象。")
            QMessageBox.critical(self, "失败", message)
        self.pending_control_hint = ""

    def _after_deploy_success(self, port: str):
        try:
            snapshot = board_network_snapshot(port)
            soft_reset(port)
        except Exception as exc:
            self._append_log("烧录后未能立即读到板端网络快照：%s" % exc)
            return

        network_mode = snapshot.get("network_mode") or "offline"
        ip_address = snapshot.get("ip_address") or ""
        self._append_log("板端网络快照：%s %s" % (network_mode, ip_address or "0.0.0.0"))
        if ip_address and ip_address != "0.0.0.0":
            base_url = normalize_control_base_url("http://%s:%s" % (ip_address, snapshot.get("port", 80)))
            self.last_discovered_board_url = base_url
        mqtt_host = str(self.hidden_profile.get("MQTT_BROKER_HOST") or "").strip()
        if mqtt_host:
            if ensure_local_bridge(logger=self._append_log):
                local_url = "http://127.0.0.1:8765"
                self._append_log("已启用热点 MQTT 本地桥：%s" % local_url)
                self._set_control_base_url(local_url, persist=True)
            return
        relay_raw = str(self.hidden_profile.get("RELAY_BASE_URL") or "").strip()
        relay_url = normalize_control_base_url(relay_raw) if relay_raw else ""
        if relay_url:
            self._append_log("已启用热点中继控制地址：%s" % relay_url)
            self._set_control_base_url(relay_url, persist=True)
        elif ip_address and ip_address != "0.0.0.0":
            self._set_control_base_url(self.last_discovered_board_url, persist=True)

    def _start_deploy(self, boot_mode: str):
        port = self._selected_port()
        if not port:
            QMessageBox.warning(self, "未检测到设备", "没有找到可用的 ESP32 串口。")
            return
        attempt_password = not self.form_widgets["STA_PASSWORD"][1].text().strip()
        self.refresh_wifi_status(fill_missing=True, attempt_password=attempt_password)
        profile = self._collect_profile()
        save_profile(profile)
        firmware = self.firmware_edit.text().strip() or None
        if not self.flash_firmware_checkbox.isChecked():
            firmware = None
        if not profile.get("STA_SSID"):
            self._append_log("提示：当前没有自动拿到 Wi-Fi 名称，已先完成烧录；后续如果要让小车进局域网，需要系统成功识别当前网络名。")
        if not profile.get("STA_PASSWORD"):
            self._append_log("提示：当前没有自动拿到 Wi-Fi 密码；如果你要让 ESP32 连路由器，请手动填写后再烧录。")
        if self.flash_firmware_checkbox.isChecked():
            self._append_log("这次会先刷固件，再上传项目文件。")
        else:
            self._append_log("这次只上传主程序文件，不重刷固件。")
        title = "主程序" if boot_mode == "main" else "自检模式"
        self._append_log("准备烧录：%s -> %s" % (title, port))
        if profile.get("STA_SSID"):
            self.pending_control_hint = "烧录完成后，如果 192.168.4.1 不通，说明板子更可能已经加入局域网，请查看路由器分配地址。"
        else:
            self.pending_control_hint = "当前没有 SSID，板子会开热点 %s；若要访问 http://192.168.4.1 ，请先让 Mac 或手机连上这个热点。" % (
                profile.get("AP_SSID") or "KS5002-SoccerBot"
            )
        self._run_worker(
            deploy_runtime,
            port,
            boot_mode,
            profile,
            firmware,
            on_success=lambda _message, port_value=port: self._after_deploy_success(port_value),
            task_kind="deploy",
        )

    def _quick_self_check(self):
        port = self._selected_port()
        if not port:
            QMessageBox.warning(self, "未检测到设备", "没有找到可用的 ESP32 串口。")
            return
        profile = self._collect_profile()
        save_profile(profile)

        def _task(port_value: str, logger=None):
            output = board_exec(port_value, "import self_test; self_test.self_check()", logger=logger)
            if logger is not None:
                logger("板端自检输出：\n%s" % (output or "<empty>"))

        self._append_log("开始执行板端快速自检...")
        self._run_worker(_task, port, task_kind="board_exec")

    def closeEvent(self, event):
        for timer_name in ("port_timer", "wifi_timer", "robot_status_timer"):
            timer = getattr(self, timer_name, None)
            if timer is not None and timer.isActive():
                timer.stop()

        if self.worker is not None and self.worker.isRunning():
            waited = self.worker.wait(8000)
            if not waited:
                QMessageBox.information(
                    self,
                    "任务仍在执行",
                    "当前还有烧录或自检任务正在运行。\n请等待它完成后再退出，避免中断上传。",
                )
                event.ignore()
                return

        if self.robot_status_worker is not None and self.robot_status_worker.isRunning():
            self.robot_status_worker.wait(2500)
        if self.robot_discovery_worker is not None and self.robot_discovery_worker.isRunning():
            self.robot_discovery_worker.wait(2500)

        if self.worker is not None:
            self.worker.deleteLater()
            self.worker = None
        if self.robot_status_worker is not None:
            self.robot_status_worker.deleteLater()
            self.robot_status_worker = None
        if self.robot_discovery_worker is not None:
            self.robot_discovery_worker.deleteLater()
            self.robot_discovery_worker = None

        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("KS5002 智控烧录台")
    window = StudioWindow()
    screen = QGuiApplication.primaryScreen()
    if screen is not None:
        area = screen.availableGeometry()
        width = max(980, min(int(area.width() * 0.92), 1680))
        height = max(700, min(int(area.height() * 0.9), 1120))
        window.resize(width, height)
        if area.width() < 1450 or area.height() < 860:
            window.showMaximized()
        else:
            window.show()
    else:
        window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
