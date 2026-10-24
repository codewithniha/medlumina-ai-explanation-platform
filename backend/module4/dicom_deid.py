"""
dicom_deid.py  --  a de-identified COPY of a DICOM file, for sharing.

ANALOGY
-------
Instead of crossing out names on a copy with a marker (and hoping you found them all), we
build a brand-new form and copy over ONLY the boxes we know are safe: image size, bit depth,
modality, pixel spacing, window, and the picture itself. Anything not on the safe list
(including every manufacturer-private tag and every date, name, ID, doctor, institution,
and free-text field) is simply never copied. A new field we have never heard of can
therefore not leak: it is not on the list.

WHAT YOU GET
------------
  * a valid DICOM file, same picture data byte-for-byte (compressed pictures stay compressed)
  * PatientName "ANONYMOUS", PatientID = the pseudonym you pass in (the record's PT- code),
    all other patient/study/physician/institution fields empty or absent
  * new UIDs, derived from the visit id so repeated exports of the same visit match
  * PatientIdentityRemoved = YES and a DeidentificationMethod note

HONEST LIMITS
-------------
  * Names or text BURNED INTO THE PIXELS cannot be removed automatically. Such files are
    refused (BurnedInAnnotation = YES) rather than exported with a false "de-identified" label.
  * This follows the intent of DICOM PS3.15 (Basic Application Level Confidentiality Profile)
    with an allow-list approach. It has NOT been certified against a formal conformance suite.
    Before releasing data outside the project, have the supervisor / ethics process review it.
"""

from __future__ import annotations

import io
import uuid

import pydicom
from pydicom.dataset import Dataset, FileDataset, FileMetaDataset
from pydicom.uid import PYDICOM_IMPLEMENTATION_UID

from dicom_convert import DicomError, _read

# Keywords copied from the original IF present. All technical; none identifies a person.
ALLOWED = [
    "SOPClassUID", "Modality", "ImageType", "SamplesPerPixel", "PhotometricInterpretation", "PlanarConfiguration",
    "Rows", "Columns", "BitsAllocated", "BitsStored", "HighBit", "PixelRepresentation", "NumberOfFrames",
    "PixelAspectRatio", "PixelSpacing", "ImagerPixelSpacing", "PixelSpacingCalibrationType",
    "WindowCenter", "WindowWidth", "VOILUTFunction", "RescaleIntercept", "RescaleSlope", "RescaleType",
    "PresentationLUTShape", "PixelIntensityRelationship", "PixelIntensityRelationshipSign",
    "PixelPaddingValue", "PixelPaddingRangeLimit", "LossyImageCompression", "LossyImageCompressionRatio",
    "LossyImageCompressionMethod", "ViewPosition", "PatientOrientation", "Laterality", "ImageLaterality",
    "BodyPartExamined", "KVP", "ExposureTime", "XRayTubeCurrent", "Exposure", "ExposureInuAs",
    "DistanceSourceToDetector", "DistanceSourceToPatient", "DetectorType", "ImageAndFluoroscopyAreaDoseProduct",
]
ALLOWED_PIXEL = "PixelData"


def _uid(session_id: str, role: str) -> str:
    """Deterministic, valid DICOM UID (2.25.<uuid as integer>)."""
    return "2.25." + str(uuid.uuid5(uuid.NAMESPACE_URL, f"medlumina|{session_id}|{role}").int)


def deidentify(data: bytes, session_id: str, pseudonym: str) -> bytes:
    ds = _read(data)
    if str(ds.get("BurnedInAnnotation", "") or "").upper() == "YES":
        raise DicomError(
            "This image may have patient text burned into the picture itself, which cannot be removed "
            "automatically. It cannot be exported as de-identified."
        )
    if "PixelData" not in ds:
        raise DicomError("This DICOM file has no picture to export.")

    ts = ds.file_meta.TransferSyntaxUID
    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = ds.get("SOPClassUID", ds.file_meta.get("MediaStorageSOPClassUID"))
    meta.MediaStorageSOPInstanceUID = _uid(session_id, "instance")
    meta.TransferSyntaxUID = ts
    meta.ImplementationClassUID = PYDICOM_IMPLEMENTATION_UID

    out = FileDataset(None, {}, file_meta=meta, preamble=b"\0" * 128)
    for kw in ALLOWED:
        if kw in ds:
            out[kw] = ds[kw]
    out.SOPClassUID = meta.MediaStorageSOPClassUID
    out.SOPInstanceUID = meta.MediaStorageSOPInstanceUID
    out.StudyInstanceUID = _uid(session_id, "study")
    out.SeriesInstanceUID = _uid(session_id, "series")
    out.SeriesNumber = "1"
    out.InstanceNumber = "1"

    # Required-but-empty (DICOM "type 2") fields so the file stays valid.
    out.PatientName = "ANONYMOUS"
    out.PatientID = pseudonym
    out.PatientBirthDate = ""
    out.PatientSex = ""
    out.StudyDate = ""
    out.StudyTime = ""
    out.ReferringPhysicianName = ""
    out.AccessionNumber = ""
    out.StudyID = ""
    out.PatientIdentityRemoved = "YES"
    out.DeidentificationMethod = "MedLumina allow-list de-identification (PS3.15 intent)"
    out.BurnedInAnnotation = "NO"

    out["PixelData"] = ds["PixelData"]  # same element -> same bytes, same VR, same compression
    buf = io.BytesIO()
    pydicom.dcmwrite(buf, out, enforce_file_format=True)
    return buf.getvalue()
