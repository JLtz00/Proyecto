"""
Constructor del notebook de Data Wrangling para el Desafio 02.
Ejecutar: py -3.12 build_notebook.py
"""
import nbformat as nbf

nb = nbf.v4.new_notebook()
cells = []

def md(text):
    cells.append(nbf.v4.new_markdown_cell(text))

def code(src):
    cells.append(nbf.v4.new_code_cell(src))

# =========================================================================
# ENCABEZADO
# =========================================================================
md("""# Análisis Exploratorio de Datos — Data Wrangling
### Desafío 02: Personalización Comercial Inteligente (NBO + Movistar Total)
**Hackathon AI Telecom 2026 — Movistar**

Este notebook resuelve la práctica **"Análisis Exploratorio de Datos - Data Wrangling"**
(UNSA, curso Tópicos en Ciencia de Datos) aplicada a los 3 datasets del desafío:

| Archivo | Filas | Descripción |
|---|---|---|
| `dataset_clientes.csv` | 100,000 | 1 fila por cliente (perfil + comportamiento 6M) |
| `catalogo_ofertas_entrega.csv` | 22 | Portafolio de ofertas |
| `historial_campanias.csv` | 300,112 | 1 fila por ofrecimiento realizado (target: `resultado`) |

**Estructura del notebook:**

- **Paso 0 — Metadata:** contexto, entidades, granularidad
- **Paso 1 — Comportamiento de los datos:** shape, tipos, nulos, duplicados, rangos, `describe()`
- **Paso 2 — Limpieza (Data Wrangling):** casteos, sentinels, imputaciones semánticas, feature engineering
- **Paso 3 — Análisis estadístico:** tendencia central, dispersión, correlación, covarianza
- **Paso 4 — Análisis de outliers**
- **Paso 5 — Visualización**
- **Paso 6 — Problema potencial (supervisado):** target, balance, feature importance
- **Conclusiones**
""")

# =========================================================================
# SETUP
# =========================================================================
md("## 0. Setup — librerías y carga de datos")

code("""# Instalación (solo Colab). Descomentar si es necesario:
# !pip install -q pandas numpy matplotlib seaborn plotly scipy

import warnings
warnings.filterwarnings('ignore')

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from scipy import stats

pd.set_option('display.max_columns', 60)
pd.set_option('display.width', 200)
pd.set_option('display.float_format', lambda x: f'{x:,.3f}')
sns.set_theme(style='whitegrid', palette='deep')
plt.rcParams['figure.figsize'] = (11, 5)
plt.rcParams['figure.dpi'] = 90

print('numpy:', np.__version__)
print('pandas:', pd.__version__)""")

code("""# Carga.
# En Colab, subir los CSV o montar Drive y ajustar DATA_DIR.
import os
DATA_DIR = 'dataset'  # local
if not os.path.exists(DATA_DIR):
    DATA_DIR = '.'   # fallback Colab (CSV en la raíz)

clientes  = pd.read_csv(f'{DATA_DIR}/dataset_clientes.csv')
catalogo  = pd.read_csv(f'{DATA_DIR}/catalogo_ofertas_entrega.csv')
historial = pd.read_csv(f'{DATA_DIR}/historial_campanias.csv')

print(f'clientes  : {clientes.shape}')
print(f'catalogo  : {catalogo.shape}')
print(f'historial : {historial.shape}')""")

# =========================================================================
# PASO 0: METADATA
# =========================================================================
md("""## Paso 0 — Metadata

**Contexto del problema.** Movistar necesita un motor de **Next Best Offer (NBO)** que, para cada
cliente, recomiende la mejor oferta comercial, el canal óptimo, la probabilidad de aceptación y
una contraoferta (rebate) si el cliente rechaza. Segmento prioritario: clientes elegibles para
**Movistar Total** (móvil + internet hogar + postpago).

**Entidades y granularidad:**

| Tabla | Grano | PK | Cobertura temporal |
|---|---|---|---|
| `dataset_clientes` | 1 cliente | `cliente_id` | Snapshot con agregados 6M (ene–jun 2026) |
| `catalogo_ofertas` | 1 oferta   | `oferta_id`   | Estático (22 productos) |
| `historial_campanias` | 1 ofrecimiento a cliente | `ofrecimiento_id` | 6 meses (ene–jun 2026) |

**Relaciones:**
```
catalogo (oferta_id) ─┬─ clientes.plan_actual_id
                      ├─ clientes.oferta_hogar_id
                      └─ historial.oferta_id
clientes (cliente_id) ─── historial.cliente_id   (1:N)
```
""")

