# Informe resumido del proyecto Next Best Offer

**Fecha de corte:** 13 de agosto de 2026  
**Versión activa:** `nbo_v2`  
**Versiones asociadas:** `features_v2`, `rules_v4`, `playbook_v2`, `decision_v3`, `catalog_2026_08`  
**Estado general:** motor closed-loop funcional, entrenado con todos los datos, evaluado sin fuga temporal y preparado para la entrega técnica, la demostración adaptativa y el procesamiento masivo. Todavía no debe considerarse un sistema productivo validado en campo.

## Actualización closed-loop

- Ledger SQLite append-only con idempotencia, evidencia, correcciones compensatorias y control optimista de versión.
- Reconstrucción de estado actual o a fecha de corte sin modificar los tres CSV maestros.
- Aceptación separada de activación; la activación validada recalcula y persiste inmediatamente la nueva NBO.
- Ofertas activas bloqueadas, derivación/override MT y adaptación de tasas, fatiga y cooldown desde feedback operacional deduplicado.
- API `1.4.0`, `rules_v4` y `decision_v3`; `nbo_v2` permanece como champion sin reentrenamiento.
- Readiness conservador para challenger, sin entrenamiento ni promoción automáticos.
- Demo reproducible `CLI000001`: `OF005` → aceptación → activación → elegible MT → `OF022` → rechazo por precio → tier MT inferior.

## 1. Objetivo

El proyecto implementa un motor de **Next Best Offer (NBO)** que, dado un cliente, selecciona tres ofertas válidas y ordenadas. Para cada recomendación determina:

- Oferta y canal recomendado.
- Probabilidad de contacto.
- Probabilidad de aceptación condicionada al contacto.
- Probabilidad aproximada de venta.
- Score interno de ranking.
- Motivos positivos y advertencias.
- Beneficio para el cliente y beneficio proxy para el negocio.
- Speech comercial inicial.
- Objeciones probables y speech de rebate.
- Momento y urgencia recomendados.
- Ruta hacia Movistar Total cuando corresponda.
- Objetivo comercial y siguiente paso explícito según la etapa MT.
- Acción de recuperación si finalmente ocurre un rechazo.
- Playbook comercial personalizado y adaptado al canal.
- Trazabilidad del score, soporte histórico y variante experimental del playbook.

Cada decisión conserva las versiones del modelo, features, reglas y catálogo utilizadas.

## 2. Datos utilizados

El motor usa exclusivamente los tres archivos crudos entregados para el desafío:

| Fuente | Registros | Uso |
|---|---:|---|
| `dataset_clientes.csv` | 100,000 | Perfil, servicios, consumo, facturación y actividad |
| `catalogo_ofertas_entrega.csv` | 22 | Portafolio y atributos de las ofertas |
| `historial_campanias.csv` | 300,112 | Contactabilidad, aceptación, rechazo y campañas históricas |

Los CSV limpios del EDA no se utilizan para entrenar porque contienen agregaciones realizadas sobre todo el historial y podrían introducir fuga de información.

## 3. Componentes implementados

### Datos y features

- Validación de esquemas, claves, relaciones, dominios e invariantes.
- Tratamiento de nulos con significado comercial.
- Acumulados históricos por cliente, oferta, tipo y canal.
- Exclusión del evento evaluado y de todos los eventos de su mismo mes.
- Afinidad de canal, sensibilidad al precio, fatiga, fricción y cooldown.
- Ajuste entre consumo, capacidad, precio y facturación.
- Clasificación de la etapa del cliente en la ruta Movistar Total.
- Exclusión de `cliente_id` y textos comerciales redundantes de las variables del modelo.

### Modelos y decisión

- Comparación entre regresión logística, CatBoost y fallbacks jerárquicos.
- Búsqueda de hiperparámetros y comparación de calibradores.
- Separación principal 70/15/15 por cliente, semilla 42.
- Evaluación temporal enero–abril, mayo y junio.
- Selección automática del modelo únicamente cuando supera un baseline definido.
- Reglas de elegibilidad para móvil, hogar, upgrades, equipos, paquetes y MT.
- Ranking con guardrails de diversidad, precio, compatibilidad y fatiga.
- Explicaciones deterministas y contribuciones del modelo cuando están disponibles.

### Operación

- Contrato interno `recommend(cliente_id)`.
- Consulta histórica reproducible con `recommend_as_of(cliente_id, fecha)`.
- API FastAPI para recomendación, batch, feedback, funnel y métricas.
- Procesamiento vectorizado de los 100,000 clientes.
- Persistencia SQLite de decisiones, candidatos, versiones, feedback y eventos del funnel.
- Incorporación del rechazo operacional al cooldown de recomendaciones futuras.
- Simulación aislada, recorrido de rechazo reproducible y escenarios económicos.
- Renderizador LLM opcional, validado y fuera del ranking.
- Model card y reportes JSON versionados.
- Mesa comercial Streamlit final para búsqueda, recomendación, guion, contexto, feedback, activación y recálculo closed-loop.

