# Model Card — Motor NBO v2

Creado: 2026-08-14T23:55:21.402292+00:00

## Uso previsto

Ranking explicable de ofertas elegibles y selección de canal para datos sintéticos del desafío.

## Datos y separación

- 100,000 clientes; catálogo de 22 ofertas; 300,112 ofrecimientos.
- Split principal 70/15/15 por cliente con semilla 42.
- Robustez temporal enero–abril / mayo / junio.
- Los acumulados excluyen el evento y todo su mes.

## Modelos seleccionados

- Contacto: `hierarchical_rate`.
- Aceptación: `logistic`.
- Rechazo: `hierarchical_prior`.

## Métricas de test

- Contacto: roc_auc=0.4965, brier=0.1309, log_loss=0.4312.
- Aceptación condicionada a contacto: roc_auc=0.5948, brier=0.2220, log_loss=0.6359.
- Motivo de rechazo: accuracy=0.3495, macro_f1=0.0863, log_loss=1.6399.

## Limitaciones y uso responsable

- La señal histórica de contacto no diferencia clientes de forma concluyente; se conserva el baseline calibrado.
- El perfil es un resumen estático de seis meses, no un snapshot mensual perfecto.
- La evaluación observacional refleja la política histórica y no demuestra causalidad.
- Precio normalizado es un proxy de valor; no existe margen en los datos.
- No predice churn ni éxito de rebate por ausencia de targets válidos.
- No usar edad o región para excluir ofertas; solo para auditoría de desempeño.
