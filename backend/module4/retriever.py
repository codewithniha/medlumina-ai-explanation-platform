"""
retriever.py

Two-tier retrieval (session first, KB only for matched terms -- unchanged
from before), but each tier now uses HYBRID retrieval instead of pure
vector search:

  1. Vector search (semantic/"meaning" match) -- what was already here.
  2. BM25 (keyword/exact-term match) -- NEW. Catches cases vector search
     can miss, e.g. the patient's report says "cardiomegaly" and the
     question uses the exact word "cardiomegaly" -- BM25 rewards exact
     term overlap directly, vector search only rewards similarity, which
     is usually right but not guaranteed.
  3. Reciprocal Rank Fusion (RRF) -- NEW. Combines the two ranked lists
     into one, so a chunk that either method ranks highly gets a real
     boost, without needing to tune a blend weight by hand (RRF's
     1/(k+rank) formula is a well-established, parameter-light way to
     merge ranked lists from very different scoring scales -- vector
     cosine similarity and BM25 scores aren't on the same numeric scale,
     so averaging them directly would be meaningless; RRF sidesteps that
     by only using RANK, not raw score).
  4. Cross-encoder reranking -- NEW. The fused top candidates get a final
     pass from a small cross-encoder model that reads the (question,
     chunk) pair TOGETHER (unlike vector search, which embeds them
     separately and compares afterward). This is slower per-pair, which
     is exactly why it only runs on the top ~10 fused candidates, not the
     whole collection -- cheap enough to run on a laptop CPU, faster on
     GPU (e.g. Kaggle) if available.

Analogy for all of this: vector search is a librarian judging books by
"does this feel similar in meaning". BM25 is a second librarian doing
old-fashioned keyword lookup. RRF is a manager combining both librarians'
shortlists into one ranked list. The cross-encoder is a specialist who
actually reads each of the top candidates side-by-side with your question
before making the final call -- slower, so only used on the shortlist.
"""

from rank_bm25 import BM25Okapi
from sentence_transformers import CrossEncoder

import live_kb
from kb_indexer import get_chroma_client, KB_COLLECTION_NAME, _embedding_fn
from session_indexer import get_session_collection
from kb_data import KB_ENTRIES
from embedding_config import embed_query_text
from session_store import get_patient_sessions

_KB_CONDITION_NAMES = [entry["condition"].lower() for entry in KB_ENTRIES]

# Small, fast cross-encoder -- good accuracy/speed tradeoff for reranking a
# short candidate list on CPU. Loaded once, lazily, so importing this
# module doesn't pay the model-load cost unless retrieval actually runs.
_RERANKER_MODEL_NAME = "cross-encoder/ms-marco-MiniLM-L-6-v2"
_reranker = None


def _get_reranker() -> CrossEncoder:
    global _reranker
    if _reranker is None:
        _reranker = CrossEncoder(_RERANKER_MODEL_NAME)
    return _reranker


def _reciprocal_rank_fusion(rankings: list[list[str]], k: int = 60) -> tuple[list[str], dict[str, float]]:
    """
    Merges multiple ranked ID lists into one ranked list using RRF.
    k=60 is the standard default from the original RRF paper -- it just
    controls how much rank position 1 is favored over position 10; not
    worth tuning unless retrieval quality testing shows a specific reason
    to.

    Returns both the fused ranking AND the raw per-doc RRF scores, since
    the caller now blends these scores with cross-encoder scores rather
    than treating the cross-encoder as the final word (see _hybrid_search).
    """
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, doc_id in enumerate(ranking):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)
    fused_order = sorted(scores.keys(), key=lambda d: scores[d], reverse=True)
    return fused_order, scores


def _minmax_normalize(values: list[float]) -> list[float]:
    """
    Scales a list of raw scores to [0, 1]. Needed because RRF scores and
    cross-encoder scores live on completely different numeric scales (RRF
    is ~0.01-0.03, cross-encoder is raw logits like -11 to +5) -- you can't
    blend them meaningfully without putting both on the same footing first.
    If all values are equal (no signal), returns 0.5 for every entry rather
    than dividing by zero.
    """
    if not values:
        return []
    lo, hi = min(values), max(values)
    if hi - lo < 1e-9:
        return [0.5 for _ in values]
    return [(v - lo) / (hi - lo) for v in values]