## 4. Resultado real del entrenamiento

La versión `nbo_v2` evaluó CatBoost frente a baselines y aplicó el criterio de fallback honesto. Ninguno de los tres modelos CatBoost demostró una mejora suficiente para ser activado.

| Tarea | Método activo | Resultado principal en test |
|---|---|---|
| Contactabilidad | Tasa jerárquica calibrada | ROC-AUC 0.4965; Brier 0.1309 |
| Aceptación | Tasa jerárquica calibrada | ROC-AUC 0.5277; Brier 0.2343 |
| Motivo de rechazo | Prior jerárquico | Accuracy 34.95%; Top-2 54.85% |

Esto significa que el motor no presenta CatBoost como superior cuando los datos no lo respaldan. Las probabilidades provienen de tasas suavizadas por historial y segmento, mientras que la personalización final se completa mediante reglas, ajuste cliente–oferta y ranking.

El suavizado bayesiano seleccionado en validación utiliza `alpha=50`.

## 5. Evaluación final del ranking

La evaluación se realizó sobre el test reservado, utilizando para cada evento solo meses completos anteriores a su fecha.

| Métrica | Motor NBO | Mejor baseline |
|---|---:|---:|
| Hit@1 | 10.96% | 10.52% |
| Hit@3 | 33.65% | 31.19% |
| NDCG@3 | 0.2376 | 0.2216 |

Resultados adicionales:

- Casos aceptados considerados: 9,077.
- Casos elegibles evaluables: 7,444.
- Cobertura de evaluación: 82.0%.
- Mejora relativa de NDCG@3: **7.24%** frente al mejor baseline.
- Gate final del ranking: **aprobado**.
- Ofertas diferentes presentes como Top 1: 16.
- Concentración máxima de una oferta en test: 27.2%.

## 6. Resultados Movistar Total

- Captura de clientes elegibles MT: 100%.
- Participación MT en las recomendaciones Top 1 del batch: 13.7%.
- Clientes a quienes falta internet hogar: 100% recibe como Top 1 un producto que completa esa ruta.
- Clientes a quienes falta móvil postpago: 100% recibe como Top 1 un plan móvil que completa esa ruta.
- Clientes que ya poseen MT no reciben una nueva adquisición MT.

Las metas de participación MT indicadas por el desafío se conservan como referencias de negocio. No se presentan como impacto causal ni como ventas reales obtenidas.

## 7. Procesamiento de los 100,000 clientes

La corrida masiva final produjo `artifacts/recomendaciones.csv` con estos resultados:

- Clientes solicitados: 100,000.
- Clientes procesados: 100,000.
- Cobertura: 100%.
- Errores: 0.
- Duración: aproximadamente 163 segundos.
- Latencia vectorizada p50: 1.46 ms por cliente.
- Latencia vectorizada p95: 1.51 ms por cliente.
- Cobertura del catálogo en Top 1: 15 de 22 ofertas.
- Concentración máxima de una oferta: 30.4%.

La consulta individual enriquecida, incluyendo trace, confianza, playbook y persistencia, registró en la verificación final un p95 caliente cercano a 206 ms y un máximo observado de 233 ms.

## 8. Trazabilidad

SQLite registra:

- Versiones del modelo.
- Decisiones individuales y masivas.
- Candidatos mostrados y ranking.
- Probabilidades y scores.
- Eventos del funnel.
- Feedback final y rebate.
- Plan post-rechazo generado a partir del motivo realmente observado.

El funnel admite la secuencia:

```text
classified → displayed → contacted → negotiated
           → rebate_used → accepted/rejected
```

Los eventos pueden almacenar canal, oferta, medio probatorio y referencia opcional de evidencia.

## 9. Calidad y pruebas

Al corte de este informe, la suite vigente contiene **31 pruebas automatizadas**, todas aprobadas. Cubre:

- Contrato y calidad de datos.
- Nulos semánticos y sentinel de datos ilimitados.
- Prevención de leakage mensual.
- Reproducibilidad de splits.
- Reglas de elegibilidad y ruta MT.
- Cooldown, scoring y Top 3.
- Equivalencia entre reglas escalares y vectorizadas.
- Entrenamiento mínimo y carga de artefactos.
- API, feedback, funnel y persistencia.
- Preservación de la ruta MT al seleccionar alternativas post-rechazo.
- Adaptación del playbook por canal y cumplimiento de guardrails comerciales.
- Trazabilidad del score, confianza, simulación, experimentación, economía y fallback LLM.

También se verificó sobre el batch final que no aparecen productos actuales, ofertas MT inválidas, roaming sin móvil, upgrades incompatibles ni paquetes adicionales para clientes sin servicios.

