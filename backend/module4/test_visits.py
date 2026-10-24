"""
test_visits.py  --  Step 4a tests: saving a visit's analysis on the server and
reading it back, through the REAL module4_api.py routes, on a THROWAWAY database
and a THROWAWAY image folder (never your real sessions.db or private_store/).

HONEST SCOPE: Gemini / MedGemma / Chroma / OCR / the answer pipeline are replaced
by fakes (same as test_access.py). What is real: the routes, login/CSRF/ownership
guards, input validation, SQLite, and the files written to disk.

Run from backend/module4:   python test_visits.py
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


def run():
    auth_api.login_limiter = core.RateLimiter(10_000, 600)
    auth_api.register_limiter = core.RateLimiter(10_000, 3600)

    with TestClient(app):
        alice, bob = new_patient("alice@example.com"), new_patient("bob@example.com")
        sid, code = new_visit(alice)

        print("\n[TEST 1] Not logged in -> 401")
        anon = TestClient(app)
        check("POST analysis", anon.post(f"/visits/{sid}/analysis").status_code == 401)
        check("GET visit", anon.get(f"/visits/{sid}").status_code == 401)
        check("GET file", anon.get(f"/visits/{sid}/files/xray").status_code == 401)
        check("GET visit list", anon.get(f"/records/{code}/visits").status_code == 401)

        print("\n[TEST 2] A visit without a saved analysis")
        v = alice.get(f"/visits/{sid}").json()
        check("report is null, no images, read_only true", v["report"] is None and v["read_only"] is True
              and not any(v["files"].values()))
        check("image request -> 404", alice.get(f"/visits/{sid}/files/xray").status_code == 404)

        print("\n[TEST 3] Saving the analysis")
        r = alice.save(sid)
        check("save -> 201 (version 1)", r.status_code == 201 and r.json()["version_no"] == 1)
        rv = sql("SELECT * FROM report_versions WHERE session_id = ?", (sid,))
        check("one report_versions row: source ai, final, version 1",
              len(rv) == 1 and rv[0]["source"] == "ai" and rv[0]["is_final"] == 1 and rv[0]["version_no"] == 1)
        check("report text stored exactly", rv[0]["report_text"] == ANALYSIS["report_text"])
        check("stray client field (annotated_image_base64) was dropped",
              "SHOULD-BE-IGNORED" not in (rv[0]["structured_findings"] or ""))
        vf = sql("SELECT * FROM visit_files WHERE session_id = ? ORDER BY kind", (sid,))
        check("three file rows (xray_original, annotated, comparison)",
              [r_["kind"] for r_ in vf] == ["annotated", "comparison", "xray_original"])
        on_disk = all((__import__("pathlib").Path(TMP_STORE) / r_["relative_path"]).is_file() for r_ in vf)
        check("all three files exist on disk", on_disk)
        row = [r_ for r_ in vf if r_["kind"] == "xray_original"][0]
        check("stored sha256 and size match the uploaded bytes",
              row["sha256"] == hashlib.sha256(png(1)).hexdigest() and row["size_bytes"] == len(png(1)))
        check("original X-ray is not tied to a report version; annotated is",
              row["version_id"] is None and [r_ for r_ in vf if r_["kind"] == "annotated"][0]["version_id"] == rv[0]["version_id"])
        check("audit entry written without any report content",
              sql("SELECT COUNT(*) FROM audit_log WHERE action='save_ai_analysis' AND target_id=?", (sid,))[0][0] == 1
              and "Likely pneumonia" not in "".join(str(tuple(x)) for x in sql("SELECT * FROM audit_log")))

        print("\n[TEST 4] Reading it back")
        v = alice.get(f"/visits/{sid}").json()
        check("report text and findings come back", v["report"]["report_text"] == ANALYSIS["report_text"]
              and v["report"]["structured"]["diseases_visualized"] == ["pneumonia", "pleural_effusion"]
              and v["report"]["structured"]["findings"]["pneumonia"]["positive_prob"] == 0.91)
        check("all three images flagged present", all(v["files"].values()))
        f = alice.get(f"/visits/{sid}/files/xray")
        check("X-ray bytes are identical to what was uploaded", f.status_code == 200 and f.content == png(1))
        check("content-type decided by the server (image/png)", f.headers["content-type"] == "image/png")
        check("nosniff + private no-store headers", f.headers.get("x-content-type-options") == "nosniff"
              and "no-store" in f.headers.get("cache-control", ""))
        check("comparison is served as jpeg", alice.get(f"/visits/{sid}/files/comparison").headers["content-type"] == "image/jpeg")
        check("unknown image kind -> 404", alice.get(f"/visits/{sid}/files/passwd").status_code == 404)

        print("\n[TEST 5] Saving twice is refused")
        before = counts()
        check("second save -> 409", alice.save(sid).status_code == 409)
        check("nothing changed (rows and files)", counts() == before)

        print("\n[TEST 6] Bob cannot save into, read, or download alice's visit")
        before = counts()
        check("bob save -> 404", bob.save(sid).status_code == 404)
        r_b = bob.get(f"/visits/{sid}")
        r_none = bob.get("/visits/00000000-0000-4000-8000-000000000000")
        check("bob GET visit -> 404, same wording as a visit that does not exist",
              r_b.status_code == 404 and r_b.json() == r_none.json())
        check("bob GET image -> 404", bob.get(f"/visits/{sid}/files/xray").status_code == 404)
        check("bob GET alice's visit list -> 404", bob.get(f"/records/{code}/visits").status_code == 404)
        check("nothing was written", counts() == before)
        sid_b, _ = new_visit(bob)
        check("bob can save into his own visit", bob.save(sid_b).status_code == 201)
        check("alice cannot read bob's", alice.get(f"/visits/{sid_b}").status_code == 404)

        print("\n[TEST 7] Bad input is refused and leaves NOTHING behind")
        sid2, _ = new_visit(alice, code)
        base = counts()

        def refused(label, resp, status):
            check(f"{label} -> {status}", resp.status_code == status)
            check("   ... no rows, no files left", counts() == base)

        refused("no CSRF header", alice.save(sid2, csrf=False), 403)
        refused("X-ray is HTML renamed to .png", alice.save(sid2, files={"xray": ("x.png", b"<html><script>alert(1)</script>", "image/png")}), 400)
        refused("X-ray is an SVG", alice.save(sid2, files={"xray": ("x.svg", b"<svg xmlns='http://www.w3.org/2000/svg'/>", "image/svg+xml")}), 400)
        refused("a PDF as the X-ray", alice.save(sid2, files={"xray": ("x.pdf", b"%PDF-1.4 ...", "application/pdf")}), 400)
        refused("good X-ray but bad annotated image", alice.save(sid2, files={"xray": ("x.png", png(3), "image/png"), "annotated": ("a.png", b"nope", "image/png")}), 400)
        refused("empty X-ray file", alice.save(sid2, files={"xray": ("x.png", b"", "image/png")}), 400)
        refused("X-ray missing entirely", alice.save(sid2, files={"annotated": ("a.png", png(4), "image/png")}), 422)
        refused("analysis_json is not JSON", alice.save(sid2, raw_json="{not json"), 422)
        refused("mode is not allowed", alice.save(sid2, analysis={**ANALYSIS, "mode": "hack"}), 422)
        refused("probability 5", alice.save(sid2, analysis={**ANALYSIS, "findings": {"x": {"positive_prob": 5}}}), 422)
        refused("report_text over 20000 chars", alice.save(sid2, analysis={**ANALYSIS, "report_text": "A" * 20001}), 422)
        refused("report_text missing", alice.save(sid2, analysis={k: v_ for k, v_ in ANALYSIS.items() if k != "report_text"}), 422)
        old = visit_store.MAX_IMAGE_BYTES
        visit_store.MAX_IMAGE_BYTES = 1000
        refused("X-ray over the size limit", alice.save(sid2, files={"xray": ("x.png", png(5) + b"0" * 2000, "image/png")}), 413)
        visit_store.MAX_IMAGE_BYTES = old
        refused("visit id that is not a UUID (path trick)", alice.c.post("/visits/..%2F..%2Fetc/analysis", data={"analysis_json": json.dumps(ANALYSIS)},
                                                                         files={"xray": ("x.png", png(6), "image/png")}, headers=alice.h), 404)

        print("\n[TEST 8] A failure halfway rolls everything back (files and rows)")
        real_audit = core.audit

        def boom(*a, **k):
            raise RuntimeError("simulated crash after files were written")
        core.audit = boom
        try:
            try:
                r = alice.save(sid2)
                crashed = r.status_code == 500
            except Exception:
                crashed = True   # TestClient re-raises server errors
        finally:
            core.audit = real_audit
        check("the crash happened", crashed)
        check("no rows and no files left behind", counts() == base)
        check("the visit can still be saved afterwards", alice.save(sid2).status_code == 201)

        print("\n[TEST 9] The server offers no way to edit a saved report")
        before = sql("SELECT report_text FROM report_versions WHERE session_id = ?", (sid,))[0][0]
        verdicts = []
        for method in ("put", "patch", "delete"):
            for path in (f"/visits/{sid}", f"/visits/{sid}/analysis", f"/visits/{sid}/files/xray"):
                verdicts.append(alice.c.request(method.upper(), path, headers=alice.h, json={"report_text": "HACKED"}).status_code in (404, 405))
        check("PUT/PATCH/DELETE on every visit route are refused (404/405)", all(verdicts))
        check("report text unchanged", sql("SELECT report_text FROM report_versions WHERE session_id = ?", (sid,))[0][0] == before)
        try:
            sql("UPDATE report_versions SET report_text = 'HACKED' WHERE session_id = ?", (sid,))
            blocked = False
        except sqlite3.DatabaseError:
            blocked = True
        check("even a direct database UPDATE of the report text is refused (trigger)", blocked)

        print("\n[TEST 10] Visit list inside a record")
        lst = alice.get(f"/records/{code}/visits").json()
        check("two visits, newest first", len(lst["visits"]) == 2 and lst["visits"][0]["session_id"] == sid2)
        check("each shows has_report and the findings", all(x["has_report"] for x in lst["visits"])
              and lst["visits"][0]["diseases_visualized"] == ["pneumonia", "pleural_effusion"])
        check("lowercase code works too", alice.get(f"/records/{code.lower()}/visits").status_code == 200)

        print("\n[TEST 11] Old unowned data and pending doctors")
        sql("INSERT INTO patients (patient_id, patient_code, name, created_at) VALUES ('lp', 'PT-OLD222', 'Old', '2026-01-01')")
        legacy = "11111111-1111-4111-8111-111111111111"
        sql("INSERT INTO sessions (session_id, created_at, patient_id) VALUES (?, '2026-01-01', 'lp')", (legacy,))
        check("alice cannot read an unowned legacy visit", alice.get(f"/visits/{legacy}").status_code == 404)
        check("alice cannot save into it", alice.save(legacy).status_code == 404)
        c = TestClient(app)
        r = c.post("/auth/register/doctor", json={"email": "d@example.com", "password": PW, "full_name": "Dr T",
                                                  "father_name": "F", "pmdc_number": "12345-P"})
        doc = Person(c, r.json()["csrf_token"], r.json()["user"]["user_id"])
        check("pending doctor GET visit -> 403", doc.get(f"/visits/{sid}").status_code == 403)
        check("pending doctor save -> 403", doc.save(sid).status_code == 403)

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
    print(f"{passed}/{passed + failed} visit tests passed.")
    print("=" * 60)
    sys.exit(0 if ok else 1)
