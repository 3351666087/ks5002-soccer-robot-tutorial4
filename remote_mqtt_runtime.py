import compat as hw
from compat import Pin, PWM


def _clamp(value, lower, upper):
    if value < lower:
        return lower
    if value > upper:
        return upper
    return value


def _hex_color(color):
    return "#%02X%02X%02X" % (
        int(_clamp(color[0], 0, 255)),
        int(_clamp(color[1], 0, 255)),
        int(_clamp(color[2], 0, 255)),
    )


class ShadowLights:
    SCENES = {
        "manual_idle": ((10, 8, 26), (0, 18, 34), (0, 24, 18), (18, 0, 18)),
        "network_lost": ((2, 10, 28), (0, 0, 10), (0, 0, 10), (2, 10, 28)),
        "hold_ball": ((28, 16, 0), (40, 22, 8), (40, 22, 8), (28, 16, 0)),
        "guard_slow": ((18, 10, 0), (38, 20, 8), (38, 20, 8), (18, 10, 0)),
        "guard_stop": ((56, 12, 0), (56, 18, 0), (56, 18, 0), (56, 12, 0)),
        "kick_charge": ((12, 8, 0), (40, 18, 0), (56, 26, 6), (30, 10, 0)),
        "kick_seek": ((0, 16, 34), (0, 28, 54), (10, 42, 18), (0, 20, 40)),
        "drive_backward": ((28, 0, 8), (48, 6, 18), (56, 16, 0), (18, 8, 0)),
        "turn_left": ((56, 20, 0), (0, 2, 10), (42, 14, 0), (0, 2, 10)),
        "turn_right": ((0, 2, 10), (22, 0, 44), (0, 2, 10), (18, 0, 56)),
        "auto_paused": ((30, 18, 0), (12, 4, 0), (30, 18, 0), (12, 4, 0)),
        "brake": ((18, 6, 6), (56, 18, 6), (56, 18, 6), (18, 6, 6)),
        "grab_burst": ((42, 18, 0), (56, 34, 8), (56, 34, 8), (42, 18, 0)),
        "release_burst": ((0, 22, 40), (0, 48, 56), (0, 48, 56), (0, 22, 40)),
        "pan_left": ((24, 10, 44), (0, 4, 10), (18, 8, 32), (0, 4, 10)),
        "pan_center": ((0, 4, 12), (18, 30, 56), (18, 30, 56), (0, 4, 12)),
        "pan_right": ((0, 4, 10), (24, 8, 38), (0, 4, 10), (30, 10, 50)),
        "speed_left": ((0, 10, 28), (0, 24, 56), (0, 10, 18), (0, 8, 10)),
        "speed_right": ((10, 0, 8), (18, 0, 12), (26, 0, 56), (12, 0, 28)),
        "face_demo": ((56, 0, 28), (0, 56, 42), (22, 22, 56), (56, 44, 0)),
        "mode_shift": ((40, 40, 40), (8, 18, 34), (40, 40, 40), (8, 18, 34)),
    }

    def __init__(self, config_module):
        self.cfg = config_module
        self.base_scene = "manual_idle"
        self.overlay_scene = None
        self.overlay_until = None
        self.last_pixels = self._scene_pixels(self.base_scene)

    def available(self):
        return False

    def mode_name(self):
        return "shadow"

    def hardware_enabled(self):
        return False

    def scene_name(self):
        if self.overlay_scene is not None:
            return self.overlay_scene
        return self.base_scene

    def set_base(self, scene):
        if not scene:
            return
        self.base_scene = str(scene)
        self.last_pixels = self._scene_pixels(self.scene_name())

    def flash(self, scene, duration_ms=None):
        if not scene:
            return
        if duration_ms is None:
            duration_ms = int(getattr(self.cfg, "LIGHT_BURST_MS", 680) or 680)
        self.overlay_scene = str(scene)
        self.overlay_until = hw.ticks_add(hw.ticks_ms(), int(duration_ms))
        self.last_pixels = self._scene_pixels(self.scene_name())

    def tick(self):
        now = hw.ticks_ms()
        if self.overlay_until is not None and hw.ticks_diff(now, self.overlay_until) >= 0:
            self.overlay_scene = None
            self.overlay_until = None
        self.last_pixels = self._scene_pixels(self.scene_name())

    def preview_hex(self):
        return [_hex_color(color) for color in self.last_pixels]

    def _scene_pixels(self, scene):
        pixels = self.SCENES.get(scene) or self.SCENES["manual_idle"]
        limit = int(getattr(self.cfg, "LIGHT_MAX_BRIGHTNESS", 56) or 56)
        capped = []
        index = 0
        while index < 4:
            color = pixels[index]
            capped.append(
                (
                    int(_clamp(color[0], 0, limit)),
                    int(_clamp(color[1], 0, limit)),
                    int(_clamp(color[2], 0, limit)),
                )
            )
            index += 1
        return tuple(capped)

    def shutdown(self):
        return