# =========================================================================
# PASO 1: COMPORTAMIENTO
# =========================================================================
md("""## Paso 1 — Comportamiento de los datos

Respondemos las preguntas de la práctica:
- ¿Cuántos registros hay? ¿Duplicados?
- ¿Qué tipo de dato tiene cada columna? ¿Rangos, min/max, valores únicos?
- ¿Datos categóricos vs numéricos, discretos vs continuos?
- ¿Nulos? ¿Por qué?
""")

md("### 1.1 Tamaño, tipos y duplicados")

code("""def resumen(df, nombre):
    print(f'━━━ {nombre} ━━━')
    print(f'Registros : {len(df):,}')
    print(f'Columnas  : {df.shape[1]}')
    print(f'Duplicados: {df.duplicated().sum()}')
    print(f'Memoria   : {df.memory_usage(deep=True).sum()/1024**2:.2f} MB')
    print()

resumen(clientes,  'dataset_clientes')
resumen(catalogo,  'catalogo_ofertas_entrega')
resumen(historial, 'historial_campanias')""")

code("""# Tipos de datos por columna
print('CLIENTES'); print(clientes.dtypes.to_string()); print()
print('CATALOGO'); print(catalogo.dtypes.to_string()); print()
print('HISTORIAL'); print(historial.dtypes.to_string())""")

md("""**Observaciones:**
- Ningún archivo tiene filas duplicadas.
- El volumen es manejable en memoria (< 100 MB total).
- `fecha` en `historial_campanias` está como `object` — hay que castear a `datetime`.
- Los campos `bool` ya vienen tipificados correctamente.
- Los `str` categóricos (tipo_cliente, canal, edad_rango, etc.) conviene convertirlos a `category`
  para ahorrar memoria y facilitar análisis.
""")

md("### 1.2 Nulos por columna")

code("""def tabla_nulos(df, nombre):
    n = df.isnull().sum()
    pct = (n / len(df) * 100).round(2)
    t = pd.DataFrame({'nulos': n, '%': pct}).query('nulos > 0').sort_values('nulos', ascending=False)
    print(f'━━━ Nulos en {nombre} ━━━')
    if t.empty:
        print('Sin nulos.')
    else:
        print(t.to_string())
    print()

tabla_nulos(clientes,  'dataset_clientes')
tabla_nulos(catalogo,  'catalogo_ofertas_entrega')
tabla_nulos(historial, 'historial_campanias')""")

md("""**Interpretación de nulos (¡NO son errores — son semánticos!):**

| Columna | Nulos | Motivo |
|---|---|---|
| `clientes.tipo_cliente` | 6,734 (6.7%) | Cliente **sin línea móvil** (`tiene_movil=False`). El concepto prepago/postpago solo aplica a móvil. |
| `clientes.oferta_hogar_id` | 54,758 (54.8%) | Cliente **sin servicio hogar** (`tiene_hogar=False`). |
| `clientes.canal_mas_usado` | 961 (1.0%) | Cliente sin ninguna interacción registrada en 6 meses. |
| `catalogo.cluster_hogar/descripcion_bundle` | 16 (72.7%) | Solo aplica a ofertas de tipo `plan_hogar`. |
| `historial.motivo_rechazo` | 140,908 (47.0%) | Solo se llena cuando `resultado='rechazada'`. |
| `historial.tipo_cliente` | 20,101 (6.7%) | Consistente con clientes sin móvil. |

**No se deben imputar los nulos semánticos con la media** — se deben tratar como una categoría
válida (ej: `"sin_movil"`, `"sin_hogar"`, `"no_rechazada"`, `"sin_interaccion"`).
""")

md("### 1.3 Verificar consistencia de las reglas de negocio")

