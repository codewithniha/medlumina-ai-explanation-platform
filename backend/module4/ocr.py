"""
ocr.py

Transcribes a doctor's handwritten report from a photo/scan into real text,
so it can flow into the exact same doctor_report pipeline Module 4 already
has (session_indexer.py, retrieval, generation) -- this is deliberately
NOT a separate "image understanding" path, it's a text-extraction step
that feeds the existing, already-tested text pipeline.

Uses Gemini's vision capability (same GEMINI_API_KEY already configured
for the classifier) rather than a dedicated OCR service -- no new API key,
no new service to set up, and general-purpose multimodal models handle
messy handwriting noticeably better than traditional character-recognition
OCR engines (which are built for printed text, not doctors' handwriting).

Deliberately does NOT use MedGemma for this -- MedGemma runs on your own
Colab GPU and its multimodal training (if the variant you're running even
has vision at all) is aimed at clinical images like X-rays, not general
handwriting transcription. Gemini's cloud API is a better fit for this
specific task and doesn't depend on your Colab tunnel being up.

RELIABILITY DESIGN (added after a real, confirmed failure): a single
transcription pass isn't reliable enough on its own for ambiguous
handwriting -- confirmed live, the SAME photo, transcribed via two
SEPARATE full pipeline runs, gave two DIFFERENT confident numbers (44 vs
24) for a weight field, with no uncertainty marker in either run. This
means even a single PAIR of readings can coincidentally agree with EACH
OTHER by chance without the underlying digit actually being clear --
temperature=0 reduces randomness but does not eliminate it, and two
readings landing on the same wrong answer is possible, not just two
readings landing on two different answers. The fix: run the
transcription THREE times, independently, then send all three results to
a final call that reconciles them -- keeping whatever attempts agree on
(real agreement should show up in at least 2 of 3, not just a lucky
pair), and explicitly marking anywhere they genuinely disagree as
[UNCERTAIN: ...].
"""

import base64

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage

from llm_client import GEMINI_API_KEY

_ocr_model = None

TRANSCRIPTION_PROMPT = """You are transcribing a doctor's handwritten medical report from a photo. Doctors' handwriting is often messy -- do your best, but accuracy matters more than completeness here, since this text will be used to answer a patient's real medical questions.

RULES:
1. Transcribe the text as faithfully as you can, preserving medical terminology, medicine names, and dosages exactly as written.
2. If a word or phrase is genuinely illegible, write [illegible] in its place -- do NOT guess or invent text that might not actually be there. A wrong guess in a medical report is worse than an honest gap.
3. MEDICINE NAMES, DOSAGE NUMBERS, AND ANY OTHER NUMERIC FIELD (age, weight, BP, HR, temperature, SPO2, R/R) ARE THE HIGHEST-STAKES PART OF THIS -- a patient often cannot read the original handwriting themselves, so they cannot catch a wrong guess by checking it against the photo. For every medicine name, dosage number, frequency (e.g. "BD", "OD", "SOS"), or numeric vital sign, only write it plainly if you are genuinely confident. If you are making an educated guess rather than being sure -- e.g. the handwriting is ambiguous between two plausible drug names, or a digit could be a 2 or a 4 or a 9 -- write it as [UNCERTAIN: your best guess] instead of presenting it as definite. Do this MORE liberally for medicines/dosages/numbers than for general narrative text.
4. Preserve the original language -- if the report is written in Urdu, transcribe it in Urdu script, not English.
5. Output ONLY the transcribed text itself -- no preamble like "Here is the transcription:", no commentary, no formatting markup.
6. If the image doesn't contain any readable handwritten medical text at all (e.g. it's blank, or an unrelated photo), say exactly: NO_TEXT_FOUND

Transcribe the report now:"""

RECONCILIATION_PROMPT_TEMPLATE = """You are reconciling multiple INDEPENDENT transcription attempts of the same handwritten medical report photo, made separately by an AI reading the same image several times.

YOUR JOB: produce ONE final transcription.
- Where the attempts genuinely AGREE (same words, same numbers) -- ideally at least 2 out of the attempts given -- use that text directly. Real agreement across independent readings is a meaningful confidence signal.
- Where the attempts DISAGREE on a word, medicine name, or number (including a near-even split, e.g. 2 say one thing and 1 says another, or all three differ), this is REAL EVIDENCE of ambiguity -- write it as [UNCERTAIN: option A / option B / ...] showing the different readings, even if any individual attempt stated it plainly. Do not silently pick one over the others just because it appeared first.
- If any attempt already marked something as [UNCERTAIN: ...] or [illegible], take that seriously even if the other attempts stated it plainly -- preserve the uncertainty in the final version rather than letting confident-sounding attempts overrule an honest flag.
- Keep the original structure and language of the report.
- Output ONLY the final reconciled transcription -- no preamble, no commentary about the reconciliation process itself.

{attempts_block}

Final reconciled transcription:"""


def _get_ocr_model():
    global _ocr_model
    if _ocr_model is None:
        if not GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY is not set -- check your .env file.")
        _ocr_model = ChatGoogleGenerativeAI(
            model="gemini-3.1-flash-lite",
            google_api_key=GEMINI_API_KEY,
            temperature=0,  # minimizes (does not eliminate -- see module docstring) randomness
        )
    return _ocr_model


