"""
classifier.py

The explicit, visible routing step: decides whether a question is
"session-grounded" (answerable from THIS patient's own data),
"general-medical" (a real medical knowledge question, not tied to any
specific patient -- answered using general medical knowledge, no patient
data involved), or "off-topic" (not medical at all -- declined).

REDESIGNED per supervisor feedback: this used to be a binary
SESSION_GROUNDED vs GENERIC_KNOWLEDGE(declined) split. The system was
patient-only. Now it also serves doctors and answers real medical
questions generally (e.g. "what is pneumonia") -- only genuinely
off-topic, non-medical questions (e.g. "where is COMSATS") get declined.

Now FOUR-way (was three-way): TREND_COMPARISON added for the
longitudinal-history feature -- when the patient is explicitly asking to
compare their condition across visits ("am I improving?", "compare to
last time"), rather than asking about their current visit alone
(SESSION_GROUNDED). See module4_pipeline.py for how each of the four
routes to a different path.

This runs BEFORE any retrieval -- if it's OFF_TOPIC, retrieval and
generation never happen at all. If it's GENERAL_MEDICAL, retrieval is
skipped too (there's no patient data to retrieve for a non-patient-
specific question) but generation still runs, on a different prompt (see
generator.py's generate_general_medical_answer). TREND_COMPARISON uses
its own retrieval (multiple past visits, not the current session's
hybrid search) and its own generation prompt.

Uses Gemini rather than MedGemma (fast, doesn't burden the Colab/ngrok
tunnel with a second call on every question).
"""

from llm_client import call_classifier_llm
from prompts import CLASSIFIER_PROMPT_TEMPLATE
from generator import _format_conversation_history

SESSION_GROUNDED = "SESSION_GROUNDED"
TREND_COMPARISON = "TREND_COMPARISON"
GENERAL_MEDICAL = "GENERAL_MEDICAL"
OFF_TOPIC = "OFF_TOPIC"

_VALID_CLASSIFICATIONS = (SESSION_GROUNDED, TREND_COMPARISON, GENERAL_MEDICAL, OFF_TOPIC)

# Cheap pre-filter: obvious "my/I" possessive phrasing almost always means
# session-grounded. This does NOT replace the LLM call -- it only acts as
# a fallback when the model's raw response doesn't parse cleanly (see
# below), not a pre-filter that skips the LLM call for obvious cases.
_SESSION_HINTS = ("my ", "i have", "i was", "why do i", "why am i", "is my", "this shadow", "this finding")

# Same fallback-only role as _SESSION_HINTS above, but for genuine
# across-time comparison language. Checked BEFORE _SESSION_HINTS in the
# fallback path below, since these phrases are more specific -- e.g. "is
# my condition better than before" would also match _SESSION_HINTS' "is
# my", but the comparison intent is the more important signal to catch.
_TREND_HINTS = (
    "compare", "compared to", "comparison", "since last", "since my last",
    "last visit", "last time", "previous visit", "previous report",
    "improved", "improving", "getting better", "getting worse",
    "worse now", "better now", "than before", "change since",
)


def classify_question(question: str, session_id: str | None = None) -> str:
    """
    Returns SESSION_GROUNDED, TREND_COMPARISON, GENERAL_MEDICAL, or
    OFF_TOPIC. Always returns one of these four constants -- never raw
    model text -- so downstream code can rely on exact string matching.

    session_id is optional but should always be passed when available --
    without it, a vague follow-up question ("give me a detailed answer of
    this", "tell me more") has NO way to know what topic it's actually
    continuing, and can get misclassified (confirmed live: a follow-up to
    a GENERAL_MEDICAL pneumonia question got classified SESSION_GROUNDED
    instead, and was answered using the patient's unrelated X-ray data).
    """
    q_lower = question.lower().strip()
    conversation_history = (
        _format_conversation_history(session_id) if session_id else "(no session context available)"
    )

    prompt = CLASSIFIER_PROMPT_TEMPLATE.format(
        question=question, conversation_history=conversation_history
    )
    raw = call_classifier_llm(prompt).strip().upper()

    # Checked in this specific order: SESSION_GROUNDED and TREND_COMPARISON
    # first, because a question can plausibly mention general medical
    # context AND be about the patient at the same time (e.g. "why do I
    # have pneumonia" touches both) -- when in doubt, prefer grounding in
    # the patient's real data over a generic answer.
    for label in (SESSION_GROUNDED, TREND_COMPARISON, GENERAL_MEDICAL, OFF_TOPIC):
        if label in raw:
            return label

    # Model returned something unparseable -- fall back to the rule-based
    # hints rather than silently guessing. Trend hints checked first since
    # they're the more specific signal (e.g. "is my condition better than
    # before" would also match a SESSION_HINT's "is my", but the
    # comparison intent is the one that actually matters here). Otherwise
    # prefer SESSION_GROUNDED on a clear personal-phrasing match, otherwise
    # OFF_TOPIC (safer to decline a borderline case than to answer one
    # that shouldn't be answered).
    if any(hint in q_lower for hint in _TREND_HINTS):
        return TREND_COMPARISON
    if any(hint in q_lower for hint in _SESSION_HINTS):
        return SESSION_GROUNDED
    return OFF_TOPIC


