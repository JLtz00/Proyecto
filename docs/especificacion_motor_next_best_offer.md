# Especificación técnica --- Motor de Next Best Offer (NBO)

## Hackathon AI Telecom Challenge 2026 · Desafío 2 --- Personalización comercial inteligente

> **Documento de implementación para el agente de desarrollo.**
>
> El objetivo es que un agente pueda tomar este documento como
> especificación funcional y técnica para implementar un MVP completo
> del motor NBO, incluyendo preparación de datos, entrenamiento de
> modelos, motor de reglas, ranking, explicabilidad, recomendación de
> canal, detección de rechazo/rebate, API y una salida lista para un
> dashboard de asesor.

------------------------------------------------------------------------

# 1. Objetivo del proyecto

Construir un **motor de Next Best Offer (NBO)** que, dado un cliente,
determine:

1.  Qué oferta es la más adecuada.
2.  Por qué esa oferta es adecuada.
3.  Qué canal tiene mayor probabilidad de contacto/aceptación.
4.  Qué probabilidad estimada de aceptación tiene.
5.  Qué alternativas deben quedar como segunda y tercera opción.
6.  Si el cliente es un candidato prioritario para Movistar Total (MT).
7.  Qué objeción/rechazo es más probable.
8.  Qué rebate o respuesta comercial debe sugerirse si existe rechazo.
9.  Qué información debe mostrarse al asesor.
10. Cómo registrar el resultado para construir trazabilidad E2E.

El desafío oficial pide explícitamente una recomendación explicable,
probabilidad de aceptación, canal y momento, una interfaz accionable
para el asesor y MT como caso de uso prioritario. El motor, sin embargo,
debe ser **generalizable al resto del catálogo**, no un modelo exclusivo
de MT.

------------------------------------------------------------------------

# 2. Fuentes oficiales y datos disponibles

Los documentos de referencia son:

-   `Desafío 2 Hackathon AI Telecom 2026.pdf`
-   `02. Desafío personalización comercial inteligente_VF.pdf`
-   `diccionario_datos_participantes.pdf`

Los datasets entregados son:

-   `dataset_clientes.csv`
-   `catalogo_ofertas_entrega.csv`
-   `historial_campanias.csv`

Los datos son sintéticos y anonimizados. El diccionario indica 100,000
clientes y seis meses de comportamiento (enero-junio de 2026).

## 2.1 Tamaños reales observados en los archivos entregados

Al implementar, verificar los tamaños automáticamente y no
hardcodearlos:

  -----------------------------------------------------------------------------------
  Archivo                                      Filas observadas Uso
  -------------------------------- ---------------------------- ---------------------
  `dataset_clientes.csv`                                100,000 Perfil actual/resumen
                                                                del cliente

  `catalogo_ofertas_entrega.csv`                             22 Portafolio de ofertas

  `historial_campanias.csv`                             300,112 Eventos históricos de
                                                                ofrecimiento
  -----------------------------------------------------------------------------------

El historial contiene fechas del 2026-01-10 al 2026-06-10.

------------------------------------------------------------------------

# 3. Concepto funcional

La explicación para usuarios no técnicos debe ser:

> **El motor analiza al cliente, genera las ofertas que podría recibir,
> elimina las que no son válidas, estima la probabilidad de contacto y
> aceptación para cada combinación de oferta y canal, y finalmente
> ordena las alternativas para seleccionar la mejor.**

Conceptualmente:

``` text
Cliente
   │
   ▼
Perfil + consumo + servicios + historial
   │
   ▼
Ingeniería de variables
   │
   ▼
Generación de ofertas candidatas
   │
   ▼
Motor de reglas
   │
   ▼
Modelo de contactabilidad
   │
   ▼
Modelo de aceptación
   │
   ▼
Scoring / ranking
   │
   ├──► Oferta #1
   ├──► Oferta #2
   └──► Oferta #3
   │
   ▼
Explicabilidad
   │
   ▼
Speech / rebate
   │
   ▼
Respuesta para asesor
   │
   ▼
Trazabilidad y feedback
```

------------------------------------------------------------------------

# 4. Arquitectura propuesta

La arquitectura del MVP debe separar claramente:

1.  Ingesta.
2.  Validación.
3.  Feature engineering.
4.  Motor de elegibilidad/reglas.
5.  Modelos ML.
6.  Scoring.
7.  Explicabilidad.
8.  Generación de mensaje.
9.  API.
10. Persistencia de resultados.

Arquitectura:

``` text
                    ┌──────────────────────────┐
                    │ dataset_clientes.csv     │
                    └────────────┬─────────────┘
                                 │
                    ┌────────────▼─────────────┐
                    │ historial_campanias.csv  │
                    └────────────┬─────────────┘
                                 │
                    ┌────────────▼─────────────┐
                    │ catalogo_ofertas.csv      │
                    └────────────┬─────────────┘
                                 │
                                 ▼
                    ┌──────────────────────────┐
                    │ Data validation / ETL     │
                    └────────────┬─────────────┘
                                 │
                                 ▼
                    ┌──────────────────────────┐
                    │ Feature engineering      │
                    └────────────┬─────────────┘
                                 │
                 ┌───────────────┴───────────────┐
                 ▼                               ▼
       ┌────────────────────┐          ┌────────────────────┐
       │ Motor de reglas    │          │ Modelos ML         │
       │ / elegibilidad     │          │ contacto + compra  │
       └─────────┬──────────┘          └─────────┬──────────┘
                 └───────────────┬───────────────┘
                                 ▼
                    ┌──────────────────────────┐
                    │ Scoring + Ranking NBO    │
                    └────────────┬─────────────┘
                                 │
                 ┌───────────────┼────────────────┐
                 ▼               ▼                ▼
          Explicabilidad     Rebate/objeción   IA generativa
                 │               │                │
                 └───────────────┴────────────────┘
                                 ▼
                    ┌──────────────────────────┐
                    │ API / Dashboard asesor   │
                    └────────────┬─────────────┘
                                 │
                                 ▼
                    ┌──────────────────────────┐
                    │ Resultado + trazabilidad │
                    └──────────────────────────┘
```

------------------------------------------------------------------------

# 5. Tecnologías recomendadas

## Backend / ML

-   Python 3.11+
-   pandas
-   numpy
-   scikit-learn
-   CatBoost
-   SHAP
-   joblib
-   FastAPI
-   Pydantic

## Dashboard

Preferencia para hackathon:

-   Streamlit

Alternativa:

-   React + FastAPI

Para el MVP, **Streamlit + FastAPI opcional** es suficiente.

## IA generativa

Debe ser una capa posterior al motor NBO.

No usar un LLM para decidir directamente qué oferta recomendar.

El LLM debe recibir datos estructurados y generar:

-   speech,
-   mensaje,
-   explicación amigable,
-   rebate.

## RAG

RAG es opcional.

Solo debe incorporarse si existe un repositorio de documentación
comercial que el LLM necesite consultar. No debe sustituir al modelo ML.

------------------------------------------------------------------------

# 6. Estructura de proyecto

Crear una estructura similar a:

``` text
nbo-movistar/
│
├── data/
│   ├── raw/
│   │   ├── dataset_clientes.csv
│   │   ├── catalogo_ofertas_entrega.csv
│   │   └── historial_campanias.csv
│   │
│   └── processed/
│
├── models/
│   ├── acceptance_model.cbm
│   ├── contactability_model.cbm
│   ├── rejection_model.cbm
│   ├── calibrator.pkl
│   └── feature_schema.json
│
├── src/
│   ├── config.py
│   ├── data_loader.py
│   ├── validation.py
│   ├── features.py
│   ├── rules.py
│   ├── candidate_generation.py
│   ├── contactability_model.py
│   ├── acceptance_model.py
│   ├── rejection_model.py
│   ├── scoring.py
│   ├── ranking.py
│   ├── explainability.py
│   ├── rebate.py
│   ├── nbo_engine.py
│   ├── schemas.py
│   └── api.py
│
├── training/
│   ├── build_training_set.py
│   ├── train_contactability.py
│   ├── train_acceptance.py
│   ├── train_rejection.py
│   ├── evaluate.py
│   └── calibrate.py
│
├── app/
│   ├── streamlit_app.py
│   └── components/
│
├── tests/
│   ├── test_data.py
│   ├── test_rules.py
│   ├── test_features.py
│   ├── test_scoring.py
│   └── test_api.py
│
├── notebooks/
│   ├── 01_eda.ipynb
│   ├── 02_features.ipynb
│   └── 03_model_evaluation.ipynb
│
├── requirements.txt
├── README.md
└── .env.example
```

