"""
evaluate_module4_iu_xray.py

Real accuracy evaluation of Module 4 (RAG Q&A) against the Indiana
University / Open-I chest X-ray report dataset -- NOT against Niha's
X-ray image model. Module 4 only ever consumes TEXT (report/findings/
symptoms), so this deliberately tests it in isolation, using real
radiologist-written reports as ground truth, independent of whether
Niha's model is online.

WHAT THIS DOES:
  1. Loads real reports from indiana_reports.csv (the Kaggle mirror:
     kaggle.com/datasets/raddar/chest-xrays-indiana-university).
  2. Samples a stratified set (roughly half "normal", half with real
     findings, so the test isn't all easy cases).
  3. For each sampled report, starts a REAL session against your REAL
     running backend (http://127.0.0.1:8001) using Findings + Impression
     + Indication as the report/symptoms input -- this mirrors a
     realistic upload (multiple real chunks), not an artificially thin
     one-chunk session.
  4. Asks 5 fixed-shape questions per session (3 SESSION_GROUNDED, 1
     GENERAL_MEDICAL, 1 OFF_TOPIC control) through the REAL /session/ask
     endpoint.
  5. Logs everything to a CSV, with an automated first-pass score
     (classification correctness is fully objective; answer quality is
     an APPROXIMATE keyword-overlap score, clearly not a substitute for
     you actually reading a sample of real answers against the real
     report -- see the printed summary for what to manually check).

WHAT THIS DOES NOT DO:
  - Does not touch Niha's X-ray image model at all -- this is Module 4
    only, on purpose (see the message accompanying this file for why).
  - Does not grade answer CORRECTNESS with full confidence -- keyword
    overlap is a rough proxy. Report the classification accuracy number
    as fully real/objective; report the answer-quality number with the
    caveat that it's an automated first pass, and back it up with a
    manually-graded subsample (the script prints which rows to check).

HOW TO RUN:
  1. Download the dataset from Kaggle, unzip it, find indiana_reports.csv
     (you don't need indiana_projections.csv or the images -- Module 4
     never touches the X-ray pixels).
  2. Make sure your Module 4 backend is actually running:
       cd F:\\medlumina-updated\\backend\\module4
       uvicorn module4_api:app --reload --port 8001
  3. pip install pandas requests   (if not already installed)
  4. Edit CSV_PATH below to point at your real indiana_reports.csv
  5. python evaluate_module4_iu_xray.py
  6. Real terminal output prints a live progress log AND a final summary.
     A full CSV (evaluation_results.csv) is written next to this script
     for you to open in Excel and manually grade the flagged rows.
"""

import csv
import random
import re
import sys
import time

import pandas as pd
import requests

# ── Config -- edit these two paths before running ──────────────────────
CSV_PATH = r"F:\archive\indiana_reports.csv"  # confirmed real path on this machine
OUTPUT_PATH = "evaluation_results.csv"
EXTRA_OUTPUT_PATH = "evaluation_extra_checks.csv"
API_BASE = "http://127.0.0.1:8001"

SAMPLE_SIZE = 40          # total reports to test -- adjust if you want more/fewer
RANDOM_SEED = 42          # fixed seed -- makes the sample reproducible if you re-run
# call_medgemma now retries once on timeout (up to 2 attempts x 180s each) --
# this MUST exceed that worst case, or the test itself will report a false
# failure exactly like the first run did (60s was far too short and made
# genuinely-working-but-slow answers look like real failures).
REQUEST_TIMEOUT_SECS = 400

# How many of the sampled reports also get the EXTRA robustness checks
# below (Urdu language support, phrasing-consistency) -- kept smaller than
# the full sample since each one adds 2+ extra real MedGemma calls, and
# these are checking a DIFFERENT dimension than the main classification/
# answer-quality numbers, not needing the same large sample size to be
# informative.
EXTRA_CHECKS_SUBSAMPLE_SIZE = 10

Q1_ALT_PHRASING = "Can you explain my X-ray results to me in simple terms?"
Q1_URDU = "میری سینے کے ایکسرے کی رپورٹ کیا ظاہر کرتی ہے؟"
Q_GENERAL_MEDICAL_URDU = "نمونیا کیا ہے؟"

_URDU_SCRIPT_RE = re.compile(r"[\u0600-\u06FF\uFB50-\uFDFF\uFE70-\uFEFF]")


