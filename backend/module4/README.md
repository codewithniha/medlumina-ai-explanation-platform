# MedLumina — Module 4: Question Answering (RAG)

## What this is

Patient-facing Q&A over a patient's own X-ray report/findings, with a hard
boundary against answering generic medical questions. Everything below has
been smoke-tested for logic correctness (chunking, two-tier retrieval,
session memory) in this session — see the test runs in chat. The only piece
that needs YOUR machine to fully verify is the live MedGemma call, since
that depends on your Colab notebook being up.

## Architecture

```
Doctor report + X-ray findings + medicines
        │
        ▼
 session_indexer.py  ──► session_<id> ChromaDB collection (per patient)
                                                    │
kb_data.py ──► kb_indexer.py ──► kb_static ChromaDB collection (shared, once)
                                                    │
Patient question                                   │
        │                                           │
        ▼                                           │
 classifier.py (Gemini 2.5 Flash)                    │
        │                                           │
   ┌────┴─────┐                                     │
   │          │                                     │
GENERIC   SESSION_GROUNDED                           │
   │          │                                     │
   ▼          ▼                                     │
DECLINE   retriever.py ──► session chunks (primary) ─┘
          │                + KB chunks (supporting only,
          │                  only for terms found in session chunks)
          ▼
 generator.py ──► prompts.py (grounding rules) ──► llm_client.py ──► MedGemma (Colab/ngrok)
          │
          ▼
 session_store.py (SQLite: logs turn, feeds conversation history into next prompt)
```

## Files

| File | Role |
|---|---|
| `kb_data.py` | Static KB content — 12 chest X-ray conditions, patient-facing language |
| `kb_indexer.py` | Chunks + indexes KB into shared `kb_static` Chroma collection |
| `session_indexer.py` | Chunks + indexes one patient's report/findings/meds into their own Chroma collection |
| `session_store.py` | SQLite session + conversation memory (see "Why SQLite" below) |
| `llm_client.py` | Swappable backend: `call_medgemma()` for generation, `call_classifier_llm()` (Gemini) for routing |
| `classifier.py` | The explicit routing step — SESSION_GROUNDED vs GENERIC_KNOWLEDGE |
| `retriever.py` | Two-tier retrieval: session first, KB only for matched terms |
| `prompts.py` | All prompt templates in one place — show this in your defense |
| `generator.py` | Builds the grounded prompt, calls MedGemma, fails safely if unreachable |
| `module4_pipeline.py` | Orchestrates the full flow, single entry point |
| `module4_api.py` | FastAPI: `/session/start`, `/session/ask` |
| `test_module4.py` | 16 paired examples for classifier accuracy — your defense evidence |

## Setup

```bash
cd module4
pip install -r requirements.txt --break-system-packages
cp .env.example .env
# edit .env: add your GEMINI_API_KEY, and MEDGEMMA_API_URL from your running Colab notebook
```

Run the API:
```bash
uvicorn module4_api:app --reload --port 8001
```

Run the classifier evaluation (doesn't need MedGemma/Colab running):
```bash
python test_module4.py
```

## Decisions made for you, and why

1. **Classifier uses Gemini 2.5 Flash, not MedGemma.** Routing every question
   through your Colab/ngrok tunnel twice (classify + generate) would make
   every single question slow and adds a second failure point tied to
   whether Colab happens to be up. Gemini is already part of your stack.
   MedGemma is reserved for the one job that actually needs a
   medically-tuned model: the final answer.

2. **SQLite instead of Postgres for session memory.** Nothing in your
   current setup runs a Postgres server. SQLite is a single file, zero
   setup, and the only place in the codebase that touches SQL directly —
   swapping to Postgres later (if you ever need to) is a contained change.

3. **KB scoped to 12 common chest X-ray findings**, not a general
   encyclopedia. Matches the scope of your Module 6 KB (31 focused entries)
   rather than an unbounded scraped dataset — realistic for an FYP
   timeline and easier to verify every entry is correct for your defense.

4. **MedGemma endpoint contract is assumed**, not confirmed. `llm_client.py`
   assumes your Colab server exposes `POST /generate` with
   `{"prompt": ...}` → `{"response": ...}`. I don't have your actual
   `medgemma_colab_server.ipynb` in front of me — if the real contract
   differs, there are two lines marked `<-- ADJUST HERE` in
   `call_medgemma()` to fix. Paste me that notebook's server cell if you
   want me to match it exactly instead of guessing.

## What's NOT built yet (intentionally, to keep this reviewable)

- No PubMed/OpenFDA API integration (FE-2 mentions these; the current KB is
  static/curated instead — a reasonable FYP scope-down, but flaggable to
  your supervisor if he expects live API calls).
- No frontend — this is the backend/API layer only.
- FE-4's "adapt to user's apparent knowledge level" is currently just a
  plain-language instruction in the prompt, not a dynamic complexity
  detector. A real detector would be a good "future work" line in your
  report if you want one, but is unlikely to be worth building given your
  timeline.

## Evaluation methodology for your defense

`test_module4.py` runs 16 paired questions (same topic, one generic
phrasing and one session-grounded phrasing) through the classifier and
reports accuracy. This directly demonstrates the classifier is reasoning
about *grounding*, not just topic — e.g. "What is cardiomegaly?" (declined)
vs "Why do I have cardiomegaly?" (answered) are about the same condition but
routed differently. Good evidence to walk through live in your defense.
