"""
llm_client.py

Swappable interface between two backends, mirroring the pattern you already
have in Module 6 (llm_config.py / llm_client.py / llm_safety.py):

  - call_medgemma(prompt)   -> generation backend, via your Module 6 Colab +
                                ngrok server. Used for the actual patient
                                answer (FE-3), since MedGemma is your
                                medically-tuned model.
  - call_classifier_llm(prompt) -> fast/cheap backend (Gemini 2.5 Flash),
                                used ONLY for the session-grounded vs
                                generic-knowledge classification step.

Confirmed endpoint contract (from medgemma_colab_server.ipynb, Cell 6):
POST /generate accepting {"prompt": "...", "temperature": 0.3} and
returning {"text": "..."}. Matches what module6's llm_client.py already
expects, so both modules talk to the same server the same way.
"""

import os
import re
import requests
from langchain_google_genai import ChatGoogleGenerativeAI
from dotenv import load_dotenv

load_dotenv()

MEDGEMMA_API_URL = os.getenv("MEDGEMMA_API_URL", "").rstrip("/")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

_classifier_model = None

# ── Strips MedGemma's "thinking" preamble ───────────────────────────────────
# MedGemma-1.5-4b-it sometimes wraps its internal reasoning in <unusedNN>
# tokens before the real answer, e.g.:
#   "<unused94>thought\n...step-by-step reasoning, self-critique, a
#   'Confidence Score: 5/5' line...<unused95>Okay, I understand you're
#   asking why..."
# Confirmed live (2026-07-12): both the "detailed" and "simple" toggle test
# responses came back with this exact shape, and without this stripping,
# call_medgemma() was returning the ENTIRE thing -- including the model's
# raw internal reasoning and self-scoring -- as the patient-facing answer.
# That's not a cosmetic issue: a patient should never see the model's
# working notes. Module 6's llm_safety.py already solved this same problem
# for its JSON-extraction case (strip_json_fences() keeps only what's after
# the LAST <unusedNN> token); this is the same fix, isolated out for plain-
# text answers since Module 4 doesn't need JSON parsing at all.
_UNUSED_TOKEN_PATTERN = re.compile(r"<unused\d+>")


def _strip_thinking_preamble(text: str) -> str:
    matches = list(_UNUSED_TOKEN_PATTERN.finditer(text))
    if matches:
        text = text[matches[-1].end():]
    return text.strip()


# MedGemma occasionally leaks stray characters from an unexpected script
# into an otherwise-Urdu answer -- confirmed live TWICE, in TWO different
# scripts (Devanagari/Hindi: "पाॉ" mid-sentence; separately, Cyrillic
# characters mid-sentence). Patching one specific script at a time (the
# original version of this function only handled Devanagari) is an
# endless chase -- there's no reason to assume a third, different script
# won't show up next. This takes the opposite, more robust approach: an
# ALLOWLIST of what can legitimately appear in an Urdu medical answer
# (Urdu/Arabic script, Latin letters and digits for medicine names/English
# terms that legitimately mix in, common punctuation, whitespace), with
# any run of characters OUTSIDE that set removed -- catching Devanagari,
# Cyrillic, or any other unexpected script generically, not just the ones
# already seen. This is a symptom-level safety net (see the strengthened
# language rule in prompts.py for the root-cause side); keeping both
# because a defensive cleanup here costs nothing and catches it even on
# the rare occasion the prompt instruction alone doesn't fully prevent it.
_UNEXPECTED_SCRIPT_PATTERN = re.compile(
    r"[^\u0600-\u06FF\u0750-\u077F\uFB50-\uFDFF\uFE70-\uFEFF"
    r"a-zA-Z0-9\s.,!?;:()\-'\"/%\u060C\u061B\u061F]+"
)


def _strip_stray_devanagari(text: str) -> str:
    # Name kept as-is so the one existing call site doesn't need updating --
    # this function now does more than its original name suggests (see
    # comment above), but renaming risks missing a call site under time
    # pressure, and the docstring here is what matters for anyone reading
    # this later, not the exact function name.
    cleaned = _UNEXPECTED_SCRIPT_PATTERN.sub("", text)
    # Collapse any double-space left behind by a removed mid-sentence token.
    return re.sub(r"[ \t]{2,}", " ", cleaned).strip()


def _get_classifier_model():
    global _classifier_model
    if _classifier_model is None:
        if not GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY is not set -- check your .env file.")
        _classifier_model = ChatGoogleGenerativeAI(
            model="gemini-3.1-flash-lite",
            google_api_key=GEMINI_API_KEY,
            temperature=0,  # deterministic -- we want consistent routing, not creative routing
        )
    return _classifier_model