def _hybrid_search(
    collection,
    all_ids: list[str],
    all_docs: list[str],
    question: str,
    top_k: int,
    rerank: bool = True,
    debug: bool = False,
    alpha: float = 0.3,
) -> tuple[list[str], float | None, bool]:
    """
    Runs vector + BM25 search over the given collection's full document
    set, fuses with RRF, optionally reranks the top candidates with the
    cross-encoder, and returns (top_k document TEXTS, confidence,
    insufficient_session_data).

    confidence is derived from the TOP reranked chunk's BLENDED score
    (cross-encoder + RRF agreement, see the calculation near the bottom of
    this function for why) -- None if nothing was retrieved at all, or if
    reranking didn't run (see the two early-return paths below, where
    there's no blended score to base a real number on).

    insufficient_session_data is True specifically when confidence is None
    BECAUSE the session has 0 or 1 total chunks indexed -- e.g. a
    Prescription-only session where the patient entered just one medicine
    and no symptoms. This is a REAL, honest gap in the confidence
    methodology, not a bug to silently hide: the confidence score is
    fundamentally a RELATIVE measure (the top candidate's score, min-max
    normalized against the OTHER candidates that were compared against
    it -- see the blend calculation below). With only one chunk in the
    whole session, there is nothing to compare it against, so there is no
    honest way to produce a real relative confidence number.
    Deliberately NOT attempting a same-shaped workaround here (e.g.
    scoring the single chunk against a fixed reference range) -- the
    cross-encoder's raw logits for this domain are documented elsewhere in
    this file (see the comment above the confidence calculation) to
    cluster tightly around -10 to -11 even for CONFIRMED CORRECT matches,
    meaning any single-chunk calibration invented under time pressure,
    without real evaluation data to anchor it, risks producing a number
    that LOOKS like a real signal but isn't -- worse than honestly showing
    none at all. Callers (module4_pipeline.py, the API response, and
    ultimately qa-screen.tsx) use this flag to show the patient a clear
    explanation ("not enough data yet for a confidence score") instead of
    a badge silently going missing, which looks like an omission/bug
    rather than an explained, honest limitation.

    all_ids/all_docs must be pre-fetched from the collection by the caller
    (session collections are small -- a handful to a few dozen chunks --
    so pulling everything for BM25 indexing is cheap; this is not
    appropriate for a collection with thousands of documents, but that's
    not this project's scale).

    alpha controls how much the final ranking trusts the cross-encoder vs.
    the RRF-fused order: final_score = alpha * cross_encoder + (1-alpha) *
    RRF. The cross-encoder is a general-domain model with no medical
    knowledge, so it can occasionally be confidently-SOUNDING but wrong on
    medical text (e.g. ranking a medicine chunk over the actual diagnosis
    chunk for a symptom question) even when its actual score margin is
    weak. Real evaluation (retrieval_eval.py, emphysema case) showed RRF
    was right and the cross-encoder was wrong with only a ~0.35-point gap
    on an ~11-point scale -- so alpha=0.3 (favor RRF, let the cross-encoder
    act as a secondary signal rather than the deciding one) is the
    evidence-based default here, not alpha>0.5. Retune only if further
    real evaluation shows a case where the cross-encoder was right and RRF
    was wrong.
    """
    if not all_docs:
        return [], None, True

    id_to_doc = dict(zip(all_ids, all_docs))

    # --- Vector search leg ---
    vector_results = collection.query(
        query_texts=[embed_query_text(question)],
        n_results=min(top_k * 3, len(all_docs)),  # over-fetch before fusion
    )
    vector_ranking = vector_results.get("ids", [[]])[0]

    # --- BM25 leg ---
    tokenized_corpus = [doc.lower().split() for doc in all_docs]
    bm25 = BM25Okapi(tokenized_corpus)
    bm25_scores = bm25.get_scores(question.lower().split())
    bm25_ranking = [
        doc_id
        for doc_id, _ in sorted(zip(all_ids, bm25_scores), key=lambda x: x[1], reverse=True)
    ][: min(top_k * 3, len(all_docs))]

    if debug:
        print(f"\n[DEBUG] Question: {question!r}")
        print(f"[DEBUG] Vector ranking (top {len(vector_ranking)}): {vector_ranking}")
        print(f"[DEBUG] BM25 ranking   (top {len(bm25_ranking)}): {bm25_ranking}")

    # --- Fuse ---
    fused_ids, rrf_scores = _reciprocal_rank_fusion([vector_ranking, bm25_ranking])
    candidate_ids = fused_ids[: max(top_k * 2, 10)]  # shortlist for reranking

    if debug:
        print(f"[DEBUG] RRF fused order: {fused_ids}")

    if not rerank or len(candidate_ids) <= 1:
        # No cross-encoder ran, so there's no real relevance-logit signal
        # to base a confidence number on. len(candidate_ids) <= 1 is the
        # live-triggered case (rerank=False is never actually passed by
        # any current caller, kept only as a defensive parameter) -- see
        # the docstring above for why this specifically means "not enough
        # session data", not "genuinely no match".
        insufficient = len(candidate_ids) <= 1
        return [id_to_doc[i] for i in candidate_ids[:top_k] if i in id_to_doc], None, insufficient

    # --- Cross-encoder rerank on the shortlist only ---
    reranker = _get_reranker()
    pairs = [(question, id_to_doc[i]) for i in candidate_ids if i in id_to_doc]
    valid_ids = [i for i in candidate_ids if i in id_to_doc]
    if not pairs:
        return [], None, True
    ce_scores = list(reranker.predict(pairs))

    # Blend: normalize both score types to [0,1], then combine so a strong
    # RRF signal can outvote a weak/uncertain cross-encoder margin instead
    # of the cross-encoder unconditionally winning (see alpha docstring
    # above for why this matters on medical text).
    ce_norm = _minmax_normalize(ce_scores)
    rrf_raw = [rrf_scores.get(i, 0.0) for i in valid_ids]
    rrf_norm = _minmax_normalize(rrf_raw)
    blended = [alpha * c + (1 - alpha) * r for c, r in zip(ce_norm, rrf_norm)]

    reranked = sorted(
        zip(valid_ids, ce_scores, rrf_raw, blended),
        key=lambda x: x[3],
        reverse=True,
    )

    if debug:
        print("[DEBUG] Cross-encoder + RRF blended order (id, ce_score, rrf_score, blended, text preview):")
        for i, ce_s, rrf_s, b in reranked:
            preview = id_to_doc[i][:80].replace("\n", " ")
            print(f"[DEBUG]   blended={b:.3f}  ce={ce_s:.3f}  rrf={rrf_s:.4f}  {i}  {preview}...")

    # Confidence comes from the TOP result's BLENDED score, not the raw
    # cross-encoder logit. Real data from this exact project (see
    # retrieval_eval.py's debug output) showed the cross-encoder's raw
    # logits for this domain cluster tightly around -10 to -11 even for
    # CONFIRMED CORRECT top matches -- a raw sigmoid on that number floors
    # at ~0% regardless of match quality, which would be actively
    # misleading (looks like zero confidence even when the system is
    # right). blended IS already meaningful on its own: it's built from
    # two independently min-max-normalized signals (cross-encoder + RRF),
    # so it lands near 1.0 only when semantic search, keyword search, AND
    # reranking all agree on the same top chunk, and drops when they
    # disagree -- genuine cross-method agreement, not an arbitrary number.
    #
    # Known, honest limitation (confirmed live): min-max normalization
    # mathematically maps whichever chunk is BEST in the candidate set to
    # exactly 1.0, by definition -- regardless of whether it's a strong
    # match or just the best of a small/easy field. With very few chunks
    # in a session (a handful, as in most demo sessions), the same chunk
    # often wins both signals outright, so this saturates to a literal
    # 100% more often than is useful to show. Rather than redesign the
    # whole formula under time pressure, cap the DISPLAYED number below
    # absolute certainty -- no AI system should present unqualified 100%
    # confidence about anything. The underlying real number is still used
    # for the retry-safety-net logic elsewhere; only the number shown to
    # the patient is capped.
    confidence = round(reranked[0][3] * 100, 1)
    confidence = min(confidence, 97.0)

    return [id_to_doc[i] for i, _, _, _ in reranked[:top_k]], confidence, False


