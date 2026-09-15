"""
Specific test confirming /api/events/{event_id}/replay extracts and serves
a clip for an event generated from tracking_test.mp4 (frames 0-149, 30fps).
"""
import json
import sqlite3
import sys
from pathlib import Path
from fastapi.testclient import TestClient

backend_dir = Path(__file__).resolve().parent.parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from backend.app.main import app

def test_tracking_test_replay():
    client = TestClient(app)
    
    # 1. Login
    login_res = client.post("/api/auth/login", json={"username": "admin", "password": "Admin@IBVAP2026!"})
    assert login_res.status_code == 200
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    
    # 2. Find or pick event with frame_number <= 149 from tracking_test.mp4
    db_path = Path(__file__).resolve().parent.parent / "ibvap.db"
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM events WHERE frame_number > 20 AND frame_number < 140 AND event_type NOT LIKE 'auth_%' AND (source_video IS NULL OR source_video != 'live_webcam') AND camera_id NOT LIKE '%WEBCAM%' ORDER BY rowid ASC LIMIT 1")
        row = cur.fetchone()
        
    if row is None:
        from backend.app.events import log_event
        import numpy as np
        created_evt = log_event(
            camera_id="CAM_01",
            event_type="zone_entry",
            object_class="person",
            track_id=4,
            frame_number=45,
            bbox=[300.0, 200.0, 450.0, 500.0],
            confidence=0.92,
            frame=np.zeros((720, 1280, 3), dtype=np.uint8),
            source_video="tracking_test.mp4",
            print_json=False,
        )
        event_id = created_evt.event_id
        frame_num = created_evt.frame_number
    else:
        event_id = row["event_id"]
        frame_num = row["frame_number"]
    print(f"[*] Testing tracking_test.mp4 Event ID: {event_id} (Frame #{frame_num})")
    
    # 3. Test Metadata format=json
    meta_res = client.get(f"/api/events/{event_id}/replay?format=json&window=3.0", headers=headers)
    assert meta_res.status_code == 200, f"JSON request failed: {meta_res.text}"
    meta = meta_res.json()
    print("[+] Replay Metadata Result:")
    print(json.dumps(meta, indent=2))
    assert meta["status"] == "ready"
    assert "tracking_test.mp4" in meta["source_video"]
    assert meta["target_frame"] == frame_num
    assert meta["fps"] == 30.0
    assert meta["total_clip_frames"] > 0
    assert meta["duration_seconds"] > 0
    
    # 4. Test MP4 Video Stream
    vid_res = client.get(f"/api/events/{event_id}/replay?window=3.0", headers=headers)
    assert vid_res.status_code == 200, f"Video stream failed: {vid_res.text}"
    assert "video/mp4" in vid_res.headers.get("content-type", "")
    assert len(vid_res.content) > 10000
    print(f"[+] Replay Video Stream: HTTP {vid_res.status_code} | {len(vid_res.content)} bytes | Content-Type: {vid_res.headers.get('content-type')}")
    print("[+] Successfully confirmed tracking_test.mp4 replay extraction and streaming!")

if __name__ == "__main__":
    test_tracking_test_replay()
