"""
test_module4.py

Evaluation script for your FYP defense: measures the classifier's routing
accuracy on a paired test set, exactly as you asked -- "how do I show/measure
that it correctly refuses generic questions and correctly answers grounded
ones". Each PAIRED_EXAMPLES entry has a generic version and a session-grounded
version of essentially the same topic, so the demo clearly shows the
classifier is reasoning about grounding, not just keyword-matching a topic.

Run with: python test_module4.py
Does NOT need MedGemma running -- classification only uses Gemini, so you
can run this evaluation even if your Colab notebook is offline.
"""

from classifier import classify_question, SESSION_GROUNDED, GENERIC_KNOWLEDGE

PAIRED_EXAMPLES = [
    ("What is cardiomegaly?", GENERIC_KNOWLEDGE),
    ("Why do I have cardiomegaly?", SESSION_GROUNDED),
    ("What causes pneumonia?", GENERIC_KNOWLEDGE),
    ("Is my pneumonia serious?", SESSION_GROUNDED),
    ("Tell me about lung cancer.", GENERIC_KNOWLEDGE),
    ("What does this shadow in my X-ray mean?", SESSION_GROUNDED),
    ("How does a pleural effusion form?", GENERIC_KNOWLEDGE),
    ("Why was I prescribed this medicine?", SESSION_GROUNDED),
    ("What are the symptoms of pneumothorax in general?", GENERIC_KNOWLEDGE),
    ("Should I be worried about my results?", SESSION_GROUNDED),
    ("Explain what emphysema is.", GENERIC_KNOWLEDGE),
    ("What does my report say is wrong with me?", SESSION_GROUNDED),
    ("What's the difference between a nodule and a mass?", GENERIC_KNOWLEDGE),
    ("Is the spot on my X-ray dangerous?", SESSION_GROUNDED),
    ("How is rib fracture usually treated?", GENERIC_KNOWLEDGE),
    ("Why does my chest hurt according to my scan?", SESSION_GROUNDED),
]


# ── Edge cases — open item #5: "classifier edge cases (ambiguous phrasing,
# multi-condition questions, empty input)". Kept separate from
# PAIRED_EXAMPLES: the adversarial and multi-condition cases DO have one
# objectively correct label and are scored, but the genuinely ambiguous case
# does not (marked expected=None) -- it's reported, not graded, since
# forcing a "correct" answer onto a case that's actually ambiguous by the
# classifier's own two-category definition would just be testing against
# my own guess, not a real spec.
EDGE_CASE_EXAMPLES = [
    # Multi-condition: two findings in one question, still entirely about
    # the patient's own data -- shouldn't get confused by having two topics.
    ("Why do I have both cardiomegaly and pneumonia?", SESSION_GROUNDED),

    # Adversarial "my"-bait: contains "my" (which _SESSION_HINTS' fallback
    # would catch) but is about a FRIEND's condition, not the patient's own.
    # Tests whether the LLM call is doing real reasoning about grounding,
    # not just keyword-matching "my"/"I" -- the rule-based fallback alone
    # would get this wrong.
    ("My friend has pneumonia -- what is it?", GENERIC_KNOWLEDGE),

    # Same trap, different phrasing: "I" appears, but it's a general
    # definitional question, not about the patient's own case.
    ("I read that cardiomegaly can be dangerous -- what does that mean in general?", GENERIC_KNOWLEDGE),

    # All-caps: confirms .lower() normalization actually matters and isn't
    # just coincidentally unnecessary for typical mixed-case input.
    ("WHY DO I HAVE PNEUMONIA", SESSION_GROUNDED),

    # Genuinely ambiguous: mixes a generic "what is X" clause with a
    # grounded "why do I have it" clause in one sentence. No single
    # objectively correct label -- reported, not scored.
    ("What is emphysema and why do I have it?", None),
]


def run_edge_case_evaluation():
    """
    Separate from run_evaluation() above: no single pass/fail accuracy
    number, since one case is intentionally ambiguous. Prints what the
    classifier actually decided for each case, plus a doesn't-crash check
    on empty/whitespace-only input (the third part of open item #5).
    """
    print(f"{'Question':<75} {'Expected':<18} {'Predicted':<18} {'Result'}")
    print("-" * 125)

    scored = 0
    scored_correct = 0
    for question, expected in EDGE_CASE_EXAMPLES:
        predicted = classify_question(question)
        if expected is None:
            expected_display = "(ambiguous)"
            result = "(reported only)"
        else:
            scored += 1
            is_correct = predicted == expected
            scored_correct += is_correct
            expected_display = expected
            result = "YES" if is_correct else "NO"
        print(f"{question:<75} {expected_display:<18} {predicted:<18} {result}")

    print("-" * 125)
    print(f"Scored edge cases: {scored_correct}/{scored} correct (ambiguous case excluded from scoring)")

    print("\nEmpty-input robustness check (no expected label -- just must not crash):")
    for empty_input in ["", "   "]:
        try:
            result = classify_question(empty_input)
            print(f"  classify_question({empty_input!r}) -> {result}  [no crash]")
        except Exception as e:
            print(f"  classify_question({empty_input!r}) -> CRASHED: {type(e).__name__}: {e}")


def run_evaluation():
    correct = 0
    results = []

    for question, expected in PAIRED_EXAMPLES:
        predicted = classify_question(question)
        is_correct = predicted == expected
        correct += is_correct
        results.append((question, expected, predicted, is_correct))

    print(f"{'Question':<55} {'Expected':<20} {'Predicted':<20} {'Correct'}")
    print("-" * 110)
    for question, expected, predicted, is_correct in results:
        mark = "YES" if is_correct else "NO"
        print(f"{question:<55} {expected:<20} {predicted:<20} {mark}")

    accuracy = correct / len(PAIRED_EXAMPLES) * 100
    print("-" * 110)
    print(f"Accuracy: {correct}/{len(PAIRED_EXAMPLES)} ({accuracy:.1f}%)")
    return accuracy


if __name__ == "__main__":
    run_evaluation()
    print()
    run_edge_case_evaluation()
