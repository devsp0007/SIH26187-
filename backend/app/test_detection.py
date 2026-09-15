"""
IBVAP - Intelligent Border Video Analytics Platform
Step 1: YOLOv8 Detection Verification Script

Features:
- Loads YOLOv8n model from backend/models/
- Filters target classes: person and border-relevant vehicles (car, motorcycle, bus, truck)
- Draws bounding boxes, labels, and confidence scores
- Logs frame-by-frame detection counts to console every 30 frames
- Live display with 'q' to exit AND/OR video export to file
"""

import argparse
import os
import sys
from pathlib import Path
import cv2
from ultralytics import YOLO

# Target classes to detect and monitor
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

# Color palette for classes (BGR)
CLASS_COLORS = {
    "person": (0, 0, 255),       # Red for human activity
    "car": (255, 128, 0),        # Cyan/Blue
    "motorcycle": (0, 255, 255),  # Yellow
    "bus": (255, 0, 255),        # Magenta
    "truck": (0, 165, 255),      # Orange
    "bicycle": (0, 255, 0),      # Green
}


def get_default_paths():
    """Resolve base directory paths relative to this script."""
    app_dir = Path(__file__).resolve().parent
    backend_dir = app_dir.parent
    models_dir = backend_dir / "models"
    test_videos_dir = backend_dir / "test_videos"

    models_dir.mkdir(parents=True, exist_ok=True)
    test_videos_dir.mkdir(parents=True, exist_ok=True)

    default_model_path = models_dir / "yolov8n.pt"
    return backend_dir, models_dir, test_videos_dir, default_model_path


def load_yolo_model(model_path: Path) -> YOLO:
    """Load or download YOLOv8 model weights."""
    print(f"[*] Loading YOLOv8 model from: {model_path}")
    if not model_path.exists():
        print(f"[*] Pretrained weights not found locally. Downloading YOLOv8n to {model_path}...")
        model = YOLO("yolov8n.pt")
        # Save or move weights to designated models directory
        try:
            model.save(str(model_path))
        except Exception:
            pass
    else:
        model = YOLO(str(model_path))
    print("[+] YOLOv8 model successfully loaded.")
    return model


def find_sample_video(test_videos_dir: Path) -> Path | None:
    """Look for any video file in the test_videos folder."""
    video_extensions = [".mp4", ".avi", ".mov", ".mkv", ".webm"]
    for ext in video_extensions:
        files = list(test_videos_dir.glob(f"*{ext}"))
        if files:
            # Prefer files that are not previous output files
            non_output = [f for f in files if "output" not in f.name.lower()]
            return non_output[0] if non_output else files[0]
    return None


