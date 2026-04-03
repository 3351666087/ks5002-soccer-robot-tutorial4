from __future__ import annotations

import json
import queue
import signal
import sys
import threading
import time
from pathlib import Path

from PySide6.QtCore import QTimer, Qt, QUrl
from PySide6.QtGui import QAction, QFont, QGuiApplication
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkProxy, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


TOOLS_DIR = Path(__file__).resolve().parent / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from common import (  # noqa: E402
    detect_wifi_environment,
    discover_robot_on_subnet,
    ensure_local_bridge,
    load_saved_profile,
    normalize_control_base_url,
    open_url,
    save_profile,
)


class StatusDot(QLabel):
    def __init__(self):
        super().__init__()
        self.setFixedSize(16, 16)
        self.set_status("offline")

    def set_status(self, state: str):
        colors = {
            "online": "#2cb36d",
            "busy": "#f2a93b",
            "offline": "#df6b67",
        }
        color = colors.get(state, "#8799ad")
        self.setStyleSheet(
            "border-radius: 8px; background: %s; border: 1px solid rgba(255,255,255,0.72);" % color
        )


class GlassCard(QFrame):
    def __init__(self, title: str, subtitle: str = ""):
        super().__init__()
        self.setObjectName("glassCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("cardTitle")
        layout.addWidget(self.title_label)

        if subtitle:
            self.subtitle_label = QLabel(subtitle)
            self.subtitle_label.setObjectName("cardSubtitle")
            self.subtitle_label.setWordWrap(True)
            layout.addWidget(self.subtitle_label)
        else:
            self.subtitle_label = None

        self.body = QVBoxLayout()
        self.body.setSpacing(12)
        layout.addLayout(self.body, 1)


class MotionButton(QPushButton):
    def __init__(self, text: str, accent: str):
        super().__init__(text)
        self._accent = accent
        self._active = False
        self.setMinimumHeight(88)
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setFocusPolicy(Qt.NoFocus)
        self._apply_style()

    def set_active(self, active: bool):
        active = bool(active)
        if self._active == active:
            return
        self._active = active
        self._apply_style()

    def _apply_style(self):
        fill = "0.90" if self._active else "0.68"
        border = self._accent if self._active else "rgba(255,255,255,0.82)"
        self.setStyleSheet(
            """
            QPushButton {
                border-radius: 24px;
                border: 1px solid %s;
                background: rgba(255,255,255,%s);
                color: #17324d;
                font-size: 21px;
                font-weight: 700;
                padding: 14px;
            }
            QPushButton:pressed {
                background: rgba(238,243,248,0.96);
                padding-top: 16px;
            }
            """
            % (border, fill)
        )


class ActionButton(QPushButton):
    def __init__(self, text: str):
        super().__init__(text)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(46)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFocusPolicy(Qt.NoFocus)


def _drain_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        child_layout = item.layout()
        if child_layout is not None:
            _drain_layout(child_layout)
        if widget is not None:
            widget.setParent(None)


class RemoteWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        app = QApplication.instance()
        if app is not None and not getattr(app, "_ks5002_font_ready", False):
            app.setFont(QFont("PingFang SC", 13))
            app._ks5002_font_ready = True
        if app is not None:
            app.applicationStateChanged.connect(self._on_app_state_changed)
        self.setWindowTitle("KS5002 专属遥控器")
        self.resize(1280, 860)
        self.setMinimumSize(860, 640)
        self.setFocusPolicy(Qt.StrongFocus)
        try:
            self.setUnifiedTitleAndToolBarOnMac(True)
        except Exception:
            pass

        self.profile = load_saved_profile()
        self.base_url = normalize_control_base_url(self.profile.get("CONTROL_BASE_URL", "http://192.168.4.1"))
        self.network_manager = QNetworkAccessManager(self)
        self.network_manager.setProxy(QNetworkProxy(QNetworkProxy.ProxyType.NoProxy))
        self.command_reply = None
        self.pending_command = ""
        self.pending_command_path = ""
        self.status_reply = None
        self.scan_thread = None
        self.scan_inflight = False
        self.scan_results: queue.Queue[tuple[bool, str, str]] = queue.Queue()
        self.status_request_inflight = False
        self.active_motion_path = ""
        self.active_motion_button = None
        self.motion_key_stack = []
        self.latest_summary = {}
        self.action_buttons = []
        self.metric_labels = []
        self.metric_values = []
        self._closing = False
        self._layout_mode = ""
        self.action_specs = []
        self.status_stale_ms = 2200
        self.keyboard_motion_deadline_ms = 0
        self.keyboard_motion_initial_grace_ms = 900
        self.keyboard_motion_repeat_grace_ms = 280

        self._build_ui()
        self._build_menu()
        self._ensure_bridge_if_needed()
        self._apply_base_url(self.base_url, announce=False)

        self.motion_timer = QTimer(self)
        self.motion_timer.timeout.connect(self._repeat_motion_command)
        self.motion_timer.setInterval(100)

        self.status_timer = QTimer(self)
        self.status_timer.timeout.connect(self.poll_status)
        self.status_timer.start(420)

        self.followup_poll_timer = QTimer(self)
        self.followup_poll_timer.setSingleShot(True)
        self.followup_poll_timer.timeout.connect(self.poll_status)

        self.initial_poll_timer = QTimer(self)
        self.initial_poll_timer.setSingleShot(True)
        self.initial_poll_timer.timeout.connect(self.poll_status)
        self.initial_poll_timer.start(250)

        self.scan_result_timer = QTimer(self)
        self.scan_result_timer.setInterval(120)
        self.scan_result_timer.timeout.connect(self._drain_scan_results)

        self.motion_release_guard_timer = QTimer(self)
        self.motion_release_guard_timer.setInterval(45)
        self.motion_release_guard_timer.timeout.connect(self._guard_mouse_release_stop)

        self.keyboard_motion_guard_timer = QTimer(self)
        self.keyboard_motion_guard_timer.setInterval(60)
        self.keyboard_motion_guard_timer.timeout.connect(self._guard_keyboard_motion_stop)

        self.stop_burst_timer = QTimer(self)
        self.stop_burst_timer.setInterval(90)
        self.stop_burst_timer.timeout.connect(self._flush_stop_burst)
        self.stop_burst_remaining = 0

    def _build_menu(self):
        action_quit = QAction("退出", self)
        action_quit.triggered.connect(self.close)
        self.menuBar().addAction(action_quit)

    def _build_ui(self):
        root = QWidget()
        root.setObjectName("appRoot")
        self.setCentralWidget(root)

        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(self.scroll)

        surface = QWidget()
        surface.setObjectName("surface")
        self.scroll.setWidget(surface)

        self.surface_layout = QVBoxLayout(surface)
        self.surface_layout.setContentsMargins(28, 28, 28, 28)
        self.surface_layout.setSpacing(18)

        hero = QFrame()
        hero.setObjectName("hero")
        self.hero_layout = QGridLayout(hero)
        self.hero_layout.setContentsMargins(24, 22, 24, 22)
        self.hero_layout.setHorizontalSpacing(18)
        self.hero_layout.setVerticalSpacing(12)

        hero_text = QVBoxLayout()
        hero_text.setSpacing(6)
        self.hero_title = QLabel("KS5002 Remote")
        self.hero_title.setObjectName("heroTitle")
        self.hero_subtitle = QLabel("简洁磨砂玻璃界面 · 热点远控优先 · WASD 驾驶 · 左右方向键调云台")
        self.hero_subtitle.setObjectName("heroSubtitle")
        self.hero_subtitle.setWordWrap(True)
        hero_text.addWidget(self.hero_title)
        hero_text.addWidget(self.hero_subtitle)
        self.hero_text_layout = hero_text

        state_box = QVBoxLayout()
        state_box.setSpacing(6)
        state_row = QHBoxLayout()
        state_row.setSpacing(8)
        self.status_dot = StatusDot()
        self.status_text = QLabel("等待连接")
        self.status_text.setObjectName("statusText")
        state_row.addWidget(self.status_dot)
        state_row.addWidget(self.status_text)
        state_row.addStretch(1)
        state_box.addLayout(state_row)
        self.hint_text = QLabel("W A S D 驾驶并松手即停；空格强制暂停；左右方向键调云台，上方向键回中。")
        self.hint_text.setObjectName("hintText")
        state_box.addWidget(self.hint_text)
        self.hero_state_layout = state_box
        self._reflow_hero("wide")
        self.surface_layout.addWidget(hero)

        self.connection_card = self._build_connection_card()
        self.drive_card = self._build_drive_card()
        self.action_card = self._build_action_card()
        self.telemetry_card = self._build_telemetry_card()
        self.console_card = self._build_console_card()

        self.dashboard_grid = QGridLayout()
        self.dashboard_grid.setContentsMargins(0, 0, 0, 0)
        self.dashboard_grid.setHorizontalSpacing(18)
        self.dashboard_grid.setVerticalSpacing(18)
        self.surface_layout.addLayout(self.dashboard_grid, 1)
        self._apply_responsive_layout(force=True)
        self._apply_scale()

        self.setStyleSheet(
            """
            #appRoot {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #e9eef4,
                    stop:0.55 #dde5ee,
                    stop:1 #cfd9e5);
            }
            QWidget {
                color: #18324c;
            }
            QMenuBar {
                background: transparent;
                color: #395772;
            }
            #hero {
                border-radius: 28px;
                background: rgba(255,255,255,0.74);
                border: 1px solid rgba(255,255,255,0.90);
            }
            #heroTitle {
                font-size: 32px;
                font-weight: 800;
                color: #10263d;
            }
            #heroSubtitle {
                font-size: 15px;
                color: #5e738c;
            }
            #statusText {
                font-size: 16px;
                font-weight: 700;
            }
            #hintText, #metaText, #cardSubtitle {
                color: #667a8f;
                font-size: 13px;
            }
            #glassCard {
                border-radius: 28px;
                background: rgba(255,255,255,0.66);
                border: 1px solid rgba(255,255,255,0.84);
            }
            #cardTitle {
                font-size: 20px;
                font-weight: 800;
                color: #18314b;
            }
            #metricLabel {
                color: #6a7f95;
                font-size: 13px;
            }
            #metricValue {
                color: #14304a;
                font-size: 14px;
                font-weight: 700;
            }
            QLineEdit, QTextEdit {
                border-radius: 18px;
                border: 1px solid rgba(255,255,255,0.86);
                background: rgba(255,255,255,0.70);
                padding: 12px 14px;
                selection-background-color: rgba(95, 148, 199, 0.28);
            }
            QSlider::groove:horizontal {
                height: 8px;
                background: rgba(90,120,150,0.18);
                border-radius: 4px;
            }
            QSlider::handle:horizontal {
                width: 20px;
                margin: -7px 0;
                border-radius: 10px;
                background: #4b8fd7;
            }
            QPushButton {
                border-radius: 18px;
                border: 1px solid rgba(255,255,255,0.84);
                background: rgba(255,255,255,0.72);
                color: #14304a;
                font-size: 15px;
                font-weight: 700;
                padding: 12px 14px;
            }
            QPushButton:hover {
                background: rgba(255,255,255,0.86);
            }
            QPushButton:pressed {
                background: rgba(232,238,245,0.96);
            }
            """
        )

    def _build_connection_card(self):
        card = GlassCard("连接", "优先使用本地桥，必要时也能快速切换地址或扫网段。")
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("http://192.168.x.x")
        self.url_input.returnPressed.connect(self.apply_url)

        self.connect_button = ActionButton("应用地址")
        self.connect_button.clicked.connect(self.apply_url)

        self.scan_button = ActionButton("扫描小车")
        self.scan_button.clicked.connect(self.scan_robot)

        self.refresh_button = ActionButton("刷新状态")
        self.refresh_button.clicked.connect(self.poll_status)

        self.connection_controls = QGridLayout()
        self.connection_controls.setHorizontalSpacing(10)
        self.connection_controls.setVerticalSpacing(10)
        card.body.addLayout(self.connection_controls)
        self._reflow_connection_controls("wide")

        self.connection_meta = QLabel("")
        self.connection_meta.setObjectName("metaText")
        self.connection_meta.setWordWrap(True)
        card.body.addWidget(self.connection_meta)
        return card

    def _build_drive_card(self):
        card = GlassCard("驾驶", "按住持续发命令，松手立刻下发停止，板端负责平滑减速。")
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(16)

        self.forward_button = MotionButton("前进", "#5ab77f")
        self.backward_button = MotionButton("后退", "#d6955f")
        self.left_button = MotionButton("左转", "#6aa7d8")
        self.right_button = MotionButton("右转", "#d9837e")
        self.brake_button = MotionButton("停止", "#d8bb62")
        self.brake_button.setMinimumHeight(72)

        self._wire_motion_button(self.forward_button, "/btn/F")
        self._wire_motion_button(self.backward_button, "/btn/B")
        self._wire_motion_button(self.left_button, "/btn/L")
        self._wire_motion_button(self.right_button, "/btn/R")
        self.brake_button.pressed.connect(lambda: (self.setFocus(Qt.OtherFocusReason), self.stop_motion()))

        grid.addWidget(self.forward_button, 0, 1)
        grid.addWidget(self.left_button, 1, 0)
        grid.addWidget(self.brake_button, 1, 1)
        grid.addWidget(self.right_button, 1, 2)
        grid.addWidget(self.backward_button, 2, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)
        card.body.addLayout(grid)

        self.motion_state_label = QLabel("当前动作: manual-idle")
        self.motion_state_label.setObjectName("metaText")
        card.body.addWidget(self.motion_state_label)
        return card

    def _build_action_card(self):
        card = GlassCard("操作", "云台、夹爪、模式切换和踢球集中在这里。")
        self.action_grid = QGridLayout()
        self.action_grid.setHorizontalSpacing(12)
        self.action_grid.setVerticalSpacing(12)

        actions = [
            ("手动", "/btn/1"),
            ("自动", "/btn/0"),
            ("停自动", "/btn/j"),
            ("踢球", "/btn/rk"),
            ("抓球", "/btn/p"),
            ("放球", "/btn/x"),
            ("云台左", "/btn/l"),
            ("云台中", "/btn/m"),
            ("云台右", "/btn/n"),
        ]
        for label, path in actions:
            button = ActionButton(label)
            button.pressed.connect(lambda cmd=path: (self.setFocus(Qt.OtherFocusReason), self.send_command(cmd)))
            self.action_buttons.append(button)
            self.action_specs.append((button, path))
        card.body.addLayout(self.action_grid)
        self._reflow_action_buttons(3)

        speed_grid = QGridLayout()
        speed_grid.setHorizontalSpacing(12)
        speed_grid.setVerticalSpacing(8)

        self.left_speed_label = QLabel("左轮速度 760")
        self.left_speed_slider = self._make_speed_slider(int(self.profile.get("MANUAL_SPEED", 760) or 760))
        self.left_speed_slider.valueChanged.connect(
            lambda value: self.left_speed_label.setText("左轮速度 %d" % int(value))
        )
        self.left_speed_slider.sliderReleased.connect(
            lambda: self.send_command("/btn/u%d" % int(self.left_speed_slider.value()))
        )

        self.right_speed_label = QLabel("右轮速度 760")
        self.right_speed_slider = self._make_speed_slider(int(self.profile.get("MANUAL_SPEED", 760) or 760))
        self.right_speed_slider.valueChanged.connect(
            lambda value: self.right_speed_label.setText("右轮速度 %d" % int(value))
        )
        self.right_speed_slider.sliderReleased.connect(
            lambda: self.send_command("/btn/v%d" % int(self.right_speed_slider.value()))
        )

        speed_grid.addWidget(self.left_speed_label, 0, 0)
        speed_grid.addWidget(self.left_speed_slider, 1, 0)
        speed_grid.addWidget(self.right_speed_label, 2, 0)
        speed_grid.addWidget(self.right_speed_slider, 3, 0)
        card.body.addLayout(speed_grid)
        return card

    def _build_telemetry_card(self):
        card = GlassCard("状态", "只保留远控真正需要的关键信息。")
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)

        self.control_state_value = QLabel("--")
        self.mode_value = QLabel("--")
        self.head_pose_value = QLabel("--")
        self.face_value = QLabel("--")
        self.ball_value = QLabel("--")
        self.sonar_value = QLabel("--")
        self.speed_value = QLabel("--")
        self.link_age_value = QLabel("--")

        metrics = [
            ("控制状态", self.control_state_value),
            ("工作模式", self.mode_value),
            ("云台朝向", self.head_pose_value),
            ("表情状态", self.face_value),
            ("抓球状态", self.ball_value),
            ("超声波", self.sonar_value),
            ("当前轮速", self.speed_value),
            ("状态延迟", self.link_age_value),
        ]
        for row, (label_text, widget) in enumerate(metrics):
            label = QLabel(label_text)
            label.setObjectName("metricLabel")
            widget.setObjectName("metricValue")
            grid.addWidget(label, row, 0)
            grid.addWidget(widget, row, 1)
            self.metric_labels.append(label)
            self.metric_values.append(widget)

        card.body.addLayout(grid)
        return card

    def _build_console_card(self):
        card = GlassCard("控制台", "保留少量高价值日志，方便判断手感和链路稳定性。")
        self.console = QTextEdit()
        self.console.setReadOnly(True)
        self.console.setMinimumHeight(220)
        card.body.addWidget(self.console, 1)
        return card

    def _reflow_hero(self, mode: str):
        while self.hero_layout.count():
            self.hero_layout.takeAt(0)
        if mode == "compact":
            self.hero_layout.addLayout(self.hero_text_layout, 0, 0)
            self.hero_layout.addLayout(self.hero_state_layout, 1, 0)
            self.hero_layout.setColumnStretch(0, 1)
        else:
            self.hero_layout.addLayout(self.hero_text_layout, 0, 0)
            self.hero_layout.addLayout(self.hero_state_layout, 0, 1)
            self.hero_layout.setColumnStretch(0, 5)
            self.hero_layout.setColumnStretch(1, 3)

    def _reflow_connection_controls(self, mode: str):
        _drain_layout(self.connection_controls)
        if mode == "compact":
            self.connection_controls.addWidget(self.url_input, 0, 0)
            self.connection_controls.addWidget(self.connect_button, 1, 0)
            self.connection_controls.addWidget(self.scan_button, 2, 0)
            self.connection_controls.addWidget(self.refresh_button, 3, 0)
            self.connection_controls.setColumnStretch(0, 1)
        else:
            self.connection_controls.addWidget(self.url_input, 0, 0, 1, 3)
            self.connection_controls.addWidget(self.connect_button, 1, 0)
            self.connection_controls.addWidget(self.scan_button, 1, 1)
            self.connection_controls.addWidget(self.refresh_button, 1, 2)
            self.connection_controls.setColumnStretch(0, 1)
            self.connection_controls.setColumnStretch(1, 1)
            self.connection_controls.setColumnStretch(2, 1)

    def _reflow_action_buttons(self, columns: int):
        columns = max(1, int(columns))
        _drain_layout(self.action_grid)
        for index, (button, _path) in enumerate(self.action_specs):
            row = index // columns
            col = index % columns
            self.action_grid.addWidget(button, row, col)
        for col in range(columns):
            self.action_grid.setColumnStretch(col, 1)

    def _apply_responsive_layout(self, force: bool = False):
        width = max(self.width(), 1)
        if width >= 1320:
            mode = "wide"
        elif width >= 1040:
            mode = "medium"
        else:
            mode = "compact"
        if not force and mode == self._layout_mode:
            return
        self._layout_mode = mode
        self._reflow_hero(mode)
        self._reflow_connection_controls(mode)
        self._reflow_action_buttons(3 if mode == "wide" else 2)

        _drain_layout(self.dashboard_grid)

        if mode == "wide":
            self.dashboard_grid.addWidget(self.drive_card, 0, 0, 2, 1)
            self.dashboard_grid.addWidget(self.action_card, 0, 1)
            self.dashboard_grid.addWidget(self.telemetry_card, 1, 1)
            self.dashboard_grid.addWidget(self.connection_card, 0, 2, 2, 1)
            self.dashboard_grid.addWidget(self.console_card, 2, 0, 1, 3)
            self.dashboard_grid.setColumnStretch(0, 5)
            self.dashboard_grid.setColumnStretch(1, 4)
            self.dashboard_grid.setColumnStretch(2, 4)
        elif mode == "medium":
            self.dashboard_grid.addWidget(self.drive_card, 0, 0, 1, 2)
            self.dashboard_grid.addWidget(self.action_card, 1, 0)
            self.dashboard_grid.addWidget(self.telemetry_card, 1, 1)
            self.dashboard_grid.addWidget(self.connection_card, 2, 0, 1, 2)
            self.dashboard_grid.addWidget(self.console_card, 3, 0, 1, 2)
            self.dashboard_grid.setColumnStretch(0, 1)
            self.dashboard_grid.setColumnStretch(1, 1)
        else:
            self.dashboard_grid.addWidget(self.drive_card, 0, 0)
            self.dashboard_grid.addWidget(self.action_card, 1, 0)
            self.dashboard_grid.addWidget(self.telemetry_card, 2, 0)
            self.dashboard_grid.addWidget(self.connection_card, 3, 0)
            self.dashboard_grid.addWidget(self.console_card, 4, 0)
            self.dashboard_grid.setColumnStretch(0, 1)

    def _apply_scale(self):
        width = max(self.width(), 860)
        scale = max(0.9, min(width / 1320.0, 1.18))
        edge = int(28 * scale)
        block = int(18 * scale)
        self.surface_layout.setContentsMargins(edge, edge, edge, edge)
        self.surface_layout.setSpacing(block)
        self.dashboard_grid.setHorizontalSpacing(block)
        self.dashboard_grid.setVerticalSpacing(block)
        self.hero_layout.setContentsMargins(int(24 * scale), int(22 * scale), int(24 * scale), int(22 * scale))
        self.hero_layout.setHorizontalSpacing(int(18 * scale))
        self.hero_layout.setVerticalSpacing(int(12 * scale))

        def _set_font(widget, size, weight=None):
            font = QFont(widget.font())
            font.setPointSizeF(size * scale)
            if weight is not None:
                if isinstance(weight, QFont.Weight):
                    resolved_weight = weight
                elif weight >= 700:
                    resolved_weight = QFont.Weight.Bold
                elif weight >= 600:
                    resolved_weight = QFont.Weight.DemiBold
                elif weight >= 500:
                    resolved_weight = QFont.Weight.Medium
                else:
                    resolved_weight = QFont.Weight.Normal
                font.setWeight(resolved_weight)
            widget.setFont(font)

        _set_font(self.hero_title, 20, 700)
        _set_font(self.hero_subtitle, 10.4)
        _set_font(self.status_text, 11.4, 700)
        _set_font(self.hint_text, 9.4)
        _set_font(self.connection_meta, 9.4)
        _set_font(self.motion_state_label, 9.4)
        _set_font(self.left_speed_label, 9.6, 700)
        _set_font(self.right_speed_label, 9.6, 700)

        for card in (
            self.connection_card,
            self.drive_card,
            self.action_card,
            self.telemetry_card,
            self.console_card,
        ):
            _set_font(card.title_label, 12.8, 700)
            if card.subtitle_label is not None:
                _set_font(card.subtitle_label, 9.4)

        for label in self.metric_labels:
            _set_font(label, 9.0)
        for value in self.metric_values:
            _set_font(value, 10.0, 700)

        self.forward_button.setMinimumHeight(int(88 * scale))
        self.backward_button.setMinimumHeight(int(88 * scale))
        self.left_button.setMinimumHeight(int(88 * scale))
        self.right_button.setMinimumHeight(int(88 * scale))
        self.brake_button.setMinimumHeight(int(70 * scale))
        for button in self.action_buttons:
            button.setMinimumHeight(int(46 * scale))
            _set_font(button, 10.0, 700)
        self.console.setMinimumHeight(int(200 * scale))

    def _wire_motion_button(self, button: MotionButton, path: str):
        button.pressed.connect(lambda cmd=path, widget=button: (self.setFocus(Qt.OtherFocusReason), self.start_motion(cmd, widget)))
        button.released.connect(lambda cmd=path: self.finish_motion(cmd))

    def _make_speed_slider(self, initial: int):
        slider = QSlider(Qt.Horizontal)
        slider.setFocusPolicy(Qt.NoFocus)
        slider.setRange(0, 1023)
        slider.setSingleStep(8)
        slider.setPageStep(40)
        slider.setValue(int(initial))
        return slider

    def _append_log(self, message: str):
        self.console.append(message)
        bar = self.console.verticalScrollBar()
        if bar is not None:
            bar.setValue(bar.maximum())

    def _ensure_bridge_if_needed(self):
        mqtt_host = str(self.profile.get("MQTT_BROKER_HOST") or "").strip()
        relay_url = str(self.profile.get("RELAY_BASE_URL") or "").strip()
        lan_host = str(self.profile.get("LAN_BRIDGE_HOST") or "").strip()
        control_url = str(self.profile.get("CONTROL_BASE_URL") or "").strip()
        if not mqtt_host and not relay_url and not lan_host and "127.0.0.1:8765" not in control_url:
            return
        try:
            ensure_local_bridge(logger=self._append_log)
        except Exception as exc:
            self._append_log("本地桥启动失败: %s" % exc)

    def _save_profile_url(self):
        self.profile["CONTROL_BASE_URL"] = self.base_url
        save_profile(self.profile)

    def _apply_base_url(self, base_url: str, announce: bool = True):
        self.base_url = normalize_control_base_url(base_url)
        self.url_input.setText(self.base_url)
        self.connection_meta.setText("控制地址: %s" % self.base_url)
        self._save_profile_url()
        if announce:
            self._append_log("控制地址切换到 %s" % self.base_url)

    def apply_url(self):
        if self._closing:
            return
        self._apply_base_url(self.url_input.text().strip() or self.base_url)
        self.poll_status()

    def scan_robot(self):
        if self._closing:
            return
        if self.scan_inflight:
            return
        self.scan_inflight = True
        self.status_dot.set_status("busy")
        self.status_text.setText("正在扫描当前热点网段…")
        self.scan_thread = threading.Thread(target=self._scan_robot_worker, daemon=True)
        self.scan_thread.start()
        if not self.scan_result_timer.isActive():
            self.scan_result_timer.start()

    def _on_scan_done(self, success: bool, base_url: str, message: str):
        self.scan_inflight = False
        self.scan_thread = None
        if self.scan_results.empty():
            self.scan_result_timer.stop()
        if self._closing:
            return
        if success and base_url:
            self._apply_base_url(base_url)
            self.status_text.setText("已发现小车")
            self.status_dot.set_status("online")
            self.poll_status()
            return
        self.status_dot.set_status("offline")
        self.status_text.setText("扫描失败")
        self._append_log("扫描失败: %s" % message)

    def _scan_robot_worker(self):
        try:
            wifi = detect_wifi_environment(include_password=False)
            local_ip = str(wifi.get("ip") or "").strip()
            if not local_ip:
                self.scan_results.put((False, "", "当前电脑没有拿到热点 IP。"))
                return
            result = discover_robot_on_subnet(local_ip, timeout_s=0.35)
        except Exception as exc:
            self.scan_results.put((False, "", str(exc)))
            return
        if not result:
            self.scan_results.put((False, "", "没有在当前热点网段扫到小车。"))
            return
        self.scan_results.put((True, result.get("base_url", ""), ""))

    def _drain_scan_results(self):
        handled = False
        while True:
            try:
                success, base_url, message = self.scan_results.get_nowait()
            except queue.Empty:
                break
            handled = True
            self._on_scan_done(success, base_url, message)
        if handled and not self.scan_inflight and self.scan_results.empty():
            self.scan_result_timer.stop()

    def _build_request_url(self, path: str) -> str:
        base = normalize_control_base_url(self.base_url)
        if not path.startswith("/"):
            path = "/" + path
        return base + path

    def _make_request(self, request_url: str, timeout_ms: int):
        request = QNetworkRequest(QUrl(request_url))
        try:
            request.setTransferTimeout(int(timeout_ms))
        except Exception:
            pass
        return request

    def _abort_reply(self, attr_name: str):
        reply = getattr(self, attr_name, None)
        if reply is None:
            return
        setattr(self, attr_name, None)
        try:
            reply.abort()
        except Exception:
            pass
        try:
            reply.deleteLater()
        except Exception:
            pass

    def _command_family(self, path: str) -> str:
        if path in {"/btn/F", "/btn/B", "/btn/L", "/btn/R", "/btn/S"}:
            return "motion"
        if path.startswith("/btn/u"):
            return "speed-left"
        if path.startswith("/btn/v"):
            return "speed-right"
        if path in {"/btn/l", "/btn/m", "/btn/n", "/btn/3", "/btn/3#", "/btn/4", "/btn/4#", "/btn/5", "/btn/5#"}:
            return "pan"
        return ""

    def _queue_pending_command(self, path: str):
        path = str(path or "")
        if not path:
            return
        current = str(self.pending_command_path or "")
        if current == "/btn/S" and path != "/btn/S":
            return
        if path == "/btn/S":
            self.pending_command_path = path
            self.pending_command = self._build_request_url(path)
            return
        current_family = self._command_family(current)
        new_family = self._command_family(path)
        if current_family and current_family == new_family:
            self.pending_command_path = path
            self.pending_command = self._build_request_url(path)
            return
        if not current:
            self.pending_command_path = path
            self.pending_command = self._build_request_url(path)
            return
        self.pending_command_path = path
        self.pending_command = self._build_request_url(path)

    def _dispatch_command(self, path: str):
        request_url = self._build_request_url(path)
        reply = self.network_manager.get(self._make_request(request_url, 700))
        self.command_reply = reply
        reply.finished.connect(lambda request_url=request_url, reply=reply: self._on_command_done(request_url, reply))
        self.status_dot.set_status("busy")

    def send_command(self, path: str):
        if self._closing:
            return
        if self.command_reply is not None:
            self._queue_pending_command(path)
            return
        self._dispatch_command(path)

    def _on_command_done(self, request_url: str, reply):
        if self.command_reply is reply:
            self.command_reply = None
        error_code = reply.error()
        success = error_code == QNetworkReply.NetworkError.NoError
        if success:
            payload = bytes(reply.readAll()).decode("utf-8", errors="ignore").strip() or "ok"
        else:
            payload = reply.errorString() or "request failed"
        reply.deleteLater()
        if self._closing:
            return
        if success:
            self.status_dot.set_status("online")
            self.status_text.setText("命令已送达")
            self._append_log("cmd %s -> %s" % (request_url, payload))
        else:
            self.status_dot.set_status("offline")
            self.status_text.setText("命令发送失败")
            self._append_log("cmd %s -> FAIL %s" % (request_url, payload))
        if self.pending_command_path:
            next_path = self.pending_command_path
            self.pending_command_path = ""
            self.pending_command = ""
            self._dispatch_command(next_path)
            return
        if self.pending_command:
            next_url = self.pending_command
            self.pending_command = ""
            next_reply = self.network_manager.get(self._make_request(next_url, 700))
            self.command_reply = next_reply
            next_reply.finished.connect(lambda request_url=next_url, reply=next_reply: self._on_command_done(request_url, reply))
            return
        self.followup_poll_timer.start(80)

    def poll_status(self):
        if self._closing:
            return
        if self.status_request_inflight:
            return
        self.status_request_inflight = True
        request_url = self._build_request_url("/status")
        reply = self.network_manager.get(self._make_request(request_url, 950))
        self.status_reply = reply
        reply.finished.connect(lambda reply=reply: self._on_status_done(reply))

    def _on_status_done(self, reply):
        self.status_request_inflight = False
        if self.status_reply is reply:
            self.status_reply = None
        error_code = reply.error()
        success = error_code == QNetworkReply.NetworkError.NoError
        if success:
            payload_text = bytes(reply.readAll()).decode("utf-8", errors="ignore").strip()
            try:
                payload = json.loads(payload_text)
            except Exception:
                success = False
                error = "状态返回不是有效 JSON"
                payload = {}
            else:
                if not isinstance(payload, dict):
                    success = False
                    error = "状态返回不是 JSON 对象"
                    payload = {}
                else:
                    error = ""
        else:
            error = reply.errorString() or "状态请求失败"
            payload = {}
        reply.deleteLater()
        if self._closing:
            return
        if not success:
            self.status_dot.set_status("offline")
            self.status_text.setText("状态不可达")
            self.connection_meta.setText("控制地址: %s\n状态错误: %s" % (self.base_url, error))
            return

        summary = payload.get("summary") or {}
        self.latest_summary = summary
        station_ip = str(payload.get("station_ip") or payload.get("ip_address") or "").strip()
        transport = str(payload.get("transport") or "mqtt").strip() or "mqtt"
        age_ms = int(payload.get("relay_status_age_ms") or -1)
        predicted = bool(payload.get("summary_predicted"))
        status_source = str(payload.get("status_source") or "").strip() or "--"
        transport_online = bool(payload.get("transport_online"))
        transport_error = str(payload.get("transport_error") or "").strip()
        control_state = str(summary.get("control_state") or "--")
        mode = str(summary.get("mode") or "--")
        head_pose = str(summary.get("head_pose") or "--")
        face_name = str(summary.get("display_face") or "--")
        sonar_cm = summary.get("sonar_cm")
        current_left = summary.get("current_left_speed")
        current_right = summary.get("current_right_speed")
        captured_ball = bool(summary.get("captured_ball"))

        stale = age_ms < 0 or age_ms > self.status_stale_ms
        if not transport_online:
            self.status_dot.set_status("offline")
            self.status_text.setText("%s 离线" % transport.upper())
        elif predicted or stale:
            self.status_dot.set_status("busy")
            if predicted:
                self.status_text.setText("%s 已送达，等待车端回执" % transport.upper())
            else:
                self.status_text.setText("%s 在线，状态滞后" % transport.upper())
        else:
            self.status_dot.set_status("online")
            self.status_text.setText("%s 在线" % transport.upper())
        self.connection_meta.setText(
            "控制地址: %s\n热点 IP: %s\n状态刷新: %s\n状态来源: %s%s"
            % (
                self.base_url,
                station_ip or "--",
                "--" if age_ms < 0 else ("%dms" % age_ms),
                status_source,
                ("" if not transport_error else "\n传输错误: %s" % transport_error),
            )
        )

        self.motion_state_label.setText("当前动作: %s" % control_state)
        self.control_state_value.setText(control_state)
        self.mode_value.setText(mode)
        self.head_pose_value.setText(head_pose)
        self.face_value.setText(face_name)
        self.ball_value.setText("已抓到" if captured_ball else "未抓到")
        self.sonar_value.setText("--" if sonar_cm in (None, "") or sonar_cm == -1 else "%scm" % sonar_cm)
        self.speed_value.setText(
            "%s / %s"
            % (
                current_left if current_left is not None else "--",
                current_right if current_right is not None else "--",
            )
        )
        if predicted:
            self.link_age_value.setText("预测中")
        elif age_ms < 0:
            self.link_age_value.setText("--")
        else:
            self.link_age_value.setText("%dms" % age_ms)

    def start_motion(self, path: str, button: MotionButton | None = None):
        if self._closing:
            return
        self.stop_burst_timer.stop()
        self.stop_burst_remaining = 0
        if self.active_motion_button is not None and self.active_motion_button is not button:
            self.active_motion_button.set_active(False)
        self.active_motion_button = button
        if self.active_motion_button is not None:
            self.active_motion_button.set_active(True)
        self.active_motion_path = path
        self.send_command(path)
        self.motion_timer.start()
        if not self.motion_release_guard_timer.isActive():
            self.motion_release_guard_timer.start()

    def finish_motion(self, released_path: str = ""):
        if released_path and released_path != self.active_motion_path:
            return
        if self.active_motion_button is not None:
            self.active_motion_button.set_active(False)
        self.active_motion_button = None
        self.active_motion_path = ""
        self.motion_timer.stop()
        self.motion_release_guard_timer.stop()
        self._request_stop_burst(clear_pending=False)

    def stop_motion(self):
        self.force_stop(clear_keys=True)

    def force_stop(self, clear_keys: bool = False):
        if self.active_motion_button is not None:
            self.active_motion_button.set_active(False)
        self.active_motion_button = None
        self.active_motion_path = ""
        self.motion_timer.stop()
        self.motion_release_guard_timer.stop()
        self.keyboard_motion_deadline_ms = 0
        self.keyboard_motion_guard_timer.stop()
        if clear_keys:
            self.motion_key_stack = []
        self.pending_command = ""
        self.pending_command_path = ""
        self._request_stop_burst(clear_pending=False)

    def _request_stop_burst(self, clear_pending: bool = True):
        if clear_pending:
            self.pending_command = ""
            self.pending_command_path = ""
        self.stop_burst_remaining = max(self.stop_burst_remaining, 5)
        self._queue_pending_command("/btn/S")
        self.send_command("/btn/S")
        if not self.stop_burst_timer.isActive():
            self.stop_burst_timer.start()

    def _flush_stop_burst(self):
        if self._closing:
            self.stop_burst_timer.stop()
            self.stop_burst_remaining = 0
            return
        if self.stop_burst_remaining <= 1:
            self.stop_burst_timer.stop()
            self.stop_burst_remaining = 0
            return
        self.stop_burst_remaining -= 1
        self.send_command("/btn/S")

    def _repeat_motion_command(self):
        if not self.active_motion_path or self._closing:
            return
        self.send_command(self.active_motion_path)

    def _arm_keyboard_motion_guard(self, is_repeat: bool = False):
        grace_ms = self.keyboard_motion_repeat_grace_ms if is_repeat else self.keyboard_motion_initial_grace_ms
        self.keyboard_motion_deadline_ms = int(time.monotonic() * 1000) + int(max(180, grace_ms))
        if not self.keyboard_motion_guard_timer.isActive():
            self.keyboard_motion_guard_timer.start()

    def _path_for_key(self, key: int) -> str:
        mapping = {
            Qt.Key_W: "/btn/F",
            Qt.Key_S: "/btn/B",
            Qt.Key_A: "/btn/L",
            Qt.Key_D: "/btn/R",
        }
        return mapping.get(key, "")

    def _pan_path_for_key(self, key: int) -> str:
        mapping = {
            Qt.Key_Left: "/btn/l",
            Qt.Key_Right: "/btn/n",
            Qt.Key_Up: "/btn/m",
        }
        return mapping.get(key, "")

    def keyPressEvent(self, event):
        if self._closing:
            event.ignore()
            return
        if event.key() == Qt.Key_Space:
            self.force_stop(clear_keys=True)
            event.accept()
            return
        path = self._path_for_key(event.key())
        if not path:
            pan_path = self._pan_path_for_key(event.key())
            if pan_path:
                if event.isAutoRepeat():
                    event.accept()
                    return
                self.send_command(pan_path)
                event.accept()
                return
            if event.isAutoRepeat():
                event.accept()
                return
            return super().keyPressEvent(event)
        self._arm_keyboard_motion_guard(is_repeat=event.isAutoRepeat())
        if event.isAutoRepeat():
            event.accept()
            return
        key_pair = (event.key(), path)
        if key_pair not in self.motion_key_stack:
            self.motion_key_stack.append(key_pair)
        button = {
            "/btn/F": self.forward_button,
            "/btn/B": self.backward_button,
            "/btn/L": self.left_button,
            "/btn/R": self.right_button,
        }.get(path)
        self.start_motion(path, button)
        event.accept()

    def keyReleaseEvent(self, event):
        if self._closing:
            event.ignore()
            return
        if event.isAutoRepeat():
            return super().keyReleaseEvent(event)
        if event.key() == Qt.Key_Space:
            event.accept()
            return
        path = self._path_for_key(event.key())
        if not path:
            return super().keyReleaseEvent(event)
        self.motion_key_stack = [item for item in self.motion_key_stack if item[0] != event.key()]
        if self.motion_key_stack:
            self._arm_keyboard_motion_guard(is_repeat=False)
            _key, next_path = self.motion_key_stack[-1]
            button = {
                "/btn/F": self.forward_button,
                "/btn/B": self.backward_button,
                "/btn/L": self.left_button,
                "/btn/R": self.right_button,
            }.get(next_path)
            self.start_motion(next_path, button)
        else:
            self.keyboard_motion_deadline_ms = 0
            self.keyboard_motion_guard_timer.stop()
            self.finish_motion(path)
        event.accept()

    def _send_stop_sync(self):
        try:
            with open_url(self._build_request_url("/btn/S"), timeout=0.7):
                return True
        except Exception:
            return False

    def _on_app_state_changed(self, state):
        if self._closing:
            return
        if state != Qt.ApplicationState.ApplicationActive and self.active_motion_path:
            self.force_stop(clear_keys=True)

    def _guard_mouse_release_stop(self):
        if self._closing:
            self.motion_release_guard_timer.stop()
            return
        if not self.active_motion_path:
            self.motion_release_guard_timer.stop()
            return
        if self.motion_key_stack:
            return
        if QGuiApplication.mouseButtons() == Qt.MouseButton.NoButton:
            self.force_stop(clear_keys=False)

    def _guard_keyboard_motion_stop(self):
        if self._closing:
            self.keyboard_motion_guard_timer.stop()
            self.keyboard_motion_deadline_ms = 0
            return
        if not self.motion_key_stack:
            self.keyboard_motion_guard_timer.stop()
            self.keyboard_motion_deadline_ms = 0
            return
        if not self.keyboard_motion_deadline_ms:
            return
        if int(time.monotonic() * 1000) < int(self.keyboard_motion_deadline_ms):
            return
        self._append_log("键盘运动释放未回调，已自动发送停止。")
        self.force_stop(clear_keys=True)

    def _prepare_shutdown(self):
        if self._closing:
            return
        self._closing = True
        current_state = str(self.latest_summary.get("control_state") or "manual-idle")
        need_stop = bool(self.active_motion_path) or current_state not in ("manual-idle", "manual-braking")
        self.motion_timer.stop()
        self.status_timer.stop()
        self.followup_poll_timer.stop()
        self.initial_poll_timer.stop()
        self.scan_result_timer.stop()
        self.motion_release_guard_timer.stop()
        self.keyboard_motion_guard_timer.stop()
        self.stop_burst_timer.stop()
        self.pending_command = ""
        self.pending_command_path = ""
        self.active_motion_path = ""
        self.motion_key_stack = []
        self.keyboard_motion_deadline_ms = 0
        self.status_request_inflight = False
        if self.active_motion_button is not None:
            self.active_motion_button.set_active(False)
        self.active_motion_button = None
        self._abort_reply("command_reply")
        self._abort_reply("status_reply")
        if need_stop:
            try:
                self._send_stop_sync()
            except Exception:
                pass

    def resizeEvent(self, event):
        self._apply_responsive_layout()
        self._apply_scale()
        super().resizeEvent(event)

    def closeEvent(self, event):
        self._prepare_shutdown()
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("KS5002 专属遥控器")
    app.setFont(QFont("PingFang SC", 13))
    window = RemoteWindow()
    app.aboutToQuit.connect(window._prepare_shutdown)
    signal.signal(signal.SIGINT, lambda *_args: app.quit())
    signal_pump = QTimer()
    signal_pump.setInterval(180)
    signal_pump.timeout.connect(lambda: None)
    signal_pump.start()
    app._signal_pump = signal_pump
    screen = QGuiApplication.primaryScreen()
    if screen is not None:
        area = screen.availableGeometry()
        width = max(980, min(int(area.width() * 0.84), 1520))
        height = max(720, min(int(area.height() * 0.9), 1040))
        window.resize(width, height)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
