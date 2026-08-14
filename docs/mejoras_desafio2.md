# Mejoras Desafío 2 — Bitácora de cambios

Este documento resume las mejoras incorporadas al motor NBO para cerrar los gaps identificados frente a la rúbrica del Desafío 2 del Hackathon AI Telecom 2026 (ver `docs/Desafío 2 Hackathon AI Telecom 2026.pdf` y `docs/Concluciones del Dashboard.pdf`). Se dejó fuera, por decisión del usuario, la **IA generativa para speech** (queda como pendiente si se quiere seguir cerrando el gap).

---

## 1. Cumplimiento de la rúbrica del Desafío 2

| Requisito de la rúbrica | Estado previo | Estado actual | Dónde |
|---|---|---|---|
| Motor NBO recomienda mejor oferta, canal y momento | ✅ | ✅ (sin cambios; ya cumplía) | `src/nbo/engine.py`, reglas en `src/nbo/rules.py` |
| Explicabilidad + probabilidad de aceptación | ✅ | ✅ (sin cambios) | `Explanation`, `probabilidad_aceptacion` en `NBOResult` |
| Vista para asesor bajo presión de tiempo | ⚠️ densa | ✅ **Vista simple** en la Mesa | Toggle "Vista simple" en sidebar de `streamlit_app.py` |
| Recomendación + scoring + segmentación/clustering | ⚠️ solo ranking | ✅ **K-Means k=5 con personas nombradas** | `src/nbo/enrichment.py::train_personas` |
| Predicción de aceptación **y churn** | ❌ churn ausente | ✅ **Churn proxy** en cada recomendación | `src/nbo/enrichment.py::ChurnModel` |
| IA generativa para speech comercial | ❌ | ❌ (excluido a pedido del usuario) | `src/nbo/llm_renderer.py` existe como andamiaje pero deshabilitado |
| Datos simulados, sin PII | ✅ | ✅ | `dataset/` sin DNI/teléfono; edad/región solo para auditoría |
| Métricas de impacto del desafío (MT hogar/móvil, ARPU, churn) | ❌ solo ranking offline | ✅ **KPIs del Desafío 2** en vivo y como reporte HTML | `src/nbo/challenge_metrics.py`, vista Impacto y `reports/challenge_kpis.html` |
| Priorización explícita de MT | ⚠️ implícita en score | ✅ **Uplift MT estimado** y peso `w_mt` visible en what-if | `src/nbo/enrichment.py::compute_uplift_mt`, `render_whatif` |
| Trazabilidad | ✅ | ✅ (sin cambios) | `DecisionTrace`, ledger append-only SQLite |
| Higiene del repo (evitar CSVs con potencial fuga en raíz) | ⚠️ | ✅ | `notebooks/eda/` |

**Veredicto:** cumplimos **todos** los requisitos del desafío excepto el de IA generativa (deliberadamente fuera de alcance). Los demás bloques imaginados por la rúbrica están cubiertos con implementación funcional, no solo declarada.

---

## 2. Cambios implementados

### 2.1 Modelo de churn proxy — `src/nbo/enrichment.py::ChurnModel`

Regresión logística sobre un proxy operacional del riesgo de fuga. La etiqueta proxy se define explícitamente como:

> `1` si (caída_facturación<0.70 y antigüedad≥6) o sin servicios activos o `dias_mora_prom`>20 o `meses_moroso`≥3 o `n_reclamos`≥3.

Se declara honestamente en el propio artefacto (`proxy_definition`) que **no es churn observado**.

- Prevalencia proxy: **17.5 %**
- Brier: 0.035 · Log-loss: 0.121 · ROC-AUC: 0.986 sobre el propio proxy (indicador de que el modelo aprendió la regla suavizada, no de que prediga churn real).
- Salida: `probabilidad` continua y `nivel` en `{bajo, medio, alto}` con umbrales 0.35 / 0.65.
- **Impacto en el ranking**: se añade `w_churn` al `scoring` (default 0.05); `score_churn_component = -w_churn · p_churn` penaliza recomendaciones a clientes en riesgo alto.

### 2.2 Segmentación K-Means — `src/nbo/enrichment.py::PersonaModel`

K-Means k=5 sobre features de antigüedad, facturación, consumo, uso app, actividad, reclamos, mora, elegibilidad MT y estado MT. Los clusters se nombran **automáticamente** post-hoc comparando cada centroide con las medias globales:

