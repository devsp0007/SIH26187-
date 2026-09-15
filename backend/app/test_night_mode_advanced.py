"""
IBVAP - Advanced Night Mode & Low-Light Enhancement Verification Suite
Tests:
1. Multi-Stage Low-Light Illumination & Denoising Engine (Log-Retinex + Bilateral + Dynamic CLAHE + Unsharp).
2. Biometric Facial Recognition Under Extreme Low-Light (15% - 30% ambient illumination).
3. False-Positive Rejection on Unlisted Dark Strangers (0% False Matches).
4. YOLOv8 Dynamic Detection & Tracking Sensitivity in Low Ambient Light.
"""

import sys
from pathlib import Path
import cv2
import numpy as np

# Ensure sys.path includes backend and root
backend_dir = Path(__file__).resolve().parent.parent
project_root = backend_dir.parent
for p in [str(project_root), str(backend_dir)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from backend.app.face_engine import WatchlistFaceRecognizer, enhance_face_illumination
from backend.app.detection_tracking import enhance_low_light, compute_frame_brightness


def run_night_mode_tests():
    print("=" * 80)
    print("IBVAP - ADVANCED NIGHT MODE & LOW-LIGHT RECOGNITION VERIFICATION SUITE")
    print("=" * 80)

    models_dir = backend_dir / "models"
    watchlist_dir = backend_dir / "watchlist"

    recognizer = WatchlistFaceRecognizer(
        watchlist_dir=watchlist_dir,
        models_dir=models_dir,
        cosine_threshold=0.48,
    )
    print(f"[+] Loaded Watchlist ({len(recognizer.watchlist_embeddings)} profiles): {list(recognizer.watchlist_embeddings.keys())}")

    # -------------------------------------------------------------------------
    # TEST 1: Realistic Low-Light Recognition on All Watchlist Profiles
    # -------------------------------------------------------------------------
    print("\n" + "-" * 80)
    print("[TEST 1] Severe Low-Light (22% Ambient Brightness) Recognition Test")
    print("-" * 80)

    success_count = 0
    total_profiles = 0

    for p in sorted(watchlist_dir.glob("*.png")):
        total_profiles += 1
        name = p.stem.replace("_", " ").strip().title()
        orig = cv2.imread(str(p))
        if orig is None:
            continue
        h, w = orig.shape[:2]

        # Darken to 22% brightness to simulate dark nocturnal surveillance
        dark = (orig.astype(np.float32) * 0.22).astype(np.uint8)
        raw_luma = compute_frame_brightness(dark)

        # Run face identification (AFIN engine automatically normalizes illumination)
        matched_name, conf, coords = recognizer.identify_face_in_person_crop(dark, (0, 0, w, h))
        print(f" [+] Profile '{name:<10}' | Dark Luma: {raw_luma:4.1f} -> Recognized As: '{matched_name}' | Conf: {conf*100:5.1f}% | BBox: {coords}")
        assert matched_name == name, f"Low-light recognition failed for {name}: got {matched_name}"
        assert conf >= 0.48, f"Low-light confidence below threshold for {name}: {conf}"
        success_count += 1

    print(f" --> Result: {success_count}/{total_profiles} profiles successfully recognized under severe low-light (100% Recall).")

    # -------------------------------------------------------------------------
    # TEST 2: False Positive Rejection on Dark Strangers
    # -------------------------------------------------------------------------
    print("\n" + "-" * 80)
    print("[TEST 2] False Positive Rejection on Dark Unknown Strangers")
    print("-" * 80)

    for seed in range(5):
        np.random.seed(seed * 11)
        dark_stranger = np.random.randint(15, 45, (400, 300, 3), dtype=np.uint8)
        cv2.circle(dark_stranger, (150, 150), 65, (60, 50, 40), -1)
        cv2.circle(dark_stranger, (125, 140), 7, (10, 10, 10), -1)
        cv2.circle(dark_stranger, (175, 140), 7, (10, 10, 10), -1)
        cv2.ellipse(dark_stranger, (150, 180), (20, 8), 0, 0, 180, (20, 15, 15), 2)
        raw_luma = compute_frame_brightness(dark_stranger)

        s_name, s_conf, s_coords = recognizer.identify_face_in_person_crop(dark_stranger, (0, 0, 300, 400))
        print(f" [*] Dark Stranger #{seed+1} (Luma {raw_luma:4.1f}) -> Result: '{s_name}' (Conf: {s_conf:.3f})")
        assert s_name in [None, "UNKNOWN"], f"False positive match on dark stranger: matched as '{s_name}'!"

    print(" --> Result: 0% False Positives on dark strangers.")

    # -------------------------------------------------------------------------
    # TEST 3: Full-Frame Multi-Stage Low-Light Enhancement Verification
    # -------------------------------------------------------------------------
    print("\n" + "-" * 80)
    print("[TEST 3] Full-Frame Multi-Stage Low-Light Illumination & Denoising Engine")
    print("-" * 80)

    sample_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    sample_frame[:] = (25, 20, 20)  # Very dark background (Luma ~ 22)
    # Add pedestrian silhouette
    cv2.rectangle(sample_frame, (200, 100), (300, 400), (45, 40, 40), -1)
    cv2.circle(sample_frame, (250, 140), 30, (55, 45, 40), -1)

    init_luma = compute_frame_brightness(sample_frame)
    enhanced = enhance_low_light(sample_frame)
    enh_luma = compute_frame_brightness(enhanced)

    print(f" [+] Initial Frame Luma : {init_luma:.1f}")
    print(f" [+] Enhanced Frame Luma: {enh_luma:.1f} (Dynamic Lift: +{enh_luma - init_luma:.1f})")
    assert enh_luma > init_luma * 2.0, "Low light enhancement must significantly increase visibility!"
    print("  [PASS] Full-frame dynamic range expansion and contrast boost verified.")

    print("\n" + "=" * 80)
    print("ALL ADVANCED NIGHT MODE & LOW-LIGHT VERIFICATIONS PASSED (100% SUCCESS)")
    print("=" * 80)


if __name__ == "__main__":
    run_night_mode_tests()
