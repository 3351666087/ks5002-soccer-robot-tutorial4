# KS5002 soccer robot configuration for MicroPython.

PROJECT_NAME = "ks5002_soccer_bot"

# Network mode stays on a station-first strategy:
# - The robot joins the current LAN whenever SSID/password are available
# - A fallback AP is only opened when station connection is unavailable
WIFI_MODE = "apsta"

STA_SSID = ""
STA_PASSWORD = ""

AP_SSID = "KS5002-SoccerBot"
AP_PASSWORD = "12345678"

HOST = "0.0.0.0"
PORT = 80
WIFI_CONNECT_TIMEOUT_MS = 12000
WIFI_RETRY_INTERVAL_MS = 9000
WIFI_STATUS_POLL_MS = 700
WIFI_DISCONNECT_GRACE_MS = 2400
RELAY_BASE_URL = ""
RELAY_CONNECT_HOST = ""
RELAY_PULL_MS = 220
RELAY_REPORT_MS = 0
RELAY_PING_MS = 0
LAN_BRIDGE_HOST = ""
LAN_BRIDGE_PORT = 8766
LAN_POLL_MS = 140
LAN_STATUS_MS = 700
MQTT_BROKER_HOST = "broker.emqx.io"
MQTT_CONNECT_HOST = ""
MQTT_BROKER_PORT = 1883
MQTT_NAMESPACE = "ks5002/remote/4d0c9b6a"
MQTT_REPORT_MS = 360
MQTT_KEEPALIVE_S = 0
MQTT_SOCKET_TIMEOUT_S = 0.25
MQTT_WRITE_TIMEOUT_S = 4.5
MQTT_CONNECT_TIMEOUT_S = 12.0
MQTT_RECONNECT_DELAY_MS = 900
MQTT_PRECONNECT_BEFORE_ACTUATORS = True
MQTT_STATUS_PUBLISH_ENABLED = True
REMOTE_TRANSPORT_DISABLE_ONBOARD_HTTP = True
RUNTIME_PROFILE = "lite_remote"
# The ESP32 on this car is sensitive to display / NeoPixel timing while MQTT
# remote control is active. Keep the front matrix and chassis RGB strip out of
# the live MQTT runtime unless a separate hardware probe path is used.
MQTT_ALLOW_DISPLAY_HARDWARE = False
MQTT_ALLOW_LIGHT_HARDWARE = False
MQTT_LIGHT_RECOVERY_MODE = "shadow"
MQTT_LIGHT_ARM_DELAY_MS = 2600
MQTT_LIGHT_TRIP_COOLDOWN_MS = 12000
MQTT_LIGHT_WRITE_MIN_MS = 260
MQTT_LIGHT_HW_MAX_BRIGHTNESS = 14
MQTT_LIGHT_HW_SCALE = 96
MQTT_LIGHT_MAX_TRIPS = 2
MQTT_SAFE_SERVO_HOLD_ENABLED = True
ACTUATOR_BACKEND = "soft"
SOFT_DRIVE_SLICE_MS = 2
SOFT_SERVO_REFRESH_MS = 22
SOFT_SERVO_MOVE_PULSES = 18
SOFT_SERVO_HOLD_REFRESH_MS = 30
SOFT_HEAD_SERVO_REFRESH_MS = 20
SOFT_HEAD_SERVO_MOVE_PULSES = 30
SOFT_HEAD_SERVO_HOLD_REFRESH_MS = 28
SOFT_HEAD_SERVO_MIN_US = 420
SOFT_HEAD_SERVO_MAX_US = 2500
SOFT_CLAW_SERVO_REFRESH_MS = 18
SOFT_CLAW_SERVO_MOVE_PULSES = 54
SOFT_CLAW_SERVO_HOLD_REFRESH_MS = 32
SOFT_CLAW_SERVO_MIN_US = 500
SOFT_CLAW_SERVO_MAX_US = 2500
# Real-board diagnostics show that a physical NeoPixel write can knock the ESP32
# TCP listener off the air under hotspot direct mode. Keep hardware chassis
# lights disabled in the live driving profile until a lower-level transport-safe
# driver is found.
DIRECT_LIGHT_AUTONOMY_ENABLED = False
DIRECT_LIGHT_MAX_BRIGHTNESS = 26
LIGHT_FRAME_MS = 140
LIGHT_BURST_MS = 680
LIGHT_MAX_BRIGHTNESS = 56