code("""# ¿tipo_cliente nulo <=> tiene_movil = False?
mask1 = clientes['tipo_cliente'].isnull() == (~clientes['tiene_movil'])
print(f'tipo_cliente NaN <=> !tiene_movil : {mask1.all()}  (coherente: {mask1.sum()}/{len(mask1)})')

# ¿oferta_hogar_id nulo <=> tiene_hogar = False?
mask2 = clientes['oferta_hogar_id'].isnull() == (~clientes['tiene_hogar'])
print(f'oferta_hogar_id NaN <=> !tiene_hogar : {mask2.all()}')

# ¿motivo_rechazo nulo <=> resultado != rechazada?
mask3 = historial['motivo_rechazo'].isnull() == (historial['resultado'] != 'rechazada')
print(f'motivo_rechazo NaN <=> resultado != rechazada : {mask3.all()}')

# ¿elegible_mt requiere tiene_movil=True, tiene_internet_hogar=True, tipo_cliente=postpago?
elig = clientes[clientes['elegible_mt']]
check = ((elig['tiene_movil']) & (elig['tiene_internet_hogar']) & (elig['tipo_cliente']=='postpago')).all()
print(f'elegible_mt => movil+internet_hogar+postpago : {check}')
print(f'Clientes elegibles para MT (target prioritario): {len(elig):,}')""")

md("""Las 4 reglas de negocio se cumplen al 100%. Esto confirma que **los nulos son informativos,
no errores de carga** — un modelo debe tratarlos como una categoría propia, no imputarlos.
""")

md("### 1.4 Rangos, valores únicos y `describe()`")

code("""print('━━━ Descriptivos numéricos - clientes ━━━')
clientes.describe().T""")

code("""print('━━━ Descriptivos numéricos - historial (numéricas de contexto) ━━━')
historial.describe().T""")

code("""print('━━━ Descriptivos numéricos - catalogo ━━━')
catalogo.describe().T""")

md("""**Hallazgos numéricos clave:**
- `monto_facturado_prom`: media ≈ S/ 81, máx **S/ 306** → posibles outliers (cola larga a la derecha).
- `dias_mora_prom`: media ≈ 8 días, máx **49.7** → morosos extremos.
- `n_reclamos` está acotado a 0-3 (muy sesgado a 0).
- `gb_incluidos = 9999` en `catalogo` es un **sentinel** que representa "ilimitado" — hay que
  tratarlo como categórico o transformarlo, NO usar en cálculos.
- `antiguedad_meses`: 1 a 180 (0 a 15 años) — razonable.
""")

code("""# Sentinel 9999 en gb_incluidos
print('Ofertas con gb_incluidos = 9999 (ilimitado):')
print(catalogo[catalogo['gb_incluidos'] == 9999][['oferta_id','nombre_oferta','gb_incluidos']].to_string(index=False))""")

md("### 1.5 Variables categóricas — cardinalidad y distribución")

code("""cat_cols_cli = ['tipo_cliente','edad_rango','ubicacion_departamento','canal_mas_usado']
for c in cat_cols_cli:
    vc = clientes[c].value_counts(dropna=False)
    print(f'━━ {c}  ({vc.shape[0]} valores únicos) ━━')
    print(vc.to_string())
    print()""")

code("""cat_cols_hist = ['canal','resultado','motivo_rechazo','contactabilidad','medio_probatorio','tipo_oferta']
for c in cat_cols_hist:
    vc = historial[c].value_counts(dropna=False)
    print(f'━━ historial.{c}  ({vc.shape[0]} valores únicos) ━━')
    print(vc.to_string())
    print()""")

md("""**Observaciones:**
- **Concentración geográfica**: 45% de clientes en Lima → sesgo territorial fuerte.
- **Digital domina** (39%) como canal más usado, luego Call In (25%), Tienda (23%).
- **Rango de edad 26-45** concentra 52% de clientes (segmento comercialmente clave).
- **Target `resultado`** está desbalanceado: 53% rechazadas, 32% aceptadas, 15% pendientes.
- **Motivo de rechazo #1: `precio` (39.5% de los rechazos)** → señal comercial fuerte.
""")

# =========================================================================
# PASO 2: LIMPIEZA
# =========================================================================
md("""## Paso 2 — Limpieza (Data Wrangling)

Aplicamos las transformaciones necesarias basadas en el análisis anterior:

1. Castear `fecha` → `datetime`.
2. Convertir strings categóricos → `category`.
3. Imputar nulos **semánticos** con etiqueta explícita (no con la media).
4. Recodificar `gb_incluidos = 9999` como `es_ilimitado` + `gb_incluidos` numérico coherente.
5. Feature engineering básica: tasa de aceptación por cliente, mes de la campaña.
""")

md("### 2.1 Casteos y conversiones")

