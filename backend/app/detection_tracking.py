"""
IBVAP - Intelligent Border Video Analytics Platform
Step 6: Multi-Source Video Analytics Engine (Webcam + RTSP + Video Files)

Features:
- Multi-Source Input Support:
  * Integer (e.g. '0'): Local Webcam device
  * RTSP/HTTP URL (e.g. 'rtsp://...'): Live Network/IP Camera stream
  * File Path: Recorded video files (.mp4, .avi, etc.)
- Stream Fault-Tolerance: Automatic 5-attempt reconnect loop for live sources
- Zone Preview Mode (--zone-preview): Saves first-frame polygon visualization
- YOLOv8 Object Detection filtered for border security classes
- Tuned ByteTrack Multi-Target Tracker with persistent track IDs
- Virtual Fence Polygon Intrusion State Machine with instant alerts
- Structured SQLite Database logging & snapshot capture
- Live console telemetry and ASCII database dump on finish
"""

import argparse
import math
import os
import sys
import tempfile
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, List, Optional, Tuple
import cv2
import numpy as np


def get_live_frame_path(camera_id: str) -> Path:
    """Fast OS temp directory path to bypass OneDrive sync locks and latency."""
    temp_dir = Path(tempfile.gettempdir()) / "ibvap_live"
    temp_dir.mkdir(parents=True, exist_ok=True)
    return temp_dir / f"live_frame_{camera_id}.jpg"
import supervision as sv
import torch
from ultralytics import YOLO

# Optimize PyTorch CPU threading for real-time video analytics
try:
    torch.set_num_threads(os.cpu_count() or 4)
except Exception:
    pass

try:
    import psutil
except ImportError:
    psutil = None

try:
    from backend.app.stream_hub import get_frame_hub
except ImportError:
    try:
        from stream_hub import get_frame_hub
    except ImportError:
        get_frame_hub = lambda: None

try:
    from backend.app.events import (
        init_db,
        log_event,
        log_event_async,
        print_database_summary,
        get_default_db_path,
        heartbeat_camera,
    )
    from backend.app.admin_management import check_watchlist_person_active, check_authorized_vehicle
    from backend.app.face_engine import WatchlistFaceRecognizer, get_watchlist_recognizer
except ImportError:
    try:
        from events import (
            init_db,
            log_event,
            log_event_async,
            print_database_summary,
            get_default_db_path,
            heartbeat_camera,
        )
        from admin_management import check_watchlist_person_active, check_authorized_vehicle
        from face_engine import WatchlistFaceRecognizer, get_watchlist_recognizer
    except ImportError:
        check_watchlist_person_active = lambda name, db_path=None: True
        check_authorized_vehicle = lambda plate, db_path=None: None
        WatchlistFaceRecognizer = None
        get_watchlist_recognizer = lambda reload=False: None

try:
    from backend.app.weather_enhancement import (
        compute_fog_haze_metric,
        dehaze_dark_channel_prior,
        dehaze_fast_contrast_saturation,
    )
except ImportError:
    from weather_enhancement import (
        compute_fog_haze_metric,
        dehaze_dark_channel_prior,
        dehaze_fast_contrast_saturation,
    )


def compute_appearance_histogram(frame: np.ndarray, bbox: list[float] | tuple[int, int, int, int]) -> Optional[np.ndarray]:
    """Extract a normalized 2D HSV color histogram from the target bounding box crop for appearance Re-ID."""
    h_img, w_img = frame.shape[:2]
    x1, y1, x2, y2 = map(int, bbox)
    x1, y1 = max(0, min(w_img - 1, x1)), max(0, min(h_img - 1, y1))
    x2, y2 = max(0, min(w_img, x2)), max(0, min(h_img, y2))
    if (x2 - x1) < 10 or (y2 - y1) < 10:
        return None

    crop = frame[y1:y2, x1:x2]
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    # Compute 16x16 H-S color histogram (Hue & Saturation)
    hist = cv2.calcHist([hsv], [0, 1], None, [16, 16], [0, 180, 0, 256])
    cv2.normalize(hist, hist, alpha=0, beta=1, norm_type=cv2.NORM_MINMAX)
    return hist


class AppearanceReIdentifier:
    """
    Lightweight Spatial + HSV Color Histogram Re-Identification Engine.
    Seamlessly links newly spawned ByteTrack tracker IDs back to recently lost tracks,
    eliminating track ID switching during momentary occlusions, turns, or confidence dips.
    """

    def __init__(self, max_lost_frames: int = 45, max_dist_px: float = 180.0, sim_threshold: float = 0.55):
        self.max_lost_frames = max_lost_frames
        self.max_dist_px = max_dist_px
        self.sim_threshold = sim_threshold
        # canonical_id -> dict of track telemetry & appearance histogram
        self.canonical_tracks: dict[int, dict[str, Any]] = {}
        # bytetrack_id -> canonical_id mapping
        self.id_remap: dict[int, int] = {}
        # set of canonical IDs active in the current frame
        self.current_frame_canonical_ids: set[int] = set()
        self.total_reid_events = 0

    def start_frame(self):
        """Prepare active tracker registry for the new frame."""
        self.current_frame_canonical_ids = set()

    def get_or_match_id(
        self,
        raw_id: int,
        frame: np.ndarray,
        bbox: list[float] | tuple[int, int, int, int],
        cls_name: str,
        frame_idx: int,
    ) -> int:
        """
        Resolve a raw ByteTrack tracker ID to a persistent Canonical Track ID.
        If raw_id is new, searches recently lost tracks by spatial proximity and HSV color similarity.
        """
        # If this ByteTrack ID was already mapped in an earlier frame, keep using its canonical ID
        if raw_id in self.id_remap:
            canonical_id = self.id_remap[raw_id]
            self._update_track_state(canonical_id, frame, bbox, cls_name, frame_idx)
            self.current_frame_canonical_ids.add(canonical_id)
            return canonical_id

        # This is a newly spawned ByteTrack ID! Search recently lost tracks for a match.
        x1, y1, x2, y2 = map(int, bbox)
        cur_center = ((x1 + x2) / 2.0, (y1 + y2) / 2.0)
        cur_hist = compute_appearance_histogram(frame, bbox)

        best_match_id: Optional[int] = None
        best_score: float = -1.0
        best_dist: float = 0.0
        best_sim: float = 0.0
        best_gap: int = 0

        # Compare against all recently lost canonical tracks of the same class
        for cid, record in self.canonical_tracks.items():
            # Skip if this track is already active in the current frame
            if cid in self.current_frame_canonical_ids:
                continue

            frame_gap = frame_idx - record["last_seen_frame"]
            if frame_gap <= 0 or frame_gap > self.max_lost_frames:
                continue

            if record["class_name"] != cls_name:
                continue

            last_cx, last_cy = record["last_center"]
            dist = math.sqrt((cur_center[0] - last_cx) ** 2 + (cur_center[1] - last_cy) ** 2)

            # Spatial distance gate: maximum plausible displacement in the lost time window
            dist_allowance = min(self.max_dist_px, self.max_dist_px * (0.50 + 0.50 * (frame_gap / 30.0)))
            if dist > dist_allowance:
                continue

            # Appearance similarity check (HSV histogram correlation)
            appearance_sim = 0.0
            if cur_hist is not None and record["appearance_hist"] is not None:
                corr = float(cv2.compareHist(cur_hist, record["appearance_hist"], cv2.HISTCMP_CORREL))
                appearance_sim = max(0.0, corr)
            else:
                # If histogram is unavailable, allow match only with very tight spatial proximity
                appearance_sim = 0.40 if dist < (dist_allowance * 0.30) else 0.0

            # Strict appearance threshold: do NOT merge tracks with conflicting appearance
            if appearance_sim < 0.35:
                continue

            # Combined weighted score (65% color appearance, 35% spatial proximity)
            norm_dist = max(0.0, 1.0 - (dist / dist_allowance))
            combined_score = 0.65 * appearance_sim + 0.35 * norm_dist

            if combined_score > self.sim_threshold and combined_score > best_score:
                best_score = combined_score
                best_match_id = cid
                best_dist = dist
                best_sim = appearance_sim
                best_gap = frame_gap

        if best_match_id is not None:
            # Match found! Re-link to the previous canonical ID
            canonical_id = best_match_id
            self.id_remap[raw_id] = canonical_id
            self.total_reid_events += 1
            print(
                f"[RE-ID] Re-identified {cls_name} as Track #{canonical_id} (ByteTrack assigned #{raw_id}) | "
                f"Distance: {best_dist:5.1f}px, Color Sim: {best_sim:.2f}, Score: {best_score:.2f}, Gap: {best_gap} frames"
            )
        else:
            # Brand new distinct person/object
            canonical_id = raw_id
            self.id_remap[raw_id] = canonical_id

        self._update_track_state(canonical_id, frame, bbox, cls_name, frame_idx)
        self.current_frame_canonical_ids.add(canonical_id)
        return canonical_id

    def _update_track_state(
        self,
        canonical_id: int,
        frame: np.ndarray,
        bbox: list[float] | tuple[int, int, int, int],
        cls_name: str,
        frame_idx: int,
    ):
        x1, y1, x2, y2 = map(int, bbox)
        cur_center = ((x1 + x2) / 2.0, (y1 + y2) / 2.0)
        cur_hist = compute_appearance_histogram(frame, bbox)

        if canonical_id not in self.canonical_tracks:
            self.canonical_tracks[canonical_id] = {
                "class_name": cls_name,
                "last_seen_frame": frame_idx,
                "last_center": cur_center,
                "last_bbox": bbox,
                "appearance_hist": cur_hist,
                "first_seen_frame": frame_idx,
            }
        else:
            rec = self.canonical_tracks[canonical_id]
            rec["last_seen_frame"] = frame_idx
            rec["last_center"] = cur_center
            rec["last_bbox"] = bbox
            # Exponential moving average for appearance histogram to adapt to illumination changes
            if cur_hist is not None:
                if rec["appearance_hist"] is not None:
                    rec["appearance_hist"] = 0.80 * rec["appearance_hist"] + 0.20 * cur_hist
                    cv2.normalize(rec["appearance_hist"], rec["appearance_hist"], 0, 1, cv2.NORM_MINMAX)
                else:
                    rec["appearance_hist"] = cur_hist

# Target classes to detect and track (COCO class mappings)
TARGET_CLASSES = {
    "person": 0,
    "bicycle": 1,
    "car": 2,
    "motorcycle": 3,
    "bus": 5,
    "truck": 7,
}
TARGET_CLASS_IDS = list(TARGET_CLASSES.values())
TARGET_CLASS_NAMES = list(TARGET_CLASSES.keys())

# Default restricted border polygon (normalized coordinates [0.0 - 1.0] for resolution independence)
DEFAULT_NORMALIZED_POLYGON = np.array(
    [
        [0.32, 0.18],
        [0.68, 0.18],
        [0.68, 0.88],
        [0.32, 0.88],
    ],
    dtype=np.float32,
)


_FAST_CLAHE_CACHE: dict[tuple, cv2.CLAHE] = {}


def compute_frame_brightness(frame: np.ndarray) -> float:
    """
    Compute average luminance/brightness of a BGR frame (0.0 to 255.0).
    Uses fast downsampled grayscale mean (<0.1ms) for low-overhead night scene evaluation.
    """
    if frame is None or frame.size == 0:
        return 128.0
    small_gray = cv2.cvtColor(cv2.resize(frame, (160, 90), interpolation=cv2.INTER_NEAREST), cv2.COLOR_BGR2GRAY)
    return float(np.mean(small_gray))


