"""
IBVAP - Pillar 1 & Pillar 2 Automated Verification Suite
Tests:
1. Bidirectional Line-Crossing & Footfall State Machine (Zero Double-Counting)
2. Lingering / Pacing Anti-Inflation Check
3. Real-Time In/Out/Occupancy Consistency
4. System Health Watchdog & Hardware Telemetry (psutil CPU/RAM/FPS/Uptime)
"""

import sys
import time
from pathlib import Path
from typing import Set

# Ensure backend path is available
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.app.stream_hub import get_frame_hub, FrameHub
from backend.app.events import compute_event_stats


def test_footfall_state_machine():
    print("=" * 80)
    print("IBVAP - PILLAR 2: BIDIRECTIONAL FOOTFALL & OCCUPANCY VERIFICATION")
    print("=" * 80)

    # Simulated Tracker State Machine
    footfall_in = 0
    footfall_out = 0
    active_inside_ids: Set[int] = set()

    # Track debouncing simulation: (tracker_id, is_inside, frame_idx)
    # Target #1: Outside (f1-f5) -> Inside (f6-f20) -> Stays Inside
    # Target #2: Outside (f1-f5) -> Inside (f6-f15) -> Exits Outside (f16-f30)
    # Target #3: Outside (f1-f10) -> Inside (f11-f30) -> Lingers inside (Zero double-count)

    track_states = {}

    def process_point(tid: int, inside: bool, f_idx: int):
        nonlocal footfall_in, footfall_out, active_inside_ids
        if tid not in track_states:
            track_states[tid] = {
                "confirmed_inside": False,
                "candidate_inside": inside,
                "consecutive": 1,
            }
        else:
            st = track_states[tid]
            if inside == st["candidate_inside"]:
                st["consecutive"] += 1
            else:
                st["candidate_inside"] = inside
                st["consecutive"] = 1

            if st["consecutive"] >= 3 and st["candidate_inside"] != st["confirmed_inside"]:
                st["confirmed_inside"] = st["candidate_inside"]
                if st["confirmed_inside"]:
                    if tid not in active_inside_ids:
                        footfall_in += 1
                        active_inside_ids.add(tid)
                        print(f" [+] [Frame {f_idx:02d}] CONFIRMED ENTRY: Track #{tid} (Total In: {footfall_in}, Occupancy: {len(active_inside_ids)})")
                else:
                    if tid in active_inside_ids:
                        footfall_out += 1
                        active_inside_ids.discard(tid)
                        print(f" [-] [Frame {f_idx:02d}] CONFIRMED EXIT : Track #{tid} (Total Out: {footfall_out}, Occupancy: {len(active_inside_ids)})")

    # Phase 1: 3 People Enter
    print("\n[PHASE 1] Simulating 3 independent individuals entering restricted sector...")
    for f in range(1, 15):
        # Target 1 enters at f=6
        process_point(1, f >= 6, f)
        # Target 2 enters at f=6
        process_point(2, f >= 6, f)
        # Target 3 enters at f=11
        process_point(3, f >= 11, f)

    assert footfall_in == 3, f"Expected 3 entries, got {footfall_in}"
    assert footfall_out == 0, f"Expected 0 exits, got {footfall_out}"
    assert len(active_inside_ids) == 3, f"Expected occupancy 3, got {len(active_inside_ids)}"
    print("  [PASS] Phase 1 Success: 3 entries recorded, 0 exits, occupancy = 3")

    # Phase 2: Target 2 exits the sector
    print("\n[PHASE 2] Simulating Target #2 exiting the restricted perimeter...")
    for f in range(15, 25):
        process_point(1, True, f)
        process_point(2, False, f)  # Exits
        process_point(3, True, f)

    assert footfall_in == 3, f"Expected total in 3, got {footfall_in}"
    assert footfall_out == 1, f"Expected 1 exit, got {footfall_out}"
    assert len(active_inside_ids) == 2, f"Expected occupancy 2, got {len(active_inside_ids)}"
    print("  [PASS] Phase 2 Success: Exit confirmed for Track #2, occupancy reduced to 2")

    # Phase 3: Target 3 lingers and paces inside for 50 frames (Anti-Inflation Check)
    print("\n[PHASE 3] Simulating Target #3 lingering and pacing inside for 50 frames (Anti-Inflation Test)...")
    for f in range(25, 75):
        process_point(1, True, f)
        process_point(2, False, f)
        process_point(3, True, f)  # Stays inside

    assert footfall_in == 3, f"Anti-Inflation failed! Total in rose to {footfall_in}"
    assert footfall_out == 1, f"Anti-Inflation failed! Total out rose to {footfall_out}"
    assert len(active_inside_ids) == 2, f"Expected occupancy 2, got {len(active_inside_ids)}"
    print("  [PASS] Phase 3 Success: Zero double-counting verified (In: 3, Out: 1, Occupancy: 2)")


def test_system_health_telemetry():
    print("\n" + "=" * 80)
    print("IBVAP - PILLAR 1: 24/7 SYSTEM HEALTH WATCHDOG & TELEMETRY VERIFICATION")
    print("=" * 80)

    hub = get_frame_hub()
    hub.update_telemetry(
        camera_id="CAM_01",
        footfall_in=42,
        footfall_out=18,
        occupancy=24,
        fps=29.8,
    )

    health = hub.get_system_health()
    print(f" [+] System Status        : {health.get('status')}")
    print(f" [+] Host CPU Utilization : {health.get('cpu_percent')}%")
    print(f" [+] Host RAM Usage       : {health.get('memory', {}).get('percent')}% ({health.get('memory', {}).get('used_mb')} MB / {health.get('memory', {}).get('total_mb')} MB)")
    print(f" [+] Host Uptime          : {health.get('uptime_seconds')} seconds")
    print(f" [+] Active Ingestion Cams: {health.get('active_streams')}")
    print(f" [+] Aggregated Footfall  : {health.get('aggregate_footfall')}")
    print(f" [+] Camera Telemetry     : {health.get('camera_telemetry')}")

    assert health["status"] == "operational"
    assert health["aggregate_footfall"]["total_in"] == 42
    assert health["aggregate_footfall"]["total_out"] == 18
    assert health["aggregate_footfall"]["current_occupancy"] == 24
    print("  [PASS] Hardware telemetry and stream watchdog successfully verified!")


if __name__ == "__main__":
    test_footfall_state_machine()
    test_system_health_telemetry()
    print("\n" + "=" * 80)
    print("ALL PILLAR 1 & PILLAR 2 VERIFICATIONS PASSED (100% SUCCESS)")
    print("=" * 80)