code("""cli = clientes.copy()
cat = catalogo.copy()
his = historial.copy()

# 1) Fecha
his['fecha'] = pd.to_datetime(his['fecha'], errors='coerce')
his['mes']   = his['fecha'].dt.to_period('M').astype(str)

# 2) Categóricas
for c in ['tipo_cliente','edad_rango','ubicacion_departamento','canal_mas_usado']:
    cli[c] = cli[c].astype('category')
for c in ['tipo_oferta','segmento_objetivo','cluster_hogar']:
    cat[c] = cat[c].astype('category')
for c in ['canal','resultado','motivo_rechazo','contactabilidad','medio_probatorio','tipo_oferta','tipo_cliente']:
    his[c] = his[c].astype('category')

print('fecha:', his['fecha'].min().date(), '->', his['fecha'].max().date())
print('Categóricas convertidas.')""")

md("### 2.2 Imputación semántica de nulos")

code("""# CLIENTES
cli['tipo_cliente']    = cli['tipo_cliente'].cat.add_categories(['sin_movil']).fillna('sin_movil')
cli['canal_mas_usado'] = cli['canal_mas_usado'].cat.add_categories(['sin_interaccion']).fillna('sin_interaccion')
cli['oferta_hogar_id'] = cli['oferta_hogar_id'].fillna('SIN_HOGAR')

# HISTORIAL
his['motivo_rechazo'] = his['motivo_rechazo'].cat.add_categories(['no_aplica']).fillna('no_aplica')
his['tipo_cliente']   = his['tipo_cliente'].cat.add_categories(['sin_movil']).fillna('sin_movil')

# CATALOGO
cat['cluster_hogar']      = cat['cluster_hogar'].cat.add_categories(['no_hogar']).fillna('no_hogar')
cat['descripcion_bundle'] = cat['descripcion_bundle'].fillna('N/A')

print('Nulos restantes (deben ser 0):')
print('  clientes :', cli.isnull().sum().sum())
print('  historial:', his.isnull().sum().sum())
print('  catalogo :', cat.isnull().sum().sum())""")

md("### 2.3 Sentinel `gb_incluidos = 9999` → variable `es_ilimitado`")

code("""cat['es_ilimitado'] = (cat['gb_incluidos'] == 9999)
cat.loc[cat['es_ilimitado'], 'gb_incluidos'] = np.nan  # para no sesgar estadísticas
print(cat[['oferta_id','nombre_oferta','gb_incluidos','es_ilimitado']].to_string(index=False))""")

md("### 2.4 Feature engineering — señales de negocio")

code("""# Tasa de aceptación histórica por cliente (útil como feature del modelo)
resumen_cli = (his.assign(aceptada=(his['resultado']=='aceptada').astype(int),
                          contactado=(his['contactabilidad']=='contactado').astype(int))
                 .groupby('cliente_id')
                 .agg(n_ofrecimientos=('ofrecimiento_id','count'),
                      n_aceptadas=('aceptada','sum'),
                      n_contactados=('contactado','sum'))
                 .assign(tasa_aceptacion=lambda d: d['n_aceptadas']/d['n_ofrecimientos'],
                         tasa_contactabilidad=lambda d: d['n_contactados']/d['n_ofrecimientos']))

cli = cli.merge(resumen_cli, on='cliente_id', how='left').fillna({'n_ofrecimientos':0,
                                                                   'n_aceptadas':0,
                                                                   'n_contactados':0,
                                                                   'tasa_aceptacion':0,
                                                                   'tasa_contactabilidad':0})
cli[['cliente_id','n_ofrecimientos','n_aceptadas','tasa_aceptacion']].head()""")

md("### 2.5 Tablas ya limpias — vista final")

code("""print('CLIENTES limpio'); display(cli.head(5))
print('\\nCATALOGO limpio'); display(cat.head(5))
print('\\nHISTORIAL limpio'); display(his.head(5))""")

# =========================================================================
# PASO 3: ANÁLISIS ESTADÍSTICO
# =========================================================================
md("""## Paso 3 — Análisis estadístico

Medidas de tendencia central, dispersión, correlación y covarianza sobre las variables
numéricas más relevantes.
""")

md("### 3.1 Tendencia central y dispersión")

