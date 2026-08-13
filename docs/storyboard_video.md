# Storyboard del video de jurado

Duración objetivo: 75 segundos. Formato: 1280×720, subtítulos incrustados, sin depender de audio.

| Tiempo | Pantalla | Subtítulo |
|---|---|---|
| 0–10 s | Problema | “Una oferta estática ignora el estado y el resultado de la conversación.” |
| 10–22 s | Solución | “Closed-Loop NBO reconstruye estado, prioriza MT y explica la siguiente acción.” |
| 22–35 s | OF005 | “CLI000001 necesita internet hogar: OF005 completa la ruta.” |
| 35–47 s | Activación | “Aceptar no cambia productos. La activación con evidencia sí.” |
| 47–59 s | OF022 y rechazo | “Elegible MT: OF022. Si rechaza por precio, se aplica cooldown.” |
| 59–69 s | Recuperación | “El motor conserva la ruta MT con un tier inferior y fecha de recontacto.” |
| 69–75 s | Evidencia | “Ranking +7.24% NDCG@3; trazable, reproducible y listo para piloto A/B.” |

Generación reproducible:

```powershell
python -m pip install -e ".[media]"
python scripts/render_pitch_video.py
```

El archivo final se genera en `assets/demo_jury.mp4`.
