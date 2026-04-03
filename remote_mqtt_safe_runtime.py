import compat as hw
from compat import Pin


def _clamp(value, lower, upper):
    if value < lower:
        return lower
    if value > upper:
        return upper
    return value


class SoftMotorChannel:
    def __init__(self, dir_pin_num, pwm_pin_num, max_pwm):
        self.max_pwm = int(max(1, max_pwm))
        self.direction_pin = Pin(dir_pin_num, Pin.OUT, value=0)
        self.enable_pin = Pin(pwm_pin_num, Pin.OUT, value=0)
        self.speed = 0
        self.accumulator = 0
        self.enable_state = 0

    def write(self, speed):
        speed = int(_clamp(speed, -self.max_pwm, self.max_pwm))
        if speed != self.speed:
            self.accumulator = 0
        self.speed = speed
        if speed == 0:
            self.accumulator = 0
            if self.enable_state:
                self.enable_pin.value(0)
                self.enable_state = 0
            try:
                self.direction_pin.value(0)
            except Exception:
                pass
            return
        self.direction_pin.value(0 if speed >= 0 else 1)

    def pump(self, now_ms):
        del now_ms
        speed = int(self.speed)
        if speed == 0:
            self.accumulator = 0
            if self.enable_state:
                self.enable_pin.value(0)
                self.enable_state = 0
            try:
                self.direction_pin.value(0)
            except Exception:
                pass
            return
        duty = abs(speed)
        if duty >= self.max_pwm:
            if not self.enable_state:
                self.enable_pin.value(1)
                self.enable_state = 1
            return
        self.accumulator += duty
        active = 0
        if self.accumulator >= self.max_pwm:
            self.accumulator -= self.max_pwm
            active = 1
        if active != self.enable_state:
            self.enable_pin.value(active)
            self.enable_state = active

    def shutdown(self):
        try:
            self.enable_pin.value(0)
        except Exception:
            pass
        self.enable_state = 0
        self.speed = 0
        self.accumulator = 0
        try:
            self.direction_pin.value(0)
        except Exception:
            pass


class SoftServoChannel:
    def __init__(self, pin_num, refresh_ms=24, move_pulses=12, hold_refresh_ms=36, min_us=500, max_us=2500):
        self.pin = Pin(pin_num, Pin.OUT, value=0)
        self.refresh_ms = max(20, int(refresh_ms))
        self.move_pulses = max(1, int(move_pulses))
        self.hold_refresh_ms = max(self.refresh_ms, int(hold_refresh_ms))
        self.min_us = int(max(300, min_us))
        self.max_us = int(max(self.min_us + 100, max_us))
        self.pulse_us = 1500
        self.next_pulse_ms = hw.ticks_ms()
        self.pending_pulses = 0
        self.hold_enabled = False
        self.hold_until_ms = 0
        self.last_pulse_ms = None

    def _pulse_us_for_angle(self, angle, pulse_offset_us=0):
        angle = _clamp(int(angle), -30, 210)
        pulse_width_ms = 0.5 + (angle / 180.0) * 2.0
        pulse_us = int(pulse_width_ms * 1000) + int(pulse_offset_us or 0)
        return int(_clamp(pulse_us, self.min_us, self.max_us))

    def write_angle(self, angle, hold=False, move_pulses=None, hold_for_ms=0, pulse_offset_us=0):
        self.pulse_us = self._pulse_us_for_angle(angle, pulse_offset_us=pulse_offset_us)
        if move_pulses is None:
            move_pulses = self.move_pulses
        self.pending_pulses = max(1, int(move_pulses))
        hold_for_ms = int(max(0, hold_for_ms or 0))
        self.hold_enabled = bool(hold or hold_for_ms > 0)
        now = hw.ticks_ms()
        self.hold_until_ms = hw.ticks_add(now, hold_for_ms) if hold_for_ms > 0 else 0
        if self.last_pulse_ms is None or hw.ticks_diff(now, self.next_pulse_ms) >= 0:
            self.next_pulse_ms = now

    def pump(self, now_ms):
        if self.hold_until_ms and hw.ticks_diff(now_ms, self.hold_until_ms) >= 0:
            self.hold_until_ms = 0
            if self.pending_pulses <= 0:
                self.hold_enabled = False
        if self.pending_pulses <= 0 and not self.hold_enabled:
            return
        if hw.ticks_diff(now_ms, self.next_pulse_ms) < 0:
            return
        try:
            self.pin.value(1)
            hw.sleep_us(self.pulse_us)
        finally:
            self.pin.value(0)
        self.last_pulse_ms = now_ms
        if self.pending_pulses > 0:
            self.pending_pulses -= 1
            interval = self.refresh_ms
        else:
            if self.hold_until_ms and hw.ticks_diff(now_ms, self.hold_until_ms) >= 0:
                self.hold_enabled = False
                return
            interval = self.hold_refresh_ms
        self.next_pulse_ms = hw.ticks_add(now_ms, interval)

    def shutdown(self):
        self.pending_pulses = 0
        self.hold_enabled = False
        self.hold_until_ms = 0
        try:
            self.pin.value(0)
        except Exception:
            pass


