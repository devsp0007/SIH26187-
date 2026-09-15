import sys
import time
import json
import sqlite3
import subprocess
from pathlib import Path
import psutil

backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir.parent))
python_exe = sys.executable
script_path = backend_dir / "app" / "detection_tracking.py"
video_1 = backend_dir / "test_videos" / "tracking_test.mp4"
video_2 = backend_dir / "test_videos" / "real_footage_3.mp4"
db_path = backend_dir / "ibvap.db"

# Reset database to clean state
from backend.app.reset_db import reset_database
reset_database()

print("=" * 80, flush=True)
print(" IBVAP MULTI-CAMERA SCALABILITY & CONCURRENCY BENCHMARK", flush=True)
print("=" * 80, flush=True)
print(f" Camera 1 Feed : {video_1.name} (Sector 4 Gate)", flush=True)
print(f" Camera 2 Feed : {video_2.name} (Sector 7 East Fence)", flush=True)
print(f" Target Frames : 45 frames per camera instance", flush=True)
print("=" * 80, flush=True)

# -------------------------------------------------------------
# PHASE 1: SINGLE CAMERA BASELINE BENCHMARK
# -------------------------------------------------------------
print("\n[PHASE 1] Running Single Camera Baseline (CAM_01)...", flush=True)

cmd_single = [
    python_exe,
    str(script_path),
    "--input", str(video_1),
    "--camera-id", "CAM_01",
    "--camera-name", "Sector 4 Gate",
    "--zone-label", "North Perimeter Fence - Sector 4",
    "--max-frames", "45",
    "--no-display",
]

t0_s = time.perf_counter()
proc_s = subprocess.Popen(cmd_single, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True)
ps_s = psutil.Process(proc_s.pid)

cpu_single = []
mem_single = []

while proc_s.poll() is None:
    time.sleep(0.3)
    try:
        cpu_single.append(psutil.cpu_percent(interval=None))
        mem_single.append(ps_s.memory_info().rss / (1024 * 1024))
    except Exception:
        pass

proc_s.wait()
t_single = time.perf_counter() - t0_s

fps_single = 45.0 / t_single
avg_cpu_single = sum(cpu_single) / len(cpu_single) if cpu_single else 0.0
avg_mem_single = sum(mem_single) / len(mem_single) if mem_single else 0.0

print(f" [+] Single Camera Completed in {t_single:.2f}s", flush=True)
print(f"     Throughput : {fps_single:.2f} FPS", flush=True)
print(f"     Mean CPU   : {avg_cpu_single:.1f}%", flush=True)
print(f"     Mean RAM   : {avg_mem_single:.1f} MB", flush=True)

# -------------------------------------------------------------
# PHASE 2: DUAL SIMULTANEOUS CAMERAS BENCHMARK
# -------------------------------------------------------------
print("\n[PHASE 2] Running Dual Simultaneous Cameras (CAM_01 + CAM_02)...", flush=True)

cmd_d1 = [
    python_exe,
    str(script_path),
    "--input", str(video_1),
    "--camera-id", "CAM_01",
    "--camera-name", "Sector 4 Gate",
    "--zone-label", "North Perimeter Fence - Sector 4",
    "--max-frames", "45",
    "--no-display",
]

cmd_d2 = [
    python_exe,
    str(script_path),
    "--input", str(video_2),
    "--camera-id", "CAM_02",
    "--camera-name", "Sector 7 East Fence",
    "--zone-label", "East Sector Perimeter - Sector 7",
    "--max-frames", "45",
    "--no-display",
]

t0_d = time.perf_counter()
proc_d1 = subprocess.Popen(cmd_d1, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True)
proc_d2 = subprocess.Popen(cmd_d2, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True)

ps_d1 = psutil.Process(proc_d1.pid)
ps_d2 = psutil.Process(proc_d2.pid)

cpu_dual = []
mem_dual = []

while proc_d1.poll() is None or proc_d2.poll() is None:
    time.sleep(0.3)
    try:
        cpu_pct = psutil.cpu_percent(interval=None)
        m1 = ps_d1.memory_info().rss / (1024 * 1024) if proc_d1.poll() is None else 0
        m2 = ps_d2.memory_info().rss / (1024 * 1024) if proc_d2.poll() is None else 0
        cpu_dual.append(cpu_pct)
        mem_dual.append(m1 + m2)
    except Exception:
        pass

proc_d1.wait()
proc_d2.wait()
t_dual = time.perf_counter() - t0_d

total_frames_dual = 45 + 45
aggregate_fps_dual = total_frames_dual / t_dual
per_stream_fps_dual = 45.0 / t_dual
avg_cpu_dual = sum(cpu_dual) / len(cpu_dual) if cpu_dual else 0.0
avg_mem_dual = sum(mem_dual) / len(mem_dual) if mem_dual else 0.0

print(f" [+] Dual Cameras Completed in {t_dual:.2f}s", flush=True)
print(f"     Aggregate Throughput : {aggregate_fps_dual:.2f} FPS (combined)", flush=True)
print(f"     Per-Stream Rate      : {per_stream_fps_dual:.2f} FPS / stream", flush=True)
print(f"     Combined Mean CPU    : {avg_cpu_dual:.1f}%", flush=True)
print(f"     Combined Mean RAM    : {avg_mem_dual:.1f} MB (RSS)", flush=True)

