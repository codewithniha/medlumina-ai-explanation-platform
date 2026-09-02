"""
generator.py

Builds the final grounded prompt (FE-3, FE-4) and calls MedGemma. This is
where the "answer only from patient data, KB is supporting-only" constraint
gets enforced explicitly in text -- the third and final layer of that
protection, after the classifier and the retrieval scoping in retriever.py.

Also handles FE-4 (adapting explanation complexity / conversational memory)
by folding recent conversation turns into the prompt so follow-ups have
context, and by instructing the model to keep language plain by default.
"""

from llm_client import call_medgemma
from prompts import (
    GENERATION_PROMPT_TEMPLATE,
    GENERAL_MEDICAL_PROMPT_TEMPLATE,
    TREND_COMPARISON_PROMPT_TEMPLATE,
    SIMPLE_EXPLANATION_INSTRUCTION,
    DETAILED_EXPLANATION_INSTRUCTION,
)
from session_store import get_recent_turns, get_explanation_level

# Named so module4_pipeline.py can check `answer in (GENERATION_FAILED_MESSAGE,
# CONNECTION_ERROR_MESSAGE)` precisely and suppress the confidence score in
# that case, instead of matching against duplicated inline strings that
# could silently drift out of sync with the actual returned text.
GENERATION_FAILED_MESSAGE = (
    "I wasn't able to generate an answer just now. Please try asking again in a moment."
)
CONNECTION_ERROR_MESSAGE = (
    "I couldn't reach the medical analysis service right now (it may be offline). "
    "Please make sure the MedGemma server is running and try again."
)


def _is_urdu(text: str) -> bool:
    """True if text contains at least one Urdu/Arabic-script character."""
    return any("\u0600" <= ch <= "\u06FF" for ch in text)


def _looks_like_urdu_response(text: str) -> bool:
    """
    True if a meaningful fraction of MedGemma's answer is actually in Urdu
    script -- used to VERIFY the language-matching instruction in
    prompts.py actually worked, rather than just trusting it did.

    Confirmed live (real test, zero conversation history): a genuine
    Urdu-script question can still get answered entirely in English --
    the prompt instruction is a soft one an LLM can ignore, not a hard
    guarantee. This is the check that catches that failure so it can be
    corrected (see the retry in generate_answer below) instead of
    silently shipping a wrong-language answer.

    Threshold is deliberately low (15%, not "mostly Urdu") -- a genuinely
    correct Urdu answer still legitimately contains Latin-script medicine
    names (e.g. "Tiotropium") and digits, so demanding a high fraction
    would create false positives on answers that are actually fine.
    """
    if not text:
        return False
    urdu_chars = sum(1 for ch in text if "\u0600" <= ch <= "\u06FF")
    return urdu_chars / max(len(text), 1) > 0.15


def _format_conversation_history(session_id: str) -> str:
    turns = get_recent_turns(session_id, limit=5)
    if not turns:
        return "(no previous conversation this session)"
    lines = []
    for t in turns:
        lines.append(f"Patient asked: {t['question']}")
        lines.append(f"You answered: {t['answer']}")
    return "\n".join(lines)


