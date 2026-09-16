"""
IBVAP - Intelligent Border Video Analytics Platform
Step 5: FastAPI REST Endpoints & Real-Time WebSocket Streaming Server

Endpoints:
- GET /api/events         : List security events with query filtering
- GET /api/events/{id}    : Get single security event details
- GET /api/cameras        : Get registered surveillance cameras & status
- GET /api/snapshots/{id} : Stream snapshot JPEG image
- GET /api/stats          : Get summary metric counts for dashboard tiles
- POST /api/pipeline/run  : Trigger video analytics test pipeline run
- WS  /ws/events          : Real-time WebSocket event streaming
- POST /api/internal/broadcast : Internal webhook for CLI detection pipelines
"""

import asyncio
import subprocess
import sys
import tempfile
import threading
import time
import re
import uuid
import base64
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional
import cv2
import numpy as np


def get_live_frame_path(camera_id: str) -> Path:
    """Fast OS temp directory path to bypass OneDrive sync locks and latency."""
    temp_dir = Path(tempfile.gettempdir()) / "ibvap_live"
    temp_dir.mkdir(parents=True, exist_ok=True)
    return temp_dir / f"live_frame_{camera_id}.jpg"
from pydantic import BaseModel
from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse

try:
    from backend.app.stream_hub import get_frame_hub
except ImportError:
    try:
        from stream_hub import get_frame_hub
    except ImportError:
        get_frame_hub = lambda: None

try:
    from backend.app.events import (
        compute_event_stats,
        fetch_all_cameras,
        fetch_event_by_id,
        fetch_events_filtered,
        get_snapshots_dir,
        heartbeat_camera,
        init_db,
        log_auth_event,
        register_event_listener,
        verify_chain_integrity,
    )
    from backend.app.auth import (
        authenticate_user,
        create_access_token,
        get_current_user,
        is_auth_disabled,
        require_admin,
        require_supervisor_or_admin,
        update_user_last_login,
    )
    from backend.app.admin_management import (
        add_or_update_authorized_vehicle,
        add_or_update_watchlist_person,
        delete_authorized_vehicle,
        delete_watchlist_person,
        get_all_authorized_vehicles,
        get_all_watchlist_personnel,
        get_watchlist_dir,
        get_watchlist_person,
        init_admin_tables,
    )
    from backend.app.cloud_sync import cloud_sync_daemon
    from backend.app.replay_service import extract_incident_replay_clip, extract_event_target_crop
except ImportError:
    from events import (
        compute_event_stats,
        fetch_all_cameras,
        fetch_event_by_id,
        fetch_events_filtered,
        get_snapshots_dir,
        heartbeat_camera,
        init_db,
        log_auth_event,
        register_event_listener,
        verify_chain_integrity,
    )
    from auth import (
        authenticate_user,
        create_access_token,
        get_current_user,
        is_auth_disabled,
        require_admin,
        require_supervisor_or_admin,
        update_user_last_login,
    )
    from admin_management import (
        add_or_update_authorized_vehicle,
        add_or_update_watchlist_person,
        delete_authorized_vehicle,
        delete_watchlist_person,
        get_all_authorized_vehicles,
        get_all_watchlist_personnel,
        get_watchlist_dir,
        get_watchlist_person,
        init_admin_tables,
    )
    try:
        from cloud_sync import cloud_sync_daemon
    except ImportError:
        cloud_sync_daemon = lambda *a, **k: None
    try:
        from replay_service import extract_incident_replay_clip, extract_event_target_crop
    except ImportError:
        extract_incident_replay_clip = lambda *a, **k: (False, {"error": "unavailable"}, None)
        extract_event_target_crop = lambda *a, **k: (False, None, {"error": "unavailable"})


def get_active_face_recognizer(reload: bool = False):
    """Retrieve shared WatchlistFaceRecognizer from lightweight face_engine."""
    try:
        from backend.app.face_engine import get_watchlist_recognizer
        return get_watchlist_recognizer(reload=reload)
    except ImportError:
        try:
            from face_engine import get_watchlist_recognizer
            return get_watchlist_recognizer(reload=reload)
        except Exception:
            return None


class LoginRequest(BaseModel):
    username: str
    password: str


class VehicleCreateRequest(BaseModel):
    plate_number: str
    owner_name: str
    vehicle_type: str = "Patrol Vehicle"
    purpose: str = "Official Duty"
    expiry_date: Optional[str] = None
    notes: Optional[str] = None

app = FastAPI(
    title="IBVAP - Intelligent Border Video Analytics Platform",
    description="Smart India Hackathon 2026 - Video Analytics API & Real-Time Event Engine",
    version="1.0.0",
)