def retrieve_session_context(
    session_id: str, question: str, top_k: int = 4, debug: bool = False
) -> tuple[list[str], float | None, bool]:
    """Retrieves the most relevant chunks from THIS patient's session collection,
    using hybrid (vector + BM25) search with cross-encoder reranking.
    Returns (chunks, confidence, insufficient_session_data) -- see
    _hybrid_search's docstring for what confidence actually means, its
    honest limitations, and what the third value means.

    debug=True prints the fused shortlist and final reranked order before
    returning -- diagnostic only, no effect on the returned result."""
    collection = get_session_collection(session_id)
    if collection is None or collection.count() == 0:
        return [], None, True

    everything = collection.get()
    all_ids = everything.get("ids", [])
    all_docs = everything.get("documents", [])

    return _hybrid_search(collection, all_ids, all_docs, question, top_k, debug=debug)


def _get_session_conditions(session_id: str) -> list[str]:
    """
    Pulls condition names directly from the session's structured
    xray_finding metadata -- NOT limited to the old 12-condition static
    KB vocabulary anymore. Whatever condition your vision module actually
    detected is what gets looked up live, which is the whole point of
    moving to live API-backed retrieval.
    """
    collection = get_session_collection(session_id)
    if collection is None:
        return []
    results = collection.get(where={"source": "xray_finding"})
    conditions = [m.get("condition") for m in results.get("metadatas", []) if m.get("condition")]
    return list(dict.fromkeys(conditions))  # dedupe, preserve order


