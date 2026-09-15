"""
IBVAP - Intelligent Border Video Analytics Platform
Step 6: Structured Event Schema, SQLite Storage, Metrics & Deduplicated WebSocket Dispatch

Provides:
- SecurityEvent schema
- SQLite persistence (backend/ibvap.db) with parameterized queries and filtering
- Dynamic metrics computation (total events, severity breakdown, class distribution)
- Automatic snapshot saving (backend/snapshots/{event_id}.jpg)
- Real-time event publishing hook to WebSocket clients (with strict deduplication)
"""

import hashlib
import json
import sqlite3
import urllib.request
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
import queue
import threading
from typing import Any, Callable, List, Literal, Optional
import cv2
import numpy as np


try:
    from backend.app.stream_hub import get_frame_hub
except ImportError:
    try:
        from stream_hub import get_frame_hub
    except ImportError:
        get_frame_hub = lambda: None

try:
    from backend.app.auth import init_users_table
    from backend.app.admin_management import (
        init_admin_tables,
        check_watchlist_person_active,
        check_authorized_vehicle,
    )
except ImportError:
    try:
        from auth import init_users_table
        from admin_management import (
            init_admin_tables,
            check_watchlist_person_active,
            check_authorized_vehicle,
        )
    except ImportError:
        init_users_table = None
        init_admin_tables = None
        check_watchlist_person_active = lambda name, db_path=None: bool(name and str(name).upper() != "UNKNOWN")
        check_authorized_vehicle = lambda plate, db_path=None: None

EventType = Literal["zone_entry", "zone_exit", "auth_login_success", "auth_login_failed"]
SeverityLevel = Literal["high", "medium", "low"]

# Cryptographic Genesis String for Blockchain-Style Tamper-Evident Audit Logging
GENESIS_HASH: str = "IBVAP_GENESIS_BLOCK_000000000000000000000000000000000000000000000000"


def compute_event_payload_hash(
    prev_hash: str,
    event_id: str,
    camera_id: str,
    event_type: str,
    object_class: str,
    track_id: int,
    timestamp: str,
    frame_number: int,
    confidence: float,
    severity: str,
    face_detected: bool = False,
    plate_number: Optional[str] = None,
    identified_as: Optional[str] = None,
) -> str:
    """
    Compute cryptographic SHA-256 hash chaining previous block hash with core event payload.
    Ensures tamper-evidence across all critical attributes (including severity, type, track, face detection, plate number, identified identity, etc.).
    """
    conf_str = f"{confidence:.3f}"
    face_str = "1" if face_detected else "0"
    plate_str = str(plate_number).strip().upper() if plate_number else "NONE"
    id_str = str(identified_as).strip().upper() if identified_as else "UNKNOWN"
    payload = (
        f"{prev_hash}|{event_id}|{camera_id}|{event_type}|{object_class}|{track_id}|"
        f"{timestamp}|{frame_number}|{conf_str}|{severity}|{face_str}|{plate_str}|{id_str}"
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def get_latest_event_hash(db_path: Optional[Path] = None) -> str:
    """Get the cryptographic SHA-256 hash of the most recently logged event."""
    if db_path is None:
        db_path = get_default_db_path()

    if not db_path.exists():
        return GENESIS_HASH

    try:
        with sqlite3.connect(db_path, timeout=10.0) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT event_hash FROM events WHERE event_hash IS NOT NULL AND event_hash != '' ORDER BY rowid DESC LIMIT 1"
            )
            row = cursor.fetchone()
            if row and row[0]:
                return row[0]
    except Exception:
        pass
    return GENESIS_HASH

# In-memory hook for in-process WebSocket connection manager
_in_process_event_listeners: List[Callable[[dict[str, Any]], Any]] = []

# Background non-blocking event worker queue
_event_queue: queue.Queue = queue.Queue(maxsize=500)
_worker_thread: Optional[threading.Thread] = None


def _event_worker_loop():
    """Background worker to save snapshots, commit SQLite rows, and dispatch webhooks without blocking video tracking."""
    while True:
        try:
            item = _event_queue.get()
            if item is None:
                break
            log_event(
                camera_id=item["camera_id"],
                event_type=item["event_type"],
                object_class=item["object_class"],
                track_id=item["track_id"],
                frame_number=item["frame_number"],
                bbox=item["bbox"],
                confidence=item["confidence"],
                frame=item["frame"],
                db_path=item["db_path"],
                print_json=item["print_json"],
                face_detected=item.get("face_detected", False),
                face_bbox=item.get("face_bbox", None),
                plate_number=item.get("plate_number", None),
                plate_confidence=item.get("plate_confidence", None),
                plate_bbox=item.get("plate_bbox", None),
                identified_as=item.get("identified_as", None),
                identification_confidence=item.get("identification_confidence", None),
                source_video=item.get("source_video", None),
                session_id=item.get("session_id", None),
            )
        except Exception:
            pass
        finally:
            _event_queue.task_done()


def start_async_event_logger():
    """Ensure the background event persistence worker is active."""
    global _worker_thread
    if _worker_thread is None or not _worker_thread.is_alive():
        _worker_thread = threading.Thread(target=_event_worker_loop, daemon=True)
        _worker_thread.start()


def log_event_async(
    camera_id: str,
    event_type: EventType,
    object_class: str,
    track_id: int,
    frame_number: int,
    bbox: List[float],
    confidence: float,
    frame: np.ndarray,
    db_path: Optional[Path] = None,
    print_json: bool = True,
    face_detected: bool = False,
    face_bbox: Optional[List[float]] = None,
    plate_number: Optional[str] = None,
    plate_confidence: Optional[float] = None,
    plate_bbox: Optional[List[float]] = None,
    identified_as: Optional[str] = None,
    identification_confidence: Optional[float] = None,
    source_video: Optional[str] = None,
    session_id: Optional[str] = None,
):
    """Enqueue security event for background processing in <0.2ms without blocking the video tracking loop."""
    start_async_event_logger()
    try:
        # Clone frame buffer so main video loop can proceed immediately
        frame_copy = frame.copy()
        _event_queue.put_nowait(
            {
                "camera_id": camera_id,
                "event_type": event_type,
                "object_class": object_class,
                "track_id": track_id,
                "frame_number": frame_number,
                "bbox": bbox,
                "confidence": confidence,
                "frame": frame_copy,
                "db_path": db_path,
                "print_json": print_json,
                "face_detected": face_detected,
                "face_bbox": face_bbox,
                "plate_number": plate_number,
                "plate_confidence": plate_confidence,
                "plate_bbox": plate_bbox,
                "identified_as": identified_as,
                "identification_confidence": identification_confidence,
                "source_video": source_video,
                "session_id": session_id,
            }
        )
    except queue.Full:
        pass


