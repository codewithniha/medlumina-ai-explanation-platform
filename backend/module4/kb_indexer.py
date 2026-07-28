"""
kb_indexer.py

Chunks and indexes the static knowledge base (kb_data.py) into a shared,
read-only ChromaDB collection called "kb_static". This is indexed ONCE
(run this script directly, or call ensure_kb_indexed() on startup) and is
never patient-specific -- it's the reference shelf, not anyone's file.

Each KB entry is split into small field-level chunks (definition, causes,
symptoms, management) rather than one giant blob per condition. This keeps
retrieval precise: if the patient's report mentions "cardiomegaly", we want
to pull back a tight definition chunk, not a wall of text mixing definition,
causes, symptoms and treatment together.
"""

import os
import chromadb
from dotenv import load_dotenv

from kb_data import KB_ENTRIES
from embedding_config import embedding_fn as _embedding_fn, embed_passage_texts

load_dotenv()

CHROMA_PERSIST_DIR = os.getenv("CHROMA_PERSIST_DIR", "./chroma_store")
KB_COLLECTION_NAME = "kb_static"

# Embedding model: BAAI/bge-small-en-v1.5 (see embedding_config.py), runs
# locally, no API key needed, GPU-accelerated automatically if available
# (e.g. on Kaggle). Session indexing uses the same function for
# consistency -- see session_indexer.py.
#
# NOTE: this replaced Chroma's DefaultEmbeddingFunction (MiniLM). If you're
# upgrading an existing project, you MUST re-run this file with reset=True
# (the default when run directly) -- old MiniLM vectors are not compatible
# with bge-small vectors.


def get_chroma_client():
    return chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)


def _chunk_kb_entry(entry: dict) -> list[dict]:
    """Splits one KB_ENTRIES dict into field-level chunks with metadata."""
    condition = entry["condition"]
    fields = {
        "definition": entry["definition"],
        "common_causes": entry["common_causes"],
        "typical_symptoms": entry["typical_symptoms"],
        "general_management": entry["general_management"],
    }
    chunks = []
    for field_name, text in fields.items():
        chunks.append(
            {
                "id": f"{condition.lower().replace(' ', '_').replace('/', '_')}__{field_name}",
                "text": f"{condition} -- {field_name.replace('_', ' ')}: {text}",
                "metadata": {
                    "condition": condition,
                    "field": field_name,
                    "source": "static_kb",
                },
            }
        )
    return chunks


def build_kb_index(reset: bool = False) -> int:
    """
    Indexes all KB_ENTRIES into the kb_static collection.
    Returns the number of chunks indexed.

    reset=True wipes and rebuilds the collection -- use this whenever you
    edit kb_data.py, otherwise stale entries will linger.
    """
    client = get_chroma_client()

    if reset:
        try:
            client.delete_collection(KB_COLLECTION_NAME)
        except Exception:
            pass  # collection didn't exist yet, nothing to delete
        # ChromaDB 0.5.0 bug workaround: reusing the same client instance
        # for delete_collection() immediately followed by
        # get_or_create_collection() leaves a stale internal reference,
        # causing the very next write to fail with
        # "InvalidCollectionException: Collection <uuid> does not exist".
        # Getting a fresh client after the delete avoids this -- confirmed
        # this is what was breaking your kb_indexer.py run.
        client = get_chroma_client()

    collection = client.get_or_create_collection(
        name=KB_COLLECTION_NAME,
        embedding_function=_embedding_fn,
        metadata={"description": "Static medical knowledge base, patient-facing definitions"},
    )

    all_chunks = []
    for entry in KB_ENTRIES:
        all_chunks.extend(_chunk_kb_entry(entry))

    chunk_texts = [c["text"] for c in all_chunks]
    collection.upsert(
        ids=[c["id"] for c in all_chunks],
        documents=chunk_texts,
        metadatas=[c["metadata"] for c in all_chunks],
        embeddings=embed_passage_texts(chunk_texts),
    )

    return len(all_chunks)


def ensure_kb_indexed() -> None:
    """
    Call this on FastAPI startup. Indexes the KB only if the collection is
    empty or missing -- avoids re-indexing on every server restart.
    """
    client = get_chroma_client()
    try:
        collection = client.get_collection(KB_COLLECTION_NAME, embedding_function=_embedding_fn)
        if collection.count() > 0:
            return
    except Exception:
        pass
    n = build_kb_index(reset=True)
    print(f"[kb_indexer] Indexed {n} KB chunks into '{KB_COLLECTION_NAME}'.")


if __name__ == "__main__":
    n = build_kb_index(reset=True)
    print(f"Indexed {n} KB chunks covering {len(KB_ENTRIES)} conditions into '{KB_COLLECTION_NAME}'.")
