"""
live_kb.py

Replaces the static, hand-written kb_data.py as the PRIMARY source for the
KB tier of retrieval. Instead of 12 pre-written condition summaries, this
pulls real, current content from two free public medical APIs:

  - PubMed (NCBI E-utilities): real research literature abstracts for
    whatever condition actually appears in the patient's own X-ray
    findings -- not limited to a fixed list of 12 conditions anymore,
    since conditions come directly from the patient's structured findings
    (xray_findings dict keys), not from text-matching against a static
    vocabulary.
  - OpenFDA (drug label API): real FDA-submitted drug labeling data
    (indications, warnings, adverse reactions) for whatever medicine
    actually appears in the patient's prescribed_medicines list.

Design decisions, explained (so this is defensible in your viva, not just
"I called some APIs"):

1. WHY THESE TWO, NOT ONE COMBINED SEARCH: conditions and medicines are
   fundamentally different kinds of questions -- "what is this diagnosis"
   is a literature question (PubMed), "what is this medicine for / what
   should I watch for" is a regulatory-labeling question (OpenFDA). Using
   the API that's actually authoritative for each question type is more
   defensible than treating both as generic web search.

2. CACHING: real API calls are slow (network round-trip) and rate-limited
   (NCBI: 3 req/sec without a free API key, 10/sec with one; OpenFDA:
   240 req/min without a key). Since the same condition/medicine can come
   up across multiple questions in one session (and across different
   patient sessions with similar diagnoses), a simple in-memory cache
   with a short TTL avoids hammering the API for the same lookup
   repeatedly. This is NOT a persistent cache (resets when the server
   restarts) -- fine for an FYP demo; a real production system would use
   Redis or a DB table instead, worth naming as a "future work" line if
   your supervisor asks about scaling.

3. GRACEFUL FAILURE: if either API is unreachable (network down, rate
   limited, NCBI/FDA having downtime), these functions return an empty
   list rather than raising -- matching the same fail-safe pattern
   already used in generator.py for the MedGemma call. retriever.py then
   falls back to the old static kb_data.py content for that specific
   condition, so a live-API outage during your defense demo doesn't take
   the whole system down -- it just quietly drops back to the curated
   static content you already validated.

4. NO API KEY REQUIRED for either service at this call volume. If you
   want higher rate limits later, get a free NCBI API key at
   https://www.ncbi.nlm.nih.gov/account/ and set NCBI_API_KEY in .env --
   this code already checks for it and uses it automatically if present.
"""

import os
import time
import requests
import xml.etree.ElementTree as ET
from dotenv import load_dotenv

load_dotenv()

PUBMED_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
OPENFDA_BASE = "https://api.fda.gov/drug/label.json"
NCBI_API_KEY = os.getenv("NCBI_API_KEY", "")  # optional, raises rate limit if set

REQUEST_TIMEOUT = 8  # seconds -- fails fast rather than hanging a patient's question
CACHE_TTL_SECONDS = 3600  # 1 hour -- see caching note above

# In-memory cache: {(source, query_key): (timestamp, chunks)}
_cache: dict[tuple[str, str], tuple[float, list[str]]] = {}


def _cache_get(source: str, query_key: str) -> list[str] | None:
    entry = _cache.get((source, query_key.lower()))
    if entry is None:
        return None
    timestamp, chunks = entry
    if time.time() - timestamp > CACHE_TTL_SECONDS:
        return None
    return chunks


def _cache_set(source: str, query_key: str, chunks: list[str]) -> None:
    _cache[(source, query_key.lower())] = (time.time(), chunks)


def _request_with_retry(url: str, params: dict, timeout: int, max_retries: int = 1, backoff_seconds: float = 1.5):
    """
    Thin wrapper around requests.get() that retries ONCE, and only on
    transient network failures (timeout, connection error) -- never on
    HTTP error status codes or malformed responses, since retrying those
    wouldn't help and would just burn the request's time budget for no
    reason.

    Added after observing one first-call KB fetch return empty during
    testing. Root cause was never confirmed (a deliberate targeted
    retest afterward succeeded cleanly on both PubMed and OpenFDA's
    first calls), so this is NOT a fix for a diagnosed bug -- it's cheap
    insurance against a transient network hiccup that we couldn't
    reproduce on demand, so a future one-off blip doesn't silently drop
    real content for a single patient question.
    """
    last_exc = None
    for attempt in range(max_retries + 1):
        try:
            return requests.get(url, params=params, timeout=timeout)
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            last_exc = e
            if attempt < max_retries:
                print(f"[live_kb] transient network error (attempt {attempt + 1}/{max_retries + 1}), retrying in {backoff_seconds}s: {e}")
                time.sleep(backoff_seconds)
    raise last_exc


