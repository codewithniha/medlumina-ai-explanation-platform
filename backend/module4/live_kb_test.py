"""
live_kb_test.py

Standalone smoke test for live_kb.py -- run this FIRST, before running
retrieval_eval.py or the full API, to confirm PubMed and OpenFDA are
actually reachable from your network and returning real data. If this
fails, the problem is your network/API access, not the RAG pipeline --
worth isolating before debugging anything downstream.

Run with: python live_kb_test.py
"""

from live_kb import pubmed_fetch, openfda_fetch


def test_pubmed():
    print("=== PubMed test: Cardiomegaly ===")
    chunks = pubmed_fetch("Cardiomegaly", max_results=2)
    if not chunks:
        print("NO RESULTS -- either the API is unreachable, or genuinely no matches. Check the [live_kb] error message above, if any.")
    for c in chunks:
        print(f"- {c[:200]}...")
    print()


def test_openfda():
    print("=== OpenFDA test: Furosemide ===")
    chunks = openfda_fetch("Furosemide")
    if not chunks:
        print("NO RESULTS -- either the API is unreachable, or genuinely no matches. Check the [live_kb] error message above, if any.")
    for c in chunks:
        print(f"- {c[:200]}...")
    print()


if __name__ == "__main__":
    test_pubmed()
    test_openfda()