------------------------------------------------------------------------

# 7. Modelo de datos

## 7.1 `dataset_clientes.csv`

Una fila por cliente.

Campos:

  Campo                       Tipo         Uso
  --------------------------- ------------ --------------------------------------------
  `cliente_id`                string       Identificador
  `tipo_cliente`              categórico   prepago/postpago
  `antiguedad_meses`          int          Antigüedad
  `tiene_movil`               bool         Tiene móvil
  `tiene_hogar`               bool         Tiene servicio hogar
  `oferta_hogar_id`           string       Oferta hogar actual
  `tiene_internet_hogar`      bool         Tiene internet hogar
  `es_movistar_total`         bool         Ya tiene MT
  `elegible_mt`               bool         Cumple requisitos MT y todavía no lo tiene
  `plan_actual_id`            string       Plan principal actual
  `monto_facturado_prom`      float        Facturación mensual promedio
  `edad_rango`                categórico   Rango de edad
  `ubicacion_departamento`    categórico   Departamento aproximado
  `es_usuario_app`            bool         Usó App recientemente
  `consumo_datos_gb_prom`     float        GB mensuales promedio
  `consumo_voz_min_prom`      float        Minutos de voz
  `consumo_sms_prom`          float        SMS
  `uso_app_movistar_prom`     float        Sesiones App promedio
  `monto_facturado_prom_6m`   float        Facturación promedio 6 meses
  `dias_mora_prom`            float        Mora promedio
  `meses_moroso`              int          Meses en mora
  `n_reclamos`                int          Reclamos
  `n_actividad_canal`         int          Actividad comercial
  `canal_mas_usado`           categórico   Canal dominante

Importante:

-   `tipo_cliente` puede ser nulo cuando no existe línea móvil.
-   `oferta_hogar_id` puede ser nulo cuando `tiene_hogar=False`.
-   `canal_mas_usado` puede ser nulo sin actividad.
-   `tiene_hogar` NO significa necesariamente que tenga internet.
-   `es_movistar_total` indica que el cliente ya tenía MT.
-   `elegible_mt=True` indica el segmento prioritario: móvil + internet
    hogar + postpago, pero todavía sin MT.

------------------------------------------------------------------------

# 8. `catalogo_ofertas_entrega.csv`

Tiene 22 ofertas.

Campos:

  -----------------------------------------------------------------------
  Campo                   Tipo                    Uso
  ----------------------- ----------------------- -----------------------
  `oferta_id`             string                  PK

  `nombre_oferta`         string                  Nombre comercial

  `tipo_oferta`           categórico              plan_movil / plan_hogar
                                                  / upgrade / equipo /
                                                  paquete_adicional /
                                                  movistar_total

  `segmento_objetivo`     categórico              movil / hogar / ambos

  `es_movistar_total`     bool                    Es una oferta MT

  `precio_mensual`        float                   Precio

  `ahorro_pct`            int                     Ahorro ilustrativo para
                                                  MT

  `gb_incluidos`          int                     GB; 9999 = ilimitado

  `cluster_hogar`         categórico              mono / duo / trio

  `descripcion_bundle`    string                  Componentes hogar

  `descripcion_corta`     string                  Texto resumido
  -----------------------------------------------------------------------

## 8.1 Catálogo completo

  --------------------------------------------------------------------------------------------
  ID        Oferta          Tipo                Segmento         Precio           GB MT
  --------- --------------- ------------------- ---------- ------------ ------------ ---------
  OF001     Plan Movil      plan_movil          movil              39.9           10 No
            Basico 10GB                                                              

  OF002     Plan Movil Plus plan_movil          movil              59.9           25 No
            25GB                                                                     

  OF003     Plan Movil Max  plan_movil          movil              79.9           50 No
            50GB                                                                     

  OF004     Plan Movil      plan_movil          movil              99.9         9999 No
            Ilimitado                                                                

  OF005     Internet Hogar  plan_hogar          hogar              89.9            0 No
            100Mb                                                                    

  OF006     Internet Hogar  plan_hogar          hogar             109.9            0 No
            200Mb                                                                    

  OF007     TV Hogar Sola   plan_hogar          hogar              69.9            0 No

  OF008     Internet + TV   plan_hogar          hogar             129.9            0 No
            Hogar                                                                    

  OF009     Internet + Fijo plan_hogar          hogar             119.9            0 No
            Hogar                                                                    

  OF010     Internet + TV + plan_hogar          hogar             159.9            0 No
            Fijo Hogar                                                               

  OF011     Upgrade a Plan  upgrade             movil              20.0           15 No
            Plus                                                                     

  OF012     Upgrade a Plan  upgrade             movil              40.0           40 No
            Max                                                                      

  OF013     Upgrade         upgrade             hogar              25.0            0 No
            Velocidad Hogar                                                          

  OF014     Equipo          equipo              movil              45.0            0 No
            Smartphone Gama                                                          
            Media                                                                    

  OF015     Equipo          equipo              movil              90.0            0 No
            Smartphone Gama                                                          
            Alta                                                                     

  OF016     Router WiFi 6   equipo              hogar              15.0            0 No

  OF017     Paquete         paquete_adicional   ambos              19.9            0 No
            Streaming Video                                                          

  OF018     Paquete         paquete_adicional   ambos              12.9            0 No
            Seguridad                                                                
            Digital                                                                  

  OF019     Paquete Roaming paquete_adicional   movil              29.9            5 No
            Internacional                                                            

  OF020     Movistar Total  movistar_total      ambos             149.9           30 Sí
            Basico                                                                   

  OF021     Movistar Total  movistar_total      ambos             189.9           60 Sí
            Plus                                                                     

  OF022     Movistar Total  movistar_total      ambos             229.9         9999 Sí
            Max                                                                      
  --------------------------------------------------------------------------------------------

El `ahorro_pct` de MT es ilustrativo para este dataset y no debe
presentarse como tarifa oficial real.

------------------------------------------------------------------------

# 9. `historial_campanias.csv`

Cada fila es un ofrecimiento.

Campos:

  -----------------------------------------------------------------------
  Campo                               Uso
  ----------------------------------- -----------------------------------
  `ofrecimiento_id`                   ID del evento

  `cliente_id`                        Cliente

  `oferta_id`                         Oferta presentada

  `fecha`                             Fecha

  `canal`                             Tienda / Call In / Call Out /
                                      Digital

  `resultado`                         aceptada / rechazada / pendiente

  `motivo_rechazo`                    precio / no_necesita /
                                      ya_tiene_similar / mal_momento /
                                      no_confia / otro

  `es_rebate`                         Si hubo contraoferta

  `contactabilidad`                   contactado / no_contactado

  `medio_probatorio`                  registro_plataforma / audio_llamada
                                      / chat_log

  `tipo_cliente`                      Copia del cliente

  `antiguedad_meses`                  Copia

  `elegible_mt`                       Copia

  `es_movistar_total`                 Estado del cliente antes del evento

  `nombre_oferta`                     Copia del catálogo

  `tipo_oferta`                       Copia del catálogo

  `oferta_es_mt`                      Indica si la oferta presentada era
                                      MT
  -----------------------------------------------------------------------

## Regla crítica

No confundir:

``` text
es_movistar_total
```

con:

``` text
oferta_es_mt
```

El primero describe al **cliente**.

El segundo describe la **oferta presentada**.

------------------------------------------------------------------------

# 10. Relaciones entre tablas

``` text
catalogo_ofertas_entrega.oferta_id
      │
      ├── dataset_clientes.plan_actual_id
      ├── dataset_clientes.oferta_hogar_id
      └── historial_campanias.oferta_id

dataset_clientes.cliente_id
      │
      └── historial_campanias.cliente_id
```

Relación:

``` text
1 cliente → N ofrecimientos
1 oferta → N ofrecimientos
```

------------------------------------------------------------------------

# 11. Validación inicial de datos

Implementar un `data_validation.py`.

Debe verificar:

## Clientes

-   `cliente_id` único.
-   100,000 filas esperadas.
-   No existen IDs vacíos.
-   Booleanos válidos.
-   Precios no negativos.
-   Consumos no negativos.
-   `meses_moroso` entre 0 y 6.
-   `n_reclamos >= 0`.
-   `n_actividad_canal >= 0`.

## Catálogo