def _looks_urdu(text: str) -> bool:
    """Rough automated signal only -- counts characters in the Arabic/
    Urdu Unicode block. Confirms SCRIPT, not correctness of the Urdu --
    still needs a human who reads Urdu to confirm the actual answer makes
    sense, same 'automated proxy, not a substitute for reading it' caveat
    as the keyword-overlap score elsewhere in this script."""
    if not text:
        return False
    urdu_chars = len(_URDU_SCRIPT_RE.findall(text))
    return urdu_chars / max(len(text), 1) > 0.3  # >30% Urdu-script chars

# ── Fixed questions asked for EVERY sampled report ──────────────────────
# Keeping these fixed (not per-report custom-written) is a deliberate
# choice: it means the classification-accuracy number below is fully
# objective and reproducible, not shaped by hand-picked easy/hard
# questions. The one part that IS per-report is Q3 (see
# _pick_finding_question below) -- it targets whatever real finding is
# actually in THIS report, when we can detect one.
Q_GENERAL_MEDICAL = "What is pneumonia?"
Q_OFF_TOPIC = "What's a good recipe for biryani?"

# Maps a keyword that might appear in a real report to a natural patient
# question about it. Checked in order -- first match wins. Deliberately
# simple keyword matching, not an LLM call, so building the test set
# itself costs nothing and is fully reproducible.
FINDING_QUESTIONS = [
    ("cardiomegaly", "Is there anything wrong with the size of my heart?"),
    ("pneumonia", "Do I have pneumonia?"),
    ("consolidation", "What does the consolidation in my lungs mean?"),
    ("effusion", "Is there fluid around my lungs?"),
    ("atelectasis", "What does the collapsed area in my lung mean?"),
    ("pneumothorax", "Is there air where it shouldn't be in my chest?"),
    ("edema", "Is there fluid buildup they're concerned about?"),
    ("nodule", "What is the spot they found on my scan?"),
    ("opacity", "What does the unclear area on my X-ray mean?"),
    ("emphysema", "Do I have emphysema?"),
    ("fracture", "Is there a fracture anywhere?"),
    ("scoliosis", "Is there anything wrong with my spine?"),
    ("calcification", "What does the calcification mentioned mean?"),
    ("hernia", "Is there a hernia mentioned in my report?"),
]

STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "of", "in", "on", "at",
    "to", "for", "and", "or", "with", "no", "not", "there", "this",
    "that", "it", "as", "be", "by", "any", "which", "chest", "x-ray",
    "xray", "seen", "noted", "shown", "shows", "found", "identified",
}


NEGATION_CUES = (
    "no ", "not ", "without ", "free of ", "no evidence of ", "no acute ",
    "absence of ", "no focal ", "unremarkable for ", "negative for ",
)


def _has_positive_mention(text: str, keyword: str) -> bool:
    """True only if `keyword` appears in text WITHOUT a negation cue
    shortly before it. Naive substring matching alone is wrong here --
    real report text like 'No pleural effusion' contains the literal
    word 'effusion' while meaning the opposite of a finding. Checks the
    ~30 characters immediately before each match for a negation word;
    a keyword is only counted as a real positive finding if at least one
    of its occurrences isn't negated."""
    text = text.lower()
    for match in re.finditer(re.escape(keyword), text):
        window_start = max(0, match.start() - 30)
        window = text[window_start:match.start()]
        if not any(neg in window for neg in NEGATION_CUES):
            return True
    return False


def _pick_finding_question(findings_text: str, impression_text: str) -> tuple[str, str] | None:
    """Returns (question, matched_keyword) for the first FINDING_QUESTIONS
    keyword found POSITIVELY MENTIONED in this report's real text (see
    _has_positive_mention -- 'No effusion' does NOT count as a match), or
    None if no known keyword is positively present (many reports are
    genuinely normal -- that's a real, expected outcome, not a bug in the
    test)."""
    combined = f"{findings_text} {impression_text}".lower()
    for keyword, question in FINDING_QUESTIONS:
        if _has_positive_mention(combined, keyword):
            return question, keyword
    return None


def _keyword_overlap_score(answer: str, source_text: str) -> float:
    """Rough, automated first-pass proxy for 'did the answer actually
    reflect the real report content' -- fraction of meaningful words from
    the SOURCE report that also appear in the generated answer. NOT a
    substitute for actually reading the answers -- flagged clearly in the
    printed summary as approximate."""
    def tokens(text):
        words = re.findall(r"[a-z]+", text.lower())
        return {w for w in words if w not in STOPWORDS and len(w) > 3}

    source_tokens = tokens(source_text)
    if not source_tokens:
        return 0.0
    answer_tokens = tokens(answer)
    overlap = source_tokens & answer_tokens
    return round(len(overlap) / len(source_tokens), 3)


