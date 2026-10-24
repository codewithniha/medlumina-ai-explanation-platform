"""
test_dicom_keep.py  --  keeping the ORIGINAL DICOM (encrypted), downloading it, de-identified export,
and window/level re-rendering, through the REAL routes on a THROWAWAY database and folder.

HONEST SCOPE: DICOMs are synthetic (built here). Crypto is the real AES-GCM code path. The AI model
is not involved. Run from backend/module4:   python test_dicom_keep.py
"""

import base64
import io
import json
import os
import sqlite3
import struct
import sys
import tempfile
import time
import types
import zlib

_fd, TMP_DB = tempfile.mkstemp(suffix=".db")
os.close(_fd)
TMP_STORE = tempfile.mkdtemp(prefix="ml_store_")
os.environ["SESSION_DB_PATH"] = TMP_DB
os.environ["PRIVATE_STORE_DIR"] = TMP_STORE
os.environ["COOKIE_SECURE"] = "false"
os.environ.pop("MEDLUMINA_DATA_KEY", None)
os.environ.pop("MEDLUMINA_REQUIRE_KEY_ENV", None)


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

import numpy as np  # noqa: E402
import pydicom  # noqa: E402
from PIL import Image  # noqa: E402
from pydicom.dataset import FileDataset, FileMetaDataset  # noqa: E402
from pydicom.uid import ExplicitVRLittleEndian, SecondaryCaptureImageStorage, generate_uid  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import auth_core as core  # noqa: E402
import dicom_store  # noqa: E402
import module4_api  # noqa: E402
import visit_store  # noqa: E402
from dicom_convert import DicomError  # noqa: E402
from dicom_deid import deidentify  # noqa: E402

PW = "correct-horse-battery"
PHI = ["DOE^SECRETNAME", "MRN-424242", "19800101", "SECRET HOSPITAL", "DR^WATSON", "ACC-777", "12 Secret Street", "PRIVSECRET", "OTHER-ID-9"]
passed = failed = 0


def check(label, condition):
    global passed, failed
    print(f"  [{'PASS' if condition else 'FAIL'}] {label}")
    if condition:
        passed += 1
    else:
        failed += 1


def raises(fn, exc=Exception, text=None):
    try:
        fn()
    except exc as e:
        return text is None or text.lower() in str(e).lower()
    return False


def make(arr, *, photometric="MONOCHROME2", burned=None, window=(2048, 4096)):
    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = SecondaryCaptureImageStorage
    meta.MediaStorageSOPInstanceUID = generate_uid()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds = FileDataset(None, {}, file_meta=meta, preamble=b"\0" * 128)
    ds.PatientName, ds.PatientID, ds.PatientBirthDate = PHI[0], PHI[1], PHI[2]
    ds.InstitutionName, ds.ReferringPhysicianName, ds.AccessionNumber = PHI[3], PHI[4], PHI[5]
    ds.PatientAddress, ds.OtherPatientIDs = PHI[6], PHI[8]
    ds.add_new((0x0009, 0x0010), "LO", "PRIVATE CREATOR")
    ds.add_new((0x0009, 0x1001), "LO", PHI[7])
    ds.StudyDate = "20260101"
    ds.Modality = "DX"
    ds.SOPClassUID, ds.SOPInstanceUID = SecondaryCaptureImageStorage, generate_uid()
    ds.StudyInstanceUID, ds.SeriesInstanceUID = generate_uid(), generate_uid()
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = photometric
    ds.Rows, ds.Columns = arr.shape
    ds.BitsAllocated, ds.BitsStored, ds.HighBit, ds.PixelRepresentation = 16, 12, 11, 0
    ds.WindowCenter, ds.WindowWidth = window
    ds.PixelSpacing = [0.143, 0.143]
    ds.ViewPosition = "PA"
    if burned:
        ds.BurnedInAnnotation = burned
    ds.PixelData = arr.tobytes()
    return ds


def to_bytes(ds):
    b = io.BytesIO()
    ds.save_as(b)
    return b.getvalue()


def gradient(h=64, w=128):
    return np.tile(np.linspace(0, 4095, w).astype(np.uint16), (h, 1))


def png_px(b):
    return np.array(Image.open(io.BytesIO(b)))


