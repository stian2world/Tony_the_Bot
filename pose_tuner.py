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
import json, os, time, re
from adafruit_servokit import ServoKit

MAP_FILE  = os.path.join(os.path.dirname(__file__), "servo_map.json")
POSE_FILE = os.path.join(os.path.dirname(__file__), "standing_pose.py")
PULSE     = (500, 2500)

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
    angle = max(10, min(170, angle))
    key = (leg, joint)
    if key not in leg_lookup:
        print(f"  Unknown: Leg {leg} {joint}")
        return
    board, ch = leg_lookup[key]
    get_kit(board).servo[ch].angle = angle

# Current pose state
angles = {
    leg: {"coxa": 90, "femur": 90, "tibia": 90}
    for leg in range(1, 7)
}

# Apply initial 90 to all
print("Centering all joints to 90°...")
for (leg, joint), (board, ch) in leg_lookup.items():
    get_kit(board).servo[ch].angle = 90
time.sleep(0.5)

def show():
    print("\n  Leg  Coxa  Femur  Tibia")
    print("  " + "-" * 26)
    for leg in range(1, 7):
        a = angles[leg]
        side = "R" if leg in (1,3,5) else "L"
        print(f"  {leg}{side}   {a['coxa']:3}   {a['femur']:3}    {a['tibia']:3}")
    print()

def save():
    with open(POSE_FILE) as f:
        src = f.read()
    lines = []
    for leg in range(1, 7):
        a = angles[leg]
        lines.append(
            f'    {leg}: {{"coxa": {a["coxa"]}, "femur": {a["femur"]}, "tibia": {a["tibia"]}}},'
        )
    new_pose = "\n".join(lines)
    import re
    src = re.sub(
        r'(POSE = \{.*?# leg.*?\n)(.*?)(\})',
        lambda m: m.group(1) + new_pose + "\n" + m.group(3),
        src, flags=re.DOTALL
    )
    with open(POSE_FILE, "w") as f:
        f.write(src)
    print(f"  Saved to {POSE_FILE}")

print("\nTony Pose Tuner — type commands to adjust live")
print("  e.g.  1 coxa 80   |   3 femur 65   |   show   |   save   |   q")
show()

JOINTS = {"coxa", "femur", "tibia"}

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
                angles[leg][j] = 90
                set_servo(leg, j, 90)
        print("  All reset to 90°")
        continue
    if cmd == "save":
        save(); continue

    parts = cmd.split()
    if len(parts) == 3:
        try:
            leg   = int(parts[0])
            joint = parts[1]
            angle = int(parts[2])
            if leg not in range(1, 7):
                print("  Leg must be 1-6"); continue
            if joint not in JOINTS:
                print("  Joint must be coxa / femur / tibia"); continue
            angles[leg][joint] = max(10, min(170, angle))
            set_servo(leg, joint, angles[leg][joint])
            print(f"  Leg {leg} {joint} → {angles[leg][joint]}°")
        except ValueError:
            print("  Usage: <leg 1-6> <coxa|femur|tibia> <angle 10-170>")
    else:
        print("  Usage: <leg> <joint> <angle>  e.g.  2 femur 65")
