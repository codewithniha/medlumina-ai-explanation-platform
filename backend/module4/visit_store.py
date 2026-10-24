"""
visit_store.py  --  Step 4a: keeping each visit's analysis on the SERVER.

Until now the report, the X-ray and the highlighted images lived only in the
browser's memory and vanished on refresh. This file stores them:

  * report text + structured findings -> table report_versions (version 1, source 'ai')
  * the three images                  -> files in private_store/<visit id>/, listed in visit_files

Analogy: a patient file in a records room. The folder (database row) says what
is inside; the X-ray films live in a locked cabinet (private_store/) that is NOT
a public web folder and is git-ignored. The only way to a film is through the
front desk (an endpoint that checks the wristband and that the file is yours).

Nothing here is ever edited in place: a later doctor edit adds version 2 and
flips which version is final (the database refuses edits to version content).
"""

import hashlib
import json
import os
import uuid
from pathlib import Path

import auth_core as core

_DEFAULT_STORE = Path(__file__).resolve().parent / "private_store"
PRIVATE_STORE = Path(os.getenv("PRIVATE_STORE_DIR") or _DEFAULT_STORE).resolve()

MAX_IMAGE_BYTES = 20 * 1024 * 1024   # same limit the upload screen shows

# kind used in URLs/forms  ->  kind stored in visit_files
KINDS = {"xray": "xray_original", "annotated": "annotated", "comparison": "comparison"}
URL_KINDS = {v: k for k, v in KINDS.items()}


class AlreadySaved(Exception):
    pass


class BadImage(ValueError):
    pass


