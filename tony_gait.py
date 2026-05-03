#!/usr/bin/env python3
"""
tony_gait.py
Tripod gait for Tony starting from tony_stand pose.

Tripod A: legs 2, 3, 6
Tripod B: legs 1, 4, 5

Usage:
  python3 tony_gait.py           # walk forward
  python3 tony_gait.py back      # walk backward
  Ctrl+C to stop and return to stand
"""
import json, os, sys, time
from adafruit_servokit import ServoKit

MAP_FILE   = os.path.join(os.path.dirname(__file__), "servo_map.json")
POSES_FILE = os.path.join(os.path.dirname(__file__), "poses.json")
PULSE      = (500, 2500)

# ── TUNE THESE ─────────────────────────────────────────────────────
STEP_ANGLE = 20    # degrees coxa swings per step
LIFT_DELTA = 25    # degrees femur changes to lift foot off ground
PAUSE      = 0.15  # seconds between phases — lower = faster
# ───────────────────────────────────────────────────────────────────

TRIPOD_A = [2, 3, 6]
TRIPOD_B = [1, 4, 5]

# +1 = increasing coxa angle swings leg forward, -1 = decreasing swings forward
# Flip any leg's value if it steps backward instead of forward
COXA_DIR = {1: -1, 2: +1, 3: -1, 4: +1, 5: -1, 6: +1}

LOW_SIDE = {1, 3, 5}  # these legs stand with LOW femur

# ── Load config ─────────────────────────────────────────────────────
with open(MAP_FILE) as f:
    servo_map = json.load(f)
with open(POSES_FILE) as f:
    poses = json.load(f)

leg_lookup = {}
for v in servo_map.values():
    if v.get("part") == "head":
        continue
    leg = v["leg"]
    if leg not in leg_lookup:
        leg_lookup[leg] = {}
    leg_lookup[leg][v["joint"]] = (v["board"], v["channel"])

_kits = {}
def get_kit(addr_str):
    addr = int(addr_str, 16)
    if addr not in _kits:
        kit = ServoKit(channels=16, address=addr)
        for ch in range(16):
            kit.servo[ch].set_pulse_width_range(*PULSE)
        _kits[addr] = kit
    return _kits[addr]

def set_angle(leg, joint, angle):
    angle = max(0, min(180, int(angle)))
    board, ch = leg_lookup[leg][joint]
    get_kit(board).servo[ch].angle = angle

# ── Pre-compute fixed positions ─────────────────────────────────────
stand = poses["tony_stand"]["legs"]

# Coxa positions — oscillate between BACK and FORWARD, never accumulate
COXA_NEUTRAL  = {leg: stand[str(leg)]["coxa"] for leg in range(1, 7)}
COXA_FORWARD  = {leg: max(0, min(180, COXA_NEUTRAL[leg] + STEP_ANGLE * COXA_DIR[leg])) for leg in range(1, 7)}
COXA_BACKWARD = {leg: max(0, min(180, COXA_NEUTRAL[leg] - STEP_ANGLE * COXA_DIR[leg])) for leg in range(1, 7)}

# Femur positions — stand height vs lifted
FEMUR_STAND = {leg: stand[str(leg)]["femur"] for leg in range(1, 7)}
FEMUR_LIFT  = {
    leg: max(0, min(180, FEMUR_STAND[leg] + (LIFT_DELTA if leg in LOW_SIDE else -LIFT_DELTA)))
    for leg in range(1, 7)
}

TIBIA_STAND = {leg: stand[str(leg)]["tibia"] for leg in range(1, 7)}

def set_group(group, coxa=None, femur=None):
    for leg in group:
        if coxa is not None:
            set_angle(leg, "coxa", coxa[leg])
        if femur is not None:
            set_angle(leg, "femur", femur[leg])

def goto_stand():
    for leg in range(1, 7):
        set_angle(leg, "coxa",  COXA_NEUTRAL[leg])
        set_angle(leg, "femur", FEMUR_STAND[leg])
        set_angle(leg, "tibia", TIBIA_STAND[leg])
    time.sleep(0.5)

# ── Gait cycle ──────────────────────────────────────────────────────
# Each cycle: A steps forward while B pushes, then B steps forward while A pushes
# Coxas go BACKWARD → body moves forward relative to feet

def gait_cycle(direction):
    fwd = COXA_FORWARD  if direction == 1 else COXA_BACKWARD
    bwd = COXA_BACKWARD if direction == 1 else COXA_FORWARD

    # Phase 1 — Lift A
    set_group(TRIPOD_A, femur=FEMUR_LIFT)
    time.sleep(PAUSE)

    # Phase 2 — Swing A forward, push B backward
    set_group(TRIPOD_A, coxa=fwd)
    set_group(TRIPOD_B, coxa=bwd)
    time.sleep(PAUSE)

    # Phase 3 — Plant A
    set_group(TRIPOD_A, femur=FEMUR_STAND)
    time.sleep(PAUSE)

    # Phase 4 — Lift B
    set_group(TRIPOD_B, femur=FEMUR_LIFT)
    time.sleep(PAUSE)

    # Phase 5 — Swing B forward, push A backward
    set_group(TRIPOD_B, coxa=fwd)
    set_group(TRIPOD_A, coxa=bwd)
    time.sleep(PAUSE)

    # Phase 6 — Plant B
    set_group(TRIPOD_B, femur=FEMUR_STAND)
    time.sleep(PAUSE)

# ── Main ─────────────────────────────────────────────────────────────
direction = -1 if "back" in sys.argv else 1

print("Tony Tripod Gait — Ctrl+C to stop")
print(f"  STEP_ANGLE={STEP_ANGLE}  LIFT_DELTA={LIFT_DELTA}  PAUSE={PAUSE}s")
print("Going to standing pose...")
goto_stand()
time.sleep(1.0)
print("Walking...")

try:
    while True:
        gait_cycle(direction)
except KeyboardInterrupt:
    print("\nStopping — returning to stand...")
    goto_stand()
    print("Done.")
