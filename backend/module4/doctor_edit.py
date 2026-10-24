"""
doctor_edit.py  --  Step 6a: a verified doctor corrects the AI's FINDINGS.

ANALOGY
-------
The AI report is a typed lab sheet. A doctor who disagrees does not scribble on it: they
write a correction slip ("confirm this, strike that, add this, plus a note"). The lab then
types a NEW sheet from the slip, files the old sheet in the archive, and logs who changed
what and when. Nothing is ever overwritten, so the history is always complete.

WHAT ONE EDIT DOES (all-or-nothing, one database transaction)
  1. checks the doctor really looked at the CURRENT version (base_version_no), so two
     people can never silently overwrite each other;
  2. builds the new findings list from the doctor's decisions
        confirm -> stays,  remove -> dropped,  added -> new "doctor_added" finding;
  3. writes a NEW report version (source 'doctor_edit', author = the doctor). The text is
     generated from the edited list by a fixed template, so it mentions ONLY the findings
     that survived the edit (plus the doctor's own note, in the doctor's own words);
  4. marks the old version "not final" (its content is never touched) and the new one final;
  5. gives the new version its pictures (redrawn, or the previous ones - see below);
  6. writes one audit row: who, when, before, after.

  5. (6b) re-draws the highlighted picture and the side-by-side picture from the findings that
     remain, so the pictures never contradict the text. If the AI's circle coordinates were not
     saved (visits made before this step), or the redraw fails, the AI's original pictures are
     kept and the version is marked `images_stale` so the screen can say so honestly.

  6. (6b-2) the doctor may also move / resize / delete / add CIRCLES (regions) for any finding that
     stays. Circles are in pixels of the square-padded X-ray (side = canvas_px), the same space
     Niha's model uses, and every circle is bounds-checked on the server.

NOT HERE YET: the RAG re-index (step 7).
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

import auth_core as core
import redraw
import visit_store

NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
MAX_REGIONS = 5          # circles per finding (the picture draws at most this many)


class EditError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status, self.detail = status, detail


class RegionEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    center_xy: list[int] = Field(min_length=2, max_length=2)
    radius_px: int = Field(ge=4, le=20000)


class FindingsEditIn(BaseModel):
    model_config = ConfigDict(extra="forbid")          # unknown fields (e.g. 'role') are refused
    base_version_no: int = Field(ge=1, le=10_000)
    decisions: dict[str, Literal["confirm", "remove"]] = Field(default_factory=dict, max_length=60)
    added: list[str] = Field(default_factory=list, max_length=10)
    note: str | None = Field(default=None, max_length=2000)
    # 6b-2: the doctor's FINAL circles for findings whose circles they changed ({finding: [circles]}).
    # A finding that is not listed keeps the circles it has. An empty list means "no circle".
    regions: dict[str, Annotated[list[RegionEdit], Field(max_length=MAX_REGIONS)]] = Field(default_factory=dict, max_length=60)

    @field_validator("decisions", "regions")
    @classmethod
    def _names(cls, v):
        if any(not isinstance(k, str) or len(k) > 64 for k in v):
            raise ValueError("finding name too long")
        return v


def normalize_name(raw: str) -> str:
    name = re.sub(r"[\s\-]+", "_", (raw or "").strip().lower())
    if not NAME_RE.match(name):
        raise EditError(422, f"'{raw[:40]}' is not a valid finding name. Use letters, numbers and spaces (2-64 characters).")
    return name


def label(name: str) -> str:
    s = name.replace("_", " ")
    return s[:1].upper() + s[1:]


def finding_detail(f: dict) -> str:
    """One finding in words (used by the report text and by the search index, so they always agree)."""
    if f.get("doctor_status") == "added":
        return "added by the reviewing doctor"
    p = f.get("positive_prob", f.get("probability"))
    return (f"AI probability {p * 100:.1f}%, confirmed by the reviewing doctor"
            if isinstance(p, (int, float)) else "confirmed by the reviewing doctor")


def build_report_text(findings: dict, note: str | None) -> str:
    """Fixed template. Mentions only the findings passed in."""
    lines = ["FINDINGS:"]
    if findings:
        for name, f in findings.items():
            lines.append(f"- {label(name)}: {finding_detail(f)}.")
        impression = "Findings after doctor review: " + ", ".join(label(n) for n in findings) + "."
    else:
        lines.append("- No abnormal findings are reported after doctor review.")
        impression = "No abnormal findings reported after doctor review."
    lines += ["", "IMPRESSION:", impression]
    if note and note.strip():
        lines += ["", "DOCTOR'S NOTE:", note.strip()]
    lines.append("")
    return "\n".join(lines)


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _canvas_of(db, session_id: str, findings: dict) -> int | None:
    """Side of the square the circles live on: what the AI reported (canvas_px), else the stored X-ray's own."""
    seen = {f.get("canvas_px") for f in findings.values() if isinstance(f.get("canvas_px"), int)}
    if len(seen) == 1:
        return seen.pop()
    try:
        xray = visit_store.read_xray_bytes(db, session_id)
        return redraw.canvas_side(xray) if xray else None
    except Exception:
        return None


