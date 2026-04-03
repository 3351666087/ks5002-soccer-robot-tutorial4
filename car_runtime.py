import compat as hw
from compat import I2C, Pin, PWM, neopixel_module
from smart_drive import SmartDriveMixin


def _clamp(value, lower, upper):
    if value < lower:
        return lower
    if value > upper:
        return upper
    return value


class FaceAnimator:
    ICONS = {
        "idle": (
            bytes([0x60, 0x80, 0x64, 0x02, 0x02, 0x64, 0x80, 0x60]),
            bytes([0x40, 0x40, 0x48, 0x10, 0x48, 0x44, 0x40, 0x00]),
        ),
        "manual": (
            bytes([0x12, 0x24, 0x48, 0x90, 0x90, 0x48, 0x24, 0x12]),
            bytes([0x48, 0x24, 0x12, 0x09, 0x09, 0x12, 0x24, 0x48]),
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
        "capture": (
            bytes([0x30, 0x48, 0x44, 0x22, 0x22, 0x44, 0x48, 0x30]),
        ),
        "thinking": (
            bytes([0x40, 0x40, 0x48, 0x10, 0x48, 0x44, 0x40, 0x00]),
            bytes([0x40, 0x40, 0x5C, 0x14, 0x5C, 0x40, 0x40, 0x40]),
        ),
        "cry": (
            bytes([0x60, 0x90, 0x68, 0x04, 0x14, 0x68, 0x90, 0x60]),
        ),
        "clear": (
            bytes([0x00] * 8),
        ),
    }
    CYCLE = ["idle", "manual", "front", "back", "left", "right", "stop", "capture", "thinking", "cry"]

    def __init__(self, config_module):
        self.cfg = config_module
        self.display = None
        self.base_name = "idle"
        self.name = "idle"
        self.override_name = None
        self.frames = self.ICONS["idle"]
        self.frame_index = 0
        self.cycle_index = 0
        self.last_frame_ms = hw.ticks_ms()
        mqtt_active = bool(str(getattr(config_module, "MQTT_BROKER_HOST", "") or "").strip())
        if mqtt_active and not bool(getattr(config_module, "MQTT_ALLOW_DISPLAY_HARDWARE", False)):
            return
        try:
            from ht16k33matrix import HT16K33Matrix

            i2c = I2C(scl=Pin(config_module.DISPLAY_SCL_PIN), sda=Pin(config_module.DISPLAY_SDA_PIN))
            self.display = HT16K33Matrix(i2c, address=config_module.DISPLAY_I2C_ADDR)
            self.display.set_brightness(config_module.DISPLAY_BRIGHTNESS)
            self.display.set_angle(getattr(config_module, "DISPLAY_ROTATION", 0))
            self.display.set_icon(self.frames[0]).draw()
        except Exception:
            self.display = None

    def available(self):
        return self.display is not None

    def _resolve(self, name):
        frames = self.ICONS.get(name)
        if frames is None:
            return "idle", self.ICONS["idle"]
        return name, frames

    def _draw(self):
        if self.display is None:
            return
        try:
            self.display.set_icon(self.frames[self.frame_index]).draw()
        except Exception:
            pass

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
            return self.clear_override()
        self.override_name, _frames = self._resolve(name)
        return self._apply(self.override_name)

    def clear_override(self):
        if self.override_name is None:
            return self.name
        self.override_name = None
        return self._apply(self.base_name)

    def active_name(self):
        return self.name

    def demo(self):
        for name in self.CYCLE:
            self.set(name)
            for _index in range(4):
                self.tick()
                hw.sleep_ms(self.cfg.EMOTION_FRAME_MS)

    def next_cycle(self):
        self.cycle_index = (self.cycle_index + 1) % len(self.CYCLE)
        return self.set(self.CYCLE[self.cycle_index])

    def prev_cycle(self):
        self.cycle_index = (self.cycle_index - 1) % len(self.CYCLE)
        return self.set(self.CYCLE[self.cycle_index])

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


class ChassisLightAnimator:
    # This board/firmware pair is stable with discrete NeoPixel writes, but
    # frequent animation updates can trigger native ESP32 crashes. Keep the
    # chassis lights event-driven: write on scene changes and burst expiry,
    # not on a continuous animation timer.
    ANIMATED_SCENES = set()

    def __init__(self, config_module):
        self.cfg = config_module
        self.strip = None
        self.base_scene = "boot"
        self.overlay_scene = None
        self.overlay_until = None
        self.last_draw_ms = 0
        self.last_pixels = None
        self.scene_dirty = True
        mqtt_active = bool(str(getattr(config_module, "MQTT_BROKER_HOST", "") or "").strip())
        if mqtt_active and not bool(getattr(config_module, "MQTT_ALLOW_LIGHT_HARDWARE", False)):
            return
        try:
            self.strip = neopixel_module.NeoPixel(Pin(config_module.RGB_PIN, Pin.OUT), 4)
        except Exception:
            self.strip = None

    def available(self):
        return self.strip is not None

    def scene_name(self):
        if self.overlay_scene is not None:
            return self.overlay_scene
        return self.base_scene

    def set_base(self, scene):
        if not scene:
            return
        if self.base_scene == scene:
            return
        self.base_scene = scene
        self.scene_dirty = True
        self.last_draw_ms = 0

    def flash(self, scene, duration_ms=None):
        if not scene:
            return
        if duration_ms is None:
            duration_ms = int(getattr(self.cfg, "LIGHT_BURST_MS", 680) or 680)
        self.overlay_scene = scene
        self.overlay_until = hw.ticks_add(hw.ticks_ms(), duration_ms)
        self.scene_dirty = True
        self.last_draw_ms = 0

    def clear_overlay(self):
        self.overlay_scene = None
        self.overlay_until = None
        self.scene_dirty = True
        self.last_draw_ms = 0

    def _write(self, pixels):
        if self.strip is None:
            return
        if self.last_pixels == pixels:
            return
        try:
            index = 0
            while index < 4:
                self.strip[index] = pixels[index]
                index += 1
            self.strip.write()
            self.last_pixels = pixels
        except Exception:
            pass

    def _scene_is_animated(self, scene):
        return scene in self.ANIMATED_SCENES

    def _scale(self, color, factor):
        return (
            (color[0] * factor) // 255,
            (color[1] * factor) // 255,
            (color[2] * factor) // 255,
        )

    def _cap(self, color):
        limit = int(getattr(self.cfg, "LIGHT_MAX_BRIGHTNESS", 72) or 72)
        return (
            int(_clamp(color[0], 0, limit)),
            int(_clamp(color[1], 0, limit)),
            int(_clamp(color[2], 0, limit)),
        )

    def _triangle(self, value, period=510):
        value = value % period
        half = period // 2
        if value > half:
            return period - value
        return value

    def _scene_pixels(self, scene, now):
        step = now // int(getattr(self.cfg, "LIGHT_FRAME_MS", 70) or 70)
        pulse_a = self._triangle(step * 23)
        pulse_b = self._triangle(step * 17 + 128)
        pulse_c = self._triangle(step * 31 + 64)
        strong = 72 + pulse_a // 6
        medium = 34 + pulse_b // 10
        soft = 8 + pulse_c // 18
        white_pop = 12 + pulse_a // 18
        blink = 255 if ((step // 2) % 2 == 0) else 28
        orbit = step % 4

        if scene == "boot":
            palette = [(0, 18, 46), (0, 42, 60), (16, 10, 34), (0, 8, 18)]
            pixels = []
            index = 0
            while index < 4:
                pixels.append(self._cap(palette[(index - orbit) % 4]))
                index += 1
            return tuple(pixels)

        if scene == "network_lost":
            return (
                self._cap((4, 12 + pulse_a // 12, 28 + pulse_a // 6)),
                self._cap((0, 0, 8 + pulse_b // 20)),
                self._cap((0, 0, 8 + pulse_c // 20)),
                self._cap((4, 10 + pulse_b // 12, 26 + pulse_b // 6)),
            )

        if scene == "manual_idle":
            return (
                self._cap((10 + pulse_a // 18, 6 + pulse_b // 22, 28 + pulse_a // 8)),
                self._cap((0, 14 + pulse_b // 12, 42 + pulse_b // 8)),
                self._cap((0, 22 + pulse_c // 14, 18 + pulse_c // 20)),
                self._cap((18 + pulse_a // 14, 0, 16 + pulse_b // 14)),
            )

        if scene == "hold_ball":
            return (
                self._cap((26 + pulse_a // 10, 14 + pulse_a // 16, 0)),
                self._cap((38 + pulse_a // 8, 20 + pulse_a // 12, white_pop)),
                self._cap((38 + pulse_a // 8, 20 + pulse_a // 12, white_pop)),
                self._cap((26 + pulse_a // 10, 14 + pulse_a // 16, 0)),
            )

        if scene == "guard_slow":
            return (
                self._cap((18 + pulse_a // 14, 6 + pulse_b // 24, 0)),
                self._cap((42 + pulse_a // 10, 18 + pulse_b // 18, white_pop)),
                self._cap((42 + pulse_a // 10, 18 + pulse_b // 18, white_pop)),
                self._cap((18 + pulse_a // 14, 6 + pulse_b // 24, 0)),
            )

        if scene == "guard_stop":
            hot = 80 + pulse_a // 3
            return (
                self._cap((hot, 14, 0)),
                self._cap((hot, hot // 3, 0)),
                self._cap((hot, hot // 3, 0)),
                self._cap((hot, 14, 0)),
            )

        if scene == "scan_sweep":
            palette = [(0, 12, 40), (0, 26, 68), (8, 42, 18), (24, 8, 44)]
            pixels = []
            index = 0
            while index < 4:
                pixels.append(self._cap(palette[(index + orbit) % 4]))
                index += 1
            return tuple(pixels)

        if scene == "ball_track":
            glow = 26 + pulse_a // 10
            return (
                self._cap((8, glow // 2, 0)),
                self._cap((18, glow, white_pop)),
                self._cap((18, glow, white_pop)),
                self._cap((8, glow // 2, 0)),
            )

        if scene == "kick_charge":
            return (
                self._cap((white_pop, 10 + pulse_a // 16, 0)),
                self._cap((42 + pulse_a // 8, 18 + pulse_b // 20, 0)),
                self._cap((62 + pulse_a // 7, 26 + pulse_b // 18, white_pop)),
                self._cap((32 + pulse_a // 10, 8 + pulse_b // 18, 0)),
            )

        if scene == "kick_seek":
            return (
                self._cap((0, 14 + pulse_a // 16, 38 + pulse_a // 10)),
                self._cap((0, 28 + pulse_a // 12, 62 + pulse_b // 8)),
                self._cap((14 + pulse_b // 14, 52 + pulse_a // 10, 20)),
                self._cap((0, 20 + pulse_b // 14, 44 + pulse_b // 10)),
            )

        if scene == "drive_forward":
            base = [
                (0, 10, 18),
                (0, 28, 34),
                (4, 56, 10),
                (white_pop, 66, white_pop),
            ]
            pixels = []
            index = 0
            while index < 4:
                pixels.append(self._cap(base[(index - orbit) % 4]))
                index += 1
            return tuple(pixels)

        if scene == "drive_backward":
            base = [
                (28, 0, 6),
                (52, 4, 18),
                (68, 16, 0),
                (white_pop, 8, 0),
            ]
            pixels = []
            index = 0
            while index < 4:
                pixels.append(self._cap(base[(index + orbit) % 4]))
                index += 1
            return tuple(pixels)

        if scene == "turn_left":
            return (
                self._cap((56 + pulse_a // 8, 20 + pulse_b // 16, 0)),
                self._cap((0, 2, 10)),
                self._cap((44 + pulse_b // 10, 12 + pulse_a // 18, 0)),
                self._cap((0, 2, 10)),
            )

        if scene == "turn_right":
            return (
                self._cap((0, 2, 10)),
                self._cap((24 + pulse_a // 12, 0, 48 + pulse_a // 8)),
                self._cap((0, 2, 10)),
                self._cap((18 + pulse_b // 12, 0, 56 + pulse_b // 8)),
            )

        if scene == "auto_paused":
            breathe = 90 + pulse_a // 2
            amber = self._scale((72, 34, 2), breathe)
            return (amber, self._cap((12, 4, 0)), amber, self._cap((12, 4, 0)))

        if scene == "auto_armed":
            palette = [(8, 0, 30), (0, 28, 42), (0, 44, 12), (28, 8, 34)]
            pixels = []
            index = 0
            while index < 4:
                pixels.append(self._cap(palette[(index + orbit) % 4]))
                index += 1
            return tuple(pixels)

        if scene == "brake":
            hot = blink
            return (
                self._cap((hot // 4, hot // 8, hot // 8)),
                self._cap((hot, hot // 4, hot // 8)),
                self._cap((hot, hot // 4, hot // 8)),
                self._cap((hot // 4, hot // 8, hot // 8)),
            )

        if scene == "grab_burst":
            return (
                self._cap((44 + pulse_a // 6, 18 + pulse_b // 14, 0)),
                self._cap((72, 42 + pulse_a // 10, white_pop)),
                self._cap((72, 42 + pulse_a // 10, white_pop)),
                self._cap((44 + pulse_a // 6, 18 + pulse_b // 14, 0)),
            )

        if scene == "release_burst":
            return (
                self._cap((0, 24 + pulse_a // 10, 44 + pulse_b // 8)),
                self._cap((0, 52 + pulse_a // 8, 72)),
                self._cap((0, 52 + pulse_a // 8, 72)),
                self._cap((0, 24 + pulse_a // 10, 44 + pulse_b // 8)),
            )

        if scene == "pan_left":
            return (
                self._cap((26 + pulse_a // 10, 10 + pulse_a // 16, 46 + pulse_a // 8)),
                self._cap((0, 4, 10)),
                self._cap((20 + pulse_b // 12, 8 + pulse_b // 16, 34 + pulse_b // 10)),
                self._cap((0, 4, 10)),
            )

        if scene == "pan_center":
            center = self._cap((white_pop + 12, 28 + pulse_a // 12, 56 + pulse_a // 8))
            return (self._cap((0, 4, 12)), center, center, self._cap((0, 4, 12)))

        if scene == "pan_right":
            return (
                self._cap((0, 4, 10)),
                self._cap((24 + pulse_a // 10, 6 + pulse_a // 18, 40 + pulse_a // 8)),
                self._cap((0, 4, 10)),
                self._cap((28 + pulse_b // 10, 8 + pulse_b // 18, 52 + pulse_b // 8)),
            )

        if scene == "speed_left":
            level = int(_clamp((pulse_a + 120) // 3, 48, 150))
            return (
                self._cap((0, level // 4, level // 2)),
                self._cap((0, level // 2, level)),
                self._cap((0, level // 6, 18)),
                self._cap((0, level // 8, 10)),
            )

        if scene == "speed_right":
            level = int(_clamp((pulse_b + 120) // 3, 48, 150))
            return (
                self._cap((12, 0, level // 8)),
                self._cap((18, 0, level // 6)),
                self._cap((level // 2, 0, level)),
                self._cap((level // 4, 0, level // 2)),
            )

        if scene == "face_demo":
            palette = [(72, 0, 28), (0, 62, 42), (22, 22, 72), (72, 44, 0)]
            pixels = []
            index = 0
            while index < 4:
                pixels.append(self._cap(palette[(index + orbit) % 4]))
                index += 1
            return tuple(pixels)

        if scene == "mode_shift":
            flare = 80 + pulse_a // 2
            pop = self._scale((72, 72, 72), flare)
            return (pop, self._cap((8, 18, 34)), pop, self._cap((8, 18, 34)))

        return (
            self._cap((soft, 0, medium)),
            self._cap((0, medium, strong // 2)),
            self._cap((0, strong // 2, soft)),
            self._cap((medium, 0, soft)),
        )

    def tick(self):
        if self.strip is None:
            return
        now = hw.ticks_ms()
        if self.overlay_until is not None and hw.ticks_diff(now, self.overlay_until) >= 0:
            self.clear_overlay()
        scene = self.scene_name()
        animated = self._scene_is_animated(scene)
        if not self.scene_dirty and not animated:
            return
        frame_ms = int(getattr(self.cfg, "LIGHT_FRAME_MS", 70) or 70)
        if not self.scene_dirty and hw.ticks_diff(now, self.last_draw_ms) < frame_ms:
            return
        self.last_draw_ms = now
        self.scene_dirty = False
        pixels = self._scene_pixels(scene, now if animated else 0)
        self._write(pixels)

    def shutdown(self):
        self._write(((0, 0, 0), (0, 0, 0), (0, 0, 0), (0, 0, 0)))


class RemoteCar(SmartDriveMixin):
    def __init__(self, config_module):
        self.cfg = config_module
        self.left_dir = Pin(config_module.LEFT_DIR_PIN, Pin.OUT)
        self.left_pwm = PWM(Pin(config_module.LEFT_PWM_PIN), freq=config_module.MOTOR_FREQ, duty=0)
        self.right_dir = Pin(config_module.RIGHT_DIR_PIN, Pin.OUT)
        self.right_pwm = PWM(Pin(config_module.RIGHT_PWM_PIN), freq=config_module.MOTOR_FREQ, duty=0)
        self.head_servo = PWM(Pin(config_module.HEAD_SERVO_PIN), freq=config_module.SERVO_FREQ)
        self.claw_servo = PWM(Pin(config_module.CLAW_SERVO_PIN), freq=config_module.SERVO_FREQ)
        try:
            self.trig = Pin(config_module.SONAR_TRIG_PIN, Pin.OUT, value=0)
            self.echo = Pin(config_module.SONAR_ECHO_PIN, Pin.IN)
        except Exception:
            self.trig = None
            self.echo = None

        self.face = FaceAnimator(config_module)
        self.lights = ChassisLightAnimator(config_module)
        self.mode = "manual"
        self.auto_state = "idle"
        self.auto_paused = True
        self.manual_motion_until = None
        self.manual_left_speed = config_module.MANUAL_SPEED
        self.manual_right_speed = config_module.MANUAL_SPEED
        self.head_angle = config_module.HEAD_CENTER_ANGLE
        self.claw_angle = config_module.CLAW_OPEN_ANGLE
        self.network_station_connected = True
        self.motion_state = "idle"
        self.forward_head_locked = False
        self.front_distance_cm = -1
        self.front_distance_raw_cm = -1
        self.front_guard_distance_cm = -1
        self.last_front_sample_ms = None
        self.last_front_valid_ms = None
        self.forward_guard_state = "clear"
        self.forward_limit_pwm = max(self.manual_left_speed, self.manual_right_speed)
        self.left_clearance_cm = -1
        self.right_clearance_cm = -1
        self.model_kind = "clear"
        self.model_score = 0.0
        self.model_width_cm = 0.0
        self.ball_visible = False
        self.ball_direction = "none"
        self.ball_distance_cm = -1
        self.scan_plan = self._scan_plan()
        self.scan_step_deg = self._scan_step_deg()
        self.scan_samples = {}
        self.scan_index = 0
        self.scan_label = "center"
        self.scan_angle = config_module.HEAD_CENTER_ANGLE
        self.scan_pending_label = None
        self.scan_pending_angle = None
        self.scan_pending_due_ms = None
        self.last_scan_step_ms = None
        self.script_name = None
        self.script_phase = ""
        self.script_started_ms = None
        self.script_phase_started_ms = None
        self.script_source = "manual"

        self.center_head()
        self.open_claw()
        self.stop()
        self.face.set("manual")
        self._refresh_visuals()

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

    def set_network_connected(self, connected):
        connected = bool(connected)
        if self.network_station_connected == connected:
            return
        self.network_station_connected = connected
        self._refresh_visuals()

    def _refresh_visuals(self):
        if not self.network_station_connected:
            self.face.set_override("cry")
            self.lights.set_base("network_lost")
            return

        self.face.clear_override()
        if self.script_name == "kick":
            if self.script_phase in ("charge", "release", "decel"):
                self.lights.set_base("kick_charge")
                self.face.set("capture")
            else:
                self.lights.set_base("kick_seek")
                self.face.set("front" if not self.ball_visible else "capture")
            return

        if self.mode == "auto":
            if self.auto_paused:
                self.lights.set_base("auto_paused")
                self.face.set("thinking")
            elif self.auto_state in ("track", "capture", "kick", "seek"):
                self.lights.set_base("ball_track")
                has_ball = self.ball_visible or self.claw_angle >= self.cfg.CLAW_HOLD_ANGLE
                self.face.set("capture" if has_ball else "front")
            elif self.auto_state == "avoid":
                self.lights.set_base("guard_slow")
                self.face.set("stop")
            else:
                self.lights.set_base("scan_sweep")
                self.face.set("thinking")
            return

        if self.forward_guard_state == "blocked" and self.face.active_name() == "stop":
            self.lights.set_base("guard_stop")
        elif self.motion_state == "forward":
            if self.forward_guard_state == "track":
                self.lights.set_base("ball_track")
            elif self.forward_guard_state == "slowdown":
                self.lights.set_base("guard_slow")
            else:
                self.lights.set_base("scan_sweep")
        elif self.motion_state == "backward":
            self.lights.set_base("drive_backward")
        elif self.motion_state == "left":
            self.lights.set_base("turn_left")
        elif self.motion_state == "right":
            self.lights.set_base("turn_right")
        elif self.claw_angle >= self.cfg.CLAW_HOLD_ANGLE:
            self.lights.set_base("hold_ball")
        else:
            self.lights.set_base("manual_idle")

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
        if self.motion_state != "forward" and self.forward_guard_state not in ("blocked", "track"):
            self.forward_limit_pwm = max(self.manual_left_speed, self.manual_right_speed)

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

    def stop(self, preserve_guard=False):
        self.drive(0, 0)
        self.motion_state = "idle"
        self._release_forward_head_lock()
        if not preserve_guard:
            self._clear_forward_guard()

    def _arm_manual_timeout(self):
        self.manual_motion_until = hw.ticks_add(hw.ticks_ms(), self.cfg.MANUAL_COMMAND_TIMEOUT_MS)

    def handle_ok_button(self):
        if self.mode == "auto":
            self.auto_paused = not self.auto_paused
            if self.auto_paused:
                self._stop_script()
            self.stop()
            self.lights.flash("mode_shift", 520)
            self._refresh_visuals()
            return "auto:%s" % ("pause" if self.auto_paused else "resume")

        if self.claw_angle >= self.cfg.CLAW_HOLD_ANGLE:
            self.open_claw()
            self.face.set("manual")
            self.lights.flash("release_burst", 540)
            self._refresh_visuals()
            return "claw:release"
        self.close_claw()
        self.face.set("capture")
        self.lights.flash("grab_burst", 620)
        self._refresh_visuals()
        return "claw:grab"

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

    def preview_faces(self):
        self.lights.flash("face_demo", 1800)
        self.face.demo()
        self.face.set("manual")
        self._refresh_visuals()
        return "face:demo"

    def summary(self):
        if self.mode == "auto":
            control_state = "auto-paused" if self.auto_paused else ("auto-%s" % self.auto_state)
        else:
            control_state = "manual"
        return {
            "mode": self.mode,
            "control_state": control_state,
            "auto_state": self.auto_state,
            "auto_paused": self.auto_paused,
            "manual_left_speed": self.manual_left_speed,
            "manual_right_speed": self.manual_right_speed,
            "display": self.face.available(),
            "display_face": self.face.active_name(),
            "lights": self.lights.available(),
            "lights_scene": self.lights.scene_name(),
            "network_station_connected": self.network_station_connected,
            "captured_ball": self.claw_angle >= self.cfg.CLAW_HOLD_ANGLE,
            "sonar_cm": self.front_distance_cm,
            "sonar_raw_cm": self.front_distance_raw_cm,
            "sonar_guard_cm": self.front_guard_distance_cm,
            "sonar_available": self.sonar_available(),
            "forward_limit_pwm": self.forward_limit_pwm,
            "forward_guard_state": self.forward_guard_state,
            "forward_head_locked": self.forward_head_locked,
            "scan_label": self.scan_label,
            "scan_angle": self.scan_angle,
            "model_kind": self.model_kind,
            "model_score": round(self.model_score, 3),
            "model_width_cm": round(self.model_width_cm, 2),
            "ball_visible": self.ball_visible,
            "ball_direction": self.ball_direction,
            "ball_distance_cm": self.ball_distance_cm,
            "left_clearance_cm": self.left_clearance_cm,
            "right_clearance_cm": self.right_clearance_cm,
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
            self.face.set("manual")
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
            return self._start_kick_script(source="manual" if self.mode != "auto" else "auto")

        if path in self.cfg.BUTTON_POLICY_RESET_ALIASES:
            return "policy:disabled"

        if path in self.cfg.BUTTON_FACE_DEMO_ALIASES:
            return self.preview_faces()

        if path in self.cfg.BUTTON_FACE_NEXT_ALIASES:
            return "face:%s" % self.face.next_cycle()

        if path in self.cfg.BUTTON_FACE_CLEAR_ALIASES:
            self.face.clear_face()
            self.lights.flash("mode_shift", 360)
            return "face:clear"

        if path in self.cfg.BUTTON_FACE_PREV_ALIASES:
            return "face:%s" % self.face.prev_cycle()

        if path in self.cfg.BUTTON_GRAB_ALIASES:
            self.mode = "manual"
            self._stop_script()
            self._release_forward_head_lock()
            self.close_claw()
            self.face.set("capture")
            self.lights.flash("grab_burst", 620)
            self._refresh_visuals()
            return "claw:grab"

        if path in self.cfg.BUTTON_RELEASE_ALIASES:
            self.mode = "manual"
            self._stop_script()
            self._release_forward_head_lock()
            self.open_claw_wide()
            self.face.set("manual")
            self.lights.flash("release_burst", 540)
            self._refresh_visuals()
            return "claw:release-wide"

        if path in self.cfg.BUTTON_PAN_LEFT_ALIASES:
            if self.mode != "manual":
                return "ignored:auto-mode"
            if self.motion_state == "forward":
                return "ignored:forward-scan-active"
            self._stop_script()
            self._clear_forward_guard()
            self.head_left()
            self.face.set("manual")
            self.lights.flash("pan_left", 520)
            self._refresh_visuals()
            return "pan:left"

        if path in self.cfg.BUTTON_PAN_CENTER_ALIASES:
            if self.mode != "manual":
                return "ignored:auto-mode"
            if self.motion_state == "forward":
                return "ignored:forward-scan-active"
            self._stop_script()
            self._clear_forward_guard()
            self.center_head()
            self.face.set("manual")
            self.lights.flash("pan_center", 520)
            self._refresh_visuals()
            return "pan:center"

        if path in self.cfg.BUTTON_PAN_RIGHT_ALIASES:
            if self.mode != "manual":
                return "ignored:auto-mode"
            if self.motion_state == "forward":
                return "ignored:forward-scan-active"
            self._stop_script()
            self._clear_forward_guard()
            self.head_right()
            self.face.set("manual")
            self.lights.flash("pan_right", 520)
            self._refresh_visuals()
            return "pan:right"

        if path == self.cfg.BUTTON_FORWARD:
            if self.mode != "manual":
                return "ignored:auto-mode"
            self._stop_script()
            return self._apply_forward_motion(force_sample=True, arm_timeout=True, prefer_ball=False)

        if path == self.cfg.BUTTON_BACKWARD:
            if self.mode != "manual":
                return "ignored:auto-mode"
            self._stop_script()
            self._release_forward_head_lock()
            self._clear_forward_guard()
            self.drive(-self.manual_left_speed, -self.manual_right_speed)
            self._arm_manual_timeout()
            self.motion_state = "backward"
            self.face.set("back")
            self._refresh_visuals()
            return "drive:backward"

        if path == self.cfg.BUTTON_LEFT:
            if self.mode != "manual":
                return "ignored:auto-mode"
            return self._smart_turn("left", arm_timeout=True)

        if path == self.cfg.BUTTON_RIGHT:
            if self.mode != "manual":
                return "ignored:auto-mode"
            return self._smart_turn("right", arm_timeout=True)

        if path == self.cfg.BUTTON_STOP:
            self._stop_script()
            self.stop()
            self.manual_motion_until = None
            self.lights.flash("brake", 420)
            if self.mode == "auto":
                self.auto_paused = True
                self.auto_state = "idle"
                self._refresh_visuals()
                return "auto:pause"
            self.face.set("stop")
            self._refresh_visuals()
            return "drive:stop"

        if path == "/":
            return "hello"

        return "unknown"

    def update(self):
        now = hw.ticks_ms()
        if self.script_name == "kick":
            self._update_kick_script(now)
        elif self.mode == "manual" and self.manual_motion_until is not None:
            if self.motion_state == "forward":
                self._apply_forward_motion(force_sample=False, arm_timeout=False, prefer_ball=False)
                self._update_scan_head()
                now = hw.ticks_ms()
            if self.manual_motion_until is None:
                self.face.tick()
                self.lights.tick()
                return
            if hw.ticks_diff(now, self.manual_motion_until) >= 0:
                self.stop()
                self.manual_motion_until = None
                if self.network_station_connected:
                    self.face.set("manual")
                self._refresh_visuals()
        elif self.mode == "auto":
            self._auto_tick()
        self.face.tick()
        self.lights.tick()

    def shutdown(self):
        self._stop_script()
        self.stop()
        self.center_head()
        self.open_claw()
        self.face.shutdown()
        self.lights.shutdown()
