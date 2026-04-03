import compat as hw
from compat import I2C, Pin, PWM, json_module, network_module, neopixel_module, socket_module
from ht16k33matrix import HT16K33Matrix

try:
    import uselect as select_module
except ImportError:
    try:
        import select as select_module
    except ImportError:
        select_module = None


def _clamp(value, lower, upper):
    if value < lower:
        return lower
    if value > upper:
        return upper
    return value


class FaceAnimator:
    ICONS = {
        "smile": (
            bytes([0x60, 0x80, 0x64, 0x02, 0x02, 0x64, 0x80, 0x60]),
        ),
        "cry": (
            bytes([0x60, 0x90, 0x68, 0x04, 0x14, 0x68, 0x90, 0x60]),
        ),
        "front": (
            bytes([0x12, 0x24, 0x48, 0x90, 0x90, 0x48, 0x24, 0x12]),
        ),
        "back": (
            bytes([0x48, 0x24, 0x12, 0x09, 0x09, 0x12, 0x24, 0x48]),
        ),
        "left": (
            bytes([0x18, 0x24, 0x42, 0x99, 0x24, 0x42, 0x81, 0x00]),
        ),
        "right": (
            bytes([0x00, 0x81, 0x42, 0x24, 0x99, 0x42, 0x24, 0x18]),
        ),
        "stop": (
            bytes([0x00, 0x00, 0x00, 0xFD, 0xFD, 0x00, 0x00, 0x00]),
        ),
        "tsundere": (
            bytes([0x40, 0x40, 0x48, 0x10, 0x48, 0x44, 0x40, 0x00]),
        ),
        "squinting": (
            bytes([0x44, 0x28, 0x12, 0x02, 0x02, 0x12, 0x28, 0x44]),
        ),
        "despise": (
            bytes([0x30, 0x10, 0x14, 0x04, 0x34, 0x10, 0x10, 0x00]),
        ),
        "speechless": (
            bytes([0x40, 0x40, 0x5C, 0x14, 0x5C, 0x40, 0x40, 0x40]),
        ),
        "heart": (
            bytes([0x30, 0x48, 0x44, 0x22, 0x22, 0x44, 0x48, 0x30]),
        ),
        "clear": (
            bytes([0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]),
        ),
        "idle": (
            bytes([0x60, 0x80, 0x64, 0x02, 0x02, 0x64, 0x80, 0x60]),
            bytes([0x40, 0x40, 0x48, 0x10, 0x48, 0x44, 0x40, 0x00]),
        ),
        "manual": (
            bytes([0x12, 0x24, 0x48, 0x90, 0x90, 0x48, 0x24, 0x12]),
            bytes([0x48, 0x24, 0x12, 0x09, 0x09, 0x12, 0x24, 0x48]),
        ),
        "search": (
            bytes([0x12, 0x24, 0x48, 0x90, 0x90, 0x48, 0x24, 0x12]),
            bytes([0x18, 0x24, 0x42, 0x99, 0x24, 0x42, 0x81, 0x00]),
            bytes([0x00, 0x81, 0x42, 0x24, 0x99, 0x42, 0x24, 0x18]),
        ),
        "focus": (
            bytes([0x44, 0x28, 0x12, 0x02, 0x02, 0x12, 0x28, 0x44]),
            bytes([0x30, 0x48, 0x44, 0x22, 0x22, 0x44, 0x48, 0x30]),
        ),
        "capture": (
            bytes([0x30, 0x48, 0x44, 0x22, 0x22, 0x44, 0x48, 0x30]),
            bytes([0x40, 0x40, 0x5C, 0x14, 0x5C, 0x40, 0x40, 0x40]),
        ),
        "obstacle": (
            bytes([0x00, 0x00, 0x00, 0xFD, 0xFD, 0x00, 0x00, 0x00]),
            bytes([0x30, 0x10, 0x14, 0x04, 0x34, 0x10, 0x10, 0x00]),
        ),
        "celebrate": (
            bytes([0x30, 0x48, 0x44, 0x22, 0x22, 0x44, 0x48, 0x30]),
            bytes([0x60, 0x80, 0x64, 0x02, 0x02, 0x64, 0x80, 0x60]),
            bytes([0x40, 0x40, 0x48, 0x10, 0x48, 0x44, 0x40, 0x00]),
        ),
        "thinking": (
            bytes([0x40, 0x40, 0x48, 0x10, 0x48, 0x44, 0x40, 0x00]),
            bytes([0x40, 0x40, 0x5C, 0x14, 0x5C, 0x40, 0x40, 0x40]),
        ),
        "ram": (
            bytes([0x12, 0x24, 0x48, 0x90, 0x90, 0x48, 0x24, 0x12]),
            bytes([0x48, 0x24, 0x12, 0x09, 0x09, 0x12, 0x24, 0x48]),
        ),
        "sleep": (
            bytes([0x40, 0x40, 0x5C, 0x14, 0x5C, 0x40, 0x40, 0x40]),
            bytes([0x44, 0x28, 0x12, 0x02, 0x02, 0x12, 0x28, 0x44]),
        ),
    }
    CYCLE = [
        "smile",
        "tsundere",
        "squinting",
        "despise",
        "speechless",
        "heart",
        "front",
        "back",
        "left",
        "right",
        "stop",
    ]

    def __init__(self, config):
        self.cfg = config
        self.display = None
        self.base_name = "idle"
        self.name = "idle"
        self.override_name = None
        self.frames = self.ICONS["idle"]
        self.frame_index = 0
        self.cycle_index = 0
        self.last_frame_ms = hw.ticks_ms()
        try:
            i2c = I2C(scl=Pin(config.DISPLAY_SCL_PIN), sda=Pin(config.DISPLAY_SDA_PIN))
            self.display = HT16K33Matrix(i2c, address=config.DISPLAY_I2C_ADDR)
            self.display.set_brightness(config.DISPLAY_BRIGHTNESS)
            self.display.set_angle(getattr(config, "DISPLAY_ROTATION", 0))
            self.display.set_icon(self.frames[0]).draw()
        except Exception:
            self.display = None

    def available(self):
        return self.display is not None

    def _resolve(self, name):
        frames = self.ICONS.get(name)
        if frames is None:
            frames = self.ICONS["idle"]
            name = "idle"
        return name, frames

    def _apply(self, name):
        name, frames = self._resolve(name)
        if self.name != name:
            self.name = name
            self.frames = frames
            self.frame_index = 0
            self.last_frame_ms = 0
            self._draw()
        return name

    def set(self, name):
        self.base_name, _frames = self._resolve(name)
        if self.override_name is not None:
            return self.base_name
        return self._apply(self.base_name)

    def set_override(self, name):
        if name is None:
            self.clear_override()
            return self.name
        self.override_name, _frames = self._resolve(name)
        return self._apply(self.override_name)

    def clear_override(self):
        if self.override_name is None:
            return self.name
        self.override_name = None
        return self._apply(self.base_name)

    def active_name(self):
        return self.name

    def _draw(self):
        if self.display is None:
            return
        try:
            self.display.set_icon(self.frames[self.frame_index]).draw()
        except Exception:
            pass

    def demo(self):
        for name in ("idle", "search", "focus", "capture", "ram", "celebrate", "obstacle"):
            self.set(name)
            for _ in range(6):
                self.tick()
                hw.sleep_ms(self.cfg.EMOTION_FRAME_MS)

    def next_cycle(self):
        self.cycle_index = (self.cycle_index + 1) % len(self.CYCLE)
        name = self.CYCLE[self.cycle_index]
        self.set(name)
        return name

    def prev_cycle(self):
        self.cycle_index = (self.cycle_index - 1) % len(self.CYCLE)
        name = self.CYCLE[self.cycle_index]
        self.set(name)
        return name

    def clear_face(self):
        self.set("clear")

    def tick(self):
        if self.display is None or len(self.frames) <= 1:
            return
        now = hw.ticks_ms()
        if hw.ticks_diff(now, self.last_frame_ms) < self.cfg.EMOTION_FRAME_MS:
            return
        self.last_frame_ms = now
        self.frame_index = (self.frame_index + 1) % len(self.frames)
        self._draw()

    def shutdown(self):
        if self.display is None:
            return
        try:
            self.display.clear().draw()
        except Exception:
            pass


