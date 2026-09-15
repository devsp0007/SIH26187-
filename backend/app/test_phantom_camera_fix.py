"""
IBVAP - Verification Test: Phantom Camera Prevention & Audit Trail Integrity
Verifies:
1. init_db() purges legacy phantom cameras like 'SYSTEM_AUTH'
2. log_auth_event() logs to events table (audit trail) WITHOUT upserting into cameras table
3. heartbeat_camera() ignores non-camera identifiers (e.g. 'SYSTEM_AUTH', 'SYSTEM_CORE', 'AUTH_SVC')
4. fetch_all_cameras() returns only genuine detection cameras
5. verify_chain_integrity() validates the cryptographic SHA-256 hash chain with auth events
"""

import sys
import sqlite3
from pathlib import Path

backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.events import (
    init_db,
    log_auth_event,
    heartbeat_camera,
    fetch_all_cameras,
    compute_event_stats,
    verify_chain_integrity,
    is_genuine_camera_id,
    get_default_db_path,
)


def run_verification():
    print("=" * 70)
    print(" IBVAP Phantom Camera Fix & Audit Integrity Verification")
    print("=" * 70)

    # 1. Test is_genuine_camera_id helper
    print("\n[Step 1] Testing is_genuine_camera_id validator...")
    assert is_genuine_camera_id("CAM_01") is True
    assert is_genuine_camera_id("CAM_02") is True
    assert is_genuine_camera_id("CAM_WEBCAM") is True
    assert is_genuine_camera_id("cam_01") is True
    assert is_genuine_camera_id("SYSTEM_AUTH") is False
    assert is_genuine_camera_id("SYSTEM_CORE") is False
    assert is_genuine_camera_id("AUTH") is False
    assert is_genuine_camera_id("AUTH_LOGIN") is False
    assert is_genuine_camera_id("UNKNOWN") is False
    assert is_genuine_camera_id("") is False
    assert is_genuine_camera_id(None) is False
    print("  [PASS] is_genuine_camera_id correctly categorizes real vs phantom IDs.")

    # 2. Test DB Initialization & Legacy Purge
    print("\n[Step 2] Testing init_db() legacy phantom camera purge...")
    db_path = init_db()
    with sqlite3.connect(db_path) as conn:
        # Check if SYSTEM_AUTH exists in cameras
        cam_rows = conn.execute("SELECT camera_id, name FROM cameras").fetchall()
        print(f"  Current cameras in DB ({len(cam_rows)} total):", cam_rows)
        for cid, cname in cam_rows:
            assert "SYSTEM" not in cid.upper(), f"Phantom camera found in DB: {cid}"
            assert "AUTH" not in cid.upper(), f"Phantom camera found in DB: {cid}"
    print("  [PASS] No phantom cameras exist in SQLite cameras table after init_db().")

    # 3. Test Direct heartbeat_camera with Non-Camera IDs
    print("\n[Step 3] Testing heartbeat_camera() refusal of non-camera IDs...")
    heartbeat_camera("SYSTEM_AUTH")
    heartbeat_camera("SYSTEM_GATEWAY")
    heartbeat_camera("AUTH_OPERATOR")
    heartbeat_camera("UNKNOWN")
    
    with sqlite3.connect(db_path) as conn:
        cam_ids = [r[0] for r in conn.execute("SELECT camera_id FROM cameras").fetchall()]
        print("  Cameras after attempted phantom heartbeats:", cam_ids)
        assert "SYSTEM_AUTH" not in cam_ids
        assert "SYSTEM_GATEWAY" not in cam_ids
        assert "AUTH_OPERATOR" not in cam_ids
    print("  [PASS] heartbeat_camera() safely ignored all non-camera identifiers.")

    # 4. Test Real Camera Registration
    print("\n[Step 4] Testing heartbeat_camera() with genuine detection cameras...")
    heartbeat_camera("CAM_01", name="Sector 4 Gate", location="North Perimeter Fence - Sector 4")
    heartbeat_camera("CAM_02", name="Sector 7 East Fence", location="East Perimeter Wall")

    with sqlite3.connect(db_path) as conn:
        cam_ids = [r[0] for r in conn.execute("SELECT camera_id FROM cameras").fetchall()]
        print("  Cameras registered:", cam_ids)
        assert "CAM_01" in cam_ids
        assert "CAM_02" in cam_ids
    print("  [PASS] Genuine detection cameras successfully registered.")

    # 5. Test Multiple Auth Login Events
    print("\n[Step 5] Simulating multiple auth events (success & failed logins)...")
    for i in range(3):
        log_auth_event(username="admin", role="admin", success=True, reason="Password login", print_json=False)
        log_auth_event(username="operator", role="operator", success=True, reason="Password login", print_json=False)
        log_auth_event(username="hacker_test", role="unknown", success=False, reason="Bad password", print_json=False)

    # Verify cameras table remains clean
    with sqlite3.connect(db_path) as conn:
        cam_rows = conn.execute("SELECT camera_id, name FROM cameras").fetchall()
        print(f"  Cameras in DB after 9 auth events ({len(cam_rows)} total):", cam_rows)
        for cid, cname in cam_rows:
            assert not cid.startswith("SYSTEM"), f"Phantom camera created: {cid}"
            assert not cid.startswith("AUTH"), f"Phantom camera created: {cid}"

    # Verify events table has recorded the auth events
    with sqlite3.connect(db_path) as conn:
        auth_events = conn.execute(
            "SELECT event_id, camera_id, event_type, object_class, identified_as FROM events WHERE camera_id = 'SYSTEM_AUTH'"
        ).fetchall()
        print(f"  Auth events recorded in audit log: {len(auth_events)}")
        assert len(auth_events) >= 9, f"Expected at least 9 auth events, got {len(auth_events)}"

    print("  [PASS] Auth events logged to events table WITHOUT polluting cameras table.")

    # 6. Test fetch_all_cameras() & compute_event_stats()
    print("\n[Step 6] Testing fetch_all_cameras() and compute_event_stats()...")
    cams = fetch_all_cameras()
    print(f"  fetch_all_cameras() returned {len(cams)} camera(s):", [c["camera_id"] for c in cams])
    assert all(not c["camera_id"].startswith("SYSTEM") for c in cams)
    assert all(not c["camera_id"].startswith("AUTH") for c in cams)

    stats = compute_event_stats()
    print(f"  Dashboard stats: active_cameras={stats['active_cameras']}, total_cameras={stats['total_cameras']}")
    assert stats["total_cameras"] == len(cams)
    print("  [PASS] fetch_all_cameras() and compute_event_stats() verified.")

    # 7. Test Cryptographic SHA-256 Hash Chain Integrity
    print("\n[Step 7] Testing Cryptographic Audit Trail Hash Chain Integrity...")
    integrity = verify_chain_integrity()
    print(f"  Audit chain verification: valid={integrity['valid']}, total_checked={integrity['total_events_checked']}")
    assert integrity["valid"] is True, f"Audit chain broken: {integrity}"
    print("  [PASS] Cryptographic SHA-256 audit chain 100% valid.")

    print("\n" + "=" * 70)
    print(" ALL PHANTOM CAMERA PREVENTION & AUDIT INTEGRITY CHECKS PASSED!")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    run_verification()
