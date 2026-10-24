"""
doctor_api.py  --  Step 5: routes only a PMDC-verified doctor may call.

  GET /doctor/visits/{session_id}   the review view of one of the doctor's own visits:
                                    final report, findings, images, and the version history

Every route here sits behind require_verified_doctor, which checks on EVERY request
that the account is a doctor, an admin approved it, and the PMDC licence date has not
passed. A patient gets 403, a pending/rejected/expired doctor gets 403, anyone not
logged in gets 401.

Doctors and patients are independent accounts: a doctor reviews the visits in the
records THEY own (the ones they uploaded). Anything else answers 404.

Step 6a adds the first edit route (findings); 6b lets the same route also carry the doctor's
circle edits (regions). Step 7: after a save, the visit's question-answering index is rebuilt from
the final version (rag_reindex.py) so the old report can no longer be retrieved.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError

import auth_core as core
import dicom_store
import rag_reindex
import redraw
import visit_store
from doctor_edit import EditError, FindingsEditIn, apply_findings_edit
from access_control import session_is_owned
from auth_api import get_db, require_verified_doctor

router = APIRouter(prefix="/doctor", tags=["doctor"])


def _review(db, session_id: str) -> dict:
    view = visit_store.get_visit_view(db, session_id)
    view["versions"] = visit_store.list_versions(db, session_id)
    view["dicom"] = dicom_store.public_meta(db, session_id)
    # Side of the square the circles are measured on (6b-2: the screen needs it to place circles).
    try:
        xray = visit_store.read_xray_bytes(db, session_id)
        view["canvas_px"] = redraw.canvas_side(xray) if xray else None
    except Exception:
        view["canvas_px"] = None
    return view


@router.get("/visits/{session_id}")
def doctor_visit(session_id: str, user: dict = Depends(require_verified_doctor), db=Depends(get_db)):
    if not visit_store.valid_session_id(session_id) or not session_is_owned(db, user, session_id):
        raise HTTPException(status_code=404, detail="Visit not found.")
    return _review(db, session_id)


@router.post("/visits/{session_id}/edit/findings")
def edit_findings(session_id: str, body: dict, user: dict = Depends(require_verified_doctor), db=Depends(get_db)):
    """Confirm / remove / add findings (+ optional note). Creates a NEW report version; the old one is kept."""
    if not visit_store.valid_session_id(session_id) or not session_is_owned(db, user, session_id):
        raise HTTPException(status_code=404, detail="Visit not found.")
    try:
        edit = FindingsEditIn.model_validate(body)
    except ValidationError:
        raise HTTPException(status_code=422, detail="The edit is not valid. Check every finding has a decision and the note is under 2000 characters.")
    try:
        apply_findings_edit(db, user, session_id, edit)
    except EditError as e:
        raise HTTPException(status_code=e.status, detail=e.detail)
    # Step 7: the question-answering index must hold only the version just saved. The edit is already
    # committed, so a failure here never undoes it; it is recorded and reported, and the next edit retries.
    view = _review(db, session_id)
    try:
        info = rag_reindex.reindex_final_version(db, session_id)
        view["index_ok"] = True
        core.audit(db, user["user_id"], user["role"], "rag_reindex", "session", session_id,
                   after={"version_no": info["version_no"], "chunks": info["chunks"], "removed_old": info["removed_old"]})
    except Exception as e:  # noqa: BLE001  (any failure must be reported, never hidden)
        view["index_ok"] = False
        core.audit(db, user["user_id"], user["role"], "rag_reindex_failed", "session", session_id,
                   after={"error": type(e).__name__})
    db.commit()
    return view