-   `oferta_id` único.
-   22 ofertas esperadas.
-   precios positivos.
-   MT exactamente en OF020, OF021, OF022.
-   `ahorro_pct` \> 0 únicamente para MT.
-   `gb_incluidos=9999` interpretado como ilimitado.

## Historial

-   `ofrecimiento_id` único.
-   `cliente_id` debe existir.
-   `oferta_id` debe existir.
-   `canal` dentro de los 4 canales.
-   `resultado` dentro de aceptada/rechazada/pendiente.
-   `pendiente` debe corresponder a `no_contactado`.
-   `aceptada` y `rechazada` deben corresponder a `contactado`.
-   `motivo_rechazo` debe ser nulo cuando resultado no sea rechazada.
-   `oferta_es_mt` debe ser consistente con catálogo.

No detener todo el pipeline por un warning no crítico; generar un
reporte de calidad.

------------------------------------------------------------------------

# 12. Tratamiento de nulos

No rellenar todo con cero automáticamente.

Reglas:

-   `tipo_cliente` nulo → categoría `"sin_linea_movil"`.
-   `oferta_hogar_id` nulo → `"sin_hogar"`.
-   `canal_mas_usado` nulo → `"sin_actividad"`.
-   `motivo_rechazo` nulo → `"sin_rechazo"`.
-   Categóricas restantes → `"unknown"`.
-   Numéricas → imputación robusta o valor mediano dentro del train.
-   El imputador debe entrenarse únicamente con train.

Para CatBoost, se pueden conservar categóricas como string y utilizar
manejo nativo de categorías.

------------------------------------------------------------------------

# 13. Ingeniería de variables

Esta es una parte importante del proyecto porque el desafío valora
variables ingeniosas.

## 13.1 Variables básicas

Crear:

``` text
precio_vs_facturacion
delta_precio
ratio_precio_facturacion
ratio_facturacion_6m_actual
actividad_por_mes
reclamos_por_antiguedad
mora_riesgo
```

Ejemplos:

``` text
ratio_precio_facturacion =
precio_oferta / max(monto_facturado_prom, epsilon)
```

``` text
delta_precio =
precio_oferta - monto_facturado_prom
```

------------------------------------------------------------------------

# 14. Variables de necesidad

## 14.1 Gap de datos

``` text
gap_gb =
gb_oferta - consumo_datos_gb_prom
```

Interpretación:

-   negativo → oferta insuficiente.
-   cercano a 0 → ajustada.
-   positivo moderado → capacidad adicional.
-   excesivamente positivo → posible sobreoferta.

No tratar 9999 como un valor numérico normal.

Para ilimitado:

``` text
oferta_es_ilimitada = gb_incluidos == 9999
```

------------------------------------------------------------------------

# 15. Variables de compatibilidad

Crear:

``` text
oferta_es_movil
oferta_es_hogar
oferta_es_upgrade
oferta_es_equipo
oferta_es_paquete
oferta_es_mt
```

Cruces:

``` text
cliente_tiene_movil × oferta_es_movil
cliente_tiene_hogar × oferta_es_hogar
cliente_tiene_internet × oferta_es_hogar
cliente_elegible_mt × oferta_es_mt
```

------------------------------------------------------------------------

# 16. Ruta Movistar Total

Crear una variable:

``` text
etapa_mt
```

Valores recomendados:

``` text
0 = ya_es_mt
1 = elegible_mt
2 = tiene_movil_postpago_sin_internet_hogar
3 = tiene_internet_hogar_sin_movil_postpago
4 = no_elegible_actual
```

La definición debe basarse en:

``` text
tiene_movil
tipo_cliente
tiene_internet_hogar
es_movistar_total
```

Importante:

-   Si `es_movistar_total=True`, no recomendar MT como adquisición.
-   Si `elegible_mt=True`, MT es una prioridad fuerte.
-   Si falta una condición, el motor puede recomendar primero el
    producto que acerque al cliente a MT.
-   No inventar condiciones comerciales no presentes en los datos.

------------------------------------------------------------------------

# 17. Variables de afinidad de canal

El dataset de clientes contiene `canal_mas_usado`.

Historial permite calcular además:

``` text
aceptacion_por_canal_cliente
contactabilidad_por_canal_cliente
rechazos_por_canal_cliente
actividad_por_canal
```

Cuando un cliente tiene suficientes eventos:

``` text
acceptance_rate_cliente_canal =
aceptadas / contactados
```

Usar smoothing para evitar tasas extremas con pocos eventos.

Ejemplo:

``` text
smoothed_rate =
(successes + alpha * global_rate) /
(trials + alpha)
```

Con `alpha` configurable, por ejemplo 5 o 10.

Si no existen suficientes eventos del cliente:

1.  usar segmento cliente/canal;
2.  luego canal global;
3.  luego tasa global.

------------------------------------------------------------------------

# 18. Variables de historial de oferta

Para cada cliente:

``` text
n_ofertas_recibidas
n_ofertas_aceptadas
n_ofertas_rechazadas
n_ofertas_pendientes
```

Por oferta:

``` text
n_veces_oferta
ultima_fecha_oferta
dias_desde_ultima_oferta
n_rechazos_oferta
n_aceptaciones_oferta
```

Por tipo:

``` text
n_plan_movil
n_plan_hogar
n_upgrade
n_equipo
n_paquete
n_mt
```

Crear:

``` text
fatiga_comercial
```

Ejemplo conceptual:

``` text
fatiga =
weighted_count_recent_offers
+
penalty_repeated_offer
+
penalty_recent_rejection
```

No debe utilizarse para castigar automáticamente al cliente; es una
señal de prudencia comercial.

------------------------------------------------------------------------

# 19. Variables de sensibilidad al precio

Crear:

``` text
rechazos_por_precio
ratio_rechazo_precio
delta_precio_promedio_rechazado
```

Y:

``` text
sensibilidad_precio =
rechazos_precio / max(rechazos_totales, 1)
```

También:

``` text
affordability_gap =
precio_oferta / monto_facturado_prom
```

------------------------------------------------------------------------

# 20. Variables de fricción

Crear un indicador interpretable:

``` text
friccion_cliente =
w1 * mora_normalizada
+ w2 * meses_moroso_normalizado
+ w3 * reclamos_normalizados
+ w4 * fatiga_comercial_normalizada
```

Los pesos deben ser configurables, no ocultos.

Ejemplo inicial:

``` text
w1 = 0.20
w2 = 0.20
w3 = 0.20
w4 = 0.40
```

No presentarlo como churn.

Es un **indicador interno de fricción comercial**.

------------------------------------------------------------------------

# 21. Modelo de Machine Learning

El núcleo del proyecto debe ser ML tabular.

## 21.1 Modelo de contactabilidad

Objetivo:

``` text
P(contactado | cliente, canal)
```

Dataset:

-   historial con `contactabilidad`.
-   target:

``` text
contactado = 1
no_contactado = 0
```

Features:

-   perfil cliente,
-   actividad,
-   canal,
-   canal más usado,
-   uso App,
-   histórico de contactabilidad,
-   oferta,
-   tipo de oferta,
-   contexto temporal disponible.

Modelo recomendado:

**CatBoostClassifier**

Alternativa:

**LightGBM / XGBoost**

Baseline:

**LogisticRegression**

------------------------------------------------------------------------

# 22. Modelo de aceptación

Objetivo:

``` text
P(aceptación | cliente, oferta, canal, contacto)
```

Entrenar únicamente con:

``` text
resultado ∈ {aceptada, rechazada}
```

No entrenar aceptación incluyendo `pendiente` como rechazo.

`pendiente` significa falta de contacto y no implica rechazo.

Target:

``` text
aceptada = 1
rechazada = 0
```

Features:

### Cliente

-   tipo_cliente
-   antiguedad_meses
-   tiene_movil
-   tiene_hogar
-   tiene_internet_hogar
-   plan_actual_id
-   monto_facturado_prom
-   edad_rango
-   departamento
-   es_usuario_app
-   consumo_datos_gb_prom
-   consumo_voz_min_prom
-   consumo_sms_prom
-   uso_app_movistar_prom
-   mora
-   reclamos
-   actividad

### Oferta

-   oferta_id
-   tipo_oferta
-   segmento_objetivo
-   es_movistar_total
-   precio
-   ahorro_pct
-   gb
-   cluster_hogar

### Relacionales

-   delta_precio
-   ratio_precio_facturacion
-   gap_gb
-   etapa_mt
-   compatibilidad
-   historial oferta-cliente
-   afinidad canal
-   fatiga

------------------------------------------------------------------------

# 23. División de train/validation/test

