"""
test_dicom.py  --  DICOM support tests: dicom_convert.py (the converter) and POST /dicom/convert
(the route), on a THROWAWAY database and image folder.

HONEST SCOPE: every DICOM here is SYNTHETIC (built by this script with pydicom: a smooth
gradient, no real patient). That proves the maths (window, rescale, inversion, padding,
downscale), the compressed-image path, privacy stripping and the route guards. It does NOT
prove how the converter treats every real scanner's files; try a few real exports too.
The AI model, Gemini, Chroma etc. are not involved.

Run from backend/module4:   python test_dicom.py
"""

import base64
import io
import os
import sys
import tempfile
import types

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

import numpy as np  # noqa: E402
import pydicom  # noqa: E402
from PIL import Image  # noqa: E402
from pydicom.dataset import FileDataset, FileMetaDataset  # noqa: E402
from pydicom.uid import ExplicitVRLittleEndian, SecondaryCaptureImageStorage, generate_uid  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
import sqlite3  # noqa: E402

import auth_core as core  # noqa: E402
import dicom_api  # noqa: E402
import module4_api  # noqa: E402
from dicom_convert import DicomError, convert_dicom, looks_like_dicom  # noqa: E402

PW = "correct-horse-battery"
NAME, PID = "DOE^JOHNATHAN", "MRN-998877"
passed = failed = 0


def check(label, condition):
    global passed, failed
    print(f"  [{'PASS' if condition else 'FAIL'}] {label}")
    if condition:
        passed += 1
    else:
        failed += 1


def make(arr, *, photometric="MONOCHROME2", modality="DX", bits=16, signed=False, spp=1,
         window=None, rescale=None, extra=None, frames=None):
    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = SecondaryCaptureImageStorage
    meta.MediaStorageSOPInstanceUID = generate_uid()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds = FileDataset(None, {}, file_meta=meta, preamble=b"\0" * 128)
    ds.PatientName, ds.PatientID, ds.PatientBirthDate = NAME, PID, "19800101"
    ds.InstitutionName = "SECRET HOSPITAL"
    if modality is not None:
        ds.Modality = modality
    ds.SOPClassUID, ds.SOPInstanceUID = SecondaryCaptureImageStorage, generate_uid()
    ds.SamplesPerPixel = spp
    ds.PhotometricInterpretation = photometric
    h, w = arr.shape[-3:-1] if spp == 3 else arr.shape[-2:]
    ds.Rows, ds.Columns = int(h), int(w)
    ds.BitsAllocated = bits
    ds.BitsStored = bits if bits == 8 else 12
    ds.HighBit = ds.BitsStored - 1
    ds.PixelRepresentation = 1 if signed else 0
    if spp == 3:
        ds.PlanarConfiguration = 0
    if frames:
        ds.NumberOfFrames = frames
    if window:
        ds.WindowCenter, ds.WindowWidth = window
    if rescale:
        ds.RescaleSlope, ds.RescaleIntercept = rescale
    for k, v in (extra or {}).items():
        setattr(ds, k, v)
    ds.PixelData = arr.tobytes()
    return ds


def to_bytes(ds):
    buf = io.BytesIO()
    ds.save_as(buf)
    return buf.getvalue()


def png_pixels(png):
    return np.array(Image.open(io.BytesIO(png)))


def gradient(h=64, w=128, hi=4095, dtype=np.uint16):
    return np.tile(np.linspace(0, hi, w).astype(dtype), (h, 1))


def raises(fn, text):
    try:
        fn()
    except DicomError as e:
        return text.lower() in str(e).lower()
    except Exception as e:  # a library error leaking out would be a bug
        print("     leaked:", type(e).__name__, e)
        return False
    return False


