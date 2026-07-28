"""
module4_api.py

Minimal FastAPI layer for Module 4, mirroring the style of your Module 6
module6_api.py. Two endpoints:

  POST /session/start   -> creates a new patient session, indexes their
                            report/findings/medicines, returns a session_id
  POST /session/ask      -> asks a question within an existing session,
                            returns the classification + answer

Run with: uvicorn module4_api:app --reload --port 8001
(port 8001 so it doesn't collide with Module 6's API if both run locally)
"""

from fastapi import FastAPI, HTTPException, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from contextlib import asynccontextmanager
import requests

from llm_client import MEDGEMMA_API_URL
from ocr import transcribe_handwritten_report, transcribe_report_from_pdf

from kb_indexer import ensure_kb_indexed
from session_store import (
    create_session,
    session_exists,
    set_explanation_level,
    VALID_EXPLANATION_LEVELS,
    create_patient,
    get_patient_by_code,
    get_patient_sessions,
    get_recent_turns,
)
from session_indexer import index_session_data
from module4_pipeline import answer_question

MAX_REPORT_FILE_BYTES = 20 * 1024 * 1024  # 20MB -- matches lib/api-client.ts


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_kb_indexed()
    yield


app = FastAPI(title="MedLumina Module 4 - QA RAG", lifespan=lifespan)

# ── CORS: lets the Next.js frontend actually call this API from a browser ──
# Without this, the browser blocks every request with a CORS error before it
# even reaches your endpoints -- this is NOT a bug in your Python code, it's
# a browser security rule that has to be explicitly opted into on the server
# side. Two origins are allowed: your frontend running locally (what you
# should use for tomorrow's demo -- see chat notes on why) and the deployed
# Vercel URL (for whenever the backend is properly hosted somewhere reachable
# from the internet, not yet true for your laptop + ngrok setup).
ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "https://medlumina-ai-explanation-platform-chi.vercel.app",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class StartSessionRequest(BaseModel):
    doctor_report: str = ""
    xray_findings: dict = {}
    prescribed_medicines: list[str] = []
    symptoms: str = ""
    explanation_level: str = "simple"   # "simple" (default) or "detailed" -- FE-4
    patient_code: str = ""              # optional -- if given, links to that EXISTING patient (from /patient/lookup). Leave blank to create a brand-new patient with a fresh system-generated code.
    patient_name: str = ""              # optional -- only used the FIRST time a new patient is created


class StartSessionResponse(BaseModel):
    session_id: str
    chunks_indexed: int
    explanation_level: str
    patient_id: str | None = None
    patient_code: str | None = None     # ALWAYS show this to the user if present -- it's the only way they can look up this visit again later


class PatientLookupRequest(BaseModel):
    patient_code: str


class PatientSessionSummary(BaseModel):
    session_id: str
    created_at: str
    explanation_level: str


class PatientLookupResponse(BaseModel):
    patient_id: str
    sessions: list[PatientSessionSummary]


class AskRequest(BaseModel):
    session_id: str
    question: str


class ExplanationLevelRequest(BaseModel):
    session_id: str
    explanation_level: str   # "simple" or "detailed"


class AskResponse(BaseModel):
    classification: str | None
    answer: str
    retrieved_session_chunks: list[str] = []
    retrieved_kb_chunks: list[str] = []
    confidence: float | None = None
    # True when this was a SESSION_GROUNDED answer but the session simply
    # doesn't have enough indexed data yet (0 or 1 chunks -- e.g. only one
    # medicine entered, no symptoms/report/findings) for a real relative
    # confidence comparison. Lets the frontend show an honest explanation
    # instead of a confidence badge silently going missing -- see
    # retriever.py's _hybrid_search docstring for the full reasoning.
    insufficient_session_data: bool = False


class SessionHistoryRequest(BaseModel):
    session_id: str


class TurnOut(BaseModel):
    question: str
    classification: str | None
    answer: str
    confidence: float | None = None


class SessionHistoryResponse(BaseModel):
    turns: list[TurnOut]


class TranscribeReportResponse(BaseModel):
    extracted_text: str
    found_text: bool  # False if the image had no readable handwritten text at all


