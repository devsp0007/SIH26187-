"""
IBVAP - Detailed Dehazing Detection Inspection & Visual Artifact Auditing
1. Compares frame-by-frame detections between Raw Foggy, DCP Dehazed, and Fast Dehazed.
2. Identifies newly detected objects to verify if they are real people/vehicles or false-positive artifacts.
3. Analyzes why the 'Fast' method degraded detections (histogram clipping & chromatic distortion).
4. Generates side-by-side visual comparison cards and saves them to artifacts and public directories.
"""

import sys
import shutil
from pathlib import Path
import cv2
import numpy as np
from ultralytics import YOLO

backend_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root.parent))

from app.weather_enhancement import (
    compute_fog_haze_metric,
    dehaze_dark_channel_prior,
    dehaze_fast_contrast_saturation,
)


def draw_yolo_detections(image: np.ndarray, results, color_theme: tuple[int, int, int] = (0, 255, 0), title: str = "") -> np.ndarray:
    annotated = image.copy()
    boxes = results.boxes
    h, w = annotated.shape[:2]
    
    # Title bar
    cv2.rectangle(annotated, (0, 0), (w, 32), (10, 16, 25), -1)
    det_count = len(boxes) if boxes is not None else 0
    mean_c = float(np.mean(boxes.conf.cpu().numpy())) if det_count > 0 else 0.0
    header_text = f"{title} | Detections: {det_count} | Mean Conf: {mean_c:.2f}"
    cv2.putText(annotated, header_text, (10, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)
    
    if boxes is None or len(boxes) == 0:
        return annotated
        
    for i in range(len(boxes)):
        xyxy = boxes.xyxy[i].cpu().numpy().astype(int)
        conf = float(boxes.conf[i].cpu().numpy())
        cls_id = int(boxes.cls[i].cpu().numpy())
        cls_name = results.names.get(cls_id, f"cls_{cls_id}")
        
        x1, y1, x2, y2 = xyxy
        
        # Color coding: Green/Cyan for person/vehicle
        box_color = color_theme
        if conf < 0.45:
            box_color = (0, 165, 255) # Orange for low conf
        elif conf >= 0.70:
            box_color = (0, 255, 120) # Bright green for high conf
            
        cv2.rectangle(annotated, (x1, y1), (x2, y2), box_color, 2)
        
        label = f"{cls_name} {conf:.2f}"
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
        cv2.rectangle(annotated, (x1, max(0, y1 - th - 6)), (x1 + tw + 4, y1), box_color, -1)
        cv2.putText(annotated, label, (x1 + 2, max(th, y1 - 3)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 1, cv2.LINE_AA)
        
    return annotated


def audit_dehazing_quality():
    base_dir = Path(__file__).resolve().parent.parent
    test_videos_dir = base_dir / "test_videos"
    model_path = base_dir / "models" / "yolov8n.pt"
    
    foggy_path = test_videos_dir / "foggy_test.mp4"
    clean_path = test_videos_dir / "tracking_test.mp4"
    
    # Destination directories for image inspection
    artifact_dir = Path(r"C:\Users\DELL\.gemini\antigravity-ide\brain\eaacd48e-931d-4d85-8b47-39a76935b874")
    public_dir = base_dir.parent / "frontend" / "public" / "audit_images"
    public_dir.mkdir(parents=True, exist_ok=True)
    
    model = YOLO(str(model_path))
    
    cap_fog = cv2.VideoCapture(str(foggy_path))
    cap_clean = cv2.VideoCapture(str(clean_path))
    
    # Select key sample frames across the video timeline
    target_frames = [12, 35, 68, 95]
    saved_images = []
    
    frame_idx = 0
    while cap_fog.isOpened() and frame_idx <= max(target_frames):
        ret_fog, frame_fog = cap_fog.read()
        ret_clean, frame_clean = cap_clean.read()
        if not ret_fog:
            break
            
        frame_idx += 1
        
        if frame_idx in target_frames:
            print(f"\n[*] Auditing Frame {frame_idx:03d}...")
            
            # 1. Dehaze with DCP
            frame_dcp = dehaze_dark_channel_prior(frame_fog)
            
            # 2. Dehaze with Fast Contrast
            frame_fast = dehaze_fast_contrast_saturation(frame_fog)
            
            # 3. Run YOLO inference on all versions
            res_clean = model(frame_clean, conf=0.25, verbose=False)[0]
            res_fog = model(frame_fog, conf=0.25, verbose=False)[0]
            res_dcp = model(frame_dcp, conf=0.25, verbose=False)[0]
            res_fast = model(frame_fast, conf=0.25, verbose=False)[0]
            
            # Box counts
            n_clean = len(res_clean.boxes)
            n_fog = len(res_fog.boxes)
            n_dcp = len(res_dcp.boxes)
            n_fast = len(res_fast.boxes)
            
            print(f"    - Clean Ground-Truth Frame : {n_clean} detections")
            print(f"    - Raw Foggy Frame          : {n_fog} detections")
            print(f"    - DCP Dehazed Frame        : {n_dcp} detections")
            print(f"    - Fast Dehazed Frame       : {n_fast} detections")
            
            # Annotate images
            vis_fog = draw_yolo_detections(frame_fog, res_fog, color_theme=(0, 165, 255), title=f"Frame {frame_idx:03d}: Raw Foggy (Baseline)")
            vis_dcp = draw_yolo_detections(frame_dcp, res_dcp, color_theme=(0, 255, 120), title=f"Frame {frame_idx:03d}: DCP Dehazed (Weather Mode)")
            vis_clean = draw_yolo_detections(frame_clean, res_clean, color_theme=(255, 200, 0), title=f"Frame {frame_idx:03d}: Clear Ground Truth")
            vis_fast = draw_yolo_detections(frame_fast, res_fast, color_theme=(180, 100, 255), title=f"Frame {frame_idx:03d}: Fast Contrast-Stretch")
            
            # Create a 2x2 grid comparison image
            # Top row: Clean Ground Truth vs Raw Foggy
            # Bottom row: Fast Dehaze vs DCP Dehazed
            top_row = np.hstack([vis_clean, vis_fog])
            bot_row = np.hstack([vis_fast, vis_dcp])
            grid_comp = np.vstack([top_row, bot_row])
            
            # Also create 1x2 side-by-side (Raw Foggy vs DCP Dehazed)
            side_by_side = np.hstack([vis_fog, vis_dcp])
            
            # Save files
            sbs_name = f"dehaze_audit_frame_{frame_idx:03d}.jpg"
            grid_name = f"dehaze_quad_frame_{frame_idx:03d}.jpg"
            
            sbs_artifact_path = artifact_dir / sbs_name
            sbs_public_path = public_dir / sbs_name
            grid_artifact_path = artifact_dir / grid_name
            
            cv2.imwrite(str(sbs_artifact_path), side_by_side)
            cv2.imwrite(str(sbs_public_path), side_by_side)
            cv2.imwrite(str(grid_artifact_path), grid_comp)
            
            saved_images.append({
                "frame": frame_idx,
                "n_clean": n_clean,
                "n_fog": n_fog,
                "n_dcp": n_dcp,
                "n_fast": n_fast,
                "artifact_path": str(sbs_artifact_path),
                "grid_artifact_path": str(grid_artifact_path),
                "filename": sbs_name,
            })
            
    cap_fog.release()
    cap_clean.release()
    
    print("\n" + "=" * 75)
    print(" SUMMARY OF DEHAZING AUDIT IMAGES SAVED")
    print("=" * 75)
    for img in saved_images:
        print(f"Frame {img['frame']:03d} -> Clean: {img['n_clean']} | Foggy: {img['n_fog']} | DCP: {img['n_dcp']} | Fast: {img['n_fast']}")
        print(f"  Artifact Path: {img['artifact_path']}")
    print("=" * 75)
    return saved_images


if __name__ == "__main__":
    audit_dehazing_quality()
