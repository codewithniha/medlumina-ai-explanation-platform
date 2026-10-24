"""
auth_core.py  --  Step 3a: the authentication engine (no web code in here).

ANALOGY
A hospital front desk. You show ID once (login). The desk checks it against the
register, then hands you a wristband (session). Every other room only looks at
the wristband. The desk keeps a stub of every wristband it issued, so it can cut
one off instantly (logout, licence expired, account disabled). The desk never
writes your password down, never keeps the wristband's secret number (only a
fingerprint of it), and logs every decision in a book nobody can erase.

WHAT IS IN HERE
  - password hashing (argon2id, via the maintained argon2-cffi library)
  - creating patient / doctor / admin accounts
  - login with lockout after repeated failures
  - server-side login sessions (only a SHA-256 fingerprint is stored)
  - CSRF token derivation
  - the doctor "gate": verified AND licence not expired (checked on every call)
  - an in-memory rate limiter
  - audit logging with a safety net that refuses secrets

DESIGN CHOICES (all deliberate)
  - Random opaque session tokens in the database, not JWTs: a JWT cannot be
    cancelled before it expires; a doctor whose licence lapses must lose access
    at once.
  - Same error for "unknown email" and "wrong password", and a dummy password
    check for unknown emails so response time does not give the answer away.
  - Locked accounts are not told they are locked (that would reveal the account
    exists); the per-IP rate limiter in auth_api.py is what returns HTTP 429.
  - The audit log never receives passwords, tokens, emails or PMDC numbers.

KNOWN LIMITS (say these honestly to Sir)
  - Email ownership is NOT verified (no mail server is set up), so anyone can
    register with any email address.
  - The rate limiter lives in process memory: fine for one uvicorn process,
    reset on restart.
  - argon2 parameters are the library defaults, not tuned for your hardware.
"""

import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import threading
import time
import uuid
from datetime import date, datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from dotenv import load_dotenv

# The database file is the same one session_store.py / accounts_schema.py use.
from accounts_schema import _resolve_db_path

load_dotenv()


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


SESSION_ABSOLUTE_HOURS = _env_int("AUTH_SESSION_HOURS", 12)    # hard stop after this long
SESSION_IDLE_MINUTES = _env_int("AUTH_IDLE_MINUTES", 120)      # logged out after this much inactivity
MAX_FAILED_LOGINS = _env_int("AUTH_MAX_FAILED_LOGINS", 5)
LOCKOUT_MINUTES = _env_int("AUTH_LOCKOUT_MINUTES", 15)
PASSWORD_MIN_LENGTH = 10
PASSWORD_MAX_LENGTH = 128
COOKIE_NAME = "ml_session"
# Set COOKIE_SECURE=true in .env once the site is served over HTTPS.
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").strip().lower() == "true"
COOKIE_SAMESITE = "lax"

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PMDC_RE = re.compile(r"^[A-Z0-9][A-Z0-9\-/]{2,31}$")


class EmailTaken(Exception):
    pass


class PmdcTaken(Exception):
    pass


