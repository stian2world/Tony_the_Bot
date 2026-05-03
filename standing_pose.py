#!/usr/bin/env python3
"""
standing_pose.py
Moves Tony to a standing pose using servo_map.json.

Tune the POSE angles below until Tony stands upright with all
6 legs planted flat on the ground.

Joint directions (observe and adjust):
  coxa  — rotates leg forward/backward (90 = neutral outward)
  femur — raises/lowers the leg      (increase = up or down depending on mounting)
  tibia — extends/curls the foot     (increase = extend or curl depending on mounting)

Run:
  python3 standing_pose.py
"""
import time
import json
import os
from adafruit_servokit import ServoKit

MAP_FILE = os.path.join(os.path.dirname(__file__), "servo_map.json")
PULSE    = (500, 2500)
SPEED    = 0.012  # seconds per degree step

# ── TUNE THESE ANGLES ──────────────────────────────────────────────
# Right side legs (1, 3, 5) — board 0x40
# Left side legs  (2, 4, 6) — board 0x41
# Start at 90 for all, then adjust femur/tibia until Tony stands level.

POSE = {
    # leg: { joint: angle }
    # Right side (1, 3, 5) — board 0x40
    1: {"coxa": 90, "femur": 105, "tibia": 55},
    3: {"coxa": 90, "femur": 105, "tibia": 55},
    5: {"coxa": 90, "femur": 105, "tibia": 55},
    # Left side (2, 4, 6) — board 0x41 (mirrored mounting)
    2: {"coxa": 90, "femur": 60, "tibia": 145},
    4: {"coxa": 90, "femur": 75, "tibia": 130},
    6: {"coxa": 90, "femur": 75, "tibia": 130},
}

HEAD = {"tilt": 90, "pan": 90}
# ───────────────────────────────────────────────────────────────────


_kits = {}

def get_kit(addr_str):
    addr = int(addr_str, 16)
    if addr not in _kits:
        kit = ServoKit(channels=16, address=addr)
        for ch in range(16):
            kit.servo[ch].set_pulse_width_range(*PULSE)
        _kits[addr] = kit
    return _kits[addr]


def smooth_move(kit, ch, start, end, speed=SPEED):
    step = 1 if end >= start else -1
    for a in range(int(start), int(end) + step, step):
        kit.servo[ch].angle = a
        time.sleep(speed)


def stand():
    if not os.path.exists(MAP_FILE):
        print("No servo_map.json — run leg_identify.py first.")
        return

    with open(MAP_FILE) as f:
        servo_map = json.load(f)

    # Build lookup: (leg, joint) -> (board, channel)
    # Also collect head channels
    leg_map  = {}
    head_map = {}
    for v in servo_map.values():
        if v.get("part") == "head":
            head_map[v["joint"]] = (v["board"], v["channel"])
        elif v.get("leg") and v.get("joint"):
            leg_map[(v["leg"], v["joint"])] = (v["board"], v["channel"])

    print("\n" + "=" * 50)
    print("  TONY STANDING POSE")
    print("=" * 50)

    # Move all to current position (90°) first to avoid jerks
    print("\nCentering all joints...")
    for (leg, joint), (board, ch) in leg_map.items():
        get_kit(board).servo[ch].angle = 90
    for joint, (board, ch) in head_map.items():
        get_kit(board).servo[ch].angle = 90
    time.sleep(1.0)

    # Move to standing pose
    print("Moving to standing pose...")

    # Move femurs first (lift body), then tibias (plant feet), then coxas
    for j in ["femur", "tibia", "coxa"]:
        for leg in range(1, 7):
            if (leg, j) not in leg_map:
                continue
            board, ch = leg_map[(leg, j)]
            target = POSE[leg][j]
            kit = get_kit(board)
            smooth_move(kit, ch, 90, target)

    # Center head
    for joint, (board, ch) in head_map.items():
        target = HEAD.get(joint, 90)
        get_kit(board).servo[ch].angle = target

    print("\nTony is in standing pose.")
    print("Observe the stance and tune POSE angles in this file if needed.")
    print("\nLeg layout:")
    print("     FRONT")
    print("  1       2")
    print("  3       4")
    print("  5       6")
    print("     BACK")


if __name__ == "__main__":
    stand()
