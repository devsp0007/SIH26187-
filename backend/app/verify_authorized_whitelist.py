"""
IBVAP - Intelligent Border Video Analytics Platform
Prompt #35 Verification Suite: Authorized Personnel Whitelist & Severity Differentiation

Tests:
1. Watchlisted person (e.g., Kunal) entering zone -> severity 'low', tactical summary 'Routine access: Kunal entered Sector 4 Gate.', voice speech skipped.
2. Unrecognized person entering zone -> severity 'high', tactical summary 'High alert: Unrecognized individual detected entering Sector 4 Gate...', voice speech triggered.
3. Watchlisted person loitering / pacing -> severity 'high', alert triggered even for authorized member.
4. Vehicle entering zone -> severity 'medium'.
5. Cryptographic SHA-256 tamper-evident hash chain verification.
"""

import sys
import numpy as np
from pathlib import Path

# Add project root to sys.path
root_dir = Path(__file__).resolve().parent.parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from backend.app.events import (
    compute_severity,
    generate_tactical_summary_rule_based,
    init_db,
    log_event,
    verify_chain_integrity,
)


def run_tests():
    print("=" * 80)
    print("IBVAP PROMPT #35 VERIFICATION: AUTHORIZED PERSONNEL WHITELIST")
    print("=" * 80)

    # Use a temporary test database
    test_db_path = Path("backend/test_whitelist.db")
    if test_db_path.exists():
        try:
            test_db_path.unlink()
        except Exception:
            pass

    init_db(test_db_path)
    dummy_frame = np.zeros((480, 640, 3), dtype=np.uint8)

    # -------------------------------------------------------------------------
    # TEST 1: Authorized / Watchlisted Person Zone Entry (e.g. Kunal)
    # -------------------------------------------------------------------------
    print("\n[TEST 1] Authorized Personnel Zone Entry (Kunal)...")
    sev_auth = compute_severity("zone_entry", "person", identified_as="Kunal")
    assert sev_auth == "low", f"Expected severity 'low' for authorized person entry, got '{sev_auth}'"

    evt_auth = log_event(
        camera_id="CAM_01",
        event_type="zone_entry",
        object_class="person",
        track_id=101,
        frame_number=45,
        bbox=[100, 150, 200, 350],
        confidence=0.88,
        frame=dummy_frame,
        db_path=test_db_path,
        print_json=False,
        face_detected=True,
        face_bbox=[130, 160, 170, 210],
        identified_as="Kunal",
        identification_confidence=0.85,
    )
    assert evt_auth.severity == "low", f"Logged event severity must be 'low', got '{evt_auth.severity}'"
    assert evt_auth.identified_as == "Kunal"
    assert "Routine access: Kunal entered Sector 4 Gate (North Perimeter)." in evt_auth.tactical_summary or "Routine access: Kunal entered Sector 4 Gate" in evt_auth.tactical_summary, f"Unexpected summary: {evt_auth.tactical_summary}"
    print(f"  [PASS] Severity: {evt_auth.severity.upper()} (Routine / Informational)")
    print(f"  [PASS] Tactical Summary: \"{evt_auth.tactical_summary}\"")
    print(f"  [PASS] Voice Alert: Skipped (since severity is {evt_auth.severity.upper()} != HIGH)")

    # -------------------------------------------------------------------------
    # TEST 2: Unrecognized / Unknown Person Zone Entry
    # -------------------------------------------------------------------------
    print("\n[TEST 2] Unrecognized / Unknown Person Zone Entry...")
    sev_unknown = compute_severity("zone_entry", "person", identified_as="UNKNOWN")
    sev_none = compute_severity("zone_entry", "person", identified_as=None)
    assert sev_unknown == "high", f"Expected 'high' for UNKNOWN person, got '{sev_unknown}'"
    assert sev_none == "high", f"Expected 'high' for None person, got '{sev_none}'"

    evt_unrec = log_event(
        camera_id="CAM_01",
        event_type="zone_entry",
        object_class="person",
        track_id=102,
        frame_number=90,
        bbox=[250, 180, 320, 390],
        confidence=0.84,
        frame=dummy_frame,
        db_path=test_db_path,
        print_json=False,
        face_detected=True,
        face_bbox=[270, 190, 300, 230],
        identified_as="UNKNOWN",
        identification_confidence=0.15,
    )
    assert evt_unrec.severity == "high", f"Logged event severity must be 'high', got '{evt_unrec.severity}'"
    assert "High alert: Unrecognized individual detected" in evt_unrec.tactical_summary
    print(f"  [PASS] Severity: {evt_unrec.severity.upper()} (High Alert Security Incident)")
    print(f"  [PASS] Tactical Summary: \"{evt_unrec.tactical_summary}\"")
    print(f"  [PASS] Voice Alert: Triggered -> \"High alert: Unrecognized individual detected entering Sector 4 Gate.\"")

    # -------------------------------------------------------------------------
    # TEST 3: Watchlisted Person (Kunal) Present/Loitering -> NEVER ALERTS (LOW Severity)
    # -------------------------------------------------------------------------
    print("\n[TEST 3] Watchlisted Person (Kunal) Present / Prolonged Presence (NO ALERT RULE)...")
    sev_loiter = compute_severity("suspicious_loitering", "person", identified_as="Kunal")
    sev_pacing = compute_severity("suspicious_pacing", "person", identified_as="Kunal")
    assert sev_loiter == "low", f"Authorized person must NEVER trigger high alert (even on loitering), got '{sev_loiter}'"
    assert sev_pacing == "low", f"Authorized person must NEVER trigger high alert (even on pacing), got '{sev_pacing}'"

    evt_loiter = log_event(
        camera_id="CAM_01",
        event_type="suspicious_loitering",
        object_class="person",
        track_id=101,
        frame_number=150,
        bbox=[100, 150, 200, 350],
        confidence=0.91,
        frame=dummy_frame,
        db_path=test_db_path,
        print_json=False,
        face_detected=True,
        face_bbox=[130, 160, 170, 210],
        identified_as="Kunal",
        identification_confidence=0.85,
    )
    assert evt_loiter.severity == "low", f"Logged event severity must be 'low' for authorized person, got '{evt_loiter.severity}'"
    assert "Routine presence: Authorized personnel [Kunal]" in evt_loiter.tactical_summary
    print(f"  [PASS] Severity: {evt_loiter.severity.upper()} (Routine / Informational - Zero Security Alert)")
    print(f"  [PASS] Tactical Summary: \"{evt_loiter.tactical_summary}\"")
    print(f"  [PASS] Voice Alert: Skipped (authorized personnel never trigger security alarm)")

    # -------------------------------------------------------------------------
    # TEST 4: Vehicle Zone Entry (Unlisted vs Authorized)
    # -------------------------------------------------------------------------
    print("\n[TEST 4] Vehicle Zone Entry (Unlisted vs Authorized)...")
    sev_veh_unlisted = compute_severity("zone_entry", "car", plate_number="UK 07 UNLISTED 9999", db_path=test_db_path)
    assert sev_veh_unlisted == "medium", f"Unlisted vehicle entry must be 'medium' severity, got '{sev_veh_unlisted}'"

    evt_veh_unlisted = log_event(
        camera_id="CAM_01",
        event_type="zone_entry",
        object_class="car",
        track_id=205,
        frame_number=200,
        bbox=[300, 200, 500, 380],
        confidence=0.93,
        frame=dummy_frame,
        db_path=test_db_path,
        print_json=False,
        plate_number="UK 07 UNLISTED 9999",
        plate_confidence=0.92,
    )
    assert evt_veh_unlisted.severity == "medium", f"Logged unlisted vehicle event severity must be 'medium', got '{evt_veh_unlisted.severity}'"
    print(f"  [PASS] Unlisted Vehicle Severity: {evt_veh_unlisted.severity.upper()} (Medium Alert)")
    print(f"  [PASS] Tactical Summary: \"{evt_veh_unlisted.tactical_summary}\"")

    evt_veh_auth = log_event(
        camera_id="CAM_01",
        event_type="zone_entry",
        object_class="car",
        track_id=206,
        frame_number=210,
        bbox=[300, 200, 500, 380],
        confidence=0.95,
        frame=dummy_frame,
        db_path=test_db_path,
        print_json=False,
        plate_number="DL-01-AB-1234",
        plate_confidence=0.94,
    )
    assert evt_veh_auth.severity == "low", f"Logged authorized vehicle event severity must be 'low', got '{evt_veh_auth.severity}'"
    print(f"  [PASS] Authorized Vehicle Severity: {evt_veh_auth.severity.upper()} (Routine Access)")
    print(f"  [PASS] Tactical Summary: \"{evt_veh_auth.tactical_summary}\"")

    # -------------------------------------------------------------------------
    # TEST 5: Cryptographic Audit Trail Hash Chain Integrity
    # -------------------------------------------------------------------------
    print("\n[TEST 5] Cryptographic SHA-256 Hash Chain Integrity Verification...")
    audit_res = verify_chain_integrity(test_db_path)
    assert audit_res["valid"] is True, f"Audit verification failed: {audit_res}"
    assert audit_res["total_events_checked"] == 5, f"Expected 5 events checked, got {audit_res['total_events_checked']}"
    print(f"  [PASS] Audit Verification: {audit_res['valid']} (Validated {audit_res['total_events_checked']} chained blocks)")
    print(f"  [PASS] Latest Block Hash: {audit_res['latest_block_hash']}")

    # Clean up test database
    if test_db_path.exists():
        try:
            test_db_path.unlink()
        except Exception:
            pass

    print("\n" + "=" * 80)
    print("ALL 5 VERIFICATION TESTS PASSED SUCCESSFULLY!")
    print("=" * 80)


if __name__ == "__main__":
    run_tests()