def register_event_listener(listener: Callable[[dict[str, Any]], Any]):
    """Register an in-process callback listener for new security events."""
    if listener not in _in_process_event_listeners:
        _in_process_event_listeners.append(listener)


def unregister_event_listener(listener: Callable[[dict[str, Any]], Any]):
    """Unregister an in-process callback listener."""
    if listener in _in_process_event_listeners:
        _in_process_event_listeners.remove(listener)


CAMERA_LOCATIONS: dict[str, str] = {
    "CAM_01": "Sector 4 Gate (North Perimeter)",
    "CAM_02": "Sector 2 East Fence Line",
    "CAM_03": "Sector 7 Southern Outpost",
    "CAM_04": "Main Checkpoint Alpha",
}


def generate_tactical_summary_rule_based(event: dict[str, Any]) -> str:
    """
    Generate a crisp, professional, plain-English tactical security log line.
    Rule-based deterministic fallback with zero latency for venue/offline environments.
    """
    camera_id = event.get("camera_id", "CAM_01")
    location = CAMERA_LOCATIONS.get(camera_id, f"Sector Gate ({camera_id})")
    event_type = event.get("event_type", "zone_entry")
    object_class = str(event.get("object_class", "person")).lower()
    track_id = event.get("track_id", 0)
    conf = float(event.get("confidence", 0.80))
    conf_pct = int(round(conf * 100))
    conf_label = "high" if conf >= 0.75 else ("moderate" if conf >= 0.50 else "nominal")
    plate_number = event.get("plate_number")
    identified_as = event.get("identified_as")
    id_conf = event.get("identification_confidence")
    id_conf_pct = int(round(float(id_conf) * 100)) if id_conf is not None else None

    if event_type == "zone_entry":
        if object_class == "person":
            if identified_as and identified_as.strip() and identified_as.upper() != "UNKNOWN":
                return f"Routine access: {identified_as} entered {location}."
            return f"High alert: Unrecognized individual detected entering {location} (Track #{track_id}, {conf_pct}% confidence)."
        elif object_class in ["car", "truck", "bus", "motorcycle", "vehicle"]:
            auth_veh = check_authorized_vehicle(plate_number) if plate_number else None
            if auth_veh:
                owner_tag = f" ({auth_veh.get('owner_name', 'Authorized Fleet')})"
                return f"Routine access: Authorized vehicle [{plate_number}]{owner_tag} entered {location}."
            plate_tag = f", Plate: {plate_number}" if plate_number else ", Plate: UNREADABLE"
            return f"Vehicle intrusion ({object_class.upper()} #{track_id}{plate_tag}) detected at {location} ({conf_pct}% confidence) - requires verification."
        else:
            return f"Unidentified target ({object_class} #{track_id}) crossed restricted boundary at {location} ({conf_pct}% confidence)."
    elif event_type == "zone_exit":
        if object_class == "person":
            if identified_as and identified_as != "UNKNOWN":
                return f"Subject identified as {identified_as} (Track #{track_id}) has left the monitored zone at {location} - track concluded."
            return f"Subject (Track #{track_id}) has left the monitored zone at {location} - track concluded ({conf_pct}% confidence)."
        elif object_class in ["car", "truck", "bus", "motorcycle", "vehicle"]:
            plate_tag = f" [{plate_number}]" if plate_number else ""
            return f"Vehicle ({object_class.upper()} #{track_id}{plate_tag}) departed restricted perimeter at {location} - clear."
        else:
            return f"Target ({object_class} #{track_id}) exited virtual fence at {location}."
    elif event_type == "suspicious_loitering":
        if identified_as and identified_as.strip() and identified_as.upper() != "UNKNOWN":
            return f"Routine presence: Authorized personnel [{identified_as}] (Track #{track_id}) present near {location}."
        id_str = f" [{identified_as}]" if identified_as and identified_as != "UNKNOWN" else ""
        return f"Suspicious Activity Alert: Subject{id_str} (Track #{track_id}) displaying prolonged stationary presence (loitering) near {location} ({conf_pct}% confidence) — visual verification recommended."
    elif event_type == "suspicious_pacing":
        if identified_as and identified_as.strip() and identified_as.upper() != "UNKNOWN":
            return f"Routine movement: Authorized personnel [{identified_as}] (Track #{track_id}) moving near {location}."
        id_str = f" [{identified_as}]" if identified_as and identified_as != "UNKNOWN" else ""
        return f"Suspicious Activity Alert: Subject{id_str} (Track #{track_id}) exhibiting erratic back-and-forth pacing behavior near {location} ({conf_pct}% confidence) — patrol dispatch advised."
    else:
        return f"Perimeter activity recorded for {object_class} #{track_id} at {location} ({conf_pct}% confidence)."


_ollama_status: dict[str, Any] = {"available": None, "last_checked": 0.0}


def is_ollama_available(cache_ttl: float = 30.0) -> bool:
    """Check if local Ollama daemon is running with a 30s TTL cache to avoid timeout latency."""
    import time
    now = time.time()
    if _ollama_status["available"] is not None and (now - _ollama_status["last_checked"]) < cache_ttl:
        return bool(_ollama_status["available"])

    try:
        req = urllib.request.Request("http://127.0.0.1:11434/api/tags", headers={"User-Agent": "IBVAP/1.0"})
        with urllib.request.urlopen(req, timeout=0.15) as resp:
            if resp.status == 200:
                _ollama_status["available"] = True
                _ollama_status["last_checked"] = now
                return True
    except Exception:
        pass

    _ollama_status["available"] = False
    _ollama_status["last_checked"] = now
    return False


