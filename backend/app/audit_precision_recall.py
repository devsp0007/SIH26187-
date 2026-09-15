"""
IBVAP - Ground-Truth IoU Precision/Recall Analysis for Dehazing Auditing
Evaluates every detection on Foggy, DCP, and Fast against Clear Ground-Truth:
- True Positives (IoU >= 0.50 with ground truth object)
- False Positives (detections with no ground truth match, i.e. noise/artifacts)
- False Negatives (missed ground truth objects)
- Precision, Recall, and F1-Score
"""

import sys
from pathlib import Path
import cv2
import numpy as np
from ultralytics import YOLO

backend_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root.parent))

from app.weather_enhancement import dehaze_dark_channel_prior, dehaze_fast_contrast_saturation


def compute_iou(box1, box2):
    """Compute IoU between [x1, y1, x2, y2] and [x1, y1, x2, y2]."""
    xa = max(box1[0], box2[0])
    ya = max(box1[1], box2[1])
    xb = min(box1[2], box2[2])
    yb = min(box1[3], box2[3])
    inter = max(0, xb - xa) * max(0, yb - ya)
    area1 = (box1[2] - box1[0]) * (box1[3] - box1[1])
    area2 = (box2[2] - box2[0]) * (box2[3] - box2[1])
    union = area1 + area2 - inter
    return inter / union if union > 0 else 0.0


def match_boxes(pred_boxes, gt_boxes, iou_thresh=0.45):
    """Match predictions to ground truth boxes."""
    matched_gt = set()
    tp = 0
    fp = 0
    for p in pred_boxes:
        best_iou = 0.0
        best_gt_idx = -1
        for g_idx, g in enumerate(gt_boxes):
            if g_idx in matched_gt:
                continue
            iou = compute_iou(p, g)
            if iou > best_iou:
                best_iou = iou
                best_gt_idx = g_idx
        if best_iou >= iou_thresh:
            tp += 1
            matched_gt.add(best_gt_idx)
        else:
            fp += 1
    fn = len(gt_boxes) - len(matched_gt)
    return tp, fp, fn


def run_precision_recall_audit():
    base_dir = Path(__file__).resolve().parent.parent
    test_videos_dir = base_dir / "test_videos"
    model_path = base_dir / "models" / "yolov8n.pt"
    
    foggy_path = test_videos_dir / "foggy_test.mp4"
    clean_path = test_videos_dir / "tracking_test.mp4"
    
    model = YOLO(str(model_path))
    
    cap_fog = cv2.VideoCapture(str(foggy_path))
    cap_clean = cv2.VideoCapture(str(clean_path))
    
    stats = {
        "fog": {"tp": 0, "fp": 0, "fn": 0, "total_gt": 0, "confs_tp": [], "confs_fp": []},
        "dcp": {"tp": 0, "fp": 0, "fn": 0, "total_gt": 0, "confs_tp": [], "confs_fp": []},
        "fast": {"tp": 0, "fp": 0, "fn": 0, "total_gt": 0, "confs_tp": [], "confs_fp": []},
    }
    
    frame_idx = 0
    max_frames = 100
    
    while cap_fog.isOpened() and frame_idx < max_frames:
        ret_fog, frame_fog = cap_fog.read()
        ret_clean, frame_clean = cap_clean.read()
        if not ret_fog or not ret_clean:
            break
            
        frame_idx += 1
        
        # Ground truth detections on clean frame
        res_clean = model(frame_clean, conf=0.25, verbose=False)[0]
        gt_boxes = res_clean.boxes.xyxy.cpu().numpy().tolist() if len(res_clean.boxes) > 0 else []
        
        # 1. Raw Foggy
        res_fog = model(frame_fog, conf=0.25, verbose=False)[0]
        pred_fog = res_fog.boxes.xyxy.cpu().numpy().tolist() if len(res_fog.boxes) > 0 else []
        tp_fog, fp_fog, fn_fog = match_boxes(pred_fog, gt_boxes)
        stats["fog"]["tp"] += tp_fog
        stats["fog"]["fp"] += fp_fog
        stats["fog"]["fn"] += fn_fog
        stats["fog"]["total_gt"] += len(gt_boxes)
        
        # 2. DCP Dehazed
        frame_dcp = dehaze_dark_channel_prior(frame_fog)
        res_dcp = model(frame_dcp, conf=0.25, verbose=False)[0]
        pred_dcp = res_dcp.boxes.xyxy.cpu().numpy().tolist() if len(res_dcp.boxes) > 0 else []
        tp_dcp, fp_dcp, fn_dcp = match_boxes(pred_dcp, gt_boxes)
        stats["dcp"]["tp"] += tp_dcp
        stats["dcp"]["fp"] += fp_dcp
        stats["dcp"]["fn"] += fn_dcp
        stats["dcp"]["total_gt"] += len(gt_boxes)
        
        # 3. Fast Dehazed
        frame_fast = dehaze_fast_contrast_saturation(frame_fog)
        res_fast = model(frame_fast, conf=0.25, verbose=False)[0]
        pred_fast = res_fast.boxes.xyxy.cpu().numpy().tolist() if len(res_fast.boxes) > 0 else []
        tp_fast, fp_fast, fn_fast = match_boxes(pred_fast, gt_boxes)
        stats["fast"]["tp"] += tp_fast
        stats["fast"]["fp"] += fp_fast
        stats["fast"]["fn"] += fn_fast
        stats["fast"]["total_gt"] += len(gt_boxes)
        
    cap_fog.release()
    cap_clean.release()
    
    print("\n" + "=" * 80)
    print(" GROUND TRUTH PRECISION & RECALL AUDIT REPORT (100 Frames)")
    print(" Evaluating True Targets vs False Positive Artifacts against Clear Footage")
    print("=" * 80)
    
    for method, label in [("fog", "1. Raw Foggy (No Weather Mode)"), ("dcp", "2. DCP Dehazed (Weather Mode)"), ("fast", "3. Fast Dehazed (Contrast-Stretch)")]:
        s = stats[method]
        tp, fp, fn = s["tp"], s["fp"], s["fn"]
        total_pred = tp + fp
        precision = tp / total_pred if total_pred > 0 else 0.0
        recall = tp / s["total_gt"] if s["total_gt"] > 0 else 0.0
        f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
        
        print(f"\n{label}:")
        print(f"  - Total Predictions   : {total_pred}")
        print(f"  - True Positives (TP) : {tp}  (Real people/vehicles confirmed in ground truth)")
        print(f"  - False Positives (FP): {fp}  (Artifacts / hallucinated boxes)")
        print(f"  - False Negatives (FN): {fn}  (Missed real people)")
        print(f"  - Precision           : {precision * 100:.1f}%")
        print(f"  - Recall              : {recall * 100:.1f}%")
        print(f"  - F1-Score            : {f1 * 100:.1f}%")
        
    print("=" * 80)


if __name__ == "__main__":
    run_precision_recall_audit()
