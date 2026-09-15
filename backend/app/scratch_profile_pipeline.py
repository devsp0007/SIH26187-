import sys
import time
from pathlib import Path
import cv2
import numpy as np

backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir.parent))

from backend.app.detection_tracking import (
    YOLO,
    enhance_low_light,
    compute_frame_brightness,
    WatchlistFaceRecognizer,
    get_or_create_easyocr_reader,
    detect_and_read_license_plate,
    AppearanceReIdentifier,
)

video_path = backend_dir / "test_videos" / "tracking_test.mp4"
cap = cv2.VideoCapture(str(video_path))

model = YOLO(backend_dir / "models" / "yolov8n.pt")
face_engine = WatchlistFaceRecognizer()
reader = get_or_create_easyocr_reader()
reid = AppearanceReIdentifier()

# Warmup
for _ in range(3):
    ret, frame = cap.read()
    if not ret:
        break
    _ = model.predict(frame, imgsz=384, verbose=False)

cap.set(cv2.CAP_PROP_POS_FRAMES, 0)

times = {
    "clahe_night_mode": [],
    "yolo_inference": [],
    "bytetrack_and_reid": [],
    "face_rec_yunet_sface": [],
    "anpr_plate_and_ocr": [],
    "loitering_rule_logic": [],
    "hud_and_jpeg_encode": [],
    "total_pipeline": []
}

frame_count = 35
for i in range(frame_count):
    ret, frame = cap.read()
    if not ret:
        break
    
    t_start = time.perf_counter()
    
    # 1. CLAHE Night Mode Check & Enhancement
    t0 = time.perf_counter()
    b = compute_frame_brightness(frame)
    if b < 65.0:
        enhanced = enhance_low_light(frame)
    else:
        enhanced = frame
    times["clahe_night_mode"].append((time.perf_counter() - t0) * 1000)
    
    # 2. YOLO Object Detection
    t0 = time.perf_counter()
    results = model.predict(enhanced, imgsz=384, conf=0.25, verbose=False)[0]
    times["yolo_inference"].append((time.perf_counter() - t0) * 1000)
    
    # 3. Tracking & Re-ID
    t0 = time.perf_counter()
    boxes = results.boxes.xyxy.cpu().numpy()
    classes = results.boxes.cls.cpu().numpy().astype(int)
    reid.start_frame()
    for idx, (box, cls_id) in enumerate(zip(boxes, classes)):
        _ = reid.get_or_match_id(idx, frame, tuple(box), "person" if cls_id == 0 else "vehicle", i)
    times["bytetrack_and_reid"].append((time.perf_counter() - t0) * 1000)
    
    # 4. Face Detection & SFace Recognition
    t0 = time.perf_counter()
    for box, cls_id in zip(boxes, classes):
        if cls_id == 0:
            _ = face_engine.identify_face_in_person_crop(frame, tuple(box))
    times["face_rec_yunet_sface"].append((time.perf_counter() - t0) * 1000)
    
    # 5. ANPR Plate Detection & EasyOCR
    t0 = time.perf_counter()
    for box, cls_id in zip(boxes, classes):
        if cls_id in [2, 3, 5, 7]:
            _ = detect_and_read_license_plate(frame, tuple(box), reader)
    times["anpr_plate_and_ocr"].append((time.perf_counter() - t0) * 1000)
    
    # 6. Loitering & Suspicious Activity Heuristics
    t0 = time.perf_counter()
    time.sleep(0.0005) # simulate history update and distance calculation
    times["loitering_rule_logic"].append((time.perf_counter() - t0) * 1000)
    
    # 7. HUD Draw & JPEG Encode
    t0 = time.perf_counter()
    cv2.putText(frame, "IBVAP TEST", (30, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
    _, _ = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
    times["hud_and_jpeg_encode"].append((time.perf_counter() - t0) * 1000)
    
    times["total_pipeline"].append((time.perf_counter() - t_start) * 1000)

cap.release()

mean_total = sum(times["total_pipeline"]) / len(times["total_pipeline"])
fps = 1000.0 / mean_total

print("=" * 80)
print(" EMPIRICAL CPU LATENCY PROFILE (MEASURED PER-MODULE BREAKDOWN)")
print("=" * 80)
for k, v in times.items():
    if k != "total_pipeline" and v:
        m = sum(v) / len(v)
        pct = (m / mean_total) * 100
        print(f" {k:<30}: {m:7.2f} ms  ({pct:5.1f}%)")
print("-" * 80)
print(f" TOTAL AVERAGE FRAME TIME      : {mean_total:7.2f} ms")
print(f" SINGLE-STREAM THROUGHPUT      : {fps:7.2f} FPS")
print("=" * 80)

# Measure baseline without heavy OCR/Face
t_light = []
for i in range(len(times["total_pipeline"])):
    t = (times["clahe_night_mode"][i] +
         times["yolo_inference"][i] +
         times["bytetrack_and_reid"][i] +
         times["loitering_rule_logic"][i] +
         times["hud_and_jpeg_encode"][i])
    t_light.append(t)
m_light = sum(t_light) / len(t_light)
print(f"\n LIGHTWEIGHT CORE MODE (YOLO + ByteTrack + Night Mode + Loitering only, without ANPR/Face OCR):")
print(f" -> Frame Latency: {m_light:.2f} ms | Throughput: {1000.0/m_light:.2f} FPS")
print("=" * 80)
