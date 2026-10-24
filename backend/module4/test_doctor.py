"""
test_doctor.py  --  Step 5 tests: the verified-doctor-only routes (/doctor/...), through the REAL module4_api.py routes, on a THROWAWAY database
and a THROWAWAY image folder (never your real sessions.db or private_store/).

HONEST SCOPE: Gemini / MedGemma / Chroma / OCR / the answer pipeline are replaced
by fakes (same as test_access.py). What is real: the routes, login/CSRF/ownership
guards, input validation, SQLite, and the files written to disk.

Run from backend/module4:   python test_doctor.py
"""

import hashlib
import json
import os
import shutil
import sqlite3
import struct
import sys
import tempfile
import types
import zlib

_fd, TMP_DB = tempfile.mkstemp(suffix=".db")
os.close(_fd)
TMP_STORE = tempfile.mkdtemp(prefix="ml_store_")
os.environ["SESSION_DB_PATH"] = TMP_DB
os.environ["PRIVATE_STORE_DIR"] = TMP_STORE
os.environ["COOKIE_SECURE"] = "false"


def _fake(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod


_fake("llm_client", MEDGEMMA_API_URL="")
_fake("ocr", transcribe_handwritten_report=lambda *a, **k: "t", transcribe_report_from_pdf=lambda *a, **k: "t")
_fake("kb_indexer", ensure_kb_indexed=lambda: None)
_fake("session_indexer", index_session_data=lambda **kw: 1)
_fake("module4_pipeline", answer_question=lambda s, q: {"classification": "X", "answer": "a"})

from fastapi.testclient import TestClient  # noqa: E402

import admin_ops  # noqa: E402
import auth_api  # noqa: E402
import auth_core as core  # noqa: E402
import module4_api  # noqa: E402
import visit_store  # noqa: E402

app = module4_api.app
PW = "correct-horse-battery"
passed = failed = 0


def check(label, condition):
    global passed, failed
    print(f"  [{'PASS' if condition else 'FAIL'}] {label}")
    if condition:
        passed += 1
    else:
        failed += 1


def sql(query, params=()):
    conn = sqlite3.connect(TMP_DB)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(query, params)
        conn.commit()
        return cur.fetchall()
    finally:
        conn.close()


def store_files():
    return sorted(str(p.relative_to(TMP_STORE)) for p in __import__("pathlib").Path(TMP_STORE).rglob("*") if p.is_file())


def counts():
    return (sql("SELECT COUNT(*) FROM report_versions")[0][0], sql("SELECT COUNT(*) FROM visit_files")[0][0],
            len(store_files()))


def png(seed=0):
    """A tiny but genuinely valid PNG (different bytes per seed)."""
    def chunk(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    raw = b"\x00" + bytes([seed % 256, 0, 0])
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
ANALYSIS = {
    "mode": "image_only",
    "diseases_visualized": ["pneumonia", "pleural_effusion"],
    "diseases_qualified_not_shown": [{"disease": "edema", "probability": 0.55}],
    "findings": {
        "pneumonia": {"positive_prob": 0.91, "method": "model", "region_count": 2, "localized": True},
        "pleural_effusion": {"positive_prob": 0.7, "method": "model", "region_count": 1, "localized": True},
    },
    "report_text": "FINDINGS:\nRight lower zone opacity.\n\nIMPRESSION:\nLikely pneumonia.\n",
    "annotated_image_base64": "SHOULD-BE-IGNORED",
    "note": None,
}


class Person:
    def __init__(self, client, csrf, user_id):
        self.c, self.h, self.user_id = client, {"X-CSRF-Token": csrf}, user_id

    def post(self, path, json=None):
        return self.c.post(path, json=json, headers=self.h)

    def get(self, path):
        return self.c.get(path)

    def save(self, sid, analysis=ANALYSIS, files=None, csrf=True, raw_json=None):
        files = files if files is not None else {"xray": ("x.png", png(1), "image/png"),
                                                 "annotated": ("a.png", png(2), "image/png"),
                                                 "comparison": ("c.jpg", JPEG, "image/jpeg")}
        data = {"analysis_json": raw_json if raw_json is not None else json.dumps(analysis)}
        return self.c.post(f"/visits/{sid}/analysis", data=data, files=files, headers=self.h if csrf else {})


def new_patient(email):
    c = TestClient(app)
    r = c.post("/auth/register/patient", json={"email": email, "password": PW})
    assert r.status_code == 201, r.text
    return Person(c, r.json()["csrf_token"], r.json()["user"]["user_id"])


def new_visit(p, code=None):
    body = {"doctor_report": "x", "xray_findings": {"a": 1}}
    if code:
        body["patient_code"] = code
    r = p.post("/session/start", body)
    assert r.status_code == 200, r.text
    return r.json()["session_id"], r.json()["patient_code"]


def new_doctor(email, pmdc):
    c = TestClient(app)
    r = c.post("/auth/register/doctor", json={"email": email, "password": PW, "full_name": "Dr Test Person",
                                              "father_name": "F", "pmdc_number": pmdc})
    assert r.status_code == 201, r.text
    return Person(c, r.json()["csrf_token"], r.json()["user"]["user_id"])


def approve(admin_row, doc, days=400):
    from datetime import date, timedelta
    conn = core.open_db()
    try:
        admin_ops.approve_doctor(conn, dict(admin_row), doc.user_id, core.utcnow().date() + timedelta(days=days))
    finally:
        conn.close()


def run():
    auth_api.login_limiter = core.RateLimiter(10_000, 600)
    auth_api.register_limiter = core.RateLimiter(10_000, 3600)

    with TestClient(app):
        conn = core.open_db()
        core.create_admin_user(conn, "admin@example.com", PW, "Admin")
        conn.close()
        admin_row = sql("SELECT user_id, role FROM users WHERE role='admin'")[0]
        ac = TestClient(app)
        r = ac.post("/auth/login", json={"email": "admin@example.com", "password": PW})
        admin = Person(ac, r.json()["csrf_token"], r.json()["user"]["user_id"])

        pat = new_patient("pat@example.com")
        doc = new_doctor("doc@example.com", "11111-A")
        doc2 = new_doctor("doc2@example.com", "22222-B")
        pending = new_doctor("pending@example.com", "33333-C")
        approve(admin_row, doc)
        approve(admin_row, doc2)

        sid, code = new_visit(doc)
        check_save = doc.save(sid)
        sid_p, _ = new_visit(pat)
        pat.save(sid_p)
        sid_other, _ = new_visit(doc2)
        doc2.save(sid_other)
        sid_plain, _ = new_visit(doc)   # a visit with no saved analysis

        print("\n[TEST 1] Not logged in -> 401")
        check("GET /doctor/visits/{id}", TestClient(app).get(f"/doctor/visits/{sid}").status_code == 401)

        print("\n[TEST 2] Who may NOT call a doctor route (acceptance criterion 2)")
        check("patient -> 403", pat.get(f"/doctor/visits/{sid_p}").status_code == 403)
        check("pending doctor -> 403", pending.get(f"/doctor/visits/{sid}").status_code == 403)
        check("admin -> 403", admin.get(f"/doctor/visits/{sid}").status_code == 403)
        admin.post(f"/admin/doctors/{pending.user_id}/reject", {"reason": "x"})
        check("rejected doctor -> 403", pending.get(f"/doctor/visits/{sid}").status_code == 403)

        print("\n[TEST 3] A verified doctor reviewing their own visit")
        r = doc.get(f"/doctor/visits/{sid}")
        check("200", r.status_code == 200)
        v = r.json()
        check("final report text and findings are there", v["report"]["report_text"] == ANALYSIS["report_text"]
              and v["report"]["structured"]["findings"]["pneumonia"]["positive_prob"] == 0.91)
        check("version history lists version 1 from the AI, final", v["versions"] == [
            {"version_no": 1, "source": "ai", "created_at": v["versions"][0]["created_at"], "is_final": True, "author": None}])
        check("all three images flagged present", all(v["files"].values()))
        check("the doctor can fetch the images through the shared image route",
              doc.get(f"/visits/{sid}/files/annotated").status_code == 200)
        vp = doc.get(f"/doctor/visits/{sid_plain}").json()
        check("a visit with no saved analysis -> report null, no versions", vp["report"] is None and vp["versions"] == [])

        print("\n[TEST 4] Doctors and patients stay independent")
        check("doctor cannot review another doctor's visit -> 404", doc.get(f"/doctor/visits/{sid_other}").status_code == 404)
        check("doctor cannot review a PATIENT's visit -> 404", doc.get(f"/doctor/visits/{sid_p}").status_code == 404)
        check("... same wording as a visit that does not exist", doc.get(f"/doctor/visits/{sid_p}").json()
              == doc.get("/doctor/visits/00000000-0000-4000-8000-000000000000").json())
        check("a non-UUID id -> 404", doc.get("/doctor/visits/..%2F..%2Fetc").status_code == 404)
        check("doctor 2 cannot review the first doctor's visit -> 404", doc2.get(f"/doctor/visits/{sid}").status_code == 404)

        print("\n[TEST 5] Revocation and expiry close the door at the next request")
        check("doctor can review now", doc.get(f"/doctor/visits/{sid}").status_code == 200)
        sql("UPDATE doctor_profiles SET license_valid_upto = date('now','-1 day') WHERE user_id = ?", (doc.user_id,))
        check("licence date passes -> 403", doc.get(f"/doctor/visits/{sid}").status_code == 403)
        admin.post(f"/admin/doctors/{doc2.user_id}/reject", {"reason": "revoked"})
        check("admin revokes doctor 2 -> their next request is 403", doc2.get(f"/doctor/visits/{sid_other}").status_code == 403)

        print("\n[TEST 6] Step 5 is view-only: no way to change anything through /doctor")
        approve(admin_row, doc)
        before = sql("SELECT report_text FROM report_versions WHERE session_id = ?", (sid,))[0][0]
        verdicts = [doc.c.request(m, f"/doctor/visits/{sid}", headers=doc.h, json={"report_text": "HACKED"}).status_code in (404, 405)
                    for m in ("POST", "PUT", "PATCH", "DELETE")]
        check("POST/PUT/PATCH/DELETE on /doctor/visits/{id} are refused", all(verdicts))
        check("report unchanged", sql("SELECT report_text FROM report_versions WHERE session_id = ?", (sid,))[0][0] == before)

    return failed == 0


if __name__ == "__main__":
    try:
        ok = run()
    finally:
        try:
            os.remove(TMP_DB)
        except OSError:
            pass
        shutil.rmtree(TMP_STORE, ignore_errors=True)
    print("\n" + "=" * 60)
    print(f"{passed}/{passed + failed} doctor-route tests passed.")
    print("=" * 60)
    sys.exit(0 if ok else 1)