| Persona | N clientes | Descripción comercial |
|---|---:|---|
| Cliente MT actual | 7,194 | Ya posee MT; priorizar profundización |
| Elegible MT estándar | 12,717 | Cumple condiciones MT; blanco directo |
| Nuevo en cartera | 24,254 | Historial corto; priorizar retención |
| Leal precio-sensible | 44,952 | Antiguo con facturación moderada; alternativas de precio |
| Perfil de riesgo | 10,883 | Fricción operacional; ofertas de bajo riesgo |

### 2.3 Uplift MT — `src/nbo/enrichment.py::compute_uplift_mt` + `population_uplift_mt`

Combina dos señales:
1. **Modelo**: Δ P(venta) entre la mejor oferta MT y la mediana de alternativas del mismo cliente.
2. **Población**: uplift observacional del histórico (tasa de aceptación MT vs resto entre contactados). El histórico da ≈35.6 pp (consistente con el 69.7% vs 34.1% del PDF de conclusiones).

Cuando el cliente es elegible MT, se reporta el **máximo** entre ambos. Es explícitamente **observacional, no causal**.

### 2.4 Score con componente de churn — `src/nbo/rules.py`

Se añadió `score_churn_component` que degrada suavemente si `w_churn` no existe en el `ranking_weights.json` guardado (mantiene retrocompatibilidad con el champion actual).

### 2.5 Vista simple de la Mesa del asesor — `streamlit_app.py`

Toggle "Vista simple" en la barra lateral. Cuando está activo, la Mesa se reduce a:
- Card grande: oferta, canal, precio, persona + churn.
- Una línea de por qué.
- Una línea de qué decir (apertura + argumento).
- Objeción probable + respuesta.
- Tres botones grandes: **Aceptó / Rechazó / No contactó** (registro directo en SQLite).

Diseñada para asesor de call center bajo presión de tiempo; oculta tabs, trazabilidad y detalle técnico.

### 2.6 Simulador what-if — `streamlit_app.py::render_whatif`

Nueva vista de política:
- Sliders para `w_conversion`, `w_fit`, `w_business`, `w_mt`, `w_friction`, `w_churn`.
- Comparación side-by-side de base vs simulado (oferta, canal, score, delta).
- Top-3 completo de ambos rankings.
- No modifica el modelo ni persiste nada.

Backend en `src/nbo/advisor_local.py::LocalAdvisorApi.what_if`.

### 2.7 KPIs del Desafío 2 — `src/nbo/challenge_metrics.py`

Ejecuta un batch determinista sobre una muestra y computa:
- **MT share hogar / móvil** (con metas >50% / >10%).
- **ΔARPU anual esperado** con supuestos explícitos.
- **Ofertas repetidas evitadas** por las reglas de elegibilidad.
- **Uplift MT promedio** y clientes con uplift ≥5%.
- **Distribución de personas** y **churn**.

Salidas:
- `reports/challenge_kpis.json` — datos para dashboards externos.
- `reports/challenge_kpis.html` — reporte autocontenido con estilos.

Ejemplo con muestra de 1,000 clientes:

| KPI | Valor | Meta rúbrica |
|---|---:|---:|
| MT share hogar | 26.2 % | >50 % |
| MT share móvil | 24.6 % | >10 % ✅ |
| ΔARPU anual esperado | S/128.62 / cliente | ↑ |
| Ofertas repetidas evitadas | 5,480 (5.48/cliente) | ↓ |
| Uplift MT promedio | 35.6 % | ↑ MT |
| Riesgo de fuga promedio | 19.1 % | ↓ churn |

Nota: MT share hogar (26.2 %) no llega a la meta >50 % del desafío. Es realista para una muestra genérica y refleja que el motor no fuerza MT cuando no es elegible o compatible.

### 2.8 Vista Impacto y evidencia — `streamlit_app.py::render_impact`

Ahora incluye una sección **"KPIs del Desafío 2"** al final que llama al mismo `compute_challenge_metrics` en vivo, con slider de tamaño de muestra y semilla, más gráficos de personas y distribución de riesgo de fuga.

### 2.9 Ordenamiento del repo

Movido a `notebooks/eda/`:
- `EDA_Data_Wrangling.ipynb`
- `dashboard_EDA.html`
- `build_dashboard.py`, `build_notebook.py`
- `catalogo_limpio.csv`, `clientes_limpio.csv`, `historial_limpio.csv`

Movido a `docs/`:
- `Concluciones del Dashboard.pdf`

Movido a `assets/screenshots/`:
- `challenge_kpis.png` (representativa del nuevo reporte HTML)

`.gitignore` extendido para ignorar `reports/screenshots_run/` (screenshots temporales de verificación).

