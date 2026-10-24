"""
admin_ops.py  --  Step 3b: what an ADMIN can do to a doctor's account.

Used by two doors into the same room:
  admin_api.py       (web routes, for the future admin screen)
  approve_doctor.py  (command-line tool, for you on the server)

Both call the functions below, so the rules and the audit entries are identical.

THE PMDC CHECK IS DONE BY A HUMAN. PMDC offers no API, so the admin looks the
doctor up on the public register (pmdc.pk), compares name / father's name /
registration number / "valid up to", and only then calls approve_doctor().
Approval stores the licence expiry date; after that date the doctor's access
closes by itself (see auth_core.doctor_gate).
"""

from datetime import date, timedelta

import auth_core as core

MAX_LICENCE_YEARS = 10


class NotADoctor(Exception):
    pass


class BadLicenceDate(ValueError):
    pass


_SELECT = (
    "SELECT u.user_id, u.display_id, u.email, u.full_name, u.status, "
    "p.pmdc_number, p.register_full_name, p.register_father_name, "
    "p.verification_status, p.license_valid_upto, p.submitted_at, p.verified_at "
    "FROM users u JOIN doctor_profiles p ON p.user_id = u.user_id WHERE u.role = 'doctor'"
)


def list_doctors(conn, status: str | None = None) -> list[dict]:
    if status:
        rows = conn.execute(_SELECT + " AND u.status = ? ORDER BY p.submitted_at", (status,)).fetchall()
    else:
        rows = conn.execute(_SELECT + " ORDER BY p.submitted_at").fetchall()
    return [dict(r) for r in rows]


def _get_doctor(conn, doctor_user_id: str) -> dict:
    row = conn.execute(_SELECT + " AND u.user_id = ?", (doctor_user_id,)).fetchone()
    if row is None:
        raise NotADoctor()
    return dict(row)


def approve_doctor(conn, admin: dict, doctor_user_id: str, license_valid_upto: date) -> dict:
    """Marks the doctor verified until `license_valid_upto` (taken from the PMDC register)."""
    doctor = _get_doctor(conn, doctor_user_id)
    today = core.utcnow().date()
    if license_valid_upto <= today:
        raise BadLicenceDate("The licence 'valid up to' date must be in the future.")
    if license_valid_upto > today + timedelta(days=365 * MAX_LICENCE_YEARS):
        raise BadLicenceDate(f"The licence date is more than {MAX_LICENCE_YEARS} years away - please re-check the register.")
    now = core._iso(core.utcnow())
    try:
        conn.execute("UPDATE users SET status = 'verified' WHERE user_id = ?", (doctor_user_id,))
        conn.execute(
            "UPDATE doctor_profiles SET verification_status = 'verified', verified_at = ?, verified_by = ?, "
            "license_valid_upto = ? WHERE user_id = ?",
            (now, admin["user_id"], license_valid_upto.isoformat(), doctor_user_id),
        )
        core.audit(conn, admin["user_id"], admin["role"], "admin_approve_doctor", "user", doctor_user_id,
                   before={"status": doctor["status"]},
                   after={"status": "verified", "license_valid_upto": license_valid_upto.isoformat()})
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return _get_doctor(conn, doctor_user_id)


def reject_doctor(conn, admin: dict, doctor_user_id: str, reason: str = "") -> dict:
    """Rejects a pending doctor, or revokes a verified one. Takes effect on their very next request."""
    doctor = _get_doctor(conn, doctor_user_id)
    try:
        conn.execute("UPDATE users SET status = 'rejected' WHERE user_id = ?", (doctor_user_id,))
        conn.execute("UPDATE doctor_profiles SET verification_status = 'rejected' WHERE user_id = ?",
                     (doctor_user_id,))
        core.audit(conn, admin["user_id"], admin["role"], "admin_reject_doctor", "user", doctor_user_id,
                   before={"status": doctor["status"]},
                   after={"status": "rejected", "reason": (reason or "")[:300]})
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return _get_doctor(conn, doctor_user_id)