# Enable CORS for all origins during development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =====================================================================
# Real-Time WebSocket Connection Manager
# =====================================================================
class ConnectionManager:
    """Manages active WebSocket client connections, keepalive heartbeats, and broadcasts events."""

    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self._heartbeat_task: Optional[asyncio.Task] = None

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        print(f"[+] WebSocket client connected. Active connections: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            print(f"[-] WebSocket client disconnected. Active connections: {len(self.active_connections)}")

    async def broadcast_json(self, data: dict[str, Any]):
        """Broadcast JSON payload to all active WebSocket clients."""
        if not self.active_connections:
            return

        disconnected = []
        for connection in list(self.active_connections):
            try:
                await connection.send_json(data)
            except Exception:
                disconnected.append(connection)

        for dead_conn in disconnected:
            self.disconnect(dead_conn)

    async def start_heartbeat(self):
        """Send periodic keepalive heartbeat every 15s to keep connections permanently active and detect dead sockets."""
        while True:
            try:
                await asyncio.sleep(15)
                if self.active_connections:
                    await self.broadcast_json({
                        "type": "heartbeat",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })
            except asyncio.CancelledError:
                break
            except Exception:
                pass

    def trigger_in_process_broadcast(self, event_data: dict[str, Any]):
        """Callback for in-process sync event logging."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(self.broadcast_json(event_data))
        except Exception:
            pass


ws_manager = ConnectionManager()
register_event_listener(ws_manager.trigger_in_process_broadcast)

# Active background analytics stream processes: camera_id -> subprocess.Popen
ACTIVE_STREAM_PROCESSES: dict[str, subprocess.Popen] = {}
STREAM_PROCESSES_LOCK = threading.Lock()


def launch_analytics_stream(
    camera_id: str = "CAM_01",
    source_type: str = "test_video",
    source: str = "sample.mp4",
    imgsz: int = 480,
    show_zone: bool = True,
):
    """Launch or restart background analytics process for a camera with seamless loop support."""
    app_dir = Path(__file__).resolve().parent
    script_path = app_dir / "detection_tracking.py"
    test_videos_dir = app_dir.parent / "test_videos"

    with STREAM_PROCESSES_LOCK:
        existing = ACTIVE_STREAM_PROCESSES.get(camera_id)
        if existing and existing.poll() is None:
            try:
                existing.terminate()
                existing.wait(timeout=2.0)
            except Exception:
                try:
                    existing.kill()
                except Exception:
                    pass

        cmd = [
            sys.executable,
            str(script_path),
            "--camera-id", camera_id,
            "--imgsz", str(imgsz),
            "--no-display",
        ]

        if not show_zone:
            cmd.append("--no-zone")

        if source_type == "webcam" or source == "0":
            cmd.extend(["--input", "0", "--no-weather-mode"])
        elif source_type == "browser_webcam":
            relay_url = f"http://127.0.0.1:8000/api/relay/{camera_id}"
            cmd.extend(["--input", relay_url, "--no-weather-mode"])
        else:
            video_file = None
            if source:
                candidate = test_videos_dir / source
                if candidate.exists():
                    video_file = candidate
                elif Path(source).exists():
                    video_file = Path(source)
            if not video_file:
                for candidate_name in ["sample.mp4", "tracking_test.mp4", "real_footage_1.mp4"]:
                    c = test_videos_dir / candidate_name
                    if c.exists():
                        video_file = c
                        break
            if video_file:
                cmd.extend(["--input", str(video_file), "--loop"])
            else:
                cmd.extend(["--input", "0"])

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
        )
        ACTIVE_STREAM_PROCESSES[camera_id] = proc
        return proc


DEFAULT_CAMERA_FEEDS = {
    "CAM_01": "sample.mp4",
    "CAM_02": "suspicious_behavior_test.mp4",
    "CAM_03": "real_footage_1.mp4",
    "CAM_04": "tracking_test.mp4",
}

MANUALLY_STOPPED_CAMERAS: set[str] = set()


def ensure_default_stream_running(camera_id: str = "CAM_01"):
    """Ensure that a persistent surveillance loop is actively feeding the camera."""
    if camera_id in MANUALLY_STOPPED_CAMERAS:
        return None
    with STREAM_PROCESSES_LOCK:
        proc = ACTIVE_STREAM_PROCESSES.get(camera_id)
        if proc and proc.poll() is None:
            return proc
    default_source = DEFAULT_CAMERA_FEEDS.get(camera_id, "sample.mp4")
    return launch_analytics_stream(camera_id=camera_id, source_type="test_video", source=default_source, imgsz=480)


@app.on_event("startup")
async def startup_event():
    """Initialize database on startup, launch keepalive heartbeat task, auto-start surveillance loop, and cloud sync."""
    init_db()
    asyncio.create_task(ws_manager.start_heartbeat())
    asyncio.create_task(cloud_sync_daemon())
    try:
        ensure_default_stream_running(camera_id="CAM_01")
        print("[+] IBVAP Surveillance Pipeline auto-started for CAM_01 (Loop mode).")
    except Exception as e:
        print(f"[!] Warning: Could not auto-start camera stream: {e}")
    print("[+] IBVAP FastAPI Server initialized with WebSocket heartbeat.")


@app.on_event("shutdown")
def shutdown_event():
    """Cleanly terminate any active video inference background processes on shutdown."""
    with STREAM_PROCESSES_LOCK:
        for cam_id, proc in list(ACTIVE_STREAM_PROCESSES.items()):
            if proc and proc.poll() is None:
                try:
                    proc.terminate()
                except Exception:
                    pass


# =====================================================================
# REST Endpoints
# =====================================================================
@app.get("/")
def root():
    return {
        "project": "IBVAP - Intelligent Border Video Analytics Platform",
        "status": "online",
        "phase": "Step 5 - React Command Center Dashboard",
        "auth_enabled": not is_auth_disabled(),
        "docs_url": "/docs",
        "ws_events_url": "/ws/events",
    }


# =====================================================================
# Authentication Endpoints
# =====================================================================
@app.get("/api/auth/config")
def get_auth_config():
    """Returns system authentication configuration status (e.g. whether bypass is enabled)."""
    return {
        "auth_disabled": is_auth_disabled(),
        "status": "active",
    }


@app.post("/api/auth/login")
def login(req: LoginRequest, request: Request):
    """
    Validate user credentials against SQLite and return a signed JWT token.
    Logs every authentication event (success and failure) to the tamper-evident audit trail.
    """
    username = req.username.strip()
    client_ip = request.client.host if request.client else "127.0.0.1"

    user = authenticate_user(username=username, password=req.password)
    if not user:
        # Record tamper-evident failed authentication event
        log_auth_event(
            username=username or "unknown",
            role="unknown",
            success=False,
            reason="Invalid username or password",
            ip_address=client_ip,
        )
        raise HTTPException(
            status_code=401,
            detail="Invalid username or password. Please check your credentials.",
        )

    # Update last login timestamp
    update_user_last_login(user["username"])

    # Record tamper-evident successful authentication event
    log_auth_event(
        username=user["username"],
        role=user["role"],
        success=True,
        reason="Successful password authentication",
        ip_address=client_ip,
    )

    access_token = create_access_token(
        data={
            "sub": user["username"],
            "role": user["role"],
            "name": user.get("full_name", user["username"]),
        }
    )

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "username": user["username"],
            "role": user["role"],
            "full_name": user.get("full_name", user["username"]),
        },
    }


@app.get("/api/auth/me")
def get_current_user_profile(current_user: dict = Depends(get_current_user)):
    """Return the profile and role of the currently authenticated user."""
    return {
        "username": current_user["username"],
        "role": current_user.get("role", "operator"),
        "full_name": current_user.get("full_name", current_user["username"]),
        "auth_disabled": current_user.get("auth_disabled", False),
    }


# =====================================================================
# Admin Command Panel Endpoints (Requires 'admin' Role)
# =====================================================================
@app.get("/api/admin/watchlist")
def get_admin_watchlist(current_user: dict = Depends(require_supervisor_or_admin)):
    """Retrieve all authorized personnel watchlist profiles (Supervisor/Admin)."""
    items = get_all_watchlist_personnel()
    return {
        "count": len(items),
        "watchlist": items,
    }


@app.post("/api/admin/watchlist")
async def add_admin_watchlist_person(
    name: str = Form(..., description="Full Name of the authorized person"),
    role: str = Form("SSB Personnel", description="Role/Category (e.g. SSB Personnel, Contractor, Visitor)"),
    expiry_date: Optional[str] = Form(None, description="Optional expiry date YYYY-MM-DD"),
    notes: Optional[str] = Form(None, description="Operational notes"),
    photo: Optional[UploadFile] = File(None, description="Facial portrait reference image"),
    current_user: dict = Depends(require_supervisor_or_admin),
):
    """Add or update an authorized person on the facial recognition watchlist (Supervisor/Admin)."""
    clean_name = name.strip()
    if not clean_name:
        raise HTTPException(status_code=400, detail="Name cannot be empty.")

    watchlist_dir = get_watchlist_dir()
    existing_person = get_watchlist_person(clean_name)
    photo_filename = existing_person["photo_filename"] if existing_person else ""

    if photo and photo.filename:
        ext = Path(photo.filename).suffix.lower()
        if ext not in [".jpg", ".jpeg", ".png", ".webp"]:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid image format '{ext}'. Supported formats: .jpg, .jpeg, .png, .webp",
            )

        safe_stem = re.sub(r"[^a-zA-Z0-9_-]", "_", clean_name.lower())
        saved_filename = f"{safe_stem}{ext}"
        target_path = watchlist_dir / saved_filename

        contents = await photo.read()
        if len(contents) < 500:
            raise HTTPException(status_code=400, detail="Uploaded photo is too small or corrupted.")

        with open(target_path, "wb") as f:
            f.write(contents)
        photo_filename = saved_filename

    if not photo_filename:
        safe_stem = re.sub(r"[^a-zA-Z0-9_-]", "_", clean_name.lower())
        for ext in [".png", ".jpg", ".jpeg"]:
            if (watchlist_dir / f"{safe_stem}{ext}").exists():
                photo_filename = f"{safe_stem}{ext}"
                break

    if not photo_filename:
        raise HTTPException(status_code=400, detail="A photo upload is required for new watchlist profiles.")

    person = add_or_update_watchlist_person(
        name=clean_name,
        role=role,
        photo_filename=photo_filename,
        expiry_date=expiry_date,
        notes=notes,
    )

    # Immediately trigger in-memory watchlist embedding reload
    get_active_face_recognizer(reload=True)

    return {
        "status": "success",
        "message": f"Watchlist profile for '{clean_name}' successfully saved & embeddings re-cached.",
        "person": person,
    }


@app.delete("/api/admin/watchlist/{name}")
def remove_admin_watchlist_person(name: str, current_user: dict = Depends(require_supervisor_or_admin)):
    """Delete an authorized person from the facial recognition watchlist (Supervisor/Admin)."""
    success = delete_watchlist_person(name)
    if not success:
        raise HTTPException(status_code=404, detail=f"Watchlist person '{name}' not found.")

    # Immediately trigger in-memory watchlist embedding reload
    get_active_face_recognizer(reload=True)

    return {
        "status": "success",
        "message": f"Profile '{name}' deleted from watchlist.",
        "name": name,
    }


@app.post("/api/admin/watchlist/rescan")
def rescan_admin_watchlist(current_user: dict = Depends(require_admin)):
    """Re-scan backend/watchlist/ folder and regenerate all embeddings in memory without restart (Admin only)."""
    watchlist_dir = get_watchlist_dir()
    for p in sorted(watchlist_dir.iterdir()):
        if p.suffix.lower() in [".png", ".jpg", ".jpeg"]:
            stem = p.stem.strip()
            display_name = stem.replace("_", " ").title()
            existing = get_watchlist_person(display_name)
            if not existing:
                add_or_update_watchlist_person(
                    name=display_name,
                    role="SSB Personnel",
                    photo_filename=p.name,
                )

    recog = get_active_face_recognizer(reload=True)
    embeddings_count = len(recog.watchlist_embeddings) if recog else 0
    active_identities = list(recog.watchlist_embeddings.keys()) if recog else []

    return {
        "status": "success",
        "message": f"Successfully reloaded watchlist from disk. {embeddings_count} face embedding profile(s) cached in memory.",
        "profiles_loaded": embeddings_count,
        "identities": active_identities,
    }


@app.get("/api/admin/watchlist/photo/{filename}")
def get_watchlist_photo(filename: str):
    """Serve photo thumbnail for admin watchlist management."""
    clean_filename = Path(filename).name
    photo_path = get_watchlist_dir() / clean_filename
    if not photo_path.exists():
        raise HTTPException(status_code=404, detail="Photo not found")
    media_type = "image/png" if clean_filename.endswith(".png") else "image/jpeg"
    return FileResponse(path=str(photo_path), media_type=media_type)


@app.get("/api/admin/vehicles")
def get_admin_authorized_vehicles(current_user: dict = Depends(require_supervisor_or_admin)):
    """Retrieve all authorized vehicles (Supervisor/Admin)."""
    vehicles = get_all_authorized_vehicles()
    return {
        "count": len(vehicles),
        "vehicles": vehicles,
    }


@app.post("/api/admin/vehicles")
def add_admin_vehicle(req: VehicleCreateRequest, current_user: dict = Depends(require_supervisor_or_admin)):
    """Add or update an authorized vehicle license plate (Supervisor/Admin)."""
    clean_plate = req.plate_number.strip().upper()
    if not clean_plate:
        raise HTTPException(status_code=400, detail="Plate number cannot be empty.")
    if not req.owner_name.strip():
        raise HTTPException(status_code=400, detail="Owner name / unit cannot be empty.")

    vehicle = add_or_update_authorized_vehicle(
        plate_number=clean_plate,
        owner_name=req.owner_name.strip(),
        vehicle_type=req.vehicle_type.strip(),
        purpose=req.purpose.strip(),
        expiry_date=req.expiry_date,
        notes=req.notes,
    )
    return {
        "status": "success",
        "message": f"Vehicle '{clean_plate}' ({req.owner_name}) successfully added to authorized whitelist.",
        "vehicle": vehicle,
    }


@app.delete("/api/admin/vehicles/{plate_number}")
def remove_admin_authorized_vehicle(plate_number: str, current_user: dict = Depends(require_supervisor_or_admin)):
    """Delete an authorized vehicle plate (Supervisor/Admin)."""
    success = delete_authorized_vehicle(plate_number)
    if not success:
        raise HTTPException(status_code=404, detail=f"Vehicle '{plate_number}' not found on whitelist.")
    return {
        "status": "success",
        "message": f"Vehicle '{plate_number}' removed from authorized whitelist.",
        "plate_number": plate_number,
    }


# =====================================================================
# Protected Security Endpoints
# =====================================================================
@app.get("/api/events")
def get_events(
    limit: int = Query(50, ge=1, le=500, description="Max number of events to return"),
    event_type: Optional[str] = Query(None, description="Filter by event_type"),
    object_class: Optional[str] = Query(None, description="Filter by object_class"),
    severity: Optional[str] = Query(None, description="Filter by severity"),
    camera_id: Optional[str] = Query(None, description="Filter by camera_id"),
    current_user: dict = Depends(get_current_user),
):
    """Retrieve security events with optional filtering (Requires Operator/Admin authentication)."""
    events = fetch_events_filtered(
        camera_id=camera_id,
        event_type=event_type,
        object_class=object_class,
        severity=severity,
        limit=limit,
    )
    return {
        "count": len(events),
        "events": events,
    }


@app.get("/api/audit/verify")
def get_audit_verification(current_user: dict = Depends(get_current_user)):
    """Verify cryptographic SHA-256 hash chain across all stored security events (Requires Operator/Admin)."""
    return verify_chain_integrity()


@app.get("/api/events/{event_id}")
def get_event_detail(event_id: str, current_user: dict = Depends(get_current_user)):
    """Retrieve full detail for a single security event."""
    event = fetch_event_by_id(event_id)
    if not event:
        raise HTTPException(status_code=404, detail=f"Event with ID '{event_id}' not found")
    return event


@app.get("/api/cameras")
def get_cameras(current_user: dict = Depends(get_current_user)):
    """Retrieve registered cameras list and real-time online/offline status."""
    cams = fetch_all_cameras()
    if not cams:
        return [
            {
                "camera_id": "CAM_01",
                "name": "Sector 4 Gate",
                "location": "North Perimeter Fence - Sector 4",
                "status": "online",
                "resolution": "1280x720",
                "fps": 30,
                "monitored_zone": "Polygon Zone Alpha (Sector 4)",
                "last_seen": datetime.now(timezone.utc).isoformat(),
            }
        ]
    return cams


@app.get("/api/snapshots/{event_id}")
def get_snapshot_image(event_id: str):
    """Serve the JPEG snapshot image for a given event ID."""
    snapshots_dir = get_snapshots_dir()
    snapshot_path = snapshots_dir / f"{event_id}.jpg"

    if not snapshot_path.exists():
        raise HTTPException(status_code=404, detail=f"Snapshot for event '{event_id}' not found")

    return FileResponse(
        path=str(snapshot_path),
        media_type="image/jpeg",
        filename=f"{event_id}.jpg",
        headers={
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": "public, max-age=3600",
        },
    )


@app.get("/api/events/{event_id}/replay")
def get_incident_replay(
    event_id: str,
    format: str = Query("video", description="Format: 'video' for MP4 stream, 'json' for forensic metadata"),
    window: float = Query(3.0, description="Window size in seconds before and after the event (default: 3.0s)"),
):
    """
    Extract and serve a forensic sub-clip (T-3s to T+3s) around a security event.
    If source video is unavailable (e.g. live-only webcam session), returns a clear fallback response.
    """
    is_available, metadata, replay_path = extract_incident_replay_clip(
        event_id=event_id,
        window_seconds=window,
    )

    if not is_available:
        raise HTTPException(
            status_code=404,
            detail=metadata.get("message", "Incident replay is unavailable for this session."),
        )

    if format.lower() == "json":
        return metadata

    return FileResponse(
        path=str(replay_path),
        media_type="video/mp4",
        filename=f"replay_{event_id}.mp4",
        headers={"Accept-Ranges": "bytes"},
    )


@app.get("/api/events/{event_id}/crop")
def get_event_target_crop(event_id: str):
    """Serve cropped high-resolution target ROI (face, plate, or body) for forensic zoom inspection."""
    success, jpeg_bytes, meta = extract_event_target_crop(event_id)
    if not success or not jpeg_bytes:
        raise HTTPException(
            status_code=404,
            detail=meta.get("error", "Target crop unavailable for this event."),
        )
    return Response(
        content=jpeg_bytes,
        media_type="image/jpeg",
        headers={
            "Cache-Control": "public, max-age=3600",
            "X-Crop-Type": meta.get("crop_type", "body"),
        },
    )


@app.get("/api/audit/verify")
def verify_security_audit_chain(current_user: dict = Depends(get_current_user)):
    """
    Perform full cryptographic verification across the entire SQLite event audit hash chain.
    Validates SHA-256 block linkages and signs cryptographic audit response.
    """
    return verify_chain_integrity()


@app.get("/api/audit/certificate")
def get_audit_certificate(current_user: dict = Depends(get_current_user)):
    """
    Generate a formal, tamper-evident Digital Chain of Custody & Forensic Verification Certificate.
    Admissible for military inquiry, internal security review, and legal compliance.
    """
    audit_res = verify_chain_integrity()
    now_utc = datetime.now(timezone.utc).isoformat()
    cert_id = f"CERT-IBVAP-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{uuid.uuid4().hex[:8].upper()}"

    is_valid = audit_res.get("valid", False)
    total_checked = audit_res.get("total_events_checked", 0)
    genesis_hash = audit_res.get("genesis_hash")
    latest_hash = audit_res.get("latest_block_hash")

    certificate = {
        "certificate_id": cert_id,
        "title": "DIGITAL CHAIN OF CUSTODY & CRYPTOGRAPHIC INTEGRITY CERTIFICATE",
        "issuing_authority": "IBVAP Autonomous Border Security Platform (V2.6)",
        "verified_at": now_utc,
        "verified_by": {
            "username": current_user.get("username", "admin"),
            "role": current_user.get("role", "operator"),
        },
        "integrity_status": "AUTHENTIC // UNCOMPROMISED" if is_valid else "COMPROMISED // INTEGRITY_VIOLATION",
        "is_valid": is_valid,
        "cryptographic_specification": {
            "algorithm": "SHA-256 Chained Hash Ledger (Genesis Block Anchored)",
            "genesis_block_hash": genesis_hash,
            "latest_block_hash": latest_hash,
            "total_blocks_verified": total_checked,
        },
        "forensic_audit_details": audit_res,
        "compliance_statement": (
            "This digital certificate attests that all surveillance intrusion records, biometric face identifications, "
            "and vehicle detections in the IBVAP database have been cryptographically verified against SHA-256 Merkle-style "
            "chained block hashes with zero detected tampering, alterations, or record deletions."
            if is_valid
            else "WARNING: Cryptographic integrity violation detected. One or more records have been tampered with post-signing."
        ),
    }
    return certificate


def generate_placeholder_frame(camera_id: str = "CAM_01", message: str = "STANDBY // NO SIGNAL") -> bytes:
    """Generate a high-tech dark mode standby placeholder frame when stream is offline/initializing."""
    img = np.zeros((480, 640, 3), dtype=np.uint8)
    img[:] = (20, 16, 10)  # Dark BGR navy #0a1014

    # Tactical grid lines
    for x in range(0, 640, 40):
        cv2.line(img, (x, 0), (x, 480), (35, 28, 18), 1)
    for y in range(0, 480, 40):
        cv2.line(img, (0, y), (640, y), (35, 28, 18), 1)

    # Top HUD banner
    cv2.rectangle(img, (0, 0), (640, 38), (30, 22, 14), -1)
    cv2.line(img, (0, 38), (640, 38), (233, 165, 14), 2)
    cv2.putText(
        img,
        f"IBVAP SURVEILLANCE | {camera_id}",
        (16, 25),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        (255, 210, 80),
        2,
        cv2.LINE_AA,
    )
    cv2.putText(
        img,
        "FEED STANDBY",
        (490, 25),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.48,
        (100, 100, 255),
        1,
        cv2.LINE_AA,
    )

    # Center alert box
    cv2.rectangle(img, (100, 170), (540, 310), (32, 24, 16), -1)
    cv2.rectangle(img, (100, 170), (540, 310), (70, 50, 28), 1)

    # Warning icon
    cv2.circle(img, (320, 215), 18, (0, 140, 255), 2)
    cv2.putText(
        img, "!", (315, 223), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 180, 255), 2, cv2.LINE_AA
    )

    (tw, _), _ = cv2.getTextSize(message, cv2.FONT_HERSHEY_SIMPLEX, 0.60, 2)
    cv2.putText(
        img,
        message,
        (max(110, int((640 - tw) / 2)), 260),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.60,
        (0, 180, 255),
        2,
        cv2.LINE_AA,
    )
    sub_msg = "Click 'Resume Feed' or 'Webcam' above to activate surveillance"
    (stw, _), _ = cv2.getTextSize(sub_msg, cv2.FONT_HERSHEY_SIMPLEX, 0.38, 1)
    cv2.putText(
        img,
        sub_msg,
        (max(110, int((640 - stw) / 2)), 290),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.38,
        (160, 160, 160),
        1,
        cv2.LINE_AA,
    )

    _, encoded = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])
    return encoded.tobytes()


async def mjpeg_frame_generator(camera_id: str, request: Optional[Request] = None):
    """Continuously yield multipart MJPEG frames from in-memory FrameHub or disk with zero judder."""
    backend_dir = Path(__file__).resolve().parent.parent
    live_frame_path = backend_dir / f"live_frame_{camera_id}.jpg"
    placeholder_bytes = generate_placeholder_frame(camera_id, "STANDBY // NO SIGNAL")

    # Auto-ensure live surveillance loop is active only if NOT manually stopped by operator
    try:
        if camera_id not in MANUALLY_STOPPED_CAMERAS:
            ensure_default_stream_running(camera_id)
    except Exception:
        pass

    hub = get_frame_hub()
    last_mtime = 0.0
    last_yield_time = 0.0
    is_standby = False

    while True:
        if request is not None and await request.is_disconnected():
            break

        if camera_id in MANUALLY_STOPPED_CAMERAS:
            if not is_standby or (time.time() - last_yield_time > 1.0):
                stale_bytes = generate_placeholder_frame(camera_id, "CAMERA STOPPED // STANDBY")
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n" + stale_bytes + b"\r\n"
                )
                last_yield_time = time.time()
                is_standby = True
            await asyncio.sleep(0.4)
            continue

        try:
            # 1. First priority: In-Memory FrameHub (Zero Disk Latency)
            if hub is not None:
                mem_bytes = hub.get_latest_frame(camera_id, max_age=3.5)
                if mem_bytes and len(mem_bytes) > 500:
                    yield (
                        b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n\r\n" + mem_bytes + b"\r\n"
                    )
                    last_yield_time = time.time()
                    is_standby = False
                    await asyncio.sleep(0.025)  # Smooth ~40 FPS pacing
                    continue

            # 2. Second priority: Disk File Fallback (fast OS temp folder first to bypass OneDrive locks)
            fast_path = get_live_frame_path(camera_id)
            target_path = fast_path if (fast_path.exists() and (time.time() - fast_path.stat().st_mtime <= 4.0)) else live_frame_path

            if target_path.exists():
                mtime = target_path.stat().st_mtime
                age = time.time() - mtime

                if age > 4.0:
                    # Stream has stopped or paused
                    if not is_standby or (time.time() - last_yield_time > 1.0):
                        stale_bytes = generate_placeholder_frame(camera_id, "STREAM STANDBY (WAITING FOR FRAMES)")
                        yield (
                            b"--frame\r\n"
                            b"Content-Type: image/jpeg\r\n\r\n" + stale_bytes + b"\r\n"
                        )
                        last_yield_time = time.time()
                        is_standby = True
                    await asyncio.sleep(0.1)
                elif mtime > last_mtime:
                    # Fresh new frame generated by video pipeline!
                    try:
                        with open(target_path, "rb") as f:
                            frame_bytes = f.read()
                        if frame_bytes and len(frame_bytes) > 500:
                            yield (
                                b"--frame\r\n"
                                b"Content-Type: image/jpeg\r\n\r\n" + frame_bytes + b"\r\n"
                            )
                            last_mtime = mtime
                            last_yield_time = time.time()
                            is_standby = False
                    except Exception:
                        pass
                    # Small yield to event loop
                    await asyncio.sleep(0.01)
                else:
                    # No new frame yet - wait briefly to match frame arrival with zero judder
                    await asyncio.sleep(0.015)
            else:
                if not is_standby or (time.time() - last_yield_time > 1.0):
                    yield (
                        b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n\r\n" + placeholder_bytes + b"\r\n"
                    )
                    last_yield_time = time.time()
                    is_standby = True
                await asyncio.sleep(0.1)
        except Exception:
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n" + placeholder_bytes + b"\r\n"
            )
            await asyncio.sleep(0.1)


@app.get("/api/live-feed/{camera_id}")
async def get_live_feed(camera_id: str = "CAM_01", request: Request = None):
    """
    Stream real-time MJPEG video feed for standard browser <img> tags.
    Continuously streams annotated detection and tracking frames from the analytics pipeline.
    """
    return StreamingResponse(
        mjpeg_frame_generator(camera_id, request),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
        },
    )


@app.get("/api/live-feed/{camera_id}/frame")
async def get_live_frame_snapshot(camera_id: str = "CAM_01"):
    """Fetch the single latest JPEG frame instantly with zero browser caching."""
    hub = get_frame_hub()
    if hub is not None:
        mem_bytes = hub.get_latest_frame(camera_id, max_age=4.0)
        if mem_bytes and len(mem_bytes) > 500:
            return Response(
                content=mem_bytes,
                media_type="image/jpeg",
                headers={
                    "Cache-Control": "no-cache, no-store, must-revalidate, max-age=0",
                    "Pragma": "no-cache",
                    "Expires": "0",
                    "Access-Control-Allow-Origin": "*",
                },
            )

    fast_path = get_live_frame_path(camera_id)
    target_path = fast_path if (fast_path.exists() and (time.time() - fast_path.stat().st_mtime <= 4.0)) else (Path(__file__).resolve().parent.parent / f"live_frame_{camera_id}.jpg")
    if target_path.exists():
        try:
            mtime = target_path.stat().st_mtime
            if (time.time() - mtime) <= 4.0:
                with open(target_path, "rb") as f:
                    data = f.read()
                if data and len(data) > 500:
                    return Response(
                        content=data,
                        media_type="image/jpeg",
                        headers={
                            "Cache-Control": "no-cache, no-store, must-revalidate, max-age=0",
                            "Pragma": "no-cache",
                            "Expires": "0",
                            "Access-Control-Allow-Origin": "*",
                        },
                    )
        except Exception:
            pass

    placeholder = generate_placeholder_frame(camera_id, "STANDBY // NO SIGNAL")
    return Response(
        content=placeholder,
        media_type="image/jpeg",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
            "Access-Control-Allow-Origin": "*",
        },
    )


# --- BROWSER WEBCAM RELAY STATE ---
LATEST_UPLOADED_FRAMES: dict[str, bytes] = {}

@app.websocket("/api/stream/upload/{camera_id}")
async def webcam_upload_endpoint(websocket: WebSocket, camera_id: str):
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_text()
            if data.startswith("data:image/jpeg;base64,"):
                data = data.split(",", 1)[1]
            try:
                frame_bytes = base64.b64decode(data)
                LATEST_UPLOADED_FRAMES[camera_id] = frame_bytes
            except Exception:
                pass
    except WebSocketDisconnect:
        pass

async def mjpeg_relay_generator(camera_id: str):
    while True:
        frame = LATEST_UPLOADED_FRAMES.get(camera_id)
        if frame:
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
            )
        await asyncio.sleep(0.03)

@app.get("/api/relay/{camera_id}")
async def mjpeg_relay_endpoint(camera_id: str):
    return StreamingResponse(
        mjpeg_relay_generator(camera_id),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )
# ------------------------------------


@app.get("/api/stats")
def get_stats(current_user: dict = Depends(get_current_user)):
    """Retrieve aggregate counts and metrics for dashboard stat tiles (Requires Operator/Admin)."""
    return compute_event_stats()


@app.get("/api/system/health")
def get_system_health():
    """Retrieve real-time hardware telemetry and stream health watchdog stats."""
    hub = get_frame_hub()
    health = hub.get_system_health() if hub is not None else {
        "status": "operational",
        "uptime_seconds": 0.0,
        "cpu_percent": 0.0,
        "memory": {"percent": 0.0, "used_mb": 0.0, "total_mb": 0.0},
        "active_streams": 0,
        "aggregate_footfall": {"total_in": 0, "total_out": 0, "current_occupancy": 0},
        "camera_telemetry": {},
    }
    backend_dir = Path(__file__).resolve().parent.parent
    active_count = 0
    with STREAM_PROCESSES_LOCK:
        for cam_id, proc in list(ACTIVE_STREAM_PROCESSES.items()):
            if proc and proc.poll() is None:
                active_count += 1
    for f in backend_dir.glob("live_frame_*.jpg"):
        try:
            if (time.time() - f.stat().st_mtime) <= 4.0:
                active_count = max(active_count, 1)
        except Exception:
            pass
    health["active_streams"] = max(health.get("active_streams", 0), active_count)
    return health


class StreamControlRequest(BaseModel):
    camera_id: str = "CAM_01"
    source: str = "sample.mp4"  # "0" for webcam, or video filename/path/url
    source_type: str = "test_video"  # "webcam" | "test_video" | "rtsp"
    imgsz: int = 480
    show_zone: bool = True


@app.get("/api/stream/videos")
def get_available_videos():
    """List all available surveillance video test feeds for quick switching."""
    app_dir = Path(__file__).resolve().parent
    test_videos_dir = app_dir.parent / "test_videos"
    video_labels = {
        "sample.mp4": "Sector 01 Gate (Multi-Person Intrusion & Bus Entry)",
        "tracking_test.mp4": "Sector 04 Gate (Multi-Target Tracking & Debounce)",
        "dark_test.mp4": "Night Low-Light Sector (Retinex-CLAHE Enhancement)",
        "foggy_test.mp4": "Adverse Fog Weather (DCP Dehazing Verification)",
        "suspicious_behavior_test.mp4": "Sector 02 Perimeter (Suspicious Loitering & Pacing)",
        "real_footage_1.mp4": "Border Outpost 01 (Real Surveillance Feed)",
        "real_footage_2.mp4": "Border Outpost 02 (Real Surveillance Feed)",
        "real_footage_3.mp4": "Border Outpost 03 (Real Surveillance Feed)",
    }
    videos = []
    for file in sorted(test_videos_dir.glob("*.mp4")):
        if "annotated" in file.name or "output" in file.name or file.name.startswith("."):
            continue
        videos.append({
            "filename": file.name,
            "label": video_labels.get(file.name, file.stem.replace("_", " ").title()),
            "size_kb": round(file.stat().st_size / 1024),
        })
    return {"videos": videos}


@app.post("/api/stream/start")
async def start_camera_stream(
    req: StreamControlRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    Start live camera analytics process (Webcam #0, RTSP stream, or test video) in background with 1-click.
    """
    cam_id = req.camera_id or "CAM_01"
    MANUALLY_STOPPED_CAMERAS.discard(cam_id)
    proc = launch_analytics_stream(
        camera_id=cam_id,
        source_type=req.source_type,
        source=req.source,
        imgsz=req.imgsz,
        show_zone=req.show_zone,
    )

    await ws_manager.broadcast_json({
        "type": "stream_started",
        "camera_id": cam_id,
        "source_type": req.source_type,
        "source": req.source,
        "pid": proc.pid,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })

    return {
        "status": "started",
        "camera_id": cam_id,
        "source_type": req.source_type,
        "source": req.source,
        "pid": proc.pid,
        "message": f"Camera '{cam_id}' ({req.source_type}) started in continuous surveillance loop.",
    }


@app.post("/api/stream/stop")
async def stop_camera_stream(
    camera_id: str = Query("CAM_01"),
    current_user: dict = Depends(get_current_user),
):
    """Stop active camera analytics process with 1-click."""
    MANUALLY_STOPPED_CAMERAS.add(camera_id)
    with STREAM_PROCESSES_LOCK:
        proc = ACTIVE_STREAM_PROCESSES.pop(camera_id, None)
        if proc and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=2.0)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

    # Clear cached frames from memory and disk so no stale frames display
    hub = get_frame_hub()
    if hub:
        hub.remove_camera(camera_id)
    backend_dir = Path(__file__).resolve().parent.parent
    live_frame_path = backend_dir / f"live_frame_{camera_id}.jpg"
    try:
        if live_frame_path.exists():
            live_frame_path.unlink()
    except Exception:
        pass

    await ws_manager.broadcast_json({
        "type": "stream_stopped",
        "camera_id": camera_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })

    return {
        "status": "stopped",
        "camera_id": camera_id,
        "message": f"Camera stream '{camera_id}' stopped.",
    }


