"""
IBVAP - Step 4 Verification Runner
Tests REST endpoints and live WebSocket event streaming concurrently.
"""

import asyncio
import json
import subprocess
import urllib.request
import websockets


def test_rest_endpoints():
    base_url = "http://127.0.0.1:8000"
    print("\n========================================================")
    print(" 1. REST API ENDPOINTS VERIFICATION (WITH JWT AUTH)")
    print("========================================================")

    # 0. Authenticate as Admin
    login_req = urllib.request.Request(
        f"{base_url}/api/auth/login",
        data=json.dumps({"username": "admin", "password": "Admin@IBVAP2026!"}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(login_req) as resp:
        login_data = json.loads(resp.read().decode())
        token = login_data["access_token"]
        print(f"[POST /api/auth/login] -> HTTP {resp.status} | Authenticated as '{login_data['user']['username']}' ({login_data['user']['role']})")

    auth_headers = {"Authorization": f"Bearer {token}"}

    # 1. Cameras
    cam_req = urllib.request.Request(f"{base_url}/api/cameras", headers=auth_headers)
    with urllib.request.urlopen(cam_req) as resp:
        cameras = json.loads(resp.read().decode())
        print(f"\n[GET /api/cameras] -> HTTP {resp.status} | Registered: {len(cameras)} camera(s)")
        print(json.dumps(cameras, indent=2))

    # 2. Stats
    stats_req = urllib.request.Request(f"{base_url}/api/stats", headers=auth_headers)
    with urllib.request.urlopen(stats_req) as resp:
        stats = json.loads(resp.read().decode())
        print(f"\n[GET /api/stats] -> HTTP {resp.status}")
        print(json.dumps(stats, indent=2))

    # 3. Events list
    events_req = urllib.request.Request(f"{base_url}/api/events?limit=3", headers=auth_headers)
    with urllib.request.urlopen(events_req) as resp:
        events = json.loads(resp.read().decode())
        print(f"\n[GET /api/events?limit=3] -> HTTP {resp.status} | Returned: {events['count']} event(s)")
        print(json.dumps(events, indent=2))

    # 4. Single event & Snapshot
    if events.get("events"):
        first_id = events["events"][0]["event_id"]
        detail_req = urllib.request.Request(f"{base_url}/api/events/{first_id}", headers=auth_headers)
        with urllib.request.urlopen(detail_req) as resp:
            ev_detail = json.loads(resp.read().decode())
            print(f"\n[GET /api/events/{first_id}] -> HTTP {resp.status}")
            print(json.dumps(ev_detail, indent=2))

        with urllib.request.urlopen(f"{base_url}/api/snapshots/{first_id}") as resp:
            data = resp.read()
            print(f"\n[GET /api/snapshots/{first_id}] -> HTTP {resp.status} | JPEG Image ({len(data)} bytes, Content-Type: {resp.headers.get('Content-Type')})")

    print("========================================================\n")


async def test_websocket_streaming():
    print("========================================================")
    print(" 2. REAL-TIME WEBSOCKET STREAMING VERIFICATION")
    print("========================================================")
    uri = "ws://127.0.0.1:8000/ws/events"
    print(f"[*] Connecting WebSocket client to: {uri}")

    async with websockets.connect(uri) as ws:
        handshake = await ws.recv()
        print(f"[+] WebSocket Handshake: {handshake}\n")

        print("[*] Launching detection_tracking.py to trigger live border events...")
        proc = subprocess.Popen(
            [
                "backend/.venv/Scripts/python",
                "backend/app/detection_tracking.py",
                "--input",
                "backend/test_videos/tracking_test.mp4",
                "--output",
                "backend/test_videos/annotated_tracking.mp4",
                "--no-display",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        events_received = []
        for i in range(5):
            raw_msg = await asyncio.wait_for(ws.recv(), timeout=30.0)
            event_data = json.loads(raw_msg)
            events_received.append(event_data)

            e_type = event_data.get("event_type", "").upper()
            e_sev = event_data.get("severity", "").upper()
            e_cls = event_data.get("object_class", "")
            e_tid = event_data.get("track_id", "")
            e_frame = event_data.get("frame_number", "")
            e_id = event_data.get("event_id", "")

            print(f">>> [WEBSOCKET LIVE EVENT #{i+1}] [{e_sev}] {e_type} -> ID #{e_tid} ({e_cls}) @ Frame {e_frame}")
            print(f"    UUID     : {e_id}")
            print(f"    BBox     : {event_data.get('bbox')}")
            print(f"    Snapshot : {event_data.get('snapshot_path')}\n")

        # Terminate background detection process after collecting events
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            pass

        print(f"[+] WebSocket verification SUCCESS! Received {len(events_received)} live security events over WebSocket.")
        print("========================================================\n")


def main():
    test_rest_endpoints()
    asyncio.run(test_websocket_streaming())


if __name__ == "__main__":
    main()