No utilizar un split aleatorio simple de filas como primera opción
porque un mismo cliente aparece muchas veces.

Mínimo:

``` text
train: 70%
validation: 15%
test: 15%
```

pero realizar la separación **por cliente_id**.

Ejemplo:

``` text
GroupShuffleSplit
group = cliente_id
```

Además, realizar una evaluación temporal como experimento adicional:

``` text
train: enero-abril
validation: mayo
test: junio
```

La evaluación temporal tiene una limitación importante:
`dataset_clientes.csv` contiene resúmenes de seis meses, por lo que no
debe asumirse que sus variables representan exclusivamente información
disponible antes de cada evento histórico. Para una evaluación temporal
rigurosa en producción se necesitarían snapshots mensuales del perfil.

Para el hackathon:

-   reportar split por cliente como evaluación principal;
-   reportar temporal split como evaluación de robustez;
-   documentar explícitamente la limitación.

------------------------------------------------------------------------

# 24. Prevención de leakage

No utilizar como feature:

-   `resultado`
-   `contactabilidad` del mismo evento
-   `motivo_rechazo`
-   `medio_probatorio`
-   `es_rebate` del mismo evento
-   información generada después del ofrecimiento.

Tampoco utilizar información futura del cliente de forma silenciosa
cuando se realice evaluación temporal.

Cuidado especial:

``` text
es_movistar_total
```

y

``` text
elegible_mt
```

son campos del dataset actual y están copiados al historial. Si se
entrena un modelo histórico con ellos, documentar que representan el
estado disponible en el dataset y que no constituyen un snapshot
perfecto por fecha.

------------------------------------------------------------------------

# 25. Modelo de rechazo

Objetivo:

``` text
P(motivo_rechazo | cliente, oferta, canal)
```

Entrenar únicamente sobre:

``` text
resultado == "rechazada"
```

Target:

``` text
precio
no_necesita
ya_tiene_similar
mal_momento
no_confia
otro
```

Modelo:

**CatBoostClassifier multiclass**

Salida:

``` json
{
  "precio": 0.51,
  "no_necesita": 0.22,
  "ya_tiene_similar": 0.13,
  "mal_momento": 0.08,
  "no_confia": 0.04,
  "otro": 0.02
}
```

Seleccionar el motivo principal y conservar el top 2 para
explicabilidad.

------------------------------------------------------------------------

# 26. Rebate

El dataset tiene `es_rebate`, pero existe una limitación fundamental:

Los registros `es_rebate=True` están asociados a rechazos y no existe un
target separado que indique si el rebate consiguió recuperar la venta.

Por tanto:

**NO afirmar que el modelo predice "probabilidad de éxito del rebate"
usando `es_rebate` como target.**

Sí se puede:

1.  Predecir el motivo de rechazo.
2.  Mapear el motivo a una estrategia de rebate.
3.  Generar un speech.
4.  Registrar posteriormente si el rebate funcionó en una nueva tabla.

Tabla de reglas:

  Motivo             Acción
  ------------------ --------------------------------------
  precio             enfatizar ahorro / alternativa menor
  no_necesita        mostrar necesidad basada en consumo
  ya_tiene_similar   explicar diferencia incremental
  mal_momento        sugerir seguimiento posterior
  no_confia          reforzar condiciones verificables
  otro               solicitar diagnóstico

------------------------------------------------------------------------

# 27. Motor de reglas

El modelo no puede recomendar cualquier oferta.

Crear una capa de reglas antes del ML.

## Regla 1 --- cliente ya tiene MT

Si:

``` text
es_movistar_total == True
```

entonces:

-   no recomendar OF020/OF021/OF022 como adquisición;
-   permitir, si se diseña una estrategia futura, ofertas
    complementarias no MT;
-   no fingir una nueva venta MT.

## Regla 2 --- oferta móvil

Si `segmento_objetivo == movil`:

``` text
tiene_movil == True
```

para plan/upgrade/equipo móvil, salvo que la lógica del negocio indique
explícitamente una excepción.

## Regla 3 --- oferta hogar

Si `segmento_objetivo == hogar`:

``` text
tiene_hogar == False
```

es una señal fuerte para adquirir hogar.

Si ya tiene hogar, preferir upgrades/bundles compatibles en lugar de
duplicar servicio.

## Regla 4 --- oferta MT

Para MT:

``` text
es_movistar_total == False
```

y la recomendación debe priorizar clientes elegibles o clientes que
tengan una ruta razonable hacia MT.

## Regla 5 --- no recomendar el producto actual

Si:

``` text
oferta_id == plan_actual_id
```

no recomendar como adquisición/upgrade.

## Regla 6 --- no recomendar hogar duplicado

Si la oferta corresponde al mismo servicio/cluster ya adquirido y no
representa upgrade, bloquear.

## Regla 7 --- fatiga

Si una oferta fue rechazada recientemente, aplicar penalización o
cooldown.

No bloquear para siempre.

## Regla 8 --- mora/reclamos

No asumir que mora implica rechazo.

Usarlo como señal de fricción o elegibilidad operativa si el negocio lo
define.

------------------------------------------------------------------------

# 28. Generación de candidatos

Para cada cliente:

``` text
cliente × 22 ofertas × 4 canales
```

En teoría:

``` text
88 combinaciones por cliente
```

Para 100,000 clientes:

``` text
8.8 millones de combinaciones
```

No hay que almacenar necesariamente todas.

Proceso:

1.  Cargar cliente.
2.  Cargar catálogo.
3.  Hacer producto cartesiano.
4.  Aplicar reglas.
5.  Conservar candidatos válidos.
6.  Generar features relacionales.
7.  Predecir.

Si el dashboard solo solicita un cliente, realizar esto bajo demanda.

Para batch:

-   vectorizar;
-   procesar por chunks;
-   evitar loops Python innecesarios.

------------------------------------------------------------------------

# 29. Modelo de ranking

Para cada candidato `(cliente, oferta, canal)`:

``` text
p_contacto
p_aceptacion
p_rechazo_motivo
valor_negocio
fit_cliente
friccion
fatiga
bonus_mt
```

Primero calcular:

``` text
p_venta =
p_contacto * p_aceptacion
```

Esto es una probabilidad aproximada de que la interacción termine en
aceptación bajo la cadena modelada.

------------------------------------------------------------------------

# 30. Score final

Implementar inicialmente:

``` text
score =
    0.50 * normalized(p_venta)
  + 0.20 * normalized(fit_cliente)
  + 0.10 * normalized(valor_negocio)
  + 0.10 * normalized(bonus_mt)
  - 0.10 * normalized(friccion)
```

Pero mantener los pesos en configuración:

``` yaml
scoring:
  w_conversion: 0.50
  w_fit: 0.20
  w_business: 0.10
  w_mt: 0.10
  w_friction: 0.10
```

El score debe ser **un ranking interno**, no una probabilidad.

La probabilidad mostrada al asesor debe ser `p_aceptacion` calibrada.

------------------------------------------------------------------------

# 31. Bonus MT

No forzar MT a todos los clientes.

El bonus MT debe activarse principalmente:

``` text
if elegible_mt:
    bonus_mt = high
elif etapa_mt in {2, 3}:
    bonus_mt = medium
else:
    bonus_mt = low
```

La razón:

El desafío pide impulsar MT, pero también pide una oferta correcta para
el cliente correcto.

El objetivo no es:

> "Siempre vender MT."

El objetivo es:

> "Priorizar MT cuando existe una oportunidad real de MT."

------------------------------------------------------------------------

# 32. Calibración de probabilidades

No basta con AUC.

El sistema mostrará:

``` text
82% de probabilidad
```

por lo que esa cifra debe ser razonablemente calibrada.

Después de entrenar:

-   probar Platt scaling / sigmoid;
-   probar isotonic regression;
-   elegir según validation.

Métricas:

-   Brier score.
-   Log loss.
-   Calibration curve.
-   Expected Calibration Error si se implementa.

Guardar calibrador junto al modelo.

------------------------------------------------------------------------

# 33. Explicabilidad

Usar SHAP para CatBoost.

Para cada recomendación devolver:

``` text
factores_positivos
factores_negativos
```

Ejemplo:

``` json
{
  "positive": [
    "Cliente elegible para Movistar Total",
    "Tiene internet hogar",
    "Consumo de datos alto",
    "Alta afinidad con canal Digital"
  ],
  "negative": [
    "Precio de la oferta superior a la facturación actual"
  ]
}
```

La explicación para el asesor debe ser humana.

