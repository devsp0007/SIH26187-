"""
IBVAP - Incident Replay & Forensic Timeline Extraction Subsystem
Extracts short synchronized clips (T-3s to T+3s) around recorded security events
from annotated surveillance sessions, generating browser-compatible MP4 clips
and frame metadata for forensic investigation.
"""

import base64
import json
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
import cv2
import numpy as np

try:
    from backend.app.events import fetch_event_by_id
except ImportError:
    from app.events import fetch_event_by_id


def get_replays_dir() -> Path:
    """Return directory where cached incident replay MP4s are stored."""
    base_dir = Path(__file__).resolve().parent.parent
    replays_dir = base_dir / "test_videos" / "replays"
    replays_dir.mkdir(parents=True, exist_ok=True)
    return replays_dir


def find_source_video_for_event(event: Dict[str, Any]) -> Optional[Path]:
    """
    Locate the exact source surveillance video corresponding to a security event.
    Returns Path if found, or None if the session was a live webcam/RTSP stream with no recording.
    """
    source_video = event.get("source_video")
    camera_id = str(event.get("camera_id", "")).upper()

    # 1. Live sessions (webcam, RTSP, live stream) or auth events have NO continuous video file
    if any(k in camera_id for k in ["WEBCAM", "USB_CAM", "SYSTEM_AUTH"]):
        return None

    if event.get("source_type") in ["webcam", "live", "rtsp_live"] or event.get("is_live_stream"):
        return None

    if source_video in ["live_webcam", "live", "webcam", "live_stream", "live_rtsp"]:
        # If source_video is explicitly live_webcam, this is a live-only event
        return None

    base_dir = Path(__file__).resolve().parent.parent
    test_videos_dir = base_dir / "test_videos"

    # 2. Look up the exact source_video filename stored with the event
    if source_video:
        target_name = Path(str(source_video)).name
        candidate_paths = [
            test_videos_dir / target_name,
            test_videos_dir / f"annotated_{target_name}",
            test_videos_dir / target_name.replace("annotated_", ""),
            base_dir / source_video if not Path(source_video).is_absolute() else Path(source_video),
        ]

        for path in candidate_paths:
            if path.exists() and path.stat().st_size > 2048:
                cap = cv2.VideoCapture(str(path))
                if cap.isOpened():
                    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                    cap.release()
                    if total_frames > 5:
                        return path

    # 3. Fallback for recorded camera feeds (e.g. CAM_01)
    if camera_id in ["CAM_01", "CAM_02", "CAM_03", ""]:
        for default_name in ["tracking_test.mp4", "annotated_tracking_test.mp4"]:
            default_path = test_videos_dir / default_name
            if default_path.exists() and default_path.stat().st_size > 2048:
                return default_path

    return None


def extract_incident_replay_clip(
    event_id: str,
    window_seconds: float = 3.0,
) -> Tuple[bool, Dict[str, Any], Optional[Path]]:
    """
    Extract a forensic sub-clip around a specific event's frame number (T-3s to T+3s).
    Returns (is_available, metadata_dict, file_path).
    """
    event = fetch_event_by_id(event_id)
    if not event:
        return False, {"status": "not_found", "message": f"Event '{event_id}' not found."}, None

    target_frame = int(event.get("frame_number", 0))
    camera_id = event.get("camera_id", "CAM_01")
    event_type = event.get("event_type", "security_event")
    timestamp = event.get("timestamp", "")

    # Locate source video
    source_video = find_source_video_for_event(event)
    if not source_video:
        return False, {
            "status": "unavailable",
            "message": "Incident replay is unavailable for live-only camera sessions where continuous video recording was not retained.",
            "event_id": event_id,
            "camera_id": camera_id,
            "frame_number": target_frame,
        }, None

    replays_dir = get_replays_dir()
    replay_file = replays_dir / f"replay_{event_id}.mp4"
    meta_file = replays_dir / f"replay_{event_id}.json"

    # Return cached replay if it already exists and is non-empty
    if replay_file.exists() and replay_file.stat().st_size > 2048 and meta_file.exists():
        try:
            with open(meta_file, "r", encoding="utf-8") as f:
                cached_meta = json.load(f)
            if cached_meta.get("source_video") == source_video.name:
                return True, cached_meta, replay_file
        except Exception:
            pass

    # Extract subclip using OpenCV & PyAV for universally playable H.264
    cap = cv2.VideoCapture(str(source_video))
    if not cap.isOpened():
        return False, {
            "status": "unavailable",
            "message": f"Could not read source video stream '{source_video.name}'.",
        }, None

    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 1280
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 720
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1

    half_window = int(round(window_seconds * fps))
    clamped_target = min(total_frames - 1, max(0, target_frame))
    start_frame = max(0, clamped_target - half_window)
    end_frame = min(total_frames - 1, clamped_target + half_window)
    clip_frames_count = max(1, end_frame - start_frame + 1)

    # Collect and annotate frames
    cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
    current_idx = start_frame
    frames_buffer = []

    while cap.isOpened() and current_idx <= end_frame:
        ret, frame = cap.read()
        if not ret:
            break

        # Forensic HUD Overlays
        t_delta = (current_idx - target_frame) / fps
        sign = "+" if t_delta >= 0 else ""
        
        # Bottom Tactical Watermark
        overlay_text = f"IBVAP FORENSIC REPLAY | Frame #{current_idx:04d} (T{sign}{t_delta:+.2f}s) | {event_type.upper()}"
        cv2.rectangle(frame, (10, height - 34), (width - 10, height - 8), (10, 16, 25), -1)
        cv2.rectangle(frame, (10, height - 34), (width - 10, height - 8), (0, 200, 255), 1)
        cv2.putText(
            frame,
            overlay_text,
            (20, height - 16),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.48,
            (0, 255, 255),
            1,
            cv2.LINE_AA,
        )

        # Highlight exact trigger frame with a distinctive forensic target box
        if current_idx == target_frame:
            cv2.putText(
                frame,
                "[*] EVENT TRIGGER INSTANT",
                (width - 240, 24),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.50,
                (0, 80, 255),
                2,
                cv2.LINE_AA,
            )

        frames_buffer.append(frame)
        current_idx += 1

    cap.release()

    if not frames_buffer:
        return False, {
            "status": "unavailable",
            "message": "No video frames could be extracted for the requested window.",
        }, None

    # Write video using PyAV H.264 (fallback to cv2.VideoWriter if PyAV fails)
    wrote_video = False
    try:
        import av
        container = av.open(str(replay_file), mode='w')
        stream = container.add_stream('h264', rate=int(round(fps)))
        stream.width = width
        stream.height = height
        stream.pix_fmt = 'yuv420p'
        stream.options = {'crf': '23', 'preset': 'fast'}

        for f_bgr in frames_buffer:
            vframe = av.VideoFrame.from_ndarray(f_bgr, format='bgr24')
            for packet in stream.encode(vframe):
                container.mux(packet)

        for packet in stream.encode():
            container.mux(packet)

        container.close()
        wrote_video = replay_file.exists() and replay_file.stat().st_size > 1000
    except Exception:
        wrote_video = False

    if not wrote_video:
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        out = cv2.VideoWriter(str(replay_file), fourcc, fps, (width, height))
        for f_bgr in frames_buffer:
            out.write(f_bgr)
        out.release()

    duration = round(len(frames_buffer) / fps, 2)
    metadata = {
        "status": "ready",
        "event_id": event_id,
        "camera_id": camera_id,
        "event_type": event_type,
        "timestamp": timestamp,
        "source_video": source_video.name,
        "target_frame": target_frame,
        "start_frame": start_frame,
        "end_frame": end_frame,
        "total_clip_frames": len(frames_buffer),
        "fps": fps,
        "duration_seconds": duration,
        "window_description": f"T-{window_seconds:.1f}s to T+{window_seconds:.1f}s around {event_type.replace('_', ' ').title()}",
    }

    try:
        with open(meta_file, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)
    except Exception:
        pass

    return True, metadata, replay_file


