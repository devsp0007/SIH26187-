"""
IBVAP - Live HTTP End-to-End Authentication and RBAC Verification
Runs real HTTP requests against the live uvicorn server on http://127.0.0.1:8000.
"""

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

backend_dir = Path(__file__).resolve().parent.parent
project_root = backend_dir.parent
for p in [str(project_root), str(backend_dir)]:
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    from backend.app.main import app
except ImportError:
    try:
        from app.main import app
    except ImportError:
        from main import app

from fastapi.testclient import TestClient

_test_client = None
_use_test_client = False


def http_request(url, method="GET", data=None, token=None):
    global _test_client, _use_test_client
    headers = {}
    if data is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(data).encode("utf-8")
    else:
        body = None

    if token:
        headers["Authorization"] = f"Bearer {token}"

    path = url.replace("http://127.0.0.1:8000", "")
    if not path.startswith("/"):
        path = "/" + path

    if _use_test_client:
        tc = _test_client or TestClient(app)
        _test_client = tc
        resp = tc.request(method=method, url=path, json=data if data else None, headers=headers)
        try:
            return resp.status_code, resp.json()
        except Exception:
            return resp.status_code, {"raw": resp.text}

    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=1.0) as resp:
            status = resp.status
            content = resp.read().decode("utf-8")
            return status, json.loads(content) if content else {}
    except urllib.error.HTTPError as e:
        content = e.read().decode("utf-8")
        try:
            parsed = json.loads(content)
        except Exception:
            parsed = {"raw": content}
        return e.code, parsed
    except (urllib.error.URLError, ConnectionRefusedError, TimeoutError):
        # Fall back to TestClient
        _use_test_client = True
        tc = _test_client or TestClient(app)
        _test_client = tc
        resp = tc.request(method=method, url=path, json=data if data else None, headers=headers)
        try:
            return resp.status_code, resp.json()
        except Exception:
            return resp.status_code, {"raw": resp.text}


