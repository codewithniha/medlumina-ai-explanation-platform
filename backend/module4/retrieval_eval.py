"""
retrieval_eval.py

test_module4.py measures classifier accuracy (did we route the question
correctly). This measures something different and equally important for
your defense: given a SESSION_GROUNDED question, did retrieval actually
pull back the RIGHT chunk from the patient's session data?

This directly demonstrates the hybrid search + reranking upgrade is doing
its job, not just "the code runs" -- for each test case, we create a real
session with sample report data, ask a question, and check whether the
chunk we EXPECT to be the top result is actually in the top result(s).

Run with: python retrieval_eval.py
Needs the KB indexed (run kb_indexer.py first) -- does NOT need MedGemma
running, since this only tests retrieval, not generation.
"""

from session_indexer import index_session_data
from retriever import retrieve_session_context
from session_store import create_session

# Each case: a sample doctor report/findings, a question, and a keyword we
# expect to appear in the TOP retrieved chunk. Keyword-based checking (not
# exact string match) because chunk text may be phrased slightly
# differently -- what matters is whether the right FACT came back on top.
TEST_CASES = [
    {
        "report": "Chest X-ray shows cardiomegaly with mild pulmonary vascular congestion. No acute infiltrate.",
        "findings": {"Cardiomegaly": "heart size enlarged, cardiothoracic ratio 0.58"},
        "medicines": ["Furosemide 20mg"],
        "question": "Why is my heart enlarged?",
        "expect_keyword": "cardiomegaly",
    },
    {
        "report": "Right lower lobe consolidation consistent with pneumonia. Patient febrile at presentation.",
        "findings": {"Pneumonia": "right lower lobe consolidation"},
        "medicines": ["Amoxicillin 500mg"],
        "question": "What did you find in my lungs?",
        "expect_keyword": "pneumonia",
    },
    {
        "report": "Small right-sided pleural effusion noted. Recommend clinical correlation.",
        "findings": {"Pleural Effusion": "small right-sided effusion"},
        "medicines": [],
        "question": "Is there fluid around my lung?",
        "expect_keyword": "effusion",
    },
    {
        "report": "No acute cardiopulmonary abnormality. Rib series shows healed fracture, right 7th rib.",
        "findings": {"Rib Fracture": "healed fracture, right 7th rib"},
        "medicines": ["Ibuprofen 400mg"],
        "question": "Why does my chest hurt when I breathe?",
        "expect_keyword": "rib",
    },
    {
        "report": "Findings consistent with emphysema, hyperinflated lung fields bilaterally.",
        "findings": {"Emphysema": "hyperinflated lung fields"},
        "medicines": ["Tiotropium inhaler"],
        "question": "Why is it getting harder to breathe over time?",
        "expect_keyword": "emphysema",
    },
    # ── Expansion (open item #5: "retrieval_eval.py past 5 cases") ─────────
    {
        # Multi-finding disambiguation: TWO conditions in one session --
        # tests whether retrieval surfaces the right one for a question
        # about specifically the heart finding, not getting pulled toward
        # the coexisting lung finding just because both are in context.
        "report": "Chest X-ray shows cardiomegaly. Also note right lower lobe consolidation consistent with pneumonia.",
        "findings": {
            "Cardiomegaly": "heart size enlarged, cardiothoracic ratio 0.56",
            "Pneumonia": "right lower lobe consolidation",
        },
        "medicines": ["Furosemide 20mg", "Amoxicillin 500mg"],
        "question": "Why is my heart enlarged?",
        "expect_keyword": "cardiomegaly",
    },
    {
        # No prescribed medicines at all -- confirms indexing/retrieval
        # doesn't implicitly depend on a non-empty medicines list to work.
        "report": "Mild degenerative changes noted in the thoracic spine. No acute findings.",
        "findings": {"Degenerative Changes": "mild thoracic spine degeneration"},
        "medicines": [],
        "question": "What did the X-ray show about my spine?",
        "expect_keyword": "degenerative",
    },
    {
        # Harder semantic paraphrase: the question's wording ("lung looks
        # collapsed") shares almost no words with the report/finding text
        # ("atelectasis", "mucus plugging") -- a real test that retrieval
        # is doing semantic matching, not keyword overlap.
        "report": "Findings consistent with atelectasis in the right lower lobe, likely due to mucus plugging.",
        "findings": {"Atelectasis": "right lower lobe atelectasis, likely mucus plugging"},
        "medicines": ["Albuterol nebulizer"],
        "question": "Why does part of my lung look collapsed on the scan?",
        "expect_keyword": "atelectasis",
    },
]


def run_evaluation(top_k: int = 4):
    correct = 0
    print(f"{'Question':<45} {'Expected term':<15} {'Found in top result?'}")
    print("-" * 90)

    for case in TEST_CASES:
        session_id = create_session()
        index_session_data(
            session_id=session_id,
            doctor_report=case["report"],
            xray_findings=case["findings"],
            prescribed_medicines=case["medicines"],
        )
        debug_this_case = case["expect_keyword"] == "emphysema"
        chunks, confidence, insufficient_data = retrieve_session_context(
            session_id, case["question"], top_k=top_k, debug=debug_this_case
        )
        top_result = chunks[0].lower() if chunks else ""
        hit = case["expect_keyword"] in top_result
        correct += hit
        mark = "YES" if hit else "NO"
        print(f"{case['question']:<45} {case['expect_keyword']:<15} {mark}")

    accuracy = correct / len(TEST_CASES) * 100
    print("-" * 90)
    print(f"Retrieval accuracy (right chunk in top result): {correct}/{len(TEST_CASES)} ({accuracy:.1f}%)")
    return accuracy


if __name__ == "__main__":
    run_evaluation()