def extract_event_target_crop(event_id: str) -> Tuple[bool, Optional[bytes], Dict[str, Any]]:
    """
    Extract a high-resolution target crop (face, license plate, or whole body) directly from
    the event snapshot or video frame for quick forensic zooming.
    Returns (success, jpeg_bytes, metadata).
    """
    event = fetch_event_by_id(event_id)
    if not event:
        return False, None, {"error": "Event not found"}

    snapshot_path = event.get("snapshot_path")
    base_dir = Path(__file__).resolve().parent.parent
    img = None

    if snapshot_path:
        full_snap_path = base_dir / snapshot_path if not Path(snapshot_path).is_absolute() else Path(snapshot_path)
        if full_snap_path.exists():
            img = cv2.imread(str(full_snap_path))

    if img is None:
        fallback_snap = base_dir / "snapshots" / f"{event_id}.jpg"
        if fallback_snap.exists():
            img = cv2.imread(str(fallback_snap))

    if img is None:
        return False, None, {"error": "Snapshot image not available for this event"}

    h, w = img.shape[:2]
    crop_type = "body"
    crop_box = event.get("bbox")

    # Priority 1: Face crop if available
    if event.get("face_bbox"):
        fb = event["face_bbox"]
        if isinstance(fb, list) and len(fb) == 4 and fb[2] > fb[0] and fb[3] > fb[1]:
            crop_box = fb
            crop_type = "face"
    # Priority 2: License plate crop if available
    elif event.get("plate_bbox"):
        pb = event["plate_bbox"]
        if isinstance(pb, list) and len(pb) == 4 and pb[2] > pb[0] and pb[3] > pb[1]:
            crop_box = pb
            crop_type = "plate"

    if not crop_box or not isinstance(crop_box, list) or len(crop_box) != 4:
        _, enc = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 90])
        return True, enc.tobytes(), {"crop_type": "full_frame", "box": [0, 0, w, h]}

    x1, y1, x2, y2 = map(int, crop_box)
    pad_x = int((x2 - x1) * 0.15)
    pad_y = int((y2 - y1) * 0.15)
    cx1 = max(0, x1 - pad_x)
    cy1 = max(0, y1 - pad_y)
    cx2 = min(w, x2 + pad_x)
    cy2 = min(h, y2 + pad_y)

    crop_img = img[cy1:cy2, cx1:cx2]
    if crop_img is None or crop_img.size == 0:
        crop_img = img

    ch, cw = crop_img.shape[:2]
    if cw < 240 or ch < 240:
        scale = max(240 / max(1, cw), 240 / max(1, ch))
        new_w = min(800, int(cw * scale))
        new_h = min(800, int(ch * scale))
        crop_img = cv2.resize(crop_img, (new_w, new_h), interpolation=cv2.INTER_CUBIC)

    _, enc = cv2.imencode(".jpg", crop_img, [cv2.IMWRITE_JPEG_QUALITY, 92])
    return True, enc.tobytes(), {
        "crop_type": crop_type,
        "box": [cx1, cy1, cx2, cy2],
        "identified_as": event.get("identified_as"),
        "plate_number": event.get("plate_number"),
    }