def png_bytes():
    def chunk(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"\x00\x01\x00\x00")) + chunk(b"IEND", b""))


ANALYSIS = {"mode": "image_only", "diseases_visualized": ["pneumonia"], "diseases_qualified_not_shown": [],
            "findings": {"pneumonia": {"positive_prob": 0.9, "method": "model", "region_count": 1, "localized": True}},
            "report_text": "IMPRESSION: x"}

app = module4_api.app
_life = TestClient(app)
_life.__enter__()   # start-up creates all tables incl. dicom_originals


class Person:
    def __init__(self, email):
        self.c = TestClient(app)
        r = self.c.post("/auth/register/patient", json={"email": email, "password": PW})
        assert r.status_code == 201, r.text
        self.h = {"X-CSRF-Token": r.json()["csrf_token"]}
        self.user_id = r.json()["user"]["user_id"]

    def convert(self, data, name="a.dcm"):
        return self.c.post("/dicom/convert", files={"file": (name, data, "application/dicom")}, headers=self.h)

    def visit(self):
        r = self.c.post("/session/start", json={"doctor_report": "x", "xray_findings": {"a": 1}}, headers=self.h)
        assert r.status_code == 200, r.text
        return r.json()["session_id"], r.json()["patient_code"]

    def save(self, sid, token=None):
        data = {"analysis_json": json.dumps(ANALYSIS)}
        if token:
            data["dicom_token"] = token
        return self.c.post(f"/visits/{sid}/analysis", data=data, files={"xray": ("x.png", png_bytes(), "image/png")}, headers=self.h)

    def get(self, path):
        return self.c.get(path)


def sql(q, p=()):
    c = sqlite3.connect(TMP_DB)
    c.row_factory = sqlite3.Row
    try:
        return c.execute(q, p).fetchall()
    finally:
        c.close()


# ─────────────────────────────────────────────────────────────────────────────
print("\n[TEST 1] Encryption primitives")
blob = dicom_store.encrypt(b"hello dicom", "aad-1")
check("round trip returns the original bytes", dicom_store.decrypt(blob, "aad-1") == b"hello dicom")
check("ciphertext does not contain the plaintext", b"hello dicom" not in blob)
check("two encryptions of the same data differ (fresh nonce)", dicom_store.encrypt(b"hello dicom", "aad-1") != blob)
check("wrong context (AAD) -> refused", raises(lambda: dicom_store.decrypt(blob, "aad-2"), dicom_store.DicomStoreError))
flipped = bytearray(blob)
flipped[-3] ^= 1
check("one flipped byte -> refused", raises(lambda: dicom_store.decrypt(bytes(flipped), "aad-1"), dicom_store.DicomStoreError))
check("not our format -> refused", raises(lambda: dicom_store.decrypt(b"x" * 100, "aad-1"), dicom_store.DicomStoreError))

print("\n[TEST 2] The key")
check("a development key file was created in the (private) store", os.path.exists(os.path.join(TMP_STORE, ".data_key")))
k1 = dicom_store._load_key()
dicom_store.reset_key_cache()
check("the same key is loaded again from the file", dicom_store._load_key() == k1)
good = base64.b64encode(os.urandom(32)).decode()
os.environ["MEDLUMINA_DATA_KEY"] = good
dicom_store.reset_key_cache()
check("MEDLUMINA_DATA_KEY wins over the file", dicom_store._load_key() == base64.b64decode(good))
check("data encrypted under another key will not open", raises(lambda: dicom_store.decrypt(blob, "aad-1"), dicom_store.DicomStoreError))
os.environ["MEDLUMINA_DATA_KEY"] = "not-base64!!"
dicom_store.reset_key_cache()
check("invalid base64 key -> clear error", raises(dicom_store._load_key, dicom_store.DicomStoreError, "base64"))
os.environ["MEDLUMINA_DATA_KEY"] = base64.b64encode(b"short").decode()
dicom_store.reset_key_cache()
check("wrong-length key -> clear error", raises(dicom_store._load_key, dicom_store.DicomStoreError, "32 bytes"))
del os.environ["MEDLUMINA_DATA_KEY"]
os.environ["MEDLUMINA_REQUIRE_KEY_ENV"] = "1"
dicom_store.reset_key_cache()
check("REQUIRE_KEY_ENV forbids the key-file fallback", raises(dicom_store._load_key, dicom_store.DicomStoreError, "forbids"))
del os.environ["MEDLUMINA_REQUIRE_KEY_ENV"]
dicom_store.reset_key_cache()
os.environ["MEDLUMINA_DATA_KEY"] = base64.b64encode(k1).decode()   # continue with the dev key via env
dicom_store.reset_key_cache()