def generate_tactical_summary_ollama(event: dict[str, Any], timeout: float = 1.5) -> Optional[str]:
    """
    Attempt to generate a tactical summary via local Ollama LLM if available on localhost:11434.
    Runs non-blocking with strict timeout and fails safe to rule-based generator.
    """
    if not is_ollama_available():
        return None

    try:
        camera_id = event.get("camera_id", "CAM_01")
        location = CAMERA_LOCATIONS.get(camera_id, f"Sector Gate ({camera_id})")
        plate_str = f" Plate: {event.get('plate_number')}" if event.get('plate_number') else ""
        id_str = f" Identified: {event.get('identified_as')}" if event.get('identified_as') and event.get('identified_as') != 'UNKNOWN' else ""
        prompt = (
            f"You are a tactical border security AI. Summarize this event in ONE short, crisp, plain-English sentence:\n"
            f"Event: {event.get('event_type')}\n"
            f"Target: {event.get('object_class')} (Track ID #{event.get('track_id')}{plate_str}{id_str})\n"
            f"Location: {location}\n"
            f"Confidence: {int(round(float(event.get('confidence', 0.8)) * 100))}%\n"
            f"Severity: {event.get('severity', 'high')}\n"
            f"Reply with ONLY the single sentence summary, nothing else."
        )
        req_data = json.dumps({
            "model": "llama3.2:1b",
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.2, "num_predict": 40}
        }).encode("utf-8")
        req = urllib.request.Request(
            "http://localhost:11434/api/generate",
            data=req_data,
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
            text = data.get("response", "").strip().strip('"').strip()
            if text and len(text) > 10:
                return text
    except Exception:
        pass
    return None


def generate_tactical_summary(event: dict[str, Any]) -> str:
    """
    Hybrid Tactical Summary Engine:
    Attempts fast local LLM (Ollama) synthesis with instant deterministic rule-based fallback.
    """
    summary = generate_tactical_summary_ollama(event)
    if not summary:
        summary = generate_tactical_summary_rule_based(event)
    return summary


@dataclass
class SecurityEvent:
    """Structured schema for border security events with cryptographic hash chain, face identification, and ANPR plate telemetry."""

    event_id: str
    camera_id: str
    event_type: EventType
    object_class: str
    track_id: int
    timestamp: str
    frame_number: int
    bbox: List[float]  # [x1, y1, x2, y2]
    confidence: float
    severity: SeverityLevel
    snapshot_path: str
    tactical_summary: str = ""
    prev_hash: str = ""
    event_hash: str = ""
    face_detected: bool = False
    face_bbox: Optional[List[float]] = None  # [fx1, fy1, fx2, fy2] if face located
    plate_number: Optional[str] = None       # Recognized license plate alphanumeric string
    plate_confidence: Optional[float] = None  # OCR recognition confidence
    plate_bbox: Optional[List[float]] = None # [px1, py1, px2, py2] license plate crop
    identified_as: Optional[str] = None      # Watchlist identity if matched (e.g. "Alex Smith")
    identification_confidence: Optional[float] = None # Cosine similarity score against watchlist
    source_video: Optional[str] = None       # Specific source/annotated video filename (None if live webcam session)
    session_id: Optional[str] = None         # Unique surveillance session UUID

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)


def get_default_db_path() -> Path:
    """Get the default SQLite database path."""
    backend_dir = Path(__file__).resolve().parent.parent
    return backend_dir / "ibvap.db"


def get_snapshots_dir() -> Path:
    """Get the default directory for event snapshot images."""
    backend_dir = Path(__file__).resolve().parent.parent
    snapshots_dir = backend_dir / "snapshots"
    snapshots_dir.mkdir(parents=True, exist_ok=True)
    return snapshots_dir


