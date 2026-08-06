# Proyecto

Repositorio del proyecto de personalización comercial inteligente.

## Estructura

- `dataset/`: archivos CSV con los datos del proyecto.
- `docs/`: documentación y descripción del desafío.

## Dashboard comercial

El dashboard presenta conclusiones comerciales sobre conversión, canales, portafolio,
oportunidad de Movistar Total, segmentación de clientes y fricciones operativas.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python build_dashboard.py
```

El resultado se guarda en `dashboard_EDA.html` y es autocontenido: puede abrirse sin
conexión a internet.

## Nota sobre los datos

Antes de publicar este repositorio, verifica que los archivos de `dataset/` no contengan información sensible y configura el repositorio como privado si corresponde.