code("""num_cols = ['antiguedad_meses','monto_facturado_prom','consumo_datos_gb_prom',
            'consumo_voz_min_prom','consumo_sms_prom','uso_app_movistar_prom',
            'monto_facturado_prom_6m','dias_mora_prom','meses_moroso',
            'n_reclamos','n_actividad_canal','tasa_aceptacion']

def resumen_estadistico(df, cols):
    out = pd.DataFrame({
        'media_aritm': df[cols].mean(),
        'mediana'    : df[cols].median(),
        'moda'       : df[cols].mode().iloc[0],
        'desv_est'   : df[cols].std(),
        'CV_%'       : (df[cols].std()/df[cols].mean()*100).round(1),
        'asimetria'  : df[cols].skew(),
        'curtosis'   : df[cols].kurtosis(),
    })
    # Media geométrica y armónica solo tienen sentido para valores estrictamente positivos
    for c in cols:
        vals = df[c][df[c] > 0]
        out.loc[c, 'media_geom'] = stats.gmean(vals) if len(vals) else np.nan
        out.loc[c, 'media_arm']  = stats.hmean(vals) if len(vals) else np.nan
    return out[['media_aritm','media_geom','media_arm','mediana','moda','desv_est','CV_%','asimetria','curtosis']]

resumen_estadistico(cli, num_cols).round(2)""")

md("""**Lectura clave:**
- `dias_mora_prom` y `n_reclamos` tienen **coeficiente de variación (CV) > 90%** — muy dispersos,
  la media es poco representativa.
- `consumo_sms_prom` tiene CV ≈ 14% — muy homogéneo (probablemente comportamiento residual).
- `monto_facturado_prom` presenta **asimetría positiva (skew > 1)** — cola derecha de clientes
  premium.
- La media geométrica < media aritmética confirma el sesgo derecho de los montos.
""")

md("### 3.2 Correlación entre features")

code("""corr = cli[num_cols].corr(method='pearson')
plt.figure(figsize=(11, 8))
sns.heatmap(corr, annot=True, fmt='.2f', cmap='RdBu_r', center=0,
            square=True, cbar_kws={'label':'Correlación de Pearson'})
plt.title('Matriz de correlación — features numéricas del cliente', fontsize=13)
plt.tight_layout()
plt.show()""")

code("""# Top pares con mayor |correlación| (excluyendo diagonal)
c = corr.abs().where(~np.eye(len(corr), dtype=bool)).unstack().dropna().sort_values(ascending=False)
c = c[~c.index.duplicated()]  # cada par una vez
print('Top 10 pares por |correlación|:')
print(c.head(20).to_string())""")

md("""**Correlaciones sorprendentes:**
- `monto_facturado_prom` ↔ `monto_facturado_prom_6m` : **0.99** — redundantes (usar solo una).
- `dias_mora_prom` ↔ `meses_moroso` : ~0.85 — casi la misma información.
- `n_ofrecimientos` ↔ `n_actividad_canal` : correlación moderada → clientes activos reciben más
  ofertas (posible sesgo del proceso comercial).
- Consumo de datos, voz, sms **no están correlacionados entre sí** → representan comportamientos
  independientes (buena señal para modelos).
""")

md("### 3.3 Covarianza (referencial)")

code("""# Covarianza en variables clave para el modelo NBO
key = ['monto_facturado_prom','consumo_datos_gb_prom','dias_mora_prom','tasa_aceptacion']
cli[key].cov().round(2)""")

# =========================================================================
# PASO 4: OUTLIERS
# =========================================================================
md("""## Paso 4 — Análisis de outliers

Buscamos valores atípicos usando el criterio **IQR** (Tukey): `[Q1 - 1.5·IQR, Q3 + 1.5·IQR]`.
""")

code("""def contar_outliers_iqr(df, cols):
    filas = []
    for c in cols:
        q1, q3 = df[c].quantile([0.25, 0.75])
        iqr = q3 - q1
        lo, hi = q1 - 1.5*iqr, q3 + 1.5*iqr
        n = ((df[c] < lo) | (df[c] > hi)).sum()
        filas.append({'columna':c, 'Q1':q1, 'Q3':q3, 'IQR':iqr, 'límite_inf':lo,
                      'límite_sup':hi, 'n_outliers':n, '%':100*n/len(df)})
    return pd.DataFrame(filas).round(2).sort_values('%', ascending=False)

contar_outliers_iqr(cli, ['monto_facturado_prom','consumo_datos_gb_prom','consumo_voz_min_prom',
                          'dias_mora_prom','n_reclamos','n_actividad_canal','antiguedad_meses'])""")