def call_medgemma(prompt: str, temperature: float = 0.3, timeout: int = 180, max_retries: int = 2) -> str:
    """
    Sends a prompt to the MedGemma server running in your Module 6 Colab
    notebook, reached via its ngrok tunnel. Raises a clear ConnectionError
    if the endpoint is unreachable after all retries -- callers
    (generator.py) are expected to catch this and fall back to a safe
    message rather than crash the request. Callers don't need to change
    anything -- the retry happens inside this function, so the external
    contract (raises ConnectionError, or returns text) is unchanged.

    temperature=0.3 matches the server's own default (see Cell 6), kept low
    since this is a medical explanation task, not creative writing --
    consistent, grounded answers matter more than varied phrasing here.

    timeout=180 (bumped from 60): Module 6's llm_client.py already learned
    this the hard way -- MedGemmaClient there was bumped from 90s to 180s
    because the free-tier Colab GPU intermittently needs that long under
    contention, and even 180s isn't always enough (see fe4_stability_check.py
    live output: Runs 3 and 10 both hit ReadTimeout AT 180s and needed a
    retry).

    max_retries=2 (added after a real, confirmed gap): this module had NO
    retry wrapper -- a single slow-but-otherwise-fine call had nowhere to
    recover, unlike Module 6's safe_invoke(). Confirmed via a real Module 4
    evaluation run: out of ~170 real questions, several genuinely legitimate
    calls needed more than one attempt to complete, and this module was
    previously giving up on the very first timeout. Only retries on
    request-level failures (timeout, connection error) -- a successful
    response with bad content isn't retried here, that's handled by the
    language-guarantee retry in generator.py instead, which is a different
    concern.

    Known, honest tradeoff: this can now take up to
    (timeout * max_retries) seconds in the worst case (~360s at the
    defaults) before finally giving up, instead of failing fast at 180s.
    That's the right tradeoff for a known-flaky free-tier GPU tunnel --
    reducing false failures matters more here than a fast failure --  but
    worth naming explicitly if a supervisor asks why an answer can be slow.
    """
    if not MEDGEMMA_API_URL:
        raise RuntimeError("MEDGEMMA_API_URL is not set -- start the Colab notebook and copy its ngrok URL into .env.")

    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            response = requests.post(
                f"{MEDGEMMA_API_URL}/generate",
                json={"prompt": prompt, "temperature": temperature},
                timeout=timeout,
            )
            response.raise_for_status()
            data = response.json()
            raw_text = data.get("text", "").strip()
            return _strip_stray_devanagari(_strip_thinking_preamble(raw_text))
        except requests.exceptions.RequestException as e:
            last_exc = e
            if attempt < max_retries - 1:
                print(f"[llm_client] MedGemma call failed (attempt {attempt + 1}/{max_retries}), retrying: {e}")

    raise ConnectionError(
        f"Could not reach MedGemma server at {MEDGEMMA_API_URL} after {max_retries} attempts: {last_exc}"
    ) from last_exc


def call_classifier_llm(prompt: str) -> str:
    """
    Sends a prompt to Gemini 2.5 Flash for the fast session-grounded vs
    generic-knowledge classification step. Kept separate from call_medgemma
    so classification latency never depends on the Colab/ngrok tunnel.
    """
    model = _get_classifier_model()
    result = model.invoke(prompt)
    return result.content.strip()


# ──────────────────────────────────────────────────────────────────────────────
# OFFLINE VERIFICATION — no network needed. The two fixtures below are your
# ACTUAL real MedGemma responses from the live "detailed"/"simple" toggle
# test (2026-07-12), not synthetic examples -- this is a permanent
# regression test built directly from the real bug, so a future prompt or
# server change can't silently reintroduce raw reasoning leaking into a
# patient-facing answer. Mirrors Module 6's offline-verification pattern.
# Run with: python llm_client.py
# ──────────────────────────────────────────────────────────────────────────────
_REAL_DETAILED_RAW_FIXTURE = """<unused94>thought
The user wants me to explain why it might be getting harder to breathe for a patient with emphysema.
1. Identify the core question, diagnosis, consult context, synthesize.
Confidence Score: 5/5 - The answer directly addresses the question using only the provided information and adheres to all rules.<unused95>Okay, I understand you're asking why your breathing might feel like it's getting harder over time.

Based on what we've seen, your X-ray showed hyperinflated lung fields, which is a sign of emphysema. Emphysema is a lung condition where the tiny air sacs, called alveoli, get damaged and destroyed over time.

The medicine you're taking, Tiotropium, helps to manage some of the symptoms associated with this condition, but it doesn't stop the underlying lung damage from progressing.

Do you have any other questions about this?"""

