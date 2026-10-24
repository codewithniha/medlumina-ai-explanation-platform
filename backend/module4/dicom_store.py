"""
dicom_store.py  --  keeping the ORIGINAL DICOM file, safely.

ANALOGY
-------
A hospital archive never throws the original film away after making a photocopy. It keeps
the original in a locked cabinet, writes down who opens it, and hands out copies. This
module is that cabinet:

  * the original DICOM is kept BYTE-FOR-BYTE (so nothing is lost: full bit depth, all
    technical tags) but ENCRYPTED on disk (AES-256-GCM). Without the key the file is noise.
  * the encryption is tied to the visit it belongs to, so a file copied into another
    visit's folder will not open (tamper / swap detection).
  * a SHA-256 fingerprint of the original is stored, and checked on every read.
  * only harmless technical facts (modality, size, pixel spacing, window ...) are copied
    into the database. The patient's name, ID and birth date are NOT: they exist only
    inside the encrypted file.
  * every download is audited by the routes that call this module.

FLOW
----
  1. POST /dicom/convert   -> original is parked encrypted in a STAGING area, bound to the
                              user who uploaded it; the browser gets a one-time `dicom_token`.
  2. POST /visits/{id}/analysis (with that token) -> the staged file moves into the visit's
                              folder and a row is added to `dicom_originals`.
  Staged files nobody claims are deleted after STAGING_TTL_HOURS.

THE KEY
-------
  Production: set MEDLUMINA_DATA_KEY to 32 random bytes encoded as base64 (see
  make_data_key.py) and keep it in a secret manager, NOT in the repo or beside the data.
  Development: if the variable is missing a key file is created inside the (git-ignored)
  private store and a loud warning is printed. Set MEDLUMINA_REQUIRE_KEY_ENV=1 to refuse
  that fallback (recommended anywhere real patient data could appear).
  Lose the key and the originals are unrecoverable; back it up separately.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import time
import uuid
from pathlib import Path

import auth_core as core
import visit_store

MAGIC = b"MLE1"               # file header: MedLumina Encrypted v1
KEY_ID = 1                    # reserved for key rotation
STAGING_TTL_HOURS = 24
_TOKEN_RE = re.compile(r"^[0-9a-f]{32}$")

DICOM_TABLE = """
CREATE TABLE IF NOT EXISTS dicom_originals (
    session_id        TEXT PRIMARY KEY REFERENCES sessions (session_id),
    relative_path     TEXT NOT NULL,
    size_bytes        INTEGER NOT NULL CHECK (size_bytes > 0),
    sha256            TEXT NOT NULL,
    key_id            INTEGER NOT NULL,
    transfer_syntax   TEXT,
    modality          TEXT,
    view_position     TEXT,
    rows_px           INTEGER,
    columns_px        INTEGER,
    bits_stored       INTEGER,
    photometric       TEXT,
    frames            INTEGER,
    pixel_spacing_row_mm REAL,
    pixel_spacing_col_mm REAL,
    window_center     REAL,
    window_width      REAL,
    burned_in_annotation INTEGER NOT NULL DEFAULT 0 CHECK (burned_in_annotation IN (0, 1)),
    created_at        TEXT NOT NULL
)
"""


class DicomStoreError(Exception):
    """Safe to show the user."""


def init_dicom_schema(db_path: str | None = None) -> None:
    """Idempotent; called at start-up after init_accounts_schema()."""
    conn = core.open_db() if db_path is None else None
    try:
        if conn is None:
            import sqlite3
            conn = sqlite3.connect(db_path)
        conn.execute(DICOM_TABLE)
        conn.commit()
    finally:
        conn.close()


# ── The key ──────────────────────────────────────────────────────────────────
_key_cache: bytes | None = None


def _load_key() -> bytes:
    global _key_cache
    if _key_cache is not None:
        return _key_cache
    raw = os.getenv("MEDLUMINA_DATA_KEY", "").strip()
    if raw:
        try:
            key = base64.b64decode(raw, validate=True)
        except Exception as e:
            raise DicomStoreError("MEDLUMINA_DATA_KEY is not valid base64.") from e
        if len(key) != 32:
            raise DicomStoreError("MEDLUMINA_DATA_KEY must decode to exactly 32 bytes.")
        _key_cache = key
        return key
    if os.getenv("MEDLUMINA_REQUIRE_KEY_ENV", "").strip() in ("1", "true", "yes"):
        raise DicomStoreError("MEDLUMINA_DATA_KEY is not set and MEDLUMINA_REQUIRE_KEY_ENV forbids a key file.")
    path = visit_store.PRIVATE_STORE / ".data_key"
    if path.exists():
        key = base64.b64decode(path.read_text().strip())
    else:
        visit_store.PRIVATE_STORE.mkdir(parents=True, exist_ok=True)
        key = secrets.token_bytes(32)
        path.write_text(base64.b64encode(key).decode("ascii"))
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        print(f"[dicom_store] WARNING: MEDLUMINA_DATA_KEY not set; created a DEVELOPMENT key file at {path}. "
              "Set the environment variable for anything beyond local testing.", flush=True)
    if len(key) != 32:
        raise DicomStoreError("The development key file is damaged.")
    _key_cache = key
    return key


def reset_key_cache() -> None:  # used by tests
    global _key_cache
    _key_cache = None


def encrypt(plain: bytes, aad: str) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    nonce = os.urandom(12)
    return MAGIC + bytes([KEY_ID]) + nonce + AESGCM(_load_key()).encrypt(nonce, plain, aad.encode())


def decrypt(blob: bytes, aad: str) -> bytes:
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    if len(blob) < 4 + 1 + 12 + 16 or blob[:4] != MAGIC:
        raise DicomStoreError("The stored file is not in the expected format.")
    if blob[4] != KEY_ID:
        raise DicomStoreError("The stored file was encrypted with a different key.")
    try:
        return AESGCM(_load_key()).decrypt(blob[5:17], blob[17:], aad.encode())
    except InvalidTag as e:
        raise DicomStoreError("The stored file failed its integrity check (wrong key, or the file was altered).") from e


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    tmp.write_bytes(data)
    os.replace(tmp, path)


# ── Staging (between "convert" and "save visit") ────────────────────────────
def _staging_dir(user_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_-]", "", user_id)
    if not safe:
        raise DicomStoreError("Bad user id.")
    return visit_store.PRIVATE_STORE / "_staging" / safe


def purge_expired_staging() -> int:
    root = visit_store.PRIVATE_STORE / "_staging"
    if not root.exists():
        return 0
    cutoff = time.time() - STAGING_TTL_HOURS * 3600
    n = 0
    for p in list(root.rglob("*.enc")) + list(root.rglob("*.json")):
        try:
            if p.stat().st_mtime < cutoff:
                p.unlink()
                n += 1
        except OSError:
            pass
    return n


def stage_original(user_id: str, data: bytes, info: dict) -> str:
    """`info` = the converter's technical facts (no patient details); kept beside the encrypted file."""
    purge_expired_staging()
    token = uuid.uuid4().hex
    folder = _staging_dir(user_id)
    _write_atomic(folder / f"{token}.json", json.dumps(info).encode())
    _write_atomic(folder / f"{token}.enc", encrypt(data, f"staging|{user_id}|{token}"))
    return token