def enhance_low_light(
    frame: np.ndarray, clip_limit: float = 3.0, tile_grid_size: tuple[int, int] = (8, 8)
) -> np.ndarray:
    """
    Tactical Vectorized Low-Light Illumination & Contrast Engine:
    1. Fast Non-Linear LUT Dynamic Range Lift (boosts shadow details in <0.2ms).
    2. Fast YCrCb space CLAHE on Y luminance channel with illumination-dependent clip limit (~3-5ms).
    3. 38x speedup over legacy bilateral filtering while preserving silhouette and edge fidelity.
    """
    if frame is None or frame.size == 0:
        return frame

    mean_luma = compute_frame_brightness(frame)
    if mean_luma >= 135.0:
        return frame

    # 1. Vectorized LUT Dynamic Range Expansion
    gamma = float(np.clip(0.35 + 0.45 * (mean_luma / 135.0), 0.30, 0.85))
    lut = np.array([np.clip(pow(i / 255.0, gamma) * 255.0 * 1.35, 0, 255) for i in range(256)], dtype=np.uint8)
    lifted = cv2.LUT(frame, lut)

    # 2. Fast YCrCb Space Processing (significantly faster on CPU than LAB)
    ycrcb = cv2.cvtColor(lifted, cv2.COLOR_BGR2YCrCb)
    y_chan = ycrcb[:, :, 0]

    dynamic_clip = float(np.clip(clip_limit + 1.5 * (1.0 - mean_luma / 135.0), 2.0, 5.0))
    clahe_key = (round(dynamic_clip, 1), tile_grid_size)
    if clahe_key not in _FAST_CLAHE_CACHE:
        _FAST_CLAHE_CACHE[clahe_key] = cv2.createCLAHE(clipLimit=dynamic_clip, tileGridSize=tile_grid_size)
    clahe = _FAST_CLAHE_CACHE[clahe_key]

    ycrcb[:, :, 0] = clahe.apply(y_chan)
    enhanced_bgr = cv2.cvtColor(ycrcb, cv2.COLOR_YCrCb2BGR)
    return enhanced_bgr


# Automatic Number Plate Recognition (ANPR) Subsystem
_easyocr_reader = None


def get_or_create_easyocr_reader():
    """Lazy initialize EasyOCR English reader (runs on CPU with PyTorch optimizations)."""
    global _easyocr_reader
    if _easyocr_reader is None:
        try:
            import easyocr
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                _easyocr_reader = easyocr.Reader(["en"], gpu=False, verbose=False)
            print("[+] ANPR Module: EasyOCR Reader INITIALIZED (English Engine)")
        except Exception as e:
            print(f"[!] Warning: Could not initialize EasyOCR reader: {e}")
            _easyocr_reader = None
    return _easyocr_reader