_REAL_SIMPLE_RAW_FIXTURE = """<unused94>thought
The user wants me to explain why the patient might be having more trouble breathing over time.
Final Answer Construction: "Okay, I understand you're asking why it might feel like breathing is getting more difficult over time..."<unused95>Okay, I understand you're asking why it might feel like breathing is getting more difficult over time.

The X-ray showed emphysema, which is a condition where the tiny air sacs in your lungs get damaged. That's why the medicine, Tiotropium, was prescribed to help manage the breathing difficulty."""


def _offline_verification() -> bool:
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

    print("\n[TEST 1] Real captured 'detailed' response: thinking preamble is fully stripped")
    cleaned = _strip_thinking_preamble(_REAL_DETAILED_RAW_FIXTURE)
    check("no leftover <unused...> tokens", "<unused" not in cleaned)
    check("no leaked 'Confidence Score' self-critique", "Confidence Score" not in cleaned)
    check("starts with the real answer, not reasoning", cleaned.startswith("Okay, I understand"))
    check("still contains the real content (alveoli mention)", "alveoli" in cleaned)

    print("\n[TEST 2] Real captured 'simple' response: thinking preamble is fully stripped")
    cleaned2 = _strip_thinking_preamble(_REAL_SIMPLE_RAW_FIXTURE)
    check("no leftover <unused...> tokens", "<unused" not in cleaned2)
    check("no leaked 'Final Answer Construction' planning text", "Final Answer Construction" not in cleaned2)
    check("starts with the real answer, not reasoning", cleaned2.startswith("Okay, I understand"))

    print("\n[TEST 3] Response with NO <unusedNN> tokens at all passes through unchanged (just stripped)")
    clean_input = "This response never had a thinking preamble to begin with."
    check("unmodified text is returned as-is", _strip_thinking_preamble(clean_input) == clean_input)

    print("\n[TEST 4] Multiple <unusedNN> tokens -- keeps only what's after the LAST one, not the first")
    multi_token = "<unused1>first reasoning block<unused2>second reasoning block<unused95>the real answer"
    check("kept text after the LAST token, not the first",
          _strip_thinking_preamble(multi_token) == "the real answer")

    print("\n[TEST 5] Empty string input doesn't crash")
    try:
        result = _strip_thinking_preamble("")
        check("empty input returns empty string, no crash", result == "")
    except Exception as e:
        check(f"empty input raised {type(e).__name__} -- should not crash", False)

    print("\n[TEST 6] call_medgemma retries on timeout, then succeeds")
    import requests as _requests

    global MEDGEMMA_API_URL
    original_url = MEDGEMMA_API_URL
    MEDGEMMA_API_URL = "http://fake-medgemma-for-test"

    call_count = {"n": 0}

    class _FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"text": "The X-ray shows normal findings."}

    def _fake_post_fails_once_then_succeeds(url, json, timeout):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise _requests.exceptions.Timeout("simulated timeout on first attempt")
        return _FakeResponse()

    real_post = _requests.post
    _requests.post = _fake_post_fails_once_then_succeeds
    try:
        result = call_medgemma("test prompt", max_retries=2)
        check("eventually succeeded after 1 retry", result == "The X-ray shows normal findings.")
        check("took exactly 2 attempts (1 failure + 1 success)", call_count["n"] == 2)
    finally:
        _requests.post = real_post

    print("\n[TEST 7] call_medgemma raises ConnectionError after exhausting all retries")
    call_count["n"] = 0

    def _fake_post_always_fails(url, json, timeout):
        call_count["n"] += 1
        raise _requests.exceptions.Timeout("simulated permanent timeout")

    _requests.post = _fake_post_always_fails
    try:
        try:
            call_medgemma("test prompt", max_retries=3)
            check("raised ConnectionError after exhausting retries", False)
        except ConnectionError:
            check("raised ConnectionError after exhausting retries", True)
        check("made exactly max_retries attempts, not more", call_count["n"] == 3)
    finally:
        _requests.post = real_post
        MEDGEMMA_API_URL = original_url

    print("\n" + "=" * 60)
    print(f"{passed}/{passed + failed} offline verification tests passed.")
    print("=" * 60)
    return failed == 0


if __name__ == "__main__":
    _offline_verification()