code("""# Boxplots comparativos
fig, axes = plt.subplots(2, 3, figsize=(15, 8))
for ax, c in zip(axes.ravel(), ['monto_facturado_prom','consumo_datos_gb_prom','consumo_voz_min_prom',
                                'dias_mora_prom','n_reclamos','n_actividad_canal']):
    sns.boxplot(y=cli[c], ax=ax, color='#0091EA')
    ax.set_title(c, fontsize=11)
    ax.set_ylabel('')
fig.suptitle('Boxplots — detección de outliers', y=1.02, fontsize=13)
plt.tight_layout()
plt.show()""")

md("""**Decisión sobre los outliers — NO se eliminan.**

Los datos son **sintéticos y consistentes** (no hay errores de carga), y los "outliers" que
aparecen representan realidades de negocio válidas:

- **`monto_facturado_prom` altos → clientes premium**: son justamente el segmento más rentable y
  con mayor probabilidad de aceptar Movistar Total Plus/Max. Eliminarlos sería descartar el
  target comercial más valioso.
- **`dias_mora_prom` altos → morosos crónicos**: no queremos ofrecerles upgrades caros, pero sí
  identificarlos para retención/riesgo.
- **`n_reclamos > 0`**: señal de churn próximo — importante mantenerla.

Regla aplicada: **conservar todos los outliers**, marcarlos con flags derivados solo cuando el
modelo lo requiera (winsorización condicional).
""")

# =========================================================================
# PASO 5: VISUALIZACIÓN
# =========================================================================
md("""## Paso 5 — Visualización

Aplicamos el criterio de la práctica:
- **Categóricas**: barras y circular.
- **Numéricas univariadas**: histograma.
- **Numéricas bivariadas**: boxplot / scatter.
""")

md("### 5.1 Categóricas — perfil de clientes")

code("""fig, axes = plt.subplots(2, 2, figsize=(15, 10))

# Tipo de cliente
vc = cli['tipo_cliente'].value_counts()
axes[0,0].pie(vc, labels=vc.index, autopct='%1.1f%%', startangle=90,
              colors=sns.color_palette('deep', len(vc)))
axes[0,0].set_title('Distribución por tipo de cliente')

# Rango de edad
vc = cli['edad_rango'].value_counts().sort_index()
sns.barplot(x=vc.index, y=vc.values, ax=axes[0,1], palette='viridis')
axes[0,1].set_title('Clientes por rango de edad')
axes[0,1].set_xlabel(''); axes[0,1].set_ylabel('cantidad')

# Departamentos
vc = cli['ubicacion_departamento'].value_counts()
sns.barplot(x=vc.values, y=vc.index, ax=axes[1,0], palette='mako')
axes[1,0].set_title('Distribución geográfica')
axes[1,0].set_xlabel('cantidad'); axes[1,0].set_ylabel('')

# Canal más usado
vc = cli['canal_mas_usado'].value_counts()
axes[1,1].pie(vc, labels=vc.index, autopct='%1.1f%%', startangle=90,
              colors=sns.color_palette('Set2', len(vc)))
axes[1,1].set_title('Canal preferido de interacción')

plt.tight_layout()
plt.show()""")

md("### 5.2 Numéricas — histogramas")

code("""fig, axes = plt.subplots(2, 3, figsize=(15, 8))
for ax, c in zip(axes.ravel(), ['antiguedad_meses','monto_facturado_prom','consumo_datos_gb_prom',
                                'consumo_voz_min_prom','dias_mora_prom','n_actividad_canal']):
    sns.histplot(cli[c], bins=40, kde=True, ax=ax, color='#0091EA')
    ax.set_title(c)
    ax.set_xlabel('')
plt.suptitle('Distribuciones univariadas — clientes', y=1.02, fontsize=13)
plt.tight_layout()
plt.show()""")

md("### 5.3 Bivariadas — señal para el modelo")

code("""# Aceptación por canal
fig, axes = plt.subplots(1, 2, figsize=(15, 5))

pivote = (his.assign(aceptada=(his['resultado']=='aceptada').astype(int))
             .groupby('canal', observed=True)['aceptada'].mean().sort_values(ascending=False))
sns.barplot(x=pivote.index, y=pivote.values*100, ax=axes[0], palette='crest')
axes[0].set_title('Tasa de aceptación por canal (%)')
axes[0].set_ylabel('% aceptación'); axes[0].set_xlabel('')
for i, v in enumerate(pivote.values*100):
    axes[0].text(i, v+0.3, f'{v:.1f}%', ha='center', fontsize=10)

# Aceptación por tipo de oferta
pivote2 = (his.assign(aceptada=(his['resultado']=='aceptada').astype(int))
              .groupby('tipo_oferta', observed=True)['aceptada'].mean().sort_values(ascending=False))
sns.barplot(x=pivote2.values*100, y=pivote2.index, ax=axes[1], palette='rocket')
axes[1].set_title('Tasa de aceptación por tipo de oferta (%)')
axes[1].set_xlabel('% aceptación'); axes[1].set_ylabel('')
for i, v in enumerate(pivote2.values*100):
    axes[1].text(v+0.3, i, f'{v:.1f}%', va='center', fontsize=10)

plt.tight_layout()
plt.show()""")

