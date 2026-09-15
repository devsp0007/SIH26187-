"""
IBVAP - Tactical Admin Management Module
Provides backend database management and validation for:
1. Authorized Personnel Watchlist (with photo management and expiry dates)
2. Authorized Vehicles Whitelist (with ANPR plate normalization and expiry dates)
3. On-demand Watchlist embedding re-synchronization
"""

import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


def get_default_db_path() -> Path:
    """Get default SQLite database path."""
    backend_dir = Path(__file__).resolve().parent.parent
    return backend_dir / "ibvap.db"


def get_watchlist_dir() -> Path:
    """Get default watchlist photos directory."""
    backend_dir = Path(__file__).resolve().parent.parent
    watchlist_dir = backend_dir / "watchlist"
    watchlist_dir.mkdir(parents=True, exist_ok=True)
    return watchlist_dir


def normalize_plate(plate_number: Optional[str]) -> str:
    """Normalize license plate text by stripping punctuation/whitespace and converting to uppercase."""
    if not plate_number:
        return ""
    return re.sub(r"[^A-Z0-9]", "", str(plate_number).upper())


def is_expired(expiry_date: Optional[str]) -> bool:
    """
    Check if an expiry date has passed relative to current UTC date.
    Returns False if expiry_date is None or empty (i.e. permanently authorized).
    """
    if not expiry_date or not str(expiry_date).strip():
        return False

    clean_str = str(expiry_date).strip()
    # Handle YYYY-MM-DD or full ISO-8601 strings
    try:
        if "T" in clean_str:
            clean_str = clean_str.split("T")[0]
        elif " " in clean_str:
            clean_str = clean_str.split(" ")[0]

        parts = [int(p) for p in clean_str.split("-") if p.isdigit()]
        if len(parts) >= 3:
            exp_date = datetime(parts[0], parts[1], parts[2], tzinfo=timezone.utc).date()
            today_utc = datetime.now(timezone.utc).date()
            return exp_date < today_utc
    except Exception:
        pass
    return False