No mostrar:

> "feature_17 = 0.823"

Mostrar:

> "El cliente consume 64 GB/mes y la oferta cubre hasta 60 GB; además,
> ya tiene móvil postpago e internet hogar, por lo que es un candidato
> natural a MT."

------------------------------------------------------------------------

# 34. Recomendación de canal

El motor debe evaluar:

``` text
Digital
Tienda
Call In
Call Out
```

Para cada oferta.

La recomendación final puede ser:

``` text
canal_recomendado = argmax(p_contacto * p_aceptacion)
```

o directamente:

``` text
argmax(p_venta)
```

entre canales.

Si el canal histórico del cliente es claramente dominante, usarlo como
feature, no como regla absoluta.

------------------------------------------------------------------------

# 35. Recomendación de momento

El dataset no tiene hora ni suficiente granularidad temporal para
aprender una hora del día.

Por eso NO inventar:

> "Martes 19:30"

La implementación MVP debe devolver:

``` text
momento_recomendado:
  "siguiente interacción digital"
```

o:

``` text
"próxima ventana comercial"
```

o una prioridad:

``` text
urgencia:
  alta / media / baja
```

Puede basarse en:

-   recencia de interacción,
-   actividad,
-   rechazo reciente,
-   fecha del último ofrecimiento,
-   canal.

Para producción se necesitarían timestamp/hora y eventos más granulares.

------------------------------------------------------------------------

# 36. Top 3 recomendaciones

La API debe devolver:

1.  Mejor oferta.
2.  Segunda opción.
3.  Tercera opción.

Cada una:

``` json
{
  "oferta_id": "OF021",
  "nombre": "Movistar Total Plus",
  "canal": "Digital",
  "probabilidad_aceptacion": 0.82,
  "probabilidad_contacto": 0.91,
  "probabilidad_venta": 0.746,
  "score": 0.88,
  "es_mt": true,
  "motivo": "...",
  "objecion_principal": "precio"
}
```

No devolver ofertas bloqueadas.

------------------------------------------------------------------------

# 37. Ejemplo de decisión

Cliente:

``` text
tipo_cliente = postpago
tiene_movil = True
tiene_hogar = True
tiene_internet_hogar = True
es_movistar_total = False
elegible_mt = True
consumo_datos = 55 GB
facturacion = S/ 150
es_usuario_app = True
canal_mas_usado = Digital
```

Candidatos:

``` text
MT Básico + Digital
MT Plus + Digital
MT Max + Digital
MT Básico + Tienda
MT Plus + Tienda
...
```

Resultado hipotético:

``` text
MT Plus + Digital
P(contacto) = 0.91
P(aceptación | contacto) = 0.82
P(venta) = 0.746
```

La recomendación:

``` text
Movistar Total Plus
Canal: Digital
Probabilidad aceptación: 82%
```

------------------------------------------------------------------------

# 38. API

Crear endpoint:

``` http
POST /api/v1/nbo/recommend
```

Request:

``` json
{
  "cliente_id": "CLI000201"
}
```

Response:

``` json
{
  "cliente": {
    "cliente_id": "CLI000201",
    "etapa_mt": "elegible_mt",
    "elegible_mt": true,
    "es_movistar_total": false
  },
  "recommendation": {
    "oferta_id": "OF021",
    "nombre_oferta": "Movistar Total Plus",
    "canal": "Digital",
    "momento": "proxima_interaccion_digital",
    "probabilidad_contacto": 0.91,
    "probabilidad_aceptacion": 0.82,
    "probabilidad_venta": 0.746,
    "score": 0.88
  },
  "why": {
    "positive": [
      "Es elegible para Movistar Total",
      "Tiene móvil postpago e internet hogar",
      "Uso digital frecuente"
    ],
    "negative": [
      "Precio relativamente superior a su facturación"
    ]
  },
  "rejection_prediction": {
    "motivo": "precio",
    "probability": 0.51
  },
  "rebate": {
    "enabled": true,
    "strategy": "mostrar_ahorro"
  },
  "alternatives": []
}
```

------------------------------------------------------------------------

# 39. Endpoint de batch

``` http
POST /api/v1/nbo/batch
```

Entrada:

``` json
{
  "limit": 1000
}
```

Salida:

CSV/JSON con:

``` text
cliente_id
oferta_id
canal
probabilidad_contacto
probabilidad_aceptacion
probabilidad_venta
score
es_mt
etapa_mt
motivo_recomendacion
```

------------------------------------------------------------------------

# 40. Endpoint de feedback

Crear:

``` http
POST /api/v1/nbo/feedback
```

Payload:

``` json
{
  "cliente_id": "CLI000201",
  "oferta_id": "OF021",
  "canal": "Digital",
  "resultado": "rechazada",
  "motivo_rechazo": "precio",
  "es_rebate": true,
  "resultado_rebate": "aceptada"
}
```

`resultado_rebate` no existe en el dataset histórico original, pero debe
existir en la futura arquitectura para poder aprender realmente la
eficacia de los rebates.

------------------------------------------------------------------------

# 41. Trazabilidad E2E

Crear una tabla de eventos:

``` text
nbo_decisions
```

Campos:

``` text
decision_id
cliente_id
timestamp
model_version
feature_version
offer_id
channel
p_contact
p_acceptance
p_sale
score
rank
reason_codes
predicted_rejection
rebate_strategy
advisor_id
displayed
contacted
proof_type
final_result
rejection_reason
rebate_used
rebate_result
```

Esto permite demostrar:

``` text
clasificación
    ↓
recomendación
    ↓
contacto
    ↓
mensaje
    ↓
medio probatorio
    ↓
resultado
```

------------------------------------------------------------------------

# 42. Dashboard para asesor

La interfaz debe ser extremadamente simple.

## Header

``` text
Cliente: CLI000201
Segmento: Elegible MT
Prioridad: ALTA
```

## Card principal

``` text
⭐ NEXT BEST OFFER

Movistar Total Plus

Probabilidad de aceptación
82%

Canal recomendado
Digital

¿Por qué?
✓ Tiene móvil postpago
✓ Tiene internet hogar
✓ Es elegible MT
✓ Uso frecuente de App
✓ Consumo de datos compatible
```

## Botones

``` text
[Presentar oferta]
[Ver alternativa]
[Registrar rechazo]
```

## Objeción probable

``` text
⚠ Objeción probable: PRECIO

Rebate sugerido:
Mostrar ahorro frente a contratar servicios por separado.
```

## Alternativas

``` text
2. MT Básico — 74%
3. Upgrade Plan Max — 68%
```

------------------------------------------------------------------------

# 43. Dashboard de negocio

Agregar una segunda vista.

KPIs:

``` text
Clientes evaluados
% elegibles MT
% recomendación MT
Probabilidad media
Conversión histórica
Conversión estimada
```

Funnel:

``` text
Clientes priorizados
        ↓
Contactados
        ↓
Oferta presentada
        ↓
Aceptadas
        ↓
Venta
```

Filtros:

-   canal;
-   oferta;
-   MT / no MT;
-   departamento;
-   tipo de cliente;
-   etapa MT;
-   edad;
-   periodo.

------------------------------------------------------------------------

# 44. Métricas de evaluación ML

## Contactabilidad

-   ROC AUC.
-   PR AUC.
-   Log loss.
-   Brier score.
-   Calibration curve.

## Aceptación

-   ROC AUC.
-   PR AUC.
-   Log loss.
-   Brier.
-   Top-K precision.
-   Recall.
-   Calibration.

## Recomendación

Más importante que accuracy:

-   Hit@1.
-   Hit@3.
-   Precision@K.
-   NDCG@K.
-   conversión estimada del top 1.
-   uplift potencial frente a baseline.

------------------------------------------------------------------------

# 45. Baselines obligatorios

Comparar contra:

## Baseline A

Oferta más popular.

``` text
recomendar la oferta con mayor aceptación histórica
```

## Baseline B

Oferta popular por segmento.

``` text
tipo_cliente × tipo_oferta
```

## Baseline C

Oferta más popular por canal.

El modelo debe demostrar mejora sobre al menos un baseline.

------------------------------------------------------------------------

# 46. Evaluación de negocio

Reportar:

``` text
% de recomendaciones MT
% de elegibles MT capturados
probabilidad media de aceptación
probabilidad media de venta
precio medio recomendado
```

Impactos esperados según el desafío:

-   mayor conversión;
-   mayor participación MT;
-   mayor ARPU;
-   menor churn;
-   mejor permanencia;
-   mejor experiencia;
-   mayor efectividad comercial.

