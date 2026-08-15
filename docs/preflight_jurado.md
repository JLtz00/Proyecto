# Preflight del Modo Jurado

Ejecutar antes de la presentación:

```powershell
nbo-check
nbo-advisor --jury --port 5000
```

Checklist:

- `nbo-check` devuelve `ready: true` y todas las entradas de `evidence_versions` son `nbo_v2_1`.
- El puerto elegido está libre y la página abierta es `http://127.0.0.1:5000/jury`.
- “Reiniciar demo” vuelve al paso “Listo” y permite completar nuevamente las seis transiciones.
- Los tres perfiles de referencia muestran ruta hacia MT, elegible para MT y cliente que ya posee MT sin adquisición duplicada.
- Evidencia real, simulación y arquitectura futura usan etiquetas visuales diferentes.
- Las capturas de respaldo están disponibles en `assets/screenshots/jury-*.png`.
- No se afirma uplift, ventas reales ni preparación productiva.

Si el vivo falla, usar las capturas en este orden: inicio, aceptación, activación, rechazo y evidencia.
