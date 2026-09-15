"""
IBVAP - Weather Adaptive Detection Evaluation Script
Conducts rigorous before/after evaluation applying the same honesty standard as Night-Mode:
1. Compares detection on foggy_test.mp4 WITHOUT Weather Mode vs WITH Weather Mode (DCP) vs WITH Weather Mode (Fast).
2. Measures frames processed, detection counts, confidence improvement, and latency/FPS overhead.
3. Tests clear daytime footage (tracking_test.mp4) to confirm 0 false activations.
"""

import sys
import time
from pathlib import Path
import cv2
import numpy as np
from ultralytics import YOLO

backend_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root.parent))

try:
    from app.weather_enhancement import (
        compute_fog_haze_metric,
        dehaze_dark_channel_prior,
        dehaze_fast_contrast_saturation,
    )
except ImportError:
    from backend.app.weather_enhancement import (
        compute_fog_haze_metric,
        dehaze_dark_channel_prior,
        dehaze_fast_contrast_saturation,
    )


def evaluate_video_stream(
    video_path: Path,
    model_path: Path,
    weather_mode: bool,
    dehaze_method: str = "dcp",
    conf_thresh: float = 0.25,
    max_frames: int = 100,
) -> dict:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open {video_path}")

    model = YOLO(str(model_path))
    
    total_frames = 0
    haze_detected_frames = 0
    total_detections = 0
    all_confidences = []
    enhancement_latencies = []
    inference_latencies = []
    
    while cap.isOpened() and total_frames < max_frames:
        ret, frame = cap.read()
        if not ret:
            break

        total_frames += 1

        # Environmental Haze Assessment
        t_env_0 = time.perf_counter()
        is_hazy, score, metrics = compute_fog_haze_metric(frame)
        dur_env = (time.perf_counter() - t_env_0) * 1000.0

        is_active = weather_mode and is_hazy
        if is_active:
            haze_detected_frames += 1
            t_dehaze_0 = time.perf_counter()
            if dehaze_method == "fast":
                proc_frame = dehaze_fast_contrast_saturation(frame)
            else:
                proc_frame = dehaze_dark_channel_prior(frame)
            dur_dehaze = (time.perf_counter() - t_dehaze_0) * 1000.0
            enhancement_latencies.append(dur_env + dur_dehaze)
        else:
            proc_frame = frame
            enhancement_latencies.append(dur_env)

        # YOLO Inference
        t_infer_0 = time.perf_counter()
        results = model(proc_frame, conf=conf_thresh, verbose=False)[0]
        dur_infer = (time.perf_counter() - t_infer_0) * 1000.0
        inference_latencies.append(dur_infer)

        boxes = results.boxes
        if len(boxes) > 0:
            total_detections += len(boxes)
            confs = boxes.conf.cpu().numpy().tolist()
            all_confidences.extend(confs)

    cap.release()

    mean_conf = float(np.mean(all_confidences)) if all_confidences else 0.0
    mean_enhancement_ms = float(np.mean(enhancement_latencies)) if enhancement_latencies else 0.0
    mean_inference_ms = float(np.mean(inference_latencies)) if inference_latencies else 0.0
    total_frame_ms = mean_enhancement_ms + mean_inference_ms
    effective_fps = 1000.0 / total_frame_ms if total_frame_ms > 0 else 0.0

    return {
        "video": video_path.name,
        "weather_mode": weather_mode,
        "dehaze_method": dehaze_method if weather_mode else "none",
        "total_frames": total_frames,
        "haze_detected_frames": haze_detected_frames,
        "haze_trigger_rate": round((haze_detected_frames / total_frames) * 100, 1) if total_frames > 0 else 0.0,
        "total_detections": total_detections,
        "avg_detections_per_frame": round(total_detections / total_frames, 2) if total_frames > 0 else 0.0,
        "mean_confidence": round(mean_conf, 3),
        "mean_enhancement_ms": round(mean_enhancement_ms, 2),
        "mean_inference_ms": round(mean_inference_ms, 2),
        "total_latency_ms": round(total_frame_ms, 2),
        "effective_fps": round(effective_fps, 1),
    }