No afirmar que el prototipo reduce churn si no existe un target de churn
entrenable en los archivos entregados.

------------------------------------------------------------------------

# 47. Churn

El material del desafío menciona churn como resultado esperado, pero los
tres CSV entregados no incluyen una variable de churn explícita
utilizable como target.

Por tanto:

## MVP

No entrenar un modelo de churn falso.

## Opcional

Crear un:

``` text
risk_proxy
```

basado en:

-   mora;
-   meses moroso;
-   reclamos;
-   actividad;
-   antigüedad.

Pero etiquetarlo claramente como:

> **proxy de fricción/riesgo comercial, no predicción validada de
> churn.**

Para un modelo real se necesita una etiqueta:

``` text
churn_30d
churn_60d
churn_90d
```

y snapshots temporales.

------------------------------------------------------------------------

# 48. Segmentación y clustering

Es opcional, pero puede aportar al proyecto.

Crear clusters utilizando:

-   consumo;
-   facturación;
-   actividad;
-   uso App;
-   antigüedad;
-   servicios.

Algoritmo:

-   KMeans como baseline;
-   seleccionar K con silhouette;
-   evaluar estabilidad.

Ejemplo de perfiles:

``` text
Cluster 1 — Alto consumo digital
Cluster 2 — Bajo consumo / precio sensible
Cluster 3 — Hogar intensivo
Cluster 4 — Alta antigüedad
```

El cluster debe ser un feature auxiliar, no la decisión final.

------------------------------------------------------------------------

# 49. IA generativa

El LLM debe estar fuera del núcleo de scoring.

Input:

``` json
{
  "cliente": {
    "tipo": "postpago",
    "consumo_gb": 55,
    "facturacion": 150
  },
  "oferta": {
    "nombre": "Movistar Total Plus",
    "precio": 189.9,
    "gb": 60,
    "ahorro_pct": 35
  },
  "motivo": [
    "elegible_mt",
    "tiene_internet",
    "alto_consumo"
  ],
  "objecion": "precio"
}
```

Output:

``` text
Mensaje:
"Por tu consumo de datos y porque ya tienes móvil e internet hogar,
Movistar Total Plus puede darte una solución integrada..."

Rebate:
"Si el precio es la principal preocupación, explica primero el ahorro
del bundle y las condiciones disponibles."
```

------------------------------------------------------------------------

# 50. Reglas del LLM

El LLM:

-   NO puede inventar precios.
-   NO puede inventar beneficios.
-   NO puede inventar descuentos.
-   NO puede inventar condiciones.
-   NO puede afirmar que un cliente aceptará.
-   NO puede revelar información sensible.
-   Debe usar solo campos estructurados.
-   Debe producir mensajes cortos y accionables.

------------------------------------------------------------------------

# 51. RAG

RAG es opcional.

Si se implementa:

``` text
Documentos comerciales
       ↓
Chunking
       ↓
Embeddings
       ↓
Vector DB
       ↓
Retriever
       ↓
LLM
       ↓
Speech validado
```

Documentos posibles:

-   fichas de oferta;
-   políticas;
-   condiciones;
-   manuales;
-   FAQs;
-   argumentarios.

El RAG no debe decidir la oferta.

El flujo correcto es:

``` text
ML → oferta
RAG → información oficial de esa oferta
LLM → speech
```

------------------------------------------------------------------------

# 52. Seguridad del RAG

Si se usa RAG:

-   limitar documentos a fuentes autorizadas;
-   devolver citas/fuentes internas;
-   evitar recuperación de información irrelevante;
-   no almacenar PII;
-   no permitir que el LLM modifique precios;
-   validar el output antes de mostrarlo.

------------------------------------------------------------------------

# 53. Recomendación de momento

Como el dataset no tiene hora del día, implementar:

``` text
urgencia
```

y:

``` text
ventana_recomendada
```

Ejemplos:

``` text
"inmediata"
"proxima_interaccion_digital"
"proximo_contacto_asesor"
"recontactar_luego"
```

Reglas:

-   rechazo `mal_momento` → aumentar delay.
-   rechazo reciente → cooldown.
-   alta actividad digital → priorizar Digital.
-   alta contactabilidad histórica → priorizar ese canal.

------------------------------------------------------------------------

# 54. Cooldown

Crear configuración:

``` yaml
cooldown:
  same_offer_days: 30
  same_offer_after_rejection_days: 14
  max_recent_offers: 3
```

Estos valores son iniciales para el MVP y deben poder cambiarse.

No presentar una regla como si fuera una política oficial de Movistar.

------------------------------------------------------------------------

# 55. Manejo de `pendiente`

Esto es crítico.

Historial:

``` text
pendiente = no_contactado
```

No significa:

``` text
rechazó
```

Para el modelo de contactabilidad:

``` text
pendiente → no_contactado = 0
```

Para aceptación:

``` text
pendiente → excluir
```

Para análisis de campaña:

``` text
pendiente → oportunidad perdida por no contacto
```

------------------------------------------------------------------------

# 56. Manejo de `es_rebate`

No usar:

``` text
es_rebate
```

como si fuera:

``` text
rebate_aceptado
```

El campo solo indica que hubo una contraoferta.

La futura tabla debe añadir:

``` text
rebate_resultado
```

------------------------------------------------------------------------

# 57. Problema de causalidad

El historial muestra ofertas observadas, no todas las ofertas posibles.

Por tanto:

``` text
P(aceptación | oferta)
```

es una estimación basada en ofertas históricamente ofrecidas.

No equivale automáticamente a:

``` text
efecto causal de ofrecer la oferta
```

Para producción avanzada:

-   propensity score;
-   inverse propensity weighting;
-   uplift modeling;
-   contextual bandits;
-   A/B testing.

Para hackathon:

**modelo supervisado + ranking + reglas + evaluación contra baseline**
es suficiente.

------------------------------------------------------------------------

# 58. Optimización avanzada opcional

Una futura versión puede utilizar:

``` text
Expected Value
=
P(venta) × margen incremental
-
coste contacto
-
penalización experiencia
```

Si no se dispone de margen, no inventarlo.

En MVP:

``` text
valor_negocio
```

puede ser un proxy basado en precio o prioridad estratégica, claramente
documentado.

------------------------------------------------------------------------

# 59. Contrato interno del motor

Crear una función:

``` python
recommend(cliente_id: str) -> NBOResult
```

Flujo:

``` python
def recommend(cliente_id):

    customer = load_customer(cliente_id)

    candidates = generate_candidates(
        customer=customer,
        catalog=offers
    )

    candidates = apply_business_rules(
        customer,
        candidates
    )

    features = build_pair_features(
        customer,
        candidates
    )

    candidates["p_contact"] = contact_model.predict_proba(features)
    candidates["p_accept"] = acceptance_model.predict_proba(features)

    candidates["p_sale"] = (
        candidates["p_contact"] *
        candidates["p_accept"]
    )

    candidates = apply_scoring(candidates)

    ranked = rank_candidates(candidates)

    top = ranked.head(3)

    explanations = explain(top)

    rejection = predict_rejection(top.iloc[0])

    rebate = build_rebate(rejection)

    return build_nbo_response(
        customer,
        top,
        explanations,
        rejection,
        rebate
    )
```

------------------------------------------------------------------------

# 60. Esquemas Pydantic

Crear:

``` python
class NBORequest(BaseModel):
    cliente_id: str

class Recommendation(BaseModel):
    oferta_id: str
    nombre_oferta: str
    canal: str
    probabilidad_contacto: float
    probabilidad_aceptacion: float
    probabilidad_venta: float
    score: float
    es_mt: bool

class Explanation(BaseModel):
    positive: list[str]
    negative: list[str]

class RejectionPrediction(BaseModel):
    motivo: str
    probability: float

class NBOResponse(BaseModel):
    cliente_id: str
    recommendation: Recommendation
    alternatives: list[Recommendation]
    explanation: Explanation
    rejection_prediction: RejectionPrediction
    rebate_strategy: str
```

------------------------------------------------------------------------

# 61. Persistencia

Para MVP:

-   SQLite o PostgreSQL.

Tablas:

``` text
customers
offers
campaign_history
model_versions
nbo_decisions
feedback_events
```

Para demo se puede cargar CSV y usar SQLite.

------------------------------------------------------------------------

# 62. Versionado

Guardar:

``` text
model_version
feature_version
rules_version
catalog_version
```

Ejemplo:

