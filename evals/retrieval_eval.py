"""Evaluación retrieval del RAG vs baseline keyword.

Métricas:
- Precision@1, Precision@3, Precision@5 (¿está alguna fuente esperada en top-k?)
- MRR (Mean Reciprocal Rank) sobre la primera fuente esperada
- Recall@5 (qué fracción de las fuentes esperadas aparecen en top-5)
- Latencia: cold (primer query), warm (segundo distinct query), cached (mismo query repetido)
"""
from __future__ import annotations

import json
import re
import statistics
import time
from pathlib import Path

from helpdesk_app import rag
from helpdesk_app.config import DATA_KB_DIR

EVAL_PATH = Path(__file__).resolve().parent
DATASET = json.loads((EVAL_PATH / "dataset.json").read_text(encoding="utf-8"))


def source_filename(metadata_source: str) -> str:
    """Chroma stores absolute paths in metadata['source']. Reduce to basename."""
    return Path(str(metadata_source or "")).name


def hits_at_k(retrieved_sources: list[str], expected: list[str], k: int) -> int:
    """1 si al menos una fuente esperada está en los primeros k, 0 si no."""
    return 1 if any(s in expected for s in retrieved_sources[:k]) else 0


def recall_at_k(retrieved_sources: list[str], expected: list[str], k: int) -> float:
    if not expected:
        return 0.0
    found = sum(1 for e in expected if e in retrieved_sources[:k])
    return found / len(expected)


def reciprocal_rank(retrieved_sources: list[str], expected: list[str]) -> float:
    for i, src in enumerate(retrieved_sources, start=1):
        if src in expected:
            return 1.0 / i
    return 0.0


def eval_rag(k: int = 5) -> dict:
    rag.invalidate_cache()
    p1, p3, p5, mrr, r5 = [], [], [], [], []
    latencies = []
    for entry in DATASET:
        t0 = time.time()
        docs = rag.buscar_contexto(entry["query"], k=k)
        dt = time.time() - t0
        latencies.append(dt)
        retrieved = [source_filename(d.metadata.get("source", "")) for d in docs]
        p1.append(hits_at_k(retrieved, entry["expected_sources"], 1))
        p3.append(hits_at_k(retrieved, entry["expected_sources"], 3))
        p5.append(hits_at_k(retrieved, entry["expected_sources"], 5))
        mrr.append(reciprocal_rank(retrieved, entry["expected_sources"]))
        r5.append(recall_at_k(retrieved, entry["expected_sources"], 5))
    return {
        "method": "rag_dense",
        "n": len(DATASET),
        "precision_at_1": statistics.mean(p1),
        "precision_at_3": statistics.mean(p3),
        "precision_at_5": statistics.mean(p5),
        "mrr": statistics.mean(mrr),
        "recall_at_5": statistics.mean(r5),
        "latency_p50_ms": round(statistics.median(latencies) * 1000, 1),
        "latency_p95_ms": round(sorted(latencies)[int(len(latencies) * 0.95) - 1] * 1000, 1),
        "latency_total_s": round(sum(latencies), 2),
    }


# ----- Baseline keyword (lexical) -----

_TOKEN_RE = re.compile(r"\w{3,}", re.UNICODE)
_STOPWORDS = {"que", "para", "con", "los", "las", "del", "una", "uno", "como", "este", "esta",
              "muy", "por", "sin", "más", "mas", "mis", "tus", "sus", "ese", "esa", "soy", "son",
              "esta", "está", "estoy", "ser", "estar"}


def tokenize(text: str) -> set[str]:
    return {t.lower() for t in _TOKEN_RE.findall(text or "") if t.lower() not in _STOPWORDS and len(t) > 2}


def load_kb_corpus() -> dict[str, str]:
    """Lee todos los .md de data/kb/ y devuelve {filename: contenido}."""
    out = {}
    for p in sorted(DATA_KB_DIR.glob("*.md")):
        out[p.name] = p.read_text(encoding="utf-8", errors="ignore")
    return out


def eval_keyword(k: int = 5) -> dict:
    corpus = load_kb_corpus()
    file_tokens = {fname: tokenize(text) for fname, text in corpus.items()}
    p1, p3, p5, mrr, r5 = [], [], [], [], []
    latencies = []
    for entry in DATASET:
        t0 = time.time()
        q_tokens = tokenize(entry["query"])
        if not q_tokens:
            ranked = list(file_tokens.keys())
        else:
            scores = []
            for fname, ftoks in file_tokens.items():
                overlap = len(q_tokens & ftoks)
                # tf-style: cuenta cuántas veces aparece cada token en el cuerpo
                if overlap > 0:
                    body = corpus[fname].lower()
                    tf = sum(body.count(t) for t in q_tokens)
                else:
                    tf = 0
                scores.append((overlap * 100 + tf, fname))
            scores.sort(reverse=True)
            ranked = [fname for _, fname in scores]
        dt = time.time() - t0
        latencies.append(dt)
        p1.append(hits_at_k(ranked, entry["expected_sources"], 1))
        p3.append(hits_at_k(ranked, entry["expected_sources"], 3))
        p5.append(hits_at_k(ranked, entry["expected_sources"], 5))
        mrr.append(reciprocal_rank(ranked, entry["expected_sources"]))
        r5.append(recall_at_k(ranked, entry["expected_sources"], 5))
    return {
        "method": "keyword_baseline",
        "n": len(DATASET),
        "precision_at_1": statistics.mean(p1),
        "precision_at_3": statistics.mean(p3),
        "precision_at_5": statistics.mean(p5),
        "mrr": statistics.mean(mrr),
        "recall_at_5": statistics.mean(r5),
        "latency_p50_ms": round(statistics.median(latencies) * 1000, 1),
        "latency_p95_ms": round(sorted(latencies)[int(len(latencies) * 0.95) - 1] * 1000, 1),
        "latency_total_s": round(sum(latencies), 2),
    }


def eval_cache_speedup() -> dict:
    """Mide cold vs warm vs cached para un mismo query repetido."""
    rag.invalidate_cache()
    query = DATASET[0]["query"]
    # Cold (incluye carga vectorstore si es primer query del proceso)
    t0 = time.time()
    rag.buscar_contexto(query, k=5)
    cold = time.time() - t0
    # Warm (otra query distinta para no usar cache)
    t0 = time.time()
    rag.buscar_contexto(DATASET[1]["query"], k=5)
    warm = time.time() - t0
    # Cached (mismo query)
    t0 = time.time()
    rag.buscar_contexto(query, k=5)
    cached = time.time() - t0
    return {
        "cold_ms": round(cold * 1000, 1),
        "warm_ms": round(warm * 1000, 1),
        "cached_ms": round(cached * 1000, 1),
    }


if __name__ == "__main__":
    print("== Cache / latencia ==")
    cache_stats = eval_cache_speedup()
    print(json.dumps(cache_stats, indent=2))

    print("\n== Baseline keyword ==")
    kw = eval_keyword()
    print(json.dumps(kw, indent=2))

    print("\n== RAG denso (sentence-transformers + Chroma) ==")
    rag_stats = eval_rag()
    print(json.dumps(rag_stats, indent=2))

    out = {"cache": cache_stats, "keyword": kw, "rag": rag_stats}
    (EVAL_PATH / "results_retrieval.json").write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print("\nResults written to evals/results_retrieval.json")
