# Evaluación offline v3

Evaluación por evento aceptado, con separación por cliente y política temporal sin fuga.

## Cobertura

- Eventos aceptados: 14,353
- Evaluables: 11,897 (82.9%)
- No evaluables: 2,456; cuentan como fallo en la métrica absoluta.

## Ranking

| Universo | Hit@1 | Hit@3 | NDCG@3 |
|---|---:|---:|---:|
| Evaluables | 12.25% | 36.55% | 0.2598 |
| Todos los aceptados | 10.15% | 30.29% | 0.2153 |

Mejora relativa NDCG@3 frente al mejor baseline comparable: **17.56%**.

Estas métricas son offline y observacionales; no demuestran uplift ni causalidad.
