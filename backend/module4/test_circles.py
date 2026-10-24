"""
test_circles.py  --  Step 6b-2 tests: a doctor moves / resizes / deletes / adds circles, through the REAL module4_api.py routes, on a THROWAWAY database
and a THROWAWAY image folder (never your real sessions.db or private_store/).

HONEST SCOPE: Gemini / MedGemma / Chroma / OCR / the answer pipeline are replaced
by fakes (same as test_access.py). What is real: the routes, login/CSRF/ownership
guards, input validation, SQLite, and the files written to disk.

Run from backend/module4:   python test_circles.py
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



import io
from PIL import Image


def real_png(w=300, h=400):
    im = Image.new("L", (w, h), 40)
    b = io.BytesIO(); im.save(b, format="PNG"); return b.getvalue()


XRAY = real_png()           # 300 x 400  -> square side 400
SIDE = 400
REGIONS = {
    "pneumonia": [{"center_xy": [150, 120], "radius_px": 40, "bbox_xyxy": [120, 90, 180, 150], "peak_activation": 0.9, "area_px": 2500}],
    "pleural_effusion": [{"center_xy": [100, 300], "radius_px": 40}],
}
AN_R = {
    "mode": "image_only",
    "diseases_visualized": ["pneumonia", "pleural_effusion"],
    "diseases_qualified_not_shown": [],
    "findings": {
        "pneumonia": {"positive_prob": 0.91, "method": "model", "region_count": 1, "localized": True, "regions": REGIONS["pneumonia"], "canvas_px": SIDE},
        "pleural_effusion": {"positive_prob": 0.7, "method": "model", "region_count": 1, "localized": True, "regions": REGIONS["pleural_effusion"], "canvas_px": SIDE},
    },
    "report_text": "FINDINGS:\nRight lower zone opacity.\n\nIMPRESSION:\nLikely pneumonia.\n",
}


def files_of(sid, vno):
    return {r["kind"]: r["relative_path"] for r in sql(
        "SELECT f.kind, f.relative_path FROM visit_files f JOIN report_versions v ON v.version_id=f.version_id "
        "WHERE v.session_id=? AND v.version_no=?", (sid, vno))}


def img_of(rel):
    return Image.open(os.path.join(visit_store.PRIVATE_STORE, rel)).convert("RGB")


def px(img, x, y):
    return img.getpixel((x, y))


def saved(person, analysis, xray=XRAY):
    sid, code = new_visit(person)
    r = person.save(sid, analysis, files={"xray": ("x.png", xray, "image/png"),
                                          "annotated": ("a.png", png(2), "image/png"),
                                          "comparison": ("c.jpg", JPEG, "image/jpeg")})
    assert r.status_code in (200, 201), r.text
    return sid



def run():
    auth_api.login_limiter = core.RateLimiter(10_000, 600)
    auth_api.register_limiter = core.RateLimiter(10_000, 3600)

    with TestClient(app):
        conn = core.open_db()
        core.create_admin_user(conn, "admin@example.com", PW, "Admin")
        conn.close()
        admin_row = sql("SELECT user_id, role FROM users WHERE role='admin'")[0]
        doc = new_doctor("doc@example.com", "11111-A")
        doc2 = new_doctor("doc2@example.com", "22222-B")
        approve(admin_row, doc); approve(admin_row, doc2)
        E = lambda s: f"/doctor/visits/{s}/edit/findings"
        RED, CYAN, YELLOW = (255, 60, 60), (0, 200, 255), (255, 200, 0)
        BOTH = {"pneumonia": "confirm", "pleural_effusion": "confirm"}
        C = lambda x, y, r: {"center_xy": [x, y], "radius_px": r}
        def struct_of(sid, vno):
            return json.loads(sql("SELECT structured_findings FROM report_versions WHERE session_id=? AND version_no=?", (sid, vno))[0][0])
        def n_versions(sid):
            return sql("SELECT COUNT(*) FROM report_versions WHERE session_id=?", (sid,))[0][0]

        print("\n[TEST 1] The screen is told the size of the square the circles live on")
        sid = saved(doc, AN_R)
        v = doc.get(f"/doctor/visits/{sid}").json()
        check("doctor view carries canvas_px = 400 (300 x 400 X-ray)", v["canvas_px"] == 400)

        print("\n[TEST 2] Move one circle")
        r = doc.post(E(sid), {"base_version_no": 1, "decisions": BOTH, "regions": {"pneumonia": [C(250, 250, 30)]}})
        check("200 (a circle change alone is a valid edit)", r.status_code == 200)
        s2 = r.json()["report"]["structured"]
        pn = s2["findings"]["pneumonia"]
        check("pneumonia now has the doctor's circle, marked as the doctor's", pn["regions"] == [{"center_xy": [250, 250], "radius_px": 30, "source": "doctor"}])
        check("region_count / localized / canvas_px follow", pn["region_count"] == 1 and pn["localized"] is True and pn["canvas_px"] == 400 and pn["regions_edited_by_doctor"] is True)
        check("the untouched finding keeps the AI's own record", "regions_edited_by_doctor" not in s2["findings"]["pleural_effusion"] and s2["findings"]["pleural_effusion"]["regions"][0]["center_xy"] == [100, 300])
        check("version 1 still holds the AI's original circle", struct_of(sid, 1)["findings"]["pneumonia"]["regions"][0]["center_xy"] == [150, 120])
        a2 = img_of(files_of(sid, 2)["annotated"])
        check("picture: the circle is at its NEW place (red outline, left edge)", px(a2, 221, 250) == RED)
        check("picture: the OLD place is empty now", px(a2, 111, 120) != RED)
        check("picture: the other finding's circle is still there (cyan)", px(a2, 61, 300) == CYAN)
        check("not stale", s2["images_stale"] is False)
        a = json.loads(sql("SELECT before_json, after_json FROM audit_log WHERE action='doctor_edit_findings' AND target_id=?", (sid,))[0][0])
        b = json.loads(sql("SELECT after_json FROM audit_log WHERE action='doctor_edit_findings' AND target_id=?", (sid,))[0][0])
        check("audit: before circles / after circles / which findings changed", a["circles"]["pneumonia"] == [[150, 120, 40]] and b["circles"]["pneumonia"] == [[250, 250, 30]] and b["circles_changed"] == ["pneumonia"])

        print("\n[TEST 3] Resize")
        sid_r = saved(doc, AN_R)
        r = doc.post(E(sid_r), {"base_version_no": 1, "decisions": BOTH, "regions": {"pneumonia": [C(150, 120, 80)]}})
        a = img_of(files_of(sid_r, 2)["annotated"])
        check("200 and the bigger circle is drawn (left edge at 70, was 110)", r.status_code == 200 and px(a, 71, 120) == RED and px(a, 111, 120) != RED)

        print("\n[TEST 4] Delete a circle (finding stays, just without a circle)")
        sid_d = saved(doc, AN_R)
        r = doc.post(E(sid_d), {"base_version_no": 1, "decisions": BOTH, "regions": {"pneumonia": []}})
        pn = r.json()["report"]["structured"]["findings"]["pneumonia"]
        check("200, region_count 0, localized false, finding still listed", r.status_code == 200 and pn["region_count"] == 0 and pn["localized"] is False and pn["regions"] == [])
        check("report still names Pneumonia", "Pneumonia" in r.json()["report"]["report_text"])
        a = img_of(files_of(sid_d, 2)["annotated"])
        check("picture: no red circle", px(a, 111, 120) != RED)

        print("\n[TEST 5] Add a finding AND give it a circle; add a second circle to another")
        sid_a = saved(doc, AN_R)
        r = doc.post(E(sid_a), {"base_version_no": 1, "decisions": BOTH, "added": ["Cardiomegaly"],
                                "regions": {"cardiomegaly": [C(200, 200, 50)], "pleural_effusion": [C(100, 300, 40), C(300, 330, 25)]}})
        check("200", r.status_code == 200)
        f = r.json()["report"]["structured"]["findings"]
        check("added finding has its circle and the canvas", f["cardiomegaly"]["regions"][0]["center_xy"] == [200, 200] and f["cardiomegaly"]["canvas_px"] == 400)
        check("effusion has two circles now (one unchanged, one new)", f["pleural_effusion"]["region_count"] == 2)
        a = img_of(files_of(sid_a, 2)["annotated"])
        check("picture: cardiomegaly circle drawn in the 3rd colour (yellow)", px(a, 151, 200) == YELLOW)
        check("picture: second effusion circle drawn (cyan)", px(a, 276, 330) == CYAN)

        print("\n[TEST 6] Bad circles are refused and change nothing")
        sid_b = saved(doc, AN_R)
        n0 = n_versions(sid_b)
        base = {"base_version_no": 1, "decisions": BOTH}
        bad = {
            "centre beyond the picture (401)": {"pneumonia": [C(401, 10, 20)]},
            "negative centre": {"pneumonia": [C(-1, 10, 20)]},
            "radius bigger than the picture": {"pneumonia": [C(10, 10, 401)]},
            "radius under 4": {"pneumonia": [C(10, 10, 3)]},
            "6 circles for one finding": {"pneumonia": [C(10 + i, 10, 20) for i in range(6)]},
            "circle for an unknown finding": {"ghost": [C(10, 10, 20)]},
            "centre with 3 numbers": {"pneumonia": [{"center_xy": [1, 2, 3], "radius_px": 10}]},
            "extra field in a circle": {"pneumonia": [{"center_xy": [1, 2], "radius_px": 10, "colour": "red"}]},
        }
        for label_, regs in bad.items():
            check(f"{label_} -> 422", doc.post(E(sid_b), {**base, "regions": regs}).status_code == 422)
        r = doc.post(E(sid_b), {"base_version_no": 1, "decisions": {"pneumonia": "remove", "pleural_effusion": "confirm"}, "regions": {"pneumonia": [C(10, 10, 20)]}})
        check("circles for a finding that is being REMOVED -> 422", r.status_code == 422)
        check("nothing was saved by any of those", n_versions(sid_b) == n0)
        r = doc.post(E(sid_b), {**base, "regions": {"pneumonia": [C(150, 120, 40)]}})
        check("re-sending the SAME circle with nothing else is 'no changes' -> 422", r.status_code == 422)
        r = doc.post(E(sid_b), {**base, "regions": {"pneumonia": [C(150, 120, 40)]}, "note": "Reviewed."})
        check("same circle + a note is fine, and keeps the AI's own record (bbox)", r.status_code == 200 and r.json()["report"]["structured"]["findings"]["pneumonia"]["regions"][0].get("bbox_xyxy") == [120, 90, 180, 150])

        print("\n[TEST 7] Circles carry through later edits")
        r = doc.post(E(sid), {"base_version_no": 2, "decisions": BOTH, "note": "Second look."})
        check("note-only edit works", r.status_code == 200)
        check("version 3 still has the doctor's moved circle", r.json()["report"]["structured"]["findings"]["pneumonia"]["regions"][0]["center_xy"] == [250, 250])
        a3 = img_of(files_of(sid, 3)["annotated"])
        check("version 3 picture shows it too", px(a3, 221, 250) == RED)

        print("\n[TEST 8] Visits saved without AI circles: the doctor can still draw")
        sid_l = saved(doc, ANALYSIS)
        r = doc.post(E(sid_l), {"base_version_no": 1, "decisions": BOTH, "regions": {"pneumonia": [C(150, 120, 40)], "pleural_effusion": [C(100, 300, 40)]}})
        s = r.json()["report"]["structured"]
        check("drawing a circle for EVERY finding makes the picture fresh", r.status_code == 200 and s["images_stale"] is False)
        check("the canvas came from the stored X-ray (400)", s["findings"]["pneumonia"]["canvas_px"] == 400)
        a = img_of(files_of(sid_l, 2)["annotated"])
        check("picture drawn from the doctor's circles", a.size == (780, 400) and px(a, 111, 120) == RED and px(a, 61, 300) == CYAN)
        sid_l2 = saved(doc, ANALYSIS)
        r = doc.post(E(sid_l2), {"base_version_no": 1, "decisions": BOTH, "regions": {"pneumonia": [C(150, 120, 40)]}})
        check("drawing for only one of two -> circles saved, picture honestly marked stale (AI's original kept)", r.status_code == 200 and r.json()["report"]["structured"]["images_stale"] is True
              and r.json()["report"]["structured"]["findings"]["pneumonia"]["regions"][0]["source"] == "doctor")

        print("\n[TEST 9] Never draw on the wrong film")
        bad_an = {**AN_R, "findings": {k: {**v_, "canvas_px": 999} for k, v_ in AN_R["findings"].items()}}
        sid_m = saved(doc, bad_an)
        r = doc.post(E(sid_m), {"base_version_no": 1, "decisions": BOTH, "regions": {"pneumonia": [C(500, 500, 30)]}})
        check("size mismatch -> circles saved, picture NOT redrawn", r.status_code == 200 and r.json()["report"]["structured"]["images_stale"] is True)

        print("\n[TEST 10] Who may do it")
        pat = new_patient("pat@example.com")
        sid_p = saved(pat, AN_R)
        check("patient with a circle edit -> 403", pat.post(E(sid_p), {"base_version_no": 1, "decisions": BOTH, "regions": {"pneumonia": [C(10, 10, 20)]}}).status_code == 403)
        check("another doctor's visit -> 404", doc2.post(E(sid), {"base_version_no": 3, "decisions": BOTH, "regions": {"pneumonia": [C(10, 10, 20)]}}).status_code == 404)
        check("patient's visit untouched", n_versions(sid_p) == 1)

        print("\n[TEST 11] All-or-nothing still holds with circles")
        sid_f = saved(doc, AN_R)
        folder = os.path.join(visit_store.PRIVATE_STORE, sid_f)
        before_files = sorted(os.listdir(folder))
        real_audit = core.audit
        core.audit = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("simulated crash while auditing"))
        try:
            try:
                code_ = doc.post(E(sid_f), {"base_version_no": 1, "decisions": BOTH, "regions": {"pneumonia": [C(250, 250, 30)]}}).status_code
            except Exception:
                code_ = 500
        finally:
            core.audit = real_audit
        check("the request failed", code_ == 500)
        check("no stray files, one version, original circle intact", sorted(os.listdir(folder)) == before_files and n_versions(sid_f) == 1
              and struct_of(sid_f, 1)["findings"]["pneumonia"]["regions"][0]["center_xy"] == [150, 120])

    print("\n" + "=" * 60)
    print(f"{passed}/{passed + failed} circle-editing tests passed.")
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