def load_and_sample_reports() -> pd.DataFrame:
    df = pd.read_csv(CSV_PATH)
    # Real, known data-quality issue in this dataset (documented in the
    # papers this evaluation is modeled on): not every report has a
    # Findings section. Drop incomplete rows rather than silently testing
    # against blank/garbage input.
    df = df.dropna(subset=["findings", "impression"])
    df = df[df["findings"].str.strip() != ""]
    df = df[df["impression"].str.strip() != ""]

    # Stratify roughly half "normal-looking" vs half with a real finding
    # keyword, so the test isn't all easy cases.
    def has_finding(row):
        return _pick_finding_question(row["findings"], row["impression"]) is not None

    df = df.copy()
    df["has_finding"] = df.apply(has_finding, axis=1)

    rng = random.Random(RANDOM_SEED)
    normal_pool = df[~df["has_finding"]]
    finding_pool = df[df["has_finding"]]

    half = SAMPLE_SIZE // 2
    n_normal = min(half, len(normal_pool))
    n_finding = min(SAMPLE_SIZE - n_normal, len(finding_pool))

    sampled = pd.concat([
        normal_pool.sample(n=n_normal, random_state=RANDOM_SEED),
        finding_pool.sample(n=n_finding, random_state=RANDOM_SEED),
    ])
    return sampled.sample(frac=1, random_state=RANDOM_SEED).reset_index(drop=True)  # shuffle order


def start_session(findings: str, impression: str, indication: str) -> dict:
    doctor_report = f"{findings}\n\n{impression}".strip()
    payload = {
        "doctor_report": doctor_report,
        "symptoms": (indication or "").strip(),
        "prescribed_medicines": [],
        "explanation_level": "simple",
    }
    resp = requests.post(f"{API_BASE}/session/start", json=payload, timeout=REQUEST_TIMEOUT_SECS)
    resp.raise_for_status()
    return resp.json()


def ask(session_id: str, question: str) -> dict:
    payload = {"session_id": session_id, "question": question}
    resp = requests.post(f"{API_BASE}/session/ask", json=payload, timeout=REQUEST_TIMEOUT_SECS)
    resp.raise_for_status()
    return resp.json()


