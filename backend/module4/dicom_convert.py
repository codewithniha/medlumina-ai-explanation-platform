"""
dicom_convert.py  --  turns a DICOM chest X-ray into a plain 8-bit PNG for the analysis model.

ANALOGY
-------
A DICOM file is a sealed medical envelope: the X-ray is inside, but so is a card with the
patient's name, ID and birth date. The model only needs the picture. This module opens the
envelope in a clean room: it takes out the picture, adjusts it the way a radiologist's
viewer would (brightness window, flip black/white if needed), and throws the card away.
Nothing from the header except a few harmless technical facts leaves this file.

WHAT IT DOES, IN ORDER
----------------------
 1. Reads the file with pydicom (rejects files that are not DICOM or have no picture).
 2. Refuses non-X-ray modalities (CT, MR, ultrasound ...) with a clear message.
 3. Decodes the pixels, including compressed ones (JPEG, JPEG-LS, JPEG 2000, RLE).
 4. Multi-frame file: uses the first frame and says so.
 5. Applies the Modality LUT (RescaleSlope / RescaleIntercept) if present.
 6. Applies the VOI window (WindowCenter / WindowWidth) the scanner chose, using the
    DICOM linear formula. No window in the file -> an automatic one (0.5th to 99.5th
    percentile of the real pixels, ignoring PixelPaddingValue).
 7. MONOCHROME1 (0 = white) is inverted so bones are bright, as the model expects.
 8. Scales to 8 bits; shrinks so the long side is at most MAX_SIDE pixels.
 9. Writes a PNG with NO metadata at all.

PRIVACY
-------
convert_dicom() returns only: modality, view position, original size, bit depth, how the
window was chosen, frame count, and warnings. It never returns or stores the patient name,
ID, birth date, institution, dates, UIDs or any other header field.
"""

from __future__ import annotations

import io
from typing import Any

import numpy as np

MAX_DICOM_BYTES = 60 * 1024 * 1024      # raw DICOM upload limit (chest CR/DX are often 10-30 MB)
MAX_SIDE = 2048                         # the model resizes anyway; this keeps uploads small
ALLOWED_MODALITIES = {"CR", "DX", "RG", "RF", "XA", "OT", "SC", "PX", ""}  # "" = not stated
# Anything in this list gets a specific message (it is DICOM, just not a chest X-ray).
KNOWN_NON_XRAY = {
    "CT": "a CT scan", "MR": "an MRI scan", "US": "an ultrasound", "NM": "a nuclear medicine scan",
    "PT": "a PET scan", "MG": "a mammogram", "OCT": "an eye scan", "ECG": "an ECG", "SR": "a structured report",
    "RTIMAGE": "a radiotherapy image", "RTDOSE": "a radiotherapy dose file", "RTSTRUCT": "a radiotherapy structure set",
    "SEG": "a segmentation", "DOC": "a document", "PR": "a presentation state",
}


class DicomError(Exception):
    """A problem the user can understand and act on. The message is safe to show them."""


def looks_like_dicom(data: bytes) -> bool:
    """True if the standard 128-byte preamble is followed by the letters DICM."""
    return len(data) >= 132 and data[128:132] == b"DICM"


def _read(data: bytes):
    try:
        import pydicom
    except ImportError as e:  # pragma: no cover
        raise DicomError("DICOM support is not installed on the server (pip install pydicom).") from e
    try:
        # force=True also opens older files that lack the 'DICM' preamble; we then insist on pixel data below.
        ds = pydicom.dcmread(io.BytesIO(data), force=True)
    except Exception as e:
        raise DicomError("This file could not be read as DICOM.") from e
    # Without the standard "DICM" marker we only accept the file if it really looks like an
    # old-style DICOM image (size AND picture present); otherwise it is just some other file.
    if not looks_like_dicom(data) and not ("PixelData" in ds and "Rows" in ds and "Columns" in ds):
        raise DicomError("This file could not be read as DICOM.")
    if "PixelData" not in ds and "FloatPixelData" not in ds and "DoubleFloatPixelData" not in ds:
        what = str(getattr(ds, "Modality", "") or "").upper()
        if what in KNOWN_NON_XRAY:
            raise DicomError(f"This DICOM file is {KNOWN_NON_XRAY[what]} and has no X-ray picture in it.")
        raise DicomError("This file has no image in it (no pixel data), so there is nothing to analyse.")
    for need in ("Rows", "Columns"):
        if need not in ds:
            raise DicomError("This DICOM file is missing its image size, so it cannot be read.")
    return ds