# ─────────────────────────────────────────────────────────────────────────────
print("\n[TEST 1] Grey-level maths")
png, info = convert_dicom(to_bytes(make(gradient(), window=(2048, 4096))))
px = png_pixels(png)
check("output is an 8-bit greyscale PNG of the same size", px.ndim == 2 and px.shape == (64, 128) and px.dtype == np.uint8)
check("gradient stays left-dark -> right-bright with the file's own window", px[0, 0] < 10 and px[0, -1] > 245 and np.all(np.diff(px[0].astype(int)) >= 0))
check("info says the window came from the file", info["window"] == "from_file")

png, info = convert_dicom(to_bytes(make(gradient(), window=(2048, 4096), photometric="MONOCHROME1")))
px = png_pixels(png)
check("MONOCHROME1 is inverted (left bright, right dark)", px[0, 0] > 245 and px[0, -1] < 10 and info.get("inverted") is True)

png, info = convert_dicom(to_bytes(make(gradient(hi=1000), window=(0, 2000), rescale=(2, -1000))))
px = png_pixels(png)
check("RescaleSlope/Intercept applied (stored 0 -> black, stored 1000 -> white)", px[0, 0] <= 3 and px[0, -1] >= 252)

png, info = convert_dicom(to_bytes(make(gradient(hi=4095, dtype=np.uint16), window=(1000, 400))))
px = png_pixels(png)
check("a narrow window clips: below -> black, above -> white", px[0, 0] == 0 and px[0, -1] == 255)

arr = gradient(hi=2000).astype(np.int16) - 1000
png, info = convert_dicom(to_bytes(make(arr, signed=True, window=(0, 2000))))
px = png_pixels(png)
check("signed (negative) pixel values are handled", px[0, 0] <= 3 and px[0, -1] >= 252)

# ─────────────────────────────────────────────────────────────────────────────
print("\n[TEST 2] No window in the file -> automatic window")
a = gradient(hi=3000)
a[0, 0] = 4095  # one hot pixel must not squash the picture
png, info = convert_dicom(to_bytes(make(a)))
px = png_pixels(png)
check("automatic window used and reported", info["window"] == "automatic")
check("uses almost the full 0..255 range despite an outlier", px[10:, :].min() <= 5 and px[10:, :].max() >= 250)

pad = np.zeros((64, 128), dtype=np.uint16)
pad[:, 32:96] = np.tile(np.linspace(1000, 2000, 64).astype(np.uint16), (64, 1))
png, info = convert_dicom(to_bytes(make(pad, extra={"PixelPaddingValue": 0})))
px = png_pixels(png)
check("PixelPaddingValue is ignored when choosing the window (content spans the range)", px[:, 32:96].max() - px[:, 32:96].min() >= 240)

# ─────────────────────────────────────────────────────────────────────────────
print("\n[TEST 3] Privacy: nothing from the header leaves")
png, info = convert_dicom(to_bytes(make(gradient(), window=(2048, 4096))))
blob = repr(info).encode() + png
check("patient name not in the PNG bytes or the info", NAME.encode() not in blob and b"JOHNATHAN" not in blob)
check("patient ID, birth date, institution not in the output", PID.encode() not in blob and b"19800101" not in blob and b"SECRET" not in blob)
check("PNG carries no text/EXIF metadata chunks", all(t not in png for t in (b"tEXt", b"iTXt", b"zTXt", b"eXIf")))
check("info contains only the allowed technical keys",
      set(info) <= {"modality", "view_position", "original_rows", "original_columns", "bits_stored", "frames", "photometric",
                    "window", "inverted", "downscaled_from", "output_width", "output_height", "warnings",
                    "transfer_syntax", "pixel_spacing_mm", "burned_in_annotation", "window_center", "window_width"})

