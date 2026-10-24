"""
test_reindex.py  --  Step 7 tests: after a doctor saves, the visit's question-answering index holds ONLY the final
report version. Uses a REAL ChromaDB (in a throwaway folder) through the REAL session_indexer.py and rag_reindex.py,
and the REAL module4_api.py routes, on a THROWAWAY database.

HONEST SCOPE: the text-embedding MODEL is replaced by a simple word-hashing function (the real multilingual-e5 model
is a big download, so it is not used here), and Gemini / MedGemma are faked. So these tests prove WHAT is stored in
and removed from the index and what a search can find; they do not prove how well the real model ranks answers.

Run from backend/module4:   python test_reindex.py     (needs chromadb installed, as for the real app)
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
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")


def _fake(name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod


_fake("llm_client", MEDGEMMA_API_URL="")
_fake("ocr", transcribe_handwritten_report=lambda *a, **k: "t", transcribe_report_from_pdf=lambda *a, **k: "t")
import hashlib as _h
import re as _re
import chromadb
from chromadb import EmbeddingFunction

def _vec(text):
    v = [0.0] * 512
    for tok in _re.findall(r"[a-z]+", text.lower()):
        v[int(_h.md5(tok.encode()).hexdigest(), 16) % 512] += 1.0
    n = sum(x * x for x in v) ** 0.5 or 1.0
    return [x / n for x in v]

class _FakeEF(EmbeddingFunction):
    def __call__(self, input):
        return [_vec(t) for t in input]

TMP_CHROMA = tempfile.mkdtemp(prefix="ml_chroma_")
_fake("kb_indexer", ensure_kb_indexed=lambda: None,
      get_chroma_client=lambda: chromadb.PersistentClient(path=TMP_CHROMA, settings=chromadb.Settings(anonymized_telemetry=False)), _embedding_fn=_FakeEF())
_fake("embedding_config", embed_passage_texts=lambda texts: [_vec(t) for t in texts])
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
    import rag_reindex
    import session_indexer
    kb = sys.modules["kb_indexer"]

    def col(sid):
        return session_indexer.get_session_collection(sid)

    def dump(sid):
        c = col(sid)
        r = c.get()
        return list(zip(r["ids"], r["documents"], r["metadatas"]))

    def texts(sid):
        return [d for _, d, _ in dump(sid)]

    def conds(sid):
        return sorted(m["condition"] for _, _, m in dump(sid) if m.get("source") == "xray_finding")

    AI_REPORT = ANALYSIS_TEXT = "FINDINGS:\nRight lower zone opacity.\n\nIMPRESSION:\nLikely pneumonia.\n"

    def started(person):
        r = person.post("/session/start", {"doctor_report": AI_REPORT, "xray_findings": {"primary_finding": "Pneumonia"},
                                           "prescribed_medicines": ["Amoxicillin 500mg"], "symptoms": "cough for two weeks"})
        assert r.status_code == 200, r.text
        sid = r.json()["session_id"]
        rr = person.save(sid, AN_R, files={"xray": ("x.png", XRAY, "image/png"), "annotated": ("a.png", png(2), "image/png"),
                                           "comparison": ("c.jpg", JPEG, "image/jpeg")})
        assert rr.status_code in (200, 201), rr.text
        return sid

    with TestClient(app):
        conn = core.open_db()
        core.create_admin_user(conn, "admin@example.com", PW, "Admin")
        conn.close()
        admin_row = sql("SELECT user_id, role FROM users WHERE role='admin'")[0]
        doc = new_doctor("doc@example.com", "11111-A")
        approve(admin_row, doc)
        E = lambda s: f"/doctor/visits/{s}/edit/findings"
        BOTH = {"pneumonia": "confirm", "pleural_effusion": "confirm"}

        print("\n[TEST 1] Before any edit: the index holds the AI's report")
        sid = started(doc)
        before = texts(sid)
        check("the AI report text is in the index", any("Likely pneumonia" in t for t in before))
        check("medicine and symptoms are in the index", any("Amoxicillin" in t for t in before) and any("cough" in t for t in before))

        print("\n[TEST 2] Doctor removes Pneumonia, adds Cardiomegaly, writes a note")
        r = doc.post(E(sid), {"base_version_no": 1, "decisions": {"pneumonia": "remove", "pleural_effusion": "confirm"},
                              "added": ["Cardiomegaly"], "note": "Heart size is borderline."})
        check("200 and the index was updated (index_ok)", r.status_code == 200 and r.json().get("index_ok") is True)
        t2 = texts(sid)
        check("the OLD report text is gone from the index", not any("Right lower zone" in t or "Likely pneumonia" in t for t in t2))
        check("no chunk is left from the old index (all report/finding chunks are version 2)",
              all(m.get("version_no") == 2 for _, _, m in dump(sid) if m.get("source") in ("doctor_report", "xray_finding")))
        check("the new findings are there (effusion kept, cardiomegaly added)", any("Pleural effusion: AI probability 70.0%" in t for t in t2) and any("Cardiomegaly: added by the reviewing doctor" in t for t in t2))
        check("the doctor's note is there", any("Heart size is borderline" in t for t in t2))
        check("the removed finding is recorded as REMOVED, not as present", any("removed these findings" in t and "Pneumonia" in t for t in t2)
              and not any(t.startswith("X-ray finding -- Pneumonia") for t in t2))
        check("conditions in the index are exactly the final findings (no 'primary_finding', no Pneumonia)", conds(sid) == ["Cardiomegaly", "Pleural effusion"])
        check("medicine and symptoms were NOT touched", any("Amoxicillin" in t for t in t2) and any("cough" in t for t in t2))

        print("\n[TEST 3] What a search can find")
        res = col(sid).query(query_texts=["Does the patient have pneumonia opacity?"], n_results=len(t2))
        found = res["documents"][0]
        check("a search for pneumonia can no longer return the old report", not any("Likely pneumonia" in d or "Right lower zone" in d for d in found))
        res = col(sid).query(query_texts=["heart size borderline"], n_results=1)
        check("a search for the doctor's note finds the note", "Heart size is borderline" in res["documents"][0][0])

        print("\n[TEST 4] The old version is still in the database history (only the index forgets it)")
        v1 = sql("SELECT report_text FROM report_versions WHERE session_id=? AND version_no=1", (sid,))[0][0]
        check("version 1 text is intact", "Likely pneumonia" in v1)

        print("\n[TEST 5] A second edit replaces version 2's chunks")
        r = doc.post(E(sid), {"base_version_no": 2, "decisions": {"pleural_effusion": "remove", "cardiomegaly": "confirm"}})
        check("200 and index_ok", r.status_code == 200 and r.json().get("index_ok") is True)
        d3 = dump(sid)
        check("only version 3 chunks remain for report and findings", all(m.get("version_no") == 3 for _, _, m in d3 if m.get("source") in ("doctor_report", "xray_finding")))
        check("conditions are now just Cardiomegaly", conds(sid) == ["Cardiomegaly"])
        check("version 2's note is gone", not any("Heart size is borderline" in t for _, t, _ in d3))

        print("\n[TEST 6] Removing every finding")
        sid_e = started(doc)
        r = doc.post(E(sid_e), {"base_version_no": 1, "decisions": {"pneumonia": "remove", "pleural_effusion": "remove"}})
        check("200 and index_ok", r.status_code == 200 and r.json().get("index_ok") is True)
        te = texts(sid_e)
        check("the index says no abnormal findings, with no finding chunks", any("No abnormal findings" in t for t in te) and conds(sid_e) == [])

        print("\n[TEST 7] Other visits and the audit trail")
        sid_o = started(doc)
        other_before = sorted(dump(sid_o))
        doc.post(E(sid), {"base_version_no": 3, "decisions": {"cardiomegaly": "confirm"}, "note": "Follow-up advised."})
        check("a different visit's index is untouched", sorted(dump(sid_o)) == other_before)
        rows = sql("SELECT after_json FROM audit_log WHERE action='rag_reindex' AND target_id=? ORDER BY rowid", (sid,))
        check("every successful edit has a rag_reindex audit entry (3 edits)", len(rows) == 3 and json.loads(rows[-1][0])["version_no"] == 4)

        print("\n[TEST 8] Calling it again changes nothing (safe to repeat)")
        conn = core.open_db()
        try:
            a = sorted(dump(sid))
            info = rag_reindex.reindex_final_version(conn, sid)
            b = sorted(dump(sid))
        finally:
            conn.close()
        check("same chunks after a repeat; nothing left to remove", a == b and info["removed_old"] == 0)

        print("\n[TEST 9] The vector database is down: the edit still succeeds, honestly reported, and heals later")
        good_client = kb.get_chroma_client
        def boom():
            raise RuntimeError("chroma is down")
        kb.get_chroma_client = boom
        try:
            r = doc.post(E(sid), {"base_version_no": 4, "decisions": {"cardiomegaly": "confirm"}, "note": "Second follow-up."})
        finally:
            kb.get_chroma_client = good_client
        check("200 (the edit is saved) but index_ok is False", r.status_code == 200 and r.json().get("index_ok") is False)
        check("version 5 is saved in the database", sql("SELECT MAX(version_no) FROM report_versions WHERE session_id=?", (sid,))[0][0] == 5)
        check("failure is on the audit trail (no error text, only its type)", sql("SELECT COUNT(*) FROM audit_log WHERE action='rag_reindex_failed' AND target_id=?", (sid,))[0][0] == 1)
        check("the index still holds the previous version (not empty, not half-written)", all(m.get("version_no") == 4 for _, _, m in dump(sid) if m.get("source") in ("doctor_report", "xray_finding")))
        r = doc.post(E(sid), {"base_version_no": 5, "decisions": {"cardiomegaly": "confirm"}, "note": "Third follow-up."})
        check("the next edit heals it: index now holds version 6 only", r.json().get("index_ok") is True
              and all(m.get("version_no") == 6 for _, _, m in dump(sid) if m.get("source") in ("doctor_report", "xray_finding")))

        print("\n[TEST 10] Embedding fails: nothing is deleted")
        emb = sys.modules["embedding_config"].embed_passage_texts
        def bad(texts):
            raise RuntimeError("embedding model not loaded")
        sys.modules["embedding_config"].embed_passage_texts = bad
        n_before = len(dump(sid))
        try:
            r = doc.post(E(sid), {"base_version_no": 6, "decisions": {"cardiomegaly": "confirm"}, "note": "Fourth."})
        finally:
            sys.modules["embedding_config"].embed_passage_texts = emb
        check("edit saved, index_ok False, and the old chunks are all still there", r.status_code == 200 and r.json().get("index_ok") is False and len(dump(sid)) == n_before)

        print("\n[TEST 11] Who may do it")
        pat = new_patient("pat@example.com")
        sid_p = started(pat)
        snap = sorted(dump(sid_p))
        r = pat.post(E(sid_p), {"base_version_no": 1, "decisions": BOTH, "note": "I am a patient"})
        check("patient edit -> 403 and the index is untouched", r.status_code == 403 and sorted(dump(sid_p)) == snap)

    print("\n" + "=" * 60)
    print(f"{passed}/{passed + failed} re-index tests passed.")
    print("=" * 60)
    return failed == 0


if __name__ == "__main__":
    ok = run()
    shutil.rmtree(TMP_STORE, ignore_errors=True)
    shutil.rmtree(TMP_CHROMA, ignore_errors=True)
    try:
        os.remove(TMP_DB)
    except OSError:
        pass
    sys.exit(0 if ok else 1)