def _extract_single_language_answer(text: str, want_urdu: bool) -> str:
    """
    Replaces the earlier narrower _strip_leaked_language_label. Confirmed
    live, repeatedly, that chasing individual label WORDINGS with regex is
    a losing game -- "Urdu Answer:", then later just "Urdu:", a new
    variant each time. This instead handles the actual underlying failure
    mode directly:

    1. MedGemma sometimes answers in BOTH languages at once, clearly
       divided by section markers ("Urdu: ... English: ..." or the
       reverse) -- confirmed live. If that pattern is detected, extract
       ONLY the block matching the language actually needed and discard
       the rest, rather than showing both to the patient.
    2. Whatever single-language text remains, strip one leading label if
       there's still one (broadened to catch known variants -- urdu/
       english/corrected/important, optionally followed by answer/note --
       without being so generic it risks stripping legitimate content
       that happens to start with an unrelated word and a colon).
    """
    import re

    markers = list(re.finditer(r"\b(urdu|english)\s*:\s*", text, flags=re.IGNORECASE))
    if len(markers) >= 2:
        segments = []
        for idx, m in enumerate(markers):
            start = m.end()
            end = markers[idx + 1].start() if idx + 1 < len(markers) else len(text)
            segments.append((m.group(1).lower(), text[start:end].strip()))
        wanted = "urdu" if want_urdu else "english"
        matching = [seg for lang, seg in segments if lang == wanted]
        if matching:
            text = matching[0]

    text = re.sub(
        r"^\s*\**\s*(urdu|english|corrected|important)\s*(answer|note)?\s*:?\s*\**\s*:?\s*",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip()
    return text


def _call_medgemma_with_language_guarantee(prompt: str, question: str) -> str:
    """
    Shared by generate_answer() and generate_general_medical_answer(): calls
    MedGemma, cleans up any leaked language label or dual-language-block
    response, and verifies the answer actually matches the question's
    language -- forcing one corrective retry if not. See generate_answer's
    original inline version (now here) for the full history of why each
    piece of this exists; extracted here so both generation paths get the
    same guarantee instead of duplicating ~40 lines twice.
    """
    try:
        answer = call_medgemma(prompt)
        if not answer:
            return GENERATION_FAILED_MESSAGE

        question_is_urdu = _is_urdu(question)
        answer = _extract_single_language_answer(answer, want_urdu=question_is_urdu)
        answer_is_urdu = _looks_like_urdu_response(answer)

        if question_is_urdu != answer_is_urdu:
            right_lang_full = "Urdu (Arabic/Nastaliq script only)" if question_is_urdu else "English"
            ANSWER_CUE = "Answer:"
            prompt_body = prompt[: -len(ANSWER_CUE)] if prompt.endswith(ANSWER_CUE) else prompt
            retry_prompt = (
                prompt_body
                + f"\n\nFINAL INSTRUCTION, overriding anything above if there is any "
                  f"conflict: your entire response must be written in {right_lang_full}, "
                  f"from the very first word. Do not mention what language you are "
                  f"writing in, do not add any label, heading, or note about language "
                  f"or corrections, do not repeat or restate the question -- begin "
                  f"immediately with the actual answer content, exactly as a doctor's "
                  f"assistant would normally respond.\n\n{ANSWER_CUE}"
            )
            retried = call_medgemma(retry_prompt)
            retried = _extract_single_language_answer(retried, want_urdu=question_is_urdu) if retried else retried
            retried_is_urdu = _looks_like_urdu_response(retried) if retried else False
            if retried and retried_is_urdu == question_is_urdu:
                return retried
            # Even the forced retry didn't produce the right language --
            # return the original answer rather than nothing. A readable
            # wrong-language answer is better than silently failing or
            # blocking the user entirely.

        return answer
    except ConnectionError:
        return CONNECTION_ERROR_MESSAGE


def generate_answer(session_id: str, question: str, session_chunks: list[str], kb_chunks: list[str]) -> str:
    """
    Constructs the grounded prompt and calls MedGemma. If MedGemma is
    unreachable (Colab not running / ngrok URL stale), fails safely with a
    clear message rather than crashing the request or silently returning
    nothing -- this matters because a silent failure here is exactly the
    kind of bug that caused Module 6's safety-net issue on the API-failure
    path. We don't want the same class of bug in Module 4.
    """
    session_context = "\n".join(f"- {c}" for c in session_chunks) if session_chunks else "(no matching data found in patient's report/findings)"
    kb_context = "\n".join(f"- {c}" for c in kb_chunks) if kb_chunks else "(no supporting definitions needed for this question)"
    conversation_history = _format_conversation_history(session_id)

    # ── FE-4: knowledge-level adaptation ────────────────────────────────────
    # Read back what the patient set at /session/start (or later changed via
    # /session/explanation_level). Same fetch-by-session_id pattern already
    # used for conversation_history above -- keeps this contained to
    # generator.py + session_store.py rather than threading a new parameter
    # through answer_question()/retrieve() in module4_pipeline.py.
    explanation_level = get_explanation_level(session_id)
    complexity_instruction = (
        DETAILED_EXPLANATION_INSTRUCTION
        if explanation_level == "detailed"
        else SIMPLE_EXPLANATION_INSTRUCTION
    )

    prompt = GENERATION_PROMPT_TEMPLATE.format(
        session_context=session_context,
        kb_context=kb_context,
        conversation_history=conversation_history,
        complexity_instruction=complexity_instruction,
        question=question,
    )

    return _call_medgemma_with_language_guarantee(prompt, question)


def _format_visit_history(visits: list[dict]) -> str:
    """
    Turns retriever.get_patient_visit_history()'s output into the dated,
    ordered text block the TREND_COMPARISON_PROMPT_TEMPLATE expects.
    visits must already be in chronological order (earliest first) --
    this function does not re-sort, it only formats and numbers them, so
    the "Visit 1/2/3" numbering in the prompt matches the real visit
    order rather than accidentally relabeling them.
    """
    if not visits:
        return "(no visit history available)"
    blocks = []
    for i, v in enumerate(visits, start=1):
        # Minute-precision timestamp (UTC, matching how created_at is
        # actually stored -- see session_store.py's
        # datetime.now(timezone.utc).isoformat()), NOT date-only.
        # Confirmed live: two visits created minutes apart during the
        # same testing session both showed as "2026-09-02" with a
        # date-only label, making them visually indistinguishable in the
        # answer even though the underlying chronological ORDER (driven
        # by the real created_at sort in retriever.py, not by this label)
        # was always correct. This is purely a display fix -- it changes
        # nothing about which visit is Visit 1 vs Visit 2.
        # created_at is stored like "2026-09-02T17:18:03.123456+00:00";
        # [:16] keeps "2026-09-02T17:18", then swap T for a space.
        timestamp_str = v["created_at"][:16].replace("T", " ") + " UTC"
        chunk_lines = "\n".join(f"  - {c}" for c in v["chunks"])
        blocks.append(f"Visit {i} -- {timestamp_str}:\n{chunk_lines}")
    return "\n\n".join(blocks)


def generate_trend_comparison_answer(session_id: str, question: str, visits: list[dict]) -> str:
    """
    Constructs the trend-comparison prompt from a patient's dated visit
    history and calls MedGemma. Mirrors generate_answer()'s structure
    (same complexity/language handling, same failure-safe pattern) but
    grounds the answer in MULTIPLE dated visits instead of one session's
    chunks -- see TREND_COMPARISON_PROMPT_TEMPLATE's strict rules for how
    cross-visit comparison is constrained to avoid an invented trend.

    Callers (module4_pipeline.py) are responsible for the two cases that
    should NEVER reach this function at all: no patient_id linked to this
    session, or fewer than 2 visits with real data -- those get a canned,
    deterministic message instead (see prompts.py's
    TREND_NO_PATIENT_MESSAGE / TREND_INSUFFICIENT_HISTORY_MESSAGE), since
    there is no real comparison to ground an LLM call in for either case.
    """
    visit_history = _format_visit_history(visits)
    conversation_history = _format_conversation_history(session_id)

    explanation_level = get_explanation_level(session_id)
    complexity_instruction = (
        DETAILED_EXPLANATION_INSTRUCTION
        if explanation_level == "detailed"
        else SIMPLE_EXPLANATION_INSTRUCTION
    )

    prompt = TREND_COMPARISON_PROMPT_TEMPLATE.format(
        visit_history=visit_history,
        conversation_history=conversation_history,
        complexity_instruction=complexity_instruction,
        question=question,
    )

    return _call_medgemma_with_language_guarantee(prompt, question)


def generate_general_medical_answer(session_id: str, question: str) -> str:
    """
    NEW (supervisor-requested scope expansion): answers a real medical
    knowledge question that is NOT about any specific patient -- e.g.
    "what is pneumonia", useful to both patients and doctors. Deliberately
    does NOT receive session_chunks/kb_chunks -- there's no patient data
    to ground this in, and mixing patient-specific context into a general
    answer would blur the exact line the classifier just drew.

    DOES receive conversation_history, though -- that's a different thing
    from patient data (it's just the recent back-and-forth), and it's
    needed for follow-up continuity: confirmed live that a vague
    follow-up ("give me a detailed answer of this") after a GENERAL_
    MEDICAL question about pneumonia needs to know it's still about
    pneumonia, not answer blind.

    Still reads the session's explanation_level so simple/detailed stays
    consistent with the rest of that session's answers, and gets the
    exact same language-matching guarantee as patient-specific answers.
    """
    explanation_level = get_explanation_level(session_id)
    complexity_instruction = (
        DETAILED_EXPLANATION_INSTRUCTION
        if explanation_level == "detailed"
        else SIMPLE_EXPLANATION_INSTRUCTION
    )
    conversation_history = _format_conversation_history(session_id)

    prompt = GENERAL_MEDICAL_PROMPT_TEMPLATE.format(
        complexity_instruction=complexity_instruction,
        conversation_history=conversation_history,
        question=question,
    )

    return _call_medgemma_with_language_guarantee(prompt, question)