Raíz quedó con solo lo esencial: `README.md`, `pyproject.toml`, `streamlit_app.py`, `requirements*`, `runtime.txt`, y las carpetas del código.

### 2.10 Extensión de contratos y bootstrap

- `src/nbo/schemas.py` añade `ChurnAssessment`, `PersonaAssignment`, y campos `persona`, `riesgo_fuga`, `uplift_mt` a `CustomerSummary`.
- `src/nbo/bootstrap.py` (comando `nbo-check`) reporta `enrichment.churn_available` y `enrichment.personas_available`, y muestra persona / riesgo / uplift para los tres casos de referencia.
- `src/nbo/advisor_local.py` añade `challenge_kpis(sample_size, seed)` y `what_if(cliente_id, scoring_overrides)`.
- `pyproject.toml` registra el CLI `nbo-challenge-kpis`.

---

## 3. Cómo verificar los cambios

```powershell
# 1. Verificación de instalación (reporta enrichment y casos de referencia)
nbo-check

# 2. Reentrenar modelos de enriquecimiento (churn + personas)
python scripts\train_enrichment.py

# 3. Generar KPIs del Desafío 2 (JSON + HTML)
python -m nbo.challenge_metrics --sample-size 1000
# equivalente:
nbo-challenge-kpis --sample-size 1000

# 4. Smoke test end-to-end de enriquecimiento, what-if y KPIs
python scripts\smoke_enrichment.py

# 5. Levantar la Mesa comercial (todas las vistas nuevas)
streamlit run streamlit_app.py
# navegar: Demo guiada / Mesa del asesor (toggle Vista simple) /
#         Impacto y evidencia (con KPIs desafío) / Simulador what-if

# 6. Test suite completa
pytest
```

Verificación final: **50/50 tests pasan** en ~100 s.

---

## 4. Nuevos archivos añadidos

```text
src/nbo/enrichment.py            # ChurnModel, PersonaModel, uplift utilities
src/nbo/challenge_metrics.py     # KPIs del desafío + renderizado HTML
scripts/train_enrichment.py      # Entrenador CLI de enrichment
scripts/smoke_enrichment.py      # Smoke test end-to-end
artifacts/nbo_v2/churn.joblib    # Modelo de churn proxy
artifacts/nbo_v2/personas.joblib # K-Means k=5
artifacts/nbo_v2/enrichment_metadata.json
reports/challenge_kpis.html      # Reporte KPIs autocontenido
reports/challenge_kpis.json      # KPIs en JSON
assets/screenshots/challenge_kpis.png
docs/mejoras_desafio2.md         # Este documento
```

## 5. Archivos modificados

```text
src/nbo/engine.py         # inyecta churn/persona/uplift en NBOResult
src/nbo/rules.py          # score_churn_component
src/nbo/schemas.py        # ChurnAssessment, PersonaAssignment, CustomerSummary extendido
src/nbo/bootstrap.py      # reporta enrichment en nbo-check
src/nbo/advisor_local.py  # métodos challenge_kpis y what_if
src/nbo/jury.py           # KPIs del desafío en demo_business_metrics
streamlit_app.py          # Vista simple, Simulador what-if, KPIs en Impacto, persona/churn/uplift en perfil
config/default.yaml       # w_churn en scoring
pyproject.toml            # entry point nbo-challenge-kpis
README.md                 # documentación de nuevos features
.gitignore                # reports/screenshots_run/
```

---

## 6. Limitaciones honestas

- **Churn**: es proxy operacional, no observado. Cualquier evaluación en campo requiere backtest sobre bajas reales.
- **Uplift MT**: componente poblacional viene del histórico observacional; no es efecto causal. Sólo comunicar como "más aceptación esperada, condicional a contactar".
- **MT share hogar** (26.2%) queda debajo de la meta del desafío (>50%). No forzamos MT donde no es elegible/compatible; una política más agresiva subiría este número a costa de más rechazos y cooldowns.
- **Personas**: los nombres son heurísticos post-hoc; el K-Means con k=5 puede generar dos clusters con el mismo nombre si dos centroides caen en la misma región (por eso pueden aparecer *Nuevo en cartera* y *Leal precio-sensible* combinados en algunos runs).
- **What-if**: sólo simula sobre `recommend_override`, no re-entrena; el efecto es puramente de ranking, no de calibración de probabilidades.

## 7. Lo que quedó fuera (pendiente si se retoma)

- **IA generativa para speech comercial** (deliberadamente fuera de este trabajo). Ver `src/nbo/llm_renderer.py` como andamiaje.