def pubmed_fetch(condition: str, max_results: int = 3) -> list[str]:
    """
    Fetches real PubMed abstracts about a condition. Returns a list of
    chunk strings, each prefixed with the condition name and PMID so the
    generation prompt (and your defense demo) can show real provenance.

    Returns [] on any failure (network, rate limit, no results) -- caller
    is expected to fall back to static KB content, not crash.
    """
    cached = _cache_get("pubmed", condition)
    if cached is not None:
        return cached

    try:
        # Step 1: ESearch -- find PMIDs. "AND review[pt]" biases toward
        # review articles, which tend to be more patient-explainable than
        # a narrow primary-research paper on a single case series.
        search_params = {
            "db": "pubmed",
            "term": f"{condition} AND review[pt] AND humans[mh]",
            "retmax": max_results,
            "retmode": "json",
            "sort": "relevance",
        }
        if NCBI_API_KEY:
            search_params["api_key"] = NCBI_API_KEY

        search_resp = _request_with_retry(f"{PUBMED_BASE}esearch.fcgi", search_params, REQUEST_TIMEOUT)
        search_resp.raise_for_status()
        pmids = search_resp.json().get("esearchresult", {}).get("idlist", [])

        if not pmids:
            _cache_set("pubmed", condition, [])
            return []

        # Step 2: EFetch -- get the actual abstracts for those PMIDs.
        fetch_params = {
            "db": "pubmed",
            "id": ",".join(pmids),
            "retmode": "xml",
            "rettype": "abstract",
        }
        if NCBI_API_KEY:
            fetch_params["api_key"] = NCBI_API_KEY

        fetch_resp = _request_with_retry(f"{PUBMED_BASE}efetch.fcgi", fetch_params, REQUEST_TIMEOUT)
        fetch_resp.raise_for_status()

        root = ET.fromstring(fetch_resp.text)
        chunks = []
        for article in root.findall(".//PubmedArticle"):
            pmid = article.findtext(".//PMID", default="unknown")
            title = article.findtext(".//ArticleTitle", default="")
            abstract_parts = [el.text for el in article.findall(".//AbstractText") if el.text]
            abstract = " ".join(abstract_parts).strip()
            if not abstract:
                continue
            # Truncate long abstracts -- keeps the generation prompt focused,
            # matching the same "short, field-level chunks" philosophy as
            # the original kb_indexer.py chunking.
            abstract = abstract[:700]
            chunks.append(f"{condition} (PubMed, PMID {pmid}) -- {title}: {abstract}")

        _cache_set("pubmed", condition, chunks)
        return chunks

    except (requests.exceptions.RequestException, ET.ParseError) as e:
        print(f"[live_kb] PubMed fetch failed for {condition!r}: {e}")
        return []


def openfda_fetch(medicine: str) -> list[str]:
    """
    Fetches real FDA drug label data for a prescribed medicine. Returns
    chunk strings covering indications and key warnings, prefixed with
    the medicine name for provenance.

    Returns [] on any failure -- caller falls back to a generic "no
    additional drug information available" state, same fail-safe pattern
    as pubmed_fetch above.
    """
    cached = _cache_get("openfda", medicine)
    if cached is not None:
        return cached

    try:
        # Search by generic OR brand name -- prescriptions are often
        # written under either, and we don't know which the patient's
        # medicine string matches without a lookup.
        clean_name = medicine.split()[0] if medicine else medicine  # strip dosage, e.g. "Furosemide 20mg" -> "Furosemide"
        params = {
            "search": f'openfda.generic_name:"{clean_name}"+openfda.brand_name:"{clean_name}"',
            "limit": 1,
        }
        resp = _request_with_retry(OPENFDA_BASE, params, REQUEST_TIMEOUT)

        if resp.status_code == 404:
            # openFDA returns 404 (not an error payload) when nothing matches
            _cache_set("openfda", medicine, [])
            return []

        resp.raise_for_status()
        results = resp.json().get("results", [])
        if not results:
            _cache_set("openfda", medicine, [])
            return []

        label = results[0]
        chunks = []

        # Field names vary by drug (OTC vs prescription labeling differs) --
        # check multiple possible field names rather than assuming one.
        indications = label.get("indications_and_usage") or label.get("purpose")
        if indications:
            text = " ".join(indications)[:600]
            chunks.append(f"{medicine} (FDA label) -- what it's for: {text}")

        warnings = label.get("warnings") or label.get("warnings_and_precautions")
        if warnings:
            text = " ".join(warnings)[:600]
            chunks.append(f"{medicine} (FDA label) -- warnings: {text}")

        adverse = label.get("adverse_reactions")
        if adverse:
            text = " ".join(adverse)[:600]
            chunks.append(f"{medicine} (FDA label) -- possible side effects: {text}")

        _cache_set("openfda", medicine, chunks)
        return chunks

    except requests.exceptions.RequestException as e:
        print(f"[live_kb] OpenFDA fetch failed for {medicine!r}: {e}")
        return []