def _decode(ds) -> np.ndarray:
    try:
        arr = ds.pixel_array
    except Exception as e:
        ts = ""
        try:
            ts = f" (compression: {ds.file_meta.TransferSyntaxUID.name})"
        except Exception:
            pass
        raise DicomError(
            "The picture inside this DICOM file could not be decoded" + ts + ". "
            "It may use a compression this server does not support. "
            "Please export it from your viewer as an uncompressed or JPEG-lossless DICOM, or as a PNG/JPEG."
        ) from e
    return np.asarray(arr)


def _first_value(v: Any):
    """DICOM numbers can be a single value or a list; take the first."""
    try:
        if isinstance(v, (list, tuple)) or (hasattr(v, "__len__") and not isinstance(v, (str, bytes))):
            return v[0] if len(v) else None
    except Exception:
        pass
    return v


def _window_from_file(ds):
    c = _first_value(ds.get("WindowCenter", None))
    w = _first_value(ds.get("WindowWidth", None))
    if c is None or w is None:
        return None
    try:
        c, w = float(c), float(w)
    except (TypeError, ValueError):
        return None
    if not (np.isfinite(c) and np.isfinite(w)) or w < 1:
        return None
    fn = str(ds.get("VOILUTFunction", "LINEAR") or "LINEAR").upper()
    if fn not in ("LINEAR", "LINEAR_EXACT"):
        return None  # SIGMOID is rare in X-rays; fall back to the automatic window instead of guessing
    return c, w, fn


def _apply_window(x: np.ndarray, c: float, w: float, fn: str) -> np.ndarray:
    """DICOM PS3.3 C.11.2.1.2: maps stored values to 0..1."""
    if fn == "LINEAR_EXACT":
        y = (x - c) / w + 0.5
    else:
        y = (x - (c - 0.5)) / (w - 1.0) + 0.5
    return np.clip(y, 0.0, 1.0)


def _auto_window(x: np.ndarray, ds) -> np.ndarray:
    valid = np.ones(x.shape, dtype=bool)
    pad = ds.get("PixelPaddingValue", None)
    if pad is not None:
        try:
            valid &= x != float(_first_value(pad))
        except (TypeError, ValueError):
            pass
    vals = x[valid] if valid.any() else x.ravel()
    lo, hi = np.percentile(vals, [0.5, 99.5])
    if hi <= lo:  # flat image
        lo, hi = float(vals.min()), float(vals.max())
    if hi <= lo:
        return np.zeros_like(x, dtype=np.float32)
    return np.clip((x - lo) / (hi - lo), 0.0, 1.0)


def _pixel_spacing(ds):
    """[row_mm, col_mm] or None. ImagerPixelSpacing is what a detector reports; PixelSpacing is calibrated."""
    for key in ("PixelSpacing", "ImagerPixelSpacing"):
        v = ds.get(key, None)
        try:
            if v is not None and len(v) == 2:
                r, c = float(v[0]), float(v[1])
                if r > 0 and c > 0:
                    return [r, c]
        except (TypeError, ValueError):
            pass
    return None