La API, la carga de artefactos, la recomendación Top 3 y su persistencia también fueron verificadas de extremo a extremo. La única advertencia de pruebas es una deprecación de la librería de testing, sin impacto funcional.

## 10. Archivos principales

| Ruta | Contenido |
|---|---|
| `src/nbo/` | Código del motor, entrenamiento, reglas, API y evaluación |
| `config/default.yaml` | Semilla, versiones, gates, pesos y cooldowns |
| `artifacts/nbo_v2/metadata.json` | Experimentos y métricas completas |
| `artifacts/nbo_v2/MODEL_CARD.md` | Resumen técnico y limitaciones |
| `artifacts/evaluation_v2.json` | Evaluación final del ranking |
| `artifacts/recomendaciones.csv` | Top 1 para los 100,000 clientes |
| `artifacts/recomendaciones.report.json` | Rendimiento y distribución del batch |
| `artifacts/nbo.sqlite3` | Trazabilidad de decisiones y funnel |

## 11. Limitaciones actuales

- Los perfiles de clientes resumen seis meses y no son snapshots mensuales perfectos.
- La información histórica tiene poca capacidad para predecir individualmente contacto, aceptación y rechazo; por eso se utilizan fallbacks jerárquicos.
- La evaluación observacional refleja la política comercial pasada y no demuestra causalidad o uplift.
- El precio normalizado es solo un proxy de valor de negocio, porque no existe margen en el dataset.
- No existe un target válido para churn ni para éxito de rebate.
- El mecanismo de feedback está implementado, pero aún no contiene resultados comerciales reales; por tanto, no hay validación online ni medición causal del impacto.
- Faltan endurecimiento productivo, autenticación, monitoreo y despliegue en infraestructura real.
- La Mesa comercial está orientada al flujo del asesor; autenticación, roles y despliegue corporativo continúan pendientes.

## 12. Valor agregado operativo

El motor implementa **Next Best Action hacia Movistar Total**: además de elegir oferta y canal, declara si debe convertir directamente a MT, completar primero hogar o móvil, profundizar la relación de un cliente que ya tiene MT o presentar la mejor oferta compatible.

Cada decisión incorpora un playbook con apertura, pregunta de descubrimiento, argumento basado en razones del ranking, beneficio verificable, cierre, tratamiento de objeción y restricciones de comunicación. El texto es determinista y utiliza únicamente catálogo, reglas y evidencia de la decisión.

Si ocurre un rechazo, genera una acción trazable según el motivo, aplica cooldown y propone un tier inferior solo cuando continúa siendo elegible y conserva la ruta MT. Un rechazo registrado afecta inmediatamente las recomendaciones posteriores sin alterar las evaluaciones históricas.

Para demostrar potencial, el motor permite comparar escenarios sin modificar el estado real, recorrer un rechazo completo, transparentar cada componente del score y estimar valor económico bajo supuestos claramente identificados. El experimento A/B prepara el aprendizaje futuro del playbook. Un LLM compatible con OpenAI puede reformular el speech, pero está apagado por defecto, no decide la oferta y vuelve al texto determinista ante cualquier incumplimiento.

## 13. Estado de entrega y pendientes

| Frente | Estado |
|---|---|
| Datos, features, modelos, reglas y ranking | Completo y validado offline |
| Batch de 100,000 clientes | Completo, sin errores |
| API, trazabilidad y persistencia | Completo para demo técnica |
| Pruebas, model card y reportes | Completo |
| Frontend y dashboard final | Completo para uso local del asesor |
| Piloto con feedback real | Pendiente |
| Despliegue y controles de producción | Pendiente |

La demo del motor ya puede reproducirse con `CLI000013` (elegible MT), `CLI000001` (ruta hacia MT) y `CLI000018` (ya posee MT).

No forman parte del MVP actual churn, uplift, clustering ni RAG. El LLM existe únicamente como renderizador opcional; no participa en el scoring ni en la decisión.

## 14. Conclusión

El núcleo del proyecto está completo y operativo para la entrega técnica. El motor procesa todo el universo de clientes, respeta las reglas comerciales, supera los baselines de ranking, prioriza correctamente Movistar Total y su ruta previa, genera respuestas trazables y cumple el objetivo local de latencia.

La decisión técnica más importante es transparente: los modelos supervisados complejos no demostraron suficiente ventaja individual, por lo que la versión final utiliza probabilidades jerárquicas calibradas junto con un ranking personalizado, reglas y features comerciales. Este enfoque es más defendible que presentar un modelo complejo sin mejora comprobada.

La siguiente fase recomendada es desplegar la Mesa comercial con autenticación, roles, observabilidad y pruebas de usabilidad con asesores reales, manteniendo congelada la lógica del motor durante la validación.
