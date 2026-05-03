from picamera2 import Picamera2
from ultralytics import YOLO
import libcamera
import cv2
import threading
import time
import json
import os
import signal
import atexit
import struct
from multiprocessing.shared_memory import SharedMemory
from collections import deque
from datetime import datetime
import board
import neopixel
from led_battery import update_leds, read_battery_pct, LED_PIN, LED_COUNT, BRIGHTNESS

# Shared memory layout: [size:4][seq:4][jpeg:N]
SHM_NAME   = "tony_frame"
SHM_SIZE   = 8 + 2 * 1024 * 1024   # 8-byte header + 2MB max JPEG

STATE_FILE = "/tmp/tony_state.json"
PID_FILE   = "/tmp/tony_brain.pid"

# ── PID lock ──────────────────────────────────────────────────────────────────
def _enforce_single_instance():
    if os.path.exists(PID_FILE):
        try:
            old = int(open(PID_FILE).read().strip())
            os.kill(old, signal.SIGKILL)
            time.sleep(1)
            print(f"Killed previous brain instance (PID {old})")
        except (ProcessLookupError, ValueError):
            pass
    open(PID_FILE, "w").write(str(os.getpid()))

_enforce_single_instance()

# ── Shared memory ─────────────────────────────────────────────────────────────
try:
    _shm = SharedMemory(name=SHM_NAME, create=True, size=SHM_SIZE)
except FileExistsError:
    _shm = SharedMemory(name=SHM_NAME, create=False)
    _shm.unlink()
    _shm = SharedMemory(name=SHM_NAME, create=True, size=SHM_SIZE)

_shm_buf   = _shm.buf
_frame_seq = 0

def _cleanup():
    try: os.remove(PID_FILE)
    except FileNotFoundError: pass
    try: _shm.close(); _shm.unlink()
    except: pass

atexit.register(_cleanup)

def write_frame(jpeg_bytes):
    global _frame_seq
    n = len(jpeg_bytes)
    if n + 8 > SHM_SIZE:
        return
    struct.pack_into("<II", _shm_buf, 0, n, _frame_seq)
    _shm_buf[8:8 + n] = jpeg_bytes
    _frame_seq += 1

# ── State ─────────────────────────────────────────────────────────────────────
cam = None
model = None
cam_lock = threading.Lock()

raw_frame      = None
raw_frame_lock = threading.Lock()

last_boxes = []
boxes_lock = threading.Lock()

fps_camera = 0.0
fps_yolo   = 0.0
fps_encode = 0.0

latest_detections = []
detections_lock   = threading.Lock()
_det_seq          = 0


def write_state(detections):
    data = {
        "det_seq":            _det_seq,
        "det_timestamp":      datetime.now().strftime("%H:%M:%S"),
        "current_detections": detections,
        "fps_camera":         fps_camera,
        "fps_yolo":           fps_yolo,
        "fps_encode":         fps_encode,
    }
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f)
    os.replace(tmp, STATE_FILE)


def start_camera():
    global cam
    cam = Picamera2()
    config = cam.create_video_configuration(
        main={"size": (1920, 1080), "format": "RGB888"},
        controls={
            "FrameRate": 30,
            "AwbEnable": True,
            "AwbMode": libcamera.controls.AwbModeEnum.Indoor,
            "AeEnable": True,
            "AeMeteringMode": libcamera.controls.AeMeteringModeEnum.Matrix,
            "AeExposureMode": libcamera.controls.AeExposureModeEnum.Normal,
            "Sharpness": 1.0,
            "Contrast": 1.0,
            "Saturation": 1.0,
            "Brightness": 0.0,
            "NoiseReductionMode": libcamera.controls.draft.NoiseReductionModeEnum.Fast,
        },
        buffer_count=4,
    )
    cam.configure(config)
    cam.start()
    time.sleep(4)
    print("Camera started")


def load_model():
    global model
    # NCNN runs 5–6× faster than PyTorch on Pi's ARM CPU — use it if available.
    # Generate it once with: python3 -c "from ultralytics import YOLO; YOLO('yolov8n.pt').export(format='ncnn')"
    ncnn_path = os.path.join(os.path.dirname(__file__), "yolov8n_ncnn_model")
    if os.path.isdir(ncnn_path):
        model = YOLO(ncnn_path)
        print("YOLOv8n loaded (NCNN — ARM optimised)")
    else:
        model = YOLO("yolov8n.pt")
        model.fuse()
        print("YOLOv8n loaded (PyTorch — run export to switch to NCNN)")


