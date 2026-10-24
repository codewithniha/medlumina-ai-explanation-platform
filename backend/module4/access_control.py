"""
access_control.py  --  Step 3b: who may use the patient/doctor features, and
which records and visits belong to whom.

  require_end_user : a logged-in PATIENT, or a DOCTOR whose PMDC approval is
                     valid right now (checked on every request). Everyone else
                     (not logged in -> 401; pending/rejected doctor, admin -> 403).
  owned_patient_id : record code -> internal id, ONLY if the caller owns it.
  session_is_owned : is this visit inside one of the caller's records?

Anything that is not yours looks exactly like something that does not exist
(404, same wording), so nobody can probe which codes or session ids are real.
"""

from fastapi import Depends, HTTPException, Request

import auth_core as core
from auth_api import _enforce_csrf, current_user, get_db


def require_end_user(request: Request, user: dict = Depends(current_user), db=Depends(get_db)) -> dict:
    _enforce_csrf(request, user)
    if user["role"] == "patient":
        return user
    if user["role"] == "doctor":
        ok, reason = core.doctor_gate(db, user["user_id"])
        if ok:
            return user
        raise HTTPException(status_code=403, detail=f"Doctor access is not active ({reason}).")
    raise HTTPException(status_code=403, detail="You do not have permission to do this.")


def owned_patient_id(db, user: dict, patient_code: str) -> str | None:
    code = (patient_code or "").strip().upper()
    if not code:
        return None
    row = db.execute(
        "SELECT patient_id FROM patients WHERE patient_code = ? AND owner_user_id = ?",
        (code, user["user_id"]),
    ).fetchone()
    return row["patient_id"] if row else None


def session_is_owned(db, user: dict, session_id: str) -> bool:
    row = db.execute(
        "SELECT 1 FROM sessions s JOIN patients p ON p.patient_id = s.patient_id "
        "WHERE s.session_id = ? AND p.owner_user_id = ?",
        (session_id, user["user_id"]),
    ).fetchone()
    return row is not None


def claim_new_record(db, user: dict, patient_id: str) -> None:
    """Stamps a freshly created record with its owner (only if it has none yet)."""
    db.execute("UPDATE patients SET owner_user_id = ? WHERE patient_id = ? AND owner_user_id IS NULL",
               (user["user_id"], patient_id))
    db.commit()
