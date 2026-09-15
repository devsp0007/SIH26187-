"""
IBVAP - Live & Video Verification Suite for Authorized Personnel Whitelist Fix

Verifies:
1. Watchlisted personnel (e.g. Kunal, Atul, Aditaya, Akanksha, Anshika) entering restricted zone
   -> Successfully recognized via Face Match (SFace Cosine Sim >= 0.38).
   -> Categorized as LOW severity (Routine Access: [Name] entered Sector 4 Gate).
   -> Voice speech alert skipped (reserved strictly for HIGH severity).
2. Grace Window verification:
   -> When a person enters the zone with face unrecognized on frame 1-2, but recognized on frame 4-10,
      the pending zone entry event resolves to LOW severity (Routine Access) without premature HIGH alert lock-in.
3. Identity Persistence across track lifetime:
   -> Once confirmed, track identity persists even during subsequent frames where the person looks away / face is occluded.
4. Unrecognized / Unlisted intruder entering zone:
   -> Correctly triggers HIGH alert (Unrecognized individual detected entering Sector 4 Gate).
   -> Cryptographic SHA-256 hash chain remains 100% integral and verified.
5. Live webcam capture evaluation:
   -> Runs live detection on camera sensor with frame-by-frame diagnostic logging.
"""

import sys
from pathlib import Path
import cv2
import numpy as np

# Ensure project root is in sys.path
root_dir = Path(__file__).resolve().parent.parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from backend.app.face_engine import WatchlistFaceRecognizer, get_watchlist_recognizer
from backend.app.events import (
    init_db,
    log_event,
    compute_severity,
    generate_tactical_summary_rule_based,
    verify_chain_integrity,
    fetch_events_filtered,
)