def _circles(regions) -> list[tuple]:
    return [(tuple(r["center_xy"]), r["radius_px"]) for r in (regions or [])]


def _apply_region_edits(db, session_id: str, old_findings: dict, new_findings: dict, edits: dict) -> list[str]:
    """Writes the doctor's circles into new_findings (in place). Returns the findings whose circles changed."""
    changed: list[str] = []
    if not edits:
        return changed
    canvas = _canvas_of(db, session_id, {**old_findings, **new_findings})
    if canvas is None:
        raise EditError(409, "This visit's X-ray could not be read, so circles cannot be edited.")
    for key, circles in edits.items():
        if key not in new_findings:
            raise EditError(422, f"Circles can only be set for findings that stay in the report ({key[:40]}).")
        for c in circles:
            cx, cy = c.center_xy
            if not (0 <= cx <= canvas and 0 <= cy <= canvas and c.radius_px <= canvas):
                raise EditError(422, "A circle is outside the X-ray picture.")
        f = new_findings[key]
        if isinstance(f.get("regions"), list) and _circles(f["regions"]) == [(tuple(c.center_xy), c.radius_px) for c in circles]:
            continue                                  # same circles as before: keep the AI's own records (bbox, peak...)
        f["regions"] = [{"center_xy": list(c.center_xy), "radius_px": c.radius_px, "source": "doctor"} for c in circles]
        f["region_count"] = len(circles)
        f["localized"] = len(circles) > 0
        f["canvas_px"] = canvas
        f["regions_edited_by_doctor"] = True
        changed.append(key)
    return changed


def _region_summary(findings: dict) -> dict:
    return {k: [[c[0][0], c[0][1], c[1]] for c in _circles(f.get("regions"))] for k, f in findings.items()
            if isinstance(f.get("regions"), list)}


def _discard(paths) -> None:
    for p in paths:
        p.unlink(missing_ok=True)


def _redraw(db, session_id: str, old_findings: dict, new_findings: dict):
    """(images or None, 'redrawn' | 'kept_ai_original'). Never raises: a doctor's correction must not
    be blocked by a picture problem; the version is then simply marked images_stale."""
    try:
        ai_findings = {k: f for k, f in new_findings.items() if f.get("doctor_status") != "added"}
        if any(not isinstance(f.get("regions"), list) for f in ai_findings.values()):
            return None, "kept_ai_original"              # AI coordinates were never saved
        canvases = {f.get("canvas_px") for f in list(old_findings.values()) + list(new_findings.values())
                    if isinstance(f.get("canvas_px"), int)}
        if (not old_findings and not new_findings) or len(canvases) != 1:
            return None, "kept_ai_original"
        xray = visit_store.read_xray_bytes(db, session_id)
        if xray is None:
            return None, "kept_ai_original"
        images = redraw.make_images(xray, new_findings, canvases.pop())
        return (images, "redrawn") if images else (None, "kept_ai_original")
    except Exception:
        return None, "kept_ai_original"


