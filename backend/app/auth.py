"""
IBVAP - Intelligent Border Video Analytics Platform
Role-Based Access Control (RBAC) & JWT Authentication Module

Provides:
- SQLite users table management and seed accounts (admin / operator)
- Bcrypt password hashing & cryptographic verification
- JWT token issuing, verification, and decoding (PyJWT)
- FastAPI authentication dependencies & role guards
- Emergency demo safety bypass mode (DISABLE_AUTH=true)
"""

import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

# Cryptographic and JWT Configuration
SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "ibvap_tactical_cyber_defense_jwt_secret_2026_sih")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 hours

# Bearer token extractor (auto_error=False allows handling DISABLE_AUTH smoothly)
security_scheme = HTTPBearer(auto_error=False)

DEFAULT_USERS = [
    {
        "username": "admin",
        "password": "Admin@IBVAP2026!",
        "role": "admin",
        "full_name": "Command Center Admin",
    },
    {
        "username": "operator",
        "password": "Operator@IBVAP2026!",
        "role": "operator",
        "full_name": "Surveillance Operator",
    },
    {
        "username": "supervisor",
        "password": "Supervisor@IBVAP2026!",
        "role": "supervisor",
        "full_name": "Shift Supervisor (Middle Person)",
    },
]


def is_auth_disabled() -> bool:
    """Check if authentication is disabled for live demo fallback via environment variable."""
    val = os.environ.get("DISABLE_AUTH", "").strip().lower()
    return val in ("true", "1", "yes", "on")


def get_default_db_path() -> Path:
    """Get the default SQLite database path."""
    backend_dir = Path(__file__).resolve().parent.parent
    return backend_dir / "ibvap.db"


def hash_password(password: str) -> str:
    """Hash a plaintext password with bcrypt salt."""
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify plaintext password against stored bcrypt hash."""
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"),
            hashed_password.encode("utf-8"),
        )
    except Exception:
        return False


def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """Generate signed JWT token containing user identity and role."""
    to_encode = data.copy()
    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode.update({
        "exp": expire,
        "iat": now,
    })
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> Optional[Dict[str, Any]]:
    """Decode and validate a signed JWT token."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.PyJWTError:
        return None


def init_users_table(db_path: Optional[Path] = None) -> Path:
    """
    Initialize SQLite users table and seed default admin and operator credentials if missing.
    Prints default credentials to console on first creation.
    """
    if db_path is None:
        db_path = get_default_db_path()

    db_path.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(db_path, timeout=10.0) as conn:
        cursor = conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA busy_timeout=5000;")
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL,
                full_name TEXT,
                created_at TEXT NOT NULL,
                last_login TEXT
            )
            """
        )

        seeded_any = False
        now_str = datetime.now(timezone.utc).isoformat()

        for user in DEFAULT_USERS:
            cursor.execute("SELECT username FROM users WHERE username = ?", (user["username"],))
            row = cursor.fetchone()
            if not row:
                pw_hash = hash_password(user["password"])
                cursor.execute(
                    """
                    INSERT INTO users (username, password_hash, role, full_name, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (user["username"], pw_hash, user["role"], user["full_name"], now_str),
                )
                seeded_any = True

        conn.commit()

    if seeded_any:
        print("\n" + "=" * 65)
        print(" [AUTH] IBVAP Role-Based Access Control Initialized")
        print(" Seeded Default Accounts:")
        for u in DEFAULT_USERS:
            print(f"   * Role '{u['role'].upper():<8}': username='{u['username']}', password='{u['password']}'")
        print("=" * 65 + "\n")

    return db_path


def get_user_by_username(username: str, db_path: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    """Fetch user record by username."""
    if db_path is None:
        db_path = get_default_db_path()

    if not db_path.exists():
        return None

    try:
        with sqlite3.connect(db_path, timeout=10.0) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
            row = cursor.fetchone()
            if row:
                return dict(row)
    except Exception:
        pass
    return None


def update_user_last_login(username: str, db_path: Optional[Path] = None):
    """Update last_login timestamp for a user."""
    if db_path is None:
        db_path = get_default_db_path()

    try:
        with sqlite3.connect(db_path, timeout=10.0) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE users SET last_login = ? WHERE username = ?",
                (datetime.now(timezone.utc).isoformat(), username),
            )
            conn.commit()
    except Exception:
        pass


def authenticate_user(username: str, password: str, db_path: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    """Validate username and password against SQLite database."""
    user = get_user_by_username(username, db_path=db_path)
    if not user:
        return None
    if not verify_password(password, user["password_hash"]):
        return None
    return {
        "username": user["username"],
        "role": user["role"],
        "full_name": user.get("full_name") or user["username"],
        "created_at": user.get("created_at"),
        "last_login": user.get("last_login"),
    }


# =====================================================================
# FastAPI Dependencies
# =====================================================================
async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security_scheme),
) -> Dict[str, Any]:
    """
    FastAPI dependency that extracts and validates the Bearer JWT token.
    If DISABLE_AUTH=true is set, automatically returns a demo admin user.
    """
    if is_auth_disabled():
        return {
            "username": "demo_admin",
            "role": "admin",
            "full_name": "Demo Admin (Bypass Mode)",
            "auth_disabled": True,
        }

    if not credentials or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Missing Bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session token. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    username: Optional[str] = payload.get("sub")
    if not username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed token payload.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return {
        "username": username,
        "role": payload.get("role", "operator"),
        "full_name": payload.get("name", username),
        "auth_disabled": False,
    }


def require_admin(current_user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """FastAPI dependency to ensure the user has 'admin' privileges."""
    if current_user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrative privileges required for this action.",
        )
    return current_user

def require_supervisor_or_admin(current_user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """FastAPI dependency to ensure the user has at least 'supervisor' privileges."""
    if current_user.get("role") not in ["admin", "supervisor"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Supervisor or Administrative privileges required for this action.",
        )
    return current_user