# ─────────────────────────────────────────────────────────────────────────────
print("\n[TEST 4] Refusals come with a clear, safe message")
check("CT -> says it is a CT scan", raises(lambda: convert_dicom(to_bytes(make(gradient(), modality="CT"))), "CT scan"))
check("MR -> says MRI", raises(lambda: convert_dicom(to_bytes(make(gradient(), modality="MR"))), "MRI"))
check("random bytes -> not readable as DICOM", raises(lambda: convert_dicom(os.urandom(5000)), "could not be read"))
check("a PNG sent as DICOM -> refused", raises(lambda: convert_dicom(b"\x89PNG\r\n\x1a\n" + b"\0" * 400), "could not be read"))
ds = make(gradient())
del ds.PixelData
check("DICOM with no picture -> 'no image'", raises(lambda: convert_dicom(to_bytes(ds)), "no image"))
check("over the size limit -> refused before any decoding", raises(lambda: convert_dicom(b"\0" * (60 * 1024 * 1024 + 1)), "limit"))
ds = make(gradient(), photometric="PALETTE COLOR")
check("palette-colour DICOM refused clearly", raises(lambda: convert_dicom(to_bytes(ds)), "palette"))

# ─────────────────────────────────────────────────────────────────────────────
print("\n[TEST 5] Size, frames, colour, warnings")
big = gradient(h=2500, w=3000)
png, info = convert_dicom(to_bytes(make(big, window=(2048, 4096))))
px = png_pixels(png)
check("a 3000x2500 image is shrunk to a 2048 long side, same aspect", max(px.shape) == 2048 and abs(px.shape[1] / px.shape[0] - 1.2) < 0.01)
check("info records the original size", info["downscaled_from"] == [3000, 2500])

mf = np.stack([gradient(), gradient()[:, ::-1].copy()])
png, info = convert_dicom(to_bytes(make(mf, window=(2048, 4096), frames=2)))
px = png_pixels(png)
check("multi-frame: first frame used (left dark), with a warning", px[0, 0] < 10 and any("frame" in w for w in info["warnings"]))

rgb = np.zeros((32, 48, 3), dtype=np.uint8)
rgb[..., 0] = 255
png, info = convert_dicom(to_bytes(make(rgb, photometric="RGB", bits=8, spp=3, modality="OT")))
im = Image.open(io.BytesIO(png))
check("colour DICOM stays colour (RGB PNG)", im.mode == "RGB" and im.getpixel((5, 5)) == (255, 0, 0))

png, info = convert_dicom(to_bytes(make(gradient(), window=(2048, 4096), extra={"ViewPosition": "LL", "BurnedInAnnotation": "YES"})))
check("lateral view and burned-in annotation both produce warnings", any("LATERAL" in w for w in info["warnings"]) and any("burned" in w for w in info["warnings"]))
check("modality missing entirely is allowed", convert_dicom(to_bytes(make(gradient(), modality=None, window=(2048, 4096))))[1]["modality"] is None)

# ─────────────────────────────────────────────────────────────────────────────
print("\n[TEST 6] Compressed pixel data")
base = make(gradient(), window=(2048, 4096))
reference = png_pixels(convert_dicom(to_bytes(base))[0])
for name, uid in (("RLE lossless", pydicom.uid.RLELossless), ("JPEG 2000 lossless", pydicom.uid.JPEG2000Lossless)):
    try:
        c = make(gradient(), window=(2048, 4096))
        c.compress(uid)
        raw = to_bytes(c)
    except Exception as e:
        check(f"{name}: could not BUILD the test file here ({type(e).__name__}) -- skipped, NOT tested", True)
        continue
    try:
        out = png_pixels(convert_dicom(raw)[0])
        check(f"{name}: decodes and equals the uncompressed result", np.array_equal(out, reference))
    except DicomError as e:
        check(f"{name}: decoder missing on this machine -> {e}", False)
bad = make(gradient())
bad.file_meta.TransferSyntaxUID = pydicom.uid.JPEGLSLossless
bad.PixelData = pydicom.encaps.encapsulate([b"this is not a jpeg-ls stream"])
bad["PixelData"].is_undefined_length = True
check("undecodable compressed data -> clear message naming the compression, no traceback",
      raises(lambda: convert_dicom(to_bytes(bad)), "could not be decoded"))

# ─────────────────────────────────────────────────────────────────────────────
print("\n[TEST 7] looks_like_dicom")
check("true for a real DICOM, false for PNG/JPEG/empty",
      looks_like_dicom(to_bytes(make(gradient()))) and not looks_like_dicom(b"\x89PNG" + b"\0" * 200) and not looks_like_dicom(b""))

