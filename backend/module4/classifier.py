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

This runs BEFORE any retrieval -- if it's OFF_TOPIC, retrieval and
generation never happen at all. If it's GENERAL_MEDICAL, retrieval is
skipped too (there's no patient data to retrieve for a non-patient-
specific question) but generation still runs, on a different prompt (see
generator.py's generate_general_medical_answer).

Uses Gemini rather than MedGemma (fast, doesn't burden the Colab/ngrok
tunnel with a second call on every question).
"""

from llm_client import call_classifier_llm
from prompts import CLASSIFIER_PROMPT_TEMPLATE
from generator import _format_conversation_history

SESSION_GROUNDED = "SESSION_GROUNDED"
GENERAL_MEDICAL = "GENERAL_MEDICAL"
OFF_TOPIC = "OFF_TOPIC"

_VALID_CLASSIFICATIONS = (SESSION_GROUNDED, GENERAL_MEDICAL, OFF_TOPIC)

# Cheap pre-filter: obvious "my/I" possessive phrasing almost always means
# session-grounded. This does NOT replace the LLM call -- it only acts as
# a fallback when the model's raw response doesn't parse cleanly (see
# below), not a pre-filter that skips the LLM call for obvious cases.
_SESSION_HINTS = ("my ", "i have", "i was", "why do i", "why am i", "is my", "this shadow", "this finding")


def classify_question(question: str, session_id: str | None = None) -> str:
    """
    Returns SESSION_GROUNDED, GENERAL_MEDICAL, or OFF_TOPIC. Always
    returns one of these three constants -- never raw model text -- so
    downstream code can rely on exact string matching.

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

    # Checked in this specific order: SESSION_GROUNDED first, because a
    # question can plausibly mention general medical context AND be about
    # the patient at the same time (e.g. "why do I have pneumonia" touches
    # both) -- when in doubt, prefer grounding in the patient's real data
    # over a generic answer.
    for label in (SESSION_GROUNDED, GENERAL_MEDICAL, OFF_TOPIC):
        if label in raw:
            return label

    # Model returned something unparseable -- fall back to the rule-based
    # hint rather than silently guessing. Prefer SESSION_GROUNDED on a
    # clear personal-phrasing match, otherwise OFF_TOPIC (safer to decline
    # a borderline case than to answer -- as either a patient-specific or
    # general-medical claim -- one that shouldn't be answered).
    if any(hint in q_lower for hint in _SESSION_HINTS):
        return SESSION_GROUNDED
    return OFF_TOPIC