@app.post("/report/transcribe", response_model=TranscribeReportResponse)
async def transcribe_report(image: UploadFile = File(...)):
    """
    Accepts a doctor's report -- either a photo (handwritten or printed)
    or a PDF (typed/printed reports commonly come this way from real
    hospitals) -- and returns the transcribed text. Does NOT create a
    session or index anything itself -- the frontend gets the text back,
    shows it to the patient/doctor for review (extraction is never
    perfect, especially on messy handwriting), and only sends it on to
    /session/start once they've confirmed it's accurate. Uses Gemini's
    vision API (cloud) for the image/scanned-page path, not MedGemma --
    doesn't depend on the Colab tunnel being up at all.
    """
    is_image = bool(image.content_type) and image.content_type.startswith("image/")
    is_pdf = image.content_type == "application/pdf"

    if not is_image and not is_pdf:
        raise HTTPException(
            status_code=400,
            detail="Uploaded file must be an image (JPG/PNG/etc.) or a PDF.",
        )

    file_bytes = await image.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    # The frontend already blocks files over this size before they're even
    # uploaded (see MAX_REPORT_FILE_BYTES in lib/api-client.ts), but that
    # check can be bypassed by anyone calling this endpoint directly --
    # this is the real enforcement point. Also protects the OCR pipeline
    # itself: a huge scanned PDF means proportionally more Gemini calls
    # (see ocr.py's rate-limit handling), so keeping the input bounded
    # here keeps that bounded too.
    if len(file_bytes) > MAX_REPORT_FILE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File is {len(file_bytes) / (1024 * 1024):.1f}MB, which is over the {MAX_REPORT_FILE_BYTES // (1024 * 1024)}MB limit.",
        )

    try:
        if is_pdf:
            extracted_text = transcribe_report_from_pdf(file_bytes)
        else:
            extracted_text = transcribe_handwritten_report(file_bytes, image.content_type)
    except ConnectionError as e:
        raise HTTPException(status_code=503, detail=str(e))

    return TranscribeReportResponse(
        extracted_text=extracted_text,
        found_text=bool(extracted_text),
    )


@app.post("/session/start", response_model=StartSessionResponse)
def start_session(req: StartSessionRequest):
    # Originally required doctor_report or xray_findings -- but
    # "Prescription / Medicines Only" has always been a real, offered mode
    # in the UI (medicines + optional symptoms, no report or X-ray at
    # all), and this check was silently rejecting that entire mode.
    # Confirmed live: a real medicine + real symptoms got a 400 here with
    # no legitimate way to start a session at all. Any ONE of the three
    # real inputs is enough -- there just needs to be SOMETHING to index
    # and ground answers in.
    if not req.doctor_report and not req.xray_findings and not req.prescribed_medicines and not req.symptoms:
        raise HTTPException(
            status_code=400,
            detail="Provide at least a doctor_report, xray_findings, prescribed_medicines, or symptoms to start a session.",
        )
    if req.explanation_level not in VALID_EXPLANATION_LEVELS:
        raise HTTPException(
            status_code=400,
            detail=f"explanation_level must be one of {VALID_EXPLANATION_LEVELS}, got '{req.explanation_level}'.",
        )
    # ID system redesign (supervisor feedback): no more phone numbers.
    # - patient_code given -> must be an EXISTING patient (from
    #   /patient/lookup); a wrong/mistyped code is a real error here, not
    #   silently treated as a new patient -- that would be confusing (the
    #   user thinks they're resuming their history, but silently isn't).
    # - patient_code blank -> every new session gets its own real,
    #   system-generated identity automatically. No typing required from
    #   the user; the code is generated here and returned below so the
    #   frontend can show it to them to save for next time.
    if req.patient_code.strip():
        patient_id = get_patient_by_code(req.patient_code)
        if patient_id is None:
            raise HTTPException(
                status_code=404,
                detail=f"No patient found with code '{req.patient_code}'.",
            )
        patient_code = req.patient_code.strip().upper()
    else:
        patient_id, patient_code = create_patient(name=req.patient_name)

    session_id = create_session(explanation_level=req.explanation_level, patient_id=patient_id)
    n_chunks = index_session_data(
        session_id=session_id,
        doctor_report=req.doctor_report,
        xray_findings=req.xray_findings,
        prescribed_medicines=req.prescribed_medicines,
        symptoms=req.symptoms,
    )
    return StartSessionResponse(
        session_id=session_id,
        chunks_indexed=n_chunks,
        explanation_level=req.explanation_level,
        patient_id=patient_id,
        patient_code=patient_code,
    )


