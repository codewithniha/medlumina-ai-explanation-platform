"""
module5_draw.py  --  Niha's Module 5 drawing code, COPIED into the backend (step 6b).

WHY A COPY
----------
A doctor's edit changes which findings (and, later, which regions) belong on the picture.
Redrawing must not depend on the Kaggle/GPU server being switched on, and the drawing
code itself needs only Pillow. So the two drawing functions are copied here UNCHANGED in
behaviour from module5_visual_explanation/annotate.py and compare.py (copied from
posthoc-notebook-version02, Oct 2026), with the constants from config5.py.

CHANGES FROM NIHA'S ORIGINAL (the only ones):
  1. config5 import -> the constants pasted below (same values).
  2. draw_annotated_xray / make_side_by_side accept a file path OR a file-like object
     (BytesIO) as `out_path`, so the picture can be produced in memory.
  3. The probability line understands the two doctor statuses ('doctor_confirmed',
     'doctor_added'); every other status is drawn exactly as before.
  4. A doctor-added finding with no circle says "(no region marked yet)" instead of the
     AI's "(no region reached the localization threshold)".

If Niha changes her drawing code, re-copy it here so patient and doctor views match.
"""

import math
from typing import Dict, List, Tuple

from PIL import Image, ImageDraw, ImageFont

# ---- constants from config5.py (values unchanged) -------------------------
MAX_REGIONS_PER_DISEASE = 2
CIRCLE_WIDTH = 3
ARROW_WIDTH = 2
ARROWHEAD_LEN = 10
LABEL_MARGIN_WIDTH = 380
LABEL_MARGIN_BG = (18, 18, 18)
LABEL_PADDING = 14
LABEL_BLOCK_GAP = 14
LABEL_LINE_GAP = 4
NAME_FONT_SIZE = 18
PCT_FONT_SIZE = 15
NOTE_FONT_SIZE = 12
FOOTER_FONT_SIZE = 13
PALETTE = [
    (255, 60, 60), (0, 200, 255), (255, 200, 0), (80, 255, 120),
    (255, 0, 200), (170, 130, 255), (255, 150, 0), (100, 255, 255),
]
COMPARISON_GAP_PX = 6
COMPARISON_CAPTION_HEIGHT = 34
COMPARISON_BG = (0, 0, 0)

# ---- annotate.py ----------------------------------------------------------
def _font(size: int) -> ImageFont.ImageFont:
    try:
        return ImageFont.load_default(size=size)   # Pillow >= 10.1
    except TypeError:
        return ImageFont.load_default()             # older Pillow: fixed small bitmap font


def _display_name(disease: str) -> str:
    """'enlarged_cardiomediastinum' -> 'Enlarged Cardiomediastinum'."""
    return disease.replace("_", " ").title()