def init_db(db_path: Optional[Path] = None) -> Path:
    """Initialize SQLite database and create events table if not present with WAL concurrency and migrations."""
    if db_path is None:
        db_path = get_default_db_path()

    db_path.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(db_path, timeout=10.0) as conn:
        cursor = conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA busy_timeout=5000;")
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                event_id TEXT PRIMARY KEY,
                camera_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                object_class TEXT NOT NULL,
                track_id INTEGER NOT NULL,
                timestamp TEXT NOT NULL,
                frame_number INTEGER NOT NULL,
                bbox TEXT NOT NULL,
                confidence REAL NOT NULL,
                severity TEXT NOT NULL,
                snapshot_path TEXT NOT NULL,
                tactical_summary TEXT,
                prev_hash TEXT,
                event_hash TEXT,
                face_detected INTEGER DEFAULT 0,
                face_bbox TEXT,
                plate_number TEXT,
                plate_confidence REAL,
                plate_bbox TEXT,
                identified_as TEXT,
                identification_confidence REAL,
                source_video TEXT,
                session_id TEXT
            )
            """
        )
        # Automatic column migrations if table was created in an earlier step
        cursor.execute("PRAGMA table_info(events)")
        existing_cols = [row[1] for row in cursor.fetchall()]
        if "tactical_summary" not in existing_cols:
            cursor.execute("ALTER TABLE events ADD COLUMN tactical_summary TEXT")
        if "prev_hash" not in existing_cols:
            cursor.execute("ALTER TABLE events ADD COLUMN prev_hash TEXT")
        if "event_hash" not in existing_cols:
            cursor.execute("ALTER TABLE events ADD COLUMN event_hash TEXT")
        if "face_detected" not in existing_cols:
            cursor.execute("ALTER TABLE events ADD COLUMN face_detected INTEGER DEFAULT 0")
        if "face_bbox" not in existing_cols:
            cursor.execute("ALTER TABLE events ADD COLUMN face_bbox TEXT")
        if "plate_number" not in existing_cols:
            cursor.execute("ALTER TABLE events ADD COLUMN plate_number TEXT")
        if "plate_confidence" not in existing_cols:
            cursor.execute("ALTER TABLE events ADD COLUMN plate_confidence REAL")
        if "plate_bbox" not in existing_cols:
            cursor.execute("ALTER TABLE events ADD COLUMN plate_bbox TEXT")
        if "identified_as" not in existing_cols:
            cursor.execute("ALTER TABLE events ADD COLUMN identified_as TEXT")
        if "identification_confidence" not in existing_cols:
            cursor.execute("ALTER TABLE events ADD COLUMN identification_confidence REAL")
        if "source_video" not in existing_cols:
            cursor.execute("ALTER TABLE events ADD COLUMN source_video TEXT")
        if "session_id" not in existing_cols:
            cursor.execute("ALTER TABLE events ADD COLUMN session_id TEXT")

        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_camera_time ON events (camera_id, timestamp)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_track_id ON events (track_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_severity ON events (severity)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_type ON events (event_type)"
        )

        # Dynamic multi-camera registry table
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS cameras (
                camera_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                location TEXT NOT NULL,
                resolution TEXT,
                fps REAL,
                monitored_zone TEXT,
                last_seen TEXT NOT NULL,
                status TEXT DEFAULT 'online'
            )
            """
        )

        # Purge any legacy/phantom non-camera records from cameras table
        cursor.execute(
            """
            DELETE FROM cameras 
            WHERE UPPER(camera_id) LIKE 'SYSTEM%' 
               OR UPPER(camera_id) LIKE 'AUTH%' 
               OR UPPER(camera_id) IN ('UNKNOWN', 'N/A', 'NONE')
            """
        )

        # Ensure default camera network is registered for multi-camera surveillance
        default_cameras = [
            ("CAM_01", "Sector 01 Gate", "North Perimeter Fence - Sector 01", "1280x720", 30.0, "Polygon Alpha (Gate 1)"),
            ("CAM_02", "Sector 02 East Fence", "East Perimeter Line - Sector 02", "1280x720", 30.0, "Polygon Beta (Perimeter 2)"),
            ("CAM_03", "Sector 03 Southern Outpost", "South River Boundary - Sector 03", "1280x720", 30.0, "Polygon Gamma (Outpost 3)"),
            ("CAM_04", "Sector 04 Road Checkpoint", "Main Highway Checkpoint Alpha", "1280x720", 30.0, "Polygon Delta (Checkpoint 4)"),
        ]
        now_seed = datetime.now(timezone.utc).isoformat()
        for c_id, c_name, c_loc, c_res, c_fps, c_zone in default_cameras:
            cursor.execute(
                """
                INSERT INTO cameras (camera_id, name, location, resolution, fps, monitored_zone, last_seen, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'online')
                ON CONFLICT(camera_id) DO UPDATE SET
                    name = excluded.name,
                    location = excluded.location
                """,
                (c_id, c_name, c_loc, c_res, c_fps, c_zone, now_seed),
            )
        conn.commit()

    if init_users_table is not None:
        try:
            init_users_table(db_path)
        except Exception:
            pass

    if init_admin_tables is not None:
        try:
            init_admin_tables(db_path)
        except Exception:
            pass

    return db_path


