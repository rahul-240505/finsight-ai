"""Document Q&A evaluation on the fictional policy corpus.

Run from backend/ with Postgres, Qdrant and Ollama up:

    PYTHONPATH=. uv run python ../eval/run_rag_eval.py

Stage 1, retrieval only (embedding model, no chat model): for several chunk sizes, recall@k
and MRR on answerable questions, plus the best-match score of every question.
Stage 2, choices made on the dev split only: the chunk size (best MRR@5) and the relevance
gate (the highest cut-off that blocks no answerable dev question).
Stage 3, end to end through the real services (Postgres + Qdrant + Ollama) with the chosen
chunk size and gate: answer rate, keyword accuracy, citation accuracy, refusals on
unanswerable questions, prompt-injection probes and latency. Reported per split.
"""

import json
import secrets
import statistics
import time
from pathlib import Path

import numpy as np
from sqlalchemy import select

from app.core.config import get_settings
from app.db.models import Document, User
from app.db.session import get_sessionmaker
from app.modules.auth import service as auth_service
from app.modules.documents import service as documents
from app.modules.documents.chunking import chunk_pages
from app.modules.documents.pdf import extract_pages
from app.modules.rag import service as rag
from app.services.llm import OllamaProvider
from app.services.vector_store import QdrantStore
from tests.pdf_factory import make_pdf

ROOT = Path(__file__).resolve().parents[1]
PDF_DIR = ROOT / "data" / "policies"
OUT = ROOT / "data" / "eval" / "rag_eval.json"
CONFIGS = [(100, 20), (200, 40), (350, 60)]
KS = (1, 3, 5)
EVAL_EMAIL = "rag-eval@example.com"


def load() -> tuple[dict[str, bytes], list[dict]]:
    corpus = json.loads((ROOT / "eval" / "policy_corpus.json").read_text())
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    pdfs = {}
    for doc in corpus["documents"]:
        pdfs[doc["filename"]] = make_pdf(doc["pages"])
        (PDF_DIR / doc["filename"]).write_bytes(pdfs[doc["filename"]])
    lines = (ROOT / "eval" / "rag_questions.jsonl").read_text().splitlines()
    return pdfs, [json.loads(line) for line in lines if line.strip()]


def expected_set(q: dict) -> set[tuple[str, int]]:
    return {(e["filename"], e["page"]) for e in q["expected"]}


def first_hit_rank(ranked: list[tuple[str, int]], expected: set[tuple[str, int]]) -> int | None:
    return next((i + 1 for i, key in enumerate(ranked) if key in expected), None)


def retrieval_stage(llm: OllamaProvider, pdfs: dict[str, bytes], questions: list[dict]) -> dict:
    q_vecs = np.array(llm.embed([q["question"] for q in questions], "query"), dtype=float)
    q_vecs /= np.linalg.norm(q_vecs, axis=1, keepdims=True)
    results = {}
    for max_words, overlap in CONFIGS:
        keys, texts = [], []
        for filename, data in pdfs.items():
            for c in chunk_pages(extract_pages(data, 50), max_words, overlap):
                keys.append((filename, c.page))
                texts.append(c.text)
        c_vecs = np.array(llm.embed(texts, "document"), dtype=float)
        c_vecs /= np.linalg.norm(c_vecs, axis=1, keepdims=True)
        sims = q_vecs @ c_vecs.T
        ranks: dict[str, list[int | None]] = {"dev": [], "test": []}
        top1 = {}
        for qi, q in enumerate(questions):
            order = np.argsort(-sims[qi])
            top1[q["id"]] = float(sims[qi, order[0]])
            if q["type"] == "answerable":
                ranked = [keys[i] for i in order[:5]]
                ranks[q["split"]].append(first_hit_rank(ranked, expected_set(q)))
        ranks["all"] = ranks["dev"] + ranks["test"]
        results[f"{max_words}w/{overlap}"] = {
            "chunks": len(texts),
            **{split: rank_metrics(r) for split, r in ranks.items()},
            "top1_scores": top1,
        }
    return results


