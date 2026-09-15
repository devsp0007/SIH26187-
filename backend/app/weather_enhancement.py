"""
IBVAP - Weather Adaptive Vision & Dehazing Module
Provides real-time atmospheric fog/haze detection and optical restoration using:
1. Optical Scattering Metric (Dark Channel floor, Color Saturation, Dynamic Range Contrast)
2. Dark Channel Prior (DCP) Dehazing (He et al.) with Fast Guided Filter
3. Fast Multi-Channel Contrast & Saturation Dehazing (Lightweight real-time alternative)
4. Synthetic Fog & Atmospheric Scattering Simulation (for testing & verification)
"""

import cv2
import numpy as np


def compute_fog_haze_metric(
    frame: np.ndarray,
    sat_thresh: float = 52.0,
    dark_thresh: float = 50.0,
    contrast_thresh: float = 46.0,
    min_lum_thresh: float = 55.0,
) -> tuple[bool, float, dict[str, float]]:
    """
    Evaluate atmospheric haze/fog density using classical optical scattering principles:
    1. Low Color Saturation: Atmospheric airlight washes out chromatic purity.
    2. Elevated Dark Channel Prior floor: Additive airlight scatters into all color channels.
    3. Suppressed Luminance Contrast: Global dynamic range and high-frequency edges attenuated.
    4. Minimum Luminance Gate: Distinguishes daylight/dusk fog from nocturnal low-light scenes.

    Returns:
        (is_hazy, composite_haze_score, metrics_dict)
    """
    if frame is None or frame.size == 0:
        return False, 0.0, {}

    # Downsample for sub-millisecond evaluation (<0.4ms)
    h, w = frame.shape[:2]
    target_w = 160
    target_h = max(1, int(h * (target_w / w)))
    small = cv2.resize(frame, (target_w, target_h), interpolation=cv2.INTER_AREA)

    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)

    mean_sat = float(np.mean(hsv[:, :, 1]))          # Saturation (0-255)
    std_lum = float(np.std(gray))                    # Luminance standard deviation / contrast (0-255)
    mean_lum = float(np.mean(gray))                  # Average luminance (0-255)

    # Dark Channel Prior minimum on thumbnail
    dark_channel = np.min(small, axis=2)
    mean_dark = float(np.mean(dark_channel))         # Mean dark channel intensity (0-255)

    # Normalized composite haze score (0.0 to 1.0)
    # Higher score = denser atmospheric haze
    dark_component = (mean_dark / 255.0) * 0.45
    sat_component = (1.0 - (mean_sat / 255.0)) * 0.35
    contrast_component = (1.0 - min(std_lum, 60.0) / 60.0) * 0.20
    haze_score = float(np.clip(dark_component + sat_component + contrast_component, 0.0, 1.0))

    # Optical Fog Signature: Low saturation, elevated dark floor, low contrast, daylight/dusk luminance
    is_hazy = (
        (mean_sat < sat_thresh)
        and (mean_dark > dark_thresh)
        and (std_lum < contrast_thresh)
        and (mean_lum > min_lum_thresh)
    )

    metrics = {
        "mean_sat": round(mean_sat, 1),
        "mean_dark": round(mean_dark, 1),
        "std_lum": round(std_lum, 1),
        "mean_lum": round(mean_lum, 1),
        "haze_score": round(haze_score, 3),
    }

    return is_hazy, haze_score, metrics


