# Preguntas difíciles y respuestas

## ¿Por qué es IA si el AUC está cerca de 0.5?

El sistema compara modelos, calibra probabilidades y rechaza automáticamente un modelo complejo cuando no supera un baseline. `nbo_v2_1` publica el ganador real por objetivo, ranking personalizado, reglas de elegibilidad y adaptación con feedback. Contacto tiene poca capacidad discriminativa y aceptación una señal moderada; no ocultamos esas limitaciones.

## ¿Esto ya está listo para producción?

No. Es un MVP útil como copiloto y como base de un piloto asistido. CRM/Customer 360, consentimiento, inventario/cobertura, órdenes y observabilidad aparecen expresamente como arquitectura futura.

## ¿Las cifras de funnel son ventas reales?

No. El bloque de funnel y economía está rotulado permanentemente “simulación, no ventas reales”, muestra supuestos y fórmula, y está separado de la evidencia operacional.

## ¿Cómo demostrarían impacto?

Con un piloto de 4–6 semanas, tratamiento y control, midiendo adopción, contacto, aceptación, activación, uplift, tiempo de gestión, reclamos, cancelación y valor económico.

## ¿Cómo saben que aumentará ventas?

No lo afirmamos todavía. La evaluación offline demuestra recuperación de ofertas históricamente aceptadas, no uplift causal. El sistema registra exposición, contacto, aceptación y activación para habilitar un piloto A/B con métricas de conversión, MT, experiencia y fatiga.

## ¿Qué lo diferencia de una campaña segmentada?

Reconstruye el estado vigente, bloquea productos activos o incompatibles, separa aceptación de activación, conserva evidencia y recalcula inmediatamente la próxima acción tras cada resultado.

## ¿Por qué el LLM no decide la oferta?

Elegibilidad, precio y ranking deben ser reproducibles y auditables. El LLM es opcional y solo reformula el guion dentro de guardrails; ante cualquier error vuelve al texto determinista.

## ¿Es productivo?

Es un prototipo funcional y reproducible. Para producción necesita identidad, roles, una base multiusuario, observabilidad, secretos gestionados y un piloto controlado.
