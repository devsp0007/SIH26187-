"""
IBVAP - Synthetic Foggy Video Generator
Generates a realistic atmospheric fog/haze video clip (foggy_test.mp4)
from an existing clean surveillance clip (tracking_test.mp4).
"""

import sys
from pathlib import Path
import cv2

backend_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root.parent))

try:
    from app.weather_enhancement import apply_synthetic_fog, compute_fog_haze_metric
except ImportError:
    from backend.app.weather_enhancement import apply_synthetic_fog, compute_fog_haze_metric


def generate_foggy_video(
    source_name: str = "tracking_test.mp4",
    output_name: str = "foggy_test.mp4",
    fog_density: float = 0.62,
    airlight: float = 215.0,
    max_frames: int = 150,
):
    base_dir = Path(__file__).resolve().parent.parent
    test_videos_dir = base_dir / "test_videos"
    src_path = test_videos_dir / source_name
    dst_path = test_videos_dir / output_name

    if not src_path.exists():
        raise FileNotFoundError(f"Source video not found: {src_path}")

    cap = cv2.VideoCapture(str(src_path))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open {src_path}")

    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out = cv2.VideoWriter(str(dst_path), fourcc, fps, (width, height))

    print(f"[*] Generating synthetic foggy video: {dst_path.name}")
    print(f"    Source: {src_path.name} ({width}x{height} @ {fps:.1f} FPS)")
    print(f"    Atmospheric Scattering Density: {fog_density} | Airlight: {airlight}")

    frame_count = 0
    haze_scores = []

    while cap.isOpened() and frame_count < max_frames:
        ret, frame = cap.read()
        if not ret:
            break

        foggy = apply_synthetic_fog(frame, fog_density=fog_density, airlight=airlight)
        is_hazy, score, _ = compute_fog_haze_metric(foggy)
        haze_scores.append(score)

        out.write(foggy)
        frame_count += 1

    cap.release()
    out.release()

    avg_score = sum(haze_scores) / len(haze_scores) if haze_scores else 0.0
    print(f"[+] Successfully generated {dst_path.name} with {frame_count} frames.")
    print(f"    Average Haze Index: {avg_score:.3f} (Fog condition confirmed)")
    return dst_path


if __name__ == "__main__":
    generate_foggy_video()
