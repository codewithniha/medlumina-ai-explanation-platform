"""
module4_pipeline.py

Ties classifier -> [retrieval ->] generation -> session memory together.
REDESIGNED for the three-way classification (see classifier.py): routes to
one of three different paths depending on what the question actually is,
rather than a single retrieve-then-generate path with a binary decline.
"""

from classifier import classify_question, SESSION_GROUNDED, TREND_COMPARISON, GENERAL_MEDICAL, OFF_TOPIC
from retriever import retrieve, get_patient_visit_history
from generator import (
    generate_answer,
    generate_general_medical_answer,
    generate_trend_comparison_answer,
    GENERATION_FAILED_MESSAGE,
    CONNECTION_ERROR_MESSAGE,
)
from prompts import (
    DECLINE_MESSAGE,
    DECLINE_MESSAGE_URDU,
    TREND_NO_PATIENT_MESSAGE,
    TREND_NO_PATIENT_MESSAGE_URDU,
    TREND_INSUFFICIENT_HISTORY_MESSAGE,
    TREND_INSUFFICIENT_HISTORY_MESSAGE_URDU,
)
from session_store import log_turn, session_exists, get_patient_id_for_session


def _is_urdu(text: str) -> bool:
    """
    True if the text contains at least one Urdu/Arabic-script character
    (Unicode range U+0600-U+06FF). Used only to pick which language the
    DECLINE_MESSAGE should be shown in -- the actual answer generation
    does its own language-matching via the LLM prompt instruction, this
    is just for the no-LLM-call decline path.
    """
    return any("\u0600" <= ch <= "\u06FF" for ch in text)


def _failed(answer: str) -> bool:
    return answer in (GENERATION_FAILED_MESSAGE, CONNECTION_ERROR_MESSAGE)


def answer_question(session_id: str, question: str) -> dict:
    """
    Runs the full pipeline for one question and returns a dict with the
    classification decision and the final answer -- classification is
    included in the return value (not hidden) so the API/frontend can show
    it, which is useful for your defense demo.

    Four paths, depending on classify_question()'s result:
    - SESSION_GROUNDED: retrieve from THIS patient's own data, generate a
      grounded answer, real confidence score from retrieval quality.
    - TREND_COMPARISON: retrieve this patient's DATED visit history
      across sessions and generate a comparison, IF there's real history
      to compare -- see the two canned, no-LLM-call cases below for when
      there genuinely isn't.
    - GENERAL_MEDICAL: no patient data involved at all -- answer from
      general medical knowledge. No retrieval happens, so no confidence
      score applies (nothing was matched against anything -- see
      generator.py's generate_general_medical_answer docstring).
    - OFF_TOPIC: declined, in whichever language the question was asked in.
    """
    if not session_exists(session_id):
        return {
            "classification": None,
            "answer": "This session doesn't exist. Please start a new session by uploading a report first.",
            "confidence": None,
            "insufficient_session_data": False,
        }

    classification = classify_question(question, session_id=session_id)

    if classification == OFF_TOPIC:
        answer = DECLINE_MESSAGE_URDU if _is_urdu(question) else DECLINE_MESSAGE
        log_turn(session_id, question, classification, answer)
        return {
            "classification": classification,
            "answer": answer,
            "confidence": None,
            "insufficient_session_data": False,
        }

    if classification == GENERAL_MEDICAL:
        answer = generate_general_medical_answer(session_id=session_id, question=question)
        # No retrieval happened for this path -- there's genuinely nothing
        # to score a confidence against (see generator.py's docstring on
        # why patient data is deliberately excluded here). None, not 0 --
        # same "None means no real signal, not zero" convention used
        # throughout this project. insufficient_session_data is False here
        # too -- that flag specifically means "retrieval ran but had too
        # little to compare", which doesn't apply when retrieval never ran
        # at all (the frontend already shows a different, correct message
        # for GENERAL_MEDICAL via the classification field itself).
        confidence = None
        log_turn(session_id, question, classification, answer, confidence=confidence)
        return {
            "classification": classification,
            "answer": answer,
            "retrieved_session_chunks": [],
            "retrieved_kb_chunks": [],
            "confidence": confidence,
            "insufficient_session_data": False,
        }

    if classification == TREND_COMPARISON:
        patient_id = get_patient_id_for_session(session_id)

        # Case 1: this session was never linked to a saved patient code --
        # there is no "history" to find at all, since sessions.patient_id
        # is how every other visit would be found. Canned message, no LLM
        # call -- there's nothing a model call could add here.
        if patient_id is None:
            answer = TREND_NO_PATIENT_MESSAGE_URDU if _is_urdu(question) else TREND_NO_PATIENT_MESSAGE
            log_turn(session_id, question, classification, answer)
            return {
                "classification": classification,
                "answer": answer,
                "retrieved_session_chunks": [],
                "retrieved_kb_chunks": [],
                "confidence": None,
                "insufficient_session_data": False,
            }

        visits = get_patient_visit_history(patient_id)

        # Case 2: fewer than 2 visits with real data exist for this
        # patient (e.g. this is their first visit, or every other session
        # never finished indexing) -- there's nothing to compare AGAINST.
        # Same reasoning as case 1: canned message, no LLM call.
        if len(visits) < 2:
            answer = (
                TREND_INSUFFICIENT_HISTORY_MESSAGE_URDU if _is_urdu(question)
                else TREND_INSUFFICIENT_HISTORY_MESSAGE
            )
            log_turn(session_id, question, classification, answer)
            return {
                "classification": classification,
                "answer": answer,
                "retrieved_session_chunks": [],
                "retrieved_kb_chunks": [],
                "confidence": None,
                "insufficient_session_data": False,
            }

        # Real comparison: at least 2 dated visits with real data exist.
        answer = generate_trend_comparison_answer(session_id=session_id, question=question, visits=visits)
        # No retrieval-quality confidence score applies here -- this isn't
        # a hybrid-search match against a question, it's a direct,
        # deterministic pull of every real dated visit. Same "None means
        # no applicable signal" convention used for GENERAL_MEDICAL above.
        confidence = None
        log_turn(session_id, question, classification, answer, confidence=confidence)
        return {
            "classification": classification,
            "answer": answer,
            "retrieved_session_chunks": [],
            "retrieved_kb_chunks": [],
            "confidence": confidence,
            "insufficient_session_data": False,
        }

    # classification == SESSION_GROUNDED
    retrieval = retrieve(session_id, question)
    answer = generate_answer(
        session_id=session_id,
        question=question,
        session_chunks=retrieval["session_chunks"],
        kb_chunks=retrieval["kb_chunks"],
    )

    # Confidence reflects how well RETRIEVAL matched the patient's data --
    # it says nothing about whether generation itself actually succeeded.
    # Confirmed live: MedGemma being unreachable still returns a real
    # confidence number attached to the "I couldn't reach the service"
    # fallback message, which is genuinely misleading -- a percentage next
    # to a system error, not an answer. Suppress it in that specific case.
    failed = _failed(answer)
    confidence = None if failed else retrieval["confidence"]
    # Only meaningful to show "not enough data yet" when generation itself
    # actually succeeded -- a failed answer already has its own explanation.
    insufficient_session_data = retrieval["insufficient_session_data"] and not failed

    log_turn(session_id, question, classification, answer, confidence=confidence)
    return {
        "classification": classification,
        "answer": answer,
        "retrieved_session_chunks": retrieval["session_chunks"],
        "retrieved_kb_chunks": retrieval["kb_chunks"],
        "confidence": confidence,
        "insufficient_session_data": insufficient_session_data,
    }
