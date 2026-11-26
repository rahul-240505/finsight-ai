# ADR-009: Document Q&A: owner isolation, citations, deletion and versioning

- Status: Accepted · Date: 2026-11-26

## Context
Analysts upload policy PDFs and ask questions about them. Answers must come from the user's own documents only, cite the page they came from, say "not enough evidence" instead of guessing, and survive hostile document text. The chat model is a small local model (ADR-003), so safety cannot rely on the model obeying instructions.

## Options
1. **Framework (LangChain / LlamaIndex) + qdrant-client.** Fast to start; hides the retrieval and prompt logic and adds many dependencies (qdrant-client brings gRPC).
2. **Plain Python modules + Qdrant REST over httpx.** About 150 lines for the adapter; every filter and prompt is visible and testable; httpx is already a dependency.
3. **Text in Qdrant payloads** vs **text in Postgres, ids only in Qdrant.**

## Decision
- Option 2. `app/services/vector_store.py` wraps five Qdrant calls. **Every search and delete takes `owner_id`**; there is no unfiltered search method. `owner_id` is a tenant-indexed payload field.
- **Postgres holds the text** (`documents`, `document_chunks`); Qdrant holds vectors with `owner_id`, `document_id`, `page`. Search results are joined back to Postgres by owner and `status = 'ready'`, a second, independent ownership check.
- **Chunking:** sentence-packed chunks that never cross a page (each chunk cites exactly one page), with sentence overlap. Size chosen by the retrieval evaluation (docs/evaluation.md).
- **Indexing order:** parse → chunk → embed with no transaction open → insert rows (`indexing`) → upsert vectors (point id = chunk id, so retries overwrite) → `ready`. A vector-store failure deletes the rows again.
- **Idempotent by content:** `UNIQUE(owner_id, content_hash)`; re-uploading the same bytes returns the existing document (200).
- **Answering:** relevance gate on the best cosine score (tuned on the dev split only); sources fenced in `<source>` blocks with fence-breaking text removed; the model must cite `[S<n>]`; citations to unknown sources are removed and an answer with no valid citation becomes `not_enough_evidence`.
- **Deletion:** Postgres rows first (the text is gone at once), then vectors (best effort; leftovers can never be returned because of the join).
- **Versioning:** each document stores `embedding_model` and `chunker_version`; the collection's vector size is checked on first use. Changing the embedding model means re-indexing into a new collection.

## Consequences
- Isolation holds even if one layer has a bug: a missing Qdrant filter would still be stopped by the Postgres join, and the other way round.
- Chunking: 100 words with 20 overlap beat 200/40 and 350/60 on dev MRR@5 (0.865 vs 0.841).
- Relevance gate 0.64 (nomic-embed-text): the highest value that blocks no answerable dev question. A balanced-accuracy gate (0.689) blocked 6 of 42 answerable questions, because answerable and unanswerable scores overlap; the gate is a cheap first filter, and the model's own refusal plus the citation check are the second.
- On the fictional 6-document corpus (55 questions): 42/42 answered with a correct-page citation, citation precision 0.98, 10/10 unanswerable declined, 3/3 injection probes passed, median answer 1.32 s (docs/evaluation.md). A small self-written set: a regression suite, not proof of general quality.
- The threshold belongs to the embedding model: changing the model means re-measuring it.

## Revisit when
Documents become large or numerous enough that keyword search (hybrid BM25) or a re-ranker is needed; scanned PDFs (OCR) are required; indexing moves to the background worker.