def take_staged(user_id: str, token: str) -> tuple[bytes, dict]:
    if not isinstance(token, str) or not _TOKEN_RE.match(token):
        raise DicomStoreError("The DICOM upload reference is not valid.")
    path = _staging_dir(user_id) / f"{token}.enc"
    if not path.exists():
        raise DicomStoreError("The DICOM upload has expired or was not found. Please upload the file again.")
    data = decrypt(path.read_bytes(), f"staging|{user_id}|{token}")
    try:
        info = json.loads((_staging_dir(user_id) / f"{token}.json").read_text())
    except (OSError, ValueError):
        info = {}
    return data, info


def discard_staged(user_id: str, token: str) -> None:
    if isinstance(token, str) and _TOKEN_RE.match(token):
        (_staging_dir(user_id) / f"{token}.enc").unlink(missing_ok=True)
        (_staging_dir(user_id) / f"{token}.json").unlink(missing_ok=True)


# ── Permanent keeping ────────────────────────────────────────────────────────
def persist_original(db, user: dict, session_id: str, data: bytes, info: dict) -> None:
    """Encrypt `data` into the visit's folder and record its technical facts.
    `info` is the converter's info dict (technical facts only)."""
    if db.execute("SELECT 1 FROM dicom_originals WHERE session_id = ?", (session_id,)).fetchone():
        raise DicomStoreError("This visit already has a retained DICOM file.")
    digest = hashlib.sha256(data).hexdigest()
    name = f"dicom-{uuid.uuid4().hex}.dcm.enc"
    rel = f"{session_id}/{name}"
    path = visit_store.PRIVATE_STORE / session_id / name
    _write_atomic(path, encrypt(data, f"visit|{session_id}|dicom"))
    try:
        ps = info.get("pixel_spacing_mm") or [None, None]
        db.execute(
            "INSERT INTO dicom_originals (session_id, relative_path, size_bytes, sha256, key_id, transfer_syntax, "
            "modality, view_position, rows_px, columns_px, bits_stored, photometric, frames, pixel_spacing_row_mm, "
            "pixel_spacing_col_mm, window_center, window_width, burned_in_annotation, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (session_id, rel, len(data), digest, KEY_ID, info.get("transfer_syntax"), info.get("modality"),
             info.get("view_position"), info.get("original_rows"), info.get("original_columns"),
             info.get("bits_stored"), info.get("photometric"), info.get("frames"), ps[0], ps[1],
             info.get("window_center"), info.get("window_width"), 1 if info.get("burned_in_annotation") else 0,
             core._iso(core.utcnow())),
        )
        core.audit(db, user["user_id"], user["role"], "dicom_retained", "session", session_id,
                   after={"bytes": len(data), "modality": info.get("modality"), "encrypted": True})
        db.commit()
    except Exception:
        db.rollback()
        path.unlink(missing_ok=True)
        raise


