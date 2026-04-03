# Tutorial 4 AI Transcript

## Prompt
Generate a complete, ready-to-upload MicroPython control program for the Keyestudio KS5002 soccer robot for a smart campus football-training scenario. Use these modules: ultrasonic sensor, dual DC motors, head servo, claw servo, 8x8 LED matrix, RGB LEDs, and Wi-Fi HTTP control. Requirements: read sensor data in real time, trigger actuators on thresholds, display status on the matrix, support manual and auto modes, add simple edge intelligence using moving averages plus adaptive profile selection, keep the code modular, and include detailed comments.

## AI Response
Build the solution in three layers so it stays debuggable on real hardware.

1. Hardware layer: initialize the motors, ultrasonic sensor, head servo, claw servo, RGB LEDs, and the HT16K33 matrix. Add helper functions for filtered distance reads, servo writes, motion, and face updates.

2. Decision layer: create a lightweight `AdaptiveBandit` with `choose()` and `learn()`. Use one bandit for scan profiles, one for capture profiles, and one for ram-kick profiles. Encode nearby distance context in the state key and keep epsilon-greedy exploration enabled.

3. Control layer: expose manual and automatic behaviour. Manual mode should support `/btn/F`, `/btn/B`, `/btn/L`, `/btn/R`, `/btn/S`, `/btn/o`, `/btn/uNNN`, `/btn/vNNN`, `/btn/l`, `/btn/m`, and `/btn/n`. Automatic mode should scan, avoid obstacles, capture the ball, and then perform a release-and-ram kick.

Recommended runtime logic:
- reverse and turn if the front distance is below the obstacle threshold;
- reward capture or ram actions when free space improves after the action;
- persist learned values to `robot_policy.json`;
- use the matrix to show `idle`, `search`, `capture`, `ram`, `celebrate`, and `obstacle`.

Recommended debug improvements:
- tune claw/head servo offsets on the real robot;
- add station Wi-Fi first, with AP fallback;
- expose a `/status` endpoint for remote monitoring.

## Applied Improvements
We applied the AI structure, but improved it after hardware testing. The final project split the policy into `scan`, `capture`, and `ram` agents, persisted the learned table, added a station-first Wi-Fi snapshot plus AP fallback, expanded HTTP button aliases, and tuned the claw/head servo settings to fit the actual KS5002 wiring on our robot.