# ─────────────────────────────────────────────────────────────────────────────
print("\n[TEST 3] Convert -> staged (encrypted) -> saved with the visit")
orig = to_bytes(make(gradient()))
pat = Person("keep1@example.com")
r = pat.convert(orig)
check("convert returns a dicom_token", r.status_code == 200 and len(r.json().get("dicom_token") or "") == 32)
token = r.json()["dicom_token"]
check("convert response has no patient details", not any(p in r.text for p in PHI))
staged = [os.path.join(d, f) for d, _, fs in os.walk(TMP_STORE) for f in fs if "_staging" in d]
check("the staged copy on disk is ciphertext (no DICM header, no patient strings)",
      staged and all(b"DICM" not in open(f, "rb").read() and not any(p.encode() in open(f, "rb").read() for p in PHI)
                     for f in staged if f.endswith(".enc")))
sid, code = pat.visit()
r = pat.save(sid, token)
check("saving the visit with the token -> 201, dicom_retained true", r.status_code == 201 and r.json()["dicom_retained"] is True)
rows = sql("SELECT * FROM dicom_originals WHERE session_id=?", (sid,))
check("one dicom_originals row", len(rows) == 1)
row = rows[0]
check("row holds technical facts only (modality DX, 128x64, spacing 0.143)",
      row["modality"] == "DX" and row["columns_px"] == 128 and row["rows_px"] == 64 and abs(row["pixel_spacing_row_mm"] - 0.143) < 1e-6)
stored_path = os.path.join(TMP_STORE, row["relative_path"])
raw = open(stored_path, "rb").read()
check("kept file on disk is ciphertext: no DICM header, no patient strings", b"DICM" not in raw and not any(p.encode() in raw for p in PHI))
dbraw = open(TMP_DB, "rb").read()
check("database file contains none of the patient strings", not any(p.encode() in dbraw for p in PHI))
check("staging copy was removed after it was claimed", not [f for f in staged if os.path.exists(f)])
check("fingerprint matches the original bytes", row["sha256"] == __import__("hashlib").sha256(orig).hexdigest())

print("\n[TEST 4] Token rules")
r2 = pat.convert(orig)
tok2 = r2.json()["dicom_token"]
sid2, _ = pat.visit()
other = Person("keep2@example.com")
sid_o, _ = other.visit()
r = other.save(sid_o, tok2)
check("another user's token: visit still saved, original NOT kept, clear message",
      r.status_code == 201 and r.json()["dicom_retained"] is False and "expired or was not found" in r.json()["dicom_message"])
r = pat.save(sid2, "../../etc/passwd")
check("malformed token: visit saved, original not kept, message", r.status_code == 201 and r.json()["dicom_retained"] is False)
sid3, _ = pat.visit()
r = pat.save(sid3, tok2)
check("a token still works for its own user (and only once)", r.status_code == 201 and r.json()["dicom_retained"] is True)
sid4, _ = pat.visit()
r = pat.save(sid4, tok2)
check("reusing a claimed token -> not kept", r.json()["dicom_retained"] is False)
sid5, _ = pat.visit()
old_tok = pat.convert(orig).json()["dicom_token"]
for d, _, fs in os.walk(os.path.join(TMP_STORE, "_staging")):
    for f in fs:
        if f.startswith(old_tok):
            os.utime(os.path.join(d, f), (time.time() - 48 * 3600,) * 2)
dicom_store.purge_expired_staging()
check("staged files older than 24 h are purged", pat.save(sid5, old_tok).json()["dicom_retained"] is False)
r = pat.save(sid, None)
check("saving the same visit twice is still refused (409)", r.status_code == 409)

