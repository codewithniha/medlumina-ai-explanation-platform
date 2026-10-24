"""
test_edit.py  --  Step 6a tests: a verified doctor edits FINDINGS (/doctor/visits/{id}/edit/findings), through the REAL module4_api.py routes, on a THROWAWAY database
and a THROWAWAY image folder (never your real sessions.db or private_store/).

HONEST SCOPE: Gemini / MedGemma / Chroma / OCR / the answer pipeline are replaced
by fakes (same as test_access.py). What is real: the routes, login/CSRF/ownership
guards, input validation, SQLite, and the files written to disk.

Run from backend/module4:   python test_edit.py
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



def fnd(view):
    return view["report"]["structured"]["findings"]


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
        doc.save(sid)
        sid_p, _ = new_visit(pat)
        pat.save(sid_p)
        sid_other, _ = new_visit(doc2)
        doc2.save(sid_other)
        sid_plain, _ = new_visit(doc)

        E = lambda s: f"/doctor/visits/{s}/edit/findings"
        GOOD = {"base_version_no": 1, "decisions": {"pneumonia": "confirm", "pleural_effusion": "remove"},
                "added": ["Cardiomegaly"], "note": "Effusion not seen on lateral view."}

        print("\n[TEST 1] Who may NOT edit (acceptance criteria 1 and 2)")
        check("not logged in -> 401", TestClient(app).post(E(sid), json=GOOD).status_code == 401)
        check("PATIENT calling the edit route directly -> 403", pat.post(E(sid_p), GOOD).status_code == 403)
        check("... even with a garbage body -> still 403 (permission is checked first)", pat.post(E(sid_p), {"x": 1}).status_code == 403)
        check("pending doctor -> 403", pending.post(E(sid), GOOD).status_code == 403)
        check("admin -> 403", admin.post(E(sid), GOOD).status_code == 403)
        r = doc.c.post(E(sid), json=GOOD)
        check("verified doctor WITHOUT the CSRF header -> 403", r.status_code == 403)
        check("nothing was changed by any of those", sql("SELECT COUNT(*) FROM report_versions WHERE session_id=?", (sid,))[0][0] == 1)

        print("\n[TEST 2] Independence")
        check("doctor cannot edit another doctor's visit -> 404", doc.post(E(sid_other), GOOD).status_code == 404)
        check("doctor cannot edit a PATIENT's visit -> 404", doc.post(E(sid_p), GOOD).status_code == 404)
        check("non-UUID id -> 404", doc.post("/doctor/visits/abc/edit/findings", GOOD).status_code == 404)
        check("a visit with no saved analysis -> 409", doc.post(E(sid_plain), GOOD).status_code == 409)
        check("others' visits untouched", sql("SELECT COUNT(*) FROM report_versions WHERE session_id IN (?, ?)", (sid_other, sid_p))[0][0] == 2)

        print("\n[TEST 3] A good edit (acceptance criterion 3)")
        v1_text = sql("SELECT report_text FROM report_versions WHERE session_id=? AND version_no=1", (sid,))[0][0]
        r = doc.post(E(sid), GOOD)
        check("200", r.status_code == 200)
        v = r.json()
        check("the view now shows version 2, source doctor_edit", v["report"]["version_no"] == 2 and v["report"]["source"] == "doctor_edit")
        text = v["report"]["report_text"]
        check("report mentions the confirmed finding (with the AI probability)", "Pneumonia" in text and "91.0%" in text)
        check("report mentions the doctor-added finding", "Cardiomegaly: added by the reviewing doctor" in text)
        generated = text.split("DOCTOR'S NOTE")[0]   # FINDINGS + IMPRESSION; the note below is the doctor's own words
        check("FINDINGS/IMPRESSION do NOT mention the removed finding", "pleural" not in generated.lower() and "effusion" not in generated.lower())
        check("report does NOT mention a finding the AI only 'qualified but not shown' (edema)", "edema" not in text.lower())
        check("the doctor's own note is included", "Effusion not seen on lateral view." in text)
        check("old AI sentence is gone from the new text", "Right lower zone opacity." not in text)
        check("structured findings = confirmed + added only", set(fnd(v)) == {"pneumonia", "cardiomegaly"})
        check("removed findings are recorded", v["report"]["structured"]["removed_findings"] == ["pleural_effusion"])
        check("diseases_visualized no longer lists the removed one", v["report"]["structured"]["diseases_visualized"] == ["pneumonia"])
        check("AI numbers preserved on the confirmed finding", fnd(v)["pneumonia"]["positive_prob"] == 0.91 and fnd(v)["pneumonia"]["doctor_status"] == "confirmed")

        print("\n[TEST 4] History is kept, nothing overwritten")
        check("two versions, only version 2 final", [(x["version_no"], x["is_final"]) for x in v["versions"]] == [(1, False), (2, True)])
        check("version 2 is attributed to the doctor's display id", v["versions"][1]["author"].startswith("DR-") and v["versions"][0]["author"] is None)
        check("version 1 text is byte-for-byte unchanged", sql("SELECT report_text FROM report_versions WHERE session_id=? AND version_no=1", (sid,))[0][0] == v1_text)
        check("version 1 findings unchanged (still has the removed one)", "pleural_effusion" in sql("SELECT structured_findings FROM report_versions WHERE session_id=? AND version_no=1", (sid,))[0][0])
        check("exactly one final version in the database", sql("SELECT COUNT(*) FROM report_versions WHERE session_id=? AND is_final=1", (sid,))[0][0] == 1)

        print("\n[TEST 5] Same X-ray and pictures; same version everywhere (acceptance criterion 6)")
        check("all three images still present for version 2", all(v["files"].values()))
        check("annotated image still downloads", doc.get(f"/visits/{sid}/files/annotated").status_code == 200)
        check("X-ray still downloads", doc.get(f"/visits/{sid}/files/xray").status_code == 200)
        own = doc.get(f"/visits/{sid}").json()
        check("the owner's normal view and the doctor view show the same report version and text",
              own["report"]["version_no"] == 2 and own["report"]["report_text"] == text and own["files"] == v["files"])
        check("My Records list shows the edited findings", doc.get(f"/records/{code}/visits").json()["visits"][0]["diseases_visualized"] == ["pneumonia"])

        print("\n[TEST 6] Audit entry (acceptance criterion 4)")
        a = sql("SELECT * FROM audit_log WHERE action='doctor_edit_findings' AND target_id=?", (sid,))
        check("exactly one audit row", len(a) == 1)
        row = a[0]
        before, after = json.loads(row["before_json"]), json.loads(row["after_json"])
        check("who: the doctor's account and role", row["actor_user_id"] == doc.user_id and row["actor_role"] == "doctor")
        check("when: a timestamp", bool(row["at"]))
        check("before: version 1 and its findings", before["version_no"] == 1 and before["findings"] == ["pleural_effusion", "pneumonia"])
        check("after: version 2, removed, added", after["version_no"] == 2 and after["removed"] == ["pleural_effusion"] and after["added"] == ["cardiomegaly"])
        check("text fingerprints differ before/after", before["text_sha"] != after["text_sha"])
        check("audit holds no email / PMDC number", "@" not in repr(row) and "11111-A" not in repr(row))

        print("\n[TEST 7] Concurrency")
        check("editing from the stale version 1 again -> 409", doc.post(E(sid), GOOD).status_code == 409)
        check("... and nothing was added", sql("SELECT COUNT(*) FROM report_versions WHERE session_id=?", (sid,))[0][0] == 2)

        print("\n[TEST 8] A second edit builds on the first")
        r = doc.post(E(sid), {"base_version_no": 2, "decisions": {"pneumonia": "remove", "cardiomegaly": "confirm"}})
        v3 = r.json()
        check("version 3", r.status_code == 200 and v3["report"]["version_no"] == 3)
        t3 = v3["report"]["report_text"]
        check("v3 mentions only cardiomegaly now", "Cardiomegaly" in t3 and "Pneumonia" not in t3)
        check("removals accumulate", v3["report"]["structured"]["removed_findings"] == ["pleural_effusion", "pneumonia"])
        check("pictures still there after two edits", all(v3["files"].values()))
        r = doc.post(E(sid), {"base_version_no": 3, "decisions": {"cardiomegaly": "remove"}})
        check("removing everything gives an honest 'no abnormal findings' report",
              r.status_code == 200 and "No abnormal findings" in r.json()["report"]["report_text"] and r.json()["report"]["structured"]["findings"] == {})

        print("\n[TEST 9] Bad requests are refused and change nothing")
        sid2, _ = new_visit(doc)
        doc.save(sid2)
        n0 = sql("SELECT COUNT(*) FROM report_versions WHERE session_id=?", (sid2,))[0][0]
        base = {"base_version_no": 1, "decisions": {"pneumonia": "confirm", "pleural_effusion": "confirm"}}
        bad = {
            "no changes at all": base,
            "missing a decision": {"base_version_no": 1, "decisions": {"pneumonia": "remove"}},
            "decision for an unknown finding": {"base_version_no": 1, "decisions": {**base["decisions"], "ghost": "remove"}},
            "decision value not confirm/remove": {"base_version_no": 1, "decisions": {"pneumonia": "maybe", "pleural_effusion": "remove"}},
            "bad added name": {**base, "added": ["<script>"]},
            "added name already present": {**base, "added": ["Pneumonia"]},
            "same name added twice": {**base, "added": ["cardiomegaly", "Cardiomegaly"]},
            "too many added": {**base, "added": [f"finding_{i}" for i in range(11)]},
            "note over 2000 characters": {**base, "note": "x" * 2001},
            "unknown extra field (role)": {**base, "note": "n", "role": "admin"},
            "base_version_no missing": {"decisions": base["decisions"], "note": "n"},
            "base_version_no 0": {"base_version_no": 0, "decisions": base["decisions"], "note": "n"},
        }
        for label_, body in bad.items():
            check(f"{label_} -> 422", doc.post(E(sid2), body).status_code == 422)
        check("a body that is not an object -> 422", doc.c.post(E(sid2), content=b"[1,2]", headers={**doc.h, "Content-Type": "application/json"}).status_code == 422)
        check("version count unchanged after all the bad requests", sql("SELECT COUNT(*) FROM report_versions WHERE session_id=?", (sid2,))[0][0] == n0)
        check("note-only edit is allowed (no change to findings)",
              doc.post(E(sid2), {**base, "note": "Reviewed, agree."}).status_code == 200)

        print("\n[TEST 10] All-or-nothing: a failure half-way leaves no trace")
        sid3, _ = new_visit(doc)
        doc.save(sid3)
        real_audit = core.audit
        def boom(*a, **k):
            raise RuntimeError("simulated crash while auditing")
        core.audit = boom
        try:
            try:
                r = doc.post(E(sid3), {"base_version_no": 1, "decisions": {"pneumonia": "remove", "pleural_effusion": "confirm"}})
                code_ = r.status_code
            except Exception:
                code_ = 500
        finally:
            core.audit = real_audit
        check("the request failed", code_ == 500)
        check("still exactly one version, still final, still the AI's",
              sql("SELECT version_no, source, is_final FROM report_versions WHERE session_id=?", (sid3,))[0][:] == (1, "ai", 1)
              and sql("SELECT COUNT(*) FROM report_versions WHERE session_id=?", (sid3,))[0][0] == 1)
        check("no stray picture rows were added", sql("SELECT COUNT(*) FROM visit_files WHERE session_id=?", (sid3,))[0][0] == 3)
        check("the same edit works once the fault is gone", doc.post(E(sid3), {"base_version_no": 1, "decisions": {"pneumonia": "remove", "pleural_effusion": "confirm"}}).status_code == 200)

        print("\n[TEST 11] Revocation and expiry close the edit door too")
        sid4, _ = new_visit(doc2)
        doc2.save(sid4)
        check("doctor 2 can edit now", doc2.post(E(sid4), {"base_version_no": 1, "decisions": {"pneumonia": "confirm", "pleural_effusion": "remove"}}).status_code == 200)
        admin.post(f"/admin/doctors/{doc2.user_id}/reject", {"reason": "x"})
        check("after the admin revokes doctor 2 -> 403 on the very next edit", doc2.post(E(sid4), {"base_version_no": 2, "decisions": {"pneumonia": "remove"}}).status_code == 403)
        sql("UPDATE doctor_profiles SET license_valid_upto = ? WHERE user_id = ?", ((core.utcnow().date().replace(year=2000)).isoformat(), doc.user_id))
        check("expired licence -> 403 on edit", doc.post(E(sid2), {"base_version_no": 2, "decisions": {"pneumonia": "remove", "pleural_effusion": "confirm"}}).status_code == 403)

        print("\n[TEST 12] Template itself")
        from doctor_edit import build_report_text
        t = build_report_text({"pleural_effusion": {"positive_prob": 0.7, "doctor_status": "confirmed"}}, None)
        check("labels read naturally (Pleural effusion)", "Pleural effusion: AI probability 70.0%" in t and "DOCTOR'S NOTE" not in t)

    print("\n" + "=" * 60)
    print(f"{passed}/{passed + failed} doctor-edit tests passed.")
    print("=" * 60)
    return failed == 0


if __name__ == "__main__":
    ok = run()
    shutil.rmtree(TMP_STORE, ignore_errors=True)
    try:
        os.remove(TMP_DB)
    except OSError:
        pass
    sys.exit(0 if ok else 1)