def run_detection(
    video_path: str,
    model_path: Path,
    output_path: str | None = None,
    conf_threshold: float = 0.35,
    show_live: bool = True,
):
    """Run YOLOv8 inference loop on video."""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"[!] Error: Could not open input video source: {video_path}")
        sys.exit(1)

    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    print("\n========================================================")
    print(" IBVAP - Video Detection Engine (YOLOv8 Verification)")
    print("========================================================")
    print(f" Input Video   : {video_path}")
    print(f" Resolution    : {width} x {height}")
    print(f" FPS           : {fps:.2f}")
    print(f" Total Frames  : {total_frames if total_frames > 0 else 'Stream/Unknown'}")
    print(f" Monitored     : {', '.join(TARGET_CLASS_NAMES)}")
    print(f" Min Confidence: {conf_threshold}")
    if output_path:
        print(f" Save Output To: {output_path}")
    print("========================================================\n")

    # Initialize video writer if output path is requested
    writer = None
    if output_path:
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(output_path, fourcc, fps, (width, height))

    model = load_yolo_model(model_path)

    frame_idx = 0
    can_display = show_live

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            frame_idx += 1

            # Run inference with target class filter
            results = model.predict(
                source=frame,
                classes=TARGET_CLASS_IDS,
                conf=conf_threshold,
                verbose=False,
            )

            # Extract detections
            detections = results[0].boxes
            class_counts = {name: 0 for name in TARGET_CLASS_NAMES}

            if detections is not None and len(detections) > 0:
                for box in detections:
                    cls_id = int(box.cls[0].item())
                    conf = float(box.conf[0].item())
                    x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())

                    cls_name = model.names.get(cls_id, f"cls_{cls_id}")
                    if cls_name in class_counts:
                        class_counts[cls_name] += 1

                    # Drawing annotations
                    color = CLASS_COLORS.get(cls_name, (0, 255, 0))
                    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)

                    label = f"{cls_name} {conf:.2f}"
                    (tw, th), baseline = cv2.getTextSize(
                        label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1
                    )
                    cv2.rectangle(
                        frame,
                        (x1, y1 - th - baseline - 4),
                        (x1 + tw + 4, y1),
                        color,
                        -1,
                    )
                    cv2.putText(
                        frame,
                        label,
                        (x1 + 2, y1 - baseline - 2),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.5,
                        (0, 0, 0) if color == (0, 255, 255) else (255, 255, 255),
                        1,
                        cv2.LINE_AA,
                    )

            # Render HUD banner on frame
            person_count = class_counts["person"]
            vehicle_count = sum(
                class_counts[k]
                for k in ["car", "truck", "motorcycle", "bus", "bicycle"]
                if k in class_counts
            )
            hud_text = (
                f"IBVAP | Frame: {frame_idx} | Persons: {person_count} | Vehicles: {vehicle_count}"
            )
            cv2.rectangle(frame, (10, 10), (550, 42), (20, 20, 20), -1)
            cv2.rectangle(frame, (10, 10), (550, 42), (0, 200, 255), 1)
            cv2.putText(
                frame,
                hud_text,
                (20, 32),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (0, 255, 255),
                2,
                cv2.LINE_AA,
            )

            # Log summary to console every 30 frames
            if frame_idx % 30 == 0 or frame_idx == 1:
                active_classes = [
                    f"{count} {cls_name}{'s' if count != 1 else ''}"
                    for cls_name, count in class_counts.items()
                    if count > 0
                ]
                summary = ", ".join(active_classes) if active_classes else "No targets detected"
                print(f"[Frame {frame_idx:04d}] Detections -> {summary}")

            # Write frame to output video file
            if writer:
                writer.write(frame)

            # Live preview window (if enabled and GUI supported)
            if can_display:
                try:
                    cv2.imshow("IBVAP - Live Detection Stream (Press 'q' to quit)", frame)
                    key = cv2.waitKey(1) & 0xFF
                    if key == ord("q"):
                        print("[*] Playback interrupted by user.")
                        break
                except cv2.error:
                    # Headless or missing display driver fallback
                    can_display = False

    finally:
        cap.release()
        if writer:
            writer.release()
            print(f"\n[+] Annotated output video saved successfully to: {output_path}")
        if can_display:
            try:
                cv2.destroyAllWindows()
            except Exception:
                pass

    print(f"\n[+] Verification completed! Processed {frame_idx} frames successfully.")


def main():
    backend_dir, models_dir, test_videos_dir, default_model = get_default_paths()

    parser = argparse.ArgumentParser(
        description="IBVAP - YOLOv8 Video Detection Verification (Step 1)"
    )
    parser.add_argument(
        "--input",
        "-i",
        type=str,
        default=None,
        help="Path to input video file (e.g. backend/test_videos/sample.mp4)",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=str,
        default=None,
        help="Optional path to save annotated output video (e.g. backend/test_videos/output.mp4)",
    )
    parser.add_argument(
        "--model",
        "-m",
        type=str,
        default=str(default_model),
        help=f"Path to YOLOv8 weights (default: {default_model})",
    )
    parser.add_argument(
        "--conf",
        "-c",
        type=float,
        default=0.35,
        help="Confidence threshold for detections (default: 0.35)",
    )
    parser.add_argument(
        "--no-display",
        action="store_true",
        help="Disable live cv2.imshow GUI display window (headless mode)",
    )

    args = parser.parse_args()

    # Determine input video
    if args.input:
        input_video_path = Path(args.input)
    else:
        sample_found = find_sample_video(test_videos_dir)
        if sample_found:
            input_video_path = sample_found
            print(f"[*] No input specified. Found sample video: {input_video_path}")
        else:
            print("[!] Error: No video specified and none found in backend/test_videos/")
            print(f"    Please place a sample video into: {test_videos_dir}")
            print("    Or specify with: python test_detection.py --input <path_to_video>")
            sys.exit(1)

    if not input_video_path.exists():
        print(f"[!] Error: Specified video file does not exist: {input_video_path}")
        sys.exit(1)

    # Set default output path if not provided
    output_path = args.output
    if output_path is None:
        output_path = str(test_videos_dir / f"annotated_{input_video_path.stem}.mp4")

    run_detection(
        video_path=str(input_video_path),
        model_path=Path(args.model),
        output_path=output_path,
        conf_threshold=args.conf,
        show_live=not args.no_display,
    )


if __name__ == "__main__":
    main()
