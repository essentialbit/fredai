#!/usr/bin/env python3
import sys
import re
import os
import random
import secrets
import hashlib
import requests
from pathlib import Path

# Paths
BASE_DIR = Path("/Volumes/Iron 1TBSSD/Claude/FredAI")
REQUIREMENTS_FILE = BASE_DIR / "requirements.txt"

print("=========================================================")
print("          FredAI End-to-End QA & Security Audit          ")
print("=========================================================")

errors = []

# 1. SBOM Audit
print("\n[1/4] Running SBOM Audit...")
if not REQUIREMENTS_FILE.exists():
    errors.append("requirements.txt missing")
else:
    with open(REQUIREMENTS_FILE) as f:
        reqs = [line.strip() for line in f if line.strip() and not line.startswith("#")]
    print(f"  Found {len(reqs)} primary dependencies:")
    for r in reqs:
        print(f"    - {r}")
    
    # Check for insecure or obsolete packages in requirements
    for r in reqs:
        if "requests<2.31.0" in r:
            errors.append(f"Insecure package dependency: {r} (Requests before 2.31.0 is vulnerable)")
        if "werkzeug<3.0.1" in r:
            errors.append(f"Insecure package dependency: {r} (Werkzeug before 3.0.1 has potential vulnerabilities)")
        if "flask<3.0.0" in r:
            errors.append(f"Outdated package dependency: {r}")

# 2. SAST (Static Application Security Testing)
print("\n[2/4] Running SAST Code Inspection...")
source_files = list(BASE_DIR.glob("*.py"))
print(f"  Scanning {len(source_files)} python source files in root...")

hardcoded_keys_pat = re.compile(r'(api_key|secret|token|password)\s*=\s*["\'][a-zA-Z0-9_\-]{16,}["\']', re.IGNORECASE)
subprocess_pat = re.compile(r'subprocess\.(run|Popen|call)\(.*shell\s*=\s*True', re.IGNORECASE)
sql_interpolation_pat = re.compile(r'\.execute\(.*%s|f"SELECT.*WHERE.*\b\w+\s*=\s*\{', re.IGNORECASE)

for fpath in source_files:
    if fpath.name.startswith("._"):
        continue
    try:
        content = fpath.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        continue
    
    # Check for hardcoded secrets
    for m in hardcoded_keys_pat.finditer(content):
        # Allow examples or test placeholders
        if "test" not in m.group(0).lower() and "dummy" not in m.group(0).lower():
            errors.append(f"Potential hardcoded secret in {fpath.name}: {m.group(0)}")
            
    # Check for shell=True subprocess calls (injection risk)
    for m in subprocess_pat.finditer(content):
        errors.append(f"Subprocess run with shell=True in {fpath.name}: {m.group(0)}")
        
    # Check for SQL injection patterns
    for m in sql_interpolation_pat.finditer(content):
        errors.append(f"Potential raw SQL interpolation in {fpath.name}: {m.group(0)}")

# 3. DAST (Dynamic Application Security Testing)
print("\n[3/4] Running DAST Endpoints Scan...")
session = requests.Session()
host = "http://localhost:8080"

try:
    # Check HTTP Headers & Security Settings
    res = session.get(f"{host}/")
    print(f"  Connected to server: {res.status_code}")
    
    headers = res.headers
    # Check security headers
    if "X-Frame-Options" not in headers:
        print("  [Warning] Missing X-Frame-Options header (potential clickjacking)")
    else:
        print(f"    X-Frame-Options: {headers['X-Frame-Options']}")
        
    if "X-Content-Type-Options" not in headers:
        print("  [Warning] Missing X-Content-Type-Options header")
    else:
        print(f"    X-Content-Type-Options: {headers['X-Content-Type-Options']}")
        
    # Check Session Cookie Security attributes
    cookies = session.cookies
    for cookie in cookies:
        if cookie.name == "session":
            print(f"    Session Cookie attributes:")
            print(f"      HttpOnly: {cookie.has_nonstandard_attr('HttpOnly') or 'HttpOnly' in str(cookie)}")
            print(f"      Secure: {cookie.secure}")
            print(f"      SameSite: {cookie.get_nonstandard_attr('SameSite')}")