def init_admin_tables(db_path: Optional[Path] = None):
    """
    Initialize SQLite tables for watchlist personnel and authorized vehicles.
    Automatically seeds initial records for existing reference images and sample vehicles.
    """
    if db_path is None:
        db_path = get_default_db_path()

    with sqlite3.connect(db_path, timeout=10.0) as conn:
        cursor = conn.cursor()

        # 1. Watchlist Personnel Table
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS watchlist_personnel (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                role TEXT NOT NULL DEFAULT 'SSB Personnel',
                photo_filename TEXT NOT NULL,
                expiry_date TEXT,
                notes TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )

        # 2. Authorized Vehicles Whitelist Table
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS authorized_vehicles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                plate_number TEXT UNIQUE NOT NULL,
                owner_name TEXT NOT NULL,
                vehicle_type TEXT NOT NULL DEFAULT 'Patrol Vehicle',
                purpose TEXT NOT NULL DEFAULT 'Official Duty',
                expiry_date TEXT,
                notes TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.commit()

        # Seed existing photo files from backend/watchlist/ if watchlist_personnel is empty
        cursor.execute("SELECT COUNT(*) FROM watchlist_personnel")
        count_wl = cursor.fetchone()[0]
        if count_wl == 0:
            now_iso = datetime.now(timezone.utc).isoformat()
            watchlist_dir = get_watchlist_dir()
            default_roles = {
                "kunal": "SSB Personnel",
                "aditya": "Border Patrol Officer",
                "akanksha": "Command Staff",
                "anshika": "Border Patrol Officer",
                "atul": "Surveillance Operator",
            }

            for p in sorted(watchlist_dir.iterdir()):
                if p.suffix.lower() in [".png", ".jpg", ".jpeg"]:
                    stem_clean = p.stem.strip()
                    display_name = stem_clean.replace("_", " ").title()
                    role = default_roles.get(stem_clean.lower(), "SSB Personnel")
                    cursor.execute(
                        """
                        INSERT OR IGNORE INTO watchlist_personnel
                        (name, role, photo_filename, expiry_date, notes, created_at, updated_at)
                        VALUES (?, ?, ?, NULL, 'Pre-configured reference profile', ?, ?)
                        """,
                        (display_name, role, p.name, now_iso, now_iso),
                    )
            conn.commit()

        # Seed initial authorized vehicles if table is empty
        cursor.execute("SELECT COUNT(*) FROM authorized_vehicles")
        count_veh = cursor.fetchone()[0]
        if count_veh == 0:
            now_iso = datetime.now(timezone.utc).isoformat()
            default_vehicles = [
                ("DL 01 AB 1234", "Capt. Rajesh Kumar", "Patrol Jeep", "Sector 4 Perimeter Patrol", None, "Command Escort Vehicle"),
                ("JK 02 CD 5678", "Subedar Major Singh", "Supply Truck", "Ration & Ammo Logistics", None, "Battalion Logistics Unit"),
                ("HR 26 EF 9012", "Dr. A. Verma", "Medical Ambulance", "Emergency Medical Support", None, "Perimeter Quick Response Unit"),
            ]
            for plate, owner, vtype, purpose, exp, notes in default_vehicles:
                cursor.execute(
                    """
                    INSERT OR IGNORE INTO authorized_vehicles
                    (plate_number, owner_name, vehicle_type, purpose, expiry_date, notes, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (plate, owner, vtype, purpose, exp, notes, now_iso, now_iso),
                )
            conn.commit()


# =====================================================================
# Watchlist Personnel CRUD Operations
# =====================================================================
def get_all_watchlist_personnel(db_path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Retrieve all watchlist personnel profiles with real-time expiry evaluation."""
    if db_path is None:
        db_path = get_default_db_path()
    init_admin_tables(db_path)

    with sqlite3.connect(db_path, timeout=10.0) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM watchlist_personnel ORDER BY name ASC")
        rows = cursor.fetchall()
        results = []
        for r in rows:
            d = dict(r)
            d["is_expired"] = is_expired(d.get("expiry_date"))
            d["photo_url"] = f"/api/admin/watchlist/photo/{d['photo_filename']}"
            results.append(d)
        return results


def get_watchlist_person(name: str, db_path: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    """Lookup a single watchlist person by name."""
    if db_path is None:
        db_path = get_default_db_path()
    init_admin_tables(db_path)

    with sqlite3.connect(db_path, timeout=10.0) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM watchlist_personnel WHERE LOWER(name) = LOWER(?)", (name.strip(),))
        row = cursor.fetchone()
        if not row:
            return None
        d = dict(row)
        d["is_expired"] = is_expired(d.get("expiry_date"))
        d["photo_url"] = f"/api/admin/watchlist/photo/{d['photo_filename']}"
        return d


def check_watchlist_person_active(name: Optional[str], db_path: Optional[Path] = None) -> bool:
    """
    Evaluate if an identified person is active on the authorized watchlist.
    Returns False if expired (logs note) or if unlisted.
    """
    if not name or not isinstance(name, str) or name.upper() == "UNKNOWN":
        return False

    person = get_watchlist_person(name, db_path=db_path)
    if person:
        if person["is_expired"]:
            print(f"[!] Expired watchlist profile skipped: '{name}' (Expired on {person['expiry_date']})")
            return False
        return True

    # If file exists in watchlist folder but not yet in DB, treat as active
    clean_name = name.strip().replace(" ", "_").lower()
    for ext in [".png", ".jpg", ".jpeg"]:
        p = get_watchlist_dir() / f"{clean_name}{ext}"
        if p.exists():
            return True
    return False


def add_or_update_watchlist_person(
    name: str,
    role: str = "SSB Personnel",
    photo_filename: str = "",
    expiry_date: Optional[str] = None,
    notes: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Add or update an authorized person in SQLite."""
    if db_path is None:
        db_path = get_default_db_path()
    init_admin_tables(db_path)

    now_iso = datetime.now(timezone.utc).isoformat()
    clean_name = name.strip()

    with sqlite3.connect(db_path, timeout=10.0) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO watchlist_personnel (name, role, photo_filename, expiry_date, notes, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                role = excluded.role,
                photo_filename = CASE WHEN excluded.photo_filename != '' THEN excluded.photo_filename ELSE watchlist_personnel.photo_filename END,
                expiry_date = excluded.expiry_date,
                notes = excluded.notes,
                updated_at = excluded.updated_at
            """,
            (clean_name, role.strip(), photo_filename.strip(), expiry_date or None, notes or None, now_iso, now_iso),
        )
        conn.commit()

    return get_watchlist_person(clean_name, db_path=db_path) or {}


def delete_watchlist_person(name: str, db_path: Optional[Path] = None) -> bool:
    """Delete person from database and remove their photo from backend/watchlist/."""
    if db_path is None:
        db_path = get_default_db_path()
    init_admin_tables(db_path)

    clean_name = name.strip()
    person = get_watchlist_person(clean_name, db_path=db_path)
    if not person:
        return False

    photo_filename = person.get("photo_filename")
    if photo_filename:
        photo_path = get_watchlist_dir() / photo_filename
        if photo_path.exists():
            try:
                photo_path.unlink()
            except Exception as e:
                print(f"[!] Warning: Could not delete photo file {photo_path}: {e}")

    with sqlite3.connect(db_path, timeout=10.0) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM watchlist_personnel WHERE LOWER(name) = LOWER(?)", (clean_name,))
        conn.commit()

    return True


# =====================================================================
# Authorized Vehicles Whitelist CRUD Operations
# =====================================================================
def get_all_authorized_vehicles(db_path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Retrieve all authorized vehicles with real-time expiry evaluation."""
    if db_path is None:
        db_path = get_default_db_path()
    init_admin_tables(db_path)

    with sqlite3.connect(db_path, timeout=10.0) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM authorized_vehicles ORDER BY plate_number ASC")
        rows = cursor.fetchall()
        results = []
        for r in rows:
            d = dict(r)
            d["is_expired"] = is_expired(d.get("expiry_date"))
            d["normalized_plate"] = normalize_plate(d["plate_number"])
            results.append(d)
        return results


def check_authorized_vehicle(plate_number: Optional[str], db_path: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    """
    Evaluate if an ANPR license plate matches an active, non-expired authorized vehicle.
    Returns vehicle record if authorized and active, or None if unlisted or expired (logs note on expiry).
    """
    if not plate_number or not isinstance(plate_number, str):
        return None

    cand_norm = normalize_plate(plate_number)
    if not cand_norm or len(cand_norm) < 4:
        return None

    vehicles = get_all_authorized_vehicles(db_path=db_path)
    for v in vehicles:
        if v["normalized_plate"] == cand_norm:
            if v["is_expired"]:
                print(f"[!] Expired authorized vehicle skipped: '{plate_number}' (Owner: {v['owner_name']}, Expired: {v['expiry_date']})")
                return None
            return v

    return None


def add_or_update_authorized_vehicle(
    plate_number: str,
    owner_name: str,
    vehicle_type: str = "Patrol Vehicle",
    purpose: str = "Official Duty",
    expiry_date: Optional[str] = None,
    notes: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Add or update an authorized vehicle in SQLite."""
    if db_path is None:
        db_path = get_default_db_path()
    init_admin_tables(db_path)

    now_iso = datetime.now(timezone.utc).isoformat()
    clean_plate = plate_number.strip().upper()

    with sqlite3.connect(db_path, timeout=10.0) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO authorized_vehicles (plate_number, owner_name, vehicle_type, purpose, expiry_date, notes, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(plate_number) DO UPDATE SET
                owner_name = excluded.owner_name,
                vehicle_type = excluded.vehicle_type,
                purpose = excluded.purpose,
                expiry_date = excluded.expiry_date,
                notes = excluded.notes,
                updated_at = excluded.updated_at
            """,
            (
                clean_plate,
                owner_name.strip(),
                vehicle_type.strip(),
                purpose.strip(),
                expiry_date.strip() if expiry_date else None,
                notes.strip() if notes else None,
                now_iso,
                now_iso,
            ),
        )
        conn.commit()

    vehicles = get_all_authorized_vehicles(db_path=db_path)
    for v in vehicles:
        if normalize_plate(v["plate_number"]) == normalize_plate(clean_plate):
            return v
    return {}


def delete_authorized_vehicle(plate_number: str, db_path: Optional[Path] = None) -> bool:
    """Remove a vehicle from the authorized whitelist."""
    if db_path is None:
        db_path = get_default_db_path()
    init_admin_tables(db_path)

    target_norm = normalize_plate(plate_number)
    vehicles = get_all_authorized_vehicles(db_path=db_path)
    exact_plate = None
    for v in vehicles:
        if v["normalized_plate"] == target_norm:
            exact_plate = v["plate_number"]
            break

    if not exact_plate:
        return False

    with sqlite3.connect(db_path, timeout=10.0) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM authorized_vehicles WHERE plate_number = ?", (exact_plate,))
        conn.commit()

    return True