def compute_severity(
    event_type: str,
    object_class: str,
    identified_as: Optional[str] = None,
    plate_number: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> SeverityLevel:
    """
    Derive event severity rule:
    - 'high'   : unauthorized/unknown person entering restricted zone, suspicious loitering, suspicious pacing
    - 'medium' : unlisted vehicle (car, truck, bus, motorcycle) entering restricted zone
    - 'low'    : authorized/face-recognized person (non-expired) entering zone, authorized vehicle (non-expired) entering zone, any zone exit event
    """
    if event_type == "zone_exit":
        sev = "low"
    elif object_class.lower() == "person":
        # Any event for an active authorized person is ALWAYS LOW (Routine / Informational) - NEVER high alert
        if identified_as and identified_as.strip() and identified_as.upper() != "UNKNOWN":
            if check_watchlist_person_active(identified_as, db_path=db_path):
                sev = "low"
            else:
                sev = "high"
        else:
            sev = "high"
    elif event_type in ["suspicious_loitering", "suspicious_pacing"]:
        sev = "high"
    elif object_class.lower() in ["car", "truck", "bus", "motorcycle", "vehicle"]:
        if plate_number and plate_number.strip():
            auth_veh = check_authorized_vehicle(plate_number, db_path=db_path)
            if auth_veh:
                sev = "low"
            else:
                sev = "medium"
        else:
            sev = "medium"
    else:
        sev = "medium"

    print(
        f"[DEBUG SEVERITY] event_type='{event_type}', object_class='{object_class}', "
        f"identified_as='{identified_as}' -> SEVERITY='{sev.upper()}'"
    )
    return sev


def save_snapshot(
    frame: np.ndarray,
    event_id: str,
    bbox: Optional[List[float]] = None,
    object_class: str = "",
    track_id: Optional[int] = None,
    face_bbox: Optional[List[float]] = None,
    plate_bbox: Optional[List[float]] = None,
    plate_number: Optional[str] = None,
    identified_as: Optional[str] = None,
    identification_confidence: Optional[float] = None,
) -> str:
    """
    Save annotated snapshot of the frame to backend/snapshots/{event_id}.jpg.
    Draws target bounding box, detected/identified face box, and detected license plate box.
    """
    snapshots_dir = get_snapshots_dir()
    snapshot_file = snapshots_dir / f"{event_id}.jpg"

    snapshot_img = frame.copy()

    if bbox and len(bbox) == 4:
        x1, y1, x2, y2 = map(int, bbox)
        cv2.rectangle(snapshot_img, (x1, y1), (x2, y2), (0, 0, 255), 2)
        tag = f"EVENT: #{track_id} {object_class}"
        cv2.putText(
            snapshot_img,
            tag,
            (x1, max(20, y1 - 8)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (0, 0, 255),
            2,
            cv2.LINE_AA,
        )

    # Draw face identification box if present
    if face_bbox and len(face_bbox) == 4:
        fx1, fy1, fx2, fy2 = map(int, face_bbox)
        if identified_as and identified_as != "UNKNOWN":
            box_color = (0, 255, 120) # Bright Green
            id_pct = f" {int(round(float(identification_confidence)*100))}%" if identification_confidence else ""
            face_label = f"ID: {identified_as}{id_pct}"
        else:
            box_color = (212, 182, 6) # Cyan
            face_label = "FACE: UNKNOWN"

        cv2.rectangle(snapshot_img, (fx1, fy1), (fx2, fy2), box_color, 2)
        cv2.putText(
            snapshot_img,
            face_label,
            (fx1, max(15, fy1 - 5)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.42,
            box_color,
            1,
            cv2.LINE_AA,
        )

    # Draw yellow license plate box if present
    if plate_bbox and len(plate_bbox) == 4:
        px1, py1, px2, py2 = map(int, plate_bbox)
        cv2.rectangle(snapshot_img, (px1, py1), (px2, py2), (0, 215, 255), 2)
        plate_label = f"PLATE: {plate_number}" if plate_number else "PLATE LOCATED"
        cv2.putText(
            snapshot_img,
            plate_label,
            (px1, max(15, py1 - 5)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.4,
            (0, 215, 255),
            1,
            cv2.LINE_AA,
        )

    cv2.imwrite(str(snapshot_file), snapshot_img)
    return str(snapshot_file)


def _notify_listeners(event_dict: dict[str, Any]):
    """
    Notify event listeners without duplicate dispatch:
    - If running in-process (FastAPI app loaded), dispatch directly to registered listener.
    - If running in an external process (CLI), post to local HTTP broadcast endpoint.
    """
    if _in_process_event_listeners:
        for listener in _in_process_event_listeners:
            try:
                listener(event_dict)
            except Exception:
                pass
        return

    # Only if NOT running in-process with registered listeners, attempt external HTTP webhook
    try:
        req = urllib.request.Request(
            "http://127.0.0.1:8000/api/internal/broadcast",
            data=json.dumps(event_dict).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=0.15) as _:
            pass
    except Exception:
        # Server not running; expected and safe to ignore
        pass


def log_event(
    camera_id: str,
    event_type: EventType,
    object_class: str,
    track_id: int,
    frame_number: int,
    bbox: List[float],
    confidence: float,
    frame: np.ndarray,
    db_path: Optional[Path] = None,
    print_json: bool = True,
    face_detected: bool = False,
    face_bbox: Optional[List[float]] = None,
    plate_number: Optional[str] = None,
    plate_confidence: Optional[float] = None,
    plate_bbox: Optional[List[float]] = None,
    identified_as: Optional[str] = None,
    identification_confidence: Optional[float] = None,
    source_video: Optional[str] = None,
    session_id: Optional[str] = None,
) -> SecurityEvent:
    """
    Log a structured security event:
    1. Generates unique UUID event_id and UTC timestamp
    2. Saves snapshot image to backend/snapshots/
    3. Generates human-readable tactical summary (Ollama hybrid with rule-based fallback)
    4. Computes SHA-256 cryptographic hash chained with previous block
    5. Persists event row to SQLite (including face identification & ANPR plate telemetry)
    6. Triggers deduplicated WebSocket broadcast
    7. Prints formatted JSON to console
    """
    event_id = str(uuid.uuid4())
    timestamp = datetime.now(timezone.utc).isoformat()
    target_db = init_db(db_path)
    severity = compute_severity(
        event_type,
        object_class,
        identified_as=identified_as,
        plate_number=plate_number,
        db_path=target_db,
    )

    snapshot_path = save_snapshot(
        frame=frame,
        event_id=event_id,
        bbox=bbox,
        object_class=object_class,
        track_id=track_id,
        face_bbox=face_bbox,
        plate_bbox=plate_bbox,
        plate_number=plate_number,
        identified_as=identified_as,
        identification_confidence=identification_confidence,
    )

    tactical_summary = generate_tactical_summary(
        {
            "event_id": event_id,
            "camera_id": camera_id,
            "event_type": event_type,
            "object_class": object_class,
            "track_id": track_id,
            "frame_number": frame_number,
            "confidence": confidence,
            "severity": severity,
            "timestamp": timestamp,
            "plate_number": plate_number,
            "identified_as": identified_as,
            "identification_confidence": identification_confidence,
        }
    )

    prev_hash = get_latest_event_hash(target_db)
    event_hash = compute_event_payload_hash(
        prev_hash=prev_hash,
        event_id=event_id,
        camera_id=camera_id,
        event_type=event_type,
        object_class=object_class,
        track_id=track_id,
        timestamp=timestamp,
        frame_number=frame_number,
        confidence=confidence,
        severity=severity,
        face_detected=face_detected,
        plate_number=plate_number,
        identified_as=identified_as,
    )

    event = SecurityEvent(
        event_id=event_id,
        camera_id=camera_id,
        event_type=event_type,
        object_class=object_class,
        track_id=track_id,
        timestamp=timestamp,
        frame_number=frame_number,
        bbox=[round(float(coord), 2) for coord in bbox],
        confidence=round(float(confidence), 3),
        severity=severity,
        snapshot_path=snapshot_path,
        tactical_summary=tactical_summary,
        prev_hash=prev_hash,
        event_hash=event_hash,
        face_detected=face_detected,
        face_bbox=[round(float(c), 2) for c in face_bbox] if face_bbox else None,
        plate_number=plate_number,
        plate_confidence=round(float(plate_confidence), 3) if plate_confidence is not None else None,
        plate_bbox=[round(float(c), 2) for c in plate_bbox] if plate_bbox else None,
        identified_as=identified_as,
        identification_confidence=round(float(identification_confidence), 3) if identification_confidence is not None else None,
        source_video=source_video,
        session_id=session_id,
    )

    with sqlite3.connect(target_db, timeout=10.0) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO events (
                event_id, camera_id, event_type, object_class, track_id,
                timestamp, frame_number, bbox, confidence, severity, snapshot_path, tactical_summary,
                prev_hash, event_hash, face_detected, face_bbox, plate_number, plate_confidence, plate_bbox,
                identified_as, identification_confidence, source_video, session_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.event_id,
                event.camera_id,
                event.event_type,
                event.object_class,
                event.track_id,
                event.timestamp,
                event.frame_number,
                json.dumps(event.bbox),
                event.confidence,
                event.severity,
                event.snapshot_path,
                event.tactical_summary,
                event.prev_hash,
                event.event_hash,
                1 if event.face_detected else 0,
                json.dumps(event.face_bbox) if event.face_bbox else None,
                event.plate_number,
                event.plate_confidence,
                json.dumps(event.plate_bbox) if event.plate_bbox else None,
                event.identified_as,
                event.identification_confidence,
                event.source_video,
                event.session_id,
            ),
        )
        conn.commit()

    # Update camera registry heartbeat only for genuine detection cameras
    if is_genuine_camera_id(event.camera_id):
        heartbeat_camera(camera_id=event.camera_id, db_path=target_db)

    # Trigger real-time notifications (deduplicated)
    _notify_listeners(event.to_dict())

    if print_json:
        face_tag = f" | ID: {event.identified_as}" if event.identified_as else (" | FACE DETECTED" if event.face_detected else "")
        plate_tag = f" | PLATE: {event.plate_number}" if event.plate_number else ""
        print(f"\n[SECURITY EVENT - {event.severity.upper()} SEVERITY{face_tag}{plate_tag} | HASH: {event.event_hash[:16]}...]")
        print(event.to_json(indent=2))

    return event


def log_auth_event(
    username: str,
    role: str = "operator",
    success: bool = True,
    reason: str = "",
    ip_address: Optional[str] = None,
    db_path: Optional[Path] = None,
    print_json: bool = True,
) -> SecurityEvent:
    """
    Log an authentication event (login success or failure) into the tamper-evident cryptographic audit chain.
    Directly connects to blockchain-style SHA-256 hash chaining and real-time WebSocket broadcast.
    """
    target_db = init_db(db_path)
    now_utc = datetime.now(timezone.utc).isoformat()
    event_id = f"evt_auth_{uuid.uuid4().hex[:12]}"
    camera_id = "SYSTEM_AUTH"
    event_type: EventType = "auth_login_success" if success else "auth_login_failed"
    object_class = "operator" if role == "operator" else "admin" if role == "admin" else "system_user"
    severity: SeverityLevel = "low" if success else "high"
    confidence = 1.0 if success else 0.0

    if success:
        time_part = now_utc[11:19] if len(now_utc) >= 19 else now_utc
        tactical_summary = f"Authentication Success: {role.title()} '{username}' logged into Command Center at {time_part} UTC"
    else:
        tactical_summary = f"Authentication Failure: Failed login attempt for user '{username}' ({reason or 'Invalid credentials'})"

    prev_hash = get_latest_event_hash(target_db)
    event_hash = compute_event_payload_hash(
        prev_hash=prev_hash,
        event_id=event_id,
        camera_id=camera_id,
        event_type=event_type,
        object_class=object_class,
        track_id=0,
        timestamp=now_utc,
        frame_number=0,
        confidence=confidence,
        severity=severity,
        face_detected=False,
        plate_number=None,
        identified_as=username,
    )

    event = SecurityEvent(
        event_id=event_id,
        camera_id=camera_id,
        event_type=event_type,
        object_class=object_class,
        track_id=0,
        timestamp=now_utc,
        frame_number=0,
        bbox=[0.0, 0.0, 0.0, 0.0],
        confidence=confidence,
        severity=severity,
        snapshot_path="",
        tactical_summary=tactical_summary,
        prev_hash=prev_hash,
        event_hash=event_hash,
        face_detected=False,
        face_bbox=None,
        plate_number=None,
        plate_confidence=None,
        plate_bbox=None,
        identified_as=username,
        identification_confidence=1.0 if success else 0.0,
        source_video=None,
        session_id=None,
    )

    with sqlite3.connect(target_db, timeout=10.0) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO events (
                event_id, camera_id, event_type, object_class, track_id,
                timestamp, frame_number, bbox, confidence, severity, snapshot_path, tactical_summary,
                prev_hash, event_hash, face_detected, face_bbox, plate_number, plate_confidence, plate_bbox,
                identified_as, identification_confidence, source_video, session_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.event_id,
                event.camera_id,
                event.event_type,
                event.object_class,
                event.track_id,
                event.timestamp,
                event.frame_number,
                json.dumps(event.bbox),
                event.confidence,
                event.severity,
                event.snapshot_path,
                event.tactical_summary,
                event.prev_hash,
                event.event_hash,
                0,
                None,
                None,
                None,
                None,
                event.identified_as,
                event.identification_confidence,
                None,
                None,
            ),
        )
        conn.commit()

    # Note: Auth events are recorded in the events table for tamper-evident audit logging,
    # but must NOT trigger camera heartbeats or create phantom camera entries.

    # Trigger real-time notifications to active WebSocket clients
    _notify_listeners(event.to_dict())

    if print_json:
        status_label = "SUCCESS" if success else "FAILED"
        print(f"\n[AUTH AUDIT EVENT - {status_label} | USER: {username} | HASH: {event.event_hash[:16]}...]")
        print(event.to_json(indent=2))

    return event


def verify_chain_integrity(db_path: Optional[Path] = None) -> dict[str, Any]:
    """
    Cryptographic SHA-256 Audit Trail Verifier.
    Walks through all events in chronological sequence and validates:
    1. Continuous hash-chain linkage (prev_hash == preceding event_hash)
    2. Data payload authenticity (recomputed SHA-256 matches stored event_hash)
    Returns tamper detection report with precise position and event ID if compromised.
    """
    if db_path is None:
        db_path = get_default_db_path()

    if not db_path.exists():
        return {
            "valid": True,
            "total_events_checked": 0,
            "first_tampered_event_id": None,
            "tampered_at_position": None,
            "reason": None,
            "genesis_hash": GENESIS_HASH,
            "latest_block_hash": None,
            "verified_at": datetime.now(timezone.utc).isoformat(),
        }

    with sqlite3.connect(db_path, timeout=10.0) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM events ORDER BY rowid ASC")
        rows = cursor.fetchall()

    if not rows:
        return {
            "valid": True,
            "total_events_checked": 0,
            "first_tampered_event_id": None,
            "tampered_at_position": None,
            "reason": None,
            "genesis_hash": GENESIS_HASH,
            "latest_block_hash": None,
            "verified_at": datetime.now(timezone.utc).isoformat(),
        }

    expected_prev = GENESIS_HASH

    for idx, r in enumerate(rows):
        stored_prev = r["prev_hash"] if "prev_hash" in r.keys() and r["prev_hash"] else ""
        stored_hash = r["event_hash"] if "event_hash" in r.keys() and r["event_hash"] else ""
        is_face = bool(r["face_detected"]) if "face_detected" in r.keys() and r["face_detected"] else False
        plate_num = r["plate_number"] if "plate_number" in r.keys() and r["plate_number"] else None
        identified = r["identified_as"] if "identified_as" in r.keys() and r["identified_as"] else None

        # Check prev_hash linkage
        if stored_prev != expected_prev:
            return {
                "valid": False,
                "total_events_checked": idx,
                "first_tampered_event_id": r["event_id"],
                "tampered_at_position": idx + 1,
                "reason": "Broken cryptographic chain linkage: prev_hash does not match preceding block hash",
                "expected_prev_hash": expected_prev,
                "stored_prev_hash": stored_prev,
                "verified_at": datetime.now(timezone.utc).isoformat(),
            }

        # Recompute expected hash from core record data
        recomputed_hash = compute_event_payload_hash(
            prev_hash=stored_prev,
            event_id=r["event_id"],
            camera_id=r["camera_id"],
            event_type=r["event_type"],
            object_class=r["object_class"],
            track_id=int(r["track_id"]),
            timestamp=r["timestamp"],
            frame_number=int(r["frame_number"]),
            confidence=float(r["confidence"]),
            severity=r["severity"],
            face_detected=is_face,
            plate_number=plate_num,
            identified_as=identified,
        )

        if stored_hash != recomputed_hash:
            return {
                "valid": False,
                "total_events_checked": idx,
                "first_tampered_event_id": r["event_id"],
                "tampered_at_position": idx + 1,
                "reason": "Data integrity violation: payload altered post-hash signing",
                "expected_hash": recomputed_hash,
                "stored_hash": stored_hash,
                "tampered_record_diagnostic": {
                    "event_id": r["event_id"],
                    "severity": r["severity"],
                    "confidence": float(r["confidence"]),
                    "plate_number": plate_num,
                    "identified_as": identified,
                },
                "verified_at": datetime.now(timezone.utc).isoformat(),
            }

        expected_prev = stored_hash

    return {
        "valid": True,
        "total_events_checked": len(rows),
        "first_tampered_event_id": None,
        "tampered_at_position": None,
        "reason": None,
        "genesis_hash": GENESIS_HASH,
        "latest_block_hash": expected_prev,
        "verified_at": datetime.now(timezone.utc).isoformat(),
    }


def fetch_events_filtered(
    camera_id: Optional[str] = None,
    event_type: Optional[str] = None,
    object_class: Optional[str] = None,
    severity: Optional[str] = None,
    limit: int = 50,
    db_path: Optional[Path] = None,
) -> List[dict[str, Any]]:
    """Retrieve filtered events from SQLite."""
    if db_path is None:
        db_path = get_default_db_path()

    if not db_path.exists():
        return []

    conditions = []
    params: list[Any] = []

    if camera_id:
        conditions.append("camera_id = ?")
        params.append(camera_id)
    if event_type:
        conditions.append("event_type = ?")
        params.append(event_type)
    if object_class:
        conditions.append("object_class = ?")
        params.append(object_class)
    if severity:
        conditions.append("severity = ?")
        params.append(severity)

    where_clause = " WHERE " + " AND ".join(conditions) if conditions else ""
    query = f"SELECT * FROM events{where_clause} ORDER BY timestamp DESC, rowid DESC LIMIT ?"
    params.append(limit)

    with sqlite3.connect(db_path, timeout=10.0) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(query, params)
        rows = cursor.fetchall()
        events = []
        for r in rows:
            d = dict(r)
            d["bbox"] = json.loads(d["bbox"])
            events.append(d)
        return events


def fetch_event_by_id(event_id: str, db_path: Optional[Path] = None) -> Optional[dict[str, Any]]:
    """Retrieve a single event by UUID."""
    if db_path is None:
        db_path = get_default_db_path()

    if not db_path.exists():
        return None

    with sqlite3.connect(db_path, timeout=10.0) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM events WHERE event_id = ?", (event_id,))
        row = cursor.fetchone()
        if row is None:
            return None
        d = dict(row)
        d["bbox"] = json.loads(d["bbox"])
        return d


def is_genuine_camera_id(camera_id: Optional[str]) -> bool:
    """Verify whether camera_id represents a genuine detection camera rather than a system/auth tag."""
    if not camera_id or not isinstance(camera_id, str):
        return False
    cid = camera_id.strip().upper()
    if cid in {"SYSTEM_AUTH", "SYSTEM", "AUTH", "UNKNOWN", "N/A", "NONE"}:
        return False
    if cid.startswith("SYSTEM") or cid.startswith("AUTH"):
        return False
    return True


def heartbeat_camera(
    camera_id: str,
    name: Optional[str] = None,
    location: Optional[str] = None,
    resolution: str = "1280x720",
    fps: float = 30.0,
    monitored_zone: Optional[str] = None,
    db_path: Optional[Path] = None,
):
    """Upsert camera record with fresh last_seen timestamp in the SQLite cameras table."""
    if not is_genuine_camera_id(camera_id):
        return

    if db_path is None:
        db_path = get_default_db_path()
    if not db_path.exists():
        init_db(db_path)

    now_iso = datetime.now(timezone.utc).isoformat()
    cid_suffix = camera_id.replace("CAM_", "").replace("cam_", "").strip()
    default_name = f"Sector {cid_suffix or '01'} Gate"
    default_loc = f"North Perimeter Fence - Sector {cid_suffix or '01'}"
    default_zone = f"Polygon Zone Alpha ({camera_id})"

    try:
        with sqlite3.connect(db_path, timeout=10.0) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO cameras (camera_id, name, location, resolution, fps, monitored_zone, last_seen, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'online')
                ON CONFLICT(camera_id) DO UPDATE SET
                    name = CASE WHEN ? IS NOT NULL THEN ? ELSE cameras.name END,
                    location = CASE WHEN ? IS NOT NULL THEN ? ELSE cameras.location END,
                    resolution = excluded.resolution,
                    fps = excluded.fps,
                    monitored_zone = CASE WHEN ? IS NOT NULL THEN ? ELSE cameras.monitored_zone END,
                    last_seen = excluded.last_seen,
                    status = 'online'
                """,
                (
                    camera_id,
                    name or default_name,
                    location or default_loc,
                    resolution,
                    fps,
                    monitored_zone or default_zone,
                    now_iso,
                    name,
                    name,
                    location,
                    location,
                    monitored_zone,
                    monitored_zone,
                ),
            )
            conn.commit()

        # Notify active WebSocket clients that camera is actively streaming
        _notify_listeners(
            {
                "type": "camera_heartbeat",
                "camera_id": camera_id,
                "status": "online",
                "name": name or default_name,
                "location": location or default_loc,
                "resolution": resolution,
                "fps": fps,
                "last_seen": now_iso,
            }
        )
    except Exception as e:
        print(f"[!] Warning: Failed to heartbeat camera '{camera_id}': {e}")


def fetch_all_cameras(
    db_path: Optional[Path] = None,
    offline_timeout_sec: float = 15.0,
) -> List[dict[str, Any]]:
    """Retrieve all registered cameras with dynamic online/offline calculation based on last_seen."""
    if db_path is None:
        db_path = get_default_db_path()
    if not db_path.exists():
        return []

    now_utc = datetime.now(timezone.utc)
    try:
        with sqlite3.connect(db_path, timeout=10.0) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM cameras 
                WHERE UPPER(camera_id) NOT LIKE 'SYSTEM%' 
                  AND UPPER(camera_id) NOT LIKE 'AUTH%' 
                  AND UPPER(camera_id) NOT IN ('UNKNOWN', 'N/A', 'NONE')
                ORDER BY camera_id ASC
                """
            )
            rows = cursor.fetchall()
            cameras = []
            for r in rows:
                d = dict(r)
                try:
                    iso_clean = d["last_seen"].replace("Z", "+00:00")
                    last_seen_dt = datetime.fromisoformat(iso_clean)
                    age_sec = (now_utc - last_seen_dt).total_seconds()
                    d["status"] = "online" if age_sec <= offline_timeout_sec else "offline"
                    d["age_seconds"] = round(age_sec, 1)
                except Exception:
                    d["status"] = "offline"
                    d["age_seconds"] = 999.0
                cameras.append(d)
            return cameras
    except Exception:
        return []


def compute_event_stats(db_path: Optional[Path] = None) -> dict[str, Any]:
    """Compute aggregate stats and live footfall metrics for dashboard cards."""
    if db_path is None:
        db_path = get_default_db_path()

    hub = get_frame_hub()
    live_footfall = {"total_in": 0, "total_out": 0, "current_occupancy": 0}
    if hub is not None:
        try:
            h_data = hub.get_system_health()
            live_footfall = h_data.get("aggregate_footfall", live_footfall)
        except Exception:
            pass

    if not db_path.exists():
        return {
            "total_events": 0,
            "by_severity": {"high": 0, "medium": 0, "low": 0},
            "by_event_type": {"zone_entry": 0, "zone_exit": 0},
            "by_class": {},
            "active_cameras": 1,
            "total_cameras": 1,
            "footfall": live_footfall,
        }

    with sqlite3.connect(db_path, timeout=10.0) as conn:
        cursor = conn.cursor()

        # Total events
        cursor.execute("SELECT COUNT(*) FROM events")
        total_events = cursor.fetchone()[0]

        # By severity
        cursor.execute("SELECT severity, COUNT(*) FROM events GROUP BY severity")
        sev_dict = {"high": 0, "medium": 0, "low": 0}
        for sev, count in cursor.fetchall():
            if sev in sev_dict:
                sev_dict[sev] = count

        # By event type
        cursor.execute("SELECT event_type, COUNT(*) FROM events GROUP BY event_type")
        type_dict = {"zone_entry": 0, "zone_exit": 0}
        for etype, count in cursor.fetchall():
            if etype in type_dict:
                type_dict[etype] = count

        # Fallback to DB entry/exit if live stream footfall is 0
        if live_footfall["total_in"] == 0 and type_dict["zone_entry"] > 0:
            live_footfall = {
                "total_in": type_dict["zone_entry"],
                "total_out": type_dict["zone_exit"],
                "current_occupancy": max(0, type_dict["zone_entry"] - type_dict["zone_exit"]),
            }

        # By object class
        cursor.execute("SELECT object_class, COUNT(*) FROM events GROUP BY object_class")
        class_dict = {cls: count for cls, count in cursor.fetchall()}

        all_cams = fetch_all_cameras(db_path)
        online_cams = sum(1 for c in all_cams if c["status"] == "online")

        return {
            "total_events": total_events,
            "by_severity": sev_dict,
            "by_event_type": type_dict,
            "by_class": class_dict,
            "active_cameras": online_cams if all_cams else 1,
            "total_cameras": len(all_cams) if all_cams else 1,
            "footfall": live_footfall,
        }


def fetch_all_events(db_path: Optional[Path] = None) -> List[dict[str, Any]]:
    """Retrieve all logged events from SQLite database."""
    return fetch_events_filtered(limit=1000, db_path=db_path)


def print_database_summary(db_path: Optional[Path] = None):
    """Print an ASCII table of all events in the SQLite database."""
    events = fetch_all_events(db_path)
    print("\n" + "=" * 90)
    print(" SQLITE DATABASE DUMP: backend/ibvap.db [Table: events]")
    print("=" * 90)

    if not events:
        print(" (No events recorded in database)")
        print("=" * 90 + "\n")
        return

    header = f"{'Frame':<7} | {'Type':<11} | {'Track':<6} | {'Class':<8} | {'Conf':<6} | {'Severity':<8} | {'Event UUID':<36}"
    print(header)
    print("-" * 90)

    for ev in events:
        print(
            f"{ev['frame_number']:<7} | "
            f"{ev['event_type']:<11} | "
            f"#{ev['track_id']:<5} | "
            f"{ev['object_class']:<8} | "
            f"{ev['confidence']:<6.2f} | "
            f"{ev['severity'].upper():<8} | "
            f"{ev['event_id']:<36}"
        )

    print("=" * 90)
    print(f" Total Stored Security Events: {len(events)}\n")
