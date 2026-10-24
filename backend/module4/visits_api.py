"""
visits_api.py  --  Step 4a: save and read back a visit's analysis (server side).

  POST /visits/{session_id}/analysis      save the AI report + images (once per visit)
  GET  /visits/{session_id}               the final report version + which images exist
  GET  /visits/{session_id}/files/{kind}  an image: xray | annotated | comparison
  GET  /records/{patient_code}/visits     the visits inside one of YOUR records

All of these need a logged-in patient or verified doctor, and the visit must be
inside a record you own (anything else answers 404, same as "does not exist").
There is deliberately NO route here that changes a saved report: the patient
dashboard is read-only because the server offers no way to edit, not because
the buttons are hidden. Doctor editing arrives in step 6 as separate routes
behind the verified-doctor guard.
"""

import json
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

import auth_core as core
import dicom_store
import visit_store
from access_control import owned_patient_id, require_end_user, session_is_owned
from auth_api import get_db

router = APIRouter(tags=["visits"])

MAX_ANALYSIS_JSON_CHARS = 500_000   # the form-field parser itself stops at 1 MB


# ── What the browser may send (anything not listed here is dropped) ──────────
class RegionIn(BaseModel):
    """One circled region, in pixels of the model's square-padded X-ray (see redraw.py)."""
    model_config = ConfigDict(extra="ignore")
    center_xy: list[int] = Field(min_length=2, max_length=2)
    radius_px: int = Field(ge=1, le=20000)
    bbox_xyxy: list[int] | None = Field(default=None, min_length=4, max_length=4)
    peak_activation: float | None = Field(default=None, ge=0, le=1)
    area_px: int | None = Field(default=None, ge=0, le=400_000_000)

    @field_validator("center_xy", "bbox_xyxy")
    @classmethod
    def _in_range(cls, v):
        if v is not None and any(not (0 <= x <= 20000) for x in v):
            raise ValueError("coordinate out of range")
        return v


class FindingIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    regions: list[RegionIn] | None = Field(default=None, max_length=20)   # None = the AI sent no coordinates
    canvas_px: int | None = Field(default=None, ge=1, le=20000)
    positive_prob: float | None = Field(default=None, ge=0, le=1)
    probability: float | None = Field(default=None, ge=0, le=1)
    method: str | None = Field(default=None, max_length=64)
    ctr: float | None = Field(default=None, ge=0, le=5)
    source_sentence: str | None = Field(default=None, max_length=2000)
    region_count: int | None = Field(default=None, ge=0, le=100)
    localized: bool | None = None


class QualifiedIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    disease: str = Field(max_length=64)
    probability: float = Field(ge=0, le=1)


class AnalysisIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    mode: Literal["image_only", "image_and_report"]
    diseases_visualized: list[str] = Field(default_factory=list, max_length=50)
    diseases_qualified_not_shown: list[QualifiedIn] = Field(default_factory=list, max_length=50)
    findings: dict[str, FindingIn] = Field(default_factory=dict)
    report_text: str = Field(max_length=20000)
    note: str | None = Field(default=None, max_length=2000)

    @field_validator("diseases_visualized")
    @classmethod
    def _short_names(cls, v):
        if any(len(x) > 64 for x in v):
            raise ValueError("disease name too long")
        return v

    @field_validator("findings")
    @classmethod
    def _few_findings(cls, v):
        if len(v) > 50 or any(len(k) > 64 for k in v):
            raise ValueError("too many findings or name too long")
        return v


def _owned_visit_or_404(db, user, session_id: str) -> None:
    if not visit_store.valid_session_id(session_id) or not session_is_owned(db, user, session_id):
        raise HTTPException(status_code=404, detail="Visit not found.")


async def _read_capped(upload: UploadFile, label: str) -> bytes:
    data = await upload.read(visit_store.MAX_IMAGE_BYTES + 1)
    if len(data) > visit_store.MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail=f"The {label} image is over the 20MB limit.")
    if not data:
        raise HTTPException(status_code=400, detail=f"The {label} image is empty.")
    return data


