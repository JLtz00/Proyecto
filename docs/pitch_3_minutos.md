# Pitch de tres minutos

## 0:00–0:30 · El problema

“Hoy un asesor atiende bajo presión y con información fragmentada. Una campaña estática puede repetir una oferta, ignorar una activación o insistir después de un rechazo. Movistar Total necesita algo más que un score: necesita la siguiente mejor conversación.”

## 0:30–1:10 · La solución

“Construimos un motor Closed-Loop NBO. Reconstruye el estado vigente del cliente, descarta ofertas incompatibles o ya activas, prioriza la ruta hacia Movistar Total y entrega oferta, canal, próxima oportunidad, argumento y rebate. Cada decisión queda trazada.”

Mostrar brevemente la arquitectura y abrir la demo guiada.

## 1:10–2:25 · La demo

1. `CLI000001` tiene móvil, pero le falta internet hogar: recomienda `OF005`.
2. La aceptación registra intención; los productos no cambian todavía.
3. La activación con evidencia cambia el estado a elegible MT y recalcula `OF022`.
4. Ante rechazo por precio, `OF022` entra en cooldown.
5. El sistema conserva la ruta estratégica con Movistar Total Básico y una fecha de recontacto.

Frase clave: “La recomendación no termina cuando el asesor la ve; evoluciona con el resultado real.”

## 2:25–2:50 · Evidencia

“Evaluamos sin fuga temporal y con clientes separados. El ranking mejora 7.24% en NDCG@3 frente al mejor baseline v2. Los modelos complejos no superaron los gates predictivos, así que el sistema activó un fallback calibrado. Preferimos una decisión honesta y auditable a una IA compleja sin evidencia.”

## 2:50–3:00 · Cierre

“No afirmamos ventas causales con datos simulados. Dejamos listo el funnel, la experimentación y el feedback para medirlas en un piloto. Convertimos una campaña en un sistema de decisión que aprende operacionalmente.”