def has_original(db, session_id: str) -> bool:
    try:
        return db.execute("SELECT 1 FROM dicom_originals WHERE session_id = ?", (session_id,)).fetchone() is not None
    except Exception:  # table not created yet (older database)
        return False


def read_original(db, session_id: str) -> bytes:
    """Decrypts and verifies the fingerprint. Raises DicomStoreError if missing or damaged."""
    row = db.execute("SELECT relative_path, sha256 FROM dicom_originals WHERE session_id = ?", (session_id,)).fetchone()
    if row is None:
        raise DicomStoreError("No DICOM original is kept for this visit.")
    path = (visit_store.PRIVATE_STORE / row["relative_path"]).resolve()
    if not visit_store._inside_store(path) or not path.exists():
        raise DicomStoreError("The stored DICOM file is missing.")
    data = decrypt(path.read_bytes(), f"visit|{session_id}|dicom")
    if hashlib.sha256(data).hexdigest() != row["sha256"]:
        raise DicomStoreError("The stored DICOM file failed its fingerprint check.")
    return data


def public_meta(db, session_id: str) -> dict | None:
    """Technical facts only (never anything from the patient part of the header)."""
    try:
        r = _meta_row(db, session_id)
    except Exception:  # table not created yet (older database): no DICOM kept
        return None
    if r is None:
        return None
    d = dict(r)
    d["burned_in_annotation"] = bool(d["burned_in_annotation"])
    return d


def _meta_row(db, session_id: str):
    return db.execute(
        "SELECT modality, view_position, rows_px, columns_px, bits_stored, photometric, frames, transfer_syntax, "
        "pixel_spacing_row_mm, pixel_spacing_col_mm, window_center, window_width, burned_in_annotation, size_bytes "
        "FROM dicom_originals WHERE session_id = ?", (session_id,)).fetchone()
