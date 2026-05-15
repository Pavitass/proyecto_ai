# Resultados de evaluación — RAG retrieval

Dataset: 20 consultas reales de mesa de ayuda TI en español (`evals/dataset.json`). Cada consulta lleva su `expected_sources` (uno o varios .md de la KB que deberían recuperarse).

## Métricas comparadas

| Método | Precision@1 | Precision@3 | Precision@5 | Recall@5 | MRR | Latencia p50 | Latencia p95 |
|---|---|---|---|---|---|---|---|
| **RAG denso (MiniLM + Chroma)** | 60.0% | 80.0% | 85.0% | 82.5% | 0.69 | 15 ms | 40 ms |
| Baseline keyword (TF + overlap) | 65.0% | 85.0% | 85.0% | 77.5% | 0.75 | 0 ms | 0 ms |

## Speedup por cache

| Escenario | Latencia |
|---|---|
| Cold (primer query, carga vectorstore) | 5.3 s |
| Warm (query nueva, vectorstore ya en memoria) | 14 ms |
| Cached (mismo query repetido) | < 1 ms |

## Interpretación

- En este dataset relativamente pequeño y con KB de 12 archivos bien temáticamente separados, el **baseline lexical es competitivo**: empata en Precision@5 (85% vs 85%) y supera ligeramente al RAG denso en Precision@1 (65% vs 60%) y MRR (0.75 vs 0.69). Esto se explica porque las consultas conservan palabras-clave muy explícitas ("VPN", "Outlook", "Wi-Fi", "Teams") que coinciden literalmente con los títulos de los .md de la KB.
- El **RAG denso gana en Recall@5** (82.5% vs 77.5%): los embeddings recuperan fuentes adicionales válidas (segundo .md esperado en consultas multi-tema como VPN+Mac, impresora+Windows) que el keyword se pierde porque no contienen el término literal.
- **Latencia**: el baseline keyword es ~70× más rápido por query en caliente (< 1 ms vs ~15 ms), pero la diferencia absoluta (14 ms) es imperceptible para el usuario. El **cache LRU del RAG colapsa a < 1 ms** consultas repetidas dentro de una sesión — útil cuando el usuario repite la pregunta tras una respuesta confusa.
- El costo **cold-start del RAG es 5.3 s** (carga de sentence-transformers MiniLM + Chroma desde disco), pagado una sola vez por proceso. En despliegues serverless habría que amortizarlo con warm-up.
- **Conclusión académica**: con KB pequeña y vocabulario controlado, un baseline lexical razonable iguala al RAG denso en precisión. El valor del RAG aparece en (a) **recall** sobre consultas multi-tema, (b) **robustez a sinónimos/parafraseos** (no medidos aquí; el dataset reusa términos de la KB), y (c) **cache de queries repetidas**. Para subir Precision@1 del RAG conviene explorar un **híbrido (BM25 + denso) con re-ranking**.

## Cómo reproducir

```bash
HELPDESK_DESKTOP_PY_EXEC=1 ../.venv/bin/python3 -m evals.retrieval_eval
```

Genera `evals/results_retrieval.json` con los números crudos.