# KS5002 pins confirmed from the official Keyestudio documentation.
LEFT_DIR_PIN = 33
LEFT_PWM_PIN = 26
RIGHT_DIR_PIN = 32
RIGHT_PWM_PIN = 25

HEAD_SERVO_PIN = 4
# The claw servo signal has been rerouted from the stock KS5002 S2 header
# to the current D13 signal pad on this robot.
CLAW_SERVO_PIN = 13

SONAR_TRIG_PIN = 5
SONAR_ECHO_PIN = 18

RGB_PIN = 14

DISPLAY_SDA_PIN = 21
DISPLAY_SCL_PIN = 22
DISPLAY_I2C_ADDR = 0x70
DISPLAY_BRIGHTNESS = 4
DISPLAY_ROTATION = 90

MOTOR_FREQ = 12500
SERVO_FREQ = 50
MAX_PWM = 1023

MANUAL_SPEED = 760
TURN_SPEED = 680
SEARCH_SPEED = 560
APPROACH_SPEED = 520
REVERSE_SPEED = 500
RAM_PREP_SPEED = 420

# This unit's ultrasonic head appears mechanically offset relative to a
# textbook 90-degree servo center. The startup/home angle is shifted so the
# face/display sits closer to the real forward direction on boot.
HEAD_LEFT_ANGLE = 65
HEAD_CENTER_ANGLE = 5
HEAD_RIGHT_ANGLE = -12
HEAD_LEFT_PULSE_OFFSET_US = 0
HEAD_CENTER_PULSE_OFFSET_US = 0
HEAD_RIGHT_PULSE_OFFSET_US = 0
HEAD_MOVE_HOLD_MS = 260
HEAD_RIGHT_MOVE_PULSES = 28

# The official soccer tutorial initializes the claw servo around 180° and
# releases around 160°. These angles are expanded for autonomous behavior and
# will likely need fine tuning on the real robot.
CLAW_CLOSED_ANGLE = 180
CLAW_HOLD_ANGLE = 180
CLAW_OPEN_ANGLE = 160
CLAW_WIDE_OPEN_ANGLE = 160
CLAW_GRAB_PULSE_OFFSET_US = 0
CLAW_RELEASE_PULSE_OFFSET_US = 0
CLAW_GRAB_MOVE_PULSES = 24
CLAW_RELEASE_MOVE_PULSES = 18
CLAW_GRAB_HOLD_MS = 1200
CLAW_RELEASE_HOLD_MS = 220

SCAN_SETTLE_MS = 180
MEASURE_GAP_MS = 40
MANUAL_COMMAND_TIMEOUT_MS = 260
MANUAL_RELEASE_DECEL_MS = 280
APPROACH_TIMEOUT_MS = 4500
SEARCH_SCAN_INTERVAL_MS = 520
EMOTION_FRAME_MS = 180
SONAR_TIMEOUT_US = 30000
SONAR_IDLE_POLL_MS = 260
SONAR_FORWARD_POLL_MS = 95
SONAR_CACHE_MS = 520
SONAR_SAMPLES_IDLE = 1
SONAR_SAMPLES_FORWARD = 2
SONAR_SWEEP_SAMPLES = 1
SONAR_SWEEP_INTERVAL_MS = 95
SONAR_SCAN_SETTLE_MS = 65
SONAR_SCAN_MEMORY_MS = 780
FORWARD_HEAD_SETTLE_MS = 120
FORWARD_HEAD_TOLERANCE_DEG = 4
SONAR_FRONT_CONE_DEG = 10
SONAR_FRONT_MODEL_DEG = 18
SONAR_SIDE_CAUTION_CM = 18
SONAR_SIDE_DANGER_CM = 10
SONAR_TRIM_GAIN = 18
SONAR_TRIM_MAX_PWM = 210

