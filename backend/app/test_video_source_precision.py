"""
Comprehensive Verification: Exact Source Video Linkage & Zero Cross-Contamination
"""
import os
import sys
import json
from pathlib import Path
import numpy as np
from fastapi.testclient import TestClient

backend_dir = Path(__file__).resolve().parent.parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from backend.app.main import app
from backend.app.events import log_event, init_db

def run_precision_test():
    print("=" * 75)
    print("VERIFYING EXACT SOURCE VIDEO LINKAGE & REPLAY ACCURACY")
    print("=" * 75)
    
    client = TestClient(app)
    
    # 1. Login
    login_res = client.post("/api/auth/login", json={"username": "admin", "password": "Admin@IBVAP2026!"})
    assert login_res.status_code == 200
    headers = {"Authorization": f"Bearer {login_res.json()['access_token']}"}
    
    # 2. Test Case A: Real Webcam Session (e.g. Kunal, Track #1, suspicious pacing)
    print("\n[Case A] Generating Live Webcam Event (Kunal, Track #1, Suspicious Pacing)...")
    webcam_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    webcam_evt = log_event(
        camera_id="CAM_01",  # Same camera ID as Sector 4 Gate!
        event_type="suspicious_pacing",
        object_class="person",
        track_id=1,
        frame_number=88,
        bbox=[150.0, 100.0, 350.0, 450.0],
        confidence=0.91,
        frame=webcam_frame,
        face_detected=True,
        identified_as="Kunal",
        identification_confidence=0.89,
        source_video="live_webcam", # Explicit live webcam source tag
        print_json=False,
    )
    print(f" -> Event ID: {webcam_evt.event_id} (Source: {webcam_evt.source_video}, Camera: {webcam_evt.camera_id}, ID: {webcam_evt.identified_as})")
    
    # Replay request for live webcam event MUST return 404 graceful fallback and MUST NOT return annotated_real_footage_1.mp4
    webcam_replay_res = client.get(f"/api/events/{webcam_evt.event_id}/replay?format=json", headers=headers)
    print(f" -> Live Webcam Replay Status: HTTP {webcam_replay_res.status_code} (Expected 404)")
    assert webcam_replay_res.status_code == 404, f"Expected 404 for live webcam event, got {webcam_replay_res.status_code}"
    webcam_replay_json = webcam_replay_res.json()
    print(" -> Fallback Detail:", webcam_replay_json)
    assert "unavailable" in webcam_replay_json["detail"].lower()
    print(" [+] Confirmed: Live webcam event returns graceful unavailable fallback and DOES NOT serve unrelated test video!")

    # 3. Test Case B: Event from tracking_test.mp4 (Frame 45)
    print("\n[Case B] Generating Event from tracking_test.mp4...")
    tracking_frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    tracking_evt = log_event(
        camera_id="CAM_01",
        event_type="zone_entry",
        object_class="person",
        track_id=4,
        frame_number=45,
        bbox=[200.0, 150.0, 400.0, 500.0],
        confidence=0.94,
        frame=tracking_frame,
        source_video="tracking_test.mp4",
        print_json=False,
    )
    print(f" -> Event ID: {tracking_evt.event_id} (Source: {tracking_evt.source_video})")
    
    tracking_meta_res = client.get(f"/api/events/{tracking_evt.event_id}/replay?format=json", headers=headers)
    assert tracking_meta_res.status_code == 200, f"Failed: {tracking_meta_res.text}"
    tracking_meta = tracking_meta_res.json()
    print(" -> Replay Metadata:")
    print(json.dumps(tracking_meta, indent=2))
    assert "tracking_test.mp4" in tracking_meta["source_video"]
    assert tracking_meta["target_frame"] == 45
    print(" [+] Confirmed: tracking_test.mp4 event specifically pulls tracking_test.mp4!")

    # 4. Test Case C: Event from real_footage_1.mp4 (Frame 343)
    print("\n[Case C] Generating Event from real_footage_1.mp4...")
    rf_frame = np.zeros((432, 768, 3), dtype=np.uint8)
    rf_evt = log_event(
        camera_id="CAM_01", # Same camera_id reused across different session
        event_type="zone_exit",
        object_class="person",
        track_id=12,
        frame_number=343,
        bbox=[100.0, 100.0, 200.0, 300.0],
        confidence=0.87,
        frame=rf_frame,
        source_video="real_footage_1.mp4",
        print_json=False,
    )
    print(f" -> Event ID: {rf_evt.event_id} (Source: {rf_evt.source_video})")
    
    rf_meta_res = client.get(f"/api/events/{rf_evt.event_id}/replay?format=json", headers=headers)
    assert rf_meta_res.status_code == 200, f"Failed: {rf_meta_res.text}"
    rf_meta = rf_meta_res.json()
    print(" -> Replay Metadata:")
    print(json.dumps(rf_meta, indent=2))
    assert "real_footage_1.mp4" in rf_meta["source_video"]
    assert rf_meta["target_frame"] == 343
    print(" [+] Confirmed: real_footage_1.mp4 event specifically pulls real_footage_1.mp4!")

    print("\n" + "=" * 75)
    print("ALL PRECISION REPLAY LINKAGE TESTS PASSED WITH ZERO CROSS-CONTAMINATION!")
    print("=" * 75)

if __name__ == "__main__":
    run_precision_test()
