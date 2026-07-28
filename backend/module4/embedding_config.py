"""
embedding_config.py

Centralizes the embedding model used across kb_indexer.py and
session_indexer.py.

UPGRADED (this change): from BAAI/bge-small-en-v1.5 (English-only) to
intfloat/multilingual-e5-small, so patient reports/findings written in
Urdu actually retrieve correctly, not just patient Q&A (that part -- the
patient asking/being answered in Urdu -- was already handled at the prompt
level in prompts.py/module4_pipeline.py and doesn't depend on this file at
all). bge-small has no meaningful understanding of Urdu text; feeding it
Urdu made retrieval unreliable. multilingual-e5-small covers 100+
languages including Urdu, and stays close in size/speed to the old model
(~118M params) so it still runs comfortably on a laptop CPU -- the bigger
BAAI/bge-m3 would be stronger but noticeably heavier, not worth it for a
laptop demo.

IMPORTANT DIFFERENCE FROM bge (read before touching this file again):
bge only needed a prefix on the QUERY side (see the old
embed_query_text-only design, and retriever.py's docstring). e5 models
need a prefix on BOTH sides: "query: " for questions, "passage: " for
indexed documents. Skipping the passage-side prefix doesn't crash
anything -- it just quietly degrades retrieval quality, which is exactly
the kind of bug that's easy to miss until you specifically test Urdu
report retrieval. This file now exposes embed_passage_texts() for that
side, and session_indexer.py / kb_indexer.py call it explicitly when
building embeddings for storage.

WHY EMBEDDINGS ARE PRECOMPUTED HERE, RATHER THAN LETTING CHROMA APPLY THE
EMBEDDING FUNCTION AUTOMATICALLY (as it still does for queries): the text
Chroma stores under `documents` is later fed directly into the LLM
generation prompt as the patient's own report content. If "passage: " were
baked into the stored text itself (the simplest-looking approach), that
literal prefix would leak into what MedGemma sees, and potentially into
debug output / BM25 tokenization. Precomputing the embedding separately
means the RAW, unprefixed text is what gets stored and later shown to the
LLM -- the prefix only ever exists transiently, for the embedding
calculation itself.

IMPORTANT: switching embedding models changes the vector space. After
this change, you MUST re-index: run kb_indexer.py directly (reset=True is
already the default when run directly) and re-run session_indexer.py /
re-create any sessions you want to keep testing with. Old vectors from
bge-small are NOT compatible with multilingual-e5-small vectors -- mixing
them silently returns wrong/irrelevant results, it will not error out.
"""

import os

# MUST be set before transformers/sentence_transformers get imported
# anywhere (directly or indirectly via chromadb). Without this, if a
# stray `tf_keras` package is present in your environment without a
# working TensorFlow install, transformers tries to auto-detect and load
# TensorFlow, crashes on `tensorflow.compat.v2`, and takes sentence-
# transformers down with it -- even though we only ever use the PyTorch
# backend here. This line tells transformers to never even check.
os.environ.setdefault("USE_TF", "0")
os.environ.setdefault("USE_TORCH", "1")

import torch
from sentence_transformers import SentenceTransformer
from chromadb.utils import embedding_functions

MODEL_NAME = "intfloat/multilingual-e5-small"

_device = "cuda" if torch.cuda.is_available() else "cpu"

QUERY_INSTRUCTION = "query: "
PASSAGE_INSTRUCTION = "passage: "

# Raw model instance, used directly for embed_passage_texts() below (see
# module docstring for why documents are embedded manually instead of via
# Chroma's automatic embedding_function).
_model = SentenceTransformer(MODEL_NAME, device=_device)

# Still used for QUERY-time Chroma calls (collection.query(query_texts=...))
# -- the query text is transient (never stored), so there's no leakage
# concern on that side, and letting Chroma handle it there keeps
# retriever.py's existing query-time code unchanged.
embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
    model_name=MODEL_NAME,
    device=_device,
    normalize_embeddings=False,  # must match embed_passage_texts() below exactly
)


def embed_query_text(question: str) -> str:
    """Applies e5's required query prefix. Use for QUERIES only -- pass the
    result to collection.query(query_texts=[...]), never use this for
    documents being indexed (see embed_passage_texts for that)."""
    return f"{QUERY_INSTRUCTION}{question}"


def embed_passage_texts(texts: list[str]) -> list[list[float]]:
    """
    Computes embeddings for a list of documents with e5's required
    "passage: " prefix applied -- WITHOUT that prefix ever being stored or
    returned. Pass texts (raw, unprefixed) in; get back one embedding
    vector per text, ready to pass as Chroma's `embeddings=` argument
    alongside the original raw `documents=` list.

    normalize_embeddings=False and convert_to_numpy=True are not
    arbitrary -- they match EXACTLY what Chroma's
    SentenceTransformerEmbeddingFunction does internally for queries (see
    embedding_fn above). If these ever drift out of sync, query and
    document vectors would be computed inconsistently and retrieval
    quality would silently degrade -- it would not throw an error, it
    would just start returning worse results for a reason that's hard to
    spot. Keep this function's parameters matching embedding_fn's if you
    ever change either.
    """
    if not texts:
        return []
    prefixed = [f"{PASSAGE_INSTRUCTION}{t}" for t in texts]
    return _model.encode(
        prefixed, convert_to_numpy=True, normalize_embeddings=False
    ).tolist()