@app.post("/patient/lookup", response_model=PatientLookupResponse)
def lookup_patient(req: PatientLookupRequest):
    """
    Called BEFORE /session/start, when a returning patient/doctor types
    their patient_code into the app. Lets the frontend show "Welcome
    back! You have 3 previous visits" and offer to continue an old session
    (just call /session/ask with that old session_id -- no re-upload
    needed) or start a fresh one under the same identity (call
    /session/start with the same patient_code).

    An unknown code is a real 404 here -- deliberately does NOT silently
    create a new patient under a typo (unlike the old phone-based version).
    """
    patient_id = get_patient_by_code(req.patient_code)
    if patient_id is None:
        raise HTTPException(
            status_code=404,
            detail=f"No patient found with code '{req.patient_code}'.",
        )
    sessions = get_patient_sessions(patient_id)
    return PatientLookupResponse(
        patient_id=patient_id,
        sessions=[PatientSessionSummary(**s) for s in sessions],
    )


@app.post("/session/explanation_level")
def update_explanation_level(req: ExplanationLevelRequest):
    """
    Lets a patient switch between "simple" and "detailed" mid-conversation
    without starting a new session -- e.g. they start on "simple" and later
    ask for more depth. Not part of the original FE-4 decision (which only
    covered setting it at session start) but a natural, low-cost extension
    of the same field; drop this endpoint if you'd rather keep FE-4 to
    exactly what was scoped.
    """
    if not session_exists(req.session_id):
        raise HTTPException(status_code=404, detail="Session not found. Call /session/start first.")
    if req.explanation_level not in VALID_EXPLANATION_LEVELS:
        raise HTTPException(
            status_code=400,
            detail=f"explanation_level must be one of {VALID_EXPLANATION_LEVELS}, got '{req.explanation_level}'.",
        )
    set_explanation_level(req.session_id, req.explanation_level)
    return {"session_id": req.session_id, "explanation_level": req.explanation_level}


@app.post("/session/ask", response_model=AskResponse)
def ask(req: AskRequest):
    if not session_exists(req.session_id):
        raise HTTPException(status_code=404, detail="Session not found. Call /session/start first.")
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty.")

    result = answer_question(req.session_id, req.question)
    return AskResponse(
        classification=result["classification"],
        answer=result["answer"],
        retrieved_session_chunks=result.get("retrieved_session_chunks", []),
        retrieved_kb_chunks=result.get("retrieved_kb_chunks", []),
        confidence=result.get("confidence"),
        insufficient_session_data=result.get("insufficient_session_data", False),
    )


@app.post("/session/history", response_model=SessionHistoryResponse)
def session_history(req: SessionHistoryRequest):
    """
    Returns every real Q&A turn logged for this session (log_turn() has
    always saved every turn to SQLite -- this endpoint just exposes that
    data, nothing new is being computed here). Used by the frontend to
    restore the chat when the patient navigates away and back, or reopens
    the app later on the same session.
    """
    if not session_exists(req.session_id):
        raise HTTPException(status_code=404, detail="Session not found.")
    turns = get_recent_turns(req.session_id, limit=200)
    return SessionHistoryResponse(turns=[TurnOut(**t) for t in turns])


@app.get("/health")
def health():
    """
    Real check, not a hardcoded value -- confirmed live that the frontend's
    "Online" indicator was misleading because this endpoint used to only
    confirm the FastAPI server itself was running, saying nothing about
    whether MedGemma (the actual thing that matters) was reachable. A
    patient could see "Online" while every question failed.

    Short timeout (3s) deliberately -- this endpoint needs to answer fast
    since the frontend may poll it, and a long hang here would make the
    status indicator itself feel broken while waiting to find out MedGemma
    is down.
    """
    medgemma_reachable = False
    if MEDGEMMA_API_URL:
        try:
            # Any real HTTP response (even a 404, since the Colab server
            # likely only implements POST /generate) proves the tunnel is
            # actually up -- a ConnectionError/Timeout is what proves it
            # isn't. Status code doesn't matter here, reachability does.
            requests.get(MEDGEMMA_API_URL, timeout=3)
            medgemma_reachable = True
        except requests.exceptions.RequestException:
            medgemma_reachable = False

    return {
        "status": "ok",
        "medgemma_configured": bool(MEDGEMMA_API_URL),
        "medgemma_reachable": medgemma_reachable,
    }
