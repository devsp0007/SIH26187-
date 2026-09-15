"""
Benchmark optimized DCP with multi-scale downsampled transmission estimation
"""
import time
from pathlib import Path
import cv2
import numpy as np


def fast_guided_filter(p, I, r, eps, s=4):
    h, w = p.shape
    small_p = cv2.resize(p, (w // s, h // s), interpolation=cv2.INTER_NEAREST)
    small_I = cv2.resize(I, (w // s, h // s), interpolation=cv2.INTER_NEAREST)
    small_r = max(1, r // s)
    
    mean_I = cv2.blur(small_I, (small_r, small_r))
    mean_p = cv2.blur(small_p, (small_r, small_r))
    mean_Ip = cv2.blur(small_I * small_p, (small_r, small_r))
    cov_Ip = mean_Ip - mean_I * mean_p
    
    mean_II = cv2.blur(small_I * small_I, (small_r, small_r))
    var_I = mean_II - mean_I * mean_I
    
    a = cov_Ip / (var_I + eps)
    b = mean_p - a * mean_I
    
    mean_a = cv2.blur(a, (small_r, small_r))
    mean_b = cv2.blur(b, (small_r, small_r))
    
    full_mean_a = cv2.resize(mean_a, (w, h), interpolation=cv2.INTER_LINEAR)
    full_mean_b = cv2.resize(mean_b, (w, h), interpolation=cv2.INTER_LINEAR)
    
    q = full_mean_a * I + full_mean_b
    return q


def dehaze_dcp_fast(frame: np.ndarray, omega: float = 0.85, t0: float = 0.18, scale_factor: float = 0.35) -> np.ndarray:
    """
    Optimized Dark Channel Prior (DCP) Dehazing with downsampled transmission map.
    Estimates atmospheric light and coarse transmission on downsampled grid, then refines.
    """
    h, w, _ = frame.shape
    dw, dh = int(w * scale_factor), int(h * scale_factor)
    
    # 1. Downsampled analysis image
    small = cv2.resize(frame, (dw, dh), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0
    
    # 2. Dark channel on thumbnail
    dark_small = np.min(small, axis=2)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    dark_eroded = cv2.erode(dark_small, kernel)
    
    # 3. Atmospheric Light A
    num_top = max(1, int(dw * dh * 0.001))
    flat_dark = dark_eroded.ravel()
    indices = np.argpartition(flat_dark, -num_top)[-num_top:]
    flat_small = small.reshape(-1, 3)
    A = np.max(flat_small[indices], axis=0)
    A = np.clip(A, 0.45, 0.98)
    
    # 4. Transmission on thumbnail
    norm_small = small / A
    raw_dark = cv2.erode(np.min(norm_small, axis=2), kernel)
    raw_t = 1.0 - omega * raw_dark
    raw_t = np.clip(raw_t, t0, 1.0)
    
    # 5. Fast Guided Filter on thumbnail
    gray_small = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    t_smooth_small = fast_guided_filter(raw_t, gray_small, r=8, eps=0.001, s=2)
    
    # 6. Upsample transmission map to full resolution with guided blur
    t_full = cv2.resize(t_smooth_small, (w, h), interpolation=cv2.INTER_LINEAR)
    t_full = np.clip(t_full, t0, 1.0)[:, :, np.newaxis]
    
    # 7. Recover scene radiance (vectorized in float32 or uint8 lookup)
    img_f = frame.astype(np.float32) / 255.0
    J = (img_f - A) / t_full + A
    J = np.clip(J * 255.0, 0, 255).astype(np.uint8)
    
    # Quick CLAHE L channel
    lab = cv2.cvtColor(J, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=1.8, tileGridSize=(8, 8))
    l = clahe.apply(l)
    return cv2.cvtColor(cv2.merge((l, a, b)), cv2.COLOR_LAB2BGR)


def dehaze_fast_contrast(frame: np.ndarray) -> np.ndarray:
    """
    Ultra-Fast Contrast & Chrominance Dehazing.
    Takes ~3-5ms per frame.
    """
    # 1. LAB CLAHE on L channel
    lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=3.2, tileGridSize=(8, 8))
    l = clahe.apply(l)
    
    # 2. Dynamic Contrast Stretching
    p3, p97 = np.percentile(l, (3, 97))
    if p97 > p3:
        l = np.clip((l.astype(np.float32) - p3) * (255.0 / (p97 - p3)), 0, 255).astype(np.uint8)
    
    bgr = cv2.cvtColor(cv2.merge((l, a, b)), cv2.COLOR_LAB2BGR)
    
    # 3. HSV Saturation Restoration
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    h, s, v = cv2.split(hsv)
    s = cv2.multiply(s, 1.4)
    return cv2.cvtColor(cv2.merge((h, s, v)), cv2.COLOR_HSV2BGR)


def test_speed():
    base_dir = Path(__file__).resolve().parent.parent
    video_path = base_dir / "test_videos" / "tracking_test.mp4"
    cap = cv2.VideoCapture(str(video_path))
    ret, frame = cap.read()
    cap.release()
    assert ret
    
    # Warmup
    for _ in range(5):
        _ = dehaze_dcp_fast(frame)
        _ = dehaze_fast_contrast(frame)
        
    t0 = time.perf_counter()
    N = 30
    for _ in range(N):
        _ = dehaze_dcp_fast(frame)
    dcp_time = (time.perf_counter() - t0) / N * 1000.0
    
    t0 = time.perf_counter()
    for _ in range(N):
        _ = dehaze_fast_contrast(frame)
    fast_time = (time.perf_counter() - t0) / N * 1000.0
    
    print(f"Optimized DCP Latency:        {dcp_time:.2f} ms / frame (~{1000/dcp_time:.1f} FPS)")
    print(f"Fast Contrast-Dehaze Latency: {fast_time:.2f} ms / frame (~{1000/fast_time:.1f} FPS)")


if __name__ == "__main__":
    test_speed()