class HardwareMotorChannel:
    def __init__(self, dir_pin_num, pwm_pin_num, freq, max_pwm):
        self.max_pwm = int(max(1, max_pwm))
        self.direction_pin = Pin(dir_pin_num, Pin.OUT)
        self.pwm = PWM(Pin(pwm_pin_num), freq=int(freq), duty=0)

    def write(self, speed):
        speed = int(_clamp(speed, -self.max_pwm, self.max_pwm))
        if speed >= 0:
            self.direction_pin.value(0)
            self.pwm.duty(speed)
        else:
            self.direction_pin.value(1)
            self.pwm.duty(-speed)

    def pump(self, now_ms):
        del now_ms

    def shutdown(self):
        try:
            self.pwm.duty(0)
        except Exception:
            pass
        try:
            self.direction_pin.value(0)
        except Exception:
            pass


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
            if self.enable_state:
                self.enable_pin.value(0)
                self.enable_state = 0
            return
        self.direction_pin.value(0 if speed >= 0 else 1)

    def pump(self, now_ms):
        del now_ms
        speed = int(self.speed)
        if speed == 0:
            if self.enable_state:
                self.enable_pin.value(0)
                self.enable_state = 0
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


class HardwareServoChannel:
    def __init__(self, pin_num, freq):
        self.servo = PWM(Pin(pin_num), freq=int(freq))

    def write_angle(self, angle):
        angle = _clamp(int(angle), 0, 180)
        pulse_width_ms = 0.5 + (angle / 180.0) * 2.0
        pulse_ns = int(pulse_width_ms * 1_000_000)
        if hasattr(self.servo, "duty_ns"):
            self.servo.duty_ns(pulse_ns)
            return
        if hasattr(self.servo, "duty_u16"):
            self.servo.duty_u16(int((pulse_ns / 20_000_000.0) * 65535))
            return
        self.servo.duty(int((pulse_ns / 20_000_000.0) * 1023))

    def pump(self, now_ms):
        del now_ms

    def shutdown(self):
        return


class SoftServoChannel:
    def __init__(self, pin_num, refresh_ms=22, move_pulses=18, hold_refresh_ms=30):
        self.pin = Pin(pin_num, Pin.OUT, value=0)
        self.refresh_ms = max(18, int(refresh_ms))
        self.move_pulses = max(1, int(move_pulses))
        self.hold_refresh_ms = max(self.refresh_ms, int(hold_refresh_ms))
        self.pulse_us = 1500
        self.next_pulse_ms = hw.ticks_ms()
        self.pending_pulses = 0
        self.hold_enabled = False
        self.last_pulse_ms = None

    def _pulse_us_for_angle(self, angle):
        angle = _clamp(int(angle), 0, 180)
        pulse_width_ms = 0.5 + (angle / 180.0) * 2.0
        return int(pulse_width_ms * 1000)

    def write_angle(self, angle, hold=False):
        self.pulse_us = self._pulse_us_for_angle(angle)
        self.pending_pulses = self.move_pulses
        self.hold_enabled = bool(hold)
        now = hw.ticks_ms()
        if self.last_pulse_ms is None or hw.ticks_diff(now, self.next_pulse_ms) >= 0:
            self.next_pulse_ms = now

    def pump(self, now_ms):
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
            refresh_ms = self.refresh_ms
        else:
            refresh_ms = self.hold_refresh_ms
        self.next_pulse_ms = hw.ticks_add(now_ms, refresh_ms)

    def shutdown(self):
        self.pending_pulses = 0
        self.hold_enabled = False
        try:
            self.pin.value(0)
        except Exception:
            pass


