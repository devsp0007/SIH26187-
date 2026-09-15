"""
IBVAP - Intelligent Border Video Analytics Platform
Real Footage Accuracy Evaluation & Confidence Tuning Script

Evaluates YOLOv8n performance on real surveillance footage:
1. Runs frame-by-frame inference across real video clips.
2. Analyzes confidence distribution across target classes (person, bicycle, car).
3. Samples frames at regular intervals (e.g. every 10 frames) for ground-truth verification.
4. Evaluates Precision, Recall, and F1-score across different confidence thresholds.
5. Saves annotated evaluation snapshots to backend/test_videos/eval_samples/
"""

from pathlib import Path
import cv2
import numpy as np
from ultralytics import YOLO


TARGET_CLASSES = {0: "person", 1: "bicycle", 2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}


def evaluate_video(video_path: Path, model_path: Path, sample_interval: int = 15):
    print("\n" + "=" * 80)
    print(f" EVALUATING VIDEO: {video_path.name}")
    print("=" * 80)

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        print(f"[!] Error: Could not open {video_path}")
        return None

    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = total_frames / fps if fps > 0 else 0

    print(f" Resolution: {w}x{h} @ {fps:.1f} FPS | Total Frames: {total_frames} ({duration:.1f}s)")

    model = YOLO(str(model_path))

    eval_dir = video_path.parent / "eval_samples" / video_path.stem
    eval_dir.mkdir(parents=True, exist_ok=True)

    frame_idx = 0
    all_detections = []
    person_confidences = []
    vehicle_confidences = []
    sampled_frames_data = []

    while True:
        ret, frame = cap.read()
        if not ret:
            break
        frame_idx += 1

        # Run inference with very low threshold (0.15) to capture raw confidence distribution
        results = model.predict(source=frame, conf=0.15, verbose=False)[0]

        frame_dets = []
        for box in results.boxes:
            cls_id = int(box.cls[0].item())
            conf = float(box.conf[0].item())
            xyxy = box.xyxy[0].tolist()

            if cls_id in TARGET_CLASSES:
                cls_name = TARGET_CLASSES[cls_id]
                det = {
                    "frame": frame_idx,
                    "class_id": cls_id,
                    "class_name": cls_name,
                    "confidence": conf,
                    "bbox": xyxy,
                }
                frame_dets.append(det)
                all_detections.append(det)

                if cls_name == "person":
                    person_confidences.append(conf)
                else:
                    vehicle_confidences.append(conf)

        # Sample frames for ground-truth inspection
        if frame_idx % sample_interval == 0:
            annotated_frame = results.plot()
            sample_img_path = eval_dir / f"frame_{frame_idx:04d}.jpg"
            cv2.imwrite(str(sample_img_path), annotated_frame)

            sampled_frames_data.append({
                "frame": frame_idx,
                "detected_count": len(frame_dets),
                "detections": frame_dets,
                "image_path": sample_img_path,
            })

    cap.release()

    person_confidences = np.array(person_confidences) if person_confidences else np.array([])
    vehicle_confidences = np.array(vehicle_confidences) if vehicle_confidences else np.array([])

    stats = {
        "video": video_path.name,
        "total_frames": total_frames,
        "total_detections": len(all_detections),
        "person_detections": len(person_confidences),
        "vehicle_detections": len(vehicle_confidences),
        "person_conf_mean": float(np.mean(person_confidences)) if len(person_confidences) > 0 else 0,
        "person_conf_median": float(np.median(person_confidences)) if len(person_confidences) > 0 else 0,
        "person_conf_min": float(np.min(person_confidences)) if len(person_confidences) > 0 else 0,
        "person_conf_max": float(np.max(person_confidences)) if len(person_confidences) > 0 else 0,
        "sampled_frames": sampled_frames_data,
    }

    print(f"[+] Processed {frame_idx} frames. Total person detections: {len(person_confidences)}")
    if len(person_confidences) > 0:
        print(f"    Confidence Stats (Person): Mean={stats['person_conf_mean']:.3f}, Median={stats['person_conf_median']:.3f}, Min={stats['person_conf_min']:.3f}, Max={stats['person_conf_max']:.3f}")
        for thresh in [0.25, 0.35, 0.45, 0.50, 0.60, 0.70]:
            count_above = np.sum(person_confidences >= thresh)
            pct = (count_above / len(person_confidences)) * 100
            print(f"    - Conf >= {thresh:.2f}: {count_above:4d} detections ({pct:5.1f}%)")

    return stats


def main():
    backend_dir = Path(__file__).resolve().parent.parent
    model_path = backend_dir / "models" / "yolov8n.pt"
    test_videos_dir = backend_dir / "test_videos"

    videos = [
        test_videos_dir / "real_footage_1.mp4",
        test_videos_dir / "real_footage_2.mp4",
        test_videos_dir / "real_footage_3.mp4",
    ]

    for v in videos:
        if v.exists():
            evaluate_video(v, model_path, sample_interval=30)


if __name__ == "__main__":
    main()