# ─────────────────────────────────────────────────────────────────────────────
print("\n[TEST 5] Download the original")
r = pat.get(f"/visits/{sid}/dicom/original")
check("owner gets the original, byte-for-byte identical", r.status_code == 200 and r.content == orig)
check("served as an attachment, never cached", "attachment" in r.headers["content-disposition"] and r.headers["cache-control"] == "private, no-store")
check("filename does not contain patient details", not any(p in r.headers["content-disposition"] for p in PHI))
a = sql("SELECT actor_user_id, actor_role FROM audit_log WHERE action='dicom_original_download' AND target_id=?", (sid,))
check("the download is audited with who", len(a) == 1 and a[0]["actor_user_id"] == pat.user_id)
check("another patient -> 404", other.get(f"/visits/{sid}/dicom/original").status_code == 404)
check("not logged in -> 401", TestClient(app).get(f"/visits/{sid}/dicom/original").status_code == 401)
check("a visit with no kept DICOM -> 404", pat.get(f"/visits/{sid2}/dicom/original").status_code == 404)
check("a non-UUID id -> 404", pat.get("/visits/not-a-uuid/dicom/original").status_code == 404)
v = pat.get(f"/visits/{sid}").json()
check("visit view shows technical DICOM facts", v["dicom"]["modality"] == "DX" and v["dicom"]["frames"] == 1)
check("visit view never shows patient details", not any(p in json.dumps(v) for p in PHI))
check("a visit without DICOM shows dicom = null", pat.get(f"/visits/{sid2}").json()["dicom"] is None)

print("\n[TEST 6] Tampering and swapping are detected")
other_sid_dir = os.path.join(TMP_STORE, sid3)
copy_rel = sql("SELECT relative_path FROM dicom_originals WHERE session_id=?", (sid3,))[0]["relative_path"]
good_blob = open(stored_path, "rb").read()
bad = bytearray(good_blob)
bad[40] ^= 0xFF
open(stored_path, "wb").write(bytes(bad))
r = pat.get(f"/visits/{sid}/dicom/original")
check("a flipped byte on disk -> 500 with a safe message", r.status_code == 500 and "verified" in r.json()["detail"])
check("... and an integrity-failure audit row exists", len(sql("SELECT 1 FROM audit_log WHERE action='dicom_integrity_failure' AND target_id=?", (sid,))) == 1)
open(stored_path, "wb").write(good_blob)
check("restoring the file makes it work again", pat.get(f"/visits/{sid}/dicom/original").status_code == 200)
open(os.path.join(TMP_STORE, copy_rel), "wb").write(good_blob)   # visit 1's file placed in visit 3's slot
check("a file moved into ANOTHER visit's slot will not open", pat.get(f"/visits/{sid3}/dicom/original").status_code == 500)

# ─────────────────────────────────────────────────────────────────────────────
print("\n[TEST 7] De-identified export")
r = pat.get(f"/visits/{sid}/dicom/deidentified")
check("export works (200)", r.status_code == 200)
out = r.content
check("NONE of the planted patient strings survive anywhere in the bytes", not any(p.encode() in out for p in PHI))
check("no study date either", b"20260101" not in out)
ds = pydicom.dcmread(io.BytesIO(out))
check("it is a valid DICOM file", ds.Rows == 64 and ds.Columns == 128 and ds.Modality == "DX")
check("DeidentificationMethod fits DICOM's 64-character limit", len(str(ds.DeidentificationMethod)) <= 64)
check("PatientName ANONYMOUS, PatientID is the record's PT- code, identity-removed flag set",
      str(ds.PatientName) == "ANONYMOUS" and ds.PatientID == code and ds.PatientIdentityRemoved == "YES")
