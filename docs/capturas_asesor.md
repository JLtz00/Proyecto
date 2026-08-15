# Capturas de la Mesa del asesor

Las cuatro capturas versionadas en `assets/screenshots/` se generan sobre Flask y un SQLite temporal. No modifican `artifacts/nbo.sqlite3`.

```powershell
python scripts/capture_advisor.py `
  --browser "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
```

El script inicia la aplicación en un puerto loopback efímero y captura un navegador Chromium real a 1440×1000:

1. `advisor-empty.png`: búsqueda sin cliente.
2. `advisor-found.png`: `CLI000013` encontrado en tema claro.
3. `advisor-rejection.png`: rechazo por precio y acción de recuperación.
4. `advisor-activation.png`: aceptación, activación con evidencia y nueva NBO.

El mismo comando genera además cinco respaldos del Modo Jurado:

1. `jury-start.png`: estado y recomendación iniciales.
2. `jury-acceptance.png`: aceptación sin cambio de cartera.
3. `jury-activation.png`: activación, nueva versión de estado y nueva NBO.
4. `jury-rejection.png`: rechazo por precio y cooldown.
5. `jury-evidence.png`: evidencia real separada de simulación y futuro.

La base temporal y el perfil del navegador se eliminan al finalizar. Ninguna captura modifica `artifacts/nbo.sqlite3`.