``` text
model_version = "acceptance_catboost_v1"
feature_version = "features_v1"
rules_version = "rules_v1"
catalog_version = "catalog_2026_08"
```

Esto es necesario para trazabilidad.

------------------------------------------------------------------------

# 63. Tests

Implementar mínimo:

## Data

-   IDs únicos.
-   FKs válidas.
-   catálogo correcto.

## Rules

Test:

``` text
cliente MT → no recomendar MT adquisición
```

``` text
cliente sin móvil → no recomendar upgrade móvil
```

``` text
cliente elegible MT → MT disponible
```

## Features

-   no división por cero;
-   9999 correctamente tratado;
-   nulos manejados.

## Model

-   output entre 0 y 1;
-   no NaN;
-   schema correcto.

## Ranking

-   top 1 tiene mayor score;
-   no aparecen ofertas bloqueadas.

------------------------------------------------------------------------

# 64. Logging

Registrar:

``` text
request_id
cliente_id
timestamp
model_version
latency_ms
number_candidates
top_offer
top_channel
score
```

No registrar información personal no necesaria.

------------------------------------------------------------------------

# 65. Latencia objetivo

Para dashboard:

``` text
< 1 segundo
```

idealmente.

Optimización:

-   cargar modelos una vez;
-   cachear catálogo;
-   cachear clientes;
-   vectorizar features;
-   evitar cargar CSV en cada request.

------------------------------------------------------------------------

# 66. Flujo de entrenamiento

Ejecutar:

``` bash
python training/build_training_set.py
python training/train_contactability.py
python training/train_acceptance.py
python training/train_rejection.py
python training/calibrate.py
python training/evaluate.py
```

Guardar:

``` text
models/
```

con:

``` text
model
metrics.json
feature_schema.json
training_metadata.json
```

------------------------------------------------------------------------

# 67. Flujo de ejecución

``` bash
python -m src.api
```

o:

``` bash
uvicorn src.api:app --reload
```

Dashboard:

``` bash
streamlit run app/streamlit_app.py
```

------------------------------------------------------------------------

# 68. EDA obligatorio

Antes de entrenar:

1.  Distribución de clientes.
2.  Distribución MT.
3.  Distribución de ofertas.
4.  Resultados históricos.
5.  Contactabilidad por canal.
6.  Aceptación por canal.
7.  Aceptación por oferta.
8.  Aceptación MT vs no MT.
9.  Rechazos por motivo.
10. Relación precio/facturación.
11. Distribución de consumo.
12. Segmentos elegibles MT.

No utilizar EDA como sustituto del modelo.

------------------------------------------------------------------------

# 69. Hallazgos de control ya observados

En los archivos entregados:

``` text
100,000 clientes
7,194 ya tienen MT
13,650 son elegibles MT
92,806 no son MT
86,350 no son elegibles MT
```

El historial tiene:

``` text
300,112 ofrecimientos
95,414 aceptados
159,204 rechazados
45,494 pendientes
```

Los pendientes son no contactados.

En MT:

``` text
28,506 ofrecimientos MT
16,872 aceptados
7,335 rechazados
4,299 pendientes
```

Estas cifras sirven como sanity checks, no como métricas de producción.

------------------------------------------------------------------------

# 70. Baseline MT

Crear una métrica específica:

``` text
MT acceptance rate =
accepted MT / contacted MT
```

y compararla con:

``` text
non-MT acceptance rate
```

También:

``` text
eligible MT → MT offer rate
eligible MT → MT acceptance rate
```

Esto ayuda a demostrar el caso prioritario.

------------------------------------------------------------------------

# 71. Objetivo de recomendación MT

Para clientes `elegible_mt=True`, el sistema debe:

1.  Incluir MT entre candidatos.
2.  Evaluar los tres tiers.
3.  Comparar MT contra otras ofertas.
4.  No forzar MT si una alternativa tiene mejor ajuste y la diferencia
    es sustancial.
5.  Mostrar claramente cuando MT ganó el ranking.

------------------------------------------------------------------------

# 72. Cómo seleccionar el tier MT

No seleccionar simplemente por precio.

Features:

``` text
consumo_datos_gb_prom
monto_facturado_prom
monto_facturado_prom_6m
precio_mt
ratio_precio
gb_mt
ahorro_pct
historial_mt
historial_rechazo_precio
```

Ejemplo:

``` text
MT Básico: 30GB / S/149.9
MT Plus: 60GB / S/189.9
MT Max: ilimitado / S/229.9
```

El modelo debe aprender cuál tiene mejor probabilidad.

------------------------------------------------------------------------

# 73. Recomendación de alternativa

Si top 1 es:

``` text
MT Plus
```

top 2 podría ser:

``` text
MT Básico
```

si tiene alta probabilidad.

Si la principal objeción prevista es precio:

``` text
alternative = tier inferior
```

Esto permite que el asesor tenga una ruta comercial:

``` text
Oferta principal
      ↓
Objeción
      ↓
Rebate
      ↓
Alternativa
```

------------------------------------------------------------------------

# 74. Reglas para no sobrepersonalizar

No utilizar:

-   inferencias sensibles;
-   información no entregada;
-   atributos no necesarios;
-   datos personales reales.

No construir recomendaciones basadas en raza, religión, orientación
sexual, salud u otros atributos sensibles.

Los datos entregados son anonimizados.

------------------------------------------------------------------------

# 75. Uso ético

El sistema debe:

-   explicar la recomendación;
-   permitir intervención del asesor;
-   no ocultar que es una recomendación;
-   evitar presión excesiva;
-   limitar frecuencia;
-   respetar rechazos;
-   no inventar beneficios;
-   no penalizar injustamente por variables sensibles.

------------------------------------------------------------------------

# 76. Interfaz: regla de oro

El asesor trabaja bajo presión.

Por eso la pantalla debe responder en menos de 10 segundos visualmente:

``` text
¿Quién es?
¿Qué le ofrezco?
¿Por qué?
¿Por qué canal?
¿Qué digo?
¿Qué hago si rechaza?
```

No mostrar un dashboard de 50 gráficos como pantalla principal.

------------------------------------------------------------------------

# 77. Demo ideal para el jurado

Preparar tres clientes:

## Demo 1 --- Elegible MT

Mostrar:

``` text
Cliente → elegible MT
→ MT Plus
→ Digital
→ 82%
→ explicación
→ rebate precio
```

## Demo 2 --- No elegible MT

Mostrar:

``` text
Cliente no tiene internet hogar
→ oferta hogar
→ ruta para acercarlo a MT
```

## Demo 3 --- Cliente con MT

Mostrar:

``` text
Ya tiene MT
→ no volver a recomendar MT
→ oferta complementaria
```

Esto demuestra que el motor no es un simple:

``` text
if elegible_mt: vender MT
```

------------------------------------------------------------------------

# 78. Criterios de aceptación del MVP

El proyecto se considera implementado cuando:

-   [ ] Los tres CSV cargan correctamente.
-   [ ] Se validan relaciones.
-   [ ] Se construyen features.
-   [ ] Se genera training set.
-   [ ] Se entrenan modelos.
-   [ ] Se calibran probabilidades.
-   [ ] Se ejecutan reglas.
-   [ ] Se generan candidatos.
-   [ ] Se calculan probabilidades.
-   [ ] Se genera ranking.
-   [ ] Se explican recomendaciones.
-   [ ] Se predice rechazo.
-   [ ] Se genera rebate.
-   [ ] Se devuelve Top 3.
-   [ ] Existe endpoint NBO.
-   [ ] Existe dashboard.
-   [ ] Se registra decisión.
-   [ ] Existe evaluación contra baseline.
-   [ ] Se documentan limitaciones.

------------------------------------------------------------------------

# 79. Prioridad de implementación

## P0 --- imprescindible

1.  Carga de datos.
2.  Validación.
3.  Features.
4.  Motor de reglas.
5.  Modelo de aceptación.
6.  Ranking.
7.  MT.
8.  Explicabilidad.
9.  Dashboard.

## P1 --- importante

10. Modelo de contactabilidad.
11. Modelo de rechazo.
12. Rebate.
13. Trazabilidad.
14. Top 3.
15. Calibración.

## P2 --- diferenciador

16. Clustering.
17. LLM.
18. RAG.
19. uplift modeling.
20. optimización avanzada.

------------------------------------------------------------------------

# 80. Orden exacto de trabajo recomendado

## Fase 1 --- datos

``` text
1. cargar CSV
2. validar
3. unir tablas
4. EDA
```

## Fase 2 --- baseline