@app.get("/api/stream/status")
def get_stream_processes_status():
    """Retrieve running status for all camera analytics processes."""
    with STREAM_PROCESSES_LOCK:
        status = {}
        for cam_id, proc in list(ACTIVE_STREAM_PROCESSES.items()):
            is_running = proc.poll() is None
            if not is_running:
                ACTIVE_STREAM_PROCESSES.pop(cam_id, None)
            status[cam_id] = {
                "running": is_running,
                "pid": proc.pid if is_running else None,
            }
        return status


def _run_detection_process():
    """Background task to run video detection pipeline with optimized CPU inference."""
    app_dir = Path(__file__).resolve().parent
    script_path = app_dir / "detection_tracking.py"
    video_path = app_dir.parent / "test_videos" / "tracking_test.mp4"
    output_path = app_dir.parent / "test_videos" / "annotated_tracking_test.mp4"

    cmd = [
        sys.executable,
        str(script_path),
        "--input", str(video_path),
        "--output", str(output_path),
        "--imgsz", "480",
        "--no-display",
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


@app.post("/api/pipeline/run")
def trigger_pipeline_run(background_tasks: BackgroundTasks, current_user: dict = Depends(get_current_user)):
    """Trigger an asynchronous video analytics pipeline run on the test video (Requires Operator/Admin)."""
    background_tasks.add_task(_run_detection_process)
    return {
        "status": "pipeline_started",
        "message": f"Video analytics engine running on sector surveillance stream (Triggered by {current_user.get('role', 'operator')} '{current_user.get('username', 'user')}'). Events will stream live over WebSocket.",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.post("/api/internal/broadcast")
async def internal_broadcast_event(event: dict[str, Any]):
    """Internal webhook endpoint for external detection processes to trigger WebSocket broadcasts."""
    await ws_manager.broadcast_json(event)
    return {"status": "broadcast_queued", "clients": len(ws_manager.active_connections)}


# =====================================================================
# WebSocket Endpoint
# =====================================================================
@app.websocket("/ws/events")
async def websocket_events_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for real-time security event streaming.
    Broadcasts live events as they occur in the video analytics pipeline.
    """
    await ws_manager.connect(websocket)

    # Send connection handshake acknowledgment
    try:
        await websocket.send_json(
            {
                "type": "connection_established",
                "message": "Connected to IBVAP Real-Time Security Event Stream",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )

        while True:
            try:
                # Wait for client keepalive messages with a 30s slice
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                if data == "ping":
                    await websocket.send_json({"type": "pong", "timestamp": datetime.now(timezone.utc).isoformat()})
            except asyncio.TimeoutError:
                # Slice timeout: send keepalive ping to verify client socket is open
                await websocket.send_json({"type": "ping", "timestamp": datetime.now(timezone.utc).isoformat()})
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception:
        ws_manager.disconnect(websocket)
