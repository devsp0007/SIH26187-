import cv2
import numpy as np
from pathlib import Path
import math

test_dir = Path("backend/test_videos")
test_dir.mkdir(parents=True, exist_ok=True)
out_path = test_dir / "suspicious_behavior_test.mp4"

# Use high quality person crop from test images or render realistic silhouette
person_crop_path = Path("backend/test_videos/person_crop.png")
if not person_crop_path.exists():
    # Create realistic human figure sprite
    sprite = np.zeros((140, 60, 3), dtype=np.uint8)
    sprite[:] = (0, 0, 0)
    # Head
    cv2.circle(sprite, (30, 25), 18, (180, 160, 140), -1)
    # Torso
    cv2.rectangle(sprite, (15, 45), (45, 95), (60, 80, 160), -1)
    # Legs
    cv2.line(sprite, (22, 95), (20, 135), (40, 40, 50), 8)
    cv2.line(sprite, (38, 95), (40, 135), (40, 40, 50), 8)
    cv2.imwrite(str(person_crop_path), sprite)
else:
    sprite = cv2.imread(str(person_crop_path))

sh, sw = sprite.shape[:2]

# Video properties
width, height = 1024, 576
fps = 10
total_frames = 140 # 14 seconds

fourcc = cv2.VideoWriter_fourcc(*"mp4v")
writer = cv2.VideoWriter(str(out_path), fourcc, fps, (width, height))

# Load background or create realistic ground/facility scene
bg_path = Path("backend/test_videos/zone_preview.jpg")
if bg_path.exists():
    base_bg = cv2.imread(str(bg_path))
    base_bg = cv2.resize(base_bg, (width, height))
else:
    base_bg = np.zeros((height, width, 3), dtype=np.uint8)
    base_bg[:] = (40, 45, 50)
    # Road / courtyard
    cv2.rectangle(base_bg, (0, 180), (width, height), (70, 75, 80), -1)

# Restricted Zone is roughly: [(400, 150), (850, 150), (900, 450), (350, 450)]
print("[*] Generating suspicious behavior benchmark video (Loitering + Pacing + Transit)...")

for f in range(total_frames):
    frame = base_bg.copy()

    # 1. Subject A: Loitering Person
    # Moves in (f=0 to 25), then STAYS STATIONARY at (600, 260) inside zone from f=25 to 110 (85 frames / 8.5s)
    if f < 25:
        p1_x = int(350 + (f / 25.0) * 250)
        p1_y = int(180 + (f / 25.0) * 80)
    elif f <= 110:
        # Loitering stationary with micro-drift < 3px
        p1_x = 600 + int(2 * math.sin(f * 0.2))
        p1_y = 260 + int(2 * math.cos(f * 0.2))
    else:
        # Exits after loitering
        p1_x = int(600 + ((f - 110) / 30.0) * 300)
        p1_y = int(260 + ((f - 110) / 30.0) * 120)

    # Blend sprite onto frame
    if 0 <= p1_x < width - sw and 0 <= p1_y < height - sh:
        mask = (sprite > 10).any(axis=2)
        frame[p1_y:p1_y+sh, p1_x:p1_x+sw][mask] = sprite[mask]

    # 2. Subject B: Pacing Person (Near fence line x=280 to 440, reverses 4 times from f=15 to 120)
    # Period of oscillation = 25 frames
    if f >= 15:
        pacing_t = (f - 15) / 25.0 # cycles
        p2_x = int(350 + 75 * math.sin(pacing_t * 2 * math.pi))
        p2_y = 360 + int(5 * math.sin(pacing_t * 4 * math.pi))
        if 0 <= p2_x < width - sw and 0 <= p2_y < height - sh:
            mask = (sprite > 10).any(axis=2)
            frame[p2_y:p2_y+sh, p2_x:p2_x+sw][mask] = sprite[mask]

    # 3. Subject C: Normal Transit Person (Linear crossing without stopping or pacing)
    if f >= 20 and f <= 90:
        p3_x = int(100 + ((f - 20) / 70.0) * 800)
        p3_y = int(480 - ((f - 20) / 70.0) * 60)
        if 0 <= p3_x < width - sw and 0 <= p3_y < height - sh:
            mask = (sprite > 10).any(axis=2)
            frame[p3_y:p3_y+sh, p3_x:p3_x+sw][mask] = sprite[mask]

    writer.write(frame)

writer.release()
print(f"[+] Successfully generated: {out_path} ({total_frames} frames, {fps} FPS)")