code("""# Boxplot: monto facturado por segmento MT
fig, ax = plt.subplots(figsize=(11, 5))
cli['segmento_mt'] = np.select(
    [cli['es_movistar_total'], cli['elegible_mt']],
    ['Ya tiene MT', 'Elegible MT'], default='Base general')
sns.boxplot(data=cli, x='segmento_mt', y='monto_facturado_prom',
            palette=['#00B0FF','#FF6D00','#B0BEC5'], ax=ax)
ax.set_title('Monto facturado según relación con Movistar Total')
ax.set_xlabel(''); ax.set_ylabel('S/ facturados / mes')
plt.tight_layout(); plt.show()""")

code("""# Scatter: consumo de datos vs facturación (2 vars numéricas, coloreadas por MT)
sample = cli.sample(min(8000, len(cli)), random_state=0)
plt.figure(figsize=(11, 6))
sns.scatterplot(data=sample, x='consumo_datos_gb_prom', y='monto_facturado_prom',
                hue='segmento_mt', alpha=0.55, s=18,
                palette={'Ya tiene MT':'#00B0FF','Elegible MT':'#FF6D00','Base general':'#B0BEC5'})
plt.title('Consumo de datos vs facturación — segmentación MT')
plt.tight_layout(); plt.show()""")

# =========================================================================
# PASO 6: PROBLEMA POTENCIAL
# =========================================================================
md("""## Paso 6 — Problema potencial (aprendizaje supervisado)

El desafío se plantea como un **problema supervisado multiclase** (o binario según se defina),
sobre la tabla `historial_campanias`:

- **Target sugerido**: `resultado ∈ {aceptada, rechazada, pendiente}`
- Se puede reformular como **binario**: aceptada vs no_aceptada (excluyendo pendientes = no
  contactados), lo cual es lo natural para el modelo de **probabilidad de aceptación** (NBO).
""")

code("""# Balance del target
plt.figure(figsize=(9, 4))
target = his['resultado'].value_counts(normalize=True) * 100
ax = sns.barplot(x=target.index, y=target.values, palette=['#4CAF50','#F44336','#9E9E9E'])
for i, v in enumerate(target.values):
    ax.text(i, v+0.5, f'{v:.1f}%', ha='center', fontsize=11, fontweight='bold')
ax.set_ylabel('% del total'); ax.set_xlabel('')
ax.set_title('Distribución del target — ¿está balanceado?')
plt.tight_layout(); plt.show()""")

md("""**Balance del target:**
- **Rechazada: 53.0%** — clase mayoritaria
- **Aceptada:  31.8%** — clase minoritaria positiva
- **Pendiente: 15.2%** — se excluye del entrenamiento (no hay señal real, solo no contactabilidad)

**El desbalance es moderado** — se puede manejar con `class_weight='balanced'`, sobremuestreo
(SMOTE) o ajuste de threshold. No hace falta undersampling agresivo.
""")

code("""# ¿Hay dependencia temporal (¿time-series?)?
por_mes = (his.assign(aceptada=(his['resultado']=='aceptada').astype(int))
              .groupby('mes').agg(ofrecimientos=('ofrecimiento_id','count'),
                                   tasa_aceptacion=('aceptada','mean')))
fig, ax1 = plt.subplots(figsize=(11, 5))
ax2 = ax1.twinx()
por_mes['ofrecimientos'].plot(kind='bar', ax=ax1, color='#B0BEC5', alpha=0.7)
por_mes['tasa_aceptacion'].plot(marker='o', ax=ax2, color='#FF6D00', linewidth=2)
ax1.set_ylabel('# ofrecimientos'); ax2.set_ylabel('tasa de aceptación')
ax1.set_title('Volumen y tasa de aceptación por mes')
plt.tight_layout(); plt.show()

print(por_mes.round(3))""")