except Exception as e:
    errors.append(f"Could not connect to FredAI server at {host}: {e}. Ensure it is running.")

# 4. Simulated UX & Acceptance Testing
if not errors:
    print("\n[4/4] Running Simulated UX & Acceptance Tests...")
    try:
        # Step A: Status check when anonymous
        res = session.get(f"{host}/api/auth/status")
        auth_status = res.json()
        assert auth_status["status"] == "anonymous", f"Expected anonymous, got {auth_status}"
        print("  ✓ Status anonymous verify: Success")
        
        # Step B: API access check (should fail 401)
        res = session.get(f"{host}/api/init")
        assert res.status_code == 401, f"Expected 401 for unauthorized /api/init, got {res.status_code}"
        print("  ✓ API Authorization guard verify: Success")
        
        # Step C: Register new user
        test_user = f"qa_test_{secrets.token_hex(4)}"
        test_pass = "qa_pass_12345"
        res = session.post(f"{host}/register", json={
            "username": test_user,
            "password": test_pass,
            "display_name": "QA Tester",
            "consent_accepted": False
        })
        assert res.status_code == 200, f"Register failed: {res.text}"
        print(f"  ✓ User registration ({test_user}): Success")
        
        # Step D: Verify status is now 'pending' (disclaimer not accepted yet)
        res = session.get(f"{host}/api/auth/status")
        auth_status = res.json()
        assert auth_status["status"] == "pending", f"Expected pending status, got {auth_status}"
        print("  ✓ User disclaimer status 'pending' verify: Success")
        
        # Step E: Accept disclaimer
        res = session.post(f"{host}/api/user/accept-disclaimer", json={"version": "1.0"})
        assert res.status_code == 200, f"Accepting disclaimer failed: {res.text}"
        print("  ✓ Accepted disclaimer: Success")
        
        # Step F: Verify status is now 'accepted'
        res = session.get(f"{host}/api/auth/status")
        auth_status = res.json()
        assert auth_status["status"] == "accepted", f"Expected accepted status, got {auth_status}"
        print("  ✓ User disclaimer status 'accepted' verify: Success")
        
        # Step G: Access /api/init (should succeed)
        res = session.get(f"{host}/api/init")
        assert res.status_code == 200, f"API init failed for logged-in user: {res.text}"
        print("  ✓ API access authorized verify: Success")
        
        # Step H: Change Password
        res = session.post(f"{host}/api/user/change-password", json={
            "current_password": test_pass,
            "new_password": "new_qa_password"
        })
        assert res.status_code == 200, f"Change password failed: {res.text}"
        print("  ✓ Change password verify: Success")
        
        # Step I: Export Data
        res = session.get(f"{host}/api/user/export")
        assert res.status_code == 200, f"Export data failed: {res.text}"
        exported = res.json()
        assert exported["user"]["username"] == test_user, f"Export data mismatch: {exported}"
        print("  ✓ User data export verify: Success")
        
        # Step J: Delete Account
        res = session.delete(f"{host}/api/user/delete", json={
            "password": "new_qa_password"
        })
        assert res.status_code == 200, f"Delete account failed: {res.text}"
        print("  ✓ Account deletion verify: Success")
        
        # Step K: Verify status is anonymous again
        res = session.get(f"{host}/api/auth/status")
        auth_status = res.json()
        assert auth_status["status"] == "anonymous", f"Expected anonymous after deletion, got {auth_status}"
        print("  ✓ Account cleanup verify: Success")
        
        print("\nAll UX Acceptance flow tests passed cleanly!")
        
    except Exception as e:
        errors.append(f"UX/Acceptance validation failed: {e}")

# Conclusion
print("\n=========================================================")
if errors:
    print(f"AUDIT FAILED with {len(errors)} error(s):")
    for err in errors:
        print(f"  [Error] {err}")
    sys.exit(1)
else:
    print("AUDIT SUCCESSFUL! 0 issues identified.")
    sys.exit(0)
