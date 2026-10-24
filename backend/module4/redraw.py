"""
redraw.py  --  Step 6b: redraw the highlighted picture from a version's findings.

ANALOGY
-------
The highlighted X-ray is a transparency (clear sheet) laid over the film, with a coloured
circle for each finding. When the doctor strikes a finding off the report, the old
transparency would still show its circle, so the picture would contradict the text. This
file makes a fresh transparency from the findings that remain, and lays it over the SAME film.

HOW COORDINATES WORK
--------------------
Niha's Module 5 measures every circle on the model's SQUARE-padded copy of the X-ray (the
short side padded with black so the picture is a square of side max(width, height)); the
side is sent along as `canvas_px`. We rebuild exactly that square from the stored X-ray and
refuse to draw if the sizes disagree, because circles on the wrong film would be worse than
no redraw.
"""

from __future__ import annotations

import io

from PIL import Image

import module5_draw as draw5

MAX_REGIONS_DRAWN = 5


def letterbox(img: Image.Image) -> Image.Image:
    """Same as Niha's preprocessing.letterbox: centre on a black square of side max(w, h)."""
    w, h = img.size
    side = max(w, h)
    canvas = Image.new(img.mode, (side, side), 0)
    canvas.paste(img, ((side - w) // 2, (side - h) // 2))
    return canvas


def canvas_side(xray_bytes: bytes) -> int:
    with Image.open(io.BytesIO(xray_bytes)) as im:
        return max(im.size)


def make_images(xray_bytes: bytes, findings: dict, canvas_px: int) -> dict[str, bytes] | None:
    """
    findings: {name: {positive_prob/probability, regions: [...], doctor_status}} in display order.
    Returns {'annotated': png_bytes, 'comparison': png_bytes}, or None if the stored X-ray does not
    match the geometry the regions were measured on.
    """
    with Image.open(io.BytesIO(xray_bytes)) as im:
        gray = im.convert("L")
    if max(gray.size) != int(canvas_px):
        return None
    square = letterbox(gray)

    disease_regions = {}
    for name, f in findings.items():
        p = f.get("positive_prob", f.get("probability"))
        status = {"added": "doctor_added", "confirmed": "doctor_confirmed"}.get(f.get("doctor_status"), "")
        disease_regions[name] = {
            "probability": float(p) if isinstance(p, (int, float)) else 0.0,
            "regions": [
                {"center_xy": tuple(r["center_xy"]), "radius_px": int(r["radius_px"])}
                for r in (f.get("regions") or [])
            ],
            "status": status,
        }

    ann_buf = io.BytesIO()
    draw5.draw_annotated_xray(square, disease_regions, ann_buf, max_regions_per_disease=MAX_REGIONS_DRAWN)
    ann_buf.seek(0)
    annotated = Image.open(ann_buf)
    annotated.load()
    cmp_buf = io.BytesIO()
    draw5.make_side_by_side(square, annotated, cmp_buf)
    return {"annotated": ann_buf.getvalue(), "comparison": cmp_buf.getvalue()}
