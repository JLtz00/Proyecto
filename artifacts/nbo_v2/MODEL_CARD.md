# Model Card — Motor NBO v2

Creado: 2026-08-13T15:55:21.358182+00:00

## Uso previsto

Ranking explicable de ofertas elegibles y selección de canal para los datos sintéticos del desafío.

## Datos y separación

- 100,000 clientes; 22 ofertas; 300,112 ofrecimientos.
- Split principal 70/15/15 por cliente, manifiesto persistente y semilla 42.
- Robustez temporal enero–abril / mayo / junio.
- Los acumulados excluyen el evento evaluado y todos los eventos de su mes.
- Alpha bayesiano seleccionado en validación: 50.0.

## Selección honesta champion/fallback

- Contacto: `hierarchical_rate`; gate CatBoost: no aprobado.
- Aceptación: `hierarchical_rate`; gate CatBoost: no aprobado.
- Rechazo: `hierarchical_prior`; gate CatBoost: no aprobado.
- Los fallbacks jerárquicos se publican cuando CatBoost no demuestra mejora útil frente a baselines.

## Métricas de test

- Contacto: roc_auc=0.4965, pr_auc=0.8444, brier=0.1309, log_loss=0.4312, ece=0.0061.
- Aceptación condicionada a contacto: roc_auc=0.5277, pr_auc=0.3987, brier=0.2343, log_loss=0.6615, ece=0.0274.
- Motivo de rechazo: log_loss=1.6399, accuracy=0.3495, macro_f1=0.0863, top2_accuracy=0.5485.

## Evaluación final de ranking

- Cobertura evaluable: 82.0% (7,444 de 9,077).
- Hit@1: 0.110; Hit@3: 0.337; NDCG@3: 0.238.
- Mejora relativa NDCG@3 frente al mejor baseline: 7.2%.
- Gate final: APROBADO.
- Política temporal: solo meses completos anteriores al evento evaluado.