class AdaptiveBandit:
    def __init__(self, config, namespace, action_count):
        self.cfg = config
        self.namespace = namespace
        self.action_count = action_count
        self.table = {}
        self.total_updates = 0
        self._load()

    def _load(self):
        try:
            with open(self.cfg.POLICY_FILE, "r") as handle:
                payload = json_module.load(handle)
        except Exception:
            payload = {}
        stored = payload.get(self.namespace, {})
        if isinstance(stored, dict):
            self.table = stored

    def _save(self):
        payload = {}
        try:
            with open(self.cfg.POLICY_FILE, "r") as handle:
                payload = json_module.load(handle)
        except Exception:
            payload = {}
        payload[self.namespace] = self.table
        try:
            with open(self.cfg.POLICY_FILE, "w") as handle:
                json_module.dump(payload, handle)
        except Exception:
            pass

    def reset(self):
        self.table = {}
        self.total_updates = 0
        self._save()

    def describe(self):
        return {
            "namespace": self.namespace,
            "states": len(self.table),
            "updates": self.total_updates,
        }

    def choose(self, state_key):
        if self.action_count <= 1:
            return 0
        if hw.randunit() < self.cfg.RL_EPSILON:
            return hw.randbelow(self.action_count)

        row = self.table.get(state_key)
        if not isinstance(row, dict) or not row:
            return hw.randbelow(self.action_count)

        best_index = 0
        best_value = None
        index = 0
        while index < self.action_count:
            value = float(row.get(str(index), 0.0))
            if best_value is None or value > best_value:
                best_value = value
                best_index = index
            index += 1
        return best_index

    def learn(self, state_key, action_index, reward):
        row = self.table.get(state_key)
        if not isinstance(row, dict):
            row = {}
            self.table[state_key] = row
        action_key = str(action_index)
        old_value = float(row.get(action_key, 0.0))
        new_value = old_value + self.cfg.RL_ALPHA * (reward - old_value)
        row[action_key] = new_value
        self.total_updates += 1
        if self.total_updates % self.cfg.RL_SAVE_EVERY == 0:
            self._save()


