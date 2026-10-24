"""
test_auth.py  --  Step 3a tests. Runs against a THROWAWAY database (never your
real sessions.db) using FastAPI's TestClient, so it makes real HTTP-style
requests through the real routes and guards.

Run from backend/module4:   python test_auth.py
Needs:  pip install -r requirements.txt   (httpx is required by TestClient)

Most tests try to do something FORBIDDEN and expect the system to refuse.
"""

import os
import sqlite3
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone

_fd, TMP_DB = tempfile.mkstemp(suffix=".db")
os.close(_fd)
os.environ["SESSION_DB_PATH"] = TMP_DB      # must be set BEFORE importing session_store
os.environ["COOKIE_SECURE"] = "false"       # the test client speaks plain http

import session_store  # noqa: E402,F401  (creates the base tables in the temp db)
from accounts_schema import init_accounts_schema  # noqa: E402

init_accounts_schema(TMP_DB, backup=False)

from fastapi import Depends, FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import auth_api  # noqa: E402
import auth_core as core  # noqa: E402

app = FastAPI()
app.include_router(auth_api.router)


# Stand-in routes protected the same way real Module 4 routes will be in step 3b.
@app.get("/t/any-user")
def t_any(user=Depends(auth_api.current_user)):
    return {"role": user["role"]}


@app.get("/t/doctor-read")
def t_doctor_read(user=Depends(auth_api.require_verified_doctor)):
    return {"ok": True}


@app.post("/t/doctor-edit")
def t_doctor_edit(user=Depends(auth_api.require_verified_doctor)):
    return {"ok": True}


@app.post("/t/patient-write")
def t_patient_write(user=Depends(auth_api.require_role("patient"))):
    return {"ok": True}


@app.post("/t/admin-only")
def t_admin_only(user=Depends(auth_api.require_admin)):
    return {"ok": True}


PW = "correct-horse-battery"
passed = failed = 0


def check(label, condition):
    global passed, failed
    print(f"  [{'PASS' if condition else 'FAIL'}] {label}")
    if condition:
        passed += 1
    else:
        failed += 1


def db():
    conn = sqlite3.connect(TMP_DB)
    conn.row_factory = sqlite3.Row
    return conn


def sql(query, params=()):
    conn = db()
    try:
        cur = conn.execute(query, params)
        conn.commit()
        return cur.fetchall()
    finally:
        conn.close()


def dump_all_text() -> str:
    conn = db()
    try:
        out = []
        for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall():
            for row in conn.execute(f'SELECT * FROM "{name}"').fetchall():
                out.append(" | ".join(str(v) for v in tuple(row)))
        return "\n".join(out)
    finally:
        conn.close()


def fresh_limiters():
    auth_api.login_limiter = core.RateLimiter(10_000, 600)
    auth_api.register_limiter = core.RateLimiter(10_000, 3600)


def reg_patient(client, email, password=PW, **extra):
    return client.post("/auth/register/patient", json={"email": email, "password": password, **extra})


def reg_doctor(client, email, pmdc, password=PW):
    return client.post("/auth/register/doctor", json={
        "email": email, "password": password, "full_name": "Dr Test Person",
        "father_name": "Test Father", "pmdc_number": pmdc})


def csrf_of(client):
    return client.get("/auth/me").json()["csrf_token"]


def post(client, path, token="MISSING"):
    headers = {} if token == "MISSING" else {"X-CSRF-Token": token}
    return client.post(path, headers=headers)


def approve_doctor(user_id, admin_id, upto):
    sql("UPDATE doctor_profiles SET verification_status = 'verified', verified_at = ?, verified_by = ?, "
        "license_valid_upto = ? WHERE user_id = ?", (core._iso(core.utcnow()), admin_id, upto, user_id))
    sql("UPDATE users SET status = 'verified' WHERE user_id = ?", (user_id,))


def future(days=365):
    return (core.utcnow().date() + timedelta(days=days)).isoformat()


def past(days=1):
    return (core.utcnow().date() - timedelta(days=days)).isoformat()