class RemoteCar:
    def __init__(self, config_module):
        self.cfg = config_module
        self.left_motor = SoftMotorChannel(
            config_module.LEFT_DIR_PIN,
            config_module.LEFT_PWM_PIN,
            config_module.MAX_PWM,
        )
        self.right_motor = SoftMotorChannel(
            config_module.RIGHT_DIR_PIN,
            config_module.RIGHT_PWM_PIN,
            config_module.MAX_PWM,
        )
        self.head_servo = SoftServoChannel(
            config_module.HEAD_SERVO_PIN,
            refresh_ms=int(
                getattr(
                    config_module,
                    "SOFT_HEAD_SERVO_REFRESH_MS",
                    getattr(config_module, "SOFT_SERVO_REFRESH_MS", 24),
                )
                or 24
            ),
            move_pulses=int(
                getattr(
                    config_module,
                    "SOFT_HEAD_SERVO_MOVE_PULSES",
                    getattr(config_module, "SOFT_SERVO_MOVE_PULSES", 12),
                )
                or 12
            ),
            hold_refresh_ms=int(
                getattr(
                    config_module,
                    "SOFT_HEAD_SERVO_HOLD_REFRESH_MS",
                    getattr(config_module, "SOFT_SERVO_HOLD_REFRESH_MS", 36),
                )
                or 36
            ),
            min_us=int(getattr(config_module, "SOFT_HEAD_SERVO_MIN_US", 500) or 500),
            max_us=int(getattr(config_module, "SOFT_HEAD_SERVO_MAX_US", 2500) or 2500),
        )
        self.claw_servo = SoftServoChannel(
            config_module.CLAW_SERVO_PIN,
            refresh_ms=int(
                getattr(
                    config_module,
                    "SOFT_CLAW_SERVO_REFRESH_MS",
                    getattr(config_module, "SOFT_SERVO_REFRESH_MS", 24),
                )
                or 24
            ),
            move_pulses=int(
                getattr(
                    config_module,
                    "SOFT_CLAW_SERVO_MOVE_PULSES",
                    getattr(config_module, "SOFT_SERVO_MOVE_PULSES", 12),
                )
                or 12
            ),
            hold_refresh_ms=int(
                getattr(
                    config_module,
                    "SOFT_CLAW_SERVO_HOLD_REFRESH_MS",
                    getattr(config_module, "SOFT_SERVO_HOLD_REFRESH_MS", 36),
                )
                or 36
            ),
            min_us=int(getattr(config_module, "SOFT_CLAW_SERVO_MIN_US", 500) or 500),
            max_us=int(getattr(config_module, "SOFT_CLAW_SERVO_MAX_US", 2500) or 2500),
        )

        self.mode = "manual"
        self.auto_paused = True
        self.auto_state = "idle"
        self.manual_left_speed = int(getattr(config_module, "MANUAL_SPEED", 760) or 760)
        self.manual_right_speed = int(getattr(config_module, "MANUAL_SPEED", 760) or 760)
        self.turn_speed = int(getattr(config_module, "TURN_SPEED", self.manual_left_speed) or self.manual_left_speed)
        self.reverse_speed = int(getattr(config_module, "REVERSE_SPEED", self.manual_left_speed) or self.manual_left_speed)
        self.current_left_speed = 0
        self.current_right_speed = 0
        self.motion_state = "idle"
        self.face_name = "manual"
        self.network_station_connected = True

        self.head_angle = int(getattr(config_module, "HEAD_CENTER_ANGLE", 5) or 5)
        self.head_pose = "center"
        self.claw_angle = int(getattr(config_module, "CLAW_OPEN_ANGLE", 156) or 156)
        self.claw_hold_servo_enabled = bool(getattr(config_module, "MQTT_SAFE_SERVO_HOLD_ENABLED", True))
        self.ball_latched = False
        self.head_move_hold_ms = int(getattr(config_module, "HEAD_MOVE_HOLD_MS", 240) or 240)
        self.claw_grab_hold_ms = int(getattr(config_module, "CLAW_GRAB_HOLD_MS", 1500) or 1500)
        self.claw_release_hold_ms = int(getattr(config_module, "CLAW_RELEASE_HOLD_MS", 260) or 260)

        self.release_decel_active = False
        self.release_decel_started_ms = 0
        self.release_decel_duration_ms = int(getattr(config_module, "MANUAL_RELEASE_DECEL_MS", 280) or 280)
        self.release_decel_start_left = 0
        self.release_decel_start_right = 0
        self.manual_command_timeout_ms = int(getattr(config_module, "MANUAL_COMMAND_TIMEOUT_MS", 260) or 260)
        self.manual_motion_deadline_ms = 0

        self.script_name = ""
        self.script_phase = ""
        self.script_started_ms = 0
        self.script_phase_started_ms = 0
        self.kick_profile = tuple((getattr(config_module, "RAM_KICK_PROFILES", ((156, 50, 640, 220, 80),)) or ((156, 50, 640, 220, 80),))[0])

        self.center_head()
        self.open_claw()
        self.stop(immediate=True)
        self._refresh_face()

    def set_network_connected(self, connected):
        self.network_station_connected = bool(connected)
        self._refresh_face()

    def note_transport_state(self, online, error=""):
        del online, error

    def _refresh_face(self):
        if not self.network_station_connected:
            self.face_name = "cry"
        elif self.script_name == "kick":
            self.face_name = "capture" if self.script_phase in ("charge", "release") else "front"
        elif self.release_decel_active:
            self.face_name = "stop"
        elif self.motion_state == "forward":
            self.face_name = "front"
        elif self.motion_state == "backward":
            self.face_name = "back"
        elif self.motion_state == "left":
            self.face_name = "left"
        elif self.motion_state == "right":
            self.face_name = "right"
        elif self.ball_latched:
            self.face_name = "capture"
        elif self.head_pose == "left":
            self.face_name = "left"
        elif self.head_pose == "right":
            self.face_name = "right"
        else:
            self.face_name = "manual"

    def _write_servo(self, servo, angle, hold=False, move_pulses=None, hold_for_ms=0, pulse_offset_us=0):
        try:
            servo.write_angle(
                angle,
                hold=hold,
                move_pulses=move_pulses,
                hold_for_ms=hold_for_ms,
                pulse_offset_us=pulse_offset_us,
            )
        except TypeError:
            servo.write_angle(angle, hold=hold)

    def set_head_angle(self, angle, pulse_offset_us=0, move_pulses=None, hold_for_ms=0):
        self.head_angle = int(_clamp(angle, -30, 210))
        self._write_servo(
            self.head_servo,
            self.head_angle,
            move_pulses=move_pulses,
            hold_for_ms=hold_for_ms,
            pulse_offset_us=pulse_offset_us,
        )

    def set_claw_angle(self, angle, move_pulses=None, hold_for_ms=0, pulse_offset_us=0):
        self.claw_angle = int(_clamp(angle, 0, 180))
        hold = self.claw_hold_servo_enabled and (
            self.claw_angle >= int(getattr(self.cfg, "CLAW_HOLD_ANGLE", 174) or 174)
        )
        self._write_servo(
            self.claw_servo,
            self.claw_angle,
            hold=hold,
            move_pulses=move_pulses,
            hold_for_ms=hold_for_ms,
            pulse_offset_us=pulse_offset_us,
        )
        self._refresh_face()

    def center_head(self):
        self.head_pose = "center"
        self.set_head_angle(
            getattr(self.cfg, "HEAD_CENTER_ANGLE", 5),
            pulse_offset_us=int(getattr(self.cfg, "HEAD_CENTER_PULSE_OFFSET_US", 0) or 0),
        )
        self._refresh_face()

    def head_left(self):
        self.head_pose = "left"
        self.set_head_angle(
            getattr(self.cfg, "HEAD_LEFT_ANGLE", 65),
            pulse_offset_us=int(getattr(self.cfg, "HEAD_LEFT_PULSE_OFFSET_US", 0) or 0),
        )
        self._refresh_face()

    def head_right(self):
        self.head_pose = "right"
        self.set_head_angle(
            getattr(self.cfg, "HEAD_RIGHT_ANGLE", 0),
            pulse_offset_us=int(getattr(self.cfg, "HEAD_RIGHT_PULSE_OFFSET_US", 0) or 0),
            move_pulses=int(
                getattr(
                    self.cfg,
                    "HEAD_RIGHT_MOVE_PULSES",
                    getattr(self.cfg, "SOFT_HEAD_SERVO_MOVE_PULSES", 30),
                )
                or 30
            ),
        )
        self._refresh_face()

    def open_claw(self):
        self.ball_latched = False
        self.set_claw_angle(
            getattr(self.cfg, "CLAW_OPEN_ANGLE", 156),
            move_pulses=int(
                getattr(
                    self.cfg,
                    "CLAW_RELEASE_MOVE_PULSES",
                    getattr(self.cfg, "SOFT_CLAW_SERVO_MOVE_PULSES", 54),
                )
                or 54
            ),
            hold_for_ms=self.claw_release_hold_ms,
            pulse_offset_us=int(getattr(self.cfg, "CLAW_RELEASE_PULSE_OFFSET_US", -180) or -180),
        )

    def release_claw(self):
        self.ball_latched = False
        self.set_claw_angle(
            getattr(self.cfg, "CLAW_WIDE_OPEN_ANGLE", 138),
            move_pulses=int(
                getattr(
                    self.cfg,
                    "CLAW_RELEASE_MOVE_PULSES",
                    getattr(self.cfg, "SOFT_CLAW_SERVO_MOVE_PULSES", 54),
                )
                or 54
            ),
            hold_for_ms=self.claw_release_hold_ms,
            pulse_offset_us=int(getattr(self.cfg, "CLAW_RELEASE_PULSE_OFFSET_US", -180) or -180),
        )

    def grab_claw(self):
        self.ball_latched = True
        self.set_claw_angle(
            getattr(self.cfg, "CLAW_CLOSED_ANGLE", 180),
            move_pulses=int(
                getattr(
                    self.cfg,
                    "CLAW_GRAB_MOVE_PULSES",
                    getattr(self.cfg, "SOFT_CLAW_SERVO_MOVE_PULSES", 54),
                )
                or 54
            ),
            hold_for_ms=self.claw_grab_hold_ms,
            pulse_offset_us=int(getattr(self.cfg, "CLAW_GRAB_PULSE_OFFSET_US", 120) or 120),
        )

    def hold_claw(self):
        self.ball_latched = True
        self.set_claw_angle(
            getattr(self.cfg, "CLAW_HOLD_ANGLE", 174),
            move_pulses=int(
                getattr(
                    self.cfg,
                    "CLAW_GRAB_MOVE_PULSES",
                    getattr(self.cfg, "SOFT_CLAW_SERVO_MOVE_PULSES", 54),
                )
                or 54
            ),
            hold_for_ms=self.claw_grab_hold_ms,
            pulse_offset_us=int(getattr(self.cfg, "CLAW_GRAB_PULSE_OFFSET_US", 120) or 120),
        )

    def _write_drive(self, left_speed, right_speed):
        self.left_motor.write(int(left_speed))
        self.right_motor.write(int(right_speed))
        self.current_left_speed = int(left_speed)
        self.current_right_speed = int(right_speed)

    def _cancel_release_decel(self):
        self.release_decel_active = False
        self.release_decel_started_ms = 0
        self.release_decel_start_left = 0
        self.release_decel_start_right = 0

    def _arm_manual_watchdog(self):
        timeout_ms = int(max(120, self.manual_command_timeout_ms))
        self.manual_motion_deadline_ms = hw.ticks_add(hw.ticks_ms(), timeout_ms)

    def _disarm_manual_watchdog(self):
        self.manual_motion_deadline_ms = 0

    def drive(self, left_speed, right_speed):
        self._cancel_release_decel()
        self._write_drive(left_speed, right_speed)

    def set_manual_speeds(self, left_value=None, right_value=None):
        if left_value is not None:
            if int(left_value) <= 255:
                left_value = int(left_value) * 4
            self.manual_left_speed = int(_clamp(int(left_value), 0, self.cfg.MAX_PWM))
        if right_value is not None:
            if int(right_value) <= 255:
                right_value = int(right_value) * 4
            self.manual_right_speed = int(_clamp(int(right_value), 0, self.cfg.MAX_PWM))

    def forward(self):
        self.mode = "manual"
        self.motion_state = "forward"
        self._arm_manual_watchdog()
        self.drive(self.manual_left_speed, self.manual_right_speed)
        self._refresh_face()
        return "drive:forward:%d" % max(self.manual_left_speed, self.manual_right_speed)

    def backward(self):
        self.mode = "manual"
        self.motion_state = "backward"
        self._arm_manual_watchdog()
        self.drive(-self.reverse_speed, -self.reverse_speed)
        self._refresh_face()
        return "drive:backward:%d" % self.reverse_speed

    def left(self):
        self.mode = "manual"
        self.motion_state = "left"
        self._arm_manual_watchdog()
        self.drive(-self.turn_speed, self.turn_speed)
        self._refresh_face()
        return "drive:left:%d" % self.turn_speed

    def right(self):
        self.mode = "manual"
        self.motion_state = "right"
        self._arm_manual_watchdog()
        self.drive(self.turn_speed, -self.turn_speed)
        self._refresh_face()
        return "drive:right:%d" % self.turn_speed

    def stop(self, immediate=False):
        self._disarm_manual_watchdog()
        if immediate or (self.current_left_speed == 0 and self.current_right_speed == 0):
            self._cancel_release_decel()
            self._write_drive(0, 0)
        else:
            self.release_decel_active = True
            self.release_decel_started_ms = hw.ticks_ms()
            self.release_decel_start_left = int(self.current_left_speed)
            self.release_decel_start_right = int(self.current_right_speed)
        self.motion_state = "idle"
        self._refresh_face()
        return "drive:stop"

    def _tick_release_decel(self, now_ms):
        if not self.release_decel_active:
            return
        elapsed = hw.ticks_diff(now_ms, self.release_decel_started_ms)
        duration = max(1, self.release_decel_duration_ms)
        if elapsed >= duration:
            self._cancel_release_decel()
            self._write_drive(0, 0)
            self._refresh_face()
            return
        remaining = duration - elapsed
        left = int((self.release_decel_start_left * remaining) / duration)
        right = int((self.release_decel_start_right * remaining) / duration)
        self._write_drive(left, right)

    def _tick_manual_watchdog(self, now_ms):
        if not self.manual_motion_deadline_ms:
            return
        if self.script_name:
            self._disarm_manual_watchdog()
            return
        if self.motion_state not in ("forward", "backward", "left", "right"):
            self._disarm_manual_watchdog()
            return
        if hw.ticks_diff(now_ms, self.manual_motion_deadline_ms) >= 0:
            self.stop(immediate=True)

    def _start_kick(self):
        self.mode = "manual"
        self._disarm_manual_watchdog()
        self.script_name = "kick"
        self.script_phase = "charge"
        self.script_started_ms = hw.ticks_ms()
        self.script_phase_started_ms = self.script_started_ms
        self.hold_claw()
        self.motion_state = "forward"
        self.drive(int(self.kick_profile[2]), int(self.kick_profile[2]))
        self._refresh_face()
        return "kick:armed"

    def _tick_kick(self, now_ms):
        if self.script_name != "kick":
            return
        drop_angle, reverse_ms, ram_pwm, ram_ms, settle_ms = self.kick_profile
        elapsed = hw.ticks_diff(now_ms, self.script_phase_started_ms)
        if self.script_phase == "charge":
            self.drive(int(ram_pwm), int(ram_pwm))
            if elapsed >= int(ram_ms):
                self.script_phase = "release"
                self.script_phase_started_ms = now_ms
                self.ball_latched = False
                self.set_claw_angle(int(drop_angle))
                self._refresh_face()
            return
        if self.script_phase == "release":
            if elapsed >= int(reverse_ms):
                self.script_phase = "decel"
                self.script_phase_started_ms = now_ms
                self.stop(immediate=False)
            return
        if self.script_phase == "decel":
            if not self.release_decel_active and elapsed >= int(settle_ms):
                self.script_name = ""
                self.script_phase = ""
                self.motion_state = "idle"
                self.open_claw()
                self._refresh_face()

    def _control_state(self):
        if self.script_name == "kick":
            return "script-%s" % self.script_phase
        if self.release_decel_active:
            return "manual-braking"
        if self.motion_state == "forward":
            return "manual-forward"
        if self.motion_state == "backward":
            return "manual-backward"
        if self.motion_state == "left":
            return "manual-left"
        if self.motion_state == "right":
            return "manual-right"
        return "manual-idle"

    def summary(self):
        return {
            "mode": self.mode,
            "control_state": self._control_state(),
            "auto_state": self.auto_state,
            "auto_paused": self.auto_paused,
            "manual_left_speed": self.manual_left_speed,
            "manual_right_speed": self.manual_right_speed,
            "current_left_speed": self.current_left_speed,
            "current_right_speed": self.current_right_speed,
            "display_face": self.face_name,
            "head_pose": self.head_pose,
            "head_angle": self.head_angle,
            "lights": False,
            "lights_scene": "shadow",
            "lights_mode": "shadow",
            "lights_hw_enabled": False,
            "lights_preview": (),
            "sonar_cm": -1,
            "forward_guard_state": "disabled",
            "forward_limit_pwm": max(self.manual_left_speed, self.manual_right_speed),
            "manual_release_decel_active": self.release_decel_active,
            "script": self.script_name,
            "script_phase": self.script_phase,
            "captured_ball": bool(self.ball_latched),
        }

    def mqtt_summary(self):
        summary = self.summary()
        return {
            "mode": summary["mode"],
            "control_state": summary["control_state"],
            "display_face": summary["display_face"],
            "manual_left_speed": summary["manual_left_speed"],
            "manual_right_speed": summary["manual_right_speed"],
            "current_left_speed": summary["current_left_speed"],
            "current_right_speed": summary["current_right_speed"],
            "head_pose": summary["head_pose"],
            "head_angle": summary["head_angle"],
            "manual_release_decel_active": summary["manual_release_decel_active"],
            "script": summary["script"],
            "script_phase": summary["script_phase"],
            "captured_ball": summary["captured_ball"],
        }

    def _update_slider_path(self, path):
        if path.startswith("/btn/u"):
            try:
                value = int(path[6:])
            except Exception:
                value = None
            if value is not None:
                self.set_manual_speeds(left_value=value)
                return "speed:left:%d" % self.manual_left_speed
        if path.startswith("/btn/v"):
            try:
                value = int(path[6:])
            except Exception:
                value = None
            if value is not None:
                self.set_manual_speeds(right_value=value)
                return "speed:right:%d" % self.manual_right_speed
        return None

    def handle_path(self, path):
        slider_result = self._update_slider_path(path)
        if slider_result is not None:
            return slider_result
        if path == getattr(self.cfg, "BUTTON_FORWARD", "/btn/F"):
            return self.forward()
        if path == getattr(self.cfg, "BUTTON_BACKWARD", "/btn/B"):
            return self.backward()
        if path == getattr(self.cfg, "BUTTON_LEFT", "/btn/L"):
            return self.left()
        if path == getattr(self.cfg, "BUTTON_RIGHT", "/btn/R"):
            return self.right()
        if path == getattr(self.cfg, "BUTTON_STOP", "/btn/S"):
            return self.stop(immediate=True)
        if path in getattr(self.cfg, "BUTTON_MANUAL_MODE_ALIASES", ()):
            self.mode = "manual"
            self.auto_paused = True
            self.script_name = ""
            self.script_phase = ""
            self.stop(immediate=True)
            return "mode:manual"
        if path in getattr(self.cfg, "BUTTON_AUTO_MODE_ALIASES", ()):
            self.mode = "auto"
            self.auto_paused = True
            self._disarm_manual_watchdog()
            self.stop(immediate=True)
            return "mode:auto-paused"
        if path in getattr(self.cfg, "BUTTON_STOP_AUTO_ALIASES", ()):
            self.auto_paused = True
            self._disarm_manual_watchdog()
            self.stop(immediate=True)
            return "auto:stop"
        if path in getattr(self.cfg, "BUTTON_PAN_LEFT_ALIASES", ()):
            self.head_left()
            return "head:left"
        if path in getattr(self.cfg, "BUTTON_PAN_CENTER_ALIASES", ()):
            self.center_head()
            return "head:center"
        if path in getattr(self.cfg, "BUTTON_PAN_RIGHT_ALIASES", ()):
            self.head_right()
            return "head:right"
        if path in getattr(self.cfg, "BUTTON_GRAB_ALIASES", ()):
            self.grab_claw()
            return "claw:grab"
        if path in getattr(self.cfg, "BUTTON_RELEASE_ALIASES", ()):
            self.release_claw()
            return "claw:release"
        if path in getattr(self.cfg, "BUTTON_RAM_KICK_ALIASES", ()):
            return self._start_kick()
        if path in getattr(self.cfg, "BUTTON_OK_ALIASES", ()):
            self.hold_claw()
            return "claw:hold"
        return "unknown:%s" % path

    def update(self):
        now_ms = hw.ticks_ms()
        self.left_motor.pump(now_ms)
        self.right_motor.pump(now_ms)
        self.head_servo.pump(now_ms)
        self.claw_servo.pump(now_ms)
        self._tick_manual_watchdog(now_ms)
        self._tick_release_decel(now_ms)
        self._tick_kick(now_ms)
        self._refresh_face()

    def idle_window(self, duration_ms):
        remaining = int(max(0, duration_ms))
        while remaining > 0:
            start_ms = hw.ticks_ms()
            self.update()
            slice_ms = 4 if remaining > 4 else remaining
            hw.sleep_ms(slice_ms)
            elapsed = hw.ticks_diff(hw.ticks_ms(), start_ms)
            if elapsed <= 0:
                elapsed = slice_ms
            remaining -= elapsed

    def shutdown(self):
        self.stop(immediate=True)
        self.left_motor.shutdown()
        self.right_motor.shutdown()
        self.head_servo.shutdown()
        self.claw_servo.shutdown()
