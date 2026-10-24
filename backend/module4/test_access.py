"""
test_access.py  --  Step 3b tests: the REAL module4_api.py routes with the
guards, on a THROWAWAY database (never your real sessions.db).

HONEST SCOPE: the AI parts (Gemini / MedGemma / Chroma indexing / the answer
pipeline / OCR) are replaced by tiny fakes so this test needs no API keys, no
GPU and no internet. What is real: module4_api.py's routes, the login/CSRF/doctor
guards, the ownership checks and the SQLite database. What is NOT tested here:
the AI answers themselves (unchanged by step 3b).

Run from backend/module4:   python test_access.py
Most tests try something FORBIDDEN and expect a refusal.
"""

import builtins
import getpass
import os
import sqlite3
import sys
import tempfile
import types
from datetime import date, timedelta

_fd, TMP_DB = tempfile.mkstemp(suffix=".db")
os.close(_fd)
os.environ["SESSION_DB_PATH"] = TMP_DB
os.environ["COOKIE_SECURE"] = "false"

CALLS = {"index": [], "answer": [], "transcribe": 0}


def _fake(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod


def _fake_index(**kw):
    CALLS["index"].append(kw)
    return 3


def _fake_answer(session_id, question):
    CALLS["answer"].append((session_id, question))
    return {"classification": "SESSION_GROUNDED", "answer": "fake answer"}


def _fake_transcribe(*a, **k):
    CALLS["transcribe"] += 1
    return "fake report text"


_fake("llm_client", MEDGEMMA_API_URL="")
_fake("ocr", transcribe_handwritten_report=_fake_transcribe, transcribe_report_from_pdf=_fake_transcribe)
_fake("kb_indexer", ensure_kb_indexed=lambda: None)
_fake("session_indexer", index_session_data=_fake_index)
_fake("module4_pipeline", answer_question=_fake_answer)

from fastapi.testclient import TestClient  # noqa: E402

import admin_ops  # noqa: E402
import auth_api  # noqa: E402
import auth_core as core  # noqa: E402
import module4_api  # noqa: E402  (the real file under test)

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


def future(days=365):
    return (core.utcnow().date() + timedelta(days=days)).isoformat()


def past(days=1):
    return (core.utcnow().date() - timedelta(days=days)).isoformat()


class Person:
    """A client (browser) plus its CSRF header."""

    def __init__(self, client, csrf, user_id):
        self.c, self.h, self.user_id = client, {"X-CSRF-Token": csrf}, user_id

    def post(self, path, json=None, **kw):
        return self.c.post(path, json=json, headers=self.h, **kw)

    def post_nocsrf(self, path, json=None):
        return self.c.post(path, json=json)

    def get(self, path):
        return self.c.get(path)


def new_patient(email):
    c = TestClient(app)
    r = c.post("/auth/register/patient", json={"email": email, "password": PW})
    assert r.status_code == 201, r.text
    return Person(c, r.json()["csrf_token"], r.json()["user"]["user_id"])


def new_doctor(email, pmdc):
    c = TestClient(app)
    r = c.post("/auth/register/doctor", json={"email": email, "password": PW, "full_name": "Dr Test Person",
                                              "father_name": "Test Father", "pmdc_number": pmdc})
    assert r.status_code == 201, r.text
    return Person(c, r.json()["csrf_token"], r.json()["user"]["user_id"])


def new_admin(email):
    conn = core.open_db()
    try:
        core.create_admin_user(conn, email, PW, "Admin Person")
    finally:
        conn.close()
    c = TestClient(app)
    r = c.post("/auth/login", json={"email": email, "password": PW})
    assert r.status_code == 200, r.text
    return Person(c, r.json()["csrf_token"], r.json()["user"]["user_id"])


START = {"doctor_report": "Mild right lower zone opacity.", "xray_findings": {"pneumonia": 0.8}}


def run():
    auth_api.login_limiter = core.RateLimiter(10_000, 600)
    auth_api.register_limiter = core.RateLimiter(10_000, 3600)

    with TestClient(app) as boot:   # runs the real startup (lifespan) once
        print("\n[TEST 1] Startup wiring")
        tables = {r["name"] for r in sql("SELECT name FROM sqlite_master WHERE type='table'")}
        check("startup created the account tables (init_accounts_schema is wired in)",
              {"users", "doctor_profiles", "auth_sessions", "audit_log"} <= tables)
        check("/health stays public", boot.get("/health").status_code == 200)

        alice = new_patient("alice@example.com")
        bob = new_patient("bob@example.com")
        admin = new_admin("admin@example.com")

        print("\n[TEST 2] Not logged in -> 401 on every Module 4 route")
        anon = TestClient(app)
        for method, path, body in [
            ("get", "/records", None),
            ("post", "/patient/lookup", {"patient_code": "PT-AAAAAA"}),
            ("post", "/session/start", START),
            ("post", "/session/ask", {"session_id": "x", "question": "hi"}),
            ("post", "/session/history", {"session_id": "x"}),
            ("post", "/session/explanation_level", {"session_id": "x", "explanation_level": "simple"}),
            ("get", "/admin/doctors", None),
        ]:
            r = getattr(anon, method)(path, **({"json": body} if body is not None else {}))
            check(f"{method.upper()} {path}", r.status_code == 401)
        r = anon.post("/report/transcribe", files={"image": ("r.png", b"x", "image/png")})
        check("POST /report/transcribe", r.status_code == 401)
        check("no AI work was triggered by any of those", not CALLS["index"] and not CALLS["answer"]
              and CALLS["transcribe"] == 0)

        print("\n[TEST 3] A patient starts a visit; the new record belongs to them")
        r = alice.post("/session/start", START)
        check("alice /session/start -> 200", r.status_code == 200)
        a_sid, a_code = r.json()["session_id"], r.json()["patient_code"]
        owner = sql("SELECT owner_user_id FROM patients WHERE patient_code = ?", (a_code,))[0]["owner_user_id"]
        check("record is owned by alice", owner == alice.user_id)
        r = alice.post("/session/start", {**START, "patient_code": a_code})
        check("second visit under her own code -> 200", r.status_code == 200)
        check("... and it joined the SAME record", r.json()["patient_id"] == sql(
            "SELECT patient_id FROM patients WHERE patient_code = ?", (a_code,))[0]["patient_id"])
        recs = alice.get("/records").json()["records"]
        check("GET /records lists her record with 2 visits", len(recs) == 1 and recs[0]["visit_count"] == 2
              and recs[0]["patient_code"] == a_code)
        r = alice.post("/session/start", {**START, "owner_user_id": bob.user_id})
        check("a body that tries to set owner_user_id is ignored (record still hers)",
              r.status_code == 200 and sql("SELECT owner_user_id FROM patients WHERE patient_code = ?",
                                           (r.json()["patient_code"],))[0]["owner_user_id"] == alice.user_id)

        print("\n[TEST 4] Her own visit works for her")
        check("ask -> 200", alice.post("/session/ask", {"session_id": a_sid, "question": "What is this?"}).status_code == 200)
        check("history -> 200", alice.post("/session/history", {"session_id": a_sid}).status_code == 200)
        check("change level -> 200", alice.post("/session/explanation_level",
                                                {"session_id": a_sid, "explanation_level": "detailed"}).status_code == 200)
        check("lookup own code -> 200", alice.post("/patient/lookup", {"patient_code": a_code}).status_code == 200)

        print("\n[TEST 5] Bob cannot touch alice's record or visit (looks like 'does not exist')")
        n_sessions = len(sql("SELECT 1 FROM sessions"))
        n_index, n_answer = len(CALLS["index"]), len(CALLS["answer"])
        r1 = bob.post("/session/start", {**START, "patient_code": a_code})
        check("start a visit in alice's record -> 404", r1.status_code == 404)
        check("... no session was created and nothing indexed",
              len(sql("SELECT 1 FROM sessions")) == n_sessions and len(CALLS["index"]) == n_index)
        r2 = bob.post("/patient/lookup", {"patient_code": a_code})
        check("lookup alice's code -> 404", r2.status_code == 404)
        r_unknown = bob.post("/patient/lookup", {"patient_code": "PT-ZZZZZZ"})
        check("... same wording as a code that truly does not exist",
              r2.json()["detail"].replace(a_code, "X") == r_unknown.json()["detail"].replace("PT-ZZZZZZ", "X"))
        r3 = bob.post("/session/ask", {"session_id": a_sid, "question": "show me her report"})
        check("ask on alice's session -> 404", r3.status_code == 404)
        check("... the AI pipeline was never called", len(CALLS["answer"]) == n_answer)
        r_missing = bob.post("/session/ask", {"session_id": "no-such-session", "question": "hi"})
        check("... same wording as a session that truly does not exist", r3.json() == r_missing.json())
        check("history of alice's session -> 404", bob.post("/session/history", {"session_id": a_sid}).status_code == 404)
        before = sql("SELECT explanation_level FROM sessions WHERE session_id = ?", (a_sid,))[0][0]
        check("change alice's explanation level -> 404", bob.post(
            "/session/explanation_level", {"session_id": a_sid, "explanation_level": "simple"}).status_code == 404)
        check("... and it did not change", sql("SELECT explanation_level FROM sessions WHERE session_id = ?",
                                               (a_sid,))[0][0] == before)
        check("bob's /records is empty", bob.get("/records").json()["records"] == [])

        print("\n[TEST 6] Old records from before accounts existed are not open to anyone")
        sql("INSERT INTO patients (patient_id, patient_code, name, created_at) VALUES ('legacy-p', 'PT-OLD111', 'Old', '2026-01-01')")
        sql("INSERT INTO sessions (session_id, created_at, patient_id) VALUES ('legacy-s', '2026-01-01', 'legacy-p')")
        check("alice lookup of unowned record -> 404", alice.post("/patient/lookup", {"patient_code": "PT-OLD111"}).status_code == 404)
        check("alice start in unowned record -> 404", alice.post("/session/start", {**START, "patient_code": "PT-OLD111"}).status_code == 404)
        check("alice ask on unowned visit -> 404", alice.post("/session/ask", {"session_id": "legacy-s", "question": "hi"}).status_code == 404)

        print("\n[TEST 7] CSRF protection on the real routes")
        n_answer = len(CALLS["answer"])
        check("ask without CSRF header -> 403", alice.post_nocsrf("/session/ask", {"session_id": a_sid, "question": "hi"}).status_code == 403)
        check("start without CSRF header -> 403", alice.post_nocsrf("/session/start", START).status_code == 403)
        check("... nothing ran", len(CALLS["answer"]) == n_answer)

        print("\n[TEST 8] Admins are not patients: no access to patient features")
        check("admin GET /records -> 403", admin.get("/records").status_code == 403)
        check("admin /session/start -> 403", admin.post("/session/start", START).status_code == 403)

        print("\n[TEST 9] Pending doctor is locked out (acceptance criterion 2)")
        doc = new_doctor("doc@example.com", "12345-P")
        check("pending doctor GET /records -> 403", doc.get("/records").status_code == 403)
        check("pending doctor /session/start -> 403", doc.post("/session/start", START).status_code == 403)
        r = doc.c.post("/report/transcribe", files={"image": ("r.png", b"x", "image/png")}, headers=doc.h)
        check("pending doctor /report/transcribe -> 403", r.status_code == 403)
        check("pending doctor may still see their own status", doc.get("/auth/me").status_code == 200)

        print("\n[TEST 10] Admin approval through the web routes")
        pend = admin.get("/admin/doctors?status=pending").json()["doctors"]
        mine = [d for d in pend if d["user_id"] == doc.user_id]
        check("admin sees the pending doctor with the PMDC number to check", len(mine) == 1 and mine[0]["pmdc_number"] == "12345-P")
        ap = f"/admin/doctors/{doc.user_id}/approve"
        check("approve without ticking 'checked on PMDC register' -> 422",
              admin.post(ap, {"license_valid_upto": future(), "checked_on_pmdc_register": False}).status_code == 422)
        check("approve with a past licence date -> 422",
              admin.post(ap, {"license_valid_upto": past(), "checked_on_pmdc_register": True}).status_code == 422)
        check("approve with a date >10 years away -> 422",
              admin.post(ap, {"license_valid_upto": future(365 * 11), "checked_on_pmdc_register": True}).status_code == 422)
        check("approve with a made-up extra field -> 422",
              admin.post(ap, {"license_valid_upto": future(), "checked_on_pmdc_register": True, "status": "x"}).status_code == 422)
        check("doctor still locked out after all those refusals", doc.get("/records").status_code == 403)
        check("approve a user id that is not a doctor (alice) -> 404",
              admin.post(f"/admin/doctors/{alice.user_id}/approve",
                         {"license_valid_upto": future(), "checked_on_pmdc_register": True}).status_code == 404)
        check("a patient cannot use the admin routes -> 403", alice.get("/admin/doctors").status_code == 403)
        check("a patient cannot approve a doctor -> 403", alice.post(
            ap, {"license_valid_upto": future(), "checked_on_pmdc_register": True}).status_code == 403)
        check("a pending doctor cannot approve themselves -> 403", doc.post(
            ap, {"license_valid_upto": future(), "checked_on_pmdc_register": True}).status_code == 403)
        check("admin approves with a valid date -> 200",
              admin.post(ap, {"license_valid_upto": future(), "checked_on_pmdc_register": True}).status_code == 200)
        r = doc.post("/session/start", START)
        check("the SAME doctor session now works (no re-login) -> 200", r.status_code == 200)
        d_sid, d_code = r.json()["session_id"], r.json()["patient_code"]
        check("doctor owns the record they started", sql(
            "SELECT owner_user_id FROM patients WHERE patient_code = ?", (d_code,))[0][0] == doc.user_id)
        r = doc.c.post("/report/transcribe", files={"image": ("r.png", b"x", "image/png")}, headers=doc.h)
        check("verified doctor /report/transcribe -> 200", r.status_code == 200)
        check("doctor cannot open alice's visit", doc.post("/session/ask", {"session_id": a_sid, "question": "hi"}).status_code == 404)
        check("alice cannot open the doctor's visit", alice.post("/session/ask", {"session_id": d_sid, "question": "hi"}).status_code == 404)

        print("\n[TEST 11] Revocation and expiry close the door on the next request")
        rj = admin.post(f"/admin/doctors/{doc.user_id}/reject", {"reason": "register shows a different name"})
        check("admin rejects/revokes -> 200", rj.status_code == 200)
        check("doctor's very next request -> 403", doc.post("/session/ask", {"session_id": d_sid, "question": "hi"}).status_code == 403)
        admin.post(ap, {"license_valid_upto": future(), "checked_on_pmdc_register": True})
        check("re-approved -> access returns", doc.get("/records").status_code == 200)
        sql("UPDATE doctor_profiles SET license_valid_upto = ? WHERE user_id = ?", (past(), doc.user_id))
        check("licence date passes -> 403", doc.get("/records").status_code == 403)

        print("\n[TEST 12] Audit trail of admin decisions")
        rows = sql("SELECT actor_user_id, actor_role, action, target_id FROM audit_log WHERE action LIKE 'admin_%'")
        acts = [r["action"] for r in rows]
        check("approve and reject were recorded", "admin_approve_doctor" in acts and "admin_reject_doctor" in acts)
        check("... with the admin as actor", all(r["actor_user_id"] == admin.user_id and r["actor_role"] == "admin" for r in rows))
        text = "\n".join(" | ".join(str(v) for v in tuple(r)) for r in sql("SELECT * FROM audit_log"))
        check("no PMDC number in the audit log", "12345-P" not in text)
        check("no email in the audit log", "@example.com" not in text)

        print("\n[TEST 13] approve_doctor.py (command-line tool) with scripted input")
        doc2 = new_doctor("doc2@example.com", "99999-Q")
        import approve_doctor
        # The first doctor (licence expired in test 11) is also waiting: skip them, approve doctor 2.
        answers = iter(["admin@example.com", "s", "a", future(400)])
        orig_input, orig_pw = builtins.input, getpass.getpass
        builtins.input = lambda prompt="": next(answers)
        getpass.getpass = lambda prompt="": PW
        try:
            rc = approve_doctor.main()
        finally:
            builtins.input, getpass.getpass = orig_input, orig_pw
        check("script returns success", rc == 0)
        check("doctor 2 is now verified", sql("SELECT status FROM users WHERE user_id = ?", (doc2.user_id,))[0][0] == "verified")
        check("the skipped doctor was NOT approved", sql("SELECT status FROM users WHERE user_id = ?", (doc.user_id,))[0][0] == "pending")
        check("doctor 2 session works", doc2.get("/records").status_code == 200)
        builtins.input, getpass.getpass = (lambda p="": "alice@example.com"), (lambda p="": PW)
        try:
            rc = approve_doctor.main()
        finally:
            builtins.input, getpass.getpass = orig_input, orig_pw
        check("a non-admin cannot use the script", rc == 1)

        print("\n[TEST 14] Logout really ends access to the data")
        r = alice.post("/auth/logout")
        check("logout -> 200", r.status_code == 200)
        check("alice's old cookie can no longer read her records", alice.get("/records").status_code == 401)

    return failed == 0


if __name__ == "__main__":
    try:
        ok = run()
    finally:
        try:
            os.remove(TMP_DB)
        except OSError:
            pass
    print("\n" + "=" * 60)
    print(f"{passed}/{passed + failed} access tests passed.")
    print("=" * 60)
    sys.exit(0 if ok else 1)
