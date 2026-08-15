# Pitch de tres minutos

## 0:00–0:30 · El problema

“Hoy un asesor atiende bajo presión y con información fragmentada. Una campaña estática puede repetir una oferta, ignorar una activación o insistir después de un rechazo. Movistar Total necesita algo más que un score: necesita la siguiente mejor conversación.”

## 0:30–1:10 · La solución

“Construimos un motor Closed-Loop NBO. Reconstruye el estado vigente del cliente, descarta ofertas incompatibles o ya activas, prioriza la ruta hacia Movistar Total y entrega oferta, canal, próxima oportunidad, argumento y rebate. Cada decisión queda trazada.”

Mostrar brevemente la arquitectura y abrir la demo guiada.

## 1:10–2:25 · La demo

1. Abrir el caso `CLI000001`: el motor obtiene dinámicamente la necesidad, oferta y canal.
2. Registrar la aceptación y señalar que los productos y la versión de estado todavía no cambian.
3. Confirmar la activación con evidencia: el estado avanza y el motor calcula una nueva NBO.
4. Registrar un rechazo por precio sobre esa nueva recomendación: aparece cooldown y fecha de recontacto.
5. Recalcular y mostrar cómo se reordenan las ofertas elegibles sin fijar IDs en el guion.

Frase clave: “La recomendación no termina cuando el asesor la ve; evoluciona con el resultado real.”

## 2:25–2:50 · Evidencia

”Evaluamos sin fuga temporal, con clientes separados y cobertura explícita. Esta pantalla lee los resultados de la versión activa: AUC/Brier, ranking, cobertura, diversidad, batch de 100 mil y latencia. Contacto discrimina poco y aceptación aporta señal moderada; por eso mostramos el modelo que realmente ganó cada gate.”

## 2:50–3:00 · Cierre

”No afirmamos uplift ni ventas causales con la simulación. Proponemos un piloto de 4–6 semanas con grupo control para medir adopción, activación, uplift, experiencia y valor económico. Hoy entregamos un copiloto auditable; no una automatización productiva.”
