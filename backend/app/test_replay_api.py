"""
Test incident replay API endpoint against running FastAPI server or via TestClient fallback
"""
import sys
from pathlib import Path
import requests

backend_dir = Path(__file__).resolve().parent.parent
project_root = backend_dir.parent
for p in [str(project_root), str(backend_dir)]:
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    from backend.app.main import app
except ImportError:
    try:
        from app.main import app
    except ImportError:
        from main import app

from fastapi.testclient import TestClient

BASE_URL = "http://127.0.0.1:8000"


def is_live_server_up() -> bool:
    try:
        r = requests.get(f"{BASE_URL}/", timeout=0.8)
        return r.status_code == 200
    except Exception:
        return False


def test_replay_api():
    if is_live_server_up():
        print(f"[*] Testing against live server at {BASE_URL}...")
        client_post = lambda path, **kw: requests.post(f"{BASE_URL}{path}", **kw)
        client_get = lambda path, **kw: requests.get(f"{BASE_URL}{path}", **kw)
    else:
        print("[*] Live server not running on port 8000. Using in-process FastAPI TestClient...")
        tc = TestClient(app)
        client_post = lambda path, **kw: tc.post(path, **kw)
        client_get = lambda path, **kw: tc.get(path, **kw)

    # 1. Login to get token
    login_resp = client_post("/api/auth/login", json={"username": "admin", "password": "Admin@IBVAP2026!"})
    assert login_resp.status_code == 200, f"Login failed: {login_resp.text}"
    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    
    # 2. Fetch events list
    events_resp = client_get("/api/events", headers=headers)
    assert events_resp.status_code == 200, f"Failed to fetch events: {events_resp.text}"
    events = events_resp.json()["events"]
    print(f"[+] Found {len(events)} events in database.")
    
    # Filter security events (not auth events)
    sec_events = [
        e for e in events
        if not e["event_type"].startswith("auth_")
        and e.get("source_video") not in ["live_webcam", "live", "webcam"]
        and "WEBCAM" not in str(e.get("camera_id", "")).upper()
    ]
    if not sec_events:
        print("[!] No recorded security events found in DB. Logging a sample test event...")
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
        sample_event = {
            "event_id": created_evt.event_id,
            "frame_number": created_evt.frame_number,
            "event_type": created_evt.event_type,
        }
    else:
        sample_event = sec_events[0]

    event_id = sample_event["event_id"]
    print(f"[*] Testing Incident Replay for Event: {event_id} (Frame #{sample_event['frame_number']}, Type: {sample_event['event_type']})")
    
    # 3. Test Metadata format
    meta_resp = client_get(f"/api/events/{event_id}/replay?format=json", headers=headers)
    print(f"[*] Metadata Response Code: {meta_resp.status_code}")
    print("    Payload:", meta_resp.json())
    assert meta_resp.status_code == 200, "Metadata fetch failed"
    assert meta_resp.json()["status"] == "ready"
    
    # 4. Test Video File stream
    video_resp = client_get(f"/api/events/{event_id}/replay", headers=headers)
    print(f"[*] Video Stream Response Code: {video_resp.status_code}")
    print(f"    Content-Type: {video_resp.headers.get('content-type')}")
    print(f"    Content-Length: {len(video_resp.content)} bytes")
    assert video_resp.status_code == 200, "Video fetch failed"
    assert "video/mp4" in video_resp.headers.get("content-type", "")
    assert len(video_resp.content) > 1000
    
    # 5. Test Non-Existent Event Replay Fallback (404)
    fake_resp = client_get("/api/events/evt_fake_nonexistent_id/replay", headers=headers)
    print(f"[*] Non-existent Event Response Code: {fake_resp.status_code} (Expected 404)")
    print("    Detail:", fake_resp.json())
    assert fake_resp.status_code == 404
    
    print("\n[+] ALL BACKEND INCIDENT REPLAY ENDPOINT TESTS PASSED!")


if __name__ == "__main__":
    test_replay_api()

