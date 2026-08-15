# Movistar Next Best Offer

Motor reproducible de Next Best Offer con reglas comerciales, ranking auditable, estado operacional closed-loop y una Mesa local para el asesor.

La versión activa conserva los contratos `nbo_v2`, `features_v2`, `rules_v5`, `playbook_v2`, `decision_v4` y la API FastAPI pública `1.5.0`. La interfaz del asesor funciona directamente sobre el motor local: no necesita iniciar FastAPI ni conectarse a internet.

## Inicio rápido

Requiere Python 3.11.

```powershell
python -m pip install -r requirements-dev.lock
python -m pip install -e . --no-deps
nbo-check
nbo-advisor
```

La mesa escucha exclusivamente en `http://127.0.0.1:5000` y abre el navegador. Para evitar la apertura automática o elegir otro puerto:

```powershell
nbo-advisor --no-browser
nbo-advisor --port 5050
```

La página acepta enlaces directos como `http://127.0.0.1:5000/?cliente_id=CLI000013`.

## Mesa del asesor

La aplicación Flask abre directamente en la búsqueda. Cada consulta genera y persiste una decisión trazable, y muestra:

- oferta principal, precio, canal, momento, prioridad, probabilidades, score y siguiente paso;
- contexto vigente, productos activos, facturación, uso, alertas y eventos recientes;
- guion, objeciones, razones, precauciones, alternativas, rebate y trazabilidad técnica;
- contacto, feedback, aceptación pendiente, activación con evidencia y recálculo inmediato.

La aceptación registra intención y no cambia los productos. Solo una activación posterior, con evidencia y control optimista de versión, modifica el estado. Cliente, oferta, canal y versión se recuperan de la decisión en SQLite; no se confía en identificadores enviados por el formulario.

La interfaz permite alternar entre tema claro y oscuro, y usa Jinja autoescapado, Flask-WTF/CSRF, CSP local y HTMX 2.0.10 vendorizado. No usa CDN, Node ni `localStorage` para historial HTMX.

Capturas reales: [estado vacío](assets/screenshots/advisor-empty.png), [cliente encontrado](assets/screenshots/advisor-found.png), [rechazo](assets/screenshots/advisor-rejection.png) y [activación](assets/screenshots/advisor-activation.png). La regeneración está descrita en [docs/capturas_asesor.md](docs/capturas_asesor.md).

## Motor y datos

El motor usa los archivos maestros de `dataset/`:

| Fuente | Registros | Uso |
|---|---:|---|
| `dataset_clientes.csv` | 100,000 | Perfil, servicios, consumo y facturación |
| `catalogo_ofertas_entrega.csv` | 22 | Portafolio y atributos comerciales |
| `historial_campanias.csv` | 300,112 | Contactabilidad, aceptación y rechazo |

Los modelos entrenados viven en `artifacts/nbo_v2`; `artifacts/current.json` selecciona el champion. La base operacional predeterminada es `artifacts/nbo.sqlite3` y se crea automáticamente.

Comandos principales:

```powershell
nbo-train
nbo-evaluate
nbo-evaluate-v3 --max-events 50 --bootstrap-iterations 20
nbo-batch --help
nbo-report --help
nbo-audit --help
nbo-check
```

La evaluación v3 y los reportes técnicos permanecen en `reports/` y `docs/`. La simulación no visual sigue disponible mediante el motor y FastAPI.

## API FastAPI 1.5.0

La API es opcional para la Mesa, pero sus contratos públicos continúan disponibles:

```powershell
uvicorn nbo.api:app --host 127.0.0.1 --port 8000
```

Endpoints principales:

| Método y ruta | Propósito |
|---|---|
| `GET /health` | Estado y versiones |
| `POST /api/v1/nbo/recommend` | Generar una NBO |
| `POST /api/v1/nbo/batch` | Recomendación por lote |
| `POST /api/v1/nbo/feedback` | Registrar resultado |
| `POST /api/v1/nbo/events` | Registrar funnel |
| `POST /api/v1/nbo/customer-events` | Modificar estado validado |
| `GET /api/v1/nbo/customer-state/{cliente_id}` | Reconstruir estado |
| `GET /api/v1/nbo/decisions/{decision_id}` | Recuperar trazabilidad |
| `POST /api/v1/nbo/simulate` | Simulación aislada |
| `POST /api/v1/nbo/demo/journey` | Recorrido no visual reproducible |

## Arquitectura

```text
CSV maestros + artefactos nbo_v2
              │
              ▼
     NBOEngine + rules_v5
              │
       LocalAdvisorApi
              │
      Flask + Jinja + HTMX ───► navegador local
              │
              ▼
 SQLite: decisiones, funnel, feedback y ledger append-only
              │
              └───────────────► nueva NBO después de activar/rechazar

FastAPI 1.5.0 ──► contrato opcional e independiente
```

El `NBOEngine` es una única instancia persistente por proceso de la mesa. Las rutas no replican reglas comerciales: delegan en `LocalAdvisorApi` y en los esquemas Pydantic existentes.

## Pruebas y quality gate

```powershell
python -m pytest
python -m nbo.bootstrap
python -m nbo.evaluation_v3 --max-events 50 --bootstrap-iterations 20 --output-dir artifacts/ci-evaluation
```

La suite incluye motor, reglas, persistencia, FastAPI, Flask/HTMX, seguridad, closed-loop, comando local y búsqueda caliente p95 menor a un segundo. GitHub Actions ejecuta esas mismas comprobaciones.

## Solución de problemas

**El motor aparece como no disponible.** Ejecuta `nbo-check`. Confirma los tres CSV, `artifacts/current.json` y los archivos de `artifacts/nbo_v2/`.

**El comando `nbo-advisor` no existe.** Reinstala el proyecto editable con `python -m pip install -e . --no-deps`.

**El puerto 5000 está ocupado.** Ejecuta `nbo-advisor --port 5050`.

**Un formulario devuelve CSRF 400.** Recarga la página; el token pertenece a la sesión local actual.

**La activación devuelve 409.** La decisión fue calculada sobre una versión anterior del estado. Vuelve a consultar el cliente y opera sobre la nueva decisión.

**La activación devuelve 422.** Confirma que exista aceptación previa y que la orden o constancia no esté vacía.

**Necesito reiniciar solo una demostración local.** Detén la mesa y elimina únicamente la base SQLite que hayas usado. No elimines `artifacts/nbo_v2` ni `artifacts/current.json`.

## Alcance

La mesa asume un asesor por proceso, ejecución local en loopback y ausencia de autenticación en esta fase. CSRF, CSP y el aislamiento `127.0.0.1` son obligatorios. El estado fuente de los eventos de la interfaz permanece como `advisor_dashboard` para conservar las métricas históricas.