def draw_boxes(frame, boxes):
    for (x1, y1, x2, y2, label) in boxes:
        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)
        cv2.rectangle(frame, (x1, y1 - th - 6), (x1 + tw + 4, y1), (0, 255, 0), -1)
        cv2.putText(frame, label, (x1 + 2, y1 - 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 1, cv2.LINE_AA)
    return frame


def camera_loop():
    global raw_frame, fps_camera
    count, t0 = 0, time.time()
    while True:
        try:
            with cam_lock:
                frame = cam.capture_array()
            with raw_frame_lock:
                raw_frame = frame
            count += 1
            elapsed = time.time() - t0
            if elapsed >= 2.0:
                fps_camera = round(count / elapsed, 1)
                count, t0 = 0, time.time()
        except Exception as e:
            print(f"[camera_loop] {e}", flush=True)
            time.sleep(0.1)


def detection_loop():
    global latest_detections, fps_yolo, _det_seq
    last_labels = set()
    count, t0 = 0, time.time()
    # Cap at 5 FPS — Pi CPU takes ~500 ms per inference at imgsz=320.
    # Without this, the loop queues 28 stale frames/sec and pegs all cores.
    INFERENCE_INTERVAL = 1.0 / 5
    next_inference_at  = time.time()
    while True:
        try:
            now = time.time()
            if now < next_inference_at:
                time.sleep(0.02)
                continue
            with raw_frame_lock:
                frame = raw_frame
            if frame is None:
                next_inference_at = time.time() + INFERENCE_INTERVAL
                continue
            next_inference_at = time.time() + INFERENCE_INTERVAL
            # Pre-resize to 640×480 before predict — avoids letterboxing a full
            # 1920×1080 frame inside YOLO, saving meaningful CPU on each call.
            small   = cv2.resize(frame, (640, 480))
            results = model.predict(small, imgsz=320, conf=0.4, verbose=False, device="cpu")
            boxes      = []
            detections = []
            for result in results:
                for box in result.boxes:
                    x1, y1, x2, y2 = map(int, box.xyxy[0])
                    conf  = float(box.conf[0])
                    name  = model.names[int(box.cls[0])]
                    label = f"{name} {conf:.0%}"
                    boxes.append((x1, y1, x2, y2, label))
                    detections.append({"label": name, "confidence": round(conf, 2)})
            with boxes_lock:
                last_boxes[:] = boxes
            with detections_lock:
                latest_detections = detections
            count += 1
            elapsed = time.time() - t0
            if elapsed >= 2.0:
                fps_yolo = round(count / elapsed, 1)
                count, t0 = 0, time.time()
            current_labels = {d["label"] for d in detections}
            if current_labels != last_labels:
                _det_seq += 1
                write_state(detections)
                last_labels = current_labels
        except Exception as e:
            print(f"[detection_loop] {e}", flush=True)
            time.sleep(0.1)


def encode_loop():
    global fps_encode
    count, t0 = 0, time.time()
    while True:
        try:
            with raw_frame_lock:
                frame = raw_frame
            if frame is None:
                time.sleep(0.01)
                continue
            with boxes_lock:
                boxes = list(last_boxes)
            annotated = draw_boxes(frame.copy(), boxes)
            _, jpeg = cv2.imencode(
                ".jpg", annotated,
                [cv2.IMWRITE_JPEG_QUALITY, 70, cv2.IMWRITE_JPEG_OPTIMIZE, 1]
            )
            write_frame(jpeg.tobytes())
            count += 1
            elapsed = time.time() - t0
            if elapsed >= 2.0:
                fps_encode = round(count / elapsed, 1)
                count, t0 = 0, time.time()
            time.sleep(0.0417)
        except Exception as e:
            print(f"[encode_loop] {e}", flush=True)
            time.sleep(0.1)


def battery_loop():
    pixels = neopixel.NeoPixel(LED_PIN, LED_COUNT, brightness=BRIGHTNESS, auto_write=False)
    while True:
        try:
            pct, _ = read_battery_pct()
            update_leds(pixels, pct)
        except Exception as e:
            print(f"[battery_loop] {e}", flush=True)
        time.sleep(10)


if __name__ == "__main__":
    load_model()
    start_camera()
    threading.Thread(target=camera_loop,    daemon=True).start()
    threading.Thread(target=detection_loop, daemon=True).start()
    threading.Thread(target=encode_loop,    daemon=True).start()
    threading.Thread(target=battery_loop,   daemon=True).start()
    print("Tony Brain running — shm='tony_frame', state='/tmp/tony_state.json'")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Stopped.")
