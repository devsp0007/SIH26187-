"""
IBVAP - Intelligent Border Video Analytics Platform
Real-Time In-Memory Frame Hub & Zero-Lag Streaming Buffer

Provides a high-throughput, lock-free in-memory frame exchange layer between
video analytics detection engines and FastAPI MJPEG streaming endpoints.
Eliminates disk I/O latency, frame tearing, and OpenCV buffer backlogs.
"""

import asyncio
import os
import threading
import time
from typing import Dict, Optional, Set
import cv2
import numpy as np

try:
    import psutil
except ImportError:
    psutil = None


class FrameHub:
    """
    Centralized thread-safe in-memory frame buffer registry and System Health Watchdog.
    Allows detection pipelines to push live annotated JPEG byte buffers directly into memory,
    which FastAPI StreamingResponse endpoints yield instantly to connected browser clients.
    Also aggregates live hardware resource vitals and bidirectional footfall metrics.
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(FrameHub, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return
        self._initialized = True
        self.start_time = time.time()
        # camera_id -> {"bytes": bytes, "timestamp": float, "frame_idx": int}
        self._frames: Dict[str, Dict[str, any]] = {}
        # camera_id -> {"footfall_in": int, "footfall_out": int, "occupancy": int, "fps": float, "updated_at": float}
        self._camera_telemetry: Dict[str, Dict[str, any]] = {}
        self._events: Dict[str, asyncio.Event] = {}
        self._subscribers: Dict[str, Set[asyncio.Queue]] = {}
        self._thread_lock = threading.Lock()

    def push_frame(
        self,
        camera_id: str,
        frame_bytes: bytes,
        frame_idx: int = 0,
    ) -> None:
        """
        Push a new JPEG frame buffer for a camera into the in-memory cache.
        Thread-safe and non-blocking for real-time video analytics engines.
        """
        now = time.time()
        with self._thread_lock:
            self._frames[camera_id] = {
                "bytes": frame_bytes,
                "timestamp": now,
                "frame_idx": frame_idx,
            }

    def push_ndarray(
        self,
        camera_id: str,
        frame: np.ndarray,
        frame_idx: int = 0,
        quality: int = 72,
    ) -> bytes:
        """
        Encode an OpenCV BGR frame directly to high-speed JPEG in memory and cache it.
        Returns the encoded JPEG bytes.
        """
        success, enc = cv2.imencode(
            ".jpg",
            frame,
            [cv2.IMWRITE_JPEG_QUALITY, quality, cv2.IMWRITE_JPEG_OPTIMIZE, 0],
        )
        if success:
            jpeg_bytes = enc.tobytes()
            self.push_frame(camera_id, jpeg_bytes, frame_idx)
            return jpeg_bytes
        return b""

    def update_telemetry(
        self,
        camera_id: str,
        footfall_in: int = 0,
        footfall_out: int = 0,
        occupancy: int = 0,
        fps: float = 0.0,
    ) -> None:
        """Update live footfall counters and stream throughput for a camera."""
        with self._thread_lock:
            self._camera_telemetry[camera_id] = {
                "footfall_in": footfall_in,
                "footfall_out": footfall_out,
                "occupancy": occupancy,
                "fps": round(fps, 1),
                "updated_at": time.time(),
            }

    def get_telemetry(self, camera_id: str) -> Dict[str, any]:
        """Retrieve latest footfall telemetry for a camera."""
        with self._thread_lock:
            return self._camera_telemetry.get(
                camera_id,
                {"footfall_in": 0, "footfall_out": 0, "occupancy": 0, "fps": 0.0, "updated_at": 0.0},
            )

    def get_all_telemetry(self) -> Dict[str, Dict[str, any]]:
        """Retrieve footfall telemetry across all monitored cameras."""
        with self._thread_lock:
            return dict(self._camera_telemetry)

    def get_system_health(self) -> Dict[str, any]:
        """Collect live host hardware vitals and pipeline health statistics."""
        uptime_sec = time.time() - self.start_time
        cpu_pct = 0.0
        ram_pct = 0.0
        ram_used_mb = 0.0
        ram_total_mb = 0.0

        if psutil is not None:
            try:
                cpu_pct = float(psutil.cpu_percent(interval=None))
                mem = psutil.virtual_memory()
                ram_pct = float(mem.percent)
                ram_used_mb = round(float(mem.used) / (1024 * 1024), 1)
                ram_total_mb = round(float(mem.total) / (1024 * 1024), 1)
            except Exception:
                pass

        with self._thread_lock:
            active_cams = sum(1 for rec in self._frames.values() if (time.time() - rec["timestamp"]) <= 3.5)
            total_in = sum(t.get("footfall_in", 0) for t in self._camera_telemetry.values())
            total_out = sum(t.get("footfall_out", 0) for t in self._camera_telemetry.values())
            total_occ = sum(t.get("occupancy", 0) for t in self._camera_telemetry.values())

        return {
            "status": "operational",
            "uptime_seconds": round(uptime_sec, 1),
            "cpu_percent": cpu_pct,
            "memory": {
                "percent": ram_pct,
                "used_mb": ram_used_mb,
                "total_mb": ram_total_mb,
            },
            "active_streams": active_cams,
            "aggregate_footfall": {
                "total_in": total_in,
                "total_out": total_out,
                "current_occupancy": total_occ,
            },
            "camera_telemetry": self.get_all_telemetry(),
        }

    def get_latest_frame(self, camera_id: str, max_age: float = 3.0) -> Optional[bytes]:
        """
        Retrieve the latest in-memory JPEG frame for a camera.
        Returns None if no frame is available or if the frame is older than max_age seconds.
        """
        with self._thread_lock:
            rec = self._frames.get(camera_id)
            if rec is not None:
                if (time.time() - rec["timestamp"]) <= max_age:
                    return rec["bytes"]
        return None

    def get_latest_frame_info(self, camera_id: str) -> Optional[Dict[str, any]]:
        """Retrieve telemetry metadata for the latest cached frame."""
        with self._thread_lock:
            rec = self._frames.get(camera_id)
            if rec is not None:
                return {
                    "timestamp": rec["timestamp"],
                    "age": time.time() - rec["timestamp"],
                    "frame_idx": rec["frame_idx"],
                    "size_bytes": len(rec["bytes"]),
                }
        return None

    def is_camera_active(self, camera_id: str, max_age: float = 3.0) -> bool:
        """Check whether fresh frames have been received within max_age seconds."""
        with self._thread_lock:
            rec = self._frames.get(camera_id)
            if rec is not None:
                return (time.time() - rec["timestamp"]) <= max_age
        return False

    def remove_camera(self, camera_id: str) -> None:
        """Clear cached frame and telemetry when a camera is stopped by the operator."""
        with self._thread_lock:
            self._frames.pop(camera_id, None)
            self._camera_telemetry.pop(camera_id, None)


# Global singleton instance
frame_hub = FrameHub()


def get_frame_hub() -> FrameHub:
    """Retrieve the global FrameHub singleton."""
    return frame_hub