class SoccerRobot:
    def __init__(self, config):
        self.cfg = config

        self.left_dir = Pin(config.LEFT_DIR_PIN, Pin.OUT)
        self.left_pwm = PWM(Pin(config.LEFT_PWM_PIN), freq=config.MOTOR_FREQ, duty=0)
        self.right_dir = Pin(config.RIGHT_DIR_PIN, Pin.OUT)
        self.right_pwm = PWM(Pin(config.RIGHT_PWM_PIN), freq=config.MOTOR_FREQ, duty=0)

        self.head_servo = PWM(Pin(config.HEAD_SERVO_PIN), freq=config.SERVO_FREQ)
        self.claw_servo = PWM(Pin(config.CLAW_SERVO_PIN), freq=config.SERVO_FREQ)

        self.trig = Pin(config.SONAR_TRIG_PIN, Pin.OUT, value=0)
        self.echo = Pin(config.SONAR_ECHO_PIN, Pin.IN)

        self.rgb = None
        try:
            self.rgb = neopixel_module.NeoPixel(Pin(config.RGB_PIN, Pin.OUT), 4)
        except Exception:
            self.rgb = None

        self.face = FaceAnimator(config)

        self.scan_agent = AdaptiveBandit(config, "scan", len(config.SCAN_PROFILES))
        self.capture_agent = AdaptiveBandit(config, "capture", len(config.CAPTURE_PROFILES))
        self.ram_agent = AdaptiveBandit(config, "ram", len(config.RAM_KICK_PROFILES))

        self.mode = "manual"
        self.auto_state = "idle"
        self.auto_paused = True
        self.last_state_ms = hw.ticks_ms()
        self.last_scan_ms = hw.ticks_ms()
        self.manual_motion_until = None
        self.current_scan_action = 0
        self.current_capture_action = 0
        self.current_ram_action = 0
        self.last_scan_state = "boot"
        self.last_capture_state = "boot"
        self.last_ram_state = "boot"
        self.captured_ball = False
        self.capture_streak = 0
        self.cycle_count = 0
        self.success_count = 0
        self.failure_count = 0
        self.recent_capture_limit = int(getattr(config, "RECENT_CAPTURE_WINDOW", 6) or 6)
        self.recent_capture_results = []
        self.last_capture_success = None
        self.manual_left_speed = config.MANUAL_SPEED
        self.manual_right_speed = config.MANUAL_SPEED
        self.network_station_connected = True

        self.head_angle = config.HEAD_CENTER_ANGLE
        self.claw_angle = config.CLAW_OPEN_ANGLE
        self.center_head()
        self.open_claw()
        self.stop()
        self.set_led(0, 0, 18)
        self.face.set("idle")

    def summary(self):
        recent_count = len(self.recent_capture_results)
        recent_successes = sum(self.recent_capture_results)
        if recent_count > 0:
            recent_capture_rate = (recent_successes * 100.0) / recent_count
        else:
            recent_capture_rate = None

        if self.mode == "auto":
            if self.auto_paused:
                control_state = "auto-paused"
            else:
                control_state = "auto-%s" % self.auto_state
        else:
            control_state = "manual"

        return {
            "mode": self.mode,
            "control_state": control_state,
            "auto_state": self.auto_state,
            "auto_paused": self.auto_paused,
            "cycle_count": self.cycle_count,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "capture_streak": self.capture_streak,
            "captured_ball": self.captured_ball,
            "recent_capture_count": recent_count,
            "recent_capture_successes": recent_successes,
            "recent_capture_window": self.recent_capture_limit,
            "recent_capture_rate": recent_capture_rate,
            "last_capture_success": self.last_capture_success,
            "manual_left_speed": self.manual_left_speed,
            "manual_right_speed": self.manual_right_speed,
            "scan_policy": self.scan_agent.describe(),
            "capture_policy": self.capture_agent.describe(),
            "ram_policy": self.ram_agent.describe(),
            "display": self.face.available(),
            "display_face": self.face.active_name(),
            "network_station_connected": self.network_station_connected,
        }

    def set_network_connected(self, connected):
        connected = bool(connected)
        if self.network_station_connected == connected:
            return
        self.network_station_connected = connected
        if connected:
            self.face.clear_override()
        else:
            self.face.set_override("cry")

    def reset_policies(self):
        self.scan_agent.reset()
        self.capture_agent.reset()
        self.ram_agent.reset()
        self.capture_streak = 0
        self.success_count = 0
        self.failure_count = 0
        self.recent_capture_results = []
        self.last_capture_success = None

    def _record_capture_result(self, success):
        success = bool(success)
        self.last_capture_success = success
        self.recent_capture_results.append(1 if success else 0)
        if len(self.recent_capture_results) > self.recent_capture_limit:
            self.recent_capture_results.pop(0)
        if success:
            self.capture_streak += 1
            self.success_count += 1
        else:
            self.capture_streak = 0
            self.failure_count += 1

    def set_led(self, red, green, blue):
        if self.rgb is None:
            return
        try:
            index = 0
            while index < 4:
                self.rgb[index] = (red, green, blue)
                index += 1
            self.rgb.write()
        except Exception:
            pass

    def _clamp_pwm(self, value):
        return int(_clamp(value, 0, self.cfg.MAX_PWM))

    def _servo_pulse_ns(self, angle):
        angle = _clamp(angle, 0, 180)
        pulse_width_ms = 0.5 + (angle / 180.0) * 2.0
        return int(pulse_width_ms * 1_000_000)

    def _servo_duty(self, angle):
        pulse_ns = self._servo_pulse_ns(angle)
        return int((pulse_ns / 20_000_000.0) * 1023)

    def _write_servo(self, servo, angle):
        pulse_ns = self._servo_pulse_ns(angle)
        if hasattr(servo, "duty_ns"):
            servo.duty_ns(pulse_ns)
            return
        if hasattr(servo, "duty_u16"):
            servo.duty_u16(int((pulse_ns / 20_000_000.0) * 65535))
            return
        servo.duty(self._servo_duty(angle))

    def set_head_angle(self, angle):
        self.head_angle = angle
        self._write_servo(self.head_servo, angle)

    def set_claw_angle(self, angle):
        self.claw_angle = angle
        self._write_servo(self.claw_servo, angle)

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

    def set_manual_speeds(self, left_value=None, right_value=None):
        if left_value is not None:
            if left_value <= 255:
                left_value = int(left_value * 4)
            self.manual_left_speed = int(_clamp(left_value, 0, self.cfg.MAX_PWM))
        if right_value is not None:
            if right_value <= 255:
                right_value = int(right_value * 4)
            self.manual_right_speed = int(_clamp(right_value, 0, self.cfg.MAX_PWM))

    def _set_wheel(self, direction_pin, pwm_pin, speed):
        if speed >= 0:
            direction_pin.value(0)
            pwm_pin.duty(self._clamp_pwm(speed))
        else:
            direction_pin.value(1)
            pwm_pin.duty(self._clamp_pwm(-speed))

    def drive(self, left_speed, right_speed):
        self._set_wheel(self.left_dir, self.left_pwm, left_speed)
        self._set_wheel(self.right_dir, self.right_pwm, right_speed)

    def forward(self, speed=None):
        if speed is None:
            speed = self.cfg.MANUAL_SPEED
        self.drive(speed, speed)

    def backward(self, speed=None):
        if speed is None:
            speed = self.cfg.REVERSE_SPEED
        self.drive(-speed, -speed)

    def turn_left(self, speed=None):
        if speed is None:
            speed = self.cfg.TURN_SPEED
        self.drive(-speed, speed)

    def turn_right(self, speed=None):
        if speed is None:
            speed = self.cfg.TURN_SPEED
        self.drive(speed, -speed)

    def arc_left(self, base_speed=None):
        if base_speed is None:
            base_speed = self.cfg.SEARCH_SPEED
        self.drive(base_speed // 2, base_speed)

    def arc_right(self, base_speed=None):
        if base_speed is None:
            base_speed = self.cfg.SEARCH_SPEED
        self.drive(base_speed, base_speed // 2)

    def stop(self):
        self.drive(0, 0)

    def _timed_motion(self, action, speed, duration_ms):
        action(speed)
        hw.sleep_ms(duration_ms)
        self.stop()

    def measure_distance_cm(self, timeout_us=30000):
        self.trig.value(0)
        hw.sleep_us(2)
        self.trig.value(1)
        hw.sleep_us(10)
        self.trig.value(0)

        wait_start = hw.ticks_us()
        while self.echo.value() == 0:
            if hw.ticks_diff_us(hw.ticks_us(), wait_start) > timeout_us:
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

    def measure_distance_filtered(self, samples=3):
        readings = []
        count = 0
        while count < samples:
            value = self.measure_distance_cm()
            if value > 0:
                readings.append(value)
            hw.sleep_ms(self.cfg.MEASURE_GAP_MS)
            count += 1
        if not readings:
            return -1
        readings.sort()
        return readings[len(readings) // 2]

    def scan_distances(self, profile=None):
        if profile is None:
            profile = (
                self.cfg.HEAD_LEFT_ANGLE,
                self.cfg.HEAD_CENTER_ANGLE,
                self.cfg.HEAD_RIGHT_ANGLE,
                self.cfg.SCAN_SETTLE_MS,
            )
        left_angle, center_angle, right_angle, settle_ms = profile
        scan = {}
        for name, angle in (
            ("left", left_angle),
            ("center", center_angle),
            ("right", right_angle),
        ):
            self.set_head_angle(angle)
            hw.sleep_ms(settle_ms)
            scan[name] = self.measure_distance_filtered(2)
        self.center_head()
        hw.sleep_ms(self.cfg.MEASURE_GAP_MS)
        return scan

    def _valid_target_distance(self, value):
        return self.cfg.BALL_DETECT_MIN_CM <= value <= self.cfg.BALL_DETECT_MAX_CM

    def choose_target(self, scan):
        candidates = []
        for name in ("left", "center", "right"):
            value = scan.get(name, -1)
            if self._valid_target_distance(value):
                candidates.append((value, name))
        if not candidates:
            return None
        candidates.sort()
        return candidates[0][1], candidates[0][0]

    def _encode_capture_state(self, scan):
        center = scan.get("center", -1)
        left = scan.get("left", -1)
        right = scan.get("right", -1)

        if center == -1 or center > 28:
            dist_bucket = "far"
        elif center > 14:
            dist_bucket = "mid"
        else:
            dist_bucket = "near"

        target = self.choose_target(scan)
        if target is None:
            direction_bucket = "none"
        else:
            direction_bucket = target[0]

        if (left > 0 and left < self.cfg.OBSTACLE_STOP_CM) or (right > 0 and right < self.cfg.OBSTACLE_STOP_CM):
            obstacle_bucket = "tight"
        else:
            obstacle_bucket = "open"

        if self.capture_streak >= 3:
            streak_bucket = "hot"
        elif self.capture_streak <= 0:
            streak_bucket = "cold"
        else:
            streak_bucket = "warm"

        return "d=%s|dir=%s|obs=%s|streak=%s" % (
            dist_bucket,
            direction_bucket,
            obstacle_bucket,
            streak_bucket,
        )

    def _encode_scan_state(self, front):
        if front == -1 or front > self.cfg.FREE_SPACE_GOOD_CM:
            front_bucket = "open"
        elif front > self.cfg.OBSTACLE_STOP_CM:
            front_bucket = "watch"
        else:
            front_bucket = "tight"

        if self.capture_streak >= 3:
            streak_bucket = "hot"
        elif self.capture_streak <= 0:
            streak_bucket = "cold"
        else:
            streak_bucket = "warm"

        return "front=%s|streak=%s|mode=%s" % (
            front_bucket,
            streak_bucket,
            self.auto_state,
        )

    def _encode_ram_state(self, lane_scan):
        center = lane_scan.get("center", -1)
        left = lane_scan.get("left", -1)
        right = lane_scan.get("right", -1)

        if center == -1 or center >= self.cfg.FREE_SPACE_GOOD_CM:
            front_bucket = "clear"
        elif center >= self.cfg.RAM_SAFE_FRONT_CM:
            front_bucket = "mid"
        else:
            front_bucket = "tight"

        if left == -1 and right == -1:
            lane_bucket = "unknown"
        elif left > right:
            lane_bucket = "left"
        elif right > left:
            lane_bucket = "right"
        else:
            lane_bucket = "center"

        return "front=%s|lane=%s|streak=%d" % (front_bucket, lane_bucket, _clamp(self.capture_streak, 0, 4))

    def _apply_lane_pre_turn(self, lane_scan):
        left = lane_scan.get("left", -1)
        right = lane_scan.get("right", -1)
        if left == -1 and right == -1:
            return
        if left > right + 3:
            self._timed_motion(self.turn_left, self.cfg.TURN_SPEED // 2, 120)
        elif right > left + 3:
            self._timed_motion(self.turn_right, self.cfg.TURN_SPEED // 2, 120)

    def _select_scan(self, front):
        state_key = self._encode_scan_state(front)
        action_index = self.scan_agent.choose(state_key)
        profile = self.cfg.SCAN_PROFILES[action_index]
        scan = self.scan_distances(profile)
        target = self.choose_target(scan)

        reward = -0.12
        if target is not None:
            direction, distance = target
            reward = 0.35
            if direction == "center":
                reward = 0.7
            if distance <= self.cfg.CAPTURE_DISTANCE_CM:
                reward = 0.95
        elif 0 < front < self.cfg.OBSTACLE_STOP_CM:
            reward = -0.2

        self.scan_agent.learn(state_key, action_index, reward)
        self.current_scan_action = action_index
        self.last_scan_state = state_key
        return scan, target

    def avoid_obstacle(self):
        self.face.set("obstacle")
        self.set_led(40, 0, 0)
        self._timed_motion(self.backward, self.cfg.REVERSE_SPEED, 180)

        scan = self.scan_distances()
        left = scan.get("left", -1)
        right = scan.get("right", -1)

        if left == -1 and right == -1:
            if hw.randbool():
                self._timed_motion(self.turn_left, self.cfg.TURN_SPEED, 260)
            else:
                self._timed_motion(self.turn_right, self.cfg.TURN_SPEED, 260)
            return

        if left > right:
            self._timed_motion(self.turn_left, self.cfg.TURN_SPEED, 260)
        else:
            self._timed_motion(self.turn_right, self.cfg.TURN_SPEED, 260)

    def capture_ball_adaptive(self, scan):
        state_key = self._encode_capture_state(scan)
        action_index = self.capture_agent.choose(state_key)
        profile = self.cfg.CAPTURE_PROFILES[action_index]
        open_angle, approach_pwm, approach_ms, close_angle, settle_ms, reverse_ms = profile

        pre_distance = scan.get("center", -1)

        self.face.set("capture")
        self.set_led(20, 20, 0)
        self.set_claw_angle(open_angle)
        hw.sleep_ms(80)
        self.forward(approach_pwm)
        hw.sleep_ms(approach_ms)
        self.stop()
        hw.sleep_ms(40)
        self.set_claw_angle(close_angle)
        hw.sleep_ms(settle_ms)
        self.hold_claw()
        hw.sleep_ms(80)

        if reverse_ms > 0:
            self.backward(self.cfg.REVERSE_SPEED)
            hw.sleep_ms(reverse_ms)
            self.stop()
            hw.sleep_ms(60)

        post_distance = self.measure_distance_filtered(3)
        success = False
        if pre_distance > 0 and (post_distance == -1 or post_distance >= pre_distance + 6):
            success = True
        elif post_distance >= self.cfg.FREE_SPACE_GOOD_CM:
            success = True

        reward = 1.0 if success else -0.75
        self.capture_agent.learn(state_key, action_index, reward)
        self.last_capture_state = state_key
        self.current_capture_action = action_index
        self._record_capture_result(success)

        if success:
            self.captured_ball = True
        else:
            self.captured_ball = False
            self.open_claw()
            hw.sleep_ms(120)

        return {
            "success": success,
            "pre_distance": pre_distance,
            "post_distance": post_distance,
            "action_index": action_index,
            "state_key": state_key,
        }

    def perform_ram_kick(self):
        lane_scan = self.scan_distances()
        state_key = self._encode_ram_state(lane_scan)
        action_index = self.ram_agent.choose(state_key)
        profile = self.cfg.RAM_KICK_PROFILES[action_index]
        drop_angle, reverse_ms, ram_pwm, ram_ms, settle_ms = profile

        self.face.set("ram")
        self.set_led(36, 18, 0)
        self._apply_lane_pre_turn(lane_scan)

        self.set_claw_angle(drop_angle)
        hw.sleep_ms(90)

        if reverse_ms > 0:
            self.backward(self.cfg.RAM_PREP_SPEED)
            hw.sleep_ms(reverse_ms)
            self.stop()
            hw.sleep_ms(60)

        pre_ram_distance = self.measure_distance_filtered(2)
        self.forward(ram_pwm)
        hw.sleep_ms(ram_ms)
        self.stop()
        hw.sleep_ms(settle_ms)

        self.open_claw_wide()
        hw.sleep_ms(70)
        post_ram_distance = self.measure_distance_filtered(3)

        if post_ram_distance == -1:
            success = True
        elif pre_ram_distance > 0 and post_ram_distance >= pre_ram_distance + 5:
            success = True
        elif post_ram_distance >= self.cfg.FREE_SPACE_GOOD_CM:
            success = True
        else:
            success = False

        reward = 0.8 if success else -0.4
        self.ram_agent.learn(state_key, action_index, reward)
        self.last_ram_state = state_key
        self.current_ram_action = action_index
        self.captured_ball = False

        if success:
            self.face.set("celebrate")
        else:
            self.face.set("thinking")

        return {
            "success": success,
            "pre_ram_distance": pre_ram_distance,
            "post_ram_distance": post_ram_distance,
            "action_index": action_index,
            "state_key": state_key,
        }

    def start_auto(self):
        self.mode = "auto"
        self.auto_state = "search"
        self.auto_paused = True
        self.last_state_ms = hw.ticks_ms()
        self.last_scan_ms = hw.ticks_ms()
        self.captured_ball = False
        self.open_claw()
        self.center_head()
        self.stop()
        self.set_led(18, 18, 0)
        self.face.set("thinking")

    def stop_auto(self):
        self.mode = "manual"
        self.auto_state = "idle"
        self.auto_paused = True
        self.manual_motion_until = None
        self.captured_ball = False
        self.center_head()
        self.stop()
        self.set_led(0, 0, 18)
        self.face.set("manual")

    def pause_auto(self):
        self.mode = "auto"
        self.auto_paused = True
        self.stop()
        self.set_led(18, 18, 0)
        self.face.set("thinking")

    def resume_auto(self):
        self.mode = "auto"
        self.auto_state = "search"
        self.auto_paused = False
        self.last_state_ms = hw.ticks_ms()
        self.last_scan_ms = hw.ticks_ms()
        self.stop()
        self.set_led(0, 30, 0)
        self.face.set("search")

    def _arm_manual_timeout(self):
        self.manual_motion_until = hw.ticks_add(
            hw.ticks_ms(), self.cfg.MANUAL_COMMAND_TIMEOUT_MS
        )

    def preview_faces(self):
        self.stop_auto()
        self.face.demo()
        self.face.set("manual")
        return "face:demo"

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
            if self.auto_paused:
                self.resume_auto()
                return "auto:resume"
            self.pause_auto()
            return "auto:pause"

        if self.claw_angle >= self.cfg.CLAW_HOLD_ANGLE:
            self.open_claw()
            self.face.set("manual")
            return "claw:release"

        self.close_claw()
        self.face.set("capture")
        return "claw:grab"

    def handle_path(self, path):
        slider_result = self._update_slider_path(path)
        if slider_result is not None:
            return slider_result

        if path in self.cfg.BUTTON_AUTO_MODE_ALIASES:
            self.start_auto()
            return "mode:auto-paused"

        if path in self.cfg.BUTTON_MANUAL_MODE_ALIASES:
            self.stop_auto()
            return "mode:manual"

        if path in self.cfg.BUTTON_OK_ALIASES:
            return self.handle_ok_button()

        if path in self.cfg.BUTTON_STOP_AUTO_ALIASES:
            self.pause_auto()
            return "auto:pause"

        if path in self.cfg.BUTTON_RAM_KICK_ALIASES:
            self.stop_auto()
            self.close_claw()
            hw.sleep_ms(120)
            result = self.perform_ram_kick()
            return "ram-kick:%s" % ("ok" if result["success"] else "retry")

        if path in self.cfg.BUTTON_POLICY_RESET_ALIASES:
            self.stop_auto()
            self.reset_policies()
            self.face.set("thinking")
            return "policy:reset"

        if path in self.cfg.BUTTON_FACE_DEMO_ALIASES:
            return self.preview_faces()

        if path in self.cfg.BUTTON_FACE_NEXT_ALIASES:
            name = self.face.next_cycle()
            return "face:%s" % name

        if path in self.cfg.BUTTON_FACE_CLEAR_ALIASES:
            self.face.clear_face()
            return "face:clear"

        if path in self.cfg.BUTTON_FACE_PREV_ALIASES:
            name = self.face.prev_cycle()
            return "face:%s" % name

        if path in self.cfg.BUTTON_GRAB_ALIASES:
            self.stop_auto()
            self.close_claw()
            self.face.set("capture")
            return "claw:grab"

        if path in self.cfg.BUTTON_RELEASE_ALIASES:
            self.stop_auto()
            self.open_claw_wide()
            self.face.set("manual")
            return "claw:release-wide"

        if path in self.cfg.BUTTON_PAN_LEFT_ALIASES:
            if self.mode != "manual":
                return "ignored:auto-mode"
            self.head_left()
            self.face.set("manual")
            return "pan:left"

        if path in self.cfg.BUTTON_PAN_CENTER_ALIASES:
            if self.mode != "manual":
                return "ignored:auto-mode"
            self.center_head()
            self.face.set("manual")
            return "pan:center"

        if path in self.cfg.BUTTON_PAN_RIGHT_ALIASES:
            if self.mode != "manual":
                return "ignored:auto-mode"
            self.head_right()
            self.face.set("manual")
            return "pan:right"

        if path == self.cfg.BUTTON_FORWARD:
            if self.mode != "manual":
                return "ignored:auto-mode"
            self.drive(self.manual_left_speed, self.manual_right_speed)
            self._arm_manual_timeout()
            self.face.set("front")
            return "drive:forward"

        if path == self.cfg.BUTTON_BACKWARD:
            if self.mode != "manual":
                return "ignored:auto-mode"
            self.drive(-self.manual_left_speed, -self.manual_right_speed)
            self._arm_manual_timeout()
            self.face.set("back")
            return "drive:backward"

        if path == self.cfg.BUTTON_LEFT:
            if self.mode != "manual":
                return "ignored:auto-mode"
            self.drive(-self.manual_left_speed, self.manual_right_speed)
            self._arm_manual_timeout()
            self.face.set("left")
            return "drive:left"

        if path == self.cfg.BUTTON_RIGHT:
            if self.mode != "manual":
                return "ignored:auto-mode"
            self.drive(self.manual_left_speed, -self.manual_right_speed)
            self._arm_manual_timeout()
            self.face.set("right")
            return "drive:right"

        if path == self.cfg.BUTTON_STOP:
            if self.mode == "auto":
                self.pause_auto()
                return "auto:pause"
            self.stop()
            self.manual_motion_until = None
            self.face.set("stop")
            return "drive:stop"

        if path == "/":
            return "hello"

        return "unknown"

    def _manual_tick(self, now):
        if self.manual_motion_until is None:
            return
        if hw.ticks_diff(now, self.manual_motion_until) >= 0:
            self.stop()
            self.manual_motion_until = None

    def _search_tick(self, now):
        self.face.set("search")
        self.set_led(0, 30, 0)
        front = self.measure_distance_filtered(2)

        if 0 < front < self.cfg.OBSTACLE_ESCAPE_CM:
            self.avoid_obstacle()
            self.last_scan_ms = hw.ticks_ms()
            return

        if hw.ticks_diff(now, self.last_scan_ms) >= self.cfg.SEARCH_SCAN_INTERVAL_MS:
            scan, target = self._select_scan(front)
            self.last_scan_ms = hw.ticks_ms()
            if target is not None:
                direction, distance = target
                if distance <= self.cfg.CAPTURE_DISTANCE_CM:
                    result = self.capture_ball_adaptive(scan)
                    if result["success"]:
                        self.auto_state = "ram"
                    else:
                        self.auto_state = "recover"
                    self.last_state_ms = hw.ticks_ms()
                    return

                if direction == "left":
                    self._timed_motion(self.turn_left, self.cfg.TURN_SPEED // 2, 130)
                elif direction == "right":
                    self._timed_motion(self.turn_right, self.cfg.TURN_SPEED // 2, 130)
                self.auto_state = "track"
                self.last_state_ms = hw.ticks_ms()
                return

        if 0 < front < self.cfg.OBSTACLE_STOP_CM:
            self.avoid_obstacle()
            return

        if hw.randbool():
            self.arc_left(self.cfg.SEARCH_SPEED)
        else:
            self.arc_right(self.cfg.SEARCH_SPEED)

    def _track_tick(self, now):
        self.face.set("focus")
        self.set_led(10, 25, 5)

        if hw.ticks_diff(now, self.last_state_ms) >= self.cfg.APPROACH_TIMEOUT_MS:
            self.auto_state = "search"
            self.last_state_ms = now
            return

        front = self.measure_distance_filtered(2)

        if front == -1 or front > self.cfg.BALL_DETECT_MAX_CM:
            self.auto_state = "search"
            self.last_state_ms = now
            return

        if front < self.cfg.OBSTACLE_ESCAPE_CM:
            scan = self.scan_distances()
            result = self.capture_ball_adaptive(scan)
            if result["success"]:
                self.auto_state = "ram"
            else:
                self.auto_state = "recover"
            self.last_state_ms = hw.ticks_ms()
            return

        if front <= self.cfg.CAPTURE_DISTANCE_CM:
            scan = {
                "left": front + 2,
                "center": front,
                "right": front + 2,
            }
            result = self.capture_ball_adaptive(scan)
            if result["success"]:
                self.auto_state = "ram"
            else:
                self.auto_state = "recover"
            self.last_state_ms = hw.ticks_ms()
            return

        self.forward(self.cfg.APPROACH_SPEED)

    def _ram_tick(self, now):
        del now
        if not self.captured_ball:
            self.auto_state = "search"
            self.last_state_ms = hw.ticks_ms()
            return

        result = self.perform_ram_kick()
        self.cycle_count += 1
        self.auto_state = "recover" if result["success"] else "search"
        self.last_state_ms = hw.ticks_ms()

    def _recover_tick(self, now):
        del now
        self.set_led(0, 10, 30)
        self.face.set("thinking")
        self.open_claw_wide()
        self._timed_motion(self.backward, self.cfg.REVERSE_SPEED, 150)
        if hw.randbool():
            self._timed_motion(self.turn_left, self.cfg.TURN_SPEED // 2, 140)
        else:
            self._timed_motion(self.turn_right, self.cfg.TURN_SPEED // 2, 140)
        self.auto_state = "search"
        self.last_state_ms = hw.ticks_ms()

    def update(self):
        now = hw.ticks_ms()

        if self.mode != "auto":
            self._manual_tick(now)
            self.face.tick()
            return

        if self.auto_paused:
            self.stop()
            self.face.tick()
            return

        if self.auto_state == "search":
            self._search_tick(now)
        elif self.auto_state == "track":
            self._track_tick(now)
        elif self.auto_state == "ram":
            self._ram_tick(now)
        elif self.auto_state == "recover":
            self._recover_tick(now)
        else:
            self.auto_state = "search"
            self.last_state_ms = now

        self.face.tick()

    def self_check(self):
        return {
            "display": self.face.available(),
            "sonar_cm": self.measure_distance_filtered(3),
            "scan_policy": self.scan_agent.describe(),
            "capture_policy": self.capture_agent.describe(),
            "ram_policy": self.ram_agent.describe(),
            "summary": self.summary(),
        }

    def shutdown(self):
        self.stop()
        self.center_head()
        self.open_claw()
        self.set_led(0, 0, 0)
        self.face.shutdown()


class RemoteServer:
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.sock = None
        self.poller = None
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
                    if select_module is not None and hasattr(select_module, "poll"):
                        try:
                            self.poller = select_module.poll()
                            pollin = getattr(select_module, "POLLIN", 1)
                            self.poller.register(self.sock, pollin)
                        except Exception:
                            self.poller = None
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
        if self.poller is not None:
            try:
                if not self.poller.poll(0):
                    return None
            except Exception:
                pass
        try:
            client, _address = self.sock.accept()
        except OSError:
            return None

        path = None
        dispatch_path = True
        try:
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


def connect_wifi(config):
    if network_module is None:
        return "offline", "0.0.0.0"

    sta = network_module.WLAN(network_module.STA_IF)
    ap = network_module.WLAN(network_module.AP_IF)
    sta.active(True)
    try:
        ap.active(False)
    except Exception:
        pass

    sta_ip = ""
    if config.STA_SSID:
        if not sta.isconnected():
            sta.connect(config.STA_SSID, config.STA_PASSWORD)
            started = hw.ticks_ms()
            while not sta.isconnected():
                if hw.ticks_diff(hw.ticks_ms(), started) > 12000:
                    break
                hw.sleep_ms(250)
        if sta.isconnected():
            sta_ip = sta.ifconfig()[0]

    if sta_ip:
        try:
            ap.active(False)
        except Exception:
            pass
        return "station", sta_ip

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

    ap_ip = ap.ifconfig()[0]
    return "ap_fallback", ap_ip