# ─────────────────────────────────────────────────────────────────────────────
print("\n[TEST 8] The route POST /dicom/convert")
app = module4_api.app
_lifespan = TestClient(app)
_lifespan.__enter__()  # runs the app's start-up, which creates the database tables


def new_patient(email):
    c = TestClient(app)
    r = c.post("/auth/register/patient", json={"email": email, "password": PW})
    assert r.status_code == 201, r.text
    return c, {"X-CSRF-Token": r.json()["csrf_token"]}


good = to_bytes(make(gradient(), window=(2048, 4096)))
anon = TestClient(app)
check("not logged in -> 401", anon.post("/dicom/convert", files={"file": ("a.dcm", good, "application/dicom")}).status_code == 401)

pc, ph = new_patient("p1@example.com")
check("logged in but no CSRF header -> 403", pc.post("/dicom/convert", files={"file": ("a.dcm", good, "application/dicom")}).status_code == 403)
r = pc.post("/dicom/convert", files={"file": ("a.dcm", good, "application/dicom")}, headers=ph)
check("patient + valid DICOM -> 200", r.status_code == 200)
body = r.json()
out = base64.b64decode(body["image_base64"])
check("response is a real PNG", out[:8] == b"\x89PNG\r\n\x1a\n" and body["mime"] == "image/png")
check("response never contains the patient's header details", NAME not in r.text and PID not in r.text and "SECRET" not in r.text)
_files = [os.path.join(d, f) for d, _, fs in os.walk(TMP_STORE) for f in fs]
check("only ENCRYPTED staging data (and the dev key) was written; no readable DICOM/name anywhere",
      all(("_staging" in f or f.endswith(".data_key")) for f in _files)
      and all(NAME.encode() not in open(f, "rb").read() and b"DICM" not in open(f, "rb").read() for f in _files if f.endswith(".enc")))

c = sqlite3.connect(TMP_DB)
rows = c.execute("SELECT action, before_json, after_json FROM audit_log WHERE action='dicom_convert'").fetchall()
c.close()
check("an audit row was written", len(rows) == 1)
check("audit row has no patient details", NAME not in repr(rows) and PID not in repr(rows))

r = pc.post("/dicom/convert", files={"file": ("a.dcm", to_bytes(make(gradient(), modality="CT")), "application/dicom")}, headers=ph)
check("CT file -> 422 with the plain reason", r.status_code == 422 and "CT scan" in r.json()["detail"])
r = pc.post("/dicom/convert", files={"file": ("a.dcm", os.urandom(3000), "application/dicom")}, headers=ph)
check("garbage file -> 422, no traceback text", r.status_code == 422 and "Traceback" not in r.text)
r = pc.post("/dicom/convert", files={"file": ("a.dcm", b"", "application/dicom")}, headers=ph)
check("empty file -> 422", r.status_code == 422)

dc = TestClient(app)
r = dc.post("/auth/register/doctor", json={"email": "d1@example.com", "password": PW, "full_name": "Dr Test Person",
                                           "father_name": "F", "pmdc_number": "1111-P"})
check("PENDING doctor -> 403 on the route", dc.post("/dicom/convert", files={"file": ("a.dcm", good, "application/dicom")},
                                                    headers={"X-CSRF-Token": r.json()["csrf_token"]}).status_code == 403)

old = dicom_api.convert_limiter
dicom_api.convert_limiter = core.RateLimiter(max_hits=2, window_seconds=600)
codes = [pc.post("/dicom/convert", files={"file": ("a.dcm", good, "application/dicom")}, headers=ph).status_code for _ in range(3)]
dicom_api.convert_limiter = old
check("rate limit: 3rd quick conversion -> 429", codes == [200, 200, 429])

print("\n" + "=" * 60)
print(f"{passed}/{passed + failed} DICOM tests passed.")
print("=" * 60)
sys.exit(0 if failed == 0 else 1)
