import math

import compat as hw


def _clamp(value, lower, upper):
    if value < lower:
        return lower
    if value > upper:
        return upper
    return value


class SmartDriveMixin:
    def _scan_plan(self):
        center = int(self.cfg.HEAD_CENTER_ANGLE)
        left = int(self.cfg.HEAD_LEFT_ANGLE)
        right = int(self.cfg.HEAD_RIGHT_ANGLE)
        left_mid = int(center + (left - center) * 0.55)
        right_mid = int(center + (right - center) * 0.55)
        return (
            ("center_0", int(_clamp(center, 0, 180))),
            ("left_mid", int(_clamp(left_mid, 0, 180))),
            ("center_1", int(_clamp(center, 0, 180))),
            ("right_mid", int(_clamp(right_mid, 0, 180))),
            ("center_2", int(_clamp(center, 0, 180))),
            ("left", int(_clamp(left, 0, 180))),
            ("center_3", int(_clamp(center, 0, 180))),
            ("right", int(_clamp(right, 0, 180))),
        )

    def _scan_step_deg(self):
        last_angle = None
        min_step = None
        for _label, angle in self.scan_plan:
            if last_angle is not None:
                delta = abs(angle - last_angle)
                if delta > 0 and (min_step is None or delta < min_step):
                    min_step = delta
            last_angle = angle
        return max(6, int(min_step or 8))

    def sonar_available(self):
        return self.trig is not None and self.echo is not None

    def _release_forward_head_lock(self):
        self.forward_head_locked = False

    def _clear_forward_guard(self):
        self.forward_guard_state = "clear"
        self.forward_limit_pwm = max(self.manual_left_speed, self.manual_right_speed)

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

    def _record_scan_sample(self, label, angle, distance_cm):
        now = hw.ticks_ms()
        self.scan_samples[label] = {
            "label": label,
            "angle": int(angle),
            "distance": int(distance_cm),
            "ts": now,
        }
        self.last_front_sample_ms = now
        self.scan_label = label
        self.scan_angle = int(angle)

    def _fresh_scan_samples(self, max_age_ms=None):
        if max_age_ms is None:
            max_age_ms = int(getattr(self.cfg, "SONAR_SCAN_MEMORY_MS", 780) or 780)
        now = hw.ticks_ms()
        samples = []
        for sample in self.scan_samples.values():
            if hw.ticks_diff(now, sample["ts"]) <= max_age_ms:
                samples.append(sample)
        samples.sort(key=lambda item: item["angle"])
        return samples

    def _estimate_width_cm(self, distance_cm, span_deg):
        if distance_cm <= 0:
            return 0.0
        span_rad = (max(1.0, float(span_deg)) * math.pi) / 180.0
        return 2.0 * float(distance_cm) * math.tan(span_rad / 2.0)

    def _ball_candidate_score(self, sample, samples):
        distance_cm = int(sample["distance"])
        if distance_cm < self.cfg.BALL_DETECT_MIN_CM or distance_cm > self.cfg.BALL_DETECT_MAX_CM:
            return 0.0, 0.0

        span_deg = float(max(14, self.scan_step_deg * 2))
        close_count = 1
        before = None
        after = None
        for other in samples:
            if other is sample or int(other["distance"]) <= 0:
                continue
            delta_angle = other["angle"] - sample["angle"]
            if delta_angle < 0:
                if before is None or delta_angle > before["angle"] - sample["angle"]:
                    before = other
            elif delta_angle > 0:
                if after is None or delta_angle < after["angle"] - sample["angle"]:
                    after = other
            if abs(delta_angle) <= self.scan_step_deg * 1.2 and abs(int(other["distance"]) - distance_cm) <= 4:
                close_count += 1
                span_deg = max(span_deg, abs(delta_angle) + self.scan_step_deg)

        width_cm = self._estimate_width_cm(distance_cm, span_deg)
        size_tol = float(getattr(self.cfg, "BALL_WIDTH_TOL_CM", 2) or 2)
        contrast_scale = float(getattr(self.cfg, "BALL_NEIGHBOR_CONTRAST_CM", 5) or 5)
        ball_size = float(getattr(self.cfg, "BALL_DIAMETER_CM", 3) or 3)
        size_score = 1.0 - (abs(width_cm - ball_size) / max(1.0, size_tol))
        if size_score < 0.0:
            size_score = 0.0

        neighbor_distances = []
        if before is not None and int(before["distance"]) > 0:
            neighbor_distances.append(int(before["distance"]))
        if after is not None and int(after["distance"]) > 0:
            neighbor_distances.append(int(after["distance"]))
        if neighbor_distances:
            contrast = (sum(neighbor_distances) / float(len(neighbor_distances))) - float(distance_cm)
            contrast_score = contrast / max(1.0, contrast_scale)
            if contrast_score < 0.0:
                contrast_score = 0.0
            if contrast_score > 1.0:
                contrast_score = 1.0
        else:
            contrast_score = 0.42

        compact_score = 1.0
        if close_count >= 3:
            compact_score = 0.45
        elif close_count == 2:
            compact_score = 0.78

        score = (0.58 * size_score) + (0.30 * contrast_score) + (0.12 * compact_score)
        if width_cm > ball_size + (size_tol * 2.0):
            score *= 0.45
        if score < 0.0:
            score = 0.0
        if score > 1.0:
            score = 1.0
        return score, width_cm

    def _refresh_spatial_model(self):
        center = int(self.cfg.HEAD_CENTER_ANGLE)
        front_cone = int(getattr(self.cfg, "SONAR_FRONT_CONE_DEG", 10) or 10)
        front_model_deg = int(getattr(self.cfg, "SONAR_FRONT_MODEL_DEG", 18) or 18)
        samples = self._fresh_scan_samples()
        valid = [sample for sample in samples if int(sample["distance"]) > 0]

        front_samples = [sample for sample in valid if abs(int(sample["angle"]) - center) <= front_model_deg]
        guard_samples = [sample for sample in valid if str(sample["label"]).startswith("center")]
        left_samples = [sample for sample in valid if int(sample["angle"]) > center + front_cone]
        right_samples = [sample for sample in valid if int(sample["angle"]) < center - front_cone]

        self.left_clearance_cm = min([int(sample["distance"]) for sample in left_samples] or [-1])
        self.right_clearance_cm = min([int(sample["distance"]) for sample in right_samples] or [-1])
        self.front_distance_raw_cm = min([int(sample["distance"]) for sample in front_samples] or [-1])
        self.front_guard_distance_cm = min([int(sample["distance"]) for sample in guard_samples] or [-1])
        if self.front_guard_distance_cm > 0:
            self.front_distance_cm = self.front_guard_distance_cm
            self.last_front_valid_ms = hw.ticks_ms()
        elif self.front_distance_raw_cm > 0:
            self.front_distance_cm = self.front_distance_raw_cm
            self.last_front_valid_ms = hw.ticks_ms()
        else:
            cache_ms = int(getattr(self.cfg, "SONAR_CACHE_MS", 520) or 520)
            now = hw.ticks_ms()
            if self.last_front_valid_ms is None or hw.ticks_diff(now, self.last_front_valid_ms) >= cache_ms:
                self.front_distance_cm = -1

        best_ball = None
        best_ball_score = 0.0
        best_ball_width = 0.0
        for sample in valid:
            score, width_cm = self._ball_candidate_score(sample, valid)
            if score > best_ball_score:
                best_ball = sample
                best_ball_score = score
                best_ball_width = width_cm

        self.ball_visible = False
        self.ball_direction = "none"
        self.ball_distance_cm = -1
        ball_threshold = float(getattr(self.cfg, "BALL_SCORE_MIN", 0.62) or 0.62)
        if best_ball is not None and best_ball_score >= ball_threshold:
            self.ball_visible = True
            self.ball_distance_cm = int(best_ball["distance"])
            angle = int(best_ball["angle"])
            if abs(angle - center) <= front_cone:
                self.ball_direction = "center"
            elif angle > center:
                self.ball_direction = "left"
            else:
                self.ball_direction = "right"

        self.model_kind = "clear"
        self.model_score = 0.0
        self.model_width_cm = 0.0
        if self.front_guard_distance_cm > 0:
            front_ball = (
                self.ball_visible
                and self.ball_direction == "center"
                and self.ball_distance_cm == self.front_guard_distance_cm
            )
            if front_ball:
                self.model_kind = "ball"
                self.model_score = best_ball_score
                self.model_width_cm = best_ball_width
            else:
                near_front = [
                    sample
                    for sample in front_samples
                    if int(sample["distance"]) > 0 and int(sample["distance"]) <= self.front_guard_distance_cm + 4
                ]
                if near_front:
                    angles = [int(sample["angle"]) for sample in near_front]
                    span_deg = max(14, (max(angles) - min(angles)) + self.scan_step_deg)
                else:
                    span_deg = max(14, self.scan_step_deg * 2)
                width_cm = self._estimate_width_cm(self.front_guard_distance_cm, span_deg)
                self.model_width_cm = width_cm
                if len(near_front) >= 3 or width_cm >= float(self.cfg.BALL_DIAMETER_CM + (self.cfg.BALL_WIDTH_TOL_CM * 2.0)):
                    self.model_kind = "wall"
                    self.model_score = min(
                        1.0,
                        0.45 + (width_cm / max(1.0, float(self.cfg.BALL_DIAMETER_CM * 3.0))),
                    )
                else:
                    self.model_kind = "obstacle"
                    self.model_score = min(
                        1.0,
                        0.35
                        + (
                            float(max(0, self.cfg.FORWARD_SLOWDOWN_CM - self.front_guard_distance_cm))
                            / max(1.0, float(self.cfg.FORWARD_SLOWDOWN_CM))
                        ),
                    )

        self.forward_head_locked = abs(int(self.head_angle) - center) <= front_cone

    def _measure_at_angle(self, angle, label, samples=1, settle_ms=None):
        if not self.sonar_available():
            self.front_distance_raw_cm = -1
            self.front_distance_cm = -1
            self.front_guard_distance_cm = -1
            return -1
        if settle_ms is None:
            settle_ms = int(getattr(self.cfg, "SONAR_SCAN_SETTLE_MS", 65) or 65)
        moved = abs(int(self.head_angle) - int(angle)) > 1
        self.set_head_angle(int(angle))
        if moved and settle_ms > 0:
            hw.sleep_ms(settle_ms)
        distance_cm = self.measure_distance_filtered(samples)
        self._record_scan_sample(label, angle, distance_cm)
        self._refresh_spatial_model()
        return distance_cm

    def _has_fresh_front_sample(self, max_age_ms=None):
        if max_age_ms is None:
            max_age_ms = int(getattr(self.cfg, "SONAR_FORWARD_POLL_MS", 95) or 95) * 3
        center = int(self.cfg.HEAD_CENTER_ANGLE)
        cone = int(getattr(self.cfg, "SONAR_FRONT_CONE_DEG", 10) or 10)
        for sample in self._fresh_scan_samples(max_age_ms=max_age_ms):
            if int(sample["distance"]) > 0 and (
                str(sample["label"]).startswith("center") or abs(int(sample["angle"]) - center) <= cone
            ):
                return True
        return False

    def _sample_forward_scene(self, force=False):
        if not self.sonar_available():
            self.front_distance_raw_cm = -1
            self.front_distance_cm = -1
            self.front_guard_distance_cm = -1
            return -1
        if force or not self._has_fresh_front_sample():
            return self._measure_at_angle(
                self.cfg.HEAD_CENTER_ANGLE,
                "center_guard",
                samples=int(getattr(self.cfg, "SONAR_SAMPLES_FORWARD", 2) or 2),
                settle_ms=int(getattr(self.cfg, "FORWARD_HEAD_SETTLE_MS", 120) or 120) if force else None,
            )
        self._refresh_spatial_model()
        return self.front_guard_distance_cm

    def _update_scan_head(self, force=False):
        if not self.sonar_available():
            return

        scanning = (
            self.script_name == "kick"
            or (self.mode == "auto" and not self.auto_paused)
            or (self.mode == "manual" and self.motion_state == "forward")
        )
        if not scanning and not force:
            self.scan_pending_label = None
            self.scan_pending_due_ms = None
            return

        now = hw.ticks_ms()
        if self.scan_pending_label is not None:
            if hw.ticks_diff(now, self.scan_pending_due_ms) >= 0:
                self._measure_at_angle(
                    self.scan_pending_angle,
                    self.scan_pending_label,
                    samples=int(getattr(self.cfg, "SONAR_SWEEP_SAMPLES", 1) or 1),
                    settle_ms=0,
                )
                self.scan_pending_label = None
                self.scan_pending_due_ms = None
                self.scan_index = (self.scan_index + 1) % len(self.scan_plan)
            return

        interval_ms = int(getattr(self.cfg, "SONAR_SWEEP_INTERVAL_MS", 95) or 95)
        if (
            not force
            and self.last_scan_step_ms is not None
            and hw.ticks_diff(now, self.last_scan_step_ms) < interval_ms
        ):
            return

        label, angle = self.scan_plan[self.scan_index]
        self.set_head_angle(angle)
        self.scan_label = label
        self.scan_angle = angle
        self.last_scan_step_ms = now
        self.scan_pending_label = label
        self.scan_pending_angle = angle
        settle_ms = int(getattr(self.cfg, "SONAR_SCAN_SETTLE_MS", 65) or 65)
        self.scan_pending_due_ms = hw.ticks_add(now, settle_ms)

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

    def _forward_trim_pwm(self, prefer_ball=False):
        gain = int(getattr(self.cfg, "SONAR_TRIM_GAIN", 18) or 18)
        max_trim = int(getattr(self.cfg, "SONAR_TRIM_MAX_PWM", 210) or 210)
        caution_cm = int(getattr(self.cfg, "SONAR_SIDE_CAUTION_CM", 18) or 18)
        bias = 0

        if self.left_clearance_cm > 0:
            bias -= max(0, caution_cm - self.left_clearance_cm) * gain // 2
        if self.right_clearance_cm > 0:
            bias += max(0, caution_cm - self.right_clearance_cm) * gain // 2
        if self.left_clearance_cm > 0 and self.right_clearance_cm > 0:
            bias += (self.left_clearance_cm - self.right_clearance_cm) * gain // 4

        if prefer_ball and self.ball_visible:
            seek_push = max_trim // 3
            if self.ball_direction == "left":
                bias += seek_push
            elif self.ball_direction == "right":
                bias -= seek_push

        return int(_clamp(bias, -max_trim, max_trim))

    def _scale_forward_pair(self, left_pwm, right_pwm, limit_pwm):
        left_pwm = int(max(0, left_pwm))
        right_pwm = int(max(0, right_pwm))
        limit_pwm = int(max(0, limit_pwm))
        requested_max = max(left_pwm, right_pwm)
        if requested_max > 0 and limit_pwm > 0 and requested_max > limit_pwm:
            left_pwm = (left_pwm * limit_pwm) // requested_max
            right_pwm = (right_pwm * limit_pwm) // requested_max
        return left_pwm, right_pwm

    def _drive_forward_trimmed(self, base_left, base_right, limit_pwm, trim_pwm=0):
        left_pwm, right_pwm = self._scale_forward_pair(base_left, base_right, limit_pwm)
        if limit_pwm <= 0:
            self.drive(0, 0)
            return 0, 0

        left_pwm = int(_clamp(left_pwm - trim_pwm, 0, limit_pwm))
        right_pwm = int(_clamp(right_pwm + trim_pwm, 0, limit_pwm))
        if left_pwm == 0 and right_pwm == 0:
            left_pwm = right_pwm = min(limit_pwm, 60)
        self.drive(left_pwm, right_pwm)
        return left_pwm, right_pwm

    def _apply_forward_motion(self, force_sample=False, arm_timeout=False, prefer_ball=False, base_left=None, base_right=None):
        if base_left is None:
            base_left = self.manual_left_speed
        if base_right is None:
            base_right = self.manual_right_speed
        requested_left = int(base_left)
        requested_right = int(base_right)
        requested_pwm = max(requested_left, requested_right)
        self._sample_forward_scene(force=force_sample)
        distance_cm = self.front_guard_distance_cm
        limit_pwm = self._forward_speed_cap(distance_cm, requested_pwm)
        previous_guard = self.forward_guard_state
        previous_limit = self.forward_limit_pwm
        previous_motion = self.motion_state
        current_kind = self.model_kind

        ball_centered = self.ball_visible and self.ball_direction == "center" and current_kind == "ball"
        if ball_centered and self.ball_distance_cm > 0:
            approach_pwm = int(getattr(self.cfg, "BALL_CAPTURE_APPROACH_PWM", 180) or 180)
            if self.ball_distance_cm <= int(getattr(self.cfg, "BALL_CAPTURE_APPROACH_CM", 4) or 4):
                limit_pwm = min(requested_pwm, approach_pwm)
            else:
                limit_pwm = min(limit_pwm or requested_pwm, max(approach_pwm, self.cfg.FORWARD_NEAR_PWM))

        if limit_pwm <= 0 and not ball_centered:
            self.forward_guard_state = "blocked"
            self.forward_limit_pwm = 0
            self.stop(preserve_guard=True)
            self.manual_motion_until = None
            self.face.set("stop")
            self.lights.flash("guard_stop", 420)
            self._refresh_visuals()
            if distance_cm > 0:
                return "drive:blocked:%dcm" % distance_cm
            return "drive:blocked"

        if ball_centered:
            self.forward_guard_state = "track"
        elif 0 < limit_pwm < requested_pwm:
            self.forward_guard_state = "slowdown"
        else:
            self.forward_guard_state = "clear"
        self.forward_limit_pwm = limit_pwm

        trim_pwm = self._forward_trim_pwm(prefer_ball=prefer_ball)
        self._drive_forward_trimmed(requested_left, requested_right, limit_pwm, trim_pwm=trim_pwm)
        if arm_timeout:
            self._arm_manual_timeout()
        self.motion_state = "forward"
        self.face.set("capture" if ball_centered else "front")
        self._refresh_visuals()

        if (
            self.forward_guard_state != previous_guard
            or self.forward_limit_pwm != previous_limit
            or previous_motion != "forward"
        ):
            if self.forward_guard_state == "slowdown":
                self.lights.flash("guard_slow", 180)
            elif self.forward_guard_state == "track":
                self.lights.flash("ball_track", 180)

        if ball_centered and self.ball_distance_cm > 0:
            return "drive:track-ball:%dcm:%d" % (self.ball_distance_cm, limit_pwm)
        if distance_cm > 0:
            return "drive:forward:%dcm:%d" % (distance_cm, limit_pwm)
        return "drive:forward:%d" % limit_pwm

    def _choose_clearer_turn(self):
        if self.left_clearance_cm < 0 and self.right_clearance_cm < 0:
            return "left"
        if self.left_clearance_cm < 0:
            return "left"
        if self.right_clearance_cm < 0:
            return "right"
        return "left" if self.left_clearance_cm >= self.right_clearance_cm else "right"

    def _smart_turn(self, direction, arm_timeout=False, scripted=False):
        self._release_forward_head_lock()
        self._clear_forward_guard()
        if self.script_name is not None and not scripted:
            self._stop_script()

        if direction == "left":
            side_angle = self.cfg.HEAD_LEFT_ANGLE
            label = "turn_left_scan"
        else:
            side_angle = self.cfg.HEAD_RIGHT_ANGLE
            label = "turn_right_scan"
        self._measure_at_angle(
            side_angle,
            label,
            samples=int(getattr(self.cfg, "SONAR_SAMPLES_FORWARD", 2) or 2),
            settle_ms=int(getattr(self.cfg, "SONAR_SCAN_SETTLE_MS", 65) or 65),
        )

        tight_cm = int(getattr(self.cfg, "TURN_TIGHT_CM", 14) or 14)
        open_cm = int(getattr(self.cfg, "TURN_OPEN_CM", 34) or 34)
        pivot_pwm = int(getattr(self.cfg, "TURN_PIVOT_INNER_PWM", 260) or 260)
        arc_min_pwm = int(getattr(self.cfg, "TURN_ARC_INNER_MIN", 160) or 160)
        outer_pwm = int(_clamp(self.cfg.TURN_SPEED, 0, self.cfg.MAX_PWM))

        clearance = self.left_clearance_cm if direction == "left" else self.right_clearance_cm
        if clearance <= 0 or clearance <= tight_cm:
            inner_pwm = pivot_pwm
        elif clearance >= open_cm:
            inner_pwm = arc_min_pwm
        else:
            span = max(1, open_cm - tight_cm)
            inner_pwm = pivot_pwm - ((clearance - tight_cm) * (pivot_pwm - arc_min_pwm)) // span
        inner_pwm = int(_clamp(inner_pwm, arc_min_pwm, pivot_pwm))

        if direction == "left":
            self.drive(-inner_pwm, outer_pwm)
            self.motion_state = "left"
            self.face.set("left")
        else:
            self.drive(outer_pwm, -inner_pwm)
            self.motion_state = "right"
            self.face.set("right")
        if arm_timeout:
            self._arm_manual_timeout()
        self._refresh_visuals()
        if clearance > 0:
            return "drive:%s:%dcm" % (direction, clearance)
        return "drive:%s" % direction

    def _set_script_phase(self, phase):
        self.script_phase = phase
        self.script_phase_started_ms = hw.ticks_ms()

    def _stop_script(self):
        self.script_name = None
        self.script_phase = ""
        self.script_started_ms = None
        self.script_phase_started_ms = None
        self.script_source = "manual"

    def _start_kick_script(self, source="manual"):
        if self.claw_angle < self.cfg.CLAW_HOLD_ANGLE:
            return "kick:no-ball"
        self.script_name = "kick"
        self.script_source = source
        now = hw.ticks_ms()
        self.script_started_ms = now
        self.script_phase_started_ms = now
        self.script_phase = "charge"
        self.manual_motion_until = None
        self.auto_state = "kick"
        self.face.set("capture")
        self.lights.flash("kick_charge", 380)
        self._refresh_visuals()
        return "kick:armed"

    def _update_kick_script(self, now):
        if self.script_name != "kick":
            return

        charge_ms = int(getattr(self.cfg, "KICK_CHARGE_MS", 240) or 240)
        release_ms = int(getattr(self.cfg, "KICK_RELEASE_MS", 150) or 150)
        decel_ms = int(getattr(self.cfg, "KICK_DECEL_MS", 220) or 220)
        seek_ms = int(getattr(self.cfg, "KICK_SEEK_MS", 1300) or 1300)

        elapsed = hw.ticks_diff(now, self.script_phase_started_ms)
        if self.script_phase == "charge":
            self._sample_forward_scene(force=False)
            if (
                self.front_guard_distance_cm > 0
                and self.model_kind not in ("clear", "ball")
                and self.front_guard_distance_cm <= self.cfg.OBSTACLE_ESCAPE_CM
            ):
                self.stop()
                self.face.set("stop")
                self.forward_guard_state = "blocked"
                self._stop_script()
                self._refresh_visuals()
                return

            start_pwm = int(_clamp(self.cfg.RAM_PREP_SPEED, 0, self.cfg.MAX_PWM))
            end_pwm = int(_clamp(getattr(self.cfg, "KICK_CHARGE_PWM", 920) or 920, 0, self.cfg.MAX_PWM))
            span = max(1, charge_ms)
            current_pwm = start_pwm + ((min(elapsed, span) * (end_pwm - start_pwm)) // span)
            self._drive_forward_trimmed(current_pwm, current_pwm, current_pwm, trim_pwm=self._forward_trim_pwm())
            self.motion_state = "forward"
            self.face.set("capture")
            self._refresh_visuals()
            if elapsed >= charge_ms:
                self.open_claw_wide()
                self.lights.flash("release_burst", 260)
                self._set_script_phase("release")
            return

        if self.script_phase == "release":
            release_pwm = int(_clamp(getattr(self.cfg, "KICK_RELEASE_PWM", 980) or 980, 0, self.cfg.MAX_PWM))
            self._drive_forward_trimmed(release_pwm, release_pwm, release_pwm, trim_pwm=0)
            self.motion_state = "forward"
            self.face.set("front")
            self._refresh_visuals()
            if elapsed >= release_ms:
                self._set_script_phase("decel")
            return

        if self.script_phase == "decel":
            start_pwm = int(_clamp(getattr(self.cfg, "KICK_RELEASE_PWM", 980) or 980, 0, self.cfg.MAX_PWM))
            end_pwm = int(_clamp(getattr(self.cfg, "KICK_DECEL_PWM", 360) or 360, 0, self.cfg.MAX_PWM))
            span = max(1, decel_ms)
            current_pwm = start_pwm + ((min(elapsed, span) * (end_pwm - start_pwm)) // span)
            self._drive_forward_trimmed(current_pwm, current_pwm, current_pwm, trim_pwm=0)
            self.motion_state = "forward"
            self.face.set("front")
            self._refresh_visuals()
            if elapsed >= decel_ms:
                self.open_claw()
                self._set_script_phase("seek")
            return

        if self.script_phase == "seek":
            self._update_scan_head()
            self._refresh_spatial_model()
            if (
                self.front_guard_distance_cm > 0
                and self.model_kind not in ("clear", "ball")
                and self.front_guard_distance_cm <= self.cfg.FORWARD_STOP_CM
            ):
                self._smart_turn(self._choose_clearer_turn(), arm_timeout=False, scripted=True)
                self._set_script_phase("seek")
                return

            seek_pwm = int(_clamp(getattr(self.cfg, "KICK_SEEK_PWM", 460) or 460, 0, self.cfg.MAX_PWM))
            self._apply_forward_motion(
                force_sample=False,
                arm_timeout=False,
                prefer_ball=True,
                base_left=seek_pwm,
                base_right=seek_pwm,
            )
            self.auto_state = "seek"
            if elapsed >= seek_ms:
                self._stop_script()
                if self.mode == "auto" and not self.auto_paused:
                    self.auto_state = "search"
                else:
                    self.stop()
                    if self.network_station_connected:
                        self.face.set("manual")
                self._refresh_visuals()

    def _auto_tick(self):
        if self.auto_paused:
            self.stop()
            self.auto_state = "idle"
            self._refresh_visuals()
            return

        if self.script_name == "kick":
            return

        self._update_scan_head()
        self._refresh_spatial_model()

        if self.claw_angle >= self.cfg.CLAW_HOLD_ANGLE:
            self._start_kick_script(source="auto")
            return

        if (
            self.front_guard_distance_cm > 0
            and self.model_kind not in ("clear", "ball")
            and self.front_guard_distance_cm <= self.cfg.OBSTACLE_ESCAPE_CM
        ):
            self.auto_state = "avoid"
            self._smart_turn(self._choose_clearer_turn(), arm_timeout=False, scripted=True)
            return

        if self.ball_visible:
            self.auto_state = "track"
            if self.ball_direction == "center" and 0 < self.ball_distance_cm <= self.cfg.CAPTURE_DISTANCE_CM:
                self.close_claw()
                self.face.set("capture")
                self.lights.flash("grab_burst", 320)
                self._refresh_visuals()
                return
            self._apply_forward_motion(
                force_sample=False,
                arm_timeout=False,
                prefer_ball=True,
                base_left=self.cfg.APPROACH_SPEED,
                base_right=self.cfg.APPROACH_SPEED,
            )
            return

        self.auto_state = "search"
        cruise_pwm = int(
            _clamp(
                getattr(self.cfg, "AUTO_CRUISE_PWM", self.cfg.SEARCH_SPEED) or self.cfg.SEARCH_SPEED,
                0,
                self.cfg.MAX_PWM,
            )
        )
        self._sample_forward_scene(force=False)
        limit_pwm = self._forward_speed_cap(self.front_guard_distance_cm, cruise_pwm)
        trim_pwm = self._forward_trim_pwm(prefer_ball=False)
        self._drive_forward_trimmed(cruise_pwm, cruise_pwm, limit_pwm or cruise_pwm, trim_pwm=trim_pwm)
        self.motion_state = "forward"
        self.face.set("thinking")
        self._refresh_visuals()