def apply_findings_edit(db, user: dict, session_id: str, edit: FindingsEditIn) -> int:
    """Returns the new version number. Raises EditError(status, detail)."""
    cur = db.execute(
        "SELECT version_id, version_no, report_text, structured_findings FROM report_versions "
        "WHERE session_id = ? AND is_final = 1", (session_id,)).fetchone()
    if cur is None:
        raise EditError(409, "This visit has no saved analysis to edit.")
    if edit.base_version_no != cur["version_no"]:
        raise EditError(409, f"This report has changed (now version {cur['version_no']}). Reload it and review the latest version.")

    old = json.loads(cur["structured_findings"] or "{}")
    old_findings: dict = old.get("findings") or {}

    # Every current finding needs an explicit decision, so nothing is changed by accident.
    unknown = [k for k in edit.decisions if k not in old_findings]
    if unknown:
        raise EditError(422, f"Unknown finding: {unknown[0][:40]}.")
    missing = [k for k in old_findings if k not in edit.decisions]
    if missing:
        raise EditError(422, f"Please confirm or remove every finding (missing: {missing[0]}).")

    added = []
    for raw in edit.added:
        n = normalize_name(raw)
        if n in old_findings or n in added:
            raise EditError(422, f"'{label(n)}' is already in the list.")
        added.append(n)

    note = (edit.note or "").strip() or None
    removed_now = [k for k, d in edit.decisions.items() if d == "remove"]

    new_findings: dict = {}
    for k, f in old_findings.items():
        if edit.decisions[k] == "confirm":
            new_findings[k] = {**f, "doctor_status": "confirmed"}
    for n in added:
        new_findings[n] = {"method": "doctor", "doctor_status": "added"}

    region_changes = _apply_region_edits(db, session_id, old_findings, new_findings, edit.regions)
    if not removed_now and not added and note is None and not region_changes:
        raise EditError(422, "No changes to save: confirm-all with no additions, no circle changes and no note.")

    keep_viz = [d for d in old.get("diseases_visualized", []) if d in new_findings]
    new_structured = {
        **{k: v for k, v in old.items() if k not in ("findings", "diseases_visualized", "removed_findings", "doctor_note", "edited_from_version", "images_stale")},
        "findings": new_findings,
        "diseases_visualized": keep_viz,
        "removed_findings": sorted(set(old.get("removed_findings", [])) | set(removed_now)),
        "doctor_note": note,
        "edited_from_version": cur["version_no"],
    }
    new_text = build_report_text(new_findings, note)
    new_no = cur["version_no"] + 1
    now = core._iso(core.utcnow())

    # 6b: try to redraw the pictures from the findings that remain.
    new_images, picture = _redraw(db, session_id, old_findings, new_findings)
    new_structured["images_stale"] = new_images is None
    written: list = []

    try:
        db.execute("UPDATE report_versions SET is_final = 0 WHERE version_id = ?", (cur["version_id"],))
        ins = db.execute(
            "INSERT INTO report_versions (session_id, version_no, source, author_user_id, created_at, report_text, "
            "structured_findings, is_final) VALUES (?, ?, 'doctor_edit', ?, ?, ?, ?, 1)",
            (session_id, new_no, user["user_id"], now, new_text, json.dumps(new_structured)))
        new_vid = ins.lastrowid
        if new_images is not None:
            written = visit_store.add_version_files(db, session_id, new_vid, new_images, now)
        # Otherwise the new version points at the same picture files as before.
        for r in ([] if new_images is not None else
                  db.execute("SELECT kind, relative_path, mime_type, size_bytes, sha256 FROM visit_files "
                             "WHERE session_id = ? AND version_id = ?", (session_id, cur["version_id"])).fetchall()):
            db.execute("INSERT INTO visit_files (session_id, version_id, kind, relative_path, mime_type, size_bytes, "
                       "sha256, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                       (session_id, new_vid, r["kind"], r["relative_path"], r["mime_type"], r["size_bytes"], r["sha256"], now))
        core.audit(
            db, user["user_id"], user["role"], "doctor_edit_findings", "session", session_id,
            before={"version_no": cur["version_no"], "findings": sorted(old_findings),
                    "text_sha": _digest(cur["report_text"]), "circles": _region_summary(old_findings)},
            after={"version_no": new_no, "findings": sorted(new_findings), "removed": removed_now, "added": added,
                   "note_added": note is not None, "text_sha": _digest(new_text), "picture": picture,
                   "circles_changed": region_changes, "circles": _region_summary(new_findings)})
        db.commit()
    except sqlite3.IntegrityError as e:
        db.rollback()
        _discard(written)
        raise EditError(409, "This report was changed at the same moment. Reload it and try again.") from e
    except Exception:
        db.rollback()
        _discard(written)
        raise
    return new_no
