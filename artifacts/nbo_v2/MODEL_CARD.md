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

## Evaluación complementaria v3

Sin reentrenar ni modificar `nbo_v2`, se añadió una evaluación por evento aceptado:

- 14,353 eventos aceptados; 11,897 evaluables (82.89%).
- Evaluables: Hit@1 12.30%, Hit@3 36.56%, NDCG@3 0.2596.
- Todos los aceptados: Hit@1 10.19%, Hit@3 30.30%, NDCG@3 0.2151.
- IC bootstrap 95% NDCG@3 evaluable: [0.2514, 0.2670].
- Mejora NDCG@3 frente al mejor baseline comparable: 17.46%.
- 16 ofertas distintas en Top 1 y concentración máxima 26.15%.

Los ablations confirman que la prioridad MT aporta cobertura estratégica al Top 3. El historial individual y el ajuste comercial no muestran mejora offline concluyente en el dataset sintético; se mantienen como información operacional y guardrail, no como evidencia causal. El reporte completo está en `reports/evaluation_v3.json`.
