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

MAP_FILE   = os.path.join(os.path.dirname(__file__), "servo_map.json")
POSES_FILE = os.path.join(os.path.dirname(__file__), "poses.json")
PULSE      = (500, 2500)
SPEED      = 0.012  # seconds per degree step

with open(POSES_FILE) as _f:
    _poses = json.load(_f)
_flat_legs = _poses.get("tony_flat", {}).get("legs", {})
POSE = {leg: {j: _flat_legs.get(str(leg), {}).get(j, 90) for j in ("coxa","femur","tibia")} for leg in range(1,7)}

HEAD = {"tilt": 90, "pan": 90}


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

    print("\nMoving to tony_flat pose...")

    for j in ["coxa", "femur", "tibia"]:
        for leg in range(1, 7):
            if (leg, j) not in leg_map:
                continue
            board, ch = leg_map[(leg, j)]
            target = POSE[leg][j]
            get_kit(board).servo[ch].angle = target

    # Center head
    for joint, (board, ch) in head_map.items():
        target = HEAD.get(joint, 90)
        get_kit(board).servo[ch].angle = target

    print("\nTony is in tony_flat pose.")
    print("Run pose_tuner.py to tune from here.")
    print("\nLeg layout:")
    print("     FRONT")
    print("  1       2")
    print("  3       4")
    print("  5       6")
    print("     BACK")


if __name__ == "__main__":
    stand()