def convert_dicom(data: bytes, override_window: tuple[float, float] | None = None,
                  invert: bool | None = None) -> tuple[bytes, dict]:
    """Returns (png_bytes, info). Raises DicomError with a user-safe message on any problem.

    override_window=(center, width) re-renders with a viewer-chosen window instead of the file's
    own (the PACS "window/level" control). invert=True/False forces the polarity; None = automatic."""
    from PIL import Image

    if len(data) > MAX_DICOM_BYTES:
        raise DicomError(f"This DICOM file is {len(data) / 1048576:.0f} MB, over the {MAX_DICOM_BYTES // 1048576} MB limit.")
    ds = _read(data)

    modality = str(ds.get("Modality", "") or "").upper().strip()
    if modality in KNOWN_NON_XRAY:
        raise DicomError(
            f"This DICOM file is {KNOWN_NON_XRAY[modality]}. MedLumina analyses chest X-rays "
            "(modality CR or DX), so it cannot use this file."
        )
    if modality not in ALLOWED_MODALITIES:
        raise DicomError(f"This DICOM file has modality '{modality}', which is not a chest X-ray type MedLumina can analyse.")

    arr = _decode(ds)
    warnings: list[str] = []
    frames = int(ds.get("NumberOfFrames", 1) or 1)
    spp = int(ds.get("SamplesPerPixel", 1) or 1)
    photometric = str(ds.get("PhotometricInterpretation", "MONOCHROME2")).upper()

    # Pick one frame.
    if spp == 1 and arr.ndim == 3:
        arr = arr[0]
    elif spp == 3 and arr.ndim == 4:
        arr = arr[0]
    if frames > 1:
        warnings.append(f"This file has {frames} frames; only the first was analysed.")

    info: dict[str, Any] = {
        "modality": modality or None,
        "view_position": (str(ds.get("ViewPosition", "") or "").upper().strip() or None),
        "original_rows": int(ds.Rows),
        "original_columns": int(ds.Columns),
        "bits_stored": int(ds.get("BitsStored", 0) or 0) or None,
        "frames": frames,
        "photometric": photometric,
        "transfer_syntax": (str(ds.file_meta.TransferSyntaxUID.name) if getattr(ds, "file_meta", None) and "TransferSyntaxUID" in ds.file_meta else None),
        "pixel_spacing_mm": _pixel_spacing(ds),
        "burned_in_annotation": str(ds.get("BurnedInAnnotation", "") or "").upper() == "YES",
    }

    if spp == 3:
        # Colour DICOM (usually a screen capture saved as DICOM). Convert YBR -> RGB, keep colour.
        if photometric.startswith("YBR"):
            try:
                from pydicom.pixels import convert_color_space
                arr = convert_color_space(arr, photometric, "RGB")
            except Exception as e:
                raise DicomError("This colour DICOM file uses a colour format that could not be converted.") from e
        a8 = arr.astype(np.float32)
        if a8.max() > 255:
            a8 = a8 / a8.max() * 255.0
        img = Image.fromarray(np.clip(a8, 0, 255).astype(np.uint8))
        info["window"] = "colour"
    else:
        x = arr.astype(np.float32)
        # Modality LUT: stored value -> real-world value (matters for some DX, and all CT).
        slope = _first_value(ds.get("RescaleSlope", None))
        inter = _first_value(ds.get("RescaleIntercept", None))
        try:
            if slope is not None or inter is not None:
                x = x * float(slope if slope is not None else 1.0) + float(inter if inter is not None else 0.0)
        except (TypeError, ValueError):
            warnings.append("The file's rescale values were unreadable and were ignored.")

        win = _window_from_file(ds)
        if override_window is not None:
            c, w = float(override_window[0]), float(override_window[1])
            y = _apply_window(x, c, w, "LINEAR")
            info["window"] = "viewer"
            info["window_center"], info["window_width"] = c, w
        elif win is not None:
            y = _apply_window(x, *win)
            info["window"] = "from_file"
            info["window_center"], info["window_width"] = win[0], win[1]
        else:
            y = _auto_window(x, ds)
            info["window"] = "automatic"
        flip = (photometric == "MONOCHROME1") if invert is None else bool(invert)
        if flip:
            y = 1.0 - y
            info["inverted"] = True
        elif photometric not in ("MONOCHROME2",):
            if photometric == "PALETTE COLOR":
                raise DicomError("This DICOM file uses a colour palette instead of grey levels and cannot be used.")
            warnings.append(f"Unusual photometric type '{photometric}'; treated as normal grey levels.")
        img = Image.fromarray((y * 255.0 + 0.5).astype(np.uint8))

    if str(ds.get("BurnedInAnnotation", "") or "").upper() == "YES":
        warnings.append("This image may have patient text burned into the pixels. Check it before sharing.")
    if info["view_position"] in ("LL", "RL", "LATERAL"):
        warnings.append("This looks like a LATERAL view; the analysis works best on frontal (PA/AP) chest X-rays.")

    w0, h0 = img.size
    if max(w0, h0) > MAX_SIDE:
        scale = MAX_SIDE / float(max(w0, h0))
        img = img.resize((max(1, round(w0 * scale)), max(1, round(h0 * scale))), getattr(Image, "Resampling", Image).LANCZOS)
        info["downscaled_from"] = [w0, h0]
    info["output_width"], info["output_height"] = img.size

    out = io.BytesIO()
    img.save(out, format="PNG", optimize=True)  # no pnginfo -> no metadata written
    info["warnings"] = warnings
    return out.getvalue(), info
