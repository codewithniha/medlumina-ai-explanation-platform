"""
rag_reindex.py  --  Step 7: the question-answering search index follows the doctor's edit.

Analogy: a patient's folder holds a "current report" sheet. When the doctor signs off a corrected
report, the old sheet is taken out and shredded, and the new one goes in. Anyone who opens the folder
afterwards can only find the corrected sheet. (The old report is NOT lost: it stays in the version
history in the database, only the search index forgets it.)

What is replaced: the report and X-ray-finding chunks of ONE visit's collection ("session_<id>").
Medicines and symptoms the patient typed are left alone.

Order of work, chosen so a failure never leaves the visit with an EMPTY index:
  1. read the final version from the database,
  2. build the new chunks and their embeddings,
  3. add the new chunks (ids contain the version number, so they cannot collide with old ones),
  4. only then delete the old report / finding chunks.
If step 2 or 3 fails nothing was deleted; the next edit (or a manual call) simply tries again,
because everything is rebuilt from the final version in the database.
"""

import json
import re

REPORT_SOURCES = ["doctor_report", "xray_finding"]
MAX_CHARS = 500


def _label(name: str) -> str:
    s = name.replace("_", " ")
    return s[:1].upper() + s[1:]


def _split_long(text: str, max_chars: int = MAX_CHARS) -> list[str]:
    """Cut one long block at sentence ends so each chunk stays focused."""
    out, cur = [], ""
    for sent in re.split(r"(?<=[.!?])\s+", text.strip()):
        if cur and len(cur) + 1 + len(sent) > max_chars:
            out.append(cur)
            cur = sent
        else:
            cur = f"{cur} {sent}".strip()
    if cur:
        out.append(cur)
    return [c[:max_chars * 2] for c in out if c]


def report_chunks(report_text: str) -> list[str]:
    """One chunk per section of the template (FINDINGS / IMPRESSION / DOCTOR'S NOTE); long sections are cut."""
    chunks = []
    for block in re.split(r"\n\s*\n", (report_text or "").strip()):
        block = block.strip()
        if not block:
            continue
        chunks.extend([block] if len(block) <= MAX_CHARS else _split_long(block))
    return chunks


def build_chunks(session_id: str, version_no: int, report_text: str, structured: dict):
    """Returns (ids, documents, metadatas) for the report and findings of one version."""
    from doctor_edit import finding_detail   # same wording as the report itself

    ids, docs, metas = [], [], []
    base = {"session_id": session_id, "version_no": version_no}
    for i, chunk in enumerate(report_chunks(report_text)):
        ids.append(f"report_v{version_no}_{i}")
        docs.append(chunk)
        metas.append({**base, "source": "doctor_report"})
    removed = [_label(n) for n in (structured.get("removed_findings") or [])]
    if removed:
        ids.append(f"report_v{version_no}_removed")
        docs.append("The reviewing doctor removed these findings that the AI had suggested: "
                    + ", ".join(removed) + ". They are not part of the final report.")
        metas.append({**base, "source": "doctor_report", "kind": "doctor_removed"})
    for i, (name, f) in enumerate((structured.get("findings") or {}).items()):
        cond = _label(name)
        ids.append(f"finding_v{version_no}_{i}")
        docs.append(f"X-ray finding -- {cond}: {finding_detail(f)}")
        metas.append({**base, "source": "xray_finding", "condition": cond})
    return ids, docs, metas


def reindex_final_version(db, session_id: str) -> dict:
    """Make the visit's search index hold exactly the FINAL report version. Safe to call again."""
    row = db.execute(
        "SELECT version_no, report_text, structured_findings FROM report_versions "
        "WHERE session_id = ? AND is_final = 1", (session_id,)).fetchone()
    if row is None:
        raise RuntimeError("no final report version to index")
    structured = json.loads(row["structured_findings"] or "{}")
    ids, docs, metas = build_chunks(session_id, row["version_no"], row["report_text"], structured)

    # Imported here so that merely importing this module never needs the vector database.
    from kb_indexer import get_chroma_client, _embedding_fn
    from embedding_config import embed_passage_texts

    embeddings = embed_passage_texts(docs) if docs else []
    collection = get_chroma_client().get_or_create_collection(
        name=f"session_{session_id}",
        embedding_function=_embedding_fn,
        metadata={"description": f"Session-specific patient data for {session_id}"},
    )
    old_ids = collection.get(where={"source": {"$in": REPORT_SOURCES}}, include=[])["ids"]
    if docs:
        collection.upsert(ids=ids, documents=docs, metadatas=metas, embeddings=embeddings)
    stale = [i for i in old_ids if i not in set(ids)]
    if stale:
        collection.delete(ids=stale)
    return {"version_no": row["version_no"], "chunks": len(docs), "removed_old": len(stale)}
