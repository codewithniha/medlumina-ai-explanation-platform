"""
admin_api.py  --  Step 3b: web routes for admins to approve / reject doctors.

  GET  /admin/doctors?status=pending
  POST /admin/doctors/{user_id}/approve   {"license_valid_upto": "2028-12-31", "checked_on_pmdc_register": true}
  POST /admin/doctors/{user_id}/reject    {"reason": "..."}

Every route needs a logged-in ADMIN (401 if not logged in, 403 for anyone else)
and, for POSTs, the CSRF header. Admin accounts can only be created on the
server with create_admin.py - there is no way to become an admin from the web.
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

import admin_ops
from auth_api import get_db, require_admin

router = APIRouter(prefix="/admin", tags=["admin"])


class ApproveBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    license_valid_upto: date
    checked_on_pmdc_register: bool   # the admin must tick this: "I looked the doctor up on pmdc.pk"


class RejectBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(default="", max_length=300)


@router.get("/doctors")
def list_doctors(status: str | None = Query(default=None, pattern="^(pending|verified|rejected|disabled)$"),
                 admin: dict = Depends(require_admin), db=Depends(get_db)):
    return {"doctors": admin_ops.list_doctors(db, status)}


@router.post("/doctors/{user_id}/approve")
def approve(user_id: str, body: ApproveBody, admin: dict = Depends(require_admin), db=Depends(get_db)):
    if not body.checked_on_pmdc_register:
        raise HTTPException(status_code=422, detail="Look the doctor up on the PMDC register first, then confirm.")
    try:
        return {"doctor": admin_ops.approve_doctor(db, admin, user_id, body.license_valid_upto)}
    except admin_ops.NotADoctor:
        raise HTTPException(status_code=404, detail="Doctor not found.")
    except admin_ops.BadLicenceDate as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/doctors/{user_id}/reject")
def reject(user_id: str, body: RejectBody, admin: dict = Depends(require_admin), db=Depends(get_db)):
    try:
        return {"doctor": admin_ops.reject_doctor(db, admin, user_id, body.reason)}
    except admin_ops.NotADoctor:
        raise HTTPException(status_code=404, detail="Doctor not found.")