class RemoteCar:
    FACE_CYCLE = ("manual", "front", "back", "left", "right", "stop", "capture", "thinking", "cry")

    def __init__(self, config_module):
        self.cfg = config_module
        self.actuator_backend = self._resolve_actuator_backend()
        self.soft_actuators = self.actuator_backend == "soft"
        self.soft_slice_ms = max(1, int(getattr(config_module, "SOFT_DRIVE_SLICE_MS", 2) or 2))

        if self.soft_actuators:
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
                refresh_ms=int(getattr(config_module, "SOFT_SERVO_REFRESH_MS", 22) or 22),
                move_pulses=int(getattr(config_module, "SOFT_SERVO_MOVE_PULSES", 18) or 18),
                hold_refresh_ms=int(getattr(config_module, "SOFT_SERVO_HOLD_REFRESH_MS", 30) or 30),
            )
            self.claw_servo = SoftServoChannel(
                config_module.CLAW_SERVO_PIN,
                refresh_ms=int(getattr(config_module, "SOFT_SERVO_REFRESH_MS", 22) or 22),
                move_pulses=int(getattr(config_module, "SOFT_SERVO_MOVE_PULSES", 18) or 18),
                hold_refresh_ms=int(getattr(config_module, "SOFT_SERVO_HOLD_REFRESH_MS", 30) or 30),
            )
        else:
            self.left_motor = HardwareMotorChannel(
                config_module.LEFT_DIR_PIN,
                config_module.LEFT_PWM_PIN,
                config_module.MOTOR_FREQ,
                config_module.MAX_PWM,
            )
            self.right_motor = HardwareMotorChannel(
                config_module.RIGHT_DIR_PIN,
                config_module.RIGHT_PWM_PIN,
                config_module.MOTOR_FREQ,
                config_module.MAX_PWM,
            )
            self.head_servo = HardwareServoChannel(
                config_module.HEAD_SERVO_PIN,
                config_module.SERVO_FREQ,
            )
            self.claw_servo = HardwareServoChannel(
                config_module.CLAW_SERVO_PIN,
                config_module.SERVO_FREQ,
            )
        try:
            self.trig = Pin(config_module.SONAR_TRIG_PIN, Pin.OUT, value=0)
            self.echo = Pin(config_module.SONAR_ECHO_PIN, Pin.IN)
        except Exception:
            self.trig = None
            self.echo = None

        self.mode = "manual"
        self.auto_paused = True
        self.auto_state = "idle"
        self.manual_left_speed = int(config_module.MANUAL_SPEED)
        self.manual_right_speed = int(config_module.MANUAL_SPEED)
        self.head_angle = int(config_module.HEAD_CENTER_ANGLE)
        self.claw_angle = int(config_module.CLAW_OPEN_ANGLE)
        self.motion_state = "idle"
        self.network_station_connected = True
        self.manual_motion_until = None
        self.current_left_speed = 0
        self.current_right_speed = 0
        self.release_decel_active = False
        self.release_decel_started_ms = None
        self.release_decel_duration_ms = int(getattr(config_module, "MANUAL_RELEASE_DECEL_MS", 280) or 280)
        self.release_decel_start_left = 0
        self.release_decel_start_right = 0
        self.release_decel_motion_state = "idle"
        self.script_name = None
        self.script_phase = ""
        self.script_started_ms = None
        self.script_phase_started_ms = None
        self.face_name = "manual"
        self.face_cycle_index = 0
        self.lights = ShadowLights(config_module)

        self.front_distance_cm = -1
        self.front_distance_raw_cm = -1
        self.front_guard_distance_cm = -1
        self.forward_limit_pwm = max(self.manual_left_speed, self.manual_right_speed)
        self.forward_guard_state = "clear"
        self.forward_head_locked = False

        self.center_head()
        self.open_claw()
        self.stop()
        self._refresh_visuals()

    def _resolve_actuator_backend(self):
        selected = str(getattr(self.cfg, "ACTUATOR_BACKEND", "auto") or "auto").strip().lower()
        if selected in ("soft", "software"):
            return "soft"
        if selected in ("hardware", "pwm"):
            return "hardware"
        return "soft"

    def _clamp_pwm(self, value):
        return int(_clamp(value, 0, self.cfg.MAX_PWM))

    def _servo_pulse_ns(self, angle):
        angle = _clamp(int(angle), 0, 180)
        pulse_width_ms = 0.5 + (angle / 180.0) * 2.0
        return int(pulse_width_ms * 1_000_000)

    def _write_servo(self, servo, angle):
        hold = False
        if servo is self.claw_servo and int(angle) >= int(self.cfg.CLAW_HOLD_ANGLE):
            hold = True
        try:
            servo.write_angle(angle, hold=hold)
        except TypeError:
            servo.write_angle(angle)

    def set_head_angle(self, angle):
        self.head_angle = int(_clamp(angle, 0, 180))
        self._write_servo(self.head_servo, self.head_angle)

    def set_claw_angle(self, angle):
        self.claw_angle = int(_clamp(angle, 0, 180))
        self._write_servo(self.claw_servo, self.claw_angle)

    def center_head(self):
        self.set_head_angle(self.cfg.HEAD_CENTER_ANGLE)

    def head_left(self):
        self.set_head_angle(self.cfg.HEAD_LEFT_ANGLE)

    def head_right(self):
        self.set_head_angle(self.cfg.HEAD_RIGHT_ANGLE)

    def close_claw(self):
        self.set_claw_angle(self.cfg.CLAW_CLOSED_ANGLE)

    def hold_claw(self):
        self.set_claw_angle(self.cfg.CLAW_HOLD_ANGLE)

    def open_claw(self):
        self.set_claw_angle(self.cfg.CLAW_OPEN_ANGLE)

    def open_claw_wide(self):
        self.set_claw_angle(self.cfg.CLAW_WIDE_OPEN_ANGLE)

    def set_network_connected(self, connected):
        self.network_station_connected = bool(connected)
        self._refresh_visuals()

    def note_transport_state(self, online, error=""):
        del online, error

    def _refresh_visuals(self):
        scene = "manual_idle"
        if not self.network_station_connected:
            self.face_name = "cry"
            scene = "network_lost"
        elif self.script_name == "kick":
            if self.script_phase in ("charge", "release", "decel"):
                self.face_name = "capture"
                scene = "kick_charge"
            else:
                self.face_name = "front"
                scene = "kick_seek"
        elif self.mode == "auto":
            self.face_name = "thinking" if not self.auto_paused else "manual"
            scene = "auto_paused" if self.auto_paused else "manual_idle"
        elif self.release_decel_active:
            self.face_name = "stop"
            scene = "brake"
        elif self.motion_state == "forward":
            if self.forward_guard_state == "blocked":
                self.face_name = "stop"
                scene = "guard_stop"
            elif self.forward_guard_state == "slowdown":
                self.face_name = "front"
                scene = "guard_slow"
            else:
                self.face_name = "front"
                scene = "manual_idle"
        elif self.motion_state == "backward":
            self.face_name = "back"
            scene = "drive_backward"
        elif self.motion_state == "left":
            self.face_name = "left"
            scene = "turn_left"
        elif self.motion_state == "right":
            self.face_name = "right"
            scene = "turn_right"
        elif self.claw_angle >= self.cfg.CLAW_HOLD_ANGLE:
            self.face_name = "capture"
            scene = "hold_ball"
        else:
            self.face_name = "manual"
            scene = "manual_idle"
        self.lights.set_base(scene)

    def set_manual_speeds(self, left_value=None, right_value=None):
        if left_value is not None:
            if left_value <= 255:
                left_value = int(left_value * 4)
            self.manual_left_speed = int(_clamp(left_value, 0, self.cfg.MAX_PWM))
            self.lights.flash("speed_left", 420)
        if right_value is not None:
            if right_value <= 255:
                right_value = int(right_value * 4)
            self.manual_right_speed = int(_clamp(right_value, 0, self.cfg.MAX_PWM))
            self.lights.flash("speed_right", 420)
        if self.motion_state != "forward":
            self.forward_limit_pwm = max(self.manual_left_speed, self.manual_right_speed)

    def _set_wheel(self, direction_pin, pwm_pin, speed):
        del direction_pin
        pwm_pin.write(speed)

    def _cancel_release_decel(self):
        self.release_decel_active = False
        self.release_decel_started_ms = None
        self.release_decel_start_left = 0
        self.release_decel_start_right = 0
        self.release_decel_motion_state = "idle"

    def _write_drive(self, left_speed, right_speed):
        self._set_wheel(None, self.left_motor, left_speed)
        self._set_wheel(None, self.right_motor, right_speed)
        self.current_left_speed = int(left_speed)
        self.current_right_speed = int(right_speed)

    def drive(self, left_speed, right_speed):
        self._cancel_release_decel()
        self._write_drive(left_speed, right_speed)

    def stop(self):
        self._cancel_release_decel()
        self._write_drive(0, 0)
        self.motion_state = "idle"
        self.forward_head_locked = False
        self.forward_guard_state = "clear"
        self.forward_limit_pwm = max(self.manual_left_speed, self.manual_right_speed)

    def _start_release_decel(self):
        if self.release_decel_active:
            return "drive:coast"
        if self.script_name is not None:
            self.stop()
            return "drive:stop"
        if self.motion_state not in ("forward", "backward", "left", "right"):
            self.stop()
            return "drive:stop"
        if self.current_left_speed == 0 and self.current_right_speed == 0:
            self.stop()
            return "drive:stop"
        self.release_decel_active = True
        self.release_decel_started_ms = hw.ticks_ms()
        self.release_decel_start_left = int(self.current_left_speed)
        self.release_decel_start_right = int(self.current_right_speed)
        self.release_decel_motion_state = self.motion_state
        self.manual_motion_until = None
        self.face_name = "stop"
        self.lights.flash("brake", 420)
        self._refresh_visuals()
        return "drive:coast"

    def _update_release_decel(self, now):
        if not self.release_decel_active or self.release_decel_started_ms is None:
            return
        duration = max(40, int(self.release_decel_duration_ms))
        elapsed = hw.ticks_diff(now, self.release_decel_started_ms)
        if elapsed >= duration:
            self.stop()
            self._refresh_visuals()
            return
        remaining = max(0, duration - elapsed)
        left_speed = (self.release_decel_start_left * remaining) // duration
        right_speed = (self.release_decel_start_right * remaining) // duration
        self.motion_state = self.release_decel_motion_state
        self._write_drive(left_speed, right_speed)

    def _arm_manual_timeout(self):
        self.manual_motion_until = hw.ticks_add(hw.ticks_ms(), self.cfg.MANUAL_COMMAND_TIMEOUT_MS)

    def sonar_available(self):
        return self.trig is not None and self.echo is not None

    def measure_distance_cm(self, timeout_us=None):
        if not self.sonar_available():
            return -1
        if timeout_us is None:
            timeout_us = int(getattr(self.cfg, "SONAR_TIMEOUT_US", 30000) or 30000)

        self.trig.value(0)
        hw.sleep_us(2)
        self.trig.value(1)
        hw.sleep_us(10)
        self.trig.value(0)

        started = hw.ticks_us()
        while self.echo.value() == 0:
            if hw.ticks_diff_us(hw.ticks_us(), started) > timeout_us:
                return -1

        pulse_start = hw.ticks_us()
        while self.echo.value() == 1:
            if hw.ticks_diff_us(hw.ticks_us(), pulse_start) > timeout_us:
                return -1

        pulse_end = hw.ticks_us()
        pulse_width = hw.ticks_diff_us(pulse_end, pulse_start)
        distance_cm = int((pulse_width * 34) // 2000)
        if distance_cm <= 0:
            return -1
        return distance_cm

    def measure_distance_filtered(self, samples=None):
        if samples is None:
            samples = int(getattr(self.cfg, "SONAR_SAMPLES_FORWARD", 2) or 2)
        readings = []
        index = 0
        while index < samples:
            value = self.measure_distance_cm()
            if value > 0:
                readings.append(value)
            hw.sleep_ms(self.cfg.MEASURE_GAP_MS)
            index += 1
        if not readings:
            return -1
        readings.sort()
        return readings[len(readings) // 2]

    def _sample_forward_scene(self, force=False):
        if not self.sonar_available():
            self.front_distance_raw_cm = -1
            self.front_distance_cm = -1
            self.front_guard_distance_cm = -1
            self.forward_head_locked = False
            return -1
        if force or abs(int(self.head_angle) - int(self.cfg.HEAD_CENTER_ANGLE)) > 1:
            self.center_head()
            self.forward_head_locked = True
            hw.sleep_ms(int(getattr(self.cfg, "FORWARD_HEAD_SETTLE_MS", 120) or 120))
        else:
            self.forward_head_locked = True
        distance_cm = self.measure_distance_filtered()
        self.front_distance_raw_cm = distance_cm
        self.front_distance_cm = distance_cm
        self.front_guard_distance_cm = distance_cm
        return distance_cm

    def _forward_speed_cap(self, distance_cm, requested_pwm):
        requested_pwm = int(_clamp(requested_pwm, 0, self.cfg.MAX_PWM))
        if requested_pwm <= 0:
            return 0
        if distance_cm <= 0:
            return requested_pwm

        stop_cm = int(getattr(self.cfg, "FORWARD_STOP_CM", 9) or 9)
        crawl_cm = max(stop_cm + 1, int(getattr(self.cfg, "FORWARD_CRAWL_CM", 14) or 14))
        slow_cm = max(crawl_cm + 1, int(getattr(self.cfg, "FORWARD_SLOWDOWN_CM", 34) or 34))
        if distance_cm <= stop_cm:
            return 0
        if distance_cm >= slow_cm:
            return requested_pwm

        min_pwm = min(requested_pwm, int(getattr(self.cfg, "FORWARD_MIN_PWM", 220) or 220))
        near_pwm = min(requested_pwm, max(min_pwm, int(getattr(self.cfg, "FORWARD_NEAR_PWM", 340) or 340)))
        if distance_cm <= crawl_cm:
            span = max(1, crawl_cm - stop_cm)
            boost = max(0, near_pwm - min_pwm)
            return min_pwm + ((distance_cm - stop_cm) * boost) // span

        span = max(1, slow_cm - crawl_cm)
        extra = max(0, requested_pwm - near_pwm)
        return near_pwm + ((distance_cm - crawl_cm) * extra) // span

    def _apply_forward_motion(self, force_sample=False, arm_timeout=False, base_left=None, base_right=None):
        if base_left is None:
            base_left = self.manual_left_speed
        if base_right is None:
            base_right = self.manual_right_speed
        requested_pwm = max(int(base_left), int(base_right))
        distance_cm = self._sample_forward_scene(force=force_sample)
        limit_pwm = self._forward_speed_cap(distance_cm, requested_pwm)
        self.forward_limit_pwm = limit_pwm
        if limit_pwm <= 0:
            self.forward_guard_state = "blocked"
            self.stop()
            self.manual_motion_until = None
            self._refresh_visuals()
            if distance_cm > 0:
                return "drive:blocked:%dcm" % distance_cm
            return "drive:blocked"

        self.forward_guard_state = "slowdown" if 0 < limit_pwm < requested_pwm else "clear"
        left_pwm = int(base_left)
        right_pwm = int(base_right)
        requested_max = max(left_pwm, right_pwm, 1)
        if requested_max > limit_pwm:
            left_pwm = (left_pwm * limit_pwm) // requested_max
            right_pwm = (right_pwm * limit_pwm) // requested_max
        self.drive(left_pwm, right_pwm)
        self.motion_state = "forward"
        if arm_timeout:
            self._arm_manual_timeout()
        self._refresh_visuals()
        if distance_cm > 0:
            return "drive:forward:%dcm:%d" % (distance_cm, limit_pwm)
        return "drive:forward:%d" % limit_pwm

    def _pivot_turn(self, direction, arm_timeout=False):
        self.forward_head_locked = False
        self.forward_guard_state = "clear"
        self.forward_limit_pwm = max(self.manual_left_speed, self.manual_right_speed)
        speed = int(_clamp(self.cfg.TURN_SPEED, 0, self.cfg.MAX_PWM))
        if direction == "left":
            self.drive(-speed, speed)
            self.motion_state = "left"
        else:
            self.drive(speed, -speed)
            self.motion_state = "right"
        if arm_timeout:
            self._arm_manual_timeout()
        self._refresh_visuals()
        return "drive:%s" % direction

    def _update_slider_path(self, path):
        if path.startswith("/btn/u") and len(path) > 6:
            try:
                self.set_manual_speeds(left_value=int(path[6:]))
            except ValueError:
                return None
            return "speed:left=%d" % self.manual_left_speed
        if path.startswith("/btn/v") and len(path) > 6:
            try:
                self.set_manual_speeds(right_value=int(path[6:]))
            except ValueError:
                return None
            return "speed:right=%d" % self.manual_right_speed
        return None

    def handle_ok_button(self):
        if self.mode == "auto":
            self.auto_paused = not self.auto_paused
            self.stop()
            self.lights.flash("mode_shift", 520)
            self._refresh_visuals()
            return "auto:%s" % ("pause" if self.auto_paused else "resume")
        if self.claw_angle >= self.cfg.CLAW_HOLD_ANGLE:
            self.open_claw()
            self.lights.flash("release_burst", 540)
            self._refresh_visuals()
            return "claw:release"
        self.close_claw()
        self.lights.flash("grab_burst", 620)
        self._refresh_visuals()
        return "claw:grab"

    def preview_faces(self):
        self.face_cycle_index = 0
        self.face_name = self.FACE_CYCLE[self.face_cycle_index]
        self.lights.flash("face_demo", 1800)
        return "face:demo"

    def next_face(self):
        self.face_cycle_index = (self.face_cycle_index + 1) % len(self.FACE_CYCLE)
        self.face_name = self.FACE_CYCLE[self.face_cycle_index]
        return "face:%s" % self.face_name

    def prev_face(self):
        self.face_cycle_index = (self.face_cycle_index - 1) % len(self.FACE_CYCLE)
        self.face_name = self.FACE_CYCLE[self.face_cycle_index]
        return "face:%s" % self.face_name

    def clear_face(self):
        self.face_name = "manual" if self.network_station_connected else "cry"
        return "face:clear"

    def _start_kick_script(self):
        if self.claw_angle < self.cfg.CLAW_HOLD_ANGLE:
            return "kick:no-ball"
        now = hw.ticks_ms()
        self.script_name = "kick"
        self.script_phase = "charge"
        self.script_started_ms = now
        self.script_phase_started_ms = now
        self.manual_motion_until = None
        self.lights.flash("kick_charge", 380)
        self._refresh_visuals()
        return "kick:armed"

    def _set_script_phase(self, phase):
        self.script_phase = phase
        self.script_phase_started_ms = hw.ticks_ms()

    def _stop_script(self):
        self.script_name = None
        self.script_phase = ""
        self.script_started_ms = None
        self.script_phase_started_ms = None

    def _update_kick_script(self, now):
        if self.script_name != "kick":
            return

        phase_elapsed = hw.ticks_diff(now, self.script_phase_started_ms)
        if self.script_phase == "charge":
            charge_pwm = int(_clamp(getattr(self.cfg, "KICK_CHARGE_PWM", 920) or 920, 0, self.cfg.MAX_PWM))
            self._apply_forward_motion(force_sample=True, arm_timeout=False, base_left=charge_pwm, base_right=charge_pwm)
            if phase_elapsed >= int(getattr(self.cfg, "KICK_CHARGE_MS", 240) or 240):
                self.open_claw_wide()
                self.lights.flash("release_burst", 260)
                self._set_script_phase("release")
            return

        if self.script_phase == "release":
            release_pwm = int(_clamp(getattr(self.cfg, "KICK_RELEASE_PWM", 980) or 980, 0, self.cfg.MAX_PWM))
            self.drive(release_pwm, release_pwm)
            self.motion_state = "forward"
            self._refresh_visuals()
            if phase_elapsed >= int(getattr(self.cfg, "KICK_RELEASE_MS", 150) or 150):
                self._set_script_phase("decel")
            return

        if self.script_phase == "decel":
            decel_pwm = int(_clamp(getattr(self.cfg, "KICK_DECEL_PWM", 360) or 360, 0, self.cfg.MAX_PWM))
            self.drive(decel_pwm, decel_pwm)
            self.motion_state = "forward"
            self._refresh_visuals()
            if phase_elapsed >= int(getattr(self.cfg, "KICK_DECEL_MS", 220) or 220):
                self.open_claw()
                self._set_script_phase("seek")
            return

        if self.script_phase == "seek":
            seek_pwm = int(_clamp(getattr(self.cfg, "KICK_SEEK_PWM", 460) or 460, 0, self.cfg.MAX_PWM))
            self._apply_forward_motion(force_sample=False, arm_timeout=False, base_left=seek_pwm, base_right=seek_pwm)
            if phase_elapsed >= int(getattr(self.cfg, "KICK_SEEK_MS", 1300) or 1300):
                self._stop_script()
                self.stop()
                self._refresh_visuals()

    def _control_state(self):
        if self.mode == "auto":
            return "auto-paused" if self.auto_paused else "auto-idle"
        if self.script_name:
            return "script-%s" % self.script_phase
        if self.release_decel_active:
            return "manual-braking"
        if self.motion_state == "forward":
            if self.forward_guard_state == "blocked":
                return "manual-blocked"
            if self.forward_guard_state == "slowdown":
                return "manual-forward-slow"
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
            "display": False,
            "display_face": self.face_name,
            "actuator_backend": self.actuator_backend,
            "lights": self.lights.available(),
            "lights_scene": self.lights.scene_name(),
            "lights_mode": self.lights.mode_name(),
            "lights_hw_enabled": self.lights.hardware_enabled(),
            "lights_preview": self.lights.preview_hex(),
            "network_station_connected": self.network_station_connected,
            "captured_ball": self.claw_angle >= self.cfg.CLAW_HOLD_ANGLE,
            "sonar_cm": self.front_distance_cm,
            "sonar_raw_cm": self.front_distance_raw_cm,
            "sonar_guard_cm": self.front_guard_distance_cm,
            "sonar_available": self.sonar_available(),
            "forward_limit_pwm": self.forward_limit_pwm,
            "forward_guard_state": self.forward_guard_state,
            "forward_head_locked": self.forward_head_locked,
            "manual_release_decel_active": self.release_decel_active,
            "script": self.script_name or "",
            "script_phase": self.script_phase or "",
        }

    def mqtt_summary(self):
        return {
            "mode": self.mode,
            "control_state": self._control_state(),
            "display_face": self.face_name,
            "actuator_backend": self.actuator_backend,
            "lights": self.lights.available(),
            "lights_scene": self.lights.scene_name(),
            "lights_mode": self.lights.mode_name(),
            "lights_hw_enabled": self.lights.hardware_enabled(),
            "lights_preview": self.lights.preview_hex(),
            "manual_left_speed": self.manual_left_speed,
            "manual_right_speed": self.manual_right_speed,
            "current_left_speed": self.current_left_speed,
            "current_right_speed": self.current_right_speed,
            "captured_ball": self.claw_angle >= self.cfg.CLAW_HOLD_ANGLE,
            "sonar_cm": self.front_distance_cm,
            "forward_guard_state": self.forward_guard_state,
            "forward_limit_pwm": self.forward_limit_pwm,
            "manual_release_decel_active": self.release_decel_active,
            "script": self.script_name or "",
            "script_phase": self.script_phase or "",
        }

    def handle_path(self, path):
        slider_result = self._update_slider_path(path)
        if slider_result is not None:
            return slider_result

        if path in self.cfg.BUTTON_AUTO_MODE_ALIASES:
            self.mode = "auto"
            self.auto_paused = True
            self.auto_state = "idle"
            self._stop_script()
            self.stop()
            self.lights.flash("mode_shift", 520)
            self._refresh_visuals()
            return "mode:auto-paused"

        if path in self.cfg.BUTTON_MANUAL_MODE_ALIASES:
            self.mode = "manual"
            self.auto_paused = True
            self.auto_state = "idle"
            self._stop_script()
            self.stop()
            self.lights.flash("mode_shift", 520)
            self._refresh_visuals()
            return "mode:manual"

        if path in self.cfg.BUTTON_OK_ALIASES:
            return self.handle_ok_button()

        if path in self.cfg.BUTTON_STOP_AUTO_ALIASES:
            self.auto_paused = True
            self.auto_state = "idle"
            self._stop_script()
            self.stop()
            self._refresh_visuals()
            return "auto:pause"

        if path in self.cfg.BUTTON_RAM_KICK_ALIASES:
            return self._start_kick_script()

        if path in getattr(self.cfg, "BUTTON_FACE_DEMO_ALIASES", ()):
            return self.preview_faces()
        if path in getattr(self.cfg, "BUTTON_FACE_NEXT_ALIASES", ()):
            return self.next_face()
        if path in getattr(self.cfg, "BUTTON_FACE_PREV_ALIASES", ()):
            return self.prev_face()
        if path in getattr(self.cfg, "BUTTON_FACE_CLEAR_ALIASES", ()):
            return self.clear_face()

        if path in self.cfg.BUTTON_GRAB_ALIASES:
            self.mode = "manual"
            self._stop_script()
            self.close_claw()
            self.lights.flash("grab_burst", 620)
            self._refresh_visuals()
            return "claw:grab"

        if path in self.cfg.BUTTON_RELEASE_ALIASES:
            self.mode = "manual"
            self._stop_script()
            self.open_claw_wide()
            self.lights.flash("release_burst", 540)
            self._refresh_visuals()
            return "claw:release-wide"

        if path in self.cfg.BUTTON_PAN_LEFT_ALIASES:
            if self.mode != "manual" or self.motion_state == "forward":
                return "ignored:pan-lock"
            self.head_left()
            self.forward_head_locked = False
            self.lights.flash("pan_left", 520)
            self._refresh_visuals()
            return "pan:left"

        if path in self.cfg.BUTTON_PAN_CENTER_ALIASES:
            if self.mode != "manual" or self.motion_state == "forward":
                return "ignored:pan-lock"
            self.center_head()
            self.forward_head_locked = False
            self.lights.flash("pan_center", 520)
            self._refresh_visuals()
            return "pan:center"

        if path in self.cfg.BUTTON_PAN_RIGHT_ALIASES:
            if self.mode != "manual" or self.motion_state == "forward":
                return "ignored:pan-lock"
            self.head_right()
            self.forward_head_locked = False
            self.lights.flash("pan_right", 520)
            self._refresh_visuals()
            return "pan:right"

        if path == self.cfg.BUTTON_FORWARD:
            if self.mode != "manual":
                return "ignored:auto-mode"
            self._stop_script()
            return self._apply_forward_motion(force_sample=True, arm_timeout=True)

        if path == self.cfg.BUTTON_BACKWARD:
            if self.mode != "manual":
                return "ignored:auto-mode"
            self._stop_script()
            self.forward_head_locked = False
            self.forward_guard_state = "clear"
            self.drive(-self.manual_left_speed, -self.manual_right_speed)
            self.motion_state = "backward"
            self._arm_manual_timeout()
            self._refresh_visuals()
            return "drive:backward"

        if path == self.cfg.BUTTON_LEFT:
            if self.mode != "manual":
                return "ignored:auto-mode"
            self._stop_script()
            return self._pivot_turn("left", arm_timeout=True)

        if path == self.cfg.BUTTON_RIGHT:
            if self.mode != "manual":
                return "ignored:auto-mode"
            self._stop_script()
            return self._pivot_turn("right", arm_timeout=True)

        if path == self.cfg.BUTTON_STOP:
            self._stop_script()
            if self.mode == "auto":
                self.stop()
                self.manual_motion_until = None
                self.lights.flash("brake", 420)
                self.auto_paused = True
                self.auto_state = "idle"
                self._refresh_visuals()
                return "auto:pause"
            return self._start_release_decel()

        if path == "/":
            return "hello"

        return "unknown"

    def update(self):
        now = hw.ticks_ms()
        if self.script_name == "kick":
            self._update_kick_script(now)
            self.lights.tick()
            return
        if self.release_decel_active:
            self._update_release_decel(now)
            self.lights.tick()
            return
        if self.mode == "manual" and self.manual_motion_until is not None:
            if self.motion_state == "forward":
                self._apply_forward_motion(force_sample=False, arm_timeout=False)
                now = hw.ticks_ms()
            if self.manual_motion_until is not None and hw.ticks_diff(now, self.manual_motion_until) >= 0:
                self.manual_motion_until = None
                self._start_release_decel()
            self.lights.tick()
            return
        if self.mode == "auto" and not self.auto_paused:
            self.stop()
            self.auto_state = "idle"
            self._refresh_visuals()
        self.lights.tick()

    def idle_window(self, duration_ms):
        duration_ms = max(0, int(duration_ms))
        if duration_ms <= 0:
            return
        if not self.soft_actuators:
            hw.sleep_ms(duration_ms)
            return
        end_ms = hw.ticks_add(hw.ticks_ms(), duration_ms)
        while True:
            now = hw.ticks_ms()
            remaining = hw.ticks_diff(end_ms, now)
            if remaining <= 0:
                break
            self.head_servo.pump(now)
            self.claw_servo.pump(now)
            self.left_motor.pump(now)
            self.right_motor.pump(now)
            hw.sleep_ms(min(self.soft_slice_ms, remaining))

    def shutdown(self):
        self._stop_script()
        self.stop()
        self.center_head()
        self.open_claw()
        try:
            self.left_motor.shutdown()
        except Exception:
            pass
        try:
            self.right_motor.shutdown()
        except Exception:
            pass
        try:
            self.head_servo.shutdown()
        except Exception:
            pass
        try:
            self.claw_servo.shutdown()
        except Exception:
            pass
        self.lights.shutdown()
