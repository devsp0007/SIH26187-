"""
Test incident replay extraction around a security event
"""
import json
from pathlib import Path
import cv2
import numpy as np


def extract_incident_replay(
    video_path: Path,
    target_frame: int,
    output_path: Path,
    window_seconds: float = 3.0,
) -> dict:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return {"success": False, "error": f"Cannot open {video_path}"}
        
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    
    half_window = int(round(window_seconds * fps))
    start_frame = max(0, target_frame - half_window)
    end_frame = min(total_frames - 1, target_frame + half_window)
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out = cv2.VideoWriter(str(output_path), fourcc, fps, (width, height))
    
    cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
    current_idx = start_frame
    frames_written = 0
    
    while cap.isOpened() and current_idx <= end_frame:
        ret, frame = cap.read()
        if not ret:
            break
        
        # Add slight forensic watermark on clip
        t_delta = (current_idx - target_frame) / fps
        sign = "+" if t_delta >= 0 else ""
        overlay_text = f"FORENSIC REPLAY | Frame #{current_idx:04d} (T{sign}{t_delta:.2f}s)"
        cv2.putText(frame, overlay_text, (16, height - 16), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (0, 255, 255), 1, cv2.LINE_AA)
        
        out.write(frame)
        frames_written += 1
        current_idx += 1
        
    cap.release()
    out.release()
    
    return {
        "success": True,
        "video_file": output_path.name,
        "target_frame": target_frame,
        "start_frame": start_frame,
        "end_frame": end_frame,
        "total_clip_frames": frames_written,
        "fps": fps,
        "duration_seconds": round(frames_written / fps, 2),
    }


if __name__ == "__main__":
    base_dir = Path(__file__).resolve().parent.parent
    src_video = base_dir / "test_videos" / "annotated_tracking_test.mp4"
    if not src_video.exists():
        src_video = base_dir / "test_videos" / "tracking_test.mp4"
    dst_video = base_dir / "test_videos" / "replays" / "sample_replay.mp4"
    
    res = extract_incident_replay(src_video, target_frame=119, output_path=dst_video, window_seconds=3.0)
    print("Replay Extraction Result:", json.dumps(res, indent=2))
