# Preguntas difíciles y respuestas

## ¿Por qué es IA si el AUC está cerca de 0.5?

El sistema compara modelos, calibra probabilidades y rechaza automáticamente un modelo complejo cuando no supera un baseline. La versión activa usa estimación jerárquica, ranking personalizado, reglas de elegibilidad y adaptación con feedback. El valor demostrado está en el ranking y el ciclo operacional, no en fingir discriminación inexistente.

## ¿Cómo saben que aumentará ventas?

No lo afirmamos todavía. La evaluación offline demuestra recuperación de ofertas históricamente aceptadas, no uplift causal. El sistema registra exposición, contacto, aceptación y activación para habilitar un piloto A/B con métricas de conversión, MT, experiencia y fatiga.

## ¿Qué lo diferencia de una campaña segmentada?

Reconstruye el estado vigente, bloquea productos activos o incompatibles, separa aceptación de activación, conserva evidencia y recalcula inmediatamente la próxima acción tras cada resultado.

## ¿Por qué el LLM no decide la oferta?

Elegibilidad, precio y ranking deben ser reproducibles y auditables. El LLM es opcional y solo reformula el guion dentro de guardrails; ante cualquier error vuelve al texto determinista.

## ¿Es productivo?

Es un prototipo funcional y reproducible. Para producción necesita identidad, roles, una base multiusuario, observabilidad, secretos gestionados y un piloto controlado.