OBSTACLE_STOP_CM = 14
OBSTACLE_ESCAPE_CM = 9
BALL_DETECT_MIN_CM = 4
BALL_DETECT_MAX_CM = 65
BALL_DIAMETER_CM = 3
BALL_WIDTH_TOL_CM = 2
BALL_NEIGHBOR_CONTRAST_CM = 5
BALL_SCORE_MIN = 0.62
BALL_CAPTURE_APPROACH_CM = 4
BALL_CAPTURE_APPROACH_PWM = 180
CAPTURE_DISTANCE_CM = 8
RAM_SAFE_FRONT_CM = 12
FREE_SPACE_GOOD_CM = 22
FORWARD_STOP_CM = 9
FORWARD_CRAWL_CM = 14
FORWARD_SLOWDOWN_CM = 34
FORWARD_MIN_PWM = 220
FORWARD_NEAR_PWM = 340
TURN_TIGHT_CM = 14
TURN_OPEN_CM = 34
TURN_PIVOT_INNER_PWM = 260
TURN_ARC_INNER_MIN = 160
TURN_SAMPLE_AGE_MS = 850
KICK_CHARGE_PWM = 920
KICK_CHARGE_MS = 240
KICK_RELEASE_PWM = 980
KICK_RELEASE_MS = 150
KICK_DECEL_PWM = 360
KICK_DECEL_MS = 220
KICK_SEEK_PWM = 460
KICK_SEEK_MS = 1300
AUTO_CRUISE_PWM = 420

# Adaptive capture profiles:
# (open_angle, approach_pwm, approach_ms, close_angle, settle_ms, reverse_ms)
CAPTURE_PROFILES = (
    (154, 460, 180, 180, 140, 70),
    (150, 520, 230, 180, 180, 90),
    (146, 580, 280, 180, 220, 120),
    (142, 620, 330, 178, 240, 150),
)

# Ram-kick profiles:
# (drop_angle, reverse_ms, ram_pwm, ram_ms, settle_ms)
RAM_KICK_PROFILES = (
    (156, 50, 640, 220, 80),
    (152, 80, 760, 320, 90),
    (146, 110, 900, 440, 110),
)

# Pan/scan profiles for the ultrasonic servo:
# (left_angle, center_angle, right_angle, settle_ms)
SCAN_PROFILES = (
    (70, 5, 0, 180),
    (58, 8, 0, 150),
    (80, 15, 0, 210),
)

POLICY_FILE = "robot_policy.json"
RL_ALPHA = 0.34
RL_EPSILON = 0.16
RL_SAVE_EVERY = 3

# Button mapping:
# Official docs confirm:
# - drive uses /btn/F /btn/B /btn/L /btn/R /btn/S
# - the keypad includes /btn/0 and /btn/1
# - the soccer tutorial uses /btn/p to close the claw and /btn/x to release it
# We also accept a few aliases such as /btn/0# and /btn/1# because some app
# skins label the keypad that way.
BUTTON_FORWARD = "/btn/F"
BUTTON_BACKWARD = "/btn/B"
BUTTON_LEFT = "/btn/L"
BUTTON_RIGHT = "/btn/R"
BUTTON_STOP = "/btn/S"

BUTTON_OK_ALIASES = (
    "/btn/o",
    "/btn/O",
    "/btn/ok",
    "/btn/OK",
)

BUTTON_AUTO_MODE_ALIASES = (
    "/btn/0",
    "/btn/0#",
)

BUTTON_MANUAL_MODE_ALIASES = (
    "/btn/1",
    "/btn/1#",
)

BUTTON_STOP_AUTO_ALIASES = (
    "/btn/j",
)

BUTTON_RAM_KICK_ALIASES = (
    "/btn/rk",
)

BUTTON_PAN_LEFT_ALIASES = (
    "/btn/l",
    "/btn/3",
    "/btn/3#",
)

BUTTON_PAN_CENTER_ALIASES = (
    "/btn/m",
    "/btn/5",
    "/btn/5#",
)

BUTTON_PAN_RIGHT_ALIASES = (
    "/btn/n",
    "/btn/4",
    "/btn/4#",
)

BUTTON_RELEASE_ALIASES = (
    "/btn/q",
    "/btn/x",
)

BUTTON_GRAB_ALIASES = (
    "/btn/p",
)

BUTTON_POLICY_RESET_ALIASES = (
    "/btn/y",
)

BUTTON_FACE_DEMO_ALIASES = (
    "/btn/2",
)

BUTTON_FACE_NEXT_ALIASES = (
    "/btn/i",
)

BUTTON_FACE_CLEAR_ALIASES = (
    "/btn/j",
)

BUTTON_FACE_PREV_ALIASES = (
    "/btn/k",
)