check("technical tags kept (pixel spacing, view position, window)", list(map(float, ds.PixelSpacing)) == [0.143, 0.143] and ds.ViewPosition == "PA" and float(ds.WindowWidth) == 4096)
check("picture is byte-identical", np.array_equal(ds.pixel_array, pydicom.dcmread(io.BytesIO(orig)).pixel_array))
od = pydicom.dcmread(io.BytesIO(orig))
check("all three UIDs replaced", ds.StudyInstanceUID != od.StudyInstanceUID and ds.SeriesInstanceUID != od.SeriesInstanceUID and ds.SOPInstanceUID != od.SOPInstanceUID)
check("private tags gone", not any(e.tag.is_private for e in ds))
again = pydicom.dcmread(io.BytesIO(pat.get(f"/visits/{sid}/dicom/deidentified").content))
check("exporting twice gives the same UIDs (repeatable)", again.StudyInstanceUID == ds.StudyInstanceUID and again.SOPInstanceUID == ds.SOPInstanceUID)
check("the export is audited", len(sql("SELECT 1 FROM audit_log WHERE action='dicom_deidentified_export' AND target_id=?", (sid,))) == 2)
check("another patient cannot export it", other.get(f"/visits/{sid}/dicom/deidentified").status_code == 404)
check("both files (original and de-identified) decode to the same PNG picture",
      np.array_equal(png_px(__import__("dicom_convert").convert_dicom(orig)[0]), png_px(__import__("dicom_convert").convert_dicom(out)[0])))

# compressed, and burned-in
for nm, uid in (("RLE", pydicom.uid.RLELossless), ("JPEG 2000", pydicom.uid.JPEG2000Lossless)):
    try:
        c = make(gradient())
        c.compress(uid)
        cb = to_bytes(c)
    except Exception as e:
        check(f"{nm}: could not BUILD the test file here ({type(e).__name__}) -- skipped, NOT tested", True)
        continue
    o2 = deidentify(cb, sid, "PT-TEST01")
    d2 = pydicom.dcmread(io.BytesIO(o2))
    check(f"{nm}-compressed original: de-identified copy keeps compression and picture",
          d2.file_meta.TransferSyntaxUID == uid and np.array_equal(d2.pixel_array, gradient()) and not any(p.encode() in o2 for p in PHI))
check("burned-in patient text -> export refused (not falsely labelled)", raises(lambda: deidentify(to_bytes(make(gradient(), burned="YES")), sid, "PT-X"), DicomError, "burned"))

# ─────────────────────────────────────────────────────────────────────────────
print("\n[TEST 8] Window / level re-render")
def render(**q):
    return pat.c.get(f"/visits/{sid}/dicom/render", params=q)
wide = render(center=2048, width=4096)
narrow = render(center=1000, width=200)
check("render works and returns a PNG", wide.status_code == 200 and wide.content[:8] == b"\x89PNG\r\n\x1a\n")
pw, pn = png_px(wide.content), png_px(narrow.content)
check("a different window gives a different picture", not np.array_equal(pw, pn))
check("narrow window clips to black/white at the ends", pn[0, 0] == 0 and pn[0, -1] == 255 and (pn.astype(int).max() - pn.astype(int).min()) == 255)
check("invert=true flips it", png_px(render(center=2048, width=4096, invert=True).content)[0, 0] > 245)
check("width 0 -> 422", render(center=100, width=0).status_code == 422)
check("absurd values -> 422", render(center=1e9, width=10).status_code == 422)
check("non-numeric -> 422", render(center="abc", width=10).status_code == 422)
check("render of someone else's visit -> 404", other.c.get(f"/visits/{sid}/dicom/render", params={"center": 1, "width": 10}).status_code == 404)
check("render without login -> 401", TestClient(app).get(f"/visits/{sid}/dicom/render", params={"center": 1, "width": 10}).status_code == 401)

# ─────────────────────────────────────────────────────────────────────────────
print("\n[TEST 9] Doctors")
dc = TestClient(app)
rr = dc.post("/auth/register/doctor", json={"email": "dd@example.com", "password": PW, "full_name": "Dr Test Person", "father_name": "F", "pmdc_number": "2222-P"})
dh = {"X-CSRF-Token": rr.json()["csrf_token"]}
check("pending doctor cannot convert", dc.post("/dicom/convert", files={"file": ("a.dcm", orig, "application/dicom")}, headers=dh).status_code == 403)
check("pending doctor cannot download", dc.get(f"/visits/{sid}/dicom/original").status_code == 403)

print("\n" + "=" * 60)
print(f"{passed}/{passed + failed} DICOM-keeping tests passed.")
print("=" * 60)
sys.exit(0 if failed == 0 else 1)