def _text_width(measure_draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> float:
    return measure_draw.textlength(text, font=font)


def _wrap_text(
    measure_draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont,
    max_width: int, max_lines: int = 2,
) -> List[str]:
    """Greedy word-wrap `text` to fit `max_width` px, measured against the
    ACTUAL font being used (not guessed from character count) -- this is
    what stops a long disease name from running off the margin's edge.
    Truncates with '...' if it still doesn't fit in `max_lines`."""
    words = text.split()
    lines: List[str] = []
    current = ""
    for word in words:
        trial = f"{current} {word}".strip()
        if _text_width(measure_draw, trial, font) <= max_width or not current:
            current = trial
        else:
            lines.append(current)
            current = word
            if len(lines) == max_lines:
                break
    else:
        if current:
            lines.append(current)

    if len(lines) > max_lines:
        lines = lines[:max_lines]

    # If we broke out early (still more words left) or the last line
    # itself overflows, truncate the last line with an ellipsis.
    consumed = sum(len(l.split()) for l in lines)
    overflowed = consumed < len(words) or _text_width(measure_draw, lines[-1], font) > max_width
    if overflowed:
        last = lines[-1]
        while last and _text_width(measure_draw, last + "...", font) > max_width:
            last = last[:-1].rstrip()
        lines[-1] = (last + "...") if last else "..."
    return lines


def _draw_arrowhead(draw: ImageDraw.ImageDraw, start: Tuple[int, int], end: Tuple[int, int],
                     color: Tuple[int, int, int], length: int = ARROWHEAD_LEN) -> None:
    """Small filled triangle at `end`, pointing in the start->end direction."""
    dx, dy = end[0] - start[0], end[1] - start[1]
    dist = math.hypot(dx, dy)
    if dist < 1e-6:
        return
    ux, uy = dx / dist, dy / dist          # unit vector along the arrow
    px, py = -uy, ux                        # perpendicular unit vector
    tip = end
    left = (end[0] - ux * length + px * length * 0.5, end[1] - uy * length + py * length * 0.5)
    right = (end[0] - ux * length - px * length * 0.5, end[1] - uy * length - py * length * 0.5)
    draw.polygon([tip, left, right], fill=color)


def draw_annotated_xray(
    image: Image.Image,
    disease_regions: Dict[str, dict],
    out_path: str,
    max_regions_per_disease: int = MAX_REGIONS_PER_DISEASE,
    circle_width: int = CIRCLE_WIDTH,
    omitted_count: int = 0,
) -> str:
    """
    :param image: the padded SQUARE image the model actually saw
        (BioViLTAligner.encode_image()['padded_image']) -- same
        "what you see is what the model saw" convention Module 2 uses.
    :param disease_regions: {disease: {"probability": float,
        "regions": [<regions.find_biomarker_regions() output>],
        "source_sentence": optional str}}. Iteration order controls
        top-to-bottom label order and color assignment -- callers
        (pipeline.py) pass diseases already sorted (highest
        probability first) and already capped to the diseases actually
        meant to be drawn.
    :param omitted_count: how many additional qualifying diseases exist
        beyond what's in `disease_regions` (e.g. capped by
        MAX_DISEASES_TO_SHOW). When > 0, a footer note is drawn instead
        of silently showing only N diseases with no explanation.
    :return: out_path.
    """
    base = image.convert("RGB")
    img_w, img_h = base.size

    name_font = _font(NAME_FONT_SIZE)
    pct_font = _font(PCT_FONT_SIZE)
    note_font = _font(NOTE_FONT_SIZE)
    footer_font = _font(FOOTER_FONT_SIZE)

    measure_draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))  # text measurement only, not the real canvas
    swatch_r = 7
    text_x_offset = 2 * swatch_r + 10
    text_max_width = LABEL_MARGIN_WIDTH - LABEL_PADDING * 2 - text_x_offset
    line_height = NAME_FONT_SIZE + LABEL_LINE_GAP

    # ---- Pass 1: lay out every label block's content + height BEFORE we
    # know the canvas size, since a long name can need a second line. ----
    blocks = []
    y = LABEL_PADDING
    for i, (disease, info) in enumerate(disease_regions.items()):
        color = PALETTE[i % len(PALETTE)]
        name_lines = _wrap_text(measure_draw, _display_name(disease), name_font, text_max_width, max_lines=2)
        regions = info.get("regions", [])[:max_regions_per_disease]

        block_h = len(name_lines) * line_height + LABEL_LINE_GAP + PCT_FONT_SIZE + 4  # name lines + pct line
        note_text = None
        if not regions:
            note_text = ("(no region marked yet)" if info.get("status") == "doctor_added"
                         else "(no region reached the localization threshold)")
        elif info.get("source_sentence"):
            note_text = _wrap_text(
                measure_draw, f'"{info["source_sentence"].strip()}"', note_font, text_max_width, max_lines=1
            )[0]
        if note_text:
            block_h += NOTE_FONT_SIZE + 6

        blocks.append({
            "disease": disease, "color": color, "name_lines": name_lines,
            "probability": info["probability"], "regions": regions, "status": info.get("status", ""),
            "note_text": note_text, "y": y, "height": block_h,
        })
        y += block_h + LABEL_BLOCK_GAP

    footer_lines: List[str] = []
    if omitted_count > 0:
        footer_lines = _wrap_text(
            measure_draw,
            f"+ {omitted_count} more finding{'s' if omitted_count != 1 else ''} not shown "
            f"(below the top {len(disease_regions)} by probability)",
            footer_font, LABEL_MARGIN_WIDTH - LABEL_PADDING * 2, max_lines=2,
        )
        y += len(footer_lines) * (FOOTER_FONT_SIZE + LABEL_LINE_GAP) + LABEL_BLOCK_GAP

    canvas_h = max(img_h, y + LABEL_PADDING)
    canvas_w = img_w + LABEL_MARGIN_WIDTH
    canvas = Image.new("RGB", (canvas_w, canvas_h), LABEL_MARGIN_BG)
    canvas.paste(base, (0, 0))
    draw = ImageDraw.Draw(canvas)
    draw.line([(img_w, 0), (img_w, canvas_h)], fill=(90, 90, 90), width=1)

    # ---- Pass 2: draw circles on the X-ray + each label block + its arrow ----
    for b in blocks:
        color = b["color"]
        for r in b["regions"]:
            cx, cy = r["center_xy"]
            radius = max(r["radius_px"], 12)  # floor so a tiny/noisy region still shows
            draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], outline=color, width=circle_width)

        label_x = img_w + LABEL_PADDING
        text_x = label_x + text_x_offset
        row_y = b["y"]
        swatch_cy = row_y + NAME_FONT_SIZE // 2
        draw.ellipse([label_x, swatch_cy - swatch_r, label_x + 2 * swatch_r, swatch_cy + swatch_r], fill=color)

        ty = row_y
        for line in b["name_lines"]:
            draw.text((text_x, ty), line, fill=(240, 240, 240), font=name_font)
            ty += line_height
        ty += LABEL_LINE_GAP
        if b.get("status") == "doctor_added":
            pct_text = "Added by the reviewing doctor"
        elif b.get("status") == "doctor_confirmed":
            pct_text = f"Confirmed by doctor - AI {b['probability'] * 100:.0f}%"
        elif b.get("status") == "not_assessed":
            pct_text = "Model: not validated for this finding"
        elif b.get("status") in ("present", "possible"):
            pct_text = f"{b['status'].title()} - calibrated {b['probability'] * 100:.0f}%"
        else:
            pct_text = f"Probability: {b['probability'] * 100:.1f}%"
        draw.text((text_x, ty), pct_text, fill=color, font=pct_font)
        ty += PCT_FONT_SIZE + 4
        if b["note_text"]:
            note_color = (160, 160, 160) if not b["regions"] else (170, 170, 170)
            draw.text((label_x, ty), b["note_text"], fill=note_color, font=note_font)

        if b["regions"]:
            top_region = b["regions"][0]
            rcx, rcy = top_region["center_xy"]
            radius = max(top_region["radius_px"], 12)

            arrow_start = (label_x - LABEL_PADDING // 2, swatch_cy)
            dx, dy = rcx - arrow_start[0], rcy - arrow_start[1]
            dist = math.hypot(dx, dy) or 1.0
            ux, uy = dx / dist, dy / dist
            arrow_end = (int(rcx - ux * radius), int(rcy - uy * radius))

            draw.line([arrow_start, arrow_end], fill=color, width=ARROW_WIDTH)
            _draw_arrowhead(draw, arrow_start, arrow_end, color)

    if footer_lines:
        fy = canvas_h - LABEL_PADDING - len(footer_lines) * (FOOTER_FONT_SIZE + LABEL_LINE_GAP)
        for line in footer_lines:
            draw.text((img_w + LABEL_PADDING, fy), line, fill=(150, 150, 150), font=footer_font)
            fy += FOOTER_FONT_SIZE + LABEL_LINE_GAP

    canvas.save(out_path, format="PNG")
    return out_path


# ---- compare.py ----------------------------------------------------------
def make_side_by_side(
    original: Image.Image,
    annotated: Image.Image,
    out_path: str,
    captions: Tuple[str, str] = ("Original X-ray", "Annotated -- Visual Explanation"),
) -> str:
    """
    :param original: the same padded image passed into
        annotate.draw_annotated_xray() (pre-annotation).
    :param annotated: the image returned by draw_annotated_xray() --
        already includes the label margin, which is fine; the two
        panels don't need to be the same width, only the same height.
    :return: out_path.
    """
    orig = original.convert("RGB")
    ann = annotated.convert("RGB")

    # Match panel heights (scale the shorter one up) so both sit on one
    # row cleanly; width is whatever each panel's own aspect ratio gives.
    target_h = max(orig.height, ann.height)
    if orig.height != target_h:
        orig = orig.resize((int(orig.width * target_h / orig.height), target_h))
    if ann.height != target_h:
        ann = ann.resize((int(ann.width * target_h / ann.height), target_h))

    canvas_w = orig.width + COMPARISON_GAP_PX + ann.width
    canvas_h = target_h + COMPARISON_CAPTION_HEIGHT
    canvas = Image.new("RGB", (canvas_w, canvas_h), COMPARISON_BG)

    canvas.paste(orig, (0, COMPARISON_CAPTION_HEIGHT))
    canvas.paste(ann, (orig.width + COMPARISON_GAP_PX, COMPARISON_CAPTION_HEIGHT))

    draw = ImageDraw.Draw(canvas)
    font = _font(max(14, canvas_w // 60))
    draw.text((8, 8), captions[0], fill=(230, 230, 230), font=font)
    draw.text((orig.width + COMPARISON_GAP_PX + 8, 8), captions[1], fill=(230, 230, 230), font=font)
    draw.line(
        [(orig.width + COMPARISON_GAP_PX // 2, 0), (orig.width + COMPARISON_GAP_PX // 2, canvas_h)],
        fill=(90, 90, 90), width=1,
    )

    canvas.save(out_path, format="PNG")
    return out_path