def rank_metrics(ranks: list[int | None]) -> dict[str, float]:
    n = len(ranks)
    out = {f"recall@{k}": round(sum(r is not None and r <= k for r in ranks) / n, 4) for k in KS}
    out["mrr@5"] = round(sum(1 / r for r in ranks if r) / n, 4)
    return out


def dev_scores(scores: dict[str, float], questions: list[dict]) -> tuple[list, list]:
    dev = [q for q in questions if q["split"] == "dev"]
    pos = [scores[q["id"]] for q in dev if q["type"] == "answerable"]
    neg = [scores[q["id"]] for q in dev if q["type"] == "unanswerable"]
    return pos, neg


def balanced_gate(scores: dict[str, float], questions: list[dict]) -> float:
    """Rule used in the first run (kept for comparison): best balanced accuracy on dev."""
    pos, neg = dev_scores(scores, questions)
    candidates = sorted(set(pos + neg))
    best, best_t = -1.0, 0.0
    for lo, hi in zip(candidates, candidates[1:], strict=False):
        t = (lo + hi) / 2
        bal = (np.mean([s >= t for s in pos]) + np.mean([s < t for s in neg])) / 2
        if bal > best:
            best, best_t = bal, t
    return round(float(best_t), 4)


def recall_first_gate(scores: dict[str, float], questions: list[dict]) -> float:
    """The highest cut-off that blocks no answerable dev question: midway between the weakest
    answerable score and the strongest unanswerable score below it. Blocking a real answer
    loses it; letting an unanswerable question through costs one model call, and the model
    and the citation check can still decline."""
    pos, neg = dev_scores(scores, questions)
    floor = min(pos)
    below = [s for s in neg if s < floor]
    return round((floor + max(below)) / 2 if below else floor - 0.01, 4)


def eval_user(db) -> User:
    user = db.scalar(select(User).where(User.email == EVAL_EMAIL))
    if user is None:
        user = auth_service.register(db, EVAL_EMAIL, secrets.token_urlsafe(24))
    return user


def has_keywords(answer: str, keywords: list[str]) -> bool:
    text = answer.lower()
    return all(any(alt.lower() in text for alt in k.split("|")) for k in keywords)


def end_to_end(pdfs: dict[str, bytes], questions: list[dict], gate: float, gate_on: bool) -> dict:
    settings = get_settings()
    settings.rag_min_score = gate if gate_on else 0.0
    llm = OllamaProvider(settings)
    store = QdrantStore(settings, collection="eval_chunks")
    store.drop_collection()
    db = get_sessionmaker()()
    user = eval_user(db)
    for doc in db.scalars(select(Document).where(Document.owner_id == user.id)):
        db.delete(doc)
    db.commit()
    ingest_ms = []
    for filename, data in pdfs.items():
        started = time.perf_counter()
        documents.ingest(db, user, llm, store, filename, data)
        ingest_ms.append((time.perf_counter() - started) * 1000)
    llm.chat([{"role": "user", "content": "Say OK."}], 5)  # warm-up, not timed
    rows = []
    for q in questions:
        started = time.perf_counter()
        a = rag.answer(db, user, llm, store, q["question"])
        rows.append(
            {
                "id": q["id"],
                "split": q["split"],
                "type": q["type"],
                "status": a.status,
                "reason": a.reason,
                "answer": a.answer,
                "cited": [[p.filename, p.page] for p in a.citations],
                "retrieved": [[p.filename, p.page, round(p.score, 4)] for p in a.passages],
                "called_model": a.model is not None,
                "latency_ms": round((time.perf_counter() - started) * 1000, 1),
            }
        )
    # Leave nothing behind: the eval user's documents (rows) and the eval collection.
    for doc in db.scalars(select(Document).where(Document.owner_id == user.id)):
        db.delete(doc)
    db.commit()
    db.close()
    store.drop_collection()
    return {"gate": settings.rag_min_score, "ingest_ms": ingest_ms, "rows": rows}


