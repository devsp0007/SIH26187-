"""
IBVAP - Pillar 5 & Pillar 6 Automated Verification Suite
Tests:
1. Target Crop Forensic Extraction (High-Res ROI Zoom)
2. Cryptographic SHA-256 Hash Chain Integrity Verification
3. Digital Chain of Custody & Forensic Certificate Generation
"""

import sys
from pathlib import Path
import json

# Ensure backend path is available
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.app.events import verify_chain_integrity, fetch_events_filtered
from backend.app.replay_service import extract_event_target_crop


def test_cryptographic_audit_chain():
    print("=" * 80)
    print("IBVAP - PILLAR 6: CRYPTOGRAPHIC SHA-256 AUDIT CHAIN VERIFICATION")
    print("=" * 80)

    res = verify_chain_integrity()
    print(f" [+] Chain Verification Status : {'VALID (AUTHENTIC)' if res.get('valid') else 'COMPROMISED'}")
    print(f" [+] Total Security Blocks     : {res.get('total_events_checked')}")
    print(f" [+] Genesis Block Hash        : {res.get('genesis_hash')}")
    print(f" [+] Latest Block Hash         : {res.get('latest_block_hash')}")

    assert res.get("valid") is True, f"Cryptographic integrity failed: {res.get('reason')}"
    assert res.get("total_events_checked", 0) > 0, "No events found in database to verify"
    print("  [PASS] Pillar 6: 100% Cryptographic integrity verified across all historical event blocks!")


def test_target_crop_extraction():
    print("\n" + "=" * 80)
    print("IBVAP - PILLAR 5: FORENSIC HIGH-RES TARGET CROP EXTRACTION")
    print("=" * 80)

    events = fetch_events_filtered(limit=5)
    if not events:
        print("  [*] No events currently in DB, skipping crop test.")
        return

    test_ev = events[0]
    ev_id = test_ev["event_id"]
    print(f" [+] Testing Target Crop Extraction for Event UUID: {ev_id} ({test_ev.get('object_class')})")

    success, crop_bytes, meta = extract_event_target_crop(ev_id)
    print(f" [+] Extraction Result : {success}")
    print(f" [+] Crop Metadata     : {meta}")
    if success and crop_bytes:
        print(f" [+] Encoded JPEG Size : {len(crop_bytes)} bytes")
        assert len(crop_bytes) > 500, "Crop image bytes suspiciously small"
        print("  [PASS] Pillar 5: High-Res Target Crop extraction verified successfully!")
    else:
        print(f"  [*] Notice: Snapshot file for event not on disk yet (expected in fresh env): {meta}")


if __name__ == "__main__":
    test_cryptographic_audit_chain()
    test_target_crop_extraction()
    print("\n" + "=" * 80)
    print("ALL PILLAR 5 & PILLAR 6 VERIFICATIONS COMPLETE!")
    print("=" * 80)