def run_evaluation():
    print(f"Loading and sampling {SAMPLE_SIZE} real reports from {CSV_PATH} ...")
    try:
        sample_df = load_and_sample_reports()
    except FileNotFoundError:
        print(f"\n[ERROR] Could not find {CSV_PATH}")
        print("Edit CSV_PATH at the top of this script to point at your real indiana_reports.csv")
        sys.exit(1)

    print(f"Sampled {len(sample_df)} reports ({sample_df['has_finding'].sum()} with a "
          f"detected finding keyword, {(~sample_df['has_finding']).sum()} without).\n")

    # Quick real connectivity check before burning time on 40 reports.
    try:
        health = requests.get(f"{API_BASE}/health", timeout=10)
        print(f"Backend health check: {health.status_code} {health.text[:200]}\n")
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] Could not reach {API_BASE} -- is uvicorn actually running? ({e})")
        sys.exit(1)

    rows = []
    extra_rows = []
    classification_correct_count = 0
    classification_total_count = 0

    for i, row in sample_df.iterrows():
        uid = row.get("uid", i)
        findings = str(row["findings"])
        impression = str(row["impression"])
        indication = str(row.get("indication", "") or "")

        print(f"[{i + 1}/{len(sample_df)}] uid={uid} ...", end=" ")

        try:
            session = start_session(findings, impression, indication)
        except requests.exceptions.RequestException as e:
            print(f"SESSION START FAILED: {e}")
            continue

        session_id = session["session_id"]
        chunks_indexed = session.get("chunks_indexed")

        finding_q = _pick_finding_question(findings, impression)
        questions = [
            ("SESSION_GROUNDED", "What does my chest X-ray report show?", findings),
            ("SESSION_GROUNDED", "What is the impression or diagnosis from my report?", impression),
        ]
        if finding_q:
            q_text, matched_keyword = finding_q
            questions.append(("SESSION_GROUNDED", q_text, f"{findings} {impression}"))
        questions.append(("GENERAL_MEDICAL", Q_GENERAL_MEDICAL, ""))
        questions.append(("OFF_TOPIC", Q_OFF_TOPIC, ""))

        for expected_classification, question_text, source_text in questions:
            try:
                result = ask(session_id, question_text)
            except requests.exceptions.RequestException as e:
                print(f"\n  [ASK FAILED] {question_text!r}: {e}")
                continue

            actual_classification = result.get("classification")
            answer = result.get("answer", "")
            confidence = result.get("confidence")
            insufficient = result.get("insufficient_session_data")

            correct = actual_classification == expected_classification
            classification_total_count += 1
            if correct:
                classification_correct_count += 1

            overlap_score = (
                _keyword_overlap_score(answer, source_text) if source_text else None
            )

            rows.append({
                "uid": uid,
                "chunks_indexed": chunks_indexed,
                "expected_classification": expected_classification,
                "actual_classification": actual_classification,
                "classification_correct": correct,
                "question": question_text,
                "answer": answer,
                "confidence": confidence,
                "insufficient_session_data": insufficient,
                "keyword_overlap_score": overlap_score,
                "real_findings": findings,
                "real_impression": impression,
            })

        print("done")
        time.sleep(0.5)  # be a little polite to your own local server / MedGemma tunnel

        # ── Extra checks, only for the first EXTRA_CHECKS_SUBSAMPLE_SIZE reports ──
        if i < EXTRA_CHECKS_SUBSAMPLE_SIZE:
            print(f"  [extra] uid={uid}: Urdu + phrasing-consistency checks ...", end=" ")

            # -- Urdu bilingual check: same question, asked in Urdu, on a
            # FRESH session (so the Urdu answer's confidence/retrieval
            # isn't affected by the 5 English questions already asked
            # against this session above).
            try:
                urdu_session = start_session(findings, impression, indication)
                urdu_result = ask(urdu_session["session_id"], Q1_URDU)
                urdu_answer = urdu_result.get("answer", "")
                extra_rows.append({
                    "uid": uid, "check_type": "urdu_language",
                    "question": Q1_URDU, "answer": urdu_answer,
                    "classification": urdu_result.get("classification"),
                    "confidence": urdu_result.get("confidence"),
                    "answer_is_urdu_script": _looks_urdu(urdu_answer),
                    "note": "answer_is_urdu_script=False means it answered in "
                            "English/other despite an Urdu question -- a real miss.",
                })
            except requests.exceptions.RequestException as e:
                extra_rows.append({"uid": uid, "check_type": "urdu_language", "note": f"REQUEST FAILED: {e}"})

            # -- Phrasing-consistency check: same report, same INTENT
            # question, worded differently -- on ANOTHER fresh session, so
            # it's not affected by conversation history from earlier
            # questions either.
            try:
                phrasing_session = start_session(findings, impression, indication)
                alt_result = ask(phrasing_session["session_id"], Q1_ALT_PHRASING)
                alt_answer = alt_result.get("answer", "")
                original_answer = next(
                    (r["answer"] for r in rows if r["uid"] == uid and r["question"] == questions[0][1]),
                    "",
                )
                # Simple, real, checkable signal: does the alternate phrasing
                # surface the same detected-finding keywords as the original?
                # A meaningful mismatch here is a real, specific, reportable
                # instance of the same issue found manually in uid=3058 --
                # this makes it a systematic check instead of a lucky find.
                orig_keywords = {kw for kw, _ in FINDING_QUESTIONS if kw in original_answer.lower()}
                alt_keywords = {kw for kw, _ in FINDING_QUESTIONS if kw in alt_answer.lower()}
                extra_rows.append({
                    "uid": uid, "check_type": "phrasing_consistency",
                    "question": Q1_ALT_PHRASING, "answer": alt_answer,
                    "classification": alt_result.get("classification"),
                    "confidence": alt_result.get("confidence"),
                    "original_answer": original_answer,
                    "finding_keywords_match": orig_keywords == alt_keywords,
                    "orig_keywords": ",".join(sorted(orig_keywords)) or "(none)",
                    "alt_keywords": ",".join(sorted(alt_keywords)) or "(none)",
                    "note": "finding_keywords_match=False means the two phrasings "
                            "surfaced DIFFERENT findings -- read both answers manually.",
                })
            except requests.exceptions.RequestException as e:
                extra_rows.append({"uid": uid, "check_type": "phrasing_consistency", "note": f"REQUEST FAILED: {e}"})

            print("done")

    # ── Write full CSV for manual review ────────────────────────────────
    if rows:
        with open(OUTPUT_PATH, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        print(f"\nFull results written to {OUTPUT_PATH} ({len(rows)} question rows).")

    if extra_rows:
        # Different rows have different keys (urdu vs phrasing checks, and
        # failed-request rows have fewer fields) -- collect the full set of
        # columns across all rows so the CSV writer doesn't choke on a
        # missing key.
        all_keys = []
        for r in extra_rows:
            for k in r.keys():
                if k not in all_keys:
                    all_keys.append(k)
        with open(EXTRA_OUTPUT_PATH, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=all_keys)
            writer.writeheader()
            writer.writerows(extra_rows)
        print(f"Extra-checks results written to {EXTRA_OUTPUT_PATH} ({len(extra_rows)} rows).")

    # ── Summary ──────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    if classification_total_count:
        acc = classification_correct_count / classification_total_count * 100
        print(f"Classification accuracy: {classification_correct_count}/"
              f"{classification_total_count} = {acc:.1f}%")
        print("  -- this number is fully objective (classifier output vs. the")
        print("  fixed, known-correct category for each question type).")
    else:
        print("No questions completed -- check the errors above.")

    session_grounded_rows = [r for r in rows if r["expected_classification"] == "SESSION_GROUNDED"]
    correctly_classified_sg = [r for r in session_grounded_rows if r["classification_correct"]]
    if correctly_classified_sg:
        scores = [r["keyword_overlap_score"] for r in correctly_classified_sg if r["keyword_overlap_score"] is not None]
        if scores:
            avg_overlap = sum(scores) / len(scores)
            print(f"\nAverage keyword-overlap score (SESSION_GROUNDED, correctly classified): {avg_overlap:.2f}")
            print("  -- APPROXIMATE proxy only. Manually read the rows with the LOWEST")
            print("  overlap score in the CSV first -- those are the most likely real misses.")

    insufficient_count = sum(1 for r in rows if r.get("insufficient_session_data"))
    print(f"\n{insufficient_count}/{len(rows)} answers showed insufficient_session_data "
          f"(not enough chunks for a confidence score).")

    confidences = [r["confidence"] for r in rows if r.get("confidence") is not None]
    if confidences:
        print(f"Average confidence (where a score was given): {sum(confidences)/len(confidences):.1f}%")

    urdu_checks = [r for r in extra_rows if r.get("check_type") == "urdu_language"]
    urdu_completed = [r for r in urdu_checks if "answer_is_urdu_script" in r]
    if urdu_completed:
        urdu_correct = sum(1 for r in urdu_completed if r["answer_is_urdu_script"])
        print(f"\nUrdu language check: {urdu_correct}/{len(urdu_completed)} answers were "
              f"actually in Urdu script when asked in Urdu.")
        print("  -- Script-only check (does it look like Urdu), not a correctness check.")
        print("  If this is below 100%, read urdu_check_results.csv for which uids failed.")
    if len(urdu_checks) > len(urdu_completed):
        print(f"  ({len(urdu_checks) - len(urdu_completed)} Urdu check(s) failed to complete -- see CSV)")

    phrasing_checks = [r for r in extra_rows if r.get("check_type") == "phrasing_consistency"]
    phrasing_completed = [r for r in phrasing_checks if "finding_keywords_match" in r]
    if phrasing_completed:
        consistent = sum(1 for r in phrasing_completed if r["finding_keywords_match"])
        print(f"\nPhrasing-consistency check: {consistent}/{len(phrasing_completed)} report(s) "
              f"gave the SAME findings regardless of how the question was worded.")
        print("  -- A mismatch here is a real, specific instance of the same issue found")
        print("  manually earlier (uid=3058) -- read both answers for any mismatched uid.")

    print("\nNEXT STEP: open evaluation_results.csv, sort by keyword_overlap_score")
    print("ascending, and manually read the lowest ~15-20 rows against real_findings/")
    print("real_impression -- that's your real, defensible answer-quality check to")
    print("report alongside the objective classification accuracy number above.")
    print("Also open evaluation_extra_checks.csv and read any Urdu or phrasing rows")
    print("flagged above as not matching -- those are the two new dimensions this")
    print("run added beyond the first pass.")


if __name__ == "__main__":
    run_evaluation()
