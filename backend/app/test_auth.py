"""
IBVAP - Authentication and RBAC Verification Suite
Tests:
1. SQLite users table initialization & password hashing (bcrypt)
2. JWT generation & validation (PyJWT)
3. POST /api/auth/login with valid/invalid credentials
4. GET /api/auth/me with Bearer token
5. Protected endpoints rejection without token (HTTP 401)
6. Cryptographic SHA-256 audit trail chain verification with login events
7. Emergency demo safety bypass (DISABLE_AUTH=true)
"""

import os
import sys
from pathlib import Path
from fastapi.testclient import TestClient

# Ensure backend root is on sys.path
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.main import app
from app.auth import (
    authenticate_user,
    create_access_token,
    decode_access_token,
    hash_password,
    init_users_table,
    verify_password,
)
from app.events import init_db, verify_chain_integrity


def run_all_tests():
    print("=" * 65)
    print(" IBVAP Tactical Auth & Role-Based Access Control Test Suite")
    print("=" * 65)

    # 1. Test Password Hashing and Verification
    print("\n[1/7] Testing Bcrypt Password Hashing & Cryptographic Verification...")
    raw_pw = "TestSecretPassword123!"
    hashed = hash_password(raw_pw)
    assert hashed != raw_pw, "Password hash must not match plaintext"
    assert verify_password(raw_pw, hashed) is True, "Valid password should verify"
    assert verify_password("WrongPassword!", hashed) is False, "Invalid password should fail"
    print("  [PASS] Password hashing & verification verified.")

    # 2. Test JWT Token Creation & Decoding
    print("\n[2/7] Testing JWT Token Generation & Claims Extraction...")
    token = create_access_token({"sub": "admin", "role": "admin", "name": "Admin User"})
    payload = decode_access_token(token)
    assert payload is not None, "JWT decoding failed"
    assert payload["sub"] == "admin", "Subject claim mismatch"
    assert payload["role"] == "admin", "Role claim mismatch"
    assert "exp" in payload, "Expiration claim missing"

    bad_payload = decode_access_token("invalid.jwt.token.string")
    assert bad_payload is None, "Invalid token string should return None"
    print("  [PASS] JWT token generation and decoding verified.")

    # 3. Test Database User Seeding and Auth
    print("\n[3/7] Testing SQLite User Persistence & Default Seed Accounts...")
    init_db()
    admin_auth = authenticate_user("admin", "Admin@IBVAP2026!")
    assert admin_auth is not None, "Seeded admin account failed authentication"
    assert admin_auth["role"] == "admin", f"Expected admin role, got {admin_auth['role']}"

    op_auth = authenticate_user("operator", "Operator@IBVAP2026!")
    assert op_auth is not None, "Seeded operator account failed authentication"
    assert op_auth["role"] == "operator", f"Expected operator role, got {op_auth['role']}"

    bad_auth = authenticate_user("admin", "WrongPassword999!")
    assert bad_auth is None, "Bad password should return None"
    print("  [PASS] Seeded admin and operator credentials successfully authenticated.")

    # 4. Test REST API Login & Rejection
    print("\n[4/7] Testing REST API /api/auth/login and /api/auth/me Endpoints...")
    client = TestClient(app)

    # 4a. Bad Login
    res_bad = client.post("/api/auth/login", json={"username": "admin", "password": "WrongPassword!"})
    assert res_bad.status_code == 401, f"Expected 401, got {res_bad.status_code}"
    print("  [PASS] Invalid password correctly rejected with HTTP 401.")

    # 4b. Admin Login
    res_admin = client.post("/api/auth/login", json={"username": "admin", "password": "Admin@IBVAP2026!"})
    assert res_admin.status_code == 200, f"Login failed: {res_admin.text}"
    admin_data = res_admin.json()
    assert "access_token" in admin_data, "Missing access_token in response"
    assert admin_data["user"]["role"] == "admin"
    admin_token = admin_data["access_token"]

    # 4c. Operator Login
    res_op = client.post("/api/auth/login", json={"username": "operator", "password": "Operator@IBVAP2026!"})
    assert res_op.status_code == 200, f"Operator login failed: {res_op.text}"
    op_data = res_op.json()
    assert op_data["user"]["role"] == "operator"
    op_token = op_data["access_token"]

    # 4d. Test /api/auth/me
    res_me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {admin_token}"})
    assert res_me.status_code == 200, f"Failed /api/auth/me: {res_me.text}"
    assert res_me.json()["username"] == "admin"
    assert res_me.json()["role"] == "admin"
    print("  [PASS] Login endpoint and /api/auth/me verified for both roles.")

    # 5. Test Endpoint Protection
    print("\n[5/7] Testing Protection on Sensitive Security Endpoints...")
    # Unauthenticated request to /api/events should fail
    res_unauth = client.get("/api/events")
    assert res_unauth.status_code == 401, f"Expected 401 for unauthenticated request, got {res_unauth.status_code}"

    # Authenticated request with Bearer token should succeed
    res_auth = client.get("/api/events", headers={"Authorization": f"Bearer {op_token}"})
    assert res_auth.status_code == 200, f"Expected 200 for authenticated request, got {res_auth.status_code}"
    print("  [PASS] Sensitive endpoints successfully reject unauthenticated calls and accept valid JWT.")

    # 6. Test Audit Trail Cryptographic Hash Chain Integrity
    print("\n[6/7] Testing Cryptographic SHA-256 Audit Trail Integrity with Login Events...")
    integrity = verify_chain_integrity()
    assert integrity["valid"] is True, f"Audit trail hash chain broken: {integrity}"
    print(f"  [PASS] SHA-256 hash chain verified 100% intact across {integrity['total_events_checked']} events.")

    # 7. Test DISABLE_AUTH Demo Bypass
    print("\n[7/8] Testing DISABLE_AUTH Demo Safety Bypass...")
    os.environ["DISABLE_AUTH"] = "true"
    res_bypass = client.get("/api/events")
    assert res_bypass.status_code == 200, f"Expected 200 with DISABLE_AUTH=true, got {res_bypass.status_code}"
    res_bypass_me = client.get("/api/auth/me")
    assert res_bypass_me.status_code == 200
    assert res_bypass_me.json()["auth_disabled"] is True
    os.environ.pop("DISABLE_AUTH", None)
    print("  [PASS] DISABLE_AUTH=true bypass mode works smoothly.")

    # 8. Test Camera Registry Purity (No Phantom SYSTEM_AUTH entries)
    print("\n[8/8] Testing Camera Registry for Zero Phantom Cameras...")
    res_cams = client.get("/api/cameras", headers={"Authorization": f"Bearer {admin_token}"})
    assert res_cams.status_code == 200
    cams_list = res_cams.json()
    for c in cams_list:
        cid = c.get("camera_id", "")
        assert not cid.upper().startswith("SYSTEM"), f"Phantom camera found in registry: {cid}"
        assert not cid.upper().startswith("AUTH"), f"Phantom camera found in registry: {cid}"
    print(f"  [PASS] Verified {len(cams_list)} registered cameras — zero phantom cameras present.")

    print("\n" + "=" * 65)
    print(" ALL 8 AUTHENTICATION & RBAC TEST PHASES PASSED SUCCESSFULLY!")
    print("=" * 65 + "\n")


if __name__ == "__main__":
    run_all_tests()