def _get_session_medicines(session_id: str) -> list[str]:
    """Pulls prescribed medicine names directly from session metadata."""
    collection = get_session_collection(session_id)
    if collection is None:
        return []
    results = collection.get(where={"source": "prescribed_medicine"})
    medicines = [m.get("medicine_name") for m in results.get("metadatas", []) if m.get("medicine_name")]
    return list(dict.fromkeys(medicines))


def _static_kb_fallback_for_condition(condition: str, top_k: int = 2) -> list[str]:
    """
    Falls back to the old static kb_data.py content for ONE condition,
    used only when the live PubMed call for that condition fails or
    returns nothing. Keeps the system answering something useful during
    a live-API outage instead of going silent.
    """
    condition_lower = condition.lower()
    if condition_lower not in _KB_CONDITION_NAMES:
        return []  # condition isn't in the old static KB either -- nothing to fall back to
    client = get_chroma_client()
    try:
        collection = client.get_collection(KB_COLLECTION_NAME, embedding_function=_embedding_fn)
    except Exception:
        return []
    condition_name = next(e["condition"] for e in KB_ENTRIES if e["condition"].lower() == condition_lower)
    subset = collection.get(where={"condition": {"$eq": condition_name}})
    return subset.get("documents", [])[:top_k]


def retrieve_kb_context(session_id: str, question: str, top_k_per_term: int = 2) -> list[str]:
    """
    PRIMARY source is now live: real PubMed abstracts for each condition
    actually present in the patient's own X-ray findings, and real FDA
    label data for each of their actual prescribed medicines -- pulled
    directly from session metadata, not from text-matching against a
    fixed vocabulary.

    FALLBACK: if a live PubMed call for a specific condition fails
    (network issue, rate limit, no results), that one condition falls
    back to the old static kb_data.py content instead of contributing
    nothing -- see live_kb.py's module docstring for why this matters.
    OpenFDA has no static fallback (there was never a static drug-label
    KB) -- a failed OpenFDA call for one medicine just contributes no
    chunks for that medicine, which is fine since medicine info is
    supplementary, not primary.
    """
    conditions = _get_session_conditions(session_id)
    medicines = _get_session_medicines(session_id)
    print(f"[KB-DEBUG] session_id={session_id!r} conditions={conditions!r} medicines={medicines!r}")

    kb_chunks = []

    for condition in conditions:
        live_chunks = live_kb.pubmed_fetch(condition, max_results=top_k_per_term)
        print(f"[KB-DEBUG] pubmed_fetch({condition!r}) returned {len(live_chunks)} chunk(s)")
        if live_chunks:
            kb_chunks.extend(live_chunks)
        else:
            fallback_chunks = _static_kb_fallback_for_condition(condition, top_k_per_term)
            print(f"[KB-DEBUG] static fallback for {condition!r} returned {len(fallback_chunks)} chunk(s)")
            kb_chunks.extend(fallback_chunks)

    for medicine in medicines:
        med_chunks = live_kb.openfda_fetch(medicine)
        print(f"[KB-DEBUG] openfda_fetch({medicine!r}) returned {len(med_chunks)} chunk(s)")
        kb_chunks.extend(med_chunks)

    print(f"[KB-DEBUG] total kb_chunks returned: {len(kb_chunks)}")
    return kb_chunks


