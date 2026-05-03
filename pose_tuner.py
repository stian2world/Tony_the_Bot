#!/usr/bin/env python3
"""
pose_tuner.py
Interactive live tuner for Tony's standing pose.

Commands:
  <leg> <joint> <angle>   e.g.  1 coxa 80  or  4 femur 65
  show                    print current angles
  save                    write current angles to standing_pose.py
  reset                   return all to 90
  q                       quit
"""
import json, os, sys, time, re
from adafruit_servokit import ServoKit

MAP_FILE   = os.path.join(os.path.dirname(__file__), "servo_map.json")
POSE_FILE  = os.path.join(os.path.dirname(__file__), "standing_pose.py")
POSES_FILE = os.path.join(os.path.dirname(__file__), "poses.json")
PULSE      = (500, 2500)

with open(MAP_FILE) as f:
    servo_map = json.load(f)

leg_lookup  = {}   # (leg, joint) -> (board_str, channel)
head_lookup = {}   # joint -> (board_str, channel)
for v in servo_map.values():
    if v.get("part") == "head":
        head_lookup[v["joint"]] = (v["board"], v["channel"])
    elif v.get("leg") and v.get("joint"):
        leg_lookup[(v["leg"], v["joint"])] = (v["board"], v["channel"])

_kits = {}
def get_kit(addr_str):
    addr = int(addr_str, 16)
    if addr not in _kits:
        kit = ServoKit(channels=16, address=addr)
        for ch in range(16):
            kit.servo[ch].set_pulse_width_range(*PULSE)
        _kits[addr] = kit
    return _kits[addr]

def set_servo(leg, joint, angle):
    angle = max(0, min(180, angle))
    key = (leg, joint)
    if key not in leg_lookup:
        print(f"  Unknown: Leg {leg} {joint}")
        return
    board, ch = leg_lookup[key]
    get_kit(board).servo[ch].angle = angle

# Load starting pose — default tony_flat, or pass pose name as argument
with open(POSES_FILE) as f:
    _poses = json.load(f)

_start_pose_name = sys.argv[1] if len(sys.argv) > 1 else "tony_flat"
if _start_pose_name not in _poses:
    print(f"Unknown pose '{_start_pose_name}'. Available: {', '.join(_poses.keys())}")
    sys.exit(1)
_start = _poses[_start_pose_name].get("legs", {})
_flat  = _poses.get("tony_flat", {}).get("legs", {})

angles = {
    leg: {
        "coxa":  _start.get(str(leg), {}).get("coxa",  90),
        "femur": _start.get(str(leg), {}).get("femur", 90),
        "tibia": _start.get(str(leg), {}).get("tibia", 90),
    }
    for leg in range(1, 7)
}

print(f"Moving to {_start_pose_name}...")
for (leg, joint), (board, ch) in leg_lookup.items():
    get_kit(board).servo[ch].angle = angles[leg][joint]
time.sleep(0.5)

def show():
    print("\n  Leg  Coxa  Femur  Tibia")
    print("  " + "-" * 26)
    for leg in range(1, 7):
        a = angles[leg]
        side = "R" if leg in (1,3,5) else "L"
        print(f"  {leg}{side}   {a['coxa']:3}   {a['femur']:3}    {a['tibia']:3}")
    print()

def save(name=None):
    if not name:
        name = input("  Pose name: ").strip()
    if not name:
        print("  Cancelled.")
        return
    with open(POSES_FILE) as f:
        poses = json.load(f)
    poses[name] = {
        "description": f"{name} pose",
        "legs": {
            str(leg): {"coxa": angles[leg]["coxa"], "femur": angles[leg]["femur"], "tibia": angles[leg]["tibia"]}
            for leg in range(1, 7)
        }
    }
    with open(POSES_FILE, "w") as f:
        json.dump(poses, f, indent=2)
    print(f"  Saved '{name}' to {POSES_FILE}")

print("\nTony Pose Tuner — type commands to adjust live")
print("  Single:  1 femur 80")
print("  Group:   r femur 60   (right legs 1/3/5)")
print("           l femur 120  (left legs 2/4/6)")
print("           all femur 90 (all legs)")
print("  Other:   show | reset | save | save <name> | q")
show()

JOINTS  = {"coxa", "femur", "tibia"}
R_LEGS  = [2, 4, 6]
L_LEGS  = [1, 3, 5]

def apply_to_legs(leg_list, joint, angle):
    for leg in leg_list:
        angles[leg][joint] = max(0, min(180, angle))
        set_servo(leg, joint, angles[leg][joint])
    print(f"  Legs {leg_list} {joint} → {max(0, min(180, angle))}°")

while True:
    try:
        cmd = input("> ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        break

    if not cmd:
        continue
    if cmd == "q":
        break
    if cmd == "show":
        show(); continue
    if cmd == "reset":
        for leg in range(1, 7):
            for j in ["coxa","femur","tibia"]:
                angles[leg][j] = _flat.get(str(leg), {}).get(j, 90)
                set_servo(leg, j, angles[leg][j])
        print("  Reset to tony_flat")
        continue
    if cmd == "save" or cmd.startswith("save "):
        parts_save = cmd.split(None, 1)
        save(parts_save[1] if len(parts_save) > 1 else None); continue

    parts = cmd.split()
    if len(parts) == 3:
        try:
            target = parts[0]
            joint  = parts[1]
            angle  = int(parts[2])
            if joint not in JOINTS:
                print("  Joint must be coxa / femur / tibia"); continue
            if target == "r":
                apply_to_legs(R_LEGS, joint, angle); continue
            elif target == "l":
                apply_to_legs(L_LEGS, joint, angle); continue
            elif target == "all":
                apply_to_legs(R_LEGS + L_LEGS, joint, angle); continue
            leg = int(target)
            if leg not in range(1, 7):
                print("  Leg must be 1-6"); continue
            angles[leg][joint] = max(0, min(180, angle))
            set_servo(leg, joint, angles[leg][joint])
            print(f"  Leg {leg} {joint} → {angles[leg][joint]}°")
        except ValueError:
            print("  Usage: <leg 1-6> <coxa|femur|tibia> <angle 10-170>")
    else:
        print("  Usage: <leg> <joint> <angle>  e.g.  2 femur 65")