@router.post("/visits/{session_id}/analysis", status_code=201)
async def save_analysis(
    session_id: str,
    analysis_json: str = Form(...),
    xray: UploadFile = File(...),
    annotated: UploadFile | None = File(default=None),
    comparison: UploadFile | None = File(default=None),
    dicom_token: str | None = Form(default=None),
    user: dict = Depends(require_end_user),
    db=Depends(get_db),
):
    _owned_visit_or_404(db, user, session_id)
    if len(analysis_json) > MAX_ANALYSIS_JSON_CHARS:
        raise HTTPException(status_code=413, detail="Analysis data is too large.")
    try:
        analysis = AnalysisIn.model_validate(json.loads(analysis_json))
    except (ValueError, ValidationError):
        raise HTTPException(status_code=422, detail="analysis_json is not a valid analysis result.")

    images = {"xray": await _read_capped(xray, "X-ray")}
    if annotated is not None:
        images["annotated"] = await _read_capped(annotated, "annotated")
    if comparison is not None:
        images["comparison"] = await _read_capped(comparison, "comparison")

    structured = analysis.model_dump(exclude={"report_text"})
    try:
        version_no = visit_store.save_ai_analysis(db, user, session_id, structured, analysis.report_text, images)
    except visit_store.BadImage as e:
        raise HTTPException(status_code=400, detail=str(e))
    except visit_store.AlreadySaved:
        raise HTTPException(status_code=409, detail="This visit already has a saved analysis.")
    result = {"session_id": session_id, "version_no": version_no, "dicom_retained": None, "dicom_message": None}
    if dicom_token:
        # The visit is already saved. Keeping the original DICOM is a second step; if it fails the
        # visit stays saved and we say so plainly instead of pretending everything worked.
        try:
            data, info = dicom_store.take_staged(user["user_id"], dicom_token)
            dicom_store.persist_original(db, user, session_id, data, info)
            dicom_store.discard_staged(user["user_id"], dicom_token)
            result["dicom_retained"] = True
        except dicom_store.DicomStoreError as e:
            result["dicom_retained"], result["dicom_message"] = False, str(e)
        except Exception:
            result["dicom_retained"], result["dicom_message"] = False, "The original DICOM file could not be kept."
    return result


@router.get("/visits/{session_id}")
def get_visit(session_id: str, user: dict = Depends(require_end_user), db=Depends(get_db)):
    _owned_visit_or_404(db, user, session_id)
    view = visit_store.get_visit_view(db, session_id)
    view["dicom"] = dicom_store.public_meta(db, session_id)
    return view


@router.get("/visits/{session_id}/files/{kind}")
def get_visit_file(session_id: str, kind: str, user: dict = Depends(require_end_user), db=Depends(get_db)):
    _owned_visit_or_404(db, user, session_id)
    found = visit_store.find_file(db, session_id, kind)
    if found is None:
        raise HTTPException(status_code=404, detail="Image not found.")
    path, mime = found
    return FileResponse(path, media_type=mime, headers={
        "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
        "Content-Disposition": "inline",
    })


@router.get("/records/{patient_code}/visits")
def list_visits(patient_code: str, user: dict = Depends(require_end_user), db=Depends(get_db)):
    patient_id = owned_patient_id(db, user, patient_code)
    if patient_id is None:
        raise HTTPException(status_code=404, detail="Record not found.")
    rows = db.execute(
        "SELECT s.session_id, s.created_at, v.version_no, v.structured_findings "
        "FROM sessions s LEFT JOIN report_versions v ON v.session_id = s.session_id AND v.is_final = 1 "
        "WHERE s.patient_id = ? ORDER BY s.created_at DESC",
        (patient_id,),
    ).fetchall()
    visits = []
    for r in rows:
        structured = json.loads(r["structured_findings"]) if r["structured_findings"] else {}
        visits.append({
            "session_id": r["session_id"], "created_at": r["created_at"],
            "has_report": r["version_no"] is not None, "version_no": r["version_no"],
            "has_dicom": dicom_store.has_original(db, r["session_id"]),
            "diseases_visualized": structured.get("diseases_visualized", []),
        })
    return {"patient_code": patient_code.strip().upper(), "visits": visits}
