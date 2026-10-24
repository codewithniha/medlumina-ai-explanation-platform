"""
auth_api.py  --  Step 3a: the web layer for authentication.

Provides:
  POST /auth/register/patient
  POST /auth/register/doctor      (account stays 'pending' until an admin approves)
  POST /auth/login
  POST /auth/logout
  GET  /auth/me

and the guard dependencies every other route will use (step 3b):
  current_user            -> any logged-in user, else 401
  require_role("patient") -> logged-in AND that role, else 401/403
  require_verified_doctor -> doctor whose PMDC approval is valid right now
  require_admin           -> admin only

Every guard that is used on a POST/PUT/PATCH/DELETE route also checks the CSRF
header (X-CSRF-Token), so a malicious website cannot make a logged-in browser
perform actions. GET /auth/me returns the CSRF token for the frontend to send.

HTTP status codes:  401 = not logged in,  403 = logged in but not allowed,
                    409 = already registered,  422 = invalid input,  429 = slow down.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

import auth_core as core

router = APIRouter(prefix="/auth", tags=["auth"])

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

# Per client address. Login: generous enough for a classroom sharing one network.
login_limiter = core.RateLimiter(max_hits=core._env_int("AUTH_LOGIN_MAX_PER_10MIN", 30), window_seconds=600)
register_limiter = core.RateLimiter(max_hits=core._env_int("AUTH_REGISTER_MAX_PER_HOUR", 10), window_seconds=3600)


def get_db():
    conn = core.open_db()
    try:
        yield conn
    finally:
        conn.close()


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _limit(limiter: core.RateLimiter, request: Request) -> None:
    retry_after = limiter.check(_client_ip(request))
    if retry_after is not None:
        raise HTTPException(status_code=429, detail="Too many attempts. Please wait and try again.",
                            headers={"Retry-After": str(retry_after)})


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=core.COOKIE_NAME,
        value=token,
        max_age=core.SESSION_ABSOLUTE_HOURS * 3600,
        httponly=True,                 # page scripts cannot read it
        secure=core.COOKIE_SECURE,     # HTTPS only once COOKIE_SECURE=true
        samesite=core.COOKIE_SAMESITE,
        path="/",
    )


# ── Request bodies (extra="forbid": a body containing "role" is rejected) ────
class RegisterPatientRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(max_length=1024)
    password: str = Field(max_length=1024)
    full_name: str = Field(default="", max_length=200)


class RegisterDoctorRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(max_length=1024)
    password: str = Field(max_length=1024)
    full_name: str = Field(max_length=200)            # exactly as on the PMDC register
    father_name: str = Field(default="", max_length=200)
    pmdc_number: str = Field(max_length=64)


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(max_length=1024)
    password: str = Field(max_length=1024)


# ── Guard dependencies ───────────────────────────────────────────────────────
def current_user(request: Request, db=Depends(get_db)) -> dict:
    token = request.cookies.get(core.COOKIE_NAME)
    user = core.get_session_user(db, token)
    if user is None:
        raise HTTPException(status_code=401, detail="Please log in.")
    user["_session_token"] = token  # internal; never returned to the client
    return user


def _enforce_csrf(request: Request, user: dict) -> None:
    if request.method in SAFE_METHODS:
        return
    if not core.csrf_ok(user["_session_token"], request.headers.get("X-CSRF-Token")):
        raise HTTPException(status_code=403, detail="CSRF check failed.")


def require_role(*roles: str):
    def dependency(request: Request, user: dict = Depends(current_user)) -> dict:
        _enforce_csrf(request, user)
        if user["role"] not in roles:
            raise HTTPException(status_code=403, detail="You do not have permission to do this.")
        return user
    return dependency


require_admin = require_role("admin")


def require_verified_doctor(request: Request, user: dict = Depends(current_user), db=Depends(get_db)) -> dict:
    _enforce_csrf(request, user)
    if user["role"] != "doctor":
        raise HTTPException(status_code=403, detail="You do not have permission to do this.")
    ok, reason = core.doctor_gate(db, user["user_id"])
    if not ok:
        raise HTTPException(status_code=403, detail=f"Doctor access is not active ({reason}).")
    return user


def _client_view(user: dict) -> dict:
    return {k: v for k, v in user.items() if not k.startswith("_")}


# ── Routes ───────────────────────────────────────────────────────────────────
@router.post("/register/patient", status_code=201)
def register_patient(body: RegisterPatientRequest, request: Request, response: Response, db=Depends(get_db)):
    _limit(register_limiter, request)
    try:
        user = core.create_patient_user(db, body.email, body.password, body.full_name)
    except core.EmailTaken:
        raise HTTPException(status_code=409, detail="An account with this email already exists.")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    token = core.create_session(db, user["user_id"])
    _set_session_cookie(response, token)
    return {"user": user, "csrf_token": core.csrf_token_for(token)}


@router.post("/register/doctor", status_code=201)
def register_doctor(body: RegisterDoctorRequest, request: Request, response: Response, db=Depends(get_db)):
    _limit(register_limiter, request)
    try:
        user = core.create_doctor_user(db, body.email, body.password, body.full_name,
                                       body.father_name, body.pmdc_number)
    except core.EmailTaken:
        raise HTTPException(status_code=409, detail="An account with this email already exists.")
    except core.PmdcTaken:
        raise HTTPException(status_code=409, detail="This PMDC number is already registered to another account.")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    token = core.create_session(db, user["user_id"])
    _set_session_cookie(response, token)
    return {"user": user, "csrf_token": core.csrf_token_for(token)}


@router.post("/login")
def login(body: LoginRequest, request: Request, response: Response, db=Depends(get_db)):
    _limit(login_limiter, request)
    user = core.authenticate(db, body.email, body.password)
    if user is None:
        # One message for: unknown email, wrong password, locked, disabled.
        raise HTTPException(status_code=401, detail="Incorrect email or password.")
    token = core.create_session(db, user["user_id"])
    _set_session_cookie(response, token)
    return {"user": user, "csrf_token": core.csrf_token_for(token)}


@router.get("/me")
def me(user: dict = Depends(current_user), db=Depends(get_db)):
    result = {"user": _client_view(user), "csrf_token": core.csrf_token_for(user["_session_token"])}
    if user["role"] == "doctor":
        profile = db.execute(
            "SELECT verification_status, license_valid_upto FROM doctor_profiles WHERE user_id = ?",
            (user["user_id"],),
        ).fetchone()
        # The PMDC number itself is never sent back.
        result["doctor"] = (
            {"verification_status": profile["verification_status"],
             "license_valid_upto": profile["license_valid_upto"]} if profile else None
        )
    return result


@router.post("/logout")
def logout(response: Response, user: dict = Depends(require_role("patient", "doctor", "admin")),
           db=Depends(get_db)):
    core.revoke_session(db, user["_session_token"])
    response.delete_cookie(core.COOKIE_NAME, path="/")
    return {"ok": True}