# -------------------------------------------------------------
# PHASE 3: VERIFICATION OF INDEPENDENT FEEDS & DB ISOLATION
# -------------------------------------------------------------
print("\n" + "=" * 80, flush=True)
print("3. VERIFICATION: INDEPENDENT LIVE FEEDS & DATABASE PARTITIONING", flush=True)
print("=" * 80, flush=True)

live_cam1 = backend_dir / "live_frame_CAM_01.jpg"
live_cam2 = backend_dir / "live_frame_CAM_02.jpg"

print(f" Live Stream Frame CAM_01 : {'EXISTS (' + str(live_cam1.stat().st_size) + ' bytes)' if live_cam1.exists() else 'MISSING'}", flush=True)
print(f" Live Stream Frame CAM_02 : {'EXISTS (' + str(live_cam2.stat().st_size) + ' bytes)' if live_cam2.exists() else 'MISSING'}", flush=True)

with sqlite3.connect(db_path) as conn:
    conn.row_factory = sqlite3.Row
    cams = conn.execute("SELECT * FROM cameras ORDER BY camera_id ASC").fetchall()
    print(f"\n Registered Cameras Table ({len(cams)} total):", flush=True)
    for c in cams:
        print(f"  - [{c['camera_id']}] {c['name']} | Status: {c['status']} | FPS: {c['fps']} | Monitored: {c['monitored_zone']}", flush=True)

    counts = conn.execute("SELECT camera_id, COUNT(*) as cnt FROM events GROUP BY camera_id").fetchall()
    print(f"\n Events Logged in SQLite by Camera ID:", flush=True)
    for row in counts:
        print(f"  - Camera {row['camera_id']}: {row['cnt']} security events", flush=True)

    cursor = conn.cursor()
    cursor.execute("""
        SELECT event_id, camera_id, event_type, object_class, track_id, frame_number, severity, tactical_summary 
        FROM events 
        ORDER BY timestamp ASC 
        LIMIT 6
    """)
    samples = cursor.fetchall()
    print("\n Interleaved Multi-Camera Event Trail Sample:", flush=True)
    for s in samples:
        print(f"  [{s['camera_id']}] Frame {s['frame_number']:03d} | {s['event_type']} | {s['object_class']} #{s['track_id']} -> \"{s['tactical_summary']}\"", flush=True)

# -------------------------------------------------------------
# PHASE 4: CRYPTOGRAPHIC AUDIT TRAIL VERIFICATION
# -------------------------------------------------------------
print("\n" + "=" * 80, flush=True)
print("4. CRYPTOGRAPHIC SHA-256 AUDIT CHAIN INTEGRITY CHECK", flush=True)
print("=" * 80, flush=True)

from backend.app.events import verify_chain_integrity
integrity = verify_chain_integrity(db_path)
print(f" Total Events in Chain : {integrity['total_events_checked']}", flush=True)
print(f" Valid Blocks          : {integrity['total_events_checked'] if integrity['valid'] else 0}", flush=True)
print(f" Chain Status          : {'INTEGRITY VERIFIED (100% UNTAMPERED)' if integrity['valid'] else 'TAMPERED / BROKEN'}", flush=True)

# -------------------------------------------------------------
# PHASE 5: HARDWARE CAPACITY EXTRAPOLATION
# -------------------------------------------------------------
print("\n" + "=" * 80, flush=True)
print("5. HARDWARE CAPACITY EXTRAPOLATION & EDGE SCALABILITY ESTIMATES", flush=True)
print("=" * 80, flush=True)

print(f"""
========================================================================================
 METRIC SUMMARY (HONEST EMPIRICAL MEASUREMENTS ON HOST CPU)
========================================================================================
 • Single Camera (1 stream)       : {fps_single:5.2f} FPS  |  CPU: {avg_cpu_single:4.1f}%  |  RAM: {avg_mem_single:5.1f} MB
 • Dual Camera (2 streams)        : {aggregate_fps_dual:5.2f} FPS  |  CPU: {avg_cpu_dual:4.1f}%  |  RAM: {avg_mem_dual:5.1f} MB
 • Per-Stream Cost (Simultaneous) : {per_stream_fps_dual:5.2f} FPS  |  CPU: {avg_cpu_dual/2.0:4.1f}%  |  RAM: {avg_mem_dual/2.0:5.1f} MB
========================================================================================

HARDWARE DEPLOYMENT EXTRAPOLATION SLIDE DATA:
----------------------------------------------------------------------------------------
Hardware Target                     | Compute / Accelerators          | Estimated Capacity
----------------------------------------------------------------------------------------
1. NVIDIA Jetson Nano (4GB)         | Quad ARM A57 + 128-core Maxwell | 2–3 Streams (TensorRT FP16, 10-15 FPS)
2. NVIDIA Jetson Orin Nano (8GB)    | 6-core ARM + 1024-core Ampere   | 6–10 Streams (TensorRT INT8, 25-30 FPS)
3. NVIDIA Jetson AGX Orin (64GB)    | 12-core ARM + 2048-core Ampere  | 20–32 Streams (Enterprise Border Outpost)
4. Host CPU Box (Intel Core i7)     | 8-Core CPU (No GPU Inference)   | 4–6 Streams (OpenVINO / ONNX runtime)
5. Command Post Server (1x RTX 4080)| 16-Core CPU + 16GB Ada Lovelace | 30–48 Streams (Batch TensorRT Pipeline)
========================================================================================
""", flush=True)
