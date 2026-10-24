"""
dicom_api.py  --  DICOM routes

  POST /dicom/convert                       DICOM in -> plain PNG out (+ a one-time `dicom_token`
                                            that lets the visit keep the original, encrypted)
  GET  /visits/{id}/dicom/original          the original DICOM file back (audited)
  GET  /visits/{id}/dicom/deidentified      a de-identified copy for sharing (audited)
  GET  /visits/{id}/dicom/render            the picture re-rendered with a chosen window/level

All need a signed-in patient or verified doctor (login cookie + CSRF on POST), and the visit
must be inside a record you own (anything else answers 404, same as "does not exist").
The patient's name/ID/birth date inside the file are never returned by convert/render, never
written to the database, never put in the audit log. They exist only inside the encrypted
original, which only its owner can download.
"""

import base64
import math

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response

import auth_core as core
import dicom_store
import visit_store
from access_control import require_end_user, session_is_owned
from auth_api import get_db
from dicom_convert import MAX_DICOM_BYTES, DicomError, convert_dicom
from dicom_deid import deidentify

router = APIRouter(tags=["dicom"])

convert_limiter = core.RateLimiter(max_hits=core._env_int("DICOM_CONVERT_MAX_PER_10MIN", 30), window_seconds=600)
SAFE_HEADERS = {"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"}


def _limit(user: dict) -> None:
    retry = convert_limiter.check(user["user_id"])
    if retry is not None:
        raise HTTPException(status_code=429, detail="Too many requests. Please wait and try again.",
                            headers={"Retry-After": str(retry)})


def _owned_or_404(db, user: dict, session_id: str) -> None:
    if not visit_store.valid_session_id(session_id) or not session_is_owned(db, user, session_id):
        raise HTTPException(status_code=404, detail="Visit not found.")


def _original_or_404(db, session_id: str) -> bytes:
    if not dicom_store.has_original(db, session_id):
        raise HTTPException(status_code=404, detail="No DICOM original is kept for this visit.")
    try:
        return dicom_store.read_original(db, session_id)
    except dicom_store.DicomStoreError:
        core.audit(db, None, None, "dicom_integrity_failure", "session", session_id)
        db.commit()
        raise HTTPException(status_code=500, detail="The stored DICOM file could not be verified. Please contact support.")


@router.post("/dicom/convert")
async def dicom_convert(
    request: Request,
    file: UploadFile = File(...),
    user: dict = Depends(require_end_user),
    db=Depends(get_db),
):
    _limit(user)
    data = await file.read(MAX_DICOM_BYTES + 1)
    if len(data) > MAX_DICOM_BYTES:
        raise HTTPException(status_code=413, detail=f"This file is over the {MAX_DICOM_BYTES // 1048576} MB limit.")
    if not data:
        raise HTTPException(status_code=422, detail="The file is empty.")

    try:
        png, info = convert_dicom(data)
    except DicomError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception:
        # Never leak a library traceback (or header contents inside it) to the browser.
        raise HTTPException(status_code=422, detail="This DICOM file could not be processed.")

    token = None
    try:
        token = dicom_store.stage_original(user["user_id"], data, info)
    except Exception:
        token = None   # the picture still works; the original just cannot be kept

    # Audit WITHOUT any header content: only the size and the technical modality.
    core.audit(db, user["user_id"], user["role"], "dicom_convert", "upload", None, None,
               {"bytes": len(data), "modality": info.get("modality"), "window": info.get("window"),
                "staged": token is not None})
    db.commit()

    return {"image_base64": base64.b64encode(png).decode("ascii"), "mime": "image/png",
            "info": info, "dicom_token": token}


@router.get("/visits/{session_id}/dicom/original")
def dicom_original(session_id: str, user: dict = Depends(require_end_user), db=Depends(get_db)):
    _owned_or_404(db, user, session_id)
    data = _original_or_404(db, session_id)
    core.audit(db, user["user_id"], user["role"], "dicom_original_download", "session", session_id)
    db.commit()
    return Response(data, media_type="application/dicom", headers={
        **SAFE_HEADERS, "Content-Disposition": f'attachment; filename="visit-{session_id[:8]}.dcm"'})


@router.get("/visits/{session_id}/dicom/deidentified")
def dicom_deidentified(session_id: str, user: dict = Depends(require_end_user), db=Depends(get_db)):
    _owned_or_404(db, user, session_id)
    data = _original_or_404(db, session_id)
    row = db.execute("SELECT p.patient_code FROM sessions s JOIN patients p ON p.patient_id = s.patient_id "
                     "WHERE s.session_id = ?", (session_id,)).fetchone()
    try:
        out = deidentify(data, session_id, row["patient_code"] if row else "UNKNOWN")
    except DicomError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception:
        raise HTTPException(status_code=422, detail="This DICOM file could not be de-identified.")
    core.audit(db, user["user_id"], user["role"], "dicom_deidentified_export", "session", session_id)
    db.commit()
    return Response(out, media_type="application/dicom", headers={
        **SAFE_HEADERS, "Content-Disposition": f'attachment; filename="visit-{session_id[:8]}-deidentified.dcm"'})


@router.get("/visits/{session_id}/dicom/render")
def dicom_render(
    session_id: str,
    center: float = Query(...),
    width: float = Query(..., ge=1),
    invert: bool | None = Query(default=None),
    user: dict = Depends(require_end_user),
    db=Depends(get_db),
):
    """Window/level, like a PACS viewer: same stored original, different brightness window."""
    _owned_or_404(db, user, session_id)
    _limit(user)
    if not (math.isfinite(center) and math.isfinite(width)) or abs(center) > 1e6 or width > 1e6:
        raise HTTPException(status_code=422, detail="That window is not valid.")
    data = _original_or_404(db, session_id)
    try:
        png, _ = convert_dicom(data, override_window=(center, width), invert=invert)
    except DicomError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception:
        raise HTTPException(status_code=422, detail="This DICOM file could not be rendered.")
    return Response(png, media_type="image/png", headers={**SAFE_HEADERS, "Content-Disposition": "inline"})