``` text
5. modelo simple
6. métricas
7. baseline de popularidad
```

## Fase 3 --- ML

``` text
8. features
9. CatBoost contactabilidad
10. CatBoost aceptación
11. calibración
12. modelo rechazo
```

## Fase 4 --- NBO

``` text
13. candidatos
14. reglas
15. score
16. ranking
17. top 3
```

## Fase 5 --- experiencia

``` text
18. SHAP
19. rebate
20. LLM
21. dashboard
```

## Fase 6 --- producción/demo

``` text
22. API
23. logging
24. tests
25. demo
26. evaluación final
```

------------------------------------------------------------------------

# 81. Qué NO hacer

## No hacer 1

No entrenar:

``` text
resultado = pendiente → rechazo
```

## No hacer 2

No recomendar MT a todo cliente elegible sin evaluar tier/canal.

## No hacer 3

No utilizar un LLM para decidir la oferta.

## No hacer 4

No usar RAG como sustituto del ML.

## No hacer 5

No afirmar causalidad:

``` text
"esta oferta causa 82% de conversión"
```

La cifra debe ser:

``` text
"probabilidad estimada según el modelo"
```

## No hacer 6

No presentar `es_rebate=True` como éxito del rebate.

## No hacer 7

No inventar churn.

## No hacer 8

No inventar horarios de contacto.

## No hacer 9

No mostrar probabilidades sin calibración.

## No hacer 10

No usar solo accuracy como métrica principal.

------------------------------------------------------------------------

# 82. Versión avanzada futura

Una versión productiva podría evolucionar hacia:

``` text
Candidate Generation
       ↓
Eligibility
       ↓
Propensity Models
       ↓
Uplift Model
       ↓
Business Optimization
       ↓
Contextual Bandit
       ↓
Next Best Action
```

En ese punto el sistema ya no solo preguntaría:

> "¿Qué cliente probablemente compra?"

sino:

> "¿Qué acción genera el mayor incremento de conversión respecto a no
> realizarla?"

Eso requiere más datos que los disponibles en el hackathon.

------------------------------------------------------------------------

# 83. Resumen final de la solución

El motor debe implementar:

``` text
CLIENTE
   │
   ├── Perfil
   ├── Consumo
   ├── Servicios
   ├── Actividad
   ├── Mora/reclamos
   └── Historial
           │
           ▼
   FEATURE ENGINEERING
           │
           ▼
   GENERACIÓN DE CANDIDATOS
           │
           ▼
   REGLAS DE NEGOCIO
           │
           ▼
   ┌─────────────────────┐
   │ ML CONTACTABILIDAD  │
   └──────────┬──────────┘
              │
              ▼
   ┌─────────────────────┐
   │ ML ACEPTACIÓN       │
   └──────────┬──────────┘
              │
              ▼
       P(contacto)
       P(aceptación)
       P(venta)
              │
              ▼
      SCORING / RANKING
              │
              ▼
        TOP 3 OFERTAS
              │
              ├──────────────┐
              ▼              ▼
        EXPLICABILIDAD    RECHAZO
                              │
                              ▼
                           REBATE
                              │
                              ▼
                           LLM/RAG
                              │
                              ▼
                     SPEECH PERSONALIZADO
                              │
                              ▼
                        DASHBOARD ASESOR
                              │
                              ▼
                      FEEDBACK / TRAZA E2E
```

------------------------------------------------------------------------

# 84. Principio de diseño definitivo

La solución debe cumplir esta ecuación conceptual:

``` text
Next Best Offer
=
Oferta adecuada
+
Canal adecuado
+
Momento adecuado
+
Probabilidad
+
Explicación
+
Rebate
+
Trazabilidad
```

Y el principio de negocio:

> **No se trata de vender siempre la oferta más rentable ni de vender
> siempre Movistar Total. Se trata de identificar la mejor acción
> comercial para ese cliente, en ese contexto, maximizando conversión y
> valor sin deteriorar la experiencia.**

------------------------------------------------------------------------

# 85. Entregables técnicos finales

El repositorio debe terminar con:

``` text
1. Código fuente
2. Dataset preprocessing
3. Modelos entrenados
4. Métricas
5. Feature schema
6. Motor de reglas
7. Motor NBO
8. API
9. Dashboard
10. Explicabilidad
11. Rebate
12. Logs/trazabilidad
13. Tests
14. README
15. Demo reproducible
```

El README debe explicar:

``` text
Cómo instalar
Cómo cargar datos
Cómo entrenar
Cómo evaluar
Cómo ejecutar API
Cómo ejecutar dashboard
Cómo consultar un cliente
Cómo interpretar la recomendación
Limitaciones
```

------------------------------------------------------------------------

# 86. Resultado esperado de una consulta

Una consulta:

``` text
CLI000201
```

debe producir algo conceptualmente equivalente a:

``` text
==================================================
NEXT BEST OFFER
==================================================

Cliente: CLI000201
Etapa: Elegible Movistar Total
Prioridad: ALTA

RECOMENDACIÓN
----------------------------------
Movistar Total Plus
OF021

Canal:
Digital

P(contacto):
91%

P(aceptación | contacto):
82%

P(venta):
74.6%

Score:
0.88

¿POR QUÉ?
----------------------------------
✓ Tiene móvil postpago
✓ Tiene internet hogar
✓ Cumple elegibilidad MT
✓ Tiene actividad digital
✓ Consumo de datos compatible

OBJECIÓN PROBABLE
----------------------------------
Precio — 51%

REBATE
----------------------------------
Mostrar beneficio económico del bundle
y comparar con la situación actual.

ALTERNATIVAS
----------------------------------
2. Movistar Total Básico
3. Upgrade / oferta alternativa compatible

[ PRESENTAR OFERTA ]
[ VER ALTERNATIVAS ]
[ REGISTRAR RESULTADO ]
```

Los números del ejemplo son ilustrativos; la implementación debe
calcularlos con los modelos entrenados.

------------------------------------------------------------------------

# 87. Nota final para el agente de implementación

Implementar primero un sistema **funcional, reproducible y explicable**.

No intentar construir una plataforma de telecomunicaciones completa.

La prioridad es:

``` text
Datos correctos
→ ML correcto
→ reglas correctas
→ ranking correcto
→ explicación clara
→ demo convincente
```

El desafío oficial enfatiza que el éxito no depende únicamente del mayor
accuracy, sino de demostrar cómo el algoritmo resuelve el problema,
crear variables ingeniosas y traducir los resultados a una interfaz
simple para un asesor. El caso MT debe ser demostrable, pero el motor
debe permanecer generalizable al resto del portafolio.

**Definition of Done:** si un desarrollador puede clonar el repositorio,
colocar los tres CSV en `data/raw/`, ejecutar el entrenamiento, levantar
la API/dashboard y consultar un `cliente_id` obteniendo una oferta,
canal, probabilidades, explicación, objeción y rebate, entonces el MVP
cumple la especificación.

# 51. Extensión closed-loop operacional (API 1.4.0)

La inferencia operacional reconstruye el estado como perfil maestro más un ledger append-only `customer_state_events`, ordenado por `effective_at`, `recorded_at` y `event_id`. Los CSV originales no se modifican. Cada escritura exige `idempotency_key` y `expected_state_version`; una corrección se expresa como un nuevo evento que referencia `correction_of_event_id`.

Eventos admitidos: `product_activated`, `product_cancelled`, `usage_updated`, `billing_updated`, `preferred_channel_changed`, `mt_eligibility_overridden` y `customer_attribute_corrected`. La aceptación solo registra intención. La activación exige evidencia y, cuando incluye `decision_id`, valida cliente, candidato y aceptación previa.

La recomendación normal usa el estado vigente y persiste `state_version`, snapshot mínimo e IDs de eventos aplicados bajo `decision_v3` y `rules_v4`. La evaluación histórica y `recommend_as_of` usan exclusivamente el perfil maestro y el histórico del dataset. La adaptación inmediata actualiza soporte jerárquico, fatiga y cooldown sin reentrenar ni modificar `nbo_v2`.

Endpoints públicos:

- `POST /api/v1/nbo/customer-events`.
- `GET /api/v1/nbo/customer-state/{cliente_id}` con `as_of` opcional.
- `GET /api/v1/nbo/customer-state/{cliente_id}/events`.
- `GET /api/v1/nbo/learning/readiness`.

El readiness es descriptivo y conservador. Solo recomienda `ready_for_challenger`; nunca dispara entrenamiento automático ni promoción de modelos.