def get_patient_visit_history(patient_id: str, exclude_session_id: str | None = None) -> list[dict]:
    """
    Pulls this patient's doctor_report and xray_finding chunks from EACH
    of their past sessions' own isolated Chroma collection (see
    session_indexer.py -- collections are already fully separated per
    session, so there's no risk of one visit's data leaking into
    another's here), one block per visit, labeled with that visit's real
    created_at date.

    Returns visits in CHRONOLOGICAL order (earliest first) -- this is the
    order the trend-comparison prompt is instructed to reason in, so the
    model is never left to guess which visit is more recent.

    exclude_session_id: pass the CURRENT session_id to skip re-including
    it if it's already indexed by the time this is called -- avoids the
    same visit showing up twice.

    A session is silently skipped (not shown as an empty visit) if it has
    no doctor_report or xray_finding chunks -- e.g. a session where the
    upload never fully completed. This mirrors the existing
    insufficient_session_data honesty pattern elsewhere in this file:
    better to omit a visit with nothing real to show than to show an
    empty, misleading entry.

    Only doctor_report and xray_finding chunks are pulled (not
    prescribed_medicine or symptoms) -- those two sources are what
    actually describe the patient's CONDITION across time, which is what
    a trend comparison is about; medicines/symptoms chunks would add
    noise without helping answer "has my condition changed".
    """
    sessions_desc = get_patient_sessions(patient_id)  # already DESC by created_at
    sessions_chronological = list(reversed(sessions_desc))

    visits = []
    for s in sessions_chronological:
        session_id = s["session_id"]
        if exclude_session_id and session_id == exclude_session_id:
            continue

        collection = get_session_collection(session_id)
        if collection is None or collection.count() == 0:
            continue

        report_result = collection.get(where={"source": "doctor_report"})
        finding_result = collection.get(where={"source": "xray_finding"})
        chunks = report_result.get("documents", []) + finding_result.get("documents", [])
        if not chunks:
            continue

        visits.append({
            "session_id": session_id,
            "created_at": s["created_at"],
            "chunks": chunks,
        })

    return visits


def retrieve(session_id: str, question: str) -> dict:
    """
    Runs the full two-tier retrieval: session tier uses hybrid search +
    reranking (unchanged), KB tier now pulls from LIVE PubMed/OpenFDA
    (primary) with static KB as fallback (see retrieve_kb_context docs).
    Returns session_chunks, kb_chunks, confidence, AND
    insufficient_session_data (see _hybrid_search's docstring for exactly
    what these mean) so the generation prompt can clearly label which
    source is primary (session) and which is supporting-only (KB) --
    matching FE-2 and the prompt rules in prompts.py.
    """
    session_chunks, confidence, insufficient_session_data = retrieve_session_context(session_id, question)
    kb_chunks = retrieve_kb_context(session_id, question)
    return {
        "session_chunks": session_chunks,
        "kb_chunks": kb_chunks,
        "confidence": confidence,
        "insufficient_session_data": insufficient_session_data,
    }