# ──────────────────────────────────────────────────────────────────────────────
# OFFLINE VERIFICATION -- no network, no Gemini call needed. Mirrors the
# pattern in session_store.py. This does NOT test the real LLM call (that
# needs a live Gemini API key and is only verifiable on your machine) --
# it tests the deterministic FALLBACK path (the hint lists above) by
# forcing call_classifier_llm to return unparseable garbage, so the
# fallback logic is what actually decides the result. This is the part
# that MUST be right on its own, since it's what protects the system when
# the LLM response can't be parsed.
# ──────────────────────────────────────────────────────────────────────────────
def _offline_verification() -> bool:
    import sys
    # sys.modules[__name__] -- NOT `import classifier as _self`. When this
    # file is run directly (`python classifier.py`), it executes as
    # `__main__`, and `import classifier` in that situation creates a
    # SECOND, separate copy of the module rather than referring back to
    # the one actually running -- patching that second copy does nothing
    # to the real classify_question() still in use. Confirmed live: the
    # first version of this fix used `import classifier as _self` and
    # still made real (failing) network calls to Gemini despite the
    # patch appearing to succeed. sys.modules[__name__] always resolves
    # to the actual running module, whether invoked as __main__ or
    # imported normally elsewhere.
    _self = sys.modules[__name__]

    passed = 0
    failed = 0

    def check(label, condition):
        nonlocal passed, failed
        status = "PASS" if condition else "FAIL"
        print(f"  [{status}] {label}")
        if condition:
            passed += 1
        else:
            failed += 1

    # classifier.py does `from llm_client import call_classifier_llm`, which
    # binds the NAME call_classifier_llm directly in classifier.py's own
    # namespace -- patching llm_client.call_classifier_llm would NOT
    # intercept it (confirmed live: the first version of this test did
    # exactly that and hung trying to reach the real Gemini API with a
    # dummy key, since network to generativelanguage.googleapis.com isn't
    # available in this sandbox). Patching classifier.call_classifier_llm
    # (this module's own name) is what actually intercepts the call.
    original_call = _self.call_classifier_llm
    _self.call_classifier_llm = lambda prompt: "UNPARSEABLE GARBLED RESPONSE"

    try:
        print("\n[TEST 1] Trend-comparison phrasing falls back to TREND_COMPARISON")
        check("'Am I improving since my last visit?'",
              classify_question("Am I improving since my last visit?") == TREND_COMPARISON)
        check("'Compare my current X-ray with my last one'",
              classify_question("Compare my current X-ray with my last one") == TREND_COMPARISON)
        check("'Is my condition worse now than before?'",
              classify_question("Is my condition worse now than before?") == TREND_COMPARISON)

        print("\n[TEST 2] Ordinary session-grounded phrasing still falls back to SESSION_GROUNDED, not TREND_COMPARISON")
        check("'Why do I have pneumonia?'",
              classify_question("Why do I have pneumonia?") == SESSION_GROUNDED)
        check("'Is my pneumonia serious?'",
              classify_question("Is my pneumonia serious?") == SESSION_GROUNDED)

        print("\n[TEST 3] Genuinely off-topic phrasing still falls back to OFF_TOPIC")
        check("'Where is COMSATS?'",
              classify_question("Where is COMSATS?") == OFF_TOPIC)

        print("\n[TEST 4] classify_question() always returns one of the four valid constants, never raw text")
        for q in ("Am I improving?", "Why do I have this?", "What is pneumonia?", "Where is COMSATS?"):
            check(f"'{q}' returns a valid classification", classify_question(q) in _VALID_CLASSIFICATIONS)

    finally:
        _self.call_classifier_llm = original_call

    print("\n" + "=" * 60)
    print(f"{passed}/{passed + failed} offline verification tests passed.")
    print("=" * 60)
    return failed == 0


if __name__ == "__main__":
    _offline_verification()