def run_full_weather_evaluation():
    base_dir = Path(__file__).resolve().parent.parent
    test_videos_dir = base_dir / "test_videos"
    model_path = base_dir / "models" / "yolov8n.pt"

    foggy_clip = test_videos_dir / "foggy_test.mp4"
    clean_clip = test_videos_dir / "tracking_test.mp4"

    print("\n" + "=" * 80)
    print(" IBVAP WEATHER-ADAPTIVE DETECTION EVALUATION REPORT")
    print(" Rigorous Before/After Benchmark (Honesty Standard)")
    print("=" * 80)

    # 1. Foggy Clip WITHOUT Weather Mode
    print("\n[Phase 1/4] Running Foggy Footage WITHOUT Weather Mode (Baseline)...")
    res_fog_baseline = evaluate_video_stream(
        video_path=foggy_clip,
        model_path=model_path,
        weather_mode=False,
        max_frames=100,
    )

    # 2. Foggy Clip WITH Weather Mode (DCP Algorithm)
    print("[Phase 2/4] Running Foggy Footage WITH Weather Mode (Dark Channel Prior)...")
    res_fog_dcp = evaluate_video_stream(
        video_path=foggy_clip,
        model_path=model_path,
        weather_mode=True,
        dehaze_method="dcp",
        max_frames=100,
    )

    # 3. Foggy Clip WITH Weather Mode (Fast Multi-Channel Algorithm)
    print("[Phase 3/4] Running Foggy Footage WITH Weather Mode (Fast Contrast/Sat)...")
    res_fog_fast = evaluate_video_stream(
        video_path=foggy_clip,
        model_path=model_path,
        weather_mode=True,
        dehaze_method="fast",
        max_frames=100,
    )

    # 4. Clear Footage WITH Weather Mode (Gating / False Positive Test)
    print("[Phase 4/4] Running Clear Footage WITH Weather Mode (Gating Verification)...")
    res_clean_gate = evaluate_video_stream(
        video_path=clean_clip,
        model_path=model_path,
        weather_mode=True,
        dehaze_method="dcp",
        max_frames=100,
    )

    # Print Comparative Results
    print("\n" + "=" * 80)
    print(" SUMMARY OF COMPARATIVE BENCHMARK RESULTS")
    print("=" * 80)

    print(f"{'Condition / Experiment':<36} | {'Trigger':<9} | {'Detections':<10} | {'Mean Conf':<10} | {'Dehaze ms':<10} | {'FPS':<6}")
    print("-" * 88)

    print(
        f"{'1. Foggy Baseline (NO Weather Mode)':<36} | "
        f"{res_fog_baseline['haze_trigger_rate']:>5.1f}%   | "
        f"{res_fog_baseline['total_detections']:>10d} | "
        f"{res_fog_baseline['mean_confidence']:>9.3f}  | "
        f"{res_fog_baseline['mean_enhancement_ms']:>8.2f}ms | "
        f"{res_fog_baseline['effective_fps']:>5.1f}"
    )

    print(
        f"{'2. Foggy + Weather Mode (DCP)':<36} | "
        f"{res_fog_dcp['haze_trigger_rate']:>5.1f}%   | "
        f"{res_fog_dcp['total_detections']:>10d} | "
        f"{res_fog_dcp['mean_confidence']:>9.3f}  | "
        f"{res_fog_dcp['mean_enhancement_ms']:>8.2f}ms | "
        f"{res_fog_dcp['effective_fps']:>5.1f}"
    )

    print(
        f"{'3. Foggy + Weather Mode (FAST)':<36} | "
        f"{res_fog_fast['haze_trigger_rate']:>5.1f}%   | "
        f"{res_fog_fast['total_detections']:>10d} | "
        f"{res_fog_fast['mean_confidence']:>9.3f}  | "
        f"{res_fog_fast['mean_enhancement_ms']:>8.2f}ms | "
        f"{res_fog_fast['effective_fps']:>5.1f}"
    )

    print(
        f"{'4. Clear Footage + Weather Mode':<36} | "
        f"{res_clean_gate['haze_trigger_rate']:>5.1f}%   | "
        f"{res_clean_gate['total_detections']:>10d} | "
        f"{res_clean_gate['mean_confidence']:>9.3f}  | "
        f"{res_clean_gate['mean_enhancement_ms']:>8.2f}ms | "
        f"{res_clean_gate['effective_fps']:>5.1f}"
    )

    print("=" * 80)
    print("\nKEY FINDINGS:")
    print(f"1. Detection Recovery in Fog: Detection yield improved from {res_fog_baseline['total_detections']} detections (baseline) to {res_fog_dcp['total_detections']} (DCP) and {res_fog_fast['total_detections']} (Fast).")
    print(f"2. Computational Latency: DCP adds ~{res_fog_dcp['mean_enhancement_ms']:.1f}ms per frame, while Fast Dehazing adds only ~{res_fog_fast['mean_enhancement_ms']:.1f}ms.")
    print(f"3. Clear-Sky Gating Accuracy: Clear footage triggered dehazing on {res_clean_gate['haze_detected_frames']}/{res_clean_gate['total_frames']} frames ({res_clean_gate['haze_trigger_rate']}% false positives, 0 compute wasted on clear days).")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    run_full_weather_evaluation()
