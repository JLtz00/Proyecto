# Capturas recomendadas para la presentación

Las capturas verificadas están versionadas en `assets/screenshots/`. Se pueden regenerar desde un Streamlit local con `scripts/capture_streamlit.py` y un navegador basado en Chromium.

Las capturas deben tomarse en 1280×720 con el navegador al 100% y sin información personal.

1. `?view=demo&step=0`: estado inicial y `OF005`.
2. `?view=demo&step=1`: aceptación sin cambio de producto.
3. `?view=demo&step=2`: activación, estado `v1`, elegibilidad MT y `OF022`.
4. `?view=demo&step=3`: rechazo por precio y cooldown.
5. `?view=demo&step=4`: Movistar Total Básico y fecha de recontacto.
6. `?view=impact`: funnel ejecutivo con etiqueta “Escenario demostrativo”.
7. `?view=impact`, pestaña **Evidencia técnica**: evaluación v3 y lectura honesta.

Antes de capturar:

- En PowerShell, ejecutar `$env:NBO_PUBLIC_DEMO="true"` antes de iniciar Streamlit.
- Confirmar que no aparezca la vista persistente del asesor.
- Mantener visible el aviso de simulación.
- No recortar títulos, fuente de datos ni disclaimers.
