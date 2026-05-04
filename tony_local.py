#!/usr/bin/env python3
"""
tony_local.py
Local classroom listener for Tony.

- Captures audio from USB mic (Adafruit Mini USB Mic, card 2) via arecord
- Transcribes with Whisper
- Detects "I have a question" → records until "thank you"
- Moves Tony's head to look at the person speaking (via YOLO detections)
- Posts question + Groq answer to Discord #tonys-chat-room

Run:
  python3 tony_local.py
"""
import json, os, sys, time, threading, subprocess
import numpy as np
import whisper
import requests
from scipy.signal import resample_poly
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "discord_bot", ".env"))

# ── Config ──────────────────────────────────────────────────────────
ALSA_DEVICE     = "hw:2,0"   # Adafruit Mini USB Mic on card 2
CAPTURE_RATE    = 44100      # native rate supported by the mic
WHISPER_RATE    = 16000      # Whisper expects 16 kHz
CHANNELS        = 1
CHUNK_SECONDS   = 3          # seconds per transcription chunk

WAKE_WORD       = "tony"
STOP_PHRASE     = "thank you"

STATE_FILE      = "/tmp/tony_state.json"   # written by tony_brain.py
FRAME_W, FRAME_H = 640, 480               # YOLO inference resolution

# Head servo neutral angles (from servo_map.json)
PAN_NEUTRAL     = 90    # 0x41 ch1
TILT_NEUTRAL    = 90    # 0x41 ch0
PAN_RANGE       = 45    # ± degrees from neutral
TILT_RANGE      = 30    # ± degrees from neutral

DISCORD_TOKEN      = os.getenv("DISCORD_TOKEN", "")
QUESTIONS_CHANNEL  = int(os.getenv("QUESTIONS_CHANNEL_ID", "1470571362287358090"))
GROQ_API_KEY       = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL         = os.getenv("GROQ_MODEL", "llama3-8b-8192")

DISCORD_API        = "https://discord.com/api/v10"
HEADERS            = {"Authorization": f"Bot {DISCORD_TOKEN}", "Content-Type": "application/json"}

# ── Servo setup ──────────────────────────────────────────────────────
from adafruit_servokit import ServoKit
_kit41 = ServoKit(channels=16, address=0x41)
for ch in range(16):
    _kit41.servo[ch].set_pulse_width_range(500, 2500)

def set_head(pan: int, tilt: int):
    pan  = max(0, min(180, pan))
    tilt = max(0, min(180, tilt))
    _kit41.servo[1].angle = pan
    _kit41.servo[0].angle = tilt

def head_neutral():
    set_head(PAN_NEUTRAL, TILT_NEUTRAL)

# ── Head tracker ─────────────────────────────────────────────────────
_tracking        = False
_tracker_thread  = None

def _tracker_loop():
    while _tracking:
        try:
            with open(STATE_FILE) as f:
                state = json.load(f)
            persons = [d for d in state.get("current_detections", []) if d["label"] == "person"]
            if persons:
                p = max(persons, key=lambda d: d["w"] * d["h"])
                pan  = int(PAN_NEUTRAL  + (p["cx"] - FRAME_W / 2) / (FRAME_W / 2) * PAN_RANGE)
                tilt = int(TILT_NEUTRAL - (p["cy"] - FRAME_H / 2) / (FRAME_H / 2) * TILT_RANGE)
                set_head(pan, tilt)
        except Exception:
            pass
        time.sleep(0.2)

def start_tracking():
    global _tracking, _tracker_thread
    _tracking = True
    _tracker_thread = threading.Thread(target=_tracker_loop, daemon=True)
    _tracker_thread.start()

def stop_tracking():
    global _tracking
    _tracking = False
    head_neutral()

# ── Whisper ──────────────────────────────────────────────────────────
print("[Tony] Loading Whisper model…")
_whisper = whisper.load_model("base")
print("[Tony] Whisper ready.")

def transcribe(pcm: np.ndarray) -> str:
    audio = pcm.astype(np.float32) / 32768.0
    # Resample from 44100 Hz (mic native) down to 16000 Hz (Whisper expects)
    audio = resample_poly(audio, 160, 441).astype(np.float32)
    result = _whisper.transcribe(audio, language="en", fp16=False)
    return result["text"].strip().lower()

# ── Discord helpers ──────────────────────────────────────────────────
def discord_post(text: str):
    requests.post(
        f"{DISCORD_API}/channels/{QUESTIONS_CHANNEL}/messages",
        headers=HEADERS,
        json={"content": text},
        timeout=10,
    )

# ── Groq helper ──────────────────────────────────────────────────────
from groq import Groq
_groq = Groq(api_key=GROQ_API_KEY)

SYSTEM_PROMPT = (
    "You are Tony, a classroom support robot. "
    "Answer clearly and concisely, always staying in character."
)

def ask_groq(question: str) -> str:
    resp = _groq.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": question},
        ],
        max_tokens=400,
        temperature=0.7,
    )
    return resp.choices[0].message.content.strip()

# ── Main listener loop ───────────────────────────────────────────────
BYTES_PER_SAMPLE = 2  # int16
CHUNK_BYTES = CAPTURE_RATE * CHANNELS * BYTES_PER_SAMPLE * CHUNK_SECONDS

def main():
    print(f"[Tony] Opening mic {ALSA_DEVICE} at {CAPTURE_RATE} Hz…")
    head_neutral()

    # arecord streams raw S16_LE PCM to stdout; we read fixed-size chunks
    proc = subprocess.Popen(
        [
            "arecord",
            "-D", ALSA_DEVICE,
            "-f", "S16_LE",
            "-r", str(CAPTURE_RATE),
            "-c", str(CHANNELS),
            "-q",          # suppress progress messages
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    print("[Tony] Listening for 'I have a question'…")

    state       = "idle"
    question    = ""
    prev_text   = ""   # previous chunk — lets trigger phrase span a chunk boundary

    try:
        while True:
            raw = proc.stdout.read(CHUNK_BYTES)
            if len(raw) < CHUNK_BYTES // 2:
                continue

            chunk = np.frombuffer(raw, dtype=np.int16)
            text  = transcribe(chunk)
            if not text:
                prev_text = ""
                continue

            print(f"[mic] {text}")

            # Combined window: tail of previous chunk + current chunk
            window = (prev_text + " " + text).strip()

            if state == "idle":
                # Trigger: hear "tony" and "question" anywhere in the rolling window
                if WAKE_WORD in window and "question" in window:
                    state = "recording"
                    # Grab anything after "question" as the start of the question
                    after = window.split("question", 1)[-1].strip(" .,!?")
                    question = after
                    prev_text = ""
                    print("[Tony] Question started — tracking speaker…")
                    start_tracking()
                    discord_post("🎙️ **Student is asking a question…**")

            elif state == "recording":
                clean = text.strip(" .,!?")
                if STOP_PHRASE in clean:
                    question += " " + clean.split(STOP_PHRASE)[0].strip(" .,!?")
                    question = question.strip()
                    state = "idle"
                    prev_text = ""
                    stop_tracking()

                    if question:
                        print(f"[Tony] Question: {question}")
                        discord_post(f"❓ **Student asked:**\n> {question}")
                        answer = ask_groq(question)
                        print(f"[Tony] Answer: {answer}")
                        discord_post(f"💡 **Tony:**\n{answer}")
                    question = ""
                else:
                    question += " " + clean

            prev_text = text
    finally:
        proc.terminate()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        stop_tracking()
        print("\n[Tony] Stopped.")