def sniff_image(data: bytes) -> tuple[str, str]:
    """(mime, extension) decided from the file's own first bytes - never from the
    filename or the browser's claim. SVG/HTML/PDF/anything else is refused."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png", "png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg", "jpg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif", "gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp", "webp"
    if data[:2] == b"BM":
        return "image/bmp", "bmp"
    raise BadImage("The file is not a supported image (PNG, JPEG, WebP, GIF or BMP).")


def valid_session_id(session_id: str) -> bool:
    try:
        return str(uuid.UUID(session_id)) == session_id.lower()
    except (ValueError, AttributeError, TypeError):
        return False


def _inside_store(path: Path) -> bool:
    try:
        path.resolve().relative_to(PRIVATE_STORE)
        return True
    except ValueError:
        return False


def save_ai_analysis(db, user: dict, session_id: str, analysis: dict, report_text: str,
                     images: dict[str, bytes]) -> int:
    """
    Stores version 1 (the AI's own report) and its images. `images` maps
    'xray' / 'annotated' / 'comparison' to raw bytes (xray is required).
    All-or-nothing: if anything fails, no database rows and no files remain.
    Returns the new version number (1).
    """
    if db.execute("SELECT 1 FROM report_versions WHERE session_id = ?", (session_id,)).fetchone():
        raise AlreadySaved()

    prepared = {}
    for url_kind, data in images.items():
        if len(data) > MAX_IMAGE_BYTES:
            raise BadImage(f"The {url_kind} image is over the {MAX_IMAGE_BYTES // (1024 * 1024)}MB limit.")
        mime, ext = sniff_image(data)
        prepared[url_kind] = (data, mime, ext)

    folder = PRIVATE_STORE / session_id
    written: list[Path] = []
    try:
        folder.mkdir(parents=True, exist_ok=True)
        rows = []
        for url_kind, (data, mime, ext) in prepared.items():
            name = f"{KINDS[url_kind]}-{uuid.uuid4().hex}.{ext}"   # random: a failed save can never delete another save's file
            tmp = folder / (name + ".part")
            tmp.write_bytes(data)
            final = folder / name
            os.replace(tmp, final)
            written.append(final)
            rows.append((url_kind, f"{session_id}/{name}", mime, len(data), hashlib.sha256(data).hexdigest()))

        now = core._iso(core.utcnow())
        cur = db.execute(
            "INSERT INTO report_versions (session_id, version_no, source, author_user_id, created_at, "
            "report_text, structured_findings, is_final) VALUES (?, 1, 'ai', NULL, ?, ?, ?, 1)",
            (session_id, now, report_text, json.dumps(analysis)),
        )
        version_id = cur.lastrowid
        for url_kind, rel, mime, size, digest in rows:
            db.execute(
                "INSERT INTO visit_files (session_id, version_id, kind, relative_path, mime_type, size_bytes, "
                "sha256, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (session_id, None if url_kind == "xray" else version_id, KINDS[url_kind], rel, mime, size, digest, now),
            )
        core.audit(db, user["user_id"], user["role"], "save_ai_analysis", "session", session_id,
                   after={"version_no": 1, "files": sorted(KINDS[k] for k in prepared)})
        db.commit()
    except Exception as e:
        db.rollback()
        for p in written:
            p.unlink(missing_ok=True)
        for p in folder.glob("*.part"):
            p.unlink(missing_ok=True)
        try:
            folder.rmdir()   # only succeeds if empty
        except OSError:
            pass
        if "UNIQUE" in str(e) and "report_versions" in str(e):
            raise AlreadySaved() from e
        raise
    return 1


def add_version_files(db, session_id: str, version_id: int, images: dict[str, bytes], now: str) -> list[Path]:
    """
    Writes new picture files for ONE report version (e.g. a redrawn highlighted image) and adds their
    visit_files rows inside the caller's open transaction. Returns the files written so the caller can
    delete them if the transaction fails. Random file names: nothing is ever overwritten.
    """
    folder = PRIVATE_STORE / session_id
    folder.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    try:
        for url_kind, data in images.items():
            if url_kind not in KINDS or url_kind == "xray":
                raise ValueError("only version pictures can be added here")
            if len(data) > MAX_IMAGE_BYTES:
                raise BadImage(f"The {url_kind} image is over the {MAX_IMAGE_BYTES // (1024 * 1024)}MB limit.")
            mime, ext = sniff_image(data)
            name = f"{KINDS[url_kind]}-{uuid.uuid4().hex}.{ext}"
            tmp = folder / (name + ".part")
            tmp.write_bytes(data)
            final = folder / name
            os.replace(tmp, final)
            written.append(final)
            db.execute(
                "INSERT INTO visit_files (session_id, version_id, kind, relative_path, mime_type, size_bytes, "
                "sha256, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (session_id, version_id, KINDS[url_kind], f"{session_id}/{name}", mime, len(data),
                 hashlib.sha256(data).hexdigest(), now))
    except Exception:
        for f in written:
            f.unlink(missing_ok=True)
        raise
    return written


def read_xray_bytes(db, session_id: str) -> bytes | None:
    found = find_file(db, session_id, "xray")
    return None if found is None else found[0].read_bytes()


def get_visit_view(db, session_id: str) -> dict:
    """What a dashboard shows for one visit: the FINAL report version + which images exist."""
    s = db.execute(
        "SELECT s.session_id, s.created_at, s.explanation_level, p.patient_code "
        "FROM sessions s JOIN patients p ON p.patient_id = s.patient_id WHERE s.session_id = ?",
        (session_id,),
    ).fetchone()
    v = db.execute(
        "SELECT version_id, version_no, source, created_at, report_text, structured_findings "
        "FROM report_versions WHERE session_id = ? AND is_final = 1",
        (session_id,),
    ).fetchone()
    files = {"xray": False, "annotated": False, "comparison": False}
    for r in db.execute(
        "SELECT kind, version_id FROM visit_files WHERE session_id = ? "
        "AND (version_id IS NULL OR version_id = ?)", (session_id, v["version_id"] if v else -1)
    ).fetchall():
        files[URL_KINDS[r["kind"]]] = True
    return {
        "visit": {"session_id": s["session_id"], "patient_code": s["patient_code"],
                  "created_at": s["created_at"], "explanation_level": s["explanation_level"]},
        "report": None if v is None else {
            "version_no": v["version_no"], "source": v["source"], "created_at": v["created_at"],
            "report_text": v["report_text"], "structured": json.loads(v["structured_findings"] or "{}"),
        },
        "files": files,
        "read_only": True,
    }


def find_file(db, session_id: str, url_kind: str) -> tuple[Path, str] | None:
    """Path + mime of the image belonging to the FINAL version (or the original X-ray)."""
    if url_kind not in KINDS:
        return None
    v = db.execute("SELECT version_id FROM report_versions WHERE session_id = ? AND is_final = 1",
                   (session_id,)).fetchone()
    row = db.execute(
        "SELECT relative_path, mime_type FROM visit_files WHERE session_id = ? AND kind = ? "
        "AND (version_id IS NULL OR version_id = ?) ORDER BY file_id DESC LIMIT 1",
        (session_id, KINDS[url_kind], v["version_id"] if v else -1),
    ).fetchone()
    if row is None:
        return None
    path = (PRIVATE_STORE / row["relative_path"])
    if not _inside_store(path) or not path.is_file():
        return None
    return path, row["mime_type"]


def list_versions(db, session_id: str) -> list[dict]:
    """Every saved version of a visit's report, oldest first. The author is shown
    by display id (e.g. DR-1A2B3C) - never by email."""
    rows = db.execute(
        "SELECT v.version_no, v.source, v.created_at, v.is_final, u.display_id AS author "
        "FROM report_versions v LEFT JOIN users u ON u.user_id = v.author_user_id "
        "WHERE v.session_id = ? ORDER BY v.version_no",
        (session_id,),
    ).fetchall()
    return [{"version_no": r["version_no"], "source": r["source"], "created_at": r["created_at"],
             "is_final": bool(r["is_final"]), "author": r["author"]} for r in rows]