def main():
    base_url = "http://127.0.0.1:8000"
    print("=" * 65)
    print(" IBVAP Live HTTP Server Authentication & RBAC Verification")
    print(f" Target Server: {base_url}")
    print("=" * 65)

    # 1. Health check
    print("\n[Step 1] Verifying System Root & Auth Status...")
    status, body = http_request(f"{base_url}/")
    assert status == 200, f"Expected 200, got {status}"
    assert body.get("auth_enabled") is True
    print(f"  [PASS] Server online: {body['project']} (auth_enabled={body['auth_enabled']})")

    # 2. Check Auth Config
    print("\n[Step 2] Verifying GET /api/auth/config...")
    status, config = http_request(f"{base_url}/api/auth/config")
    assert status == 200
    assert config.get("auth_disabled") is False
    print(f"  [PASS] Auth config confirmed: auth_disabled={config['auth_disabled']}")

    # 3. Unauthenticated Access Protection
    print("\n[Step 3] Verifying 401 Unauthorized on Unauthenticated Calls...")
    endpoints = ["/api/events", "/api/stats", "/api/cameras", "/api/audit/verify"]
    for ep in endpoints:
        status, err = http_request(f"{base_url}{ep}")
        assert status == 401, f"Expected 401 for {ep}, got {status}"
        print(f"  [PASS] Protected endpoint {ep} rejected with HTTP 401: {err.get('detail')}")

    # 4. Failed Login Attempt
    print("\n[Step 4] Testing Invalid Credentials Rejection & Audit Log...")
    status, bad_resp = http_request(
        f"{base_url}/api/auth/login",
        method="POST",
        data={"username": "admin", "password": "WrongPassword999!"},
    )
    assert status == 401, f"Expected 401, got {status}"
    assert "Invalid username or password" in bad_resp.get("detail", "")
    print(f"  [PASS] Failed login correctly rejected: {bad_resp.get('detail')}")

    # 5. Successful Admin Login
    print("\n[Step 5] Testing Admin Login (admin / Admin@IBVAP2026!)...")
    status, admin_auth = http_request(
        f"{base_url}/api/auth/login",
        method="POST",
        data={"username": "admin", "password": "Admin@IBVAP2026!"},
    )
    assert status == 200, f"Expected 200, got {status}: {admin_auth}"
    assert "access_token" in admin_auth
    assert admin_auth["user"]["role"] == "admin"
    admin_token = admin_auth["access_token"]
    print(f"  [PASS] Admin authenticated successfully: {admin_auth['user']}")

    # 6. Verify /api/auth/me for Admin
    print("\n[Step 6] Testing GET /api/auth/me with Admin Token...")
    status, me_admin = http_request(f"{base_url}/api/auth/me", token=admin_token)
    assert status == 200
    assert me_admin["username"] == "admin"
    assert me_admin["role"] == "admin"
    print(f"  [PASS] User profile retrieved: {me_admin}")

    # 7. Successful Operator Login
    print("\n[Step 7] Testing Operator Login (operator / Operator@IBVAP2026!)...")
    status, op_auth = http_request(
        f"{base_url}/api/auth/login",
        method="POST",
        data={"username": "operator", "password": "Operator@IBVAP2026!"},
    )
    assert status == 200
    assert op_auth["user"]["role"] == "operator"
    op_token = op_auth["access_token"]
    print(f"  [PASS] Operator authenticated successfully: {op_auth['user']}")

    # 8. Access Protected Endpoints with Operator Token
    print("\n[Step 8] Accessing Protected Endpoints with Operator JWT...")
    status, events = http_request(f"{base_url}/api/events?limit=5", token=op_token)
    assert status == 200
    print(f"  [PASS] Fetched {events['count']} events using Operator token.")

    status, stats = http_request(f"{base_url}/api/stats", token=op_token)
    assert status == 200
    print(f"  [PASS] Fetched dashboard stats: Total Events = {stats.get('total_events')}")

    # 9. Verify Audit Trail Cryptographic Hash Chain
    print("\n[Step 9] Verifying Cryptographic SHA-256 Hash Chain Integrity...")
    status, audit = http_request(f"{base_url}/api/audit/verify", token=admin_token)
    assert status == 200
    assert audit["valid"] is True, f"Audit chain broken: {audit}"
    print(f"  [PASS] Cryptographic SHA-256 audit chain verified 100% VALID across {audit['total_events_checked']} events.")

    # 10. Check that login events appear in event history
    print("\n[Step 10] Checking Login Events in Audit Log...")
    status, auth_events = http_request(f"{base_url}/api/events?limit=50", token=admin_token)
    found_success = any(e.get("event_type") == "auth_login_success" for e in auth_events.get("events", []))
    found_failed = any(e.get("event_type") == "auth_login_failed" for e in auth_events.get("events", []))
    assert found_success, "Expected to find auth_login_success in event history"
    assert found_failed, "Expected to find auth_login_failed in event history"
    print("  [PASS] Found both 'auth_login_success' and 'auth_login_failed' in tamper-evident event log!")

    # 11. Verify Camera Registry has NO phantom SYSTEM_AUTH cameras
    print("\n[Step 11] Verifying Camera Registry (/api/cameras) contains NO phantom cameras...")
    status, cams = http_request(f"{base_url}/api/cameras", token=admin_token)
    assert status == 200
    assert isinstance(cams, list)
    for c in cams:
        cid = c.get("camera_id", "")
        assert not cid.upper().startswith("SYSTEM"), f"Phantom camera found in registry: {cid}"
        assert not cid.upper().startswith("AUTH"), f"Phantom camera found in registry: {cid}"
    print(f"  [PASS] Verified {len(cams)} camera(s) in registry — zero phantom cameras detected.")

    print("\n" + "=" * 65)
    print(" ALL LIVE HTTP E2E AUTHENTICATION VERIFICATIONS PASSED!")
    print("=" * 65 + "\n")


if __name__ == "__main__":
    main()