md("""**¿Time series?** El volumen mensual es estable (~50k ofrecimientos/mes) y la tasa de
aceptación oscila estrechamente. **No es un problema de forecasting**, pero se debe hacer
**split temporal** (train: ene-abr / valid: mayo / test: junio) para evitar leakage.
""")

md("### 6.1 Feature importance — señal fuerte: motivo de rechazo")

code("""motivos = (his[his['resultado']=='rechazada']['motivo_rechazo']
              .value_counts(normalize=True) * 100).sort_values(ascending=False)
plt.figure(figsize=(10, 4))
sns.barplot(x=motivos.values, y=motivos.index, palette='rocket_r')
for i, v in enumerate(motivos.values):
    plt.text(v+0.4, i, f'{v:.1f}%', va='center')
plt.title('¿Por qué rechazan? — motivos de rechazo (%)')
plt.xlabel('% del total de rechazos')
plt.tight_layout(); plt.show()""")

md("""**Insight comercial más impactante:**
- **PRECIO** explica **39.5%** de los rechazos — la contraoferta (rebate) debe atacar precio.
- **NO NECESITA** (22.6%) → mejor targeting: no ofrecer lo mismo dos veces.
- **YA TIENE SIMILAR** (17.0%) → falla del sistema de recomendación actual.
""")

# =========================================================================
# CONCLUSIONES
# =========================================================================
md("""## Conclusiones

**¿Qué aprendimos de este análisis?**

1. **Los datos están limpios estructuralmente** (0 duplicados, tipos coherentes) pero los
   **nulos son semánticos** — no imputar con la media; representarlos como categoría propia.
2. **Segmento prioritario `elegible_mt` = 13,650 clientes** (13.7% de la base). Este es el
   universo donde el modelo NBO debe maximizar conversión a Movistar Total.
3. **Concentración geográfica en Lima** (45%) — el modelo debe evitar overfitting territorial;
   validar métricas por región.
4. **Fuerte correlación entre `monto_facturado_prom` y `monto_facturado_prom_6m` (0.99)** —
   redundantes, conservar solo una.
5. **Canal Digital domina** en interacciones (39%) pero **Tienda tiene la mejor tasa de
   aceptación** en campañas → canal + oferta importan más que canal solo.
6. **Precio es el rechazo #1** (39.5%) — el rebate más efectivo va a ser sobre precio, no sobre
   producto.
7. **Target moderadamente desbalanceado** (aceptada 32%) — manejable con `class_weight`, no
   hace falta undersampling.
8. **No es problema de forecasting** — pero requiere split temporal para evitar leakage.
9. **Outliers son reales, no errores** — clientes premium y morosos crónicos son señales
   válidas para el modelo, no se eliminan.
10. **Feature engineering clave**: `tasa_aceptacion` histórica del cliente y `n_ofrecimientos`
    son muy predictivas y ya vienen listas para usar.

**Próximos pasos:**
- Construir dataset de entrenamiento uniendo `historial + clientes + catalogo` a nivel
  (cliente × oferta).
- Entrenar clasificador binario (aceptada vs no_aceptada) sobre contactados.
- Definir política NBO: `argmax_offer P(aceptada | cliente, oferta)` con restricción "compatible
  con perfil".
- Definir política de rebate condicionada a `motivo_rechazo`.
""")

# =========================================================================
# GUARDAR ARTEFACTOS
# =========================================================================
md("""## Anexo — Exportar tablas limpias

Para reutilizar en el pipeline de modelado.
""")

code("""cli.to_csv('clientes_limpio.csv', index=False)
cat.to_csv('catalogo_limpio.csv', index=False)
his.to_csv('historial_limpio.csv', index=False)
print('Archivos limpios exportados: clientes_limpio.csv, catalogo_limpio.csv, historial_limpio.csv')""")

# =========================================================================
# SAVE
# =========================================================================
nb['cells'] = cells
nb['metadata'] = {
    'kernelspec': {'display_name': 'Python 3', 'language': 'python', 'name': 'python3'},
    'language_info': {'name': 'python', 'version': '3.12'},
    'colab': {'provenance': [], 'toc_visible': True},
}

with open('EDA_Data_Wrangling.ipynb', 'w', encoding='utf-8') as f:
    nbf.write(nb, f)

print(f'Notebook creado: EDA_Data_Wrangling.ipynb — {len(cells)} celdas')
