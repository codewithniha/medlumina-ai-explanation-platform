"""
session_indexer.py

Chunks and indexes ONE patient's data into its own dedicated ChromaDB
collection ("session_<session_id>"), separate from every other patient's
data and separate from the static KB. This is the "patient's folder" from
the earlier analogy -- retrieval always checks this collection first and
weighs it heavily, per your project's two-tier retrieval design.

Input data comes from two places, matching FE-2:
  - doctor_report: free text from the patient's own doctor's report
  - xray_findings: structured output from the vision modules (a dict of
    condition -> confidence/notes), which gets turned into readable chunks

A simple paragraph/sentence-based splitter is used for the doctor report
(good enough for typical report lengths -- a few paragraphs, not a novel).
Findings are chunked one-per-condition so retrieval can pull just the
relevant finding rather than the whole findings blob.
"""

import re
from kb_indexer import get_chroma_client, _embedding_fn
from embedding_config import embed_passage_texts


def _split_report_text(text: str, max_chars: int = 500) -> list[str]:
    """
    Splits doctor report text into chunks on paragraph boundaries first,
    falling back to sentence boundaries if a paragraph is too long. Keeps
    chunks under max_chars so each retrieved chunk stays focused.
    """
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    chunks = []
    for para in paragraphs:
        if len(para) <= max_chars:
            chunks.append(para)
        else:
            sentences = re.split(r"(?<=[.!?])\s+", para)
            current = ""
            for sent in sentences:
                if len(current) + len(sent) <= max_chars:
                    current = f"{current} {sent}".strip()
                else:
                    if current:
                        chunks.append(current)
                    current = sent
            if current:
                chunks.append(current)
    return chunks


def index_session_data(
    session_id: str,
    doctor_report: str = "",
    xray_findings: dict | None = None,
    prescribed_medicines: list[str] | None = None,
    symptoms: str = "",
) -> int:
    """
    Indexes a patient's report, structured X-ray findings, prescribed
    medicines, and reported symptoms into their session-specific Chroma
    collection. Safe to call multiple times for the same session (uses
    upsert) -- e.g. if findings come in after the report, or get
    corrected.

    Returns the number of chunks indexed.
    """
    client = get_chroma_client()
    collection_name = f"session_{session_id}"
    collection = client.get_or_create_collection(
        name=collection_name,
        embedding_function=_embedding_fn,
        metadata={"description": f"Session-specific patient data for {session_id}"},
    )

    ids, documents, metadatas = [], [], []

    if doctor_report:
        for i, chunk in enumerate(_split_report_text(doctor_report)):
            ids.append(f"report_{i}")
            documents.append(chunk)
            metadatas.append({"source": "doctor_report", "session_id": session_id})

    if xray_findings:
        for i, (condition, detail) in enumerate(xray_findings.items()):
            text = f"X-ray finding -- {condition}: {detail}"
            ids.append(f"finding_{i}")
            documents.append(text)
            metadatas.append({"source": "xray_finding", "condition": condition, "session_id": session_id})

    if prescribed_medicines:
        for i, med in enumerate(prescribed_medicines):
            ids.append(f"medicine_{i}")
            documents.append(f"Prescribed medicine: {med}")
            metadatas.append({"source": "prescribed_medicine", "medicine_name": med, "session_id": session_id})

    if symptoms:
        ids.append("symptoms_0")
        documents.append(f"Patient-reported symptoms: {symptoms}")
        metadatas.append({"source": "symptoms", "session_id": session_id})

    if not documents:
        return 0

    collection.upsert(
        ids=ids,
        documents=documents,
        metadatas=metadatas,
        embeddings=embed_passage_texts(documents),
    )
    return len(documents)


def get_session_collection(session_id: str):
    """Fetches an existing session collection, or None if it doesn't exist yet."""
    client = get_chroma_client()
    try:
        return client.get_collection(f"session_{session_id}", embedding_function=_embedding_fn)
    except Exception:
        return None
