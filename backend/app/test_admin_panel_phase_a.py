"""
IBVAP - Phase A Admin Panel Verification Test
Tests:
1. Watchlist Personnel database CRUD, photo persistence, and expiration enforcement
2. Authorized Vehicles database CRUD, plate normalization, and expiration enforcement
3. Severity calculation for authorized vs unauthorized vs expired targets
4. FastAPI RBAC security guards (401 unauth, 403 operator, 200 admin)
5. Live Watchlist rescan endpoint and embedding synchronization
"""

import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Ensure backend root is on sys.path
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from fastapi.testclient import TestClient
from app.main import app
from app.auth import create_access_token, init_users_table
from app.events import init_db, compute_severity, generate_tactical_summary_rule_based
from app.admin_management import (
    init_admin_tables,
    add_or_update_watchlist_person,
    get_all_watchlist_personnel,
    get_watchlist_person,
    delete_watchlist_person,
    check_watchlist_person_active,
    add_or_update_authorized_vehicle,
    get_all_authorized_vehicles,
    delete_authorized_vehicle,
    check_authorized_vehicle,
)


def run_tests():
    print("======================================================================", flush=True)
    print("   IBVAP PHASE A - ADMIN PANEL VERIFICATION TEST SUITE", flush=True)
    print("======================================================================\n", flush=True)

    # Initialize default DB as well
    init_db()
    init_users_table()
    init_admin_tables()

    # Use a temporary test database for clean unit logic
    temp_dir = tempfile.TemporaryDirectory()
    test_db = Path(temp_dir.name) / "test_ibvap.db"
    init_db(test_db)
    init_users_table(test_db)
    init_admin_tables(test_db)

    print("[PHASE 1] Testing Database Table Initialization & Auto-Seeding...", flush=True)
    wl_entries = get_all_watchlist_personnel(test_db)
    assert len(wl_entries) >= 5, f"Expected >=5 seeded watchlist personnel, got {len(wl_entries)}"
    print(f"  [+] Watchlist Personnel auto-seeded: {len(wl_entries)} profiles", flush=True)

    veh_entries = get_all_authorized_vehicles(test_db)
    assert len(veh_entries) >= 3, f"Expected >=3 seeded vehicles, got {len(veh_entries)}"
    print(f"  [+] Authorized Vehicles auto-seeded: {len(veh_entries)} vehicles", flush=True)
    print("  [+] PASS: Database initialization & seeding\n", flush=True)

    print("[PHASE 2] Testing Watchlist Personnel CRUD & Expiry Checking...", flush=True)
    today = datetime.now(timezone.utc).date()
    yesterday_str = (today - timedelta(days=1)).isoformat()
    future_str = (today + timedelta(days=30)).isoformat()

    # Add active officer
    active_person = add_or_update_watchlist_person(
        name="Maj. Vikram Batra",
        role="Command Staff",
        photo_filename="kunal.png",
        expiry_date=future_str,
        notes="Active duty clearance",
        db_path=test_db,
    )
    assert active_person["name"] == "Maj. Vikram Batra"
    assert active_person["is_expired"] is False
    assert check_watchlist_person_active("Maj. Vikram Batra", db_path=test_db) is True
    print("  [+] Active profile created and verified as active", flush=True)

    # Add expired contractor
    dummy_photo = Path(__file__).resolve().parent.parent / "watchlist" / "temp_dave.png"
    dummy_photo.write_bytes(b"dummy photo content")
    expired_person = add_or_update_watchlist_person(
        name="Contractor Dave",
        role="Contractor",
        photo_filename="temp_dave.png",
        expiry_date=yesterday_str,
        notes="Temporary gate pass",
        db_path=test_db,
    )
    assert expired_person["name"] == "Contractor Dave"
    assert expired_person["is_expired"] is True
    assert check_watchlist_person_active("Contractor Dave", db_path=test_db) is False
    print("  [+] Expired profile created and verified as skipped/inactive", flush=True)

    # Delete person (should also delete temp_dave.png)
    del_ok = delete_watchlist_person("Contractor Dave", db_path=test_db)
    assert del_ok is True
    assert get_watchlist_person("Contractor Dave", db_path=test_db) is None
    assert not dummy_photo.exists(), "Photo file should be deleted"
    print("  [+] PASS: Watchlist Personnel CRUD & Expiration Logic\n", flush=True)

    print("[PHASE 3] Testing Authorized Vehicles Whitelist CRUD & Plate Matching...", flush=True)
    # Add active patrol vehicle
    active_veh = add_or_update_authorized_vehicle(
        plate_number="DL 04 CA 1122",
        owner_name="Inspector Sharma",
        vehicle_type="Patrol Gypsy",
        purpose="Border Sector 4 Patrol",
        expiry_date=future_str,
        db_path=test_db,
    )
    assert active_veh["normalized_plate"] == "DL04CA1122"
    assert active_veh["is_expired"] is False

    # Check plate matching with varied spacing and lowercase
    matched_veh = check_authorized_vehicle("dl-04-ca-1122", db_path=test_db)
    assert matched_veh is not None
    assert matched_veh["owner_name"] == "Inspector Sharma"
    print("  [+] Active vehicle verified with normalized plate matching ('dl-04-ca-1122' -> 'DL04CA1122')", flush=True)

    # Add expired delivery truck
    expired_veh = add_or_update_authorized_vehicle(
        plate_number="UP 14 Z 9999",
        owner_name="Civilian Supply Co.",
        vehicle_type="Commercial Truck",
        purpose="One-time Delivery Pass",
        expiry_date=yesterday_str,
        db_path=test_db,
    )
    assert expired_veh["is_expired"] is True
    matched_exp = check_authorized_vehicle("UP 14 Z 9999", db_path=test_db)
    assert matched_exp is None, "Expired vehicle must NOT match as authorized!"
    print("  [+] Expired vehicle correctly excluded from authorization match", flush=True)
    print("  [+] PASS: Authorized Vehicles CRUD & Expiration Logic\n", flush=True)

    print("[PHASE 4] Testing Severity Calculation & Tactical Summaries...", flush=True)
    # 1. Authorized Active Person Entry -> LOW
    sev1 = compute_severity("zone_entry", "person", identified_as="Maj. Vikram Batra", db_path=test_db)
    assert sev1 == "low", f"Expected 'low' severity for active person, got {sev1}"
    print("  [+] Authorized active person entry -> severity 'low'", flush=True)

    # 2. Unrecognized Person Entry -> HIGH
    sev2 = compute_severity("zone_entry", "person", identified_as="UNKNOWN", db_path=test_db)
    assert sev2 == "high", f"Expected 'high' severity for UNKNOWN person, got {sev2}"
    print("  [+] Unrecognized person entry -> severity 'high'", flush=True)

    # 3. Expired Person Entry -> HIGH
    add_or_update_watchlist_person("Expired Visitor", "Visitor", "exp.png", expiry_date=yesterday_str, db_path=test_db)
    sev3 = compute_severity("zone_entry", "person", identified_as="Expired Visitor", db_path=test_db)
    assert sev3 == "high", f"Expected 'high' severity for expired person, got {sev3}"
    print("  [+] Expired person entry -> severity 'high'", flush=True)

    # 4. Authorized Active Vehicle Entry -> LOW
    sev4 = compute_severity("zone_entry", "car", plate_number="DL 04 CA 1122", db_path=test_db)
    assert sev4 == "low", f"Expected 'low' severity for authorized vehicle, got {sev4}"
    print("  [+] Authorized active vehicle entry -> severity 'low'", flush=True)

    # 5. Expired Vehicle Entry -> MEDIUM
    sev5 = compute_severity("zone_entry", "car", plate_number="UP 14 Z 9999", db_path=test_db)
    assert sev5 == "medium", f"Expected 'medium' severity for expired vehicle, got {sev5}"
    print("  [+] Expired vehicle entry -> severity 'medium'", flush=True)

    # 6. Unlisted Vehicle Entry -> MEDIUM
    sev6 = compute_severity("zone_entry", "car", plate_number="MH 02 AB 0001", db_path=test_db)
    assert sev6 == "medium", f"Expected 'medium' severity for unlisted vehicle, got {sev6}"
    print("  [+] Unlisted vehicle entry -> severity 'medium'", flush=True)

    # Tactical Summary text
    sum_auth_veh = generate_tactical_summary_rule_based({
        "event_type": "zone_entry",
        "object_class": "car",
        "track_id": 42,
        "camera_id": "CAM_01",
        "plate_number": "DL 01 AB 1234",
    })
    assert "Routine access: Authorized vehicle [DL 01 AB 1234]" in sum_auth_veh
    print(f"  [+] Tactical Summary verified: \"{sum_auth_veh}\"", flush=True)
    print("  [+] PASS: Severity Calculation & Tactical Summary\n", flush=True)

    print("[PHASE 5] Testing FastAPI REST Endpoints & RBAC Enforcement...", flush=True)
    client = TestClient(app)

    # 1. Unauthenticated Request -> 401 Unauthorized
    resp_unauth = client.get("/api/admin/watchlist")
    assert resp_unauth.status_code == 401, f"Expected 401, got {resp_unauth.status_code}"
    print("  [+] Unauthenticated GET /api/admin/watchlist -> 401 Unauthorized", flush=True)

    # 2. Operator Role Request -> 403 Forbidden
    op_token = create_access_token({"sub": "operator", "role": "operator", "name": "Surveillance Operator"})
    op_headers = {"Authorization": f"Bearer {op_token}"}

    resp_op_wl = client.get("/api/admin/watchlist", headers=op_headers)
    assert resp_op_wl.status_code == 403, f"Expected 403 Forbidden for operator, got {resp_op_wl.status_code}"

    resp_op_veh = client.get("/api/admin/vehicles", headers=op_headers)
    assert resp_op_veh.status_code == 403, f"Expected 403 Forbidden for operator, got {resp_op_veh.status_code}"

    resp_op_rescan = client.post("/api/admin/watchlist/rescan", headers=op_headers)
    assert resp_op_rescan.status_code == 403, f"Expected 403 Forbidden for operator on rescan, got {resp_op_rescan.status_code}"
    print("  [+] Operator role requests -> 403 Forbidden on all /api/admin/* endpoints", flush=True)

    # 3. Admin Role Request -> 200 OK
    admin_token = create_access_token({"sub": "admin", "role": "admin", "name": "Command Admin"})
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    resp_admin_wl = client.get("/api/admin/watchlist", headers=admin_headers)
    assert resp_admin_wl.status_code == 200, f"Expected 200, got {resp_admin_wl.status_code}"
    assert "watchlist" in resp_admin_wl.json()
    print(f"  [+] Admin GET /api/admin/watchlist -> 200 OK ({resp_admin_wl.json()['count']} items)", flush=True)

    resp_admin_veh = client.get("/api/admin/vehicles", headers=admin_headers)
    assert resp_admin_veh.status_code == 200, f"Expected 200, got {resp_admin_veh.status_code}"
    assert "vehicles" in resp_admin_veh.json()
    print(f"  [+] Admin GET /api/admin/vehicles -> 200 OK ({resp_admin_veh.json()['count']} items)", flush=True)

    # 4. Admin Add Vehicle
    new_veh_payload = {
        "plate_number": "PB 10 XY 7788",
        "owner_name": "Border Sec Fleet 9",
        "vehicle_type": "QRT Interceptor",
        "purpose": "Rapid Response Patrol",
        "expiry_date": future_str,
        "notes": "Armored Patrol Vehicle",
    }
    resp_add_veh = client.post("/api/admin/vehicles", json=new_veh_payload, headers=admin_headers)
    assert resp_add_veh.status_code == 200, f"Expected 200, got {resp_add_veh.text}"
    print("  [+] Admin POST /api/admin/vehicles -> 200 OK", flush=True)

    # 5. Admin Delete Vehicle
    resp_del_veh = client.delete("/api/admin/vehicles/PB10XY7788", headers=admin_headers)
    assert resp_del_veh.status_code == 200, f"Expected 200, got {resp_del_veh.text}"
    print("  [+] Admin DELETE /api/admin/vehicles/PB10XY7788 -> 200 OK", flush=True)

    # 6. Admin Watchlist Rescan
    resp_rescan = client.post("/api/admin/watchlist/rescan", headers=admin_headers)
    assert resp_rescan.status_code == 200, f"Expected 200, got {resp_rescan.text}"
    rescan_data = resp_rescan.json()
    assert rescan_data["status"] == "success"
    print(f"  [+] Admin POST /api/admin/watchlist/rescan -> 200 OK ({rescan_data['profiles_loaded']} profiles cached in memory)", flush=True)
    print("  [+] PASS: REST API & RBAC Security Guards\n", flush=True)

    import gc
    gc.collect()
    try:
        temp_dir.cleanup()
    except Exception:
        pass
    print("======================================================================", flush=True)
    print("   ALL 5 PHASES PASSED WITH ZERO REGRESSIONS!", flush=True)
    print("======================================================================\n", flush=True)


if __name__ == "__main__":
    run_tests()