# ── Time helpers ─────────────────────────────────────────────────────────────
def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _parse(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# ── Database ─────────────────────────────────────────────────────────────────
def open_db(db_path: str | None = None) -> sqlite3.Connection:
    """
    One connection per web request. check_same_thread=False because FastAPI may
    run a request's dependency and its endpoint on different worker threads;
    each connection is still used by one request at a time.
    """
    conn = sqlite3.connect(_resolve_db_path(db_path), check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# ── Audit log ────────────────────────────────────────────────────────────────
_FORBIDDEN_AUDIT_KEYS = {
    "password", "password_hash", "pmdc_number", "token", "token_hash",
    "certificate_path", "email",
}


def _scan_for_secrets(obj) -> None:
    if isinstance(obj, dict):
        for key, value in obj.items():
            if str(key).lower() in _FORBIDDEN_AUDIT_KEYS:
                raise ValueError(f"audit_log must never contain '{key}'")
            _scan_for_secrets(value)
    elif isinstance(obj, (list, tuple)):
        for item in obj:
            _scan_for_secrets(item)


def audit(
    conn: sqlite3.Connection,
    actor_user_id: str | None,
    actor_role: str | None,
    action: str,
    target_type: str | None = None,
    target_id: str | None = None,
    before: dict | None = None,
    after: dict | None = None,
) -> None:
    """Appends one row. Does NOT commit (the caller commits with its own change)."""
    _scan_for_secrets(before)
    _scan_for_secrets(after)
    conn.execute(
        "INSERT INTO audit_log (at, actor_user_id, actor_role, action, target_type, target_id, before_json, after_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            _iso(utcnow()), actor_user_id, actor_role, action, target_type, target_id,
            json.dumps(before) if before is not None else None,
            json.dumps(after) if after is not None else None,
        ),
    )


# ── Passwords ────────────────────────────────────────────────────────────────
_hasher = PasswordHasher()
# Used to burn the same time when the email is unknown or the account is locked.
_DUMMY_HASH = _hasher.hash("timing-equalizer-not-a-real-password")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(stored_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(stored_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def normalize_email(email: str) -> str:
    cleaned = (email or "").strip().lower()
    if len(cleaned) > 254 or not _EMAIL_RE.match(cleaned):
        raise ValueError("Please enter a valid email address.")
    return cleaned


def validate_password(password: str, email: str) -> None:
    if not isinstance(password, str) or len(password) < PASSWORD_MIN_LENGTH:
        raise ValueError(f"Password must be at least {PASSWORD_MIN_LENGTH} characters long.")
    if len(password) > PASSWORD_MAX_LENGTH:
        raise ValueError(f"Password must be at most {PASSWORD_MAX_LENGTH} characters long.")
    if password.strip().lower() == email:
        raise ValueError("Password must not be the same as your email address.")


# ── Accounts ─────────────────────────────────────────────────────────────────
def _public_user(row) -> dict:
    return {
        "user_id": row["user_id"],
        "role": row["role"],
        "display_id": row["display_id"],
        "email": row["email"],
        "full_name": row["full_name"],
        "status": row["status"],
    }


def _new_display_id(conn: sqlite3.Connection, prefix: str) -> str:
    while True:
        code = f"{prefix}-{secrets.token_hex(3).upper()}"
        if not conn.execute("SELECT 1 FROM users WHERE display_id = ?", (code,)).fetchone():
            return code


def _insert_user(conn, *, email, password, role, full_name, status, display_prefix) -> str:
    email_n = normalize_email(email)
    validate_password(password, email_n)
    user_id = str(uuid.uuid4())
    display_id = _new_display_id(conn, display_prefix) if display_prefix else None
    try:
        conn.execute(
            "INSERT INTO users (user_id, role, display_id, email, password_hash, full_name, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, role, display_id, email_n, hash_password(password), (full_name or "").strip()[:200],
             status, _iso(utcnow())),
        )
    except sqlite3.IntegrityError as e:
        if "users.email" in str(e):
            raise EmailTaken() from e
        raise
    return user_id


def _get_public_user(conn, user_id: str) -> dict:
    return _public_user(conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone())


def create_patient_user(conn, email: str, password: str, full_name: str = "") -> dict:
    try:
        user_id = _insert_user(conn, email=email, password=password, role="patient",
                               full_name=full_name, status="active", display_prefix=None)
        audit(conn, user_id, "patient", "register_patient", "user", user_id)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return _get_public_user(conn, user_id)


def create_doctor_user(conn, email: str, password: str, full_name: str,
                       father_name: str, pmdc_number: str) -> dict:
    """Creates the account AND its PMDC profile in one transaction; status 'pending'."""
    pmdc = re.sub(r"\s+", "", pmdc_number or "").upper()
    if not _PMDC_RE.match(pmdc):
        raise ValueError("Please enter your PMDC registration number (letters, digits, '-' or '/').")
    if not (full_name or "").strip():
        raise ValueError("Please enter your full name exactly as it appears on the PMDC register.")
    try:
        user_id = _insert_user(conn, email=email, password=password, role="doctor",
                               full_name=full_name, status="pending", display_prefix="DR")
        try:
            conn.execute(
                "INSERT INTO doctor_profiles (user_id, pmdc_number, register_full_name, register_father_name, "
                "verification_status, submitted_at) VALUES (?, ?, ?, ?, 'pending', ?)",
                (user_id, pmdc, full_name.strip()[:200], (father_name or "").strip()[:200], _iso(utcnow())),
            )
        except sqlite3.IntegrityError as e:
            if "pmdc_number" in str(e):
                raise PmdcTaken() from e
            raise
        # Deliberately no PMDC number in the audit row.
        audit(conn, user_id, "doctor", "register_doctor", "user", user_id, after={"status": "pending"})
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return _get_public_user(conn, user_id)


def create_admin_user(conn, email: str, password: str, full_name: str = "") -> dict:
    """Only called from create_admin.py on the server; there is no web route for this."""
    try:
        user_id = _insert_user(conn, email=email, password=password, role="admin",
                               full_name=full_name, status="active", display_prefix="AD")
        audit(conn, None, "system", "create_admin", "user", user_id)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return _get_public_user(conn, user_id)


# ── Login ────────────────────────────────────────────────────────────────────
def authenticate(conn, email: str, password: str) -> dict | None:
    """
    Returns the public user dict on success, otherwise None. The caller must
    answer every None identically (same message, same status code).
    """
    try:
        email_n = normalize_email(email)
    except ValueError:
        verify_password(_DUMMY_HASH, password or "")
        return None

    row = conn.execute("SELECT * FROM users WHERE email = ?", (email_n,)).fetchone()
    if row is None:
        verify_password(_DUMMY_HASH, password or "")
        audit(conn, None, None, "login_failed", after={"reason": "unknown_account"})
        conn.commit()
        return None

    uid, role = row["user_id"], row["role"]
    now = utcnow()
    failed = row["failed_login_count"]

    if row["locked_until"]:
        if now < _parse(row["locked_until"]):
            verify_password(_DUMMY_HASH, password or "")  # do not even check the real password
            audit(conn, uid, role, "login_blocked", "user", uid, after={"reason": "locked"})
            conn.commit()
            return None
        failed = 0  # lock has expired: start counting again from zero

    if row["status"] == "disabled":
        verify_password(_DUMMY_HASH, password or "")
        audit(conn, uid, role, "login_blocked", "user", uid, after={"reason": "disabled"})
        conn.commit()
        return None

    if not verify_password(row["password_hash"], password or ""):
        failed += 1
        locked_until = None
        if failed >= MAX_FAILED_LOGINS:
            locked_until = _iso(now + timedelta(minutes=LOCKOUT_MINUTES))
        conn.execute("UPDATE users SET failed_login_count = ?, locked_until = ? WHERE user_id = ?",
                     (failed, locked_until, uid))
        audit(conn, uid, role, "login_failed", "user", uid,
              after={"reason": "wrong_password", "failed_count": failed, "locked": bool(locked_until)})
        conn.commit()
        return None

    # Success.
    new_hash = None
    if _hasher.check_needs_rehash(row["password_hash"]):
        new_hash = hash_password(password)
    conn.execute(
        "UPDATE users SET failed_login_count = 0, locked_until = NULL, last_login_at = ?, "
        "password_hash = COALESCE(?, password_hash) WHERE user_id = ?",
        (_iso(now), new_hash, uid),
    )
    audit(conn, uid, role, "login_ok", "user", uid)
    conn.commit()
    return _get_public_user(conn, uid)


# ── Sessions ─────────────────────────────────────────────────────────────────
def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(conn, user_id: str) -> str:
    """Returns the RAW token (goes into the cookie). Only its fingerprint is stored."""
    token = secrets.token_urlsafe(32)
    now = utcnow()
    conn.execute(
        "INSERT INTO auth_sessions (token_hash, user_id, csrf_hash, created_at, expires_at, last_seen_at) "
        "VALUES (?, ?, NULL, ?, ?, ?)",
        (hash_token(token), user_id, _iso(now), _iso(now + timedelta(hours=SESSION_ABSOLUTE_HOURS)), _iso(now)),
    )
    conn.commit()
    return token


def get_session_user(conn, token: str | None) -> dict | None:
    if not token or len(token) > 200:
        return None
    row = conn.execute(
        "SELECT s.expires_at AS s_expires, s.last_seen_at AS s_seen, s.revoked_at AS s_revoked, "
        "u.user_id, u.role, u.display_id, u.email, u.full_name, u.status "
        "FROM auth_sessions s JOIN users u ON u.user_id = s.user_id WHERE s.token_hash = ?",
        (hash_token(token),),
    ).fetchone()
    if row is None or row["s_revoked"]:
        return None
    now = utcnow()
    if now >= _parse(row["s_expires"]):
        return None
    if row["s_seen"] and now - _parse(row["s_seen"]) > timedelta(minutes=SESSION_IDLE_MINUTES):
        return None
    if row["status"] == "disabled":
        return None
    if not row["s_seen"] or now - _parse(row["s_seen"]) > timedelta(seconds=60):
        conn.execute("UPDATE auth_sessions SET last_seen_at = ? WHERE token_hash = ?",
                     (_iso(now), hash_token(token)))
        conn.commit()
    return _public_user(row)


def revoke_session(conn, token: str) -> None:
    conn.execute("UPDATE auth_sessions SET revoked_at = ? WHERE token_hash = ? AND revoked_at IS NULL",
                 (_iso(utcnow()), hash_token(token)))
    conn.commit()


def revoke_all_sessions(conn, user_id: str) -> None:
    conn.execute("UPDATE auth_sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL",
                 (_iso(utcnow()), user_id))
    conn.commit()


# ── CSRF ─────────────────────────────────────────────────────────────────────
# The CSRF token is derived from the secret session token, so it needs no extra
# storage and survives a page reload (GET /auth/me returns it again). An attacker
# on another website cannot read the HttpOnly cookie, so cannot compute it.
def csrf_token_for(session_token: str) -> str:
    return hashlib.sha256(b"csrf|" + session_token.encode("utf-8")).hexdigest()


def csrf_ok(session_token: str, header_value: str | None) -> bool:
    if not header_value:
        return False
    return hmac.compare_digest(csrf_token_for(session_token), header_value)


# ── Doctor gate ──────────────────────────────────────────────────────────────
def doctor_gate(conn, user_id: str) -> tuple[bool, str]:
    """
    (True, 'ok') only for a verified doctor whose PMDC licence has not expired.
    Checked on EVERY doctor request, so approval is revoked the moment an admin
    changes the status, and an expired licence closes the door by itself.
    """
    row = conn.execute(
        "SELECT u.role, u.status, p.license_valid_upto FROM users u "
        "LEFT JOIN doctor_profiles p ON p.user_id = u.user_id WHERE u.user_id = ?",
        (user_id,),
    ).fetchone()
    if row is None or row["role"] != "doctor":
        return False, "not_a_doctor"
    if row["status"] != "verified":
        return False, row["status"]  # pending / rejected / disabled
    try:
        valid_upto = date.fromisoformat(row["license_valid_upto"])
    except (TypeError, ValueError):
        return False, "licence_date_invalid"  # fail closed
    if valid_upto < utcnow().date():
        conn.execute("UPDATE users SET status = 'pending' WHERE user_id = ?", (user_id,))
        conn.execute("UPDATE doctor_profiles SET verification_status = 'expired' WHERE user_id = ?", (user_id,))
        audit(conn, None, "system", "doctor_license_expired", "user", user_id,
              before={"status": "verified"}, after={"status": "pending"})
        conn.commit()
        return False, "licence_expired"
    return True, "ok"


# ── Rate limiter ─────────────────────────────────────────────────────────────
class RateLimiter:
    """Sliding-window counter in process memory. check() returns None if allowed,
    otherwise the number of seconds to wait."""

    def __init__(self, max_hits: int, window_seconds: int):
        self.max_hits = max_hits
        self.window = window_seconds
        self._hits: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str) -> int | None:
        now = time.monotonic()
        with self._lock:
            hits = [t for t in self._hits.get(key, []) if now - t < self.window]
            if len(hits) >= self.max_hits:
                self._hits[key] = hits
                return max(1, int(self.window - (now - hits[0])) + 1)
            hits.append(now)
            self._hits[key] = hits
            if len(self._hits) > 10_000:  # keep memory bounded
                self._hits = {k: v for k, v in self._hits.items() if v and now - v[-1] < self.window}
            return None