def _run_single_transcription(image_bytes: bytes, mime_type: str) -> str:
    """One independent transcription attempt. Returns '' for NO_TEXT_FOUND
    or an empty response -- never raises for that case, only for a real
    API failure (see caller)."""
    b64_image = base64.b64encode(image_bytes).decode("utf-8")
    message = HumanMessage(
        content=[
            {"type": "text", "text": TRANSCRIPTION_PROMPT},
            {"type": "image_url", "image_url": f"data:{mime_type};base64,{b64_image}"},
        ]
    )
    model = _get_ocr_model()
    response = model.invoke([message])
    text = (response.content or "").strip()
    return "" if text == "NO_TEXT_FOUND" else text


def _reconcile(attempts: list[str]) -> str:
    """Sends all independent attempts back to Gemini for comparison --
    letting the model do the comparison rather than a hand-built text-diff
    algorithm, since free-form handwriting transcriptions won't be
    byte-identical even when semantically consistent (spacing, line
    breaks, etc.), and a naive string diff would produce false
    disagreements on formatting alone."""
    model = _get_ocr_model()
    attempts_block = "\n\n".join(
        f"--- ATTEMPT {i + 1} ---\n{a}" for i, a in enumerate(attempts)
    )
    prompt = RECONCILIATION_PROMPT_TEMPLATE.format(attempts_block=attempts_block)
    response = model.invoke([HumanMessage(content=prompt)])
    return (response.content or "").strip()


def transcribe_handwritten_report(image_bytes: bytes, mime_type: str) -> str:
    """
    Runs THREE independent transcription attempts and reconciles them into
    one final result -- see module docstring for why even two attempts
    aren't reliable enough on their own (confirmed live: two SEPARATE full
    runs, each already comparing a pair internally, still landed on two
    different confident numbers across the two runs). A third independent
    reading makes coincidental pairwise agreement far less likely to slip
    through unchallenged.

    Returns an empty string if no readable text was found in any attempt.

    Raises ConnectionError only if fewer than 2 of the 3 attempts
    succeeded (not enough to cross-check at all). If at least 2 succeed,
    degrades gracefully and reconciles whatever did succeed, rather than
    failing the whole request over one transient failure.
    """
    attempts: list[str] = []
    first_error: Exception | None = None

    for _ in range(3):
        try:
            result = _run_single_transcription(image_bytes, mime_type)
            attempts.append(result)
        except Exception as e:
            if first_error is None:
                first_error = e

    if len(attempts) < 2:
        raise ConnectionError(f"Could not reach the OCR service: {first_error}")

    non_empty = [a for a in attempts if a]
    if not non_empty:
        return ""  # every successful attempt found no readable text
    if len(non_empty) == 1:
        # Only one attempt found real text -- can't cross-check this one,
        # but returning it is more useful than discarding it.
        return non_empty[0]

    try:
        return _reconcile(non_empty)
    except Exception:
        # Reconciliation call itself failed -- fall back to the longest
        # individual attempt (a rough proxy for "most complete") rather
        # than losing every real transcription attempt over a failure in
        # the final, reconciliation-only call.
        return max(non_empty, key=len)


def transcribe_report_from_pdf(pdf_bytes: bytes, max_pages: int = 5) -> str:
    """
    Handles a doctor's report submitted as a PDF, not a photo -- real
    hospitals commonly issue typed/printed reports this way, not just
    handwritten photos. Two different extraction paths, chosen PER PAGE:

    1. If the page has a real embedded text layer (a typed/printed PDF,
       not a scan), extract that text DIRECTLY -- fast, free, and more
       accurate than OCR, since it's the actual original text, not a
       machine's best guess from a picture of it.
    2. If a page has no real text layer (a scanned image saved as PDF),
       render that page as an image and run it through the SAME 3-way
       consensus OCR pipeline already used for photos -- a scanned page
       has exactly the same reliability concerns as a photo, so it gets
       exactly the same reliability treatment, not a shortcut.

    Capped at max_pages (default 5) -- a full multi-page chart isn't the
    real use case here (a single visit's report/prescription), and
    processing an unbounded number of pages could mean an unbounded
    number of OCR calls if every page turned out to be scanned images.
    """
    import fitz  # PyMuPDF

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    page_texts = []

    for page_index, page in enumerate(doc):
        if page_index >= max_pages:
            break

        real_text = page.get_text().strip()
        # A short fragment (e.g. a page number, a header) isn't a real
        # text layer worth trusting over OCR -- only treat this page as
        # "has real text" if there's a meaningful amount of it.
        if len(real_text) > 40:
            page_texts.append(real_text)
            continue

        # No usable text layer -- this page is a scan. Render it as an
        # image and route through the exact same OCR pipeline as a photo
        # upload, same reliability guarantees.
        pixmap = page.get_pixmap(dpi=200)
        image_bytes = pixmap.tobytes("png")
        try:
            page_ocr_text = transcribe_handwritten_report(image_bytes, "image/png")
        except ConnectionError:
            page_ocr_text = ""
        if page_ocr_text:
            page_texts.append(page_ocr_text)

    doc.close()

    if not page_texts:
        return ""
    return "\n\n".join(page_texts)