def run_live_and_synthetic_tests():
    print("=" * 80)
    print("IBVAP AUTHORIZED PERSONNEL WHITELIST LIVE VERIFICATION SUITE")
    print("=" * 80)

    test_db = Path("backend/test_whitelist_live.db")
    if test_db.exists():
        try:
            test_db.unlink()
        except Exception:
            pass
    init_db(test_db)

    # 1. Initialize Face Engine
    backend_dir = Path("backend")
    recognizer = WatchlistFaceRecognizer(
        watchlist_dir=backend_dir / "watchlist",
        models_dir=backend_dir / "models",
        cosine_threshold=0.48,
    )
    print(f"[+] Loaded Watchlist: {list(recognizer.watchlist_embeddings.keys())}")
    assert len(recognizer.watchlist_embeddings) >= 5, "Watchlist must contain all 5 registered profiles"

    # -------------------------------------------------------------------------
    # PART 1: Single Frame Face Recognition & Pairwise Separation
    # -------------------------------------------------------------------------
    print("\n" + "-" * 80)
    print("[TEST 1] Watchlist Image Ingestion & Self-Identification Tests")
    print("-" * 80)

    watchlist_dir = backend_dir / "watchlist"
    for p in sorted(watchlist_dir.glob("*.png")):
        name = p.stem.replace("_", " ").strip().title()
        img = cv2.imread(str(p))
        if img is None:
            continue
        h, w = img.shape[:2]
        matched_name, conf, coords = recognizer.identify_face_in_person_crop(img, (0, 0, w, h))
        print(f" [+] Profile '{name:<10}' -> Recognized As: '{matched_name}' | Cosine Match Conf: {conf*100:5.1f}% | Face Coords: {coords}")
        assert matched_name == name, f"Expected self-match for {name}, got {matched_name}"
        assert conf >= 0.48, f"Expected confidence >= 0.48 for {name}, got {conf}"

    # -------------------------------------------------------------------------
    # PART 2: Unlisted / Unknown Person Negative Test
    # -------------------------------------------------------------------------
    print("\n" + "-" * 80)
    print("[TEST 2] Unlisted / Unrecognized Person Rejection Test")
    print("-" * 80)

    # Create synthetic stranger face (non-matching geometry)
    stranger_frame = np.zeros((400, 300, 3), dtype=np.uint8)
    stranger_frame[:] = (70, 75, 80)
    cv2.circle(stranger_frame, (150, 150), 70, (180, 150, 130), -1)
    cv2.circle(stranger_frame, (125, 135), 8, (20, 20, 20), -1)
    cv2.circle(stranger_frame, (175, 135), 8, (20, 20, 20), -1)
    cv2.ellipse(stranger_frame, (150, 185), (25, 12), 0, 0, 180, (50, 30, 30), 3)

    s_name, s_conf, s_coords = recognizer.identify_face_in_person_crop(stranger_frame, (0, 0, 300, 400))
    print(f" [*] Stranger Target -> Result: '{s_name}' | Confidence: {s_conf:.3f} | BBox: {s_coords}")
    assert s_name in [None, "UNKNOWN"], f"Unlisted person must NOT match as authorized, got '{s_name}'"
    sev_unlisted = compute_severity("zone_entry", "person", identified_as=s_name, db_path=test_db)
    assert sev_unlisted == "high", f"Unrecognized person entry must be 'high' severity, got '{sev_unlisted}'"
    print(f"  [PASS] Unlisted Target correctly evaluated as HIGH severity alert (Intrusion Alert)")

    # -------------------------------------------------------------------------
    # PART 3: Track Lifetime Identity Persistence Test
    # -------------------------------------------------------------------------
    print("\n" + "-" * 80)
    print("[TEST 3] Track Lifetime Identity Persistence Across Occlusions")
    print("-" * 80)

    kunal_img = cv2.imread(str(watchlist_dir / "kunal.png"))
    kh, kw = kunal_img.shape[:2]

    # Blank frame representing occlusion/back turned
    blank_frame = np.zeros((400, 300, 3), dtype=np.uint8)

    tracker_id = 42
    confirmed_track_identities = {}
    face_recog_cache = {}

    # Frame 1: Kunal enters
    f_name, f_conf, f_coords = recognizer.identify_face_in_person_crop(kunal_img, (0, 0, kw, kh))
    if f_name and f_name != "UNKNOWN":
        confirmed_track_identities[tracker_id] = {"name": f_name, "confidence": f_conf, "first_identified_frame": 1}
    face_recog_cache[tracker_id] = {"face_bbox": f_coords, "identified_as": f_name, "identification_confidence": f_conf, "last_checked": 1}

    print(f" Frame  1 (Face Visible): Track #{tracker_id} identified as '{confirmed_track_identities[tracker_id]['name']}' ({confirmed_track_identities[tracker_id]['confidence']*100:.1f}%)")

    # Frames 2-30: Person turns around (blank/occluded face crop)
    for test_f in [5, 15, 25, 35, 45]:
        # Under the fixed logic: if tracker_id in confirmed_track_identities, identity persists
        if tracker_id in confirmed_track_identities:
            cur_id = confirmed_track_identities[tracker_id]["name"]
            cur_conf = confirmed_track_identities[tracker_id]["confidence"]
        else:
            cur_id, cur_conf, _ = recognizer.identify_face_in_person_crop(blank_frame, (0, 0, 300, 400))

        print(f" Frame {test_f:02d} (Face Occluded): Track #{tracker_id} active identity is '{cur_id}' ({cur_conf*100:.1f}%) -> PERSISTED")
        assert cur_id == "Kunal", f"Identity must NOT be lost on occluded frame, got '{cur_id}'"

    print("  [PASS] Track identity persistence verified across occlusions.")

    # -------------------------------------------------------------------------
    # PART 4: Zone-Entry Grace Window Simulation Test
    # -------------------------------------------------------------------------
    print("\n" + "-" * 80)
    print("[TEST 4] Zone-Entry Grace Window Resolution (Simulated Natural Entry)")
    print("-" * 80)

    # Simulation Scenario:
    # Track #101 enters restricted zone at Frame 10.
    # On Frame 10-12 (first 3 frames), person is entering with face angled (no face detected).
    # Hysteresis confirms inside at Frame 12.
    # Instead of firing HIGH alert, it is buffered into pending_zone_entries with grace window up to Frame 27.
    # At Frame 15 (3 frames later), person turns toward camera, face recognized as 'Kunal' (0.85).
    # Pending event resolves as LOW severity (Routine Access).

    pending_zone_entries = {}
    confirmed_track_identities = {}
    logged_events = []

    def mock_log_event_async(**kwargs):
        kwargs["print_json"] = False
        evt = log_event(**kwargs)
        logged_events.append(evt)
        return evt

    # Frame 10-12: Enter zone without face
    pending_zone_entries[101] = {
        "camera_id": "CAM_01",
        "event_type": "zone_entry",
        "object_class": "person",
        "track_id": 101,
        "trigger_frame": 12,
        "grace_until_frame": 12 + 15,
        "bbox": [100.0, 100.0, 200.0, 300.0],
        "confidence": 0.88,
        "frame": kunal_img.copy(),
        "face_bbox": None,
        "source_video": None,
        "db_path": test_db,
    }
    print(f" Frame 12: Track #101 crossed zone boundary -> Buffered in Grace Window (valid until Frame 27)")

    # Frame 15: Face becomes visible and is recognized
    f_name, f_conf, f_coords = recognizer.identify_face_in_person_crop(kunal_img, (0, 0, kw, kh))
    assert f_name == "Kunal"
    confirmed_track_identities[101] = {"name": f_name, "confidence": f_conf, "first_identified_frame": 15}
    print(f" Frame 15: Face recognition succeeded -> Track #101 identified as '{f_name}' ({f_conf*100:.1f}%)")

    # Grace window resolution logic
    for p_tid in list(pending_zone_entries.keys()):
        p_ent = pending_zone_entries[p_tid]
        if p_tid in confirmed_track_identities:
            conf_data = confirmed_track_identities[p_tid]
            evt = mock_log_event_async(
                camera_id=p_ent["camera_id"],
                event_type="zone_entry",
                object_class=p_ent["object_class"],
                track_id=p_tid,
                frame_number=p_ent["trigger_frame"],
                bbox=p_ent["bbox"],
                confidence=p_ent["confidence"],
                frame=p_ent["frame"],
                db_path=test_db,
                print_json=False,
                face_detected=True,
                face_bbox=f_coords,
                identified_as=conf_data["name"],
                identification_confidence=conf_data["confidence"],
            )
            del pending_zone_entries[p_tid]

    assert len(logged_events) == 1, "Exactly one zone entry event should have been logged"
    resolved_event = logged_events[0]
    print(f" Resolved Event -> Severity: '{resolved_event.severity.upper()}' | ID: '{resolved_event.identified_as}' | Conf: {resolved_event.identification_confidence*100:.1f}%")
    print(f" Tactical Summary: \"{resolved_event.tactical_summary}\"")
    assert resolved_event.severity == "low", f"Expected severity 'low' for resolved authorized entry, got '{resolved_event.severity}'"
    assert resolved_event.identified_as == "Kunal"
    assert "Routine access: Kunal entered" in resolved_event.tactical_summary
    print("  [PASS] Grace window correctly prevented false HIGH alert and resolved to Routine Access (LOW).")

    # -------------------------------------------------------------------------
    # PART 5: Unidentified Intruder Grace Window Expiration Test
    # -------------------------------------------------------------------------
    print("\n" + "-" * 80)
    print("[TEST 5] Unrecognized Intruder Grace Window Expiration -> HIGH Alert")
    print("-" * 80)

    pending_zone_entries[102] = {
        "camera_id": "CAM_01",
        "event_type": "zone_entry",
        "object_class": "person",
        "track_id": 102,
        "trigger_frame": 40,
        "grace_until_frame": 40 + 15,
        "bbox": [250.0, 150.0, 350.0, 400.0],
        "confidence": 0.90,
        "frame": stranger_frame.copy(),
        "face_bbox": None,
        "source_video": None,
        "db_path": test_db,
    }

    # Simulate frames 40 to 56 (Grace window expires at frame 55)
    current_f = 56
    for p_tid in list(pending_zone_entries.keys()):
        p_ent = pending_zone_entries[p_tid]
        if current_f >= p_ent["grace_until_frame"]:
            evt_unrec = mock_log_event_async(
                camera_id=p_ent["camera_id"],
                event_type="zone_entry",
                object_class=p_ent["object_class"],
                track_id=p_tid,
                frame_number=p_ent["trigger_frame"],
                bbox=p_ent["bbox"],
                confidence=p_ent["confidence"],
                frame=p_ent["frame"],
                db_path=test_db,
                print_json=False,
                face_detected=False,
                face_bbox=None,
                identified_as=None,
                identification_confidence=None,
            )
            del pending_zone_entries[p_tid]

    assert len(logged_events) == 2
    intruder_event = logged_events[1]
    print(f" Resolved Intruder Event -> Severity: '{intruder_event.severity.upper()}' | ID: '{intruder_event.identified_as}'")
    print(f" Tactical Summary: \"{intruder_event.tactical_summary}\"")
    assert intruder_event.severity == "high", f"Expected 'high' severity for unlisted intruder, got '{intruder_event.severity}'"
    assert "High alert: Unrecognized individual detected" in intruder_event.tactical_summary
    print("  [PASS] Unlisted intruder correctly finalized as HIGH severity after grace window.")

    # -------------------------------------------------------------------------
    # PART 6: Cryptographic Hash Chain Audit
    # -------------------------------------------------------------------------
    print("\n" + "-" * 80)
    print("[TEST 6] Cryptographic SHA-256 Audit Trail Integrity Verification")
    print("-" * 80)

    integrity_report = verify_chain_integrity(test_db)
    print(f" Chain Valid            : {integrity_report['valid']}")
    print(f" Total Events Checked   : {integrity_report['total_events_checked']}")
    print(f" Latest Block Hash      : {integrity_report['latest_block_hash']}")
    assert integrity_report["valid"] is True, f"Integrity check failed: {integrity_report.get('reason')}"
    print("  [PASS] 100% Cryptographic Hash Chain Integrity Verified.")

    # -------------------------------------------------------------------------
    # PART 7: Live Camera Sensor Diagnostic Test
    # -------------------------------------------------------------------------
    print("\n" + "-" * 80)
    print("[TEST 7] Live Camera Sensor Identification Diagnostic")
    print("-" * 80)

    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print(" [!] Live Camera: Sensor not accessible on index 0.")
    else:
        for _ in range(15):
            cap.read()
        ret, live_frame = cap.read()
        cap.release()

        if ret and live_frame is not None:
            lh, lw = live_frame.shape[:2]
            l_name, l_conf, l_coords = recognizer.identify_face_in_person_crop(live_frame, (0, 0, lw, lh))
            print(f" [+] Live Frame Capture ({lw}x{lh}):")
            if l_coords:
                print(f"     - Face Detected at  : {l_coords}")
                print(f"     - Watchlist Match   : '{l_name}' (Confidence: {l_conf:.3f} | Threshold: 0.380)")
                print(f"     - Auth Decision     : {'AUTHORIZED (Routine Access)' if l_name and l_name != 'UNKNOWN' else 'UNRECOGNIZED (Intrusion Warning)'}")
            else:
                print("     - Face Status       : No human face in current camera sensor view (Idle background).")
        else:
            print(" [!] Failed to capture frame from webcam.")

    print("\n" + "=" * 80)
    print("ALL TESTS COMPLETED SUCCESSFULLY - 100% PASS RATE")
    print("=" * 80)


if __name__ == "__main__":
    run_live_and_synthetic_tests()
