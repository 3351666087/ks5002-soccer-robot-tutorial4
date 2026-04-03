# KS5002 Soccer Robot for MicroPython

This project is a MicroPython rewrite for the Keyestudio KS5002 soccer robot.

## What changed

- The robot now kicks by releasing the ball and using the car body to ram it.
- The front 8x8 LED matrix shows richer animated expressions.
- The autonomous logic includes a tiny on-device adaptive policy that keeps
  tuning capture and ram-kick profiles based on inferred success.
- The ultrasonic pan servo is now a first-class control target:
  manual mode can steer it directly, and auto mode uses an adaptive scan policy
  to choose how the ultrasonic board sweeps.
- The phone app protocol is now aligned much more closely with the official
  HTTP demo: `/btn/uNNN` and `/btn/vNNN` update the left/right motor sliders,
  `/btn/o` acts as OK, `/btn/0` and `/btn/1` switch modes, and `/btn/l/m/n`
  can steer the ultrasonic pan servo.
- A desktop-safe compatibility layer is included so local Python imports do not
  fail when you inspect or lint the project on macOS.
- Host-side scripts can auto deploy, self-test, and record theory-vs-observed
  results.
- A Chinese PySide6 desktop studio is included for flashing, parameter editing,
  Wi-Fi setup, and ESP32 auto detection.

## Hardware mapping

These pins are taken from the official KS5002 documentation:

- Left motor direction: GPIO33
- Left motor PWM: GPIO26
- Right motor direction: GPIO32
- Right motor PWM: GPIO25
- Head servo / ultrasonic pan servo: GPIO4
- Claw servo: GPIO13 on this unit's current rewired harness
- Ultrasonic trig: GPIO5
- Ultrasonic echo: GPIO18
- RGB LEDs: GPIO14
- Dot matrix SDA: GPIO21
- Dot matrix SCL: GPIO22

## App button mapping

- `/btn/F`: forward in manual mode
- `/btn/B`: backward in manual mode
- `/btn/L`: rotate left in manual mode
- `/btn/R`: rotate right in manual mode
- `/btn/S`: stop in manual mode; pause in auto mode
- `/btn/uNNN`: set left wheel slider speed, official app ML slider
- `/btn/vNNN`: set right wheel slider speed, official app MR slider
- `/btn/l` or `/btn/3`: ultrasonic pan servo left in manual mode
- `/btn/m` or `/btn/5`: ultrasonic pan servo center in manual mode
- `/btn/n` or `/btn/4`: ultrasonic pan servo right in manual mode
- `OK` uses `/btn/o`
- Manual mode:
  first `OK` closes the claw to grab the ball, next `OK` releases it
- Auto mode:
  first `OK` resumes from pause, next `OK` pauses again
- `/btn/p`: direct grab
- `/btn/q` or `/btn/x`: direct release
- `/btn/0`: switch to auto mode, default paused
- `/btn/1`: switch to manual mode
- `/btn/2`: play the built-in face demo
- `/btn/j`: clear expression matrix
- `/btn/i`: next expression
- `/btn/k`: previous expression
- `/btn/y`: reset the learned policy
- `/btn/rk`: desktop-side custom single ram-kick path

## Adaptive policy

This project does not use a heavyweight neural model. Instead it runs a tiny
contextual bandit on the ESP32 itself:

- `scan_agent` learns which ultrasonic pan scan profile works best for the
  current space and recent success streak.
- `capture_agent` learns which claw-and-approach profile works best for the
  current distance/obstacle context.
- `ram_agent` learns which release-and-ram profile most reliably drives the
  ball away after release.
- Learned values are persisted in `robot_policy.json` on the device.

That keeps the code realistic for an ESP-WROOM-32 while still giving you an
online adaptive "micro RL" loop.

## Deploy

Activate the local environment first:

```bash
source .venv/bin/activate
```

## Desktop studio

Launch the Chinese GUI:

```bash
python studio.py
```

If you want macOS native permission prompts for Wi-Fi/location, build and use the real `.app` instead of running the raw Python script:

```bash
python tools/build_macos_app.py
open dist/KS5002Studio.app
```

Features:

- Auto-detect ESP32 serial connection and show a status light
- Auto-locate a local ESP32 MicroPython `bin`, and if missing, download the latest official `ESP32_GENERIC` firmware automatically
- Edit the current Wi-Fi password, manual parameters, auto parameters, servo angles, and RL values
- Auto-detect the current Mac Wi-Fi IP and try to infer the SSID in the background; if macOS blocks it, the GUI will clearly prompt for manual password-only fallback
- The packaged `.app` includes native macOS permission descriptions and buttons to request system location permission, open Privacy settings, and try keychain-backed Wi-Fi password retrieval
- Station-first networking on the robot: it will prefer joining the LAN, and only open a fallback AP when LAN credentials are unavailable
- Built-in glass-style manual console that is closer to the official App layout, with a direction pad, ML/MR sliders, right-side function keys, number shortcuts, and responsive fullscreen/window scaling
- Real-time WLAN health indicator for the robot: the desktop GUI polls `/status` and shows whether the robot HTTP port is open after you unplug the USB cable
- Built-in ML/MR sliders that send `/btn/uNNN` and `/btn/vNNN`
- Save, load, and delete named parameter presets
- Flash either the main program or the self-test boot logic
- Run a quick self-check without changing the boot entry
- Save the last desktop-side parameter profile locally

Then deploy the project:

```bash
python tools/deploy_main.py
```

If you also want to flash a new MicroPython firmware first:

```bash
python tools/deploy_main.py --firmware /path/to/esp32-firmware.bin
```

## Auto flash + self test

This uploads the project, runs self-check and action tests, asks you for the
actual observed behavior, and saves a JSON report.

```bash
python tools/flash_and_test.py
```

The script will explicitly ask you to lift the robot before any motor or
ram-kick test.

## Important calibration points

You will almost certainly need to tune these on real hardware:

- `CLAW_CLOSED_ANGLE`
- `CLAW_OPEN_ANGLE`
- `CLAW_WIDE_OPEN_ANGLE`
- `CAPTURE_PROFILES`
- `RAM_KICK_PROFILES`

The adaptive policy helps, but it still needs a sane starting range.
