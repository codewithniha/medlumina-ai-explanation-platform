"""
test_redraw.py  --  Step 6b-1 tests: the highlighted picture is redrawn from the findings that remain, through the REAL module4_api.py routes, on a THROWAWAY database
and a THROWAWAY image folder (never your real sessions.db or private_store/).

HONEST SCOPE: Gemini / MedGemma / Chroma / OCR / the answer pipeline are replaced
by fakes (same as test_access.py). What is real: the routes, login/CSRF/ownership
guards, input validation, SQLite, and the files written to disk.

Run from backend/module4:   python test_redraw.py
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
    import redraw

    with TestClient(app):
        conn = core.open_db()
        core.create_admin_user(conn, "admin@example.com", PW, "Admin")
        conn.close()
        admin_row = sql("SELECT user_id, role FROM users WHERE role='admin'")[0]
        doc = new_doctor("doc@example.com", "11111-A")
        approve(admin_row, doc)
        E = lambda s: f"/doctor/visits/{s}/edit/findings"
        CYAN, RED = (0, 200, 255), (255, 60, 60)

        print("\n[TEST 1] The AI's circle coordinates are kept when an analysis is saved")
        sid = saved(doc, AN_R)
        v = doc.get(f"/doctor/visits/{sid}").json()
        f = v["report"]["structured"]["findings"]
        check("regions survive the save", f["pneumonia"]["regions"][0]["center_xy"] == [150, 120] and f["pneumonia"]["regions"][0]["radius_px"] == 40)
        check("canvas size survives the save", f["pneumonia"]["canvas_px"] == SIDE)
        check("the drawing control: with both findings the effusion circle IS cyan",
              px(img_of_bytes := Image.open(io.BytesIO(redraw.make_images(XRAY, {k: {**x, "doctor_status": "confirmed"} for k, x in f.items()}, SIDE)["annotated"])).convert("RGB"), 61, 300) == CYAN)

        print("\n[TEST 2] Bad coordinates from the browser are refused")
        base = lambda reg: {**AN_R, "findings": {"pneumonia": {**AN_R["findings"]["pneumonia"], "regions": reg}}}
        for label_, reg in {
            "centre with 3 numbers": [{"center_xy": [1, 2, 3], "radius_px": 10}],
            "radius 0": [{"center_xy": [1, 2], "radius_px": 0}],
            "coordinate 99999": [{"center_xy": [99999, 2], "radius_px": 10}],
            "negative coordinate": [{"center_xy": [-5, 2], "radius_px": 10}],
            "21 regions": [{"center_xy": [1, 2], "radius_px": 5}] * 21,
        }.items():
            sidx, _ = new_visit(doc)
            r = doc.save(sidx, base(reg))
            check(f"{label_} -> 422", r.status_code == 422)

        print("\n[TEST 3] Removing a finding redraws the picture without it")
        r = doc.post(E(sid), {"base_version_no": 1, "decisions": {"pneumonia": "confirm", "pleural_effusion": "remove"}})
        check("200", r.status_code == 200)
        s2 = r.json()["report"]["structured"]
        check("version marked as freshly drawn (images_stale false)", s2["images_stale"] is False)
        f1, f2 = files_of(sid, 1), files_of(sid, 2)
        check("version 2 has its OWN annotated and comparison files", set(f2) == {"annotated", "comparison"} and f2["annotated"] != f1["annotated"] and f2["comparison"] != f1["comparison"])
        check("version 1's picture files are untouched on disk", all(os.path.isfile(os.path.join(visit_store.PRIVATE_STORE, p)) for p in f1.values()))
        a2 = img_of(f2["annotated"])
        check("picture is the square (400) + 380 label margin wide, 400 tall", a2.size == (SIDE + 380, SIDE))
        check("the removed finding's circle is GONE (no cyan where it was)", px(a2, 61, 300) != CYAN)
        check("the remaining finding's circle is there (red outline)", px(a2, 111, 120) == RED)
        c2 = img_of(f2["comparison"])
        check("comparison picture is original + annotated side by side", c2.size == (SIDE + 6 + SIDE + 380, SIDE + 34))
        served = doc.get(f"/visits/{sid}/files/annotated")
        check("what the owner is served as the highlighted picture is the NEW file", served.status_code == 200 and served.content == open(os.path.join(visit_store.PRIVATE_STORE, f2["annotated"]), "rb").read())
        a = sql("SELECT after_json FROM audit_log WHERE action='doctor_edit_findings' AND target_id=?", (sid,))
        check("audit records that the picture was redrawn", json.loads(a[0][0])["picture"] == "redrawn")

        print("\n[TEST 4] A doctor-added finding is drawn (without a circle), earlier circles stay")
        r = doc.post(E(sid), {"base_version_no": 2, "decisions": {"pneumonia": "confirm"}, "added": ["Cardiomegaly"]})
        check("200 and still fresh", r.status_code == 200 and r.json()["report"]["structured"]["images_stale"] is False)
        s3 = r.json()["report"]["structured"]["findings"]
        check("the AI's pneumonia circle data was carried to version 3", s3["pneumonia"]["regions"][0]["center_xy"] == [150, 120])
        a3 = img_of(files_of(sid, 3)["annotated"])
        check("pneumonia circle still drawn on version 3", px(a3, 111, 120) == RED)
        check("added finding has no circle: nothing cyan on the X-ray area", all(px(a3, x, 300) != CYAN for x in range(0, SIDE, 7)))

        print("\n[TEST 5] Removing everything gives a clean picture, not a stale one")
        r = doc.post(E(sid), {"base_version_no": 3, "decisions": {"pneumonia": "remove", "cardiomegaly": "remove"}})
        check("200", r.status_code == 200 and r.json()["report"]["structured"]["images_stale"] is False)
        a4 = img_of(files_of(sid, 4)["annotated"])
        check("no red circle left", px(a4, 111, 120) != RED)

        print("\n[TEST 6] Visits saved WITHOUT coordinates keep the AI picture, honestly flagged")
        sid_l = saved(doc, ANALYSIS)
        r = doc.post(E(sid_l), {"base_version_no": 1, "decisions": {"pneumonia": "confirm", "pleural_effusion": "remove"}})
        check("edit still succeeds", r.status_code == 200)
        check("marked images_stale = true", r.json()["report"]["structured"]["images_stale"] is True)
        check("version 2 points at the SAME picture files as version 1", files_of(sid_l, 2) == files_of(sid_l, 1))
        a = sql("SELECT after_json FROM audit_log WHERE action='doctor_edit_findings' AND target_id=?", (sid_l,))
        check("audit says the AI original was kept", json.loads(a[0][0])["picture"] == "kept_ai_original")

        print("\n[TEST 7] Never draw on the wrong film")
        bad = {**AN_R, "findings": {k: {**v_, "canvas_px": 999} for k, v_ in AN_R["findings"].items()}}
        sid_m = saved(doc, bad)
        r = doc.post(E(sid_m), {"base_version_no": 1, "decisions": {"pneumonia": "confirm", "pleural_effusion": "remove"}})
        check("size mismatch -> edit saved, picture NOT redrawn", r.status_code == 200 and r.json()["report"]["structured"]["images_stale"] is True)
        sid_n = saved(doc, AN_R, xray=real_png(500, 300))
        r = doc.post(E(sid_n), {"base_version_no": 1, "decisions": {"pneumonia": "confirm", "pleural_effusion": "remove"}})
        check("the stored X-ray being a different size than the regions were measured on -> not redrawn", r.json()["report"]["structured"]["images_stale"] is True)

        print("\n[TEST 8] A drawing failure never blocks the doctor's correction")
        sid_f = saved(doc, AN_R)
        real_make = redraw.make_images
        def boom(*a, **k):
            raise RuntimeError("simulated drawing crash")
        redraw.make_images = boom
        try:
            r = doc.post(E(sid_f), {"base_version_no": 1, "decisions": {"pneumonia": "confirm", "pleural_effusion": "remove"}})
        finally:
            redraw.make_images = real_make
        check("edit saved even though drawing crashed", r.status_code == 200 and r.json()["report"]["structured"]["images_stale"] is True)
        r = doc.post(E(sid_f), {"base_version_no": 2, "decisions": {"pneumonia": "confirm"}, "note": "second try"})
        check("the next edit, with drawing working, is fresh again", r.status_code == 200 and r.json()["report"]["structured"]["images_stale"] is False)

        print("\n[TEST 9] All-or-nothing includes the new picture files")
        sid_a = saved(doc, AN_R)
        folder = os.path.join(visit_store.PRIVATE_STORE, sid_a)
        before_files = sorted(os.listdir(folder))
        real_audit = core.audit
        core.audit = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("simulated crash while auditing"))
        try:
            try:
                code_ = doc.post(E(sid_a), {"base_version_no": 1, "decisions": {"pneumonia": "remove", "pleural_effusion": "confirm"}}).status_code
            except Exception:
                code_ = 500
        finally:
            core.audit = real_audit
        check("the request failed", code_ == 500)
        check("no stray picture files were left behind", sorted(os.listdir(folder)) == before_files)
        check("still one version and no extra file rows", sql("SELECT COUNT(*) FROM report_versions WHERE session_id=?", (sid_a,))[0][0] == 1
              and sql("SELECT COUNT(*) FROM visit_files WHERE session_id=?", (sid_a,))[0][0] == 3)

        print("\n[TEST 10] Patients and strangers still cannot trigger any of this")
        pat = new_patient("pat@example.com")
        sid_p = saved(pat, AN_R)
        check("patient edit -> 403", pat.post(E(sid_p), {"base_version_no": 1, "decisions": {"pneumonia": "remove", "pleural_effusion": "remove"}}).status_code == 403)
        check("patient's visit still has exactly one version", sql("SELECT COUNT(*) FROM report_versions WHERE session_id=?", (sid_p,))[0][0] == 1)

    print("\n" + "=" * 60)
    print(f"{passed}/{passed + failed} redraw tests passed.")
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