def _fast_guided_filter(
    p: np.ndarray,
    I: np.ndarray,
    r: int = 8,
    eps: float = 0.001,
    subsample: int = 2,
) -> np.ndarray:
    """
    Fast Guided Filter with spatial sub-sampling (He et al.) for edge-preserving
    transmission map smoothing in O(N) linear time.
    """
    h, w = p.shape
    sub_w = max(1, w // subsample)
    sub_h = max(1, h // subsample)

    small_p = cv2.resize(p, (sub_w, sub_h), interpolation=cv2.INTER_NEAREST)
    small_I = cv2.resize(I, (sub_w, sub_h), interpolation=cv2.INTER_NEAREST)
    small_r = max(1, r // subsample)

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

    return full_mean_a * I + full_mean_b


def dehaze_dark_channel_prior(
    frame: np.ndarray,
    omega: float = 0.85,
    t0: float = 0.18,
    scale_factor: float = 0.35,
) -> np.ndarray:
    """
    Classical Dark Channel Prior (DCP) Dehazing (He, Sun, Tang 2011).
    Estimates global atmospheric airlight A and coarse transmission map t(x)
    on a downsampled grid, refines via fast guided filtering, and inverts the
    atmospheric scattering equation:
        J(x) = (I(x) - A) / max(t(x), t0) + A

    Args:
        frame: Input BGR image (uint8).
        omega: Haze retention factor (0.80-0.95) to maintain aerial perspective realism.
        t0: Lower transmission threshold to prevent noise amplification in heavy fog.
        scale_factor: Scale factor for coarse transmission estimation.
    """
    if frame is None or frame.size == 0:
        return frame

    h, w, _ = frame.shape
    dw, dh = max(16, int(w * scale_factor)), max(16, int(h * scale_factor))

    # 1. Downsampled analysis image (normalized 0.0 to 1.0)
    small = cv2.resize(frame, (dw, dh), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0

    # 2. Coarse Dark Channel on thumbnail
    dark_small = np.min(small, axis=2)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    dark_eroded = cv2.erode(dark_small, kernel)

    # 3. Atmospheric Light A (from top 0.1% brightest pixels in dark channel)
    num_top = max(1, int(dw * dh * 0.001))
    flat_dark = dark_eroded.ravel()
    indices = np.argpartition(flat_dark, -num_top)[-num_top:]
    flat_small = small.reshape(-1, 3)
    A = np.max(flat_small[indices], axis=0)
    A = np.clip(A, 0.45, 0.98)

    # 4. Transmission Map Estimation
    norm_small = small / A
    raw_dark = cv2.erode(np.min(norm_small, axis=2), kernel)
    raw_t = 1.0 - omega * raw_dark
    raw_t = np.clip(raw_t, t0, 1.0)

    # 5. Fast Guided Filter smoothing
    gray_small = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    t_smooth_small = _fast_guided_filter(raw_t, gray_small, r=8, eps=0.001, subsample=2)

    # 6. Upsample transmission map to full resolution
    t_full = cv2.resize(t_smooth_small, (w, h), interpolation=cv2.INTER_LINEAR)
    t_full = np.clip(t_full, t0, 1.0)[:, :, np.newaxis]

    # 7. Recover scene radiance J(x)
    img_f = frame.astype(np.float32) / 255.0
    J = (img_f - A) / t_full + A
    J_uint8 = np.clip(J * 255.0, 0, 255).astype(np.uint8)

    # 8. Subtle micro-contrast boost on Lightness channel
    lab = cv2.cvtColor(J_uint8, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=1.8, tileGridSize=(8, 8))
    l = clahe.apply(l)

    return cv2.cvtColor(cv2.merge((l, a, b)), cv2.COLOR_LAB2BGR)


def dehaze_fast_contrast_saturation(
    frame: np.ndarray,
    clip_limit: float = 3.2,
    sat_scale: float = 1.4,
) -> np.ndarray:
    """
    [EXPERIMENTAL - NOT VIABLE FOR ACCURATE DETECTION]
    Empirical Audit Result: Degrades True Positives from 451 to 348 and increases
    False Positives from 8 to 64.
    
    Mathematical Failure Mode: Naive percentile contrast stretching across narrow
    haze histograms severely clips high-luminance regions (blowing out sky/ground)
    and amplifies noise in shadows, destroying the spatial gradient textures that
    YOLO convolution kernels rely on for object boundary recognition.
    
    Retained for comparative evaluation and research documentation only.
    Use Dark Channel Prior (dehaze_dark_channel_prior) for production deployment.
    """
    if frame is None or frame.size == 0:
        return frame

    # 1. LAB CLAHE on Lightness channel
    lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=(8, 8))
    l = clahe.apply(l)

    # 2. Dynamic Contrast Stretching on L
    p3, p97 = np.percentile(l, (3, 97))
    if p97 > p3:
        l = np.clip((l.astype(np.float32) - p3) * (255.0 / (p97 - p3)), 0, 255).astype(np.uint8)

    bgr = cv2.cvtColor(cv2.merge((l, a, b)), cv2.COLOR_LAB2BGR)

    # 3. HSV Saturation Restoration
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    h, s, v = cv2.split(hsv)
    s = np.clip(s.astype(np.float32) * sat_scale, 0, 255).astype(np.uint8)

    return cv2.cvtColor(cv2.merge((h, s, v)), cv2.COLOR_HSV2BGR)


def apply_synthetic_fog(
    frame: np.ndarray,
    fog_density: float = 0.60,
    airlight: float = 210.0,
) -> np.ndarray:
    """
    Synthesize realistic atmospheric fog/haze using Koschmieder's physical scattering model:
        I(x) = J(x)*t(x) + A*(1 - t(x))
    where transmission t(x) = exp(-beta * d(x)), with realistic depth map gradient.
    """
    if frame is None or frame.size == 0:
        return frame

    h, w, _ = frame.shape
    y_coords, x_coords = np.mgrid[0:h, 0:w]

    # Depth approximation (horizon + radial perspective)
    depth = 0.5 * (1.0 - (y_coords / h)) + 0.5 * (
        np.sqrt((x_coords - w / 2) ** 2 + (y_coords - h / 2) ** 2) / np.sqrt((w / 2) ** 2 + (h / 2) ** 2)
    )
    depth = np.clip(depth, 0.2, 1.0)

    # Transmission map
    beta = fog_density * 2.2
    transmission = np.exp(-beta * depth)[:, :, np.newaxis]

    # Atmospheric airlight veil
    A = np.array([airlight, airlight, airlight], dtype=np.float32)

    # Scattered radiance
    foggy = frame.astype(np.float32) * transmission + A * (1.0 - transmission)
    foggy_bgr = np.clip(foggy, 0, 255).astype(np.uint8)

    # Slight forward-scattering blur
    foggy_bgr = cv2.GaussianBlur(foggy_bgr, (3, 3), 0.5)

    return foggy_bgr