def run() -> bool:
    fresh_limiters()

    print("\n[TEST 1] Registration, login and the session cookie")
    c = TestClient(app)
    r = reg_patient(c, "  Pat@Example.COM ", full_name="Pat One")
    check("patient registers (201)", r.status_code == 201)
    check("account is an active patient", r.json()["user"]["role"] == "patient" and r.json()["user"]["status"] == "active")
    cookie_header = r.headers.get("set-cookie", "").lower()
    check("cookie is HttpOnly", "httponly" in cookie_header)
    check("cookie is SameSite=Lax", "samesite=lax" in cookie_header)
    check("response never contains the password hash", "argon2" not in r.text and "password" not in r.text.lower())
    me = c.get("/auth/me")
    check("GET /auth/me works with the cookie", me.status_code == 200 and me.json()["user"]["email"] == "pat@example.com")
    check("CSRF token from /auth/me matches the one from registration", me.json()["csrf_token"] == r.json()["csrf_token"])
    c2 = TestClient(app)
    check("login with different letter case and spaces works",
          c2.post("/auth/login", json={"email": " PAT@example.com", "password": PW}).status_code == 200)

    print("\n[TEST 2] Secrets never sit in the database in readable form")
    token = c.cookies.get(core.COOKIE_NAME)
    dump = dump_all_text()
    check("raw session token is not stored anywhere", token and token not in dump)
    check("raw password is not stored anywhere", PW not in dump)
    check("only an argon2id hash is stored for the password", "$argon2id$" in dump)

    print("\n[TEST 3] Input rules")
    check("password shorter than 10 characters -> 422", reg_patient(TestClient(app), "short@example.com", "123456789").status_code == 422)
    long_email = "averyveryverylongemailaddress@example.com"
    check("password equal to the email -> 422", reg_patient(TestClient(app), long_email, long_email).status_code == 422)
    check("password longer than 128 characters -> 422", reg_patient(TestClient(app), "long@example.com", "x" * 129).status_code == 422)
    check("invalid email -> 422", reg_patient(TestClient(app), "not-an-email").status_code == 422)
    check("duplicate email (any letter case) -> 409", reg_patient(TestClient(app), "PAT@example.com").status_code == 409)
    before = sql("SELECT COUNT(*) AS n FROM users")[0]["n"]
    r = reg_patient(TestClient(app), "sneaky@example.com", role="admin")
    check("body containing 'role' is rejected (422)", r.status_code == 422)
    check("... and no account was created", sql("SELECT COUNT(*) AS n FROM users")[0]["n"] == before)

    print("\n[TEST 4] Login errors do not reveal anything")
    bad_pw = TestClient(app).post("/auth/login", json={"email": "pat@example.com", "password": "wrong-password-1"})
    bad_email = TestClient(app).post("/auth/login", json={"email": "nobody@example.com", "password": "wrong-password-1"})
    check("wrong password and unknown email give the same status", bad_pw.status_code == bad_email.status_code == 401)
    check("... and the same message", bad_pw.json() == bad_email.json())

    print("\n[TEST 5] Lockout after repeated wrong passwords")
    lc = TestClient(app)
    reg_patient(lc, "lock@example.com")
    for _ in range(core.MAX_FAILED_LOGINS):
        TestClient(app).post("/auth/login", json={"email": "lock@example.com", "password": "wrong-password-1"})
    locked = TestClient(app).post("/auth/login", json={"email": "lock@example.com", "password": PW})
    check("correct password is refused while locked", locked.status_code == 401)
    check("... with the same generic message", locked.json() == bad_email.json())
    check("lock time is recorded", sql("SELECT locked_until FROM users WHERE email = 'lock@example.com'")[0]["locked_until"] is not None)
    sql("UPDATE users SET locked_until = ? WHERE email = 'lock@example.com'", (core._iso(core.utcnow() - timedelta(minutes=1)),))
    TestClient(app).post("/auth/login", json={"email": "lock@example.com", "password": "wrong-password-1"})
    row = sql("SELECT failed_login_count, locked_until FROM users WHERE email = 'lock@example.com'")[0]
    check("after the lock expires the counter starts again from zero (1 miss, not re-locked)",
          row["failed_login_count"] == 1 and row["locked_until"] is None)
    ok = TestClient(app).post("/auth/login", json={"email": "lock@example.com", "password": PW})
    check("correct password works again and resets the counter",
          ok.status_code == 200 and sql("SELECT failed_login_count FROM users WHERE email = 'lock@example.com'")[0]["failed_login_count"] == 0)

    print("\n[TEST 6] Not logged in -> 401 everywhere")
    anon = TestClient(app)
    check("GET /auth/me", anon.get("/auth/me").status_code == 401)
    check("GET /t/any-user", anon.get("/t/any-user").status_code == 401)
    check("POST /t/patient-write", post(anon, "/t/patient-write", "x").status_code == 401)
    check("POST /t/doctor-edit", post(anon, "/t/doctor-edit", "x").status_code == 401)
    check("POST /t/admin-only", post(anon, "/t/admin-only", "x").status_code == 401)
    check("POST /auth/logout", post(anon, "/auth/logout", "x").status_code == 401)
    check("a made-up cookie is refused", anon.get("/t/any-user", headers={"Cookie": f"{core.COOKIE_NAME}=not-a-real-token"}).status_code == 401)

    print("\n[TEST 7] CSRF protection on state-changing routes")
    tok = csrf_of(c)
    check("POST without the CSRF header -> 403", post(c, "/t/patient-write").status_code == 403)
    check("POST with a wrong CSRF token -> 403", post(c, "/t/patient-write", "0" * 64).status_code == 403)
    check("POST with the right CSRF token -> 200", post(c, "/t/patient-write", tok).status_code == 200)
    check("GET needs no CSRF token", c.get("/t/any-user").status_code == 200)
    check("a CSRF token from another user's session is refused", post(c, "/t/patient-write", csrf_of(c2)).status_code == 403)

    print("\n[TEST 8] A patient cannot reach doctor or admin functions (acceptance criterion 1)")
    r = post(c, "/t/doctor-edit", tok)
    check("patient -> doctor edit route = 403", r.status_code == 403)
    check("patient -> doctor read route (GET) = 403", c.get("/t/doctor-read").status_code == 403)
    check("patient -> admin route = 403", post(c, "/t/admin-only", tok).status_code == 403)

    print("\n[TEST 9] Doctors: pending until approved (acceptance criterion 2)")
    dc = TestClient(app)
    r = reg_doctor(dc, "doc@example.com", " 12345-p ")
    check("doctor registers (201) as 'pending' with a DR- code",
          r.status_code == 201 and r.json()["user"]["status"] == "pending" and r.json()["user"]["display_id"].startswith("DR-"))
    doc_id = r.json()["user"]["user_id"]
    dtok = csrf_of(dc)
    check("pending doctor -> doctor edit = 403", post(dc, "/t/doctor-edit", dtok).status_code == 403)
    check("pending doctor -> doctor read (GET) = 403", dc.get("/t/doctor-read").status_code == 403)
    check("pending doctor can still see their own status", dc.get("/auth/me").json()["doctor"]["verification_status"] == "pending")
    check("/auth/me never exposes the PMDC number", "12345" not in dc.get("/auth/me").text)
    check("doctor -> patient-only route = 403", post(dc, "/t/patient-write", dtok).status_code == 403)
    r2 = reg_doctor(TestClient(app), "doc2@example.com", "12345-P")
    check("same PMDC number (different spacing/case) on another account -> 409", r2.status_code == 409)
    check("... and no orphan account was left behind", sql("SELECT COUNT(*) AS n FROM users WHERE email = 'doc2@example.com'")[0]["n"] == 0)

    print("\n[TEST 10] Admin approval opens the door; revocation closes it at once")
    ac = TestClient(app)
    conn = core.open_db()
    admin = core.create_admin_user(conn, "admin@example.com", PW, "Admin One")
    conn.close()
    check("admin account has an AD- code", admin["display_id"].startswith("AD-"))
    ac.post("/auth/login", json={"email": "admin@example.com", "password": PW})
    atok = csrf_of(ac)
    check("admin -> admin route = 200", post(ac, "/t/admin-only", atok).status_code == 200)
    check("doctor -> admin route = 403", post(dc, "/t/admin-only", dtok).status_code == 403)
    approve_doctor(doc_id, admin["user_id"], future())
    check("approved doctor -> doctor edit = 200 (same session, no re-login)", post(dc, "/t/doctor-edit", dtok).status_code == 200)
    check("approved doctor -> doctor read (GET) = 200", dc.get("/t/doctor-read").status_code == 200)
    sql("UPDATE users SET status = 'rejected' WHERE user_id = ?", (doc_id,))
    check("admin revokes approval -> doctor's very next request = 403", post(dc, "/t/doctor-edit", dtok).status_code == 403)
    approve_doctor(doc_id, admin["user_id"], future())

    print("\n[TEST 11] An expired PMDC licence closes the doctor door by itself")
    sql("UPDATE doctor_profiles SET license_valid_upto = ? WHERE user_id = ?", (past(), doc_id))
    r = post(dc, "/t/doctor-edit", dtok)
    check("licence expired yesterday -> 403", r.status_code == 403 and "licence_expired" in r.text)
    check("account dropped back to 'pending', profile marked 'expired'",
          sql("SELECT status FROM users WHERE user_id = ?", (doc_id,))[0]["status"] == "pending"
          and sql("SELECT verification_status FROM doctor_profiles WHERE user_id = ?", (doc_id,))[0]["verification_status"] == "expired")
    check("an audit row 'doctor_license_expired' was written",
          sql("SELECT COUNT(*) AS n FROM audit_log WHERE action = 'doctor_license_expired'")[0]["n"] == 1)
    approve_doctor(doc_id, admin["user_id"], future())
    check("after the admin re-approves with a new expiry date, access returns", post(dc, "/t/doctor-edit", dtok).status_code == 200)

    print("\n[TEST 12] Logout, expiry and idle timeout")
    lo = TestClient(app)
    reg_patient(lo, "logout@example.com")
    lo_token = lo.cookies.get(core.COOKIE_NAME)
    lo_csrf = csrf_of(lo)
    check("logout without CSRF header -> 403 (session still valid)", post(lo, "/auth/logout").status_code == 403)
    check("logout with CSRF header -> 200", post(lo, "/auth/logout", lo_csrf).status_code == 200)
    check("after logout /auth/me = 401", lo.get("/auth/me").status_code == 401)
    check("replaying the old cookie value is refused (server-side revocation)",
          TestClient(app).get("/auth/me", headers={"Cookie": f"{core.COOKIE_NAME}={lo_token}"}).status_code == 401)
    ex = TestClient(app)
    reg_patient(ex, "expiry@example.com")
    ex_token = ex.cookies.get(core.COOKIE_NAME)
    sql("UPDATE auth_sessions SET expires_at = ? WHERE token_hash = ?", (core._iso(core.utcnow() - timedelta(seconds=1)), core.hash_token(ex_token)))
    check("session past its absolute expiry -> 401", ex.get("/auth/me").status_code == 401)
    idle = TestClient(app)
    reg_patient(idle, "idle@example.com")
    idle_token = idle.cookies.get(core.COOKIE_NAME)
    sql("UPDATE auth_sessions SET last_seen_at = ? WHERE token_hash = ?",
        (core._iso(core.utcnow() - timedelta(minutes=core.SESSION_IDLE_MINUTES + 5)), core.hash_token(idle_token)))
    check("session idle for too long -> 401", idle.get("/auth/me").status_code == 401)

    print("\n[TEST 13] Disabled accounts")
    dis = TestClient(app)
    reg_patient(dis, "disabled@example.com")
    sql("UPDATE users SET status = 'disabled' WHERE email = 'disabled@example.com'")
    check("existing session of a disabled account -> 401", dis.get("/auth/me").status_code == 401)
    check("disabled account cannot log in",
          TestClient(app).post("/auth/login", json={"email": "disabled@example.com", "password": PW}).status_code == 401)

    print("\n[TEST 14] Rate limiting")
    auth_api.login_limiter = core.RateLimiter(3, 600)
    codes = [TestClient(app).post("/auth/login", json={"email": "x@example.com", "password": "wrong-password-1"}).status_code for _ in range(4)]
    check("3 attempts allowed, the 4th from the same address -> 429", codes == [401, 401, 401, 429])
    r = TestClient(app).post("/auth/login", json={"email": "x@example.com", "password": "wrong-password-1"})
    check("429 carries a Retry-After header", "retry-after" in {k.lower() for k in r.headers})
    auth_api.register_limiter = core.RateLimiter(2, 3600)
    codes = [reg_patient(TestClient(app), f"rl{i}@example.com").status_code for i in range(3)]
    check("registration is limited too (201, 201, 429)", codes == [201, 201, 429])
    fresh_limiters()

    print("\n[TEST 15] Audit log")
    actions = {r["action"] for r in sql("SELECT action FROM audit_log")}
    check("expected actions were recorded",
          {"register_patient", "register_doctor", "login_ok", "login_failed", "login_blocked", "create_admin"} <= actions)
    audit_text = "\n".join(" | ".join(str(v) for v in tuple(r)) for r in sql("SELECT * FROM audit_log"))
    check("no email addresses in the audit log", "@example.com" not in audit_text)
    check("no PMDC numbers in the audit log", "12345" not in audit_text)
    check("no passwords in the audit log", PW not in audit_text and "wrong-password" not in audit_text)
    conn = core.open_db()
    try:
        core.audit(conn, None, None, "x", after={"nested": {"password": "p"}})
        blocked = False
    except ValueError:
        blocked = True
    finally:
        conn.close()
    check("audit() itself refuses a payload containing a password key", blocked)

    return failed == 0


if __name__ == "__main__":
    try:
        ok = run()
    finally:
        try:
            os.remove(TMP_DB)
        except OSError:
            pass
    print("\n" + "=" * 60)
    print(f"{passed}/{passed + failed} auth tests passed.")
    print("=" * 60)
    sys.exit(0 if ok else 1)