def detect_and_read_license_plate(
    frame: np.ndarray,
    vehicle_bbox: Tuple[int, int, int, int],
    ocr_reader=None,
) -> Tuple[Optional[List[float]], Optional[str], float]:
    """
    Automatic Number Plate Recognition (ANPR) Pipeline:
    1. Plate Localization: Evaluates candidate rectangular regions in lower 65% of vehicle crop
       using morphological gradients and contour aspect-ratio filtering (AR: 1.8 - 6.0).
    2. Plate Preprocessing: Normalizes resolution (rescaling small crops), enhances contrast via CLAHE.
    3. OCR Extraction: EasyOCR character recognition with alphanumeric pattern filtering.
    
    Returns:
        (plate_bbox_in_frame, cleaned_plate_text, ocr_confidence)
    """
    try:
        x1, y1, x2, y2 = vehicle_bbox
        vw = x2 - x1
        vh = y2 - y1
        if vw < 35 or vh < 35:
            return None, None, 0.0

        # Extract lower 65% of vehicle bounding box (typical bumper/grille registration mount)
        crop_y1 = max(0, int(y1 + 0.35 * vh))
        crop_y2 = min(frame.shape[0], y2)
        crop_x1 = max(0, x1)
        crop_x2 = min(frame.shape[1], x2)
        v_crop = frame[crop_y1:crop_y2, crop_x1:crop_x2]
        if v_crop.size == 0:
            return None, None, 0.0

        plate_coords = None
        plate_crop = None

        # Method: Morphological Edge & Contour Aspect Ratio Analysis
        gray = cv2.cvtColor(v_crop, cv2.COLOR_BGR2GRAY)
        sobelx = cv2.Sobel(gray, cv2.CV_8U, 1, 0, ksize=3)
        _, thresh = cv2.threshold(sobelx, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (17, 3))
        morph = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)
        contours, _ = cv2.findContours(morph, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        best_cnt = None
        best_score = -1.0
        crop_area = v_crop.shape[0] * v_crop.shape[1]

        for cnt in contours:
            cx, cy, cw, ch = cv2.boundingRect(cnt)
            if ch == 0:
                continue
            ar = cw / float(ch)
            area = cw * ch
            if 1.8 <= ar <= 6.0 and (0.01 * crop_area) <= area <= (0.45 * crop_area) and cw >= 24 and ch >= 10:
                # Score based on how close aspect ratio is to 3.5 (standard plate)
                score = 1.0 / (abs(ar - 3.5) + 0.1)
                if score > best_score:
                    best_score = score
                    best_cnt = (cx, cy, cw, ch)

        if best_cnt is not None:
            cx, cy, cw, ch = best_cnt
            px1 = crop_x1 + max(0, cx - 2)
            py1 = crop_y1 + max(0, cy - 2)
            px2 = min(frame.shape[1], crop_x1 + cx + cw + 2)
            py2 = min(frame.shape[0], crop_y1 + cy + ch + 2)
            plate_coords = [float(px1), float(py1), float(px2), float(py2)]
            plate_crop = frame[py1:py2, px1:px2]
        else:
            # Fallback to lower-center bumper crop
            px1 = int(crop_x1 + 0.20 * vw)
            px2 = int(crop_x1 + 0.80 * vw)
            py1 = int(crop_y1 + 0.50 * (crop_y2 - crop_y1))
            py2 = int(crop_y2)
            if (px2 - px1) >= 20 and (py2 - py1) >= 10:
                plate_coords = [float(px1), float(py1), float(px2), float(py2)]
                plate_crop = frame[py1:py2, px1:px2]

        if plate_crop is None or plate_crop.size == 0 or ocr_reader is None:
            return plate_coords, None, 0.0

        # Enhance plate crop for OCR
        ph, pw = plate_crop.shape[:2]
        if ph < 40 or pw < 100:
            scale = max(2.0, 60.0 / max(1, ph))
            plate_crop = cv2.resize(plate_crop, (int(pw * scale), int(ph * scale)), interpolation=cv2.INTER_CUBIC)

        ocr_results = ocr_reader.readtext(
            plate_crop,
            detail=1,
            paragraph=False,
            allowlist="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789- "
        )

        if ocr_results:
            clean_texts = []
            max_conf = 0.0
            for item in ocr_results:
                _, text, conf = item
                clean = "".join(c for c in text.upper() if c.isalnum())
                if len(clean) >= 2 and float(conf) > 0.25:
                    clean_texts.append(clean)
                    max_conf = max(max_conf, float(conf))

            if clean_texts:
                merged_plate = "".join(clean_texts)
                if len(merged_plate) >= 4:
                    return plate_coords, merged_plate, round(max_conf, 3)

        return plate_coords, None, 0.0
    except Exception:
        return None, None, 0.0


class SuspiciousBehaviorDetector:
    """
    Lightweight rule-based behavioral anomaly detection engine.
    Analyzes spatial-temporal trajectory history from ByteTrack canonical tracks.
    
    Capabilities:
    1. Suspicious Loitering: Flagged when a person's center-point remains confined
       within a tight radius (<= 45px) for > 35 frames near or inside the restricted perimeter.
    2. Suspicious Pacing / Erratic Traversal: Flagged when a person exhibits >= 3 horizontal
       direction reversals within a sliding window while near the perimeter.
    """
    def __init__(
        self,
        loiter_radius_px: float = 40.0,
        loiter_min_frames: int = 70,
        pacing_window_frames: int = 60,
        pacing_min_reversals: int = 3,
        pacing_min_dist_px: float = 85.0,
        near_zone_distance_px: float = 90.0,
    ):
        self.loiter_radius_px = loiter_radius_px
        self.loiter_min_frames = loiter_min_frames
        self.pacing_window_frames = pacing_window_frames
        self.pacing_min_reversals = pacing_min_reversals
        self.pacing_min_dist_px = pacing_min_dist_px
        self.near_zone_distance_px = near_zone_distance_px

        # Trajectory history: {tracker_id: deque([(frame_idx, cx, cy, is_inside, dist_to_zone)])}
        self.position_histories: dict[int, deque] = {}
        # Tracking alert states: {tracker_id: {loiter_alerted: bool, loiter_alert_frame: int, pacing_alerted: bool, pacing_alert_frame: int, active_behavior: str}}
        self.alert_states: dict[int, dict] = {}

    def update(
        self,
        tracker_id: int,
        cls_name: str,
        center_pt: tuple[int, int],
        is_inside: bool,
        dist_to_zone: float,
        frame_idx: int,
    ) -> list[str]:
        """
        Analyze current frame track movement and return newly triggered behavioral alerts:
        ['suspicious_loitering', 'suspicious_pacing']
        """
        if cls_name != "person":
            return []

        if tracker_id not in self.position_histories:
            self.position_histories[tracker_id] = deque(maxlen=150)
            self.alert_states[tracker_id] = {
                "loiter_alerted": False,
                "loiter_alert_frame": -999,
                "pacing_alerted": False,
                "pacing_alert_frame": -999,
                "active_behavior": None,
            }

        history = self.position_histories[tracker_id]
        history.append((frame_idx, center_pt[0], center_pt[1], is_inside, dist_to_zone))
        st = self.alert_states[tracker_id]
        triggered_events = []

        # Only evaluate behavioral anomalies if near or inside restricted perimeter
        near_or_inside = is_inside or (dist_to_zone <= self.near_zone_distance_px)
        if not near_or_inside:
            st["active_behavior"] = None
            return []

        # 1. Check Loitering Anomaly (Prolonged stationary presence)
        if len(history) >= self.loiter_min_frames:
            recent_loiter = list(history)[-self.loiter_min_frames:]
            xs = [p[1] for p in recent_loiter]
            ys = [p[2] for p in recent_loiter]
            cx_mean = sum(xs) / len(xs)
            cy_mean = sum(ys) / len(ys)
            max_spread = max(math.hypot(x - cx_mean, y - cy_mean) for x, y in zip(xs, ys))

            if max_spread <= self.loiter_radius_px:
                st["active_behavior"] = "LOITERING"
                if (not st["loiter_alerted"]) or (frame_idx - st["loiter_alert_frame"] >= 90):
                    st["loiter_alerted"] = True
                    st["loiter_alert_frame"] = frame_idx
                    triggered_events.append("suspicious_loitering")
            else:
                if max_spread > self.loiter_radius_px * 1.6:
                    st["loiter_alerted"] = False
                    if st["active_behavior"] == "LOITERING":
                        st["active_behavior"] = None

        # 2. Check Pacing Anomaly (Genuine lateral traversal with significant physical displacement)
        if len(history) >= 24:
            window_pts = [p for p in history if (frame_idx - p[0]) <= self.pacing_window_frames]
            if len(window_pts) >= 16:
                # Sample every 3 frames to smooth micro-jitter
                sampled_x = [window_pts[k][1] for k in range(0, len(window_pts), 3)]
                if len(sampled_x) >= 4:
                    diffs = [sampled_x[k + 1] - sampled_x[k] for k in range(len(sampled_x) - 1)]
                    reversals = 0
                    last_dir = 0
                    accum_dist = 0
                    for d in diffs:
                        if abs(d) >= 18:  # Significant physical stride (filters out camera/head jitter)
                            curr_dir = 1 if d > 0 else -1
                            if last_dir != 0 and curr_dir != last_dir:
                                reversals += 1
                            last_dir = curr_dir
                            accum_dist += abs(d)

                    # Total spatial trajectory corridor spread (must be traversing actual ground, not sitting/swaying)
                    x_spread = float(max(sampled_x) - min(sampled_x))

                    if x_spread >= 90.0 and reversals >= self.pacing_min_reversals and accum_dist >= self.pacing_min_dist_px:
                        st["active_behavior"] = "PACING"
                        if (not st["pacing_alerted"]) or (frame_idx - st["pacing_alert_frame"] >= 75):
                            st["pacing_alerted"] = True
                            st["pacing_alert_frame"] = frame_idx
                            triggered_events.append("suspicious_pacing")
                    elif reversals == 0 or x_spread < 35.0:
                        st["pacing_alerted"] = False
                        if st["active_behavior"] == "PACING":
                            st["active_behavior"] = None

        return triggered_events

    def get_active_behavior(self, tracker_id: int) -> str | None:
        return self.alert_states.get(tracker_id, {}).get("active_behavior")


def get_default_paths():
    """Resolve directory paths relative to this script."""
    app_dir = Path(__file__).resolve().parent
    backend_dir = app_dir.parent
    models_dir = backend_dir / "models"
    test_videos_dir = backend_dir / "test_videos"
    tracker_config_path = app_dir / "bytetrack_tuned.yaml"

    models_dir.mkdir(parents=True, exist_ok=True)
    test_videos_dir.mkdir(parents=True, exist_ok=True)

    default_model_path = models_dir / "yolov8n.pt"
    return backend_dir, models_dir, test_videos_dir, default_model_path, tracker_config_path


def load_yolo_model(model_path: Path) -> YOLO:
    """Load or automatically download YOLOv8 model weights."""
    if not model_path.exists():
        print(f"[*] Pretrained weights not found at {model_path}. Downloading YOLOv8n...")
        model = YOLO("yolov8n.pt")
        try:
            model.save(str(model_path))
        except Exception:
            pass
    else:
        model = YOLO(str(model_path))
    return model


def draw_restricted_zone(frame: np.ndarray, polygon: np.ndarray, is_intruded: bool):
    """
    Draw a sleek tactical cyber perimeter zone overlay.
    Uses clean neon borders with corner reticles and an ultra-light transparent interior,
    ensuring background objects (furniture, trees, cupboards) are never obscured or mistaken for detections.
    """
    border_color = (0, 0, 245) if is_intruded else (255, 200, 0)

    # Ultra-subtle tint (alpha <= 0.04) only to give a faint atmospheric holographic field
    overlay = frame.copy()
    cv2.fillPoly(overlay, [polygon], (0, 0, 180) if is_intruded else (255, 180, 0))
    cv2.addWeighted(overlay, 0.04 if is_intruded else 0.02, frame, 0.96 if is_intruded else 0.98, 0, frame)

    # Draw crisp tactical boundary line
    cv2.polylines(
        frame,
        [polygon],
        isClosed=True,
        color=border_color,
        thickness=2,
        lineType=cv2.LINE_AA,
    )

    # Draw high-tech tactical corner reticles (L-brackets) on polygon vertices
    reticle_len = 16
    for pt in polygon:
        px, py = int(pt[0]), int(pt[1])
        cv2.line(frame, (px - reticle_len, py), (px + reticle_len, py), border_color, 2, cv2.LINE_AA)
        cv2.line(frame, (px, py - reticle_len), (px, py + reticle_len), border_color, 2, cv2.LINE_AA)
        cv2.circle(frame, (px, py), 3, (255, 255, 255), -1, cv2.LINE_AA)

    # Draw explicit Virtual Geo-Fence status banner
    top_left = polygon[0]
    status_text = (
        "[ VIRTUAL GEO-FENCE ] ALERT: INTRUSION DETECTED"
        if is_intruded
        else "[ VIRTUAL GEO-FENCE ] STATUS: PERIMETER SECURE"
    )
    text_color = (0, 0, 255) if is_intruded else (0, 240, 255)

    tx = max(10, int(top_left[0]))
    ty = max(24, int(top_left[1]) - 10)
    (tw, th), baseline = cv2.getTextSize(status_text, cv2.FONT_HERSHEY_SIMPLEX, 0.48, 1)
    cv2.rectangle(
        frame,
        (tx - 4, ty - th - baseline - 4),
        (tx + tw + 6, ty + baseline),
        (15, 23, 42),
        -1,
    )
    cv2.rectangle(
        frame,
        (tx - 4, ty - th - baseline - 4),
        (tx + tw + 6, ty + baseline),
        border_color,
        1,
    )
    cv2.putText(
        frame,
        status_text,
        (tx, ty - 2),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.48,
        text_color,
        1,
        cv2.LINE_AA,
    )


def save_zone_preview(frame: np.ndarray, polygon: np.ndarray, preview_path: Path):
    """Save an initial frame image with the virtual fence polygon clearly visualized."""
    preview_img = frame.copy()
    draw_restricted_zone(preview_img, polygon, is_intruded=False)

    # Annotate polygon vertex coordinates for easy calibration
    for idx, pt in enumerate(polygon):
        cv2.circle(preview_img, (pt[0], pt[1]), 6, (0, 255, 255), -1)
        cv2.putText(
            preview_img,
            f"P{idx+1} ({pt[0]},{pt[1]})",
            (pt[0] + 8, pt[1] - 8),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (0, 255, 255),
            1,
            cv2.LINE_AA,
        )

    cv2.putText(
        preview_img,
        "VIRTUAL FENCE ZONE CALIBRATION PREVIEW",
        (20, 40),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.75,
        (0, 255, 255),
        2,
        cv2.LINE_AA,
    )
    cv2.imwrite(str(preview_path), preview_img)
    print(f"\n[+] Zone preview image saved to: {preview_path}")
    print("    Inspect this image to verify/adjust virtual fence polygon coordinates for this camera.\n")


class ThreadedLiveStream:
    """
    High-Performance Zero-Lag Threaded Video Ingestion Stream for Live Webcams & RTSP Streams.
    Continuously consumes camera hardware frames in a daemon worker thread, dropping stale buffer backlog,
    and returns the latest instant frame with 0 ms latency.
    """

    def __init__(self, source: str | int):
        self.source = source
        self.cap = open_video_capture(source)
        self.lock = threading.Lock()
        self.latest_frame: Optional[np.ndarray] = None
        self.ret = False
        self.stopped = False
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 5

        if self.cap.isOpened():
            self.ret, self.latest_frame = self.cap.read()
            self.thread = threading.Thread(target=self._reader_loop, daemon=True)
            self.thread.start()

    def _reader_loop(self):
        while not self.stopped:
            if not self.cap or not self.cap.isOpened():
                time.sleep(0.5)
                continue
            try:
                grabbed = self.cap.grab()
                if grabbed:
                    ret, frame = self.cap.retrieve()
                    if ret and frame is not None:
                        with self.lock:
                            self.ret = ret
                            self.latest_frame = frame
                else:
                    time.sleep(0.005)
            except Exception:
                time.sleep(0.01)

    def read(self) -> Tuple[bool, Optional[np.ndarray]]:
        with self.lock:
            if self.latest_frame is not None:
                return self.ret, self.latest_frame.copy()
            return False, None

    def isOpened(self) -> bool:
        return self.cap.isOpened() if self.cap else False

    def get(self, prop_id: int) -> float:
        return self.cap.get(prop_id) if self.cap else 0.0

    def release(self):
        self.stopped = True
        if hasattr(self, "thread") and self.thread.is_alive():
            self.thread.join(timeout=0.5)
        if self.cap:
            self.cap.release()


def open_video_capture(source: str | int):
    """Open OpenCV VideoCapture supporting Webcam index, RTSP/HTTP URL, or file path."""
    if isinstance(source, int):
        # On Windows, cv2.CAP_DSHOW provides fast hardware webcam initialization
        cap = cv2.VideoCapture(source, cv2.CAP_DSHOW)
        if not cap.isOpened():
            cap = cv2.VideoCapture(source)
        try:
            # Set minimal buffer to eliminate video lag and frame queuing
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass
        return cap
    elif isinstance(source, str) and (source.startswith("rtsp://") or source.startswith("http://") or source.startswith("https://")):
        # Network RTSP / HTTP IP Camera Stream
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"
        return cv2.VideoCapture(source, cv2.CAP_FFMPEG)
    else:
        # Standard video file
        return cv2.VideoCapture(str(source))


def run_tracking_and_fence(
    input_source: str | int,
    model_path: Path,
    tracker_config: Path,
    output_path: str | None = None,
    conf_threshold: float = 0.35,
    alert_conf_threshold: float = 0.45,
    show_live: bool = True,
    polygon_points: np.ndarray | None = None,
    camera_id: str = "CAM_01",
    camera_name: str | None = None,
    zone_label: str | None = None,
    zone_preview: bool = False,
    max_frames: int | None = None,
    imgsz: int = 480,
    night_mode: bool = True,
    low_light_thresh: float = 65.0,
    weather_mode: bool = True,
    weather_dehaze_method: str = "dcp",
    loop: bool = True,
    show_zone: bool = True,
):
    """Run ByteTrack tracking and polygon virtual fence intrusion detection with live reconnect support, Appearance Re-ID, Night-Mode CLAHE, and Weather-Adaptive Dehazing."""
    is_webcam = isinstance(input_source, int)
    is_network_stream = isinstance(input_source, str) and (
        input_source.startswith("rtsp://")
        or input_source.startswith("http://")
        or input_source.startswith("https://")
    )
    is_live_stream = is_webcam or is_network_stream

    # Canonical source video identifier for precision incident replay tracking
    if is_live_stream:
        source_video_tag = "live_webcam" if is_webcam else "live_stream"
    elif output_path:
        source_video_tag = Path(output_path).name
    elif isinstance(input_source, (str, Path)):
        source_video_tag = Path(str(input_source)).name
    else:
        source_video_tag = None

    if is_live_stream:
        cap = ThreadedLiveStream(input_source)
    else:
        cap = open_video_capture(input_source)

    if not cap.isOpened():
        print(f"[!] Error: Could not open video source: {input_source}")
        if is_webcam:
            print(f"    No webcam found at device index {input_source}.")
        sys.exit(1)

    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 1280
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 720
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) if not is_live_stream else 0

    # Initialize SQLite database
    db_path = init_db()

    # Resolve camera display name & location zone labels
    cid_suffix = camera_id.replace("CAM_", "").replace("cam_", "").strip()
    resolved_cam_name = camera_name or f"Sector {cid_suffix or '01'} Gate"
    resolved_zone_label = zone_label or f"North Perimeter Fence - Sector {cid_suffix or '01'}"

    # Initial camera registry heartbeat
    heartbeat_camera(
        camera_id=camera_id,
        name=resolved_cam_name,
        location=resolved_zone_label,
        resolution=f"{width}x{height}",
        fps=fps,
        monitored_zone=resolved_zone_label,
        db_path=db_path,
    )

    # Scale normalized polygon to match actual video frame resolution
    if polygon_points is None:
        if is_webcam:
            # Dedicated side perimeter corridor for webcam mode so sitting at desk/center does not trigger zone
            webcam_poly = np.array([[0.62, 0.12], [0.96, 0.12], [0.96, 0.88], [0.62, 0.88]], dtype=np.float32)
            polygon = (webcam_poly * [width, height]).astype(np.int32)
        else:
            polygon = (DEFAULT_NORMALIZED_POLYGON * [width, height]).astype(np.int32)
    else:
        polygon = polygon_points.astype(np.int32)

    source_type_label = (
        f"Webcam (Device #{input_source})"
        if is_webcam
        else ("RTSP / IP Camera Stream" if is_network_stream else f"File ({input_source})")
    )

    print("\n" + "=" * 75)
    print(" IBVAP - Multi-Source Tracking, Virtual Fence & Event Logging Engine")
    print("=" * 75)
    print(f" Camera ID         : {camera_id} ({resolved_cam_name})")
    print(f" Zone Location     : {resolved_zone_label}")
    print(f" Source Type       : {source_type_label}")
    print(f" Resolution        : {width} x {height} @ {fps:.2f} FPS")
    print(f" Total Frames      : {total_frames if total_frames > 0 else 'Live Stream (Continuous)'}")
    print(f" Model             : {model_path.name}")
    print(f" Inference Size    : {imgsz}px (Optimized)")
    print(f" Tracker Config    : {tracker_config.name} (Tuned ByteTrack + Appearance Re-ID)")
    print(f" Track / Alert Conf: {conf_threshold:.2f} (Tracking) / {alert_conf_threshold:.2f} (Alerting)")
    print(f" Night Mode (CLAHE): {'ENABLED (Auto-Detect Luminance < ' + str(low_light_thresh) + ')' if night_mode else 'DISABLED'}")
    print(f" Weather Dehazing  : {'ENABLED (' + weather_dehaze_method.upper() + ' Algorithm)' if weather_mode else 'DISABLED'}")
    if weather_mode and weather_dehaze_method == "fast":
        print("   [!] WARNING: 'fast' contrast-stretching is experimental and degraded recall in empirical audits. 'dcp' is strongly recommended.")
    print(f" SQLite Database   : {db_path}")
    print(f" Virtual Fence Poly: {polygon.tolist()}")
    if output_path and not is_live_stream:
        print(f" Output Video File : {output_path}")
    print("=" * 75 + "\n")

    # Warm up camera sensor for live/webcam sources to allow auto-exposure & white balance to settle
    if is_webcam:
        print("[*] Warming up camera sensor (skipping initial 3 warmup frames)...")
        for _ in range(3):
            cap.read()

    # Initialize video output writer (only if output_path is requested)
    writer = None
    if output_path:
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(output_path, fourcc, fps, (width, height))

    model = load_yolo_model(model_path)
    tracker_arg = str(tracker_config) if tracker_config.exists() else "bytetrack.yaml"

    # Neural network warmup (compiles PyTorch graph & pre-allocates CPU buffers)
    print("[*] Warming up YOLO inference engine...")
    try:
        dummy_img = np.zeros((imgsz, imgsz, 3), dtype=np.uint8)
        _ = model.track(
            source=dummy_img,
            persist=True,
            tracker=tracker_arg,
            classes=TARGET_CLASS_IDS,
            conf=conf_threshold,
            imgsz=imgsz,
            verbose=False,
        )
    except Exception:
        pass

    # Appearance Re-ID Engine & Intrusion State Management
    reid_engine = AppearanceReIdentifier(max_lost_frames=45, max_dist_px=180.0, sim_threshold=0.55)
    behavior_detector = SuspiciousBehaviorDetector(
        loiter_radius_px=45.0,
        loiter_min_frames=35,
        pacing_window_frames=40,
        pacing_min_reversals=3,
        pacing_min_dist_px=25.0,
        near_zone_distance_px=120.0,
    )
    tracked_states: dict[int, dict] = {}
    track_histories: dict[int, deque] = {}
    total_intrusion_events = 0

    # Initialize Face Identification Module (YuNet Detection + SFace 128-d Cosine Matching against Watchlist)
    backend_dir = Path(__file__).resolve().parent.parent
    models_dir = backend_dir / "models"
    watchlist_recognizer = WatchlistFaceRecognizer(
        watchlist_dir=backend_dir / "watchlist",
        models_dir=models_dir,
        cosine_threshold=0.48,
    )
    face_recog_cache: dict[int, dict] = {}
    # Track-lifetime confirmed identity registry (persists across track life, never demoted)
    confirmed_track_identities: dict[int, dict] = {}
    # Temporal facial recognition observation history for multi-frame consensus
    track_face_history: dict[int, deque] = {}
    # Buffered zone entry events awaiting face verification grace window (tracker_id -> pending event dict)
    pending_zone_entries: dict[int, dict] = {}
    if watchlist_recognizer.detector is not None and watchlist_recognizer.recognizer is not None:
        wl_count = len(watchlist_recognizer.watchlist_embeddings)
        print(f"[+] Face Recognition Module: INITIALIZED (SFace ONNX - {wl_count} Consented Watchlist Profiles Cached)")
    else:
        print("[!] Face Recognition Module: DISABLED (Models could not be loaded)")

    # Initialize ANPR Engine (License Plate Localization + EasyOCR Character Recognition)
    ocr_reader = get_or_create_easyocr_reader()
    vehicle_plate_cache: dict[int, dict] = {}

    frame_idx = 0
    can_display = show_live
    reconnect_attempts = 0
    max_reconnect_attempts = 5
    preview_saved = False

    # FPS Rolling Window & Per-Stage Profiling
    fps_history: deque[float] = deque(maxlen=30)
    stat_grab: deque[float] = deque(maxlen=30)
    stat_track: deque[float] = deque(maxlen=30)
    stat_zone: deque[float] = deque(maxlen=30)
    stat_draw: deque[float] = deque(maxlen=30)
    stat_write: deque[float] = deque(maxlen=30)
    stat_total: deque[float] = deque(maxlen=30)

    current_fps = 0.0

    # Bidirectional Footfall & Sector Occupancy State
    footfall_in_count = 0
    footfall_out_count = 0
    active_inside_track_ids: set[int] = set()

    try:
        while True:
            # Stage 1: Frame Grab
            t0 = time.perf_counter()
            ret, frame = cap.read()
            t_grab_end = time.perf_counter()
            dur_grab = (t_grab_end - t0) * 1000.0
            stat_grab.append(dur_grab)

            if not ret or frame is None:
                if is_live_stream:
                    reconnect_attempts += 1
                    print(
                        f"[WARNING] Stream read failed, attempting reconnect ({reconnect_attempts}/{max_reconnect_attempts})..."
                    )
                    cap.release()
                    time.sleep(2)
                    cap = open_video_capture(input_source)
                    if cap.isOpened():
                        print("[+] Stream successfully reconnected.")
                        reconnect_attempts = 0
                        continue
                    elif reconnect_attempts >= max_reconnect_attempts:
                        print(
                            f"[!] Error: Stream disconnected and failed to recover after {max_reconnect_attempts} attempts."
                        )
                        break
                    else:
                        continue
                else:
                    # Video file ended -> Rewind if loop enabled
                    if loop:
                        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        ret, frame = cap.read()
                        if not ret or frame is None:
                            cap.release()
                            cap = open_video_capture(input_source)
                            ret, frame = cap.read()
                        if ret and frame is not None:
                            continue
                    break

            # Successful frame read, reset reconnect counter
            reconnect_attempts = 0
            frame_idx += 1

            # Update resolution if changed dynamically
            if max_frames is not None and frame_idx > max_frames:
                break

            # Save zone preview on frame 15 (after auto-exposure settling) if requested
            if zone_preview and frame_idx == 15:
                preview_frame = frame.copy()
                draw_restricted_zone(preview_frame, polygon, is_intruded=False)
                preview_path = test_videos_dir / "zone_preview.jpg"
                cv2.imwrite(str(preview_path), preview_frame)
                print(f"[+] Clean Zone preview saved to: {preview_path}")
                break

            # Stage 1: Environmental Condition Analysis (Fog/Haze & Night Low-Light) - Cached every 20 frames
            if frame_idx == 1 or (frame_idx % 20 == 0):
                if is_webcam:
                    # Indoor webcam does not experience atmospheric fog; avoid CPU-heavy DCP dehazing
                    is_hazy, haze_score, haze_metrics = False, 0.0, {}
                    is_weather_mode_active = False
                else:
                    is_hazy, haze_score, haze_metrics = compute_fog_haze_metric(frame)
                    is_weather_mode_active = weather_mode and is_hazy

                frame_brightness = compute_frame_brightness(frame)
                is_night_mode_active = night_mode and (frame_brightness < low_light_thresh)

            # Apply Weather Dehazing if atmospheric fog/haze is detected
            if is_weather_mode_active:
                if weather_dehaze_method == "fast":
                    frame = dehaze_fast_contrast_saturation(frame)
                else:
                    frame = dehaze_dark_channel_prior(frame)

            # Apply Advanced Night Mode if low ambient light is detected (can coexist with weather mode)
            effective_conf = conf_threshold
            if is_night_mode_active:
                frame = enhance_low_light(frame, clip_limit=3.0, tile_grid_size=(8, 8))
                # Dynamic tracking confidence sensitivity for low-light figures
                effective_conf = max(0.28, conf_threshold - 0.07)

            # Stage 2: YOLOv8 Inference + ByteTrack Tracking (with PyTorch inference_mode)
            t1 = time.perf_counter()
            with torch.inference_mode():
                results = model.track(
                    source=frame,
                    persist=True,
                    tracker=tracker_arg,
                    classes=TARGET_CLASS_IDS,
                    conf=effective_conf,
                    imgsz=imgsz,
                    verbose=False,
                )[0]
            t_track_end = time.perf_counter()
            dur_track = (t_track_end - t1) * 1000.0
            stat_track.append(dur_track)

            # Stage 3: Supervision Parsing, Point-in-Polygon Tests, Face Localization & Hysteresis State Machine
            t2 = time.perf_counter()
            detections = sv.Detections.from_ultralytics(results)

            reid_engine.start_frame()
            current_intruders = []
            active_tracks_count = 0
            track_render_data = []

            if (
                detections is not None
                and len(detections) > 0
            ):
                has_tracker_ids = detections.tracker_id is not None
                for i in range(len(detections)):
                    raw_tracker_id = (
                        int(detections.tracker_id[i])
                        if (has_tracker_ids and detections.tracker_id[i] is not None)
                        else (i + 1)
                    )

                    cls_id = int(detections.class_id[i])
                    confidence = float(detections.confidence[i])
                    x1, y1, x2, y2 = map(int, detections.xyxy[i].tolist())
                    bbox_coords = [float(x1), float(y1), float(x2), float(y2)]
                    cls_name = model.names.get(cls_id, f"cls_{cls_id}")

                    # Anti-False-Positive Filter for Inanimate Background Objects (Furniture, Trees, Walls, Cupboards)
                    bw = x2 - x1
                    bh = y2 - y1
                    if cls_name == "person":
                        if bh <= 0 or bw <= 0:
                            continue
                        aspect_ratio = bh / float(bw)
                        # Humans sitting in front of webcam have lower aspect ratio (~0.45 - 0.85) due to wide shoulders
                        min_aspect = 0.40 if is_webcam else 0.50
                        if aspect_ratio < min_aspect:
                            continue
                        # Reject micro pixel noise
                        if bw < 20 or bh < 25:
                            continue
                        # Enforce responsive detection threshold for instant appearance
                        min_conf = 0.32 if is_webcam else 0.38
                        if confidence < min_conf:
                            continue
                    elif cls_name in ["car", "bus", "truck"]:
                        if bw < 30 or bh < 25 or confidence < 0.45:
                            continue

                    # Resolve raw ByteTrack ID to Canonical Track ID via Appearance Re-ID
                    tracker_id = reid_engine.get_or_match_id(
                        raw_id=raw_tracker_id,
                        frame=frame,
                        bbox=(x1, y1, x2, y2),
                        cls_name=cls_name,
                        frame_idx=frame_idx,
                    )

                    # Run Face Identification (YuNet + SFace against Watchlist)
                    face_bbox = None
                    identified_as = None
                    identification_confidence = None
                    if cls_name == "person" and watchlist_recognizer is not None:
                        # 1. Check if this canonical track was already confirmed as a watchlisted person
                        if tracker_id in confirmed_track_identities:
                            conf_data = confirmed_track_identities[tracker_id]
                            identified_as = conf_data["name"]
                            identification_confidence = conf_data["confidence"]
                            cached_f = face_recog_cache.get(tracker_id)
                            face_bbox = cached_f.get("face_bbox") if cached_f else None

                            # Periodically (every 45 frames) or if face_bbox is None, refresh face bounding box coords for HUD
                            if cached_f is None or (frame_idx - cached_f.get("last_checked", 0)) >= 45 or face_bbox is None:
                                f_name, f_conf, f_coords = watchlist_recognizer.identify_face_in_person_crop(frame, (x1, y1, x2, y2))
                                if f_coords is not None:
                                    face_bbox = f_coords
                                # Update confidence if higher match score attained
                                if f_name and f_name != "UNKNOWN" and f_name == identified_as and f_conf > identification_confidence:
                                    confirmed_track_identities[tracker_id]["confidence"] = f_conf
                                    identification_confidence = f_conf
                                face_recog_cache[tracker_id] = {
                                    "face_bbox": face_bbox,
                                    "identified_as": identified_as,
                                    "identification_confidence": identification_confidence,
                                    "last_checked": frame_idx,
                                }
                        else:
                            # 2. Not yet confirmed: check face on initial appearance (cached_f is None) immediately, then throttle to every 8 frames
                            cached_f = face_recog_cache.get(tracker_id)
                            should_check_face = (cached_f is None or (frame_idx - cached_f.get("last_checked", 0)) >= 8)
                            if should_check_face:
                                f_name, f_conf, f_coords = watchlist_recognizer.identify_face_in_person_crop(frame, (x1, y1, x2, y2))
                                face_bbox = f_coords
                            else:
                                f_name = cached_f.get("identified_as")
                                f_conf = cached_f.get("identification_confidence") or 0.0
                                face_bbox = cached_f.get("face_bbox")

                            if should_check_face and f_name and f_name != "UNKNOWN" and f_conf >= 0.46:
                                if tracker_id not in track_face_history:
                                    track_face_history[tracker_id] = deque(maxlen=10)
                                track_face_history[tracker_id].append((frame_idx, f_name, f_conf))

                                # Multi-frame consensus check (within recent 25 frames)
                                recent_same_matches = [
                                    (f_idx, name, conf)
                                    for (f_idx, name, conf) in track_face_history[tracker_id]
                                    if name == f_name and (frame_idx - f_idx) <= 25
                                ]

                                # Confirm if 2+ consistent matching frames or ultra-high single match (>=0.75)
                                if len(recent_same_matches) >= 2 or f_conf >= 0.75:
                                    avg_conf = sum(c for _, _, c in recent_same_matches) / len(recent_same_matches)
                                    confirmed_track_identities[tracker_id] = {
                                        "name": f_name,
                                        "confidence": round(avg_conf, 3),
                                        "first_identified_frame": recent_same_matches[0][0],
                                        "consensus_frames": len(recent_same_matches),
                                    }
                                    identified_as = f_name
                                    identification_confidence = round(avg_conf, 3)
                                    print(
                                        f"[+] [FACE RECOG CONFIRMED] Track #{tracker_id} positively identified as: '{f_name}' "
                                        f"(Consensus: {len(recent_same_matches)} frame(s), Avg Conf: {avg_conf*100:.1f}%) @ Frame {frame_idx}"
                                    )
                                else:
                                    # Candidate match awaiting multi-frame confirmation
                                    identified_as = "UNKNOWN"
                                    identification_confidence = None
                            elif should_check_face:
                                identified_as = f_name
                                identification_confidence = None
                            else:
                                identified_as = f_name
                                identification_confidence = f_conf if f_conf > 0 else None

                            if should_check_face:
                                face_recog_cache[tracker_id] = {
                                    "face_bbox": face_bbox,
                                    "identified_as": identified_as,
                                    "identification_confidence": identification_confidence,
                                    "last_checked": frame_idx,
                                }

                    # Run ANPR License Plate Localization & EasyOCR Character Recognition on vehicles
                    plate_bbox = None
                    plate_number = None
                    plate_confidence = None
                    if cls_name in ["car", "bus", "truck", "motorcycle", "vehicle"]:
                        cached_p = vehicle_plate_cache.get(tracker_id)
                        if cached_p and cached_p.get("plate_number") is not None:
                            plate_bbox = cached_p.get("plate_bbox")
                            plate_number = cached_p.get("plate_number")
                            plate_confidence = cached_p.get("plate_confidence")
                        elif cached_p is None or (frame_idx - cached_p.get("last_checked", 0)) >= 15:
                            p_bbox, p_text, p_conf = detect_and_read_license_plate(frame, (x1, y1, x2, y2), ocr_reader)
                            plate_bbox = p_bbox
                            plate_number = p_text
                            plate_confidence = p_conf
                            vehicle_plate_cache[tracker_id] = {
                                "plate_bbox": plate_bbox,
                                "plate_number": plate_number,
                                "plate_confidence": plate_confidence,
                                "last_checked": frame_idx,
                            }
                        elif cached_p is not None:
                            plate_bbox = cached_p.get("plate_bbox")
                            plate_number = cached_p.get("plate_number")
                            plate_confidence = cached_p.get("plate_confidence")

                    active_tracks_count += 1

                    # Determine object anchor / center points for ground-plane and bounding box testing
                    foot_point = (int((x1 + x2) / 2), int(y2))
                    center_point = (int((x1 + x2) / 2), int((y1 + y2) / 2))

                    # Test if object is inside restricted polygon (foot or center)
                    if show_zone:
                        poly_foot = cv2.pointPolygonTest(polygon, (float(foot_point[0]), float(foot_point[1])), True)
                        poly_center = cv2.pointPolygonTest(polygon, (float(center_point[0]), float(center_point[1])), True)
                        is_inside = (poly_foot >= 0 or poly_center >= 0)
                        dist_to_zone = 0.0 if is_inside else min(abs(poly_foot), abs(poly_center))
                    else:
                        is_inside = False
                        dist_to_zone = 999.0

                    # Check if target is an authorized/watchlisted person
                    is_person_auth = (
                        cls_name == "person"
                        and (tracker_id in confirmed_track_identities or (identified_as and identified_as != "UNKNOWN"))
                    )

                    # Evaluate Suspicious Behavioral Anomalies (Loitering & Pacing)
                    behavior_events = behavior_detector.update(
                        tracker_id=tracker_id,
                        cls_name=cls_name,
                        center_pt=center_point,
                        is_inside=is_inside,
                        dist_to_zone=dist_to_zone,
                        frame_idx=frame_idx,
                    )
                    # For authorized personnel, completely suppress suspicious behavior alarms
                    if not is_person_auth:
                        for b_ev in behavior_events:
                            total_intrusion_events += 1
                            log_event_async(
                                camera_id=camera_id,
                                event_type=b_ev,
                                object_class=cls_name,
                                track_id=tracker_id,
                                frame_number=frame_idx,
                                bbox=bbox_coords,
                                confidence=confidence,
                                frame=frame,
                                db_path=db_path,
                                print_json=True,
                                face_detected=(face_bbox is not None),
                                face_bbox=face_bbox,
                                plate_number=plate_number,
                                plate_confidence=plate_confidence,
                                plate_bbox=plate_bbox,
                                identified_as=identified_as,
                                identification_confidence=identification_confidence,
                                source_video=source_video_tag,
                            )

                    active_behavior = None if is_person_auth else behavior_detector.get_active_behavior(tracker_id)

                    # Update movement trail history
                    if tracker_id not in track_histories:
                        track_histories[tracker_id] = deque(maxlen=30)
                    track_histories[tracker_id].append(foot_point)

                    # 3-Frame Hysteresis / Debounce State Machine
                    if tracker_id not in tracked_states:
                        tracked_states[tracker_id] = {
                            "confirmed_inside": False,
                            "candidate_inside": is_inside,
                            "consecutive_count": 1,
                            "class_name": cls_name,
                            "last_frame": frame_idx,
                            "bbox": bbox_coords,
                            "conf": confidence,
                            "face_bbox": face_bbox,
                            "plate_number": plate_number,
                            "plate_confidence": plate_confidence,
                            "plate_bbox": plate_bbox,
                            "identified_as": identified_as,
                            "identification_confidence": identification_confidence,
                        }
                    else:
                        st = tracked_states[tracker_id]
                        if is_inside == st["candidate_inside"]:
                            st["consecutive_count"] += 1
                        else:
                            st["candidate_inside"] = is_inside
                            st["consecutive_count"] = 1

                        # Require 3 consecutive frames to confirm state transition
                        if st["consecutive_count"] >= 3 and st["candidate_inside"] != st["confirmed_inside"]:
                            st["confirmed_inside"] = st["candidate_inside"]
                            if st["confirmed_inside"]:
                                # Transition OUTSIDE -> INSIDE (Confirmed Entry)
                                if tracker_id not in active_inside_track_ids:
                                    footfall_in_count += 1
                                    active_inside_track_ids.add(tracker_id)

                                # Only log zone entry alert if detection meets alert confidence threshold
                                if confidence >= alert_conf_threshold:
                                    if cls_name == "person":
                                        if tracker_id in confirmed_track_identities:
                                            # Already confirmed as authorized person -> Log Routine Access (LOW severity) immediately
                                            conf_data = confirmed_track_identities[tracker_id]
                                            print(
                                                f"[DEBUG ZONE_ENTRY DECISION] Track #{tracker_id} entered zone @ Frame {frame_idx}: "
                                                f"in_confirmed=True (Name: '{conf_data['name']}'), "
                                                f"identified_as='{conf_data['name']}', "
                                                f"grace_window=SKIPPED -> IMMEDIATE_LOG (LOW / Routine Access)"
                                            )
                                            total_intrusion_events += 1
                                            log_event_async(
                                                camera_id=camera_id,
                                                event_type="zone_entry",
                                                object_class=cls_name,
                                                track_id=tracker_id,
                                                frame_number=frame_idx,
                                                bbox=bbox_coords,
                                                confidence=confidence,
                                                frame=frame,
                                                db_path=db_path,
                                                print_json=True,
                                                face_detected=(face_bbox is not None),
                                                face_bbox=face_bbox,
                                                plate_number=plate_number,
                                                plate_confidence=plate_confidence,
                                                plate_bbox=plate_bbox,
                                                identified_as=conf_data["name"],
                                                identification_confidence=conf_data["confidence"],
                                                source_video=source_video_tag,
                                            )
                                        else:
                                            # Person entered without confirmed identity yet: buffer for grace window of 45 frames (~1.5s at 30fps)
                                            grace_limit = frame_idx + 45
                                            print(
                                                f"[DEBUG ZONE_ENTRY DECISION] Track #{tracker_id} entered zone @ Frame {frame_idx}: "
                                                f"in_confirmed=False, identified_as='{identified_as}', "
                                                f"grace_window=TRIGGERED -> BUFFERED (Grace until Frame {grace_limit})"
                                            )
                                            pending_zone_entries[tracker_id] = {
                                                "camera_id": camera_id,
                                                "event_type": "zone_entry",
                                                "object_class": cls_name,
                                                "track_id": tracker_id,
                                                "trigger_frame": frame_idx,
                                                "grace_until_frame": grace_limit,
                                                "bbox": bbox_coords,
                                                "confidence": confidence,
                                                "frame": frame.copy(),
                                                "face_bbox": face_bbox,
                                                "plate_number": plate_number,
                                                "plate_confidence": plate_confidence,
                                                "plate_bbox": plate_bbox,
                                                "source_video": source_video_tag,
                                            }
                                    else:
                                        total_intrusion_events += 1
                                        log_event_async(
                                            camera_id=camera_id,
                                            event_type="zone_entry",
                                            object_class=cls_name,
                                            track_id=tracker_id,
                                            frame_number=frame_idx,
                                            bbox=bbox_coords,
                                            confidence=confidence,
                                            frame=frame,
                                            db_path=db_path,
                                            print_json=True,
                                            face_detected=(face_bbox is not None),
                                            face_bbox=face_bbox,
                                            plate_number=plate_number,
                                            plate_confidence=plate_confidence,
                                            plate_bbox=plate_bbox,
                                            identified_as=identified_as,
                                            identification_confidence=identification_confidence,
                                            source_video=source_video_tag,
                                        )
                            else:
                                # Transition INSIDE -> OUTSIDE (Confirmed Exit)
                                if tracker_id in active_inside_track_ids:
                                    footfall_out_count += 1
                                    active_inside_track_ids.discard(tracker_id)

                                if tracker_id in pending_zone_entries:
                                    p_ent = pending_zone_entries.pop(tracker_id)
                                    total_intrusion_events += 1
                                    cur_f_bbox = face_recog_cache.get(tracker_id, {}).get("face_bbox") or p_ent.get("face_bbox")
                                    log_event_async(
                                        camera_id=p_ent["camera_id"],
                                        event_type="zone_entry",
                                        object_class=p_ent["object_class"],
                                        track_id=tracker_id,
                                        frame_number=p_ent["trigger_frame"],
                                        bbox=p_ent["bbox"],
                                        confidence=p_ent["confidence"],
                                        frame=p_ent["frame"],
                                        db_path=db_path,
                                        print_json=True,
                                        face_detected=(cur_f_bbox is not None),
                                        face_bbox=cur_f_bbox,
                                        plate_number=p_ent.get("plate_number"),
                                        plate_confidence=p_ent.get("plate_confidence"),
                                        plate_bbox=p_ent.get("plate_bbox"),
                                        identified_as=identified_as,
                                        identification_confidence=identification_confidence,
                                        source_video=p_ent.get("source_video"),
                                    )
                                total_intrusion_events += 1
                                log_event_async(
                                    camera_id=camera_id,
                                    event_type="zone_exit",
                                    object_class=cls_name,
                                    track_id=tracker_id,
                                    frame_number=frame_idx,
                                    bbox=bbox_coords,
                                    confidence=confidence,
                                    frame=frame,
                                    db_path=db_path,
                                    print_json=True,
                                    face_detected=(face_bbox is not None),
                                    face_bbox=face_bbox,
                                    plate_number=plate_number,
                                    plate_confidence=plate_confidence,
                                    plate_bbox=plate_bbox,
                                    identified_as=identified_as,
                                    identification_confidence=identification_confidence,
                                    source_video=source_video_tag,
                                )

                        st["last_frame"] = frame_idx
                        st["bbox"] = bbox_coords
                        st["conf"] = confidence
                        st["face_bbox"] = face_bbox
                        st["plate_number"] = plate_number
                        st["plate_confidence"] = plate_confidence
                        st["plate_bbox"] = plate_bbox
                        st["identified_as"] = identified_as
                        st["identification_confidence"] = identification_confidence

                    is_confirmed_inside = tracked_states[tracker_id]["confirmed_inside"]
                    is_known_auth = (
                        cls_name == "person"
                        and (tracker_id in confirmed_track_identities or (identified_as and identified_as != "UNKNOWN"))
                        and not active_behavior
                    )
                    # Only add to intruder count if not authorized and not currently in grace window
                    if is_confirmed_inside and not is_known_auth and tracker_id not in pending_zone_entries:
                        current_intruders.append((tracker_id, cls_name))

                    track_render_data.append({
                        "tracker_id": tracker_id,
                        "cls_name": cls_name,
                        "confidence": confidence,
                        "bbox": (x1, y1, x2, y2),
                        "is_inside": is_confirmed_inside,
                        "active_behavior": active_behavior,
                        "face_bbox": face_bbox,
                        "identified_as": identified_as,
                        "identification_confidence": identification_confidence,
                        "plate_number": plate_number,
                        "plate_confidence": plate_confidence,
                        "plate_bbox": plate_bbox,
                    })

            # Resolve pending zone entry events with grace window
            for p_tid in list(pending_zone_entries.keys()):
                p_entry = pending_zone_entries[p_tid]
                if p_tid in confirmed_track_identities:
                    # Positive face identification achieved within the grace window!
                    conf_data = confirmed_track_identities[p_tid]
                    print(
                        f"[DEBUG GRACE_WINDOW RESOLVED] Track #{p_tid} face verified within grace window @ Frame {frame_idx}: "
                        f"Name='{conf_data['name']}', Conf={conf_data['confidence']*100:.1f}%, "
                        f"TriggerFrame={p_entry['trigger_frame']} -> Finalized as LOW (Routine Access)"
                    )
                    total_intrusion_events += 1
                    cur_f_bbox = face_recog_cache.get(p_tid, {}).get("face_bbox") or p_entry.get("face_bbox")
                    log_event_async(
                        camera_id=p_entry["camera_id"],
                        event_type="zone_entry",
                        object_class=p_entry["object_class"],
                        track_id=p_tid,
                        frame_number=p_entry["trigger_frame"],
                        bbox=p_entry["bbox"],
                        confidence=p_entry["confidence"],
                        frame=frame,
                        db_path=db_path,
                        print_json=True,
                        face_detected=True,
                        face_bbox=cur_f_bbox,
                        identified_as=conf_data["name"],
                        identification_confidence=conf_data["confidence"],
                        source_video=p_entry.get("source_video"),
                    )
                    del pending_zone_entries[p_tid]
                elif frame_idx >= p_entry["grace_until_frame"]:
                    # Grace window expired without authorized face recognition -> Finalize as HIGH severity (unrecognized intruder)
                    cur_f = face_recog_cache.get(p_tid, {})
                    cur_f_bbox = cur_f.get("face_bbox") or p_entry.get("face_bbox")
                    unrec_id = cur_f.get("identified_as") or ("UNKNOWN" if cur_f_bbox else None)
                    print(
                        f"[DEBUG GRACE_WINDOW EXPIRED] Track #{p_tid} grace window expired @ Frame {frame_idx}: "
                        f"identified_as='{unrec_id}', "
                        f"TriggerFrame={p_entry['trigger_frame']} -> Finalized as HIGH (Intrusion Alert)"
                    )
                    total_intrusion_events += 1
                    log_event_async(
                        camera_id=p_entry["camera_id"],
                        event_type="zone_entry",
                        object_class=p_entry["object_class"],
                        track_id=p_tid,
                        frame_number=p_entry["trigger_frame"],
                        bbox=p_entry["bbox"],
                        confidence=p_entry["confidence"],
                        frame=p_entry["frame"],
                        db_path=db_path,
                        print_json=True,
                        face_detected=(cur_f_bbox is not None),
                        face_bbox=cur_f_bbox,
                        plate_number=p_entry.get("plate_number"),
                        plate_confidence=p_entry.get("plate_confidence"),
                        plate_bbox=p_entry.get("plate_bbox"),
                        identified_as=unrec_id,
                        identification_confidence=cur_f.get("identification_confidence"),
                        source_video=p_entry.get("source_video"),
                    )
                    del pending_zone_entries[p_tid]

            t_zone_end = time.perf_counter()
            dur_zone = (t_zone_end - t2) * 1000.0
            stat_zone.append(dur_zone)

            # Stage 4: Annotation Drawing & HUD Rendering
            t3 = time.perf_counter()
            for obj in track_render_data:
                tracker_id = obj["tracker_id"]
                cls_name = obj["cls_name"]
                confidence = obj["confidence"]
                x1, y1, x2, y2 = obj["bbox"]
                is_confirmed_inside = obj["is_inside"]
                active_behavior = obj.get("active_behavior")
                obj_face_bbox = obj.get("face_bbox")
                # Look up most current confirmed identity from registry
                if tracker_id in confirmed_track_identities:
                    obj_identified_as = confirmed_track_identities[tracker_id]["name"]
                    obj_id_conf = confirmed_track_identities[tracker_id]["confidence"]
                else:
                    obj_identified_as = obj.get("identified_as")
                    obj_id_conf = obj.get("identification_confidence")
                obj_plate_bbox = obj.get("plate_bbox")
                obj_plate_number = obj.get("plate_number")
                obj_plate_conf = obj.get("plate_confidence")

                is_authorized_entry = (
                    is_confirmed_inside
                    and cls_name == "person"
                    and (tracker_id in confirmed_track_identities or (obj_identified_as and obj_identified_as != "UNKNOWN"))
                    and not active_behavior
                )
                is_in_grace = (tracker_id in pending_zone_entries)

                if is_authorized_entry:
                    box_color = (0, 255, 120)  # Bright Green for authorized personnel routine access
                elif is_in_grace:
                    box_color = (255, 200, 0)  # Cyan/Yellow during grace verification window
                elif is_confirmed_inside:
                    box_color = (0, 0, 255)  # Red for unauthorized intrusion
                elif active_behavior:
                    box_color = (0, 140, 255)  # Amber/Orange for suspicious behavior
                elif obj_identified_as and obj_identified_as != "UNKNOWN":
                    box_color = (0, 255, 120)  # Bright Green for verified team identity
                else:
                    box_color = (0, 255, 120)  # Green for normal tracking
                cv2.rectangle(frame, (x1, y1), (x2, y2), box_color, 2)

                # Draw motion trail
                trail_pts = list(track_histories.get(tracker_id, []))
                for t_idx in range(1, len(trail_pts)):
                    t_alpha = t_idx / len(trail_pts)
                    thickness = max(1, int(t_alpha * 3))
                    cv2.line(frame, trail_pts[t_idx - 1], trail_pts[t_idx], box_color, thickness)

                # Draw ID Label Badge
                if is_authorized_entry:
                    status_tag = " [AUTHORIZED ACCESS]"
                elif is_in_grace:
                    status_tag = " [VERIFYING IDENTITY]"
                elif is_confirmed_inside:
                    status_tag = " [INTRUSION]"
                else:
                    status_tag = ""
                behavior_tag = f" [SUSPICIOUS: {active_behavior}]" if active_behavior else ""
                if obj_identified_as and obj_identified_as != "UNKNOWN":
                    id_pct = f" {int(round(float(obj_id_conf)*100))}%" if obj_id_conf else ""
                    face_tag = f" [{obj_identified_as}{id_pct}]"
                elif obj_face_bbox:
                    face_tag = " [FACE: UNKNOWN]"
                else:
                    face_tag = ""
                plate_tag = f" [PLATE: {obj_plate_number}]" if obj_plate_number else ""
                label = f"ID #{tracker_id} {cls_name} {confidence:.2f}{status_tag}{behavior_tag}{face_tag}{plate_tag}"
                (tw, th), baseline = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.48, 1)
                cv2.rectangle(frame, (x1, y1 - th - baseline - 4), (x1 + tw + 4, y1), box_color, -1)
                cv2.putText(
                    frame,
                    label,
                    (x1 + 2, y1 - baseline - 2),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.48,
                    (255, 255, 255) if (is_confirmed_inside and not is_authorized_entry and not is_in_grace or active_behavior) else (0, 0, 0),
                    1,
                    cv2.LINE_AA,
                )

                # Draw Face Recognition Box & Identity Tag
                if obj_face_bbox:
                    fx1, fy1, fx2, fy2 = map(int, obj_face_bbox)
                    if obj_identified_as and obj_identified_as != "UNKNOWN":
                        f_box_color = (0, 255, 120)  # Bright Green
                        id_pct_str = f" {int(round(float(obj_id_conf)*100))}%" if obj_id_conf else ""
                        face_caption = f"ID: {obj_identified_as}{id_pct_str}"
                    else:
                        f_box_color = (212, 182, 6)  # Cyan
                        face_caption = "FACE: UNKNOWN"

                    cv2.rectangle(frame, (fx1, fy1), (fx2, fy2), f_box_color, 2)
                    (ftw, fth), fbase = cv2.getTextSize(face_caption, cv2.FONT_HERSHEY_SIMPLEX, 0.36, 1)
                    cv2.rectangle(frame, (fx1, max(0, fy1 - fth - 4)), (fx1 + ftw + 4, max(fth + 4, fy1)), f_box_color, -1)
                    cv2.putText(
                        frame,
                        face_caption,
                        (fx1 + 2, max(fth + 1, fy1 - 2)),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.36,
                        (0, 0, 0),
                        1,
                        cv2.LINE_AA,
                    )

                # Draw Yellow License Plate Box & Text Label
                if obj_plate_bbox:
                    px1, py1, px2, py2 = map(int, obj_plate_bbox)
                    cv2.rectangle(frame, (px1, py1), (px2, py2), (0, 215, 255), 2)  # Yellow BGR
                    p_badge = f"PLATE: {obj_plate_number}" if obj_plate_number else "PLATE"
                    (ptw, pth), pbase = cv2.getTextSize(p_badge, cv2.FONT_HERSHEY_SIMPLEX, 0.36, 1)
                    cv2.rectangle(frame, (px1, max(0, py1 - pth - 4)), (px1 + ptw + 4, max(pth + 4, py1)), (0, 215, 255), -1)
                    cv2.putText(
                        frame,
                        p_badge,
                        (px1 + 2, max(pth + 1, py1 - 2)),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.36,
                        (0, 0, 0),
                        1,
                        cv2.LINE_AA,
                    )

            # Draw Restricted Zone Polygon Overlay
            is_zone_intruded = (len(current_intruders) > 0) if show_zone else False
            if show_zone:
                draw_restricted_zone(frame, polygon, is_zone_intruded)

            # Collect Hardware Telemetry for HUD
            cpu_metric_str = ""
            ram_metric_str = ""
            if psutil is not None:
                try:
                    cpu_metric_str = f" | CPU: {psutil.cpu_percent():.0f}%"
                    ram_metric_str = f" | RAM: {psutil.virtual_memory().percent:.0f}%"
                except Exception:
                    pass

            # Render Global Defense HUD Header (Dual-Tier Tactical Display)
            hud_bg_color = (0, 0, 60) if is_zone_intruded else (15, 15, 20)
            cv2.rectangle(frame, (0, 0), (width, 54), hud_bg_color, -1)
            cv2.line(frame, (0, 54), (width, 54), (0, 0, 255) if is_zone_intruded else (0, 200, 255), 2)

            if not show_zone:
                intruder_summary = "VIRTUAL FENCE: OFF (FULL SECTOR VIEW)"
            else:
                intruder_summary = (
                    f"INTRUDERS IN SECTOR: {len(current_intruders)}"
                    if is_zone_intruded
                    else "PERIMETER: SECURE"
                )
            hud_tier1 = (
                f"IBVAP | {camera_id} ({resolved_cam_name}) | Frame: {frame_idx:04d} | {current_fps:4.1f} FPS"
                f"{cpu_metric_str}{ram_metric_str} | {intruder_summary}"
            )
            hud_text_color = (0, 100, 255) if is_zone_intruded else (0, 255, 255)
            cv2.putText(
                frame,
                hud_tier1,
                (14, 22),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.48,
                hud_text_color,
                1,
                cv2.LINE_AA,
            )

            # Tier 2: Real-Time Bidirectional Footfall & Sector Occupancy
            cur_occ = len(active_inside_track_ids)
            hud_tier2 = f"FOOTFALL ANALYTICS -> IN: {footfall_in_count} | OUT: {footfall_out_count} | NET INSIDE SECTOR: {cur_occ} | ACTIVE TRACKS: {active_tracks_count}"
            cv2.putText(
                frame,
                hud_tier2,
                (14, 44),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.42,
                (0, 255, 180),
                1,
                cv2.LINE_AA,
            )

            # Draw Compliance, Night Mode & Weather Badges
            right_badge_x = width - 14

            # Weather Mode Badge
            if is_weather_mode_active:
                method_tag = "DCP" if weather_dehaze_method == "dcp" else "FAST"
                w_badge_text = f"[WEATHER: DEHAZE ({method_tag})]"
                (wbw, wbh), wb_base = cv2.getTextSize(w_badge_text, cv2.FONT_HERSHEY_SIMPLEX, 0.38, 1)
                wbx = right_badge_x - wbw
                wby = 7
                cv2.rectangle(frame, (wbx - 4, wby), (wbx + wbw + 4, wby + wbh + 6), (45, 25, 0), -1)
                cv2.rectangle(frame, (wbx - 4, wby), (wbx + wbw + 4, wby + wbh + 6), (255, 190, 40), 1)
                cv2.putText(
                    frame,
                    w_badge_text,
                    (wbx, wby + wbh + 1),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.38,
                    (255, 190, 40),
                    1,
                    cv2.LINE_AA,
                )
                right_badge_x = wbx - 8
            
            # Night Mode Badge
            if is_night_mode_active:
                badge_text = f"[NIGHT: RETINEX-CLAHE (L:{frame_brightness:.0f})]"
                (bw, bh), b_base = cv2.getTextSize(badge_text, cv2.FONT_HERSHEY_SIMPLEX, 0.38, 1)
                bx = right_badge_x - bw
                by = 7
                cv2.rectangle(frame, (bx - 4, by), (bx + bw + 4, by + bh + 6), (0, 60, 0), -1)
                cv2.rectangle(frame, (bx - 4, by), (bx + bw + 4, by + bh + 6), (0, 255, 120), 1)
                cv2.putText(
                    frame,
                    badge_text,
                    (bx, by + bh + 1),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.38,
                    (0, 255, 120),
                    1,
                    cv2.LINE_AA,
                )
                right_badge_x = bx - 8

            # Face Recognition Badge (Consented Demo Watchlist)
            if watchlist_recognizer is not None and watchlist_recognizer.detector is not None:
                wl_size = len(watchlist_recognizer.watchlist_embeddings)
                face_badge_text = f"[FACE RECOG: {wl_size} PROFILES]"
                (fbw, fbh), fb_base = cv2.getTextSize(face_badge_text, cv2.FONT_HERSHEY_SIMPLEX, 0.38, 1)
                fbx = right_badge_x - fbw
                fby = 7
                cv2.rectangle(frame, (fbx - 4, fby), (fbx + fbw + 4, fby + fbh + 6), (0, 45, 20), -1)
                cv2.rectangle(frame, (fbx - 4, fby), (fbx + fbw + 4, fby + fbh + 6), (0, 255, 120), 1)
                cv2.putText(
                    frame,
                    face_badge_text,
                    (fbx, fby + fbh + 1),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.38,
                    (0, 255, 120),
                    1,
                    cv2.LINE_AA,
                )
                right_badge_x = fbx - 8

            # ANPR Plate Engine Badge
            if ocr_reader is not None:
                anpr_badge_text = "[ANPR: ACTIVE]"
                (abw, abh), ab_base = cv2.getTextSize(anpr_badge_text, cv2.FONT_HERSHEY_SIMPLEX, 0.38, 1)
                abx = right_badge_x - abw
                aby = 7
                cv2.rectangle(frame, (abx - 4, aby), (abx + abw + 4, aby + abh + 6), (40, 35, 0), -1)
                cv2.rectangle(frame, (abx - 4, aby), (abx + abw + 4, aby + abh + 6), (0, 215, 255), 1)
                cv2.putText(
                    frame,
                    anpr_badge_text,
                    (abx, aby + abh + 1),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.38,
                    (0, 215, 255),
                    1,
                    cv2.LINE_AA,
                )
                right_badge_x = abx - 8

            t_draw_end = time.perf_counter()
            dur_draw = (t_draw_end - t3) * 1000.0
            stat_draw.append(dur_draw)

            # Stage 5: Fast In-Memory FrameHub Cache & JPEG Buffer Encode
            t4 = time.perf_counter()
            try:
                hub = get_frame_hub()
                if hub is not None:
                    enc_buf = hub.push_ndarray(camera_id=camera_id, frame=frame, frame_idx=frame_idx, quality=72)
                    hub.update_telemetry(
                        camera_id=camera_id,
                        footfall_in=footfall_in_count,
                        footfall_out=footfall_out_count,
                        occupancy=len(active_inside_track_ids),
                        fps=current_fps,
                    )
                else:
                    _, enc = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 72, cv2.IMWRITE_JPEG_OPTIMIZE, 0])
                    enc_buf = enc.tobytes()

                # Write to high-speed OS temp path to bypass OneDrive sync latency & file locks
                fast_frame_path = get_live_frame_path(camera_id)
                fast_tmp_path = fast_frame_path.parent / f".{fast_frame_path.name}.tmp"
                with open(fast_tmp_path, "wb") as f:
                    f.write(enc_buf)
                fast_tmp_path.replace(fast_frame_path)

                # Periodic fallback disk write (every 30 frames) to backend_dir for static tools
                if frame_idx % 30 == 0:
                    try:
                        backend_dir = Path(__file__).resolve().parent.parent
                        live_tmp_path = backend_dir / f".live_frame_{camera_id}.tmp.jpg"
                        live_frame_path = backend_dir / f"live_frame_{camera_id}.jpg"
                        with open(live_tmp_path, "wb") as f:
                            f.write(enc_buf)
                        live_tmp_path.replace(live_frame_path)
                    except Exception:
                        pass

                # Periodic Heartbeat every 30 frames
                if frame_idx % 30 == 0:
                    heartbeat_camera(camera_id=camera_id, fps=current_fps, db_path=db_path)
            except Exception:
                pass
            t_write_end = time.perf_counter()
            dur_write = (t_write_end - t4) * 1000.0
            stat_write.append(dur_write)

            total_frame_dur = (time.perf_counter() - t0) * 1000.0
            stat_total.append(total_frame_dur)

            if total_frame_dur > 0:
                fps_history.append(1000.0 / total_frame_dur)
                current_fps = sum(fps_history) / len(fps_history)

            # Periodic Detailed Timing Summary every 30 frames (excluding cold start frame 1)
            if frame_idx % 30 == 0:
                # Refresh camera heartbeat registry in SQLite
                heartbeat_camera(
                    camera_id=camera_id,
                    name=resolved_cam_name,
                    location=resolved_zone_label,
                    resolution=f"{width}x{height}",
                    fps=round(current_fps, 1),
                    monitored_zone=resolved_zone_label,
                    db_path=db_path,
                )

                avg_grab = sum(stat_grab) / len(stat_grab) if stat_grab else 0.0
                avg_track = sum(stat_track) / len(stat_track) if stat_track else 0.0
                avg_zone = sum(stat_zone) / len(stat_zone) if stat_zone else 0.0
                avg_draw = sum(stat_draw) / len(stat_draw) if stat_draw else 0.0
                avg_write = sum(stat_write) / len(stat_write) if stat_write else 0.0
                avg_total = sum(stat_total) / len(stat_total) if stat_total else (avg_grab + avg_track + avg_zone + avg_draw + avg_write)
                if avg_total <= 0:
                    avg_total = 1.0
                avg_fps = 1000.0 / avg_total

                intruder_desc = ", ".join(
                    [f"ID #{i_id} ({i_cls})" for i_id, i_cls in current_intruders]
                )
                intruder_str = (
                    f"Intruders in Zone -> {intruder_desc}"
                    if intruder_desc
                    else "Restricted Zone Clear"
                )
                print(
                    f"\n[Frame {frame_idx:04d}] Total Pipeline: {avg_fps:4.1f} FPS ({avg_total:5.1f} ms/frame) | Tracks: {active_tracks_count} | {intruder_str}\n"
                    f"    ├── [1] Frame Grab (cap.read) : {avg_grab:5.1f} ms ({avg_grab / avg_total * 100:4.1f}%)\n"
                    f"    ├── [2] YOLOv8 + ByteTrack    : {avg_track:5.1f} ms ({avg_track / avg_total * 100:4.1f}%)\n"
                    f"    ├── [3] Zone & Hysteresis     : {avg_zone:5.1f} ms ({avg_zone / avg_total * 100:4.1f}%)\n"
                    f"    ├── [4] Drawing HUD & Boxes   : {avg_draw:5.1f} ms ({avg_draw / avg_total * 100:4.1f}%)\n"
                    f"    └── [5] JPEG Encode & Write   : {avg_write:5.1f} ms ({avg_write / avg_total * 100:4.1f}%)"
                )

            # Write annotated frame to video output
            if writer:
                writer.write(frame)

            # Check max frames limit
            if max_frames is not None and frame_idx >= max_frames:
                print(f"[*] Reached max frame limit ({max_frames} frames). Terminating.")
                break

            # Live preview window
            if can_display:
                try:
                    cv2.imshow(
                        f"IBVAP - {camera_id} [{source_type_label}]", frame
                    )
                    key = cv2.waitKey(1) & 0xFF
                    if key == ord("q"):
                        print("[*] Stream stopped by user.")
                        break
                except cv2.error:
                    can_display = False

    finally:
        cap.release()
        if writer:
            writer.release()
            print(f"\n[+] Annotated tracking video saved to: {output_path}")
        if can_display:
            try:
                cv2.destroyAllWindows()
            except Exception:
                pass

        # Flush any remaining pending zone entries upon video/stream termination
        for rem_tid, rem_entry in list(pending_zone_entries.items()):
            total_intrusion_events += 1
            if rem_tid in confirmed_track_identities:
                conf_data = confirmed_track_identities[rem_tid]
                log_event_async(
                    camera_id=rem_entry["camera_id"],
                    event_type="zone_entry",
                    object_class=rem_entry["object_class"],
                    track_id=rem_tid,
                    frame_number=rem_entry["trigger_frame"],
                    bbox=rem_entry["bbox"],
                    confidence=rem_entry["confidence"],
                    frame=rem_entry["frame"],
                    db_path=db_path,
                    print_json=True,
                    face_detected=True,
                    face_bbox=rem_entry.get("face_bbox"),
                    identified_as=conf_data["name"],
                    identification_confidence=conf_data["confidence"],
                    source_video=rem_entry.get("source_video"),
                )
            else:
                cur_f = face_recog_cache.get(rem_tid, {})
                cur_f_bbox = cur_f.get("face_bbox") or rem_entry.get("face_bbox")
                log_event_async(
                    camera_id=rem_entry["camera_id"],
                    event_type="zone_entry",
                    object_class=rem_entry["object_class"],
                    track_id=rem_tid,
                    frame_number=rem_entry["trigger_frame"],
                    bbox=rem_entry["bbox"],
                    confidence=rem_entry["confidence"],
                    frame=rem_entry["frame"],
                    db_path=db_path,
                    print_json=True,
                    face_detected=(cur_f_bbox is not None),
                    face_bbox=cur_f_bbox,
                    identified_as=cur_f.get("identified_as") or ("UNKNOWN" if cur_f_bbox else None),
                    identification_confidence=cur_f.get("identification_confidence"),
                    source_video=rem_entry.get("source_video"),
                )
        pending_zone_entries.clear()

    distinct_ids = len(reid_engine.canonical_tracks)
    print(f"\n[+] Tracking & Virtual Fence execution complete. Processed {frame_idx} frames.")
    print(f"    - Distinct Canonical Track IDs Created : {distinct_ids}")
    print(f"    - Re-Identification Events Linked      : {reid_engine.total_reid_events}")
    print(f"    - Total Zone Crossing Alerts Logged    : {total_intrusion_events}\n")

    # Print full contents of the SQLite events table
    print_database_summary(db_path)