def summarise(rows: list[dict], questions: list[dict]) -> dict:
    by_id = {q["id"]: q for q in questions}
    out = {}
    for split in ("dev", "test", "all"):
        sel = [r for r in rows if split == "all" or r["split"] == split]
        ans = [r for r in sel if r["type"] == "answerable"]
        una = [r for r in sel if r["type"] == "unanswerable"]
        inj = [r for r in sel if r["type"] == "injection"]
        answered = [r for r in ans if r["status"] == "answered"]
        cites = [tuple(c) for r in answered for c in r["cited"]]
        good_cites = sum(
            tuple(c) in expected_set(by_id[r["id"]]) for r in answered for c in r["cited"]
        )
        recall5 = [
            first_hit_rank([(f, p) for f, p, _ in r["retrieved"]], expected_set(by_id[r["id"]]))
            for r in ans
        ]
        model_calls = [r["latency_ms"] for r in sel if r["called_model"]]
        out[split] = {
            "answerable": len(ans),
            "answered_rate": round(len(answered) / len(ans), 4) if ans else None,
            "keyword_accuracy": round(
                sum(has_keywords(r["answer"], by_id[r["id"]]["keywords"]) for r in answered)
                / len(ans),
                4,
            )
            if ans
            else None,
            "citation_accuracy": round(
                sum(
                    any(tuple(c) in expected_set(by_id[r["id"]]) for c in r["cited"])
                    for r in answered
                )
                / len(answered),
                4,
            )
            if answered
            else None,
            "citation_precision": round(good_cites / len(cites), 4) if cites else None,
            "qdrant_recall@5": round(sum(r is not None for r in recall5) / len(ans), 4)
            if ans
            else None,
            "unanswerable": len(una),
            "refusal_rate": round(sum(r["status"] != "answered" for r in una) / len(una), 4)
            if una
            else None,
            "refusal_reasons": {
                k: sum(r["reason"] == k for r in una) for k in {r["reason"] for r in una}
            },
            "injection_probes": len(inj),
            "injection_passed": sum(
                by_id[r["id"]]["must_not_contain"].lower() not in (r["answer"] or "").lower()
                for r in inj
            ),
            "latency_ms_p50": round(statistics.median(model_calls), 1) if model_calls else None,
            "latency_ms_p95": round(float(np.percentile(model_calls, 95)), 1)
            if model_calls
            else None,
        }
    return out


def main() -> None:
    settings = get_settings()
    pdfs, questions = load()
    llm = OllamaProvider(settings)
    retrieval = retrieval_stage(llm, pdfs, questions)
    for name, r in retrieval.items():
        for split in ("dev", "test", "all"):
            m = r[split]
            print(
                f"retrieval {name:8} {split:4} chunks {r['chunks']:3}  "
                + "  ".join(
                    f"{k} {m[k]:.3f}" for k in ("recall@1", "recall@3", "recall@5", "mrr@5")
                )
            )
    # Chunk size: best dev MRR@5 (ties → best dev recall@1, then the smaller chunk).
    chosen = max(
        CONFIGS,
        key=lambda c: (
            retrieval[f"{c[0]}w/{c[1]}"]["dev"]["mrr@5"],
            retrieval[f"{c[0]}w/{c[1]}"]["dev"]["recall@1"],
            -c[0],
        ),
    )
    settings.chunk_max_words, settings.chunk_overlap_words = chosen
    scores = retrieval[f"{chosen[0]}w/{chosen[1]}"]["top1_scores"]
    gate = recall_first_gate(scores, questions)
    print(
        f"chunking {chosen} (by dev MRR); gate {gate} (recall-first; balanced-accuracy rule "
        f"would give {balanced_gate(scores, questions)})"
    )

    runs = {}
    for label, gate_on in (("gate_on", True), ("gate_off", False)):
        run = end_to_end(pdfs, questions, gate, gate_on)
        run["summary"] = summarise(run["rows"], questions)
        runs[label] = run
        for split in ("dev", "test", "all"):
            s = run["summary"][split]
            print(f"{label:8} {split:4} " + json.dumps({k: v for k, v in s.items()}))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(
            {
                "prompt_version": rag.PROMPT_VERSION,
                "chunking": chosen,
                "retrieval": retrieval,
                "gate": gate,
                "runs": runs,
            },
            indent=2,
        )
    )
    print(f"results → {OUT}")


if __name__ == "__main__":
    main()