def main():
    (
        backend_dir,
        models_dir,
        test_videos_dir,
        default_model,
        tracker_config,
    ) = get_default_paths()

    parser = argparse.ArgumentParser(
        description="IBVAP - Multi-Source ByteTrack Tracking & Virtual Fence Intrusion Detection Engine (Step 6)"
    )
    parser.add_argument(
        "--input",
        "-i",
        type=str,
        default=None,
        help="Input source: Device Index (e.g. 0 for webcam), RTSP URL (rtsp://...), HTTP URL, or video file path",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=str,
        default=None,
        help="Path to save annotated output video (default: backend/test_videos/annotated_tracking.mp4)",
    )
    parser.add_argument(
        "--model",
        "-m",
        type=str,
        default=str(default_model),
        help=f"Path to YOLOv8 weights (default: {default_model})",
    )
    parser.add_argument(
        "--tracker-config",
        "-t",
        type=str,
        default=str(tracker_config),
        help=f"Path to ByteTrack yaml config (default: {tracker_config})",
    )
    parser.add_argument(
        "--camera-id",
        type=str,
        default="CAM_01",
        help="Camera identifier (default: CAM_01)",
    )
    parser.add_argument(
        "--camera-name",
        type=str,
        default=None,
        help="Human-readable camera display name (e.g. 'Sector 4 Gate')",
    )
    parser.add_argument(
        "--zone-label",
        type=str,
        default=None,
        help="Monitored sector or perimeter location label (e.g. 'North Perimeter Fence - Sector 4')",
    )
    parser.add_argument(
        "--conf",
        "-c",
        type=float,
        default=0.35,
        help="YOLO detection confidence threshold for tracking continuity (default: 0.35)",
    )
    parser.add_argument(
        "--alert-conf",
        type=float,
        default=0.45,
        help="Minimum confidence required to trigger restricted zone alerts (default: 0.45)",
    )
    parser.add_argument(
        "--zone-preview",
        action="store_true",
        help="Save first frame with virtual fence polygon overlay to backend/test_videos/zone_preview.jpg for calibration",
    )
    parser.add_argument(
        "--max-frames",
        type=int,
        default=None,
        help="Maximum number of frames to process before terminating (useful for testing live streams/webcams)",
    )
    parser.add_argument(
        "--imgsz",
        type=int,
        default=None,
        help="YOLO inference image dimension (default: 384 for webcam, 640 for high-res video files/RTSP streams)",
    )
    parser.add_argument(
        "--no-display",
        action="store_true",
        help="Disable cv2.imshow GUI display window (headless mode)",
    )
    parser.add_argument(
        "--night-mode",
        action="store_true",
        default=True,
        help="Enable automatic low-light CLAHE enhancement when frame brightness is low (default: True)",
    )
    parser.add_argument(
        "--no-night-mode",
        dest="night_mode",
        action="store_false",
        help="Disable automatic low-light CLAHE enhancement for baseline comparison",
    )
    parser.add_argument(
        "--low-light-thresh",
        type=float,
        default=110.0,
        help="Luminance threshold (0-255) below which night mode CLAHE enhancement is activated (default: 110.0)",
    )
    parser.add_argument(
        "--weather-mode",
        action="store_true",
        default=True,
        help="Enable automatic weather-adaptive fog/haze detection and dehazing (default: True)",
    )
    parser.add_argument(
        "--no-weather-mode",
        dest="weather_mode",
        action="store_false",
        help="Disable automatic weather-adaptive dehazing for baseline comparison",
    )
    parser.add_argument(
        "--weather-dehaze-method",
        type=str,
        choices=["dcp", "fast"],
        default="dcp",
        help="Dehazing algorithm to use: 'dcp' (Dark Channel Prior) or 'fast' (Multi-channel contrast/saturation) (default: dcp)",
    )
    parser.add_argument(
        "--show-zone",
        dest="show_zone",
        action="store_true",
        default=True,
        help="Enable drawing and intrusion alerts for polygon virtual fence (default: True)",
    )
    parser.add_argument(
        "--no-zone",
        dest="show_zone",
        action="store_false",
        help="Disable drawing and intrusion alerts for polygon virtual fence",
    )
    parser.add_argument(
        "--loop",
        action="store_true",
        default=True,
        help="Loop video file continuously for persistent surveillance stream",
    )
    parser.add_argument(
        "--no-loop",
        dest="loop",
        action="store_false",
        help="Disable looping video input",
    )

    args = parser.parse_args()

    # Determine input source type (Integer for webcam, URL, or File path)
    if args.input is not None:
        raw_input = args.input.strip()
        if raw_input.isdigit():
            # Webcam device index
            input_source = int(raw_input)
        elif raw_input.startswith("rtsp://") or raw_input.startswith("http://") or raw_input.startswith("https://"):
            # RTSP/HTTP network camera stream
            input_source = raw_input
        else:
            # File path
            input_source = Path(raw_input)
            if not input_source.exists():
                print(f"[!] Error: Specified video file does not exist: {input_source}")
                sys.exit(1)
    else:
        # Default to tracking_test.mp4 or any available test video
        preferred = test_videos_dir / "tracking_test.mp4"
        if preferred.exists():
            input_source = preferred
        else:
            files = [
                f
                for f in test_videos_dir.glob("*.mp4")
                if "output" not in f.name and "annotated" not in f.name
            ]
            if files:
                input_source = files[0]
            else:
                print(f"[!] Error: No input specified and no video found in {test_videos_dir}")
                print("    Specify an input with: --input 0 (for webcam), --input rtsp://... (for IP camera), or --input path/to/video.mp4")
                sys.exit(1)

    # Resolve inference size: 384 for CPU webcam, 640 for video file/RTSP
    if args.imgsz is not None:
        imgsz = args.imgsz
    else:
        imgsz = 384 if isinstance(input_source, int) else 640

    # Output path handling
    output_path = args.output
    if output_path is None and isinstance(input_source, Path):
        output_path = str(test_videos_dir / f"annotated_{input_source.stem}.mp4")

    run_tracking_and_fence(
        input_source=input_source,
        model_path=Path(args.model),
        tracker_config=Path(args.tracker_config),
        output_path=output_path,
        conf_threshold=args.conf,
        alert_conf_threshold=args.alert_conf,
        show_live=not args.no_display,
        camera_id=args.camera_id,
        camera_name=args.camera_name,
        zone_label=args.zone_label,
        zone_preview=args.zone_preview,
        max_frames=args.max_frames,
        imgsz=imgsz,
        night_mode=args.night_mode,
        low_light_thresh=args.low_light_thresh,
        weather_mode=args.weather_mode,
        weather_dehaze_method=args.weather_dehaze_method,
        loop=args.loop,
        show_zone=args.show_zone,
    )


if __name__ == "__main__":
    main()
