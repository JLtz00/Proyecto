from __future__ import annotations

import html
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from nbo.advisor_ui import (
    AdvisorApi, AdvisorApiError, AdvisorContext, alternative_rows, confidence_summary,
    label_event, label_objective, label_rejection, label_stage, money, percentage,
    service_summary,
)
from nbo.advisor_local import LocalAdvisorApi


st.set_page_config(
    page_title="Mesa comercial · NBO",
    page_icon="M",
    layout="wide",
    initial_sidebar_state="expanded",
)


THEME = """
<style>
:root {
    --bg: #0b1015;
    --surface: #111820;
    --surface-soft: #151e27;
    --line: #26323d;
    --line-soft: #1d2730;
    --text: #edf1f4;
    --muted: #93a0aa;
    --accent: #79a99d;
    --accent-soft: #172824;
    --warning: #c6a36a;
    --danger: #c27d7d;
}

html, body, [class*="css"], .stApp {
    font-family: Inter, ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}

.stApp { background: var(--bg); color: var(--text); }
[data-testid="stHeader"], [data-testid="stToolbar"], footer { display: none; }
[data-testid="stAppViewContainer"] > .main { background: var(--bg); }
.block-container { max-width: 1440px; padding: 2rem 2.4rem 4rem; }

[data-testid="stSidebar"] {
    background: #0e151b;
    border-right: 1px solid var(--line-soft);
}
[data-testid="stSidebar"] .block-container { padding: 1.6rem 1.2rem; }

h1, h2, h3, p { color: var(--text); }
h1 { letter-spacing: -.035em; font-size: 2rem !important; font-weight: 650 !important; }
h2 { letter-spacing: -.02em; }

.brand { margin: .15rem 0 1.7rem; }
.brand-mark {
    display: inline-flex; align-items: center; justify-content: center;
    width: 32px; height: 32px; border: 1px solid #46665f; border-radius: 8px;
    color: #a9c7bf; font-weight: 750; margin-right: .65rem;
}
.brand-name { font-size: .96rem; font-weight: 650; color: var(--text); }
.brand-copy { color: var(--muted); font-size: .76rem; margin: .65rem 0 0; line-height: 1.5; }

.connection {
    border-top: 1px solid var(--line-soft); padding-top: 1rem; margin-top: 1.2rem;
    color: var(--muted); font-size: .78rem;
}
.status-dot {
    display: inline-block; width: 7px; height: 7px; border-radius: 50%;
    background: var(--accent); margin-right: .5rem;
}
.status-dot.offline { background: var(--danger); }

.eyebrow {
    color: var(--accent); font-size: .72rem; font-weight: 700;
    letter-spacing: .11em; text-transform: uppercase; margin-bottom: .4rem;
}
.page-subtitle { color: var(--muted); font-size: .92rem; margin-top: -.55rem; }
.section-title {
    color: var(--text); font-size: .82rem; font-weight: 700; letter-spacing: .08em;
    text-transform: uppercase; margin: 1.6rem 0 .8rem;
}
.muted { color: var(--muted); }

.context-strip {
    display: flex; align-items: center; gap: .7rem; flex-wrap: wrap;
    border-top: 1px solid var(--line); border-bottom: 1px solid var(--line);
    padding: .85rem 0; margin: 1.25rem 0 1.5rem;
}
.context-item { color: var(--muted); font-size: .81rem; }
.context-item strong { color: var(--text); font-weight: 600; }
.context-divider { color: #41505d; }
.stage-pill, .soft-pill {
    display: inline-flex; align-items: center; border: 1px solid #35534c;
    color: #b8d1ca; background: var(--accent-soft); border-radius: 999px;
    padding: .25rem .6rem; font-size: .75rem; font-weight: 600;
}
.soft-pill { border-color: var(--line); color: #bbc4cb; background: #151d24; margin: 0 .3rem .35rem 0; }

.offer-hero {
    border: 1px solid #33423f; border-left: 3px solid var(--accent);
    background: var(--surface); border-radius: 10px; padding: 1.25rem 1.35rem;
    margin-bottom: 1rem;
}
.offer-top { display: flex; justify-content: space-between; gap: 1rem; align-items: flex-start; }
.offer-id { color: var(--muted); font-size: .75rem; letter-spacing: .06em; text-transform: uppercase; }
.offer-name { font-size: 1.55rem; font-weight: 650; letter-spacing: -.025em; margin: .18rem 0 .25rem; }
.offer-price { color: #d9e2e6; font-size: 1.04rem; white-space: nowrap; }
.offer-next { color: #cbd4d9; font-size: .91rem; line-height: 1.55; margin-top: .85rem; }
.offer-next strong { color: var(--accent); font-weight: 650; }

[data-testid="stMetric"] { background: transparent; border: 0; padding: .15rem 0; }
[data-testid="stMetricLabel"] { color: var(--muted); font-size: .77rem; }
[data-testid="stMetricValue"] { color: var(--text); font-size: 1.25rem; }

[data-testid="stVerticalBlockBorderWrapper"] {
    border-color: var(--line) !important; border-radius: 10px !important;
    background: var(--surface) !important;
}

.script-line { border-bottom: 1px solid var(--line-soft); padding: .75rem 0 .9rem; }
.script-line:last-child { border-bottom: 0; }
.script-label { color: var(--muted); font-size: .72rem; text-transform: uppercase; letter-spacing: .08em; margin-bottom: .28rem; }
.script-copy { color: #e4e9ec; font-size: .93rem; line-height: 1.55; }
.why-list { margin: .4rem 0 .2rem; padding-left: 1.15rem; color: #d3dade; }
.why-list li { margin: .42rem 0; line-height: 1.45; }
.caution { color: #cfb78f; font-size: .84rem; line-height: 1.5; border-left: 2px solid #806b49; padding-left: .7rem; }

.profile-row {
    display: flex; justify-content: space-between; gap: 1rem;
    padding: .58rem 0; border-bottom: 1px solid var(--line-soft); font-size: .83rem;
}
.profile-row:last-child { border-bottom: 0; }
.profile-key { color: var(--muted); }
.profile-value { color: var(--text); text-align: right; font-weight: 550; }

.event-row { padding: .68rem 0; border-bottom: 1px solid var(--line-soft); }
.event-row:last-child { border-bottom: 0; }
.event-name { font-size: .82rem; color: var(--text); font-weight: 600; }
.event-meta { font-size: .72rem; color: var(--muted); margin-top: .22rem; }

.journey-track { display: flex; gap: .35rem; margin: 1.1rem 0 1.5rem; }
.journey-segment { height: 4px; flex: 1; background: var(--line); border-radius: 3px; }
.journey-segment.active { background: var(--accent); }
.proof-note { border-left: 2px solid var(--accent); padding: .7rem .9rem; color: #cbd4d9; background: #101920; }

.empty-state {
    max-width: 650px; padding: 4.4rem 0 2rem; margin: 0 auto; text-align: center;
}
.empty-state h2 { font-size: 1.45rem; margin-bottom: .6rem; }
.empty-state p { color: var(--muted); line-height: 1.65; }

.stButton > button, .stFormSubmitButton > button {
    border-radius: 7px; border: 1px solid #33424d; background: #17212a;
    color: #e7ecef; font-weight: 600; min-height: 2.55rem;
}
.stButton > button:hover, .stFormSubmitButton > button:hover {
    border-color: #638d83; color: #f5f8f9; background: #1a2928;
}
.stButton > button[kind="primary"], .stFormSubmitButton > button[kind="primary"] {
    background: #527e74; color: #07100e; border-color: #527e74;
}
.stButton > button[kind="primary"]:hover, .stFormSubmitButton > button[kind="primary"]:hover {
    background: #66968b; border-color: #66968b;
}

[data-baseweb="input"] > div, [data-baseweb="select"] > div,
[data-baseweb="textarea"] > div {
    background: #0f161c !important; border-color: var(--line) !important;
}
[data-baseweb="tab-list"] { gap: 1.2rem; border-bottom: 1px solid var(--line); }
[data-baseweb="tab"] { padding-left: 0; padding-right: 0; color: var(--muted); }
[aria-selected="true"][data-baseweb="tab"] { color: var(--text); }
[data-baseweb="tab-highlight"] { background-color: var(--accent); }
[data-testid="stDataFrame"] { border: 1px solid var(--line); border-radius: 8px; overflow: hidden; }
[data-testid="stExpander"] { border-color: var(--line) !important; background: transparent !important; }
[data-testid="stAlert"] { border-radius: 8px; border-width: 1px; }
hr { border-color: var(--line-soft) !important; }

@media (max-width: 900px) {
    .block-container { padding: 1.3rem 1rem 3rem; }
    .offer-top { flex-direction: column; }
}
</style>
"""
st.markdown(THEME, unsafe_allow_html=True)


def safe(value: Any) -> str:
    return html.escape(str(value if value is not None else "—"))


def section_title(value: str) -> None:
    st.markdown(f'<div class="section-title">{safe(value)}</div>', unsafe_allow_html=True)


def profile_row(label: str, value: Any) -> None:
    st.markdown(
        f'<div class="profile-row"><span class="profile-key">{safe(label)}</span>'
        f'<span class="profile-value">{safe(value)}</span></div>',
        unsafe_allow_html=True,
    )


def script_line(label: str, value: str) -> None:
    st.markdown(
        f'<div class="script-line"><div class="script-label">{safe(label)}</div>'
        f'<div class="script-copy">{safe(value)}</div></div>',
        unsafe_allow_html=True,
    )


@st.cache_resource(show_spinner=False)
def local_backend() -> LocalAdvisorApi:
    from nbo.engine import NBOEngine

    return LocalAdvisorApi(NBOEngine(persist=True))


def load_context(api: Any, cliente_id: str) -> AdvisorContext:
    normalized = cliente_id.strip().upper()
    if not normalized:
        raise AdvisorApiError("Ingresa un identificador de cliente.")
    result = api.recommend(normalized)
    state = api.customer_state(normalized)
    events = api.customer_events(normalized)
    return AdvisorContext(result=result, state=state, events=events)


def set_context(context: AdvisorContext) -> None:
    st.session_state.advisor_context = {
        "result": context.result, "state": context.state, "events": context.events,
    }
    st.session_state.active_decision = context.decision_id
    st.session_state.feedback_recorded = None
    st.session_state.recovery_action = None


def current_context() -> AdvisorContext | None:
    value = st.session_state.get("advisor_context")
    return AdvisorContext(**value) if value else None


def refresh_context(api: Any, cliente_id: str) -> None:
    set_context(load_context(api, cliente_id))


def render_guided_demo(api: Any) -> None:
    st.markdown('<div class="eyebrow">Demo aislada · 90 segundos</div>', unsafe_allow_html=True)
    st.title("De una oferta estática a una decisión que aprende")
    st.markdown(
        '<p class="page-subtitle">Recorre el ciclo completo sin modificar datos maestros ni persistir operaciones.</p>',
        unsafe_allow_html=True,
    )
    try:
        journey = api.demo_journey("CLI000001", "precio")
    except AdvisorApiError as exc:
        st.error(str(exc), icon=None)
        return

    steps = journey["steps"]
    requested = st.query_params.get("step", "0")
    try:
        index = min(max(int(requested), 0), len(steps) - 1)
    except (TypeError, ValueError):
        index = 0
    labels = {
        "initial": ("1 · Estado inicial", "Falta internet hogar; el motor prioriza completar la ruta hacia MT."),
        "accepted": ("2 · Aceptación", "Se registra intención comercial, pero los productos y la versión todavía no cambian."),
        "activated": ("3 · Activación confirmada", "La evidencia de provisión cambia el estado y habilita Movistar Total."),
        "rejected": ("4 · Rechazo por precio", "OF022 entra en cooldown y el motor evita repetir una conversación inadecuada."),
        "recontact": ("5 · Recuperación", "En la fecha permitida se conserva la ruta MT con un tier inferior."),
    }
    result_by_step = {
        "initial": journey["initial"], "accepted": journey.get("after_acceptance"),
        "activated": journey.get("after_activation"), "rejected": journey["immediate_after_rejection"],
        "recontact": journey["at_recontact"],
    }
    step = steps[index]
    result = result_by_step[step["step"]]
    title, description = labels[step["step"]]
    st.markdown(
        '<div class="journey-track">' + ''.join(
            f'<span class="journey-segment {"active" if position <= index else ""}"></span>'
            for position in range(len(steps))
        ) + '</div>', unsafe_allow_html=True,
    )
    st.markdown(f'<div class="eyebrow">{safe(title)}</div>', unsafe_allow_html=True)
    st.subheader(result["recommendation"]["nombre_oferta"])
    st.write(description)
    a, b, c, d = st.columns(4)
    a.metric("Etapa MT", label_stage(step["mt_stage"]))
    b.metric("Estado", f'v{step["state_version"]}')
    b.caption("Sin cambio" if step["step"] == "accepted" else "Versión reconstruida")
    c.metric("Oferta", result["recommendation"]["oferta_id"])
    d.metric("Canal", result["recommendation"]["canal"])
    st.markdown(
        f'<div class="proof-note"><strong>Qué demuestra:</strong> {safe(description)}</div>',
        unsafe_allow_html=True,
    )
    left, middle, right = st.columns([1, 1, 1])
    if left.button("Anterior", disabled=index == 0, width="stretch"):
        st.query_params.update({"view": "demo", "step": str(index - 1)})
        st.rerun()
    if middle.button("Reiniciar", width="stretch"):
        st.session_state.pop("advisor_context", None)
        st.query_params.update({"view": "demo", "step": "0"})
        st.rerun()
    if right.button("Siguiente", type="primary", disabled=index == len(steps) - 1, width="stretch"):
        st.query_params.update({"view": "demo", "step": str(index + 1)})
        st.rerun()
    with st.expander("Trazabilidad del paso"):
        trace = step.get("decision_trace") or result.get("decision_trace", {})
        st.json({
            "evento_que_produciria_el_cambio": journey["events_to_register"],
            "productos_cambiaron": step.get("products_changed", False),
            "decision_trace": trace,
        }, expanded=False)
    st.caption("Demo determinista y no persistente. Las cifras mostradas son estimaciones offline, no resultados comerciales reales.")


def render_impact(api: Any) -> None:
    st.markdown('<div class="eyebrow">Impacto y evidencia</div>', unsafe_allow_html=True)
    st.title("Del ofrecimiento a la activación")
    st.markdown(
        '<p class="page-subtitle">Visión ejecutiva separada del espacio operativo del asesor.</p>',
        unsafe_allow_html=True,
    )
    source_label = st.radio(
        "Fuente", ["Escenario demostrativo", "Operación local"], horizontal=True,
        help="Los datos simulados nunca se mezclan con la base operacional.",
    )
    source = "demo" if source_label == "Escenario demostrativo" else "operational"
    metrics = api.metrics(source)
    if metrics["is_simulated"]:
        st.warning(metrics["disclaimer"], icon=None)
    else:
        st.info(metrics["disclaimer"], icon=None)

    funnel = metrics["funnel"]
    cols = st.columns(5)
    for column, (label, key) in zip(cols, (
        ("Clasificados", "classified"), ("Contactados", "contacted"),
        ("Aceptados", "accepted"), ("Activados", "activated"), ("Rechazados", "rejected"),
    )):
        column.metric(label, f'{int(funnel.get(key, 0)):,}')
    funnel_frame = pd.DataFrame({
        "Etapa": ["Clasificados", "Mostrados", "Contactados", "Negociados", "Aceptados", "Activados"],
        "Clientes": [funnel.get(key, 0) for key in ("classified", "displayed", "contacted", "negotiated", "accepted", "activated")],
    }).set_index("Etapa")
    st.bar_chart(funnel_frame, color="#79a99d", horizontal=True)

    tab_mt, tab_channels, tab_objections, tab_economics, tab_evidence = st.tabs([
        "Movistar Total", "Canales", "Objeciones", "Economía", "Evidencia técnica",
    ])
    with tab_mt:
        mt = metrics["mt"]
        one, two, three = st.columns(3)
        one.metric("Recomendaciones MT", mt["recommendations"])
        two.metric("Nuevos elegibles MT", mt["customers_converted_to_eligible"])
        three.metric("NBO recalculadas", mt["recalculated_after_activation"])
        if mt.get("tier_distribution"):
            st.bar_chart(pd.Series(mt["tier_distribution"], name="Recomendaciones"), color="#79a99d")
    with tab_channels:
        channel_rows = []
        for channel, values in metrics.get("channel_performance", {}).items():
            contacted = values.get("contacted", 0)
            channel_rows.append({
                "Canal": channel, **values,
                "Conversión contacto → aceptación": values.get("accepted", 0) / contacted if contacted else 0,
            })
        if channel_rows:
            st.dataframe(pd.DataFrame(channel_rows), hide_index=True, width="stretch")
        else:
            st.caption("Aún no existe soporte operacional suficiente por canal.")
    with tab_objections:
        reasons = metrics.get("rejection_reasons", {})
        if reasons:
            st.bar_chart(pd.Series(reasons, name="Rechazos"), color="#c6a36a")
        rebate = metrics.get("rebate", {})
        if rebate:
            st.caption(f"Rebate utilizado {rebate.get('used', 0)} veces; aceptado {rebate.get('accepted', 0)} veces.")
    with tab_economics:
        presets = {
            "Conservador": {"margin_rate": .20, "expected_months": 6, "channel_costs": {"Digital": 1, "Tienda": 10, "Call In": 5, "Call Out": 8}, "rebate_cost": 12, "expected_rebate_use_rate": .30, "max_experience_penalty": 20},
            "Base": {"margin_rate": .30, "expected_months": 12, "channel_costs": {"Digital": 1, "Tienda": 8, "Call In": 4, "Call Out": 6}, "rebate_cost": 10, "expected_rebate_use_rate": .25, "max_experience_penalty": 15},
            "Optimista": {"margin_rate": .40, "expected_months": 18, "channel_costs": {"Digital": .5, "Tienda": 7, "Call In": 3, "Call Out": 5}, "rebate_cost": 8, "expected_rebate_use_rate": .20, "max_experience_penalty": 10},
        }
        scenario = st.selectbox("Escenario", list(presets), index=1)
        client = st.selectbox("Cliente de referencia", ["CLI000013", "CLI000001", "CLI000018"])
        volume = st.number_input("Volumen ilustrativo de clientes", min_value=1, max_value=100000, value=1000, step=100)
        economics = api.economics(client, presets[scenario])
        rows = [{
            "Oferta": item["nombre_oferta"], "Canal": item["canal"],
            "Ranking oficial": item["official_rank"], "Ranking económico": item["economic_rank"],
            "Valor esperado": round(item["expected_value"], 2),
        } for item in economics["economic_top3"]]
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        best_value = max((item["expected_value"] for item in economics["economic_top3"]), default=0)
        st.metric("Valor esperado ilustrativo para el volumen", money(best_value * int(volume)))
        with st.expander("Supuestos y sensibilidad"):
            st.json(presets, expanded=False)
        st.caption(economics["disclaimer"])
    with tab_evidence:
        evaluation_path = Path("reports/evaluation_v3.json")
        if evaluation_path.exists():
            report = __import__("json").loads(evaluation_path.read_text(encoding="utf-8"))
            conditioned = report["ranking_conditioned"]
            absolute = report["ranking_all_accepted_events"]
            st.write("**Ranking offline v3**")
            st.dataframe(pd.DataFrame([
                {"Universo": "Evaluables", **conditioned},
                {"Universo": "Todos los aceptados", **absolute},
            ]), hide_index=True, width="stretch")
            st.caption(
                f"Cobertura evaluable: {report['coverage']['rate']:.1%} · mejora NDCG@3 frente al mejor baseline comparable: "
                f"{report['relative_ndcg_improvement_vs_best_baseline']:.2%}. Intervalos bootstrap al 95% disponibles en el reporte versionado."
            )
        else:
            st.info("Ejecuta `python -m nbo.evaluation_v3` para generar el reporte v3.", icon=None)
        st.markdown(
            "**Lectura honesta:** CatBoost no superó los gates de calibración. El sistema activó tasas jerárquicas y concentra la personalización en elegibilidad, ajuste, canal, ruta MT y closed loop."
        )
        audit_path = Path("artifacts/nbo_v2/audit.json")
        if audit_path.exists():
            audit = __import__("json").loads(audit_path.read_text(encoding="utf-8"))
            fairness = audit.get("fairness_diagnostic", {})
            if fairness:
                st.write("**Diagnóstico responsable**")
                st.json(fairness, expanded=False)
                st.caption("Edad y ubicación se auditan descriptivamente, pero no se usan para excluir ofertas.")


with st.sidebar:
    st.markdown(
        '<div class="brand"><span class="brand-mark">M</span>'
        '<span class="brand-name">Mesa comercial</span>'
        '<p class="brand-copy">Asistente de decisión para conversaciones relevantes, trazables y oportunas.</p></div>',
        unsafe_allow_html=True,
    )
    public_demo = os.getenv("NBO_PUBLIC_DEMO", "false").lower() in {"1", "true", "yes"}
    requested_view = str(st.query_params.get("view", "demo"))
    view_options = ["Demo guiada", "Impacto y evidencia"]
    if not public_demo:
        view_options.insert(1, "Mesa del asesor")
    view_map = {"demo": "Demo guiada", "advisor": "Mesa del asesor", "impact": "Impacto y evidencia"}
    default_view = view_map.get(requested_view, "Demo guiada")
    if default_view not in view_options:
        default_view = "Demo guiada"
    selected_view = st.radio(
        "Vista", view_options, index=view_options.index(default_view),
        help="La demo pública es aislada; la Mesa del asesor conserva persistencia solo en entornos controlados.",
    )
    selected_slug = {"Demo guiada": "demo", "Mesa del asesor": "advisor", "Impacto y evidencia": "impact"}[selected_view]
    if requested_view != selected_slug:
        st.query_params.update({"view": selected_slug})
    with st.expander("Conexión", expanded=False):
        connection_mode = st.radio(
            "Origen", ["Motor local", "API remota"], horizontal=True,
            help="El motor local funciona sin iniciar Uvicorn.",
        )
        api_url = "http://127.0.0.1:8000"
        if connection_mode == "API remota":
            api_url = st.text_input("URL del motor", api_url)
    try:
        api = local_backend() if connection_mode == "Motor local" else AdvisorApi(api_url, timeout=4)
        health = api.health()
        online = health.get("status") == "ok"
        source_label = "local" if connection_mode == "Motor local" else "remoto"
        status_text = f"Motor {source_label} activo · {health.get('model_version', 'NBO')}"
        if connection_mode == "API remota" and health.get("api_version") != "1.5.0":
            online = False
            status_text = "API incompatible · se requiere 1.5.0"
    except Exception:
        online = False
        status_text = "Motor no disponible"
        api = AdvisorApi(api_url, timeout=4)
    dot_class = "status-dot" if online else "status-dot offline"
    st.markdown(
        f'<div class="connection"><span class="{dot_class}"></span>{safe(status_text)}</div>',
        unsafe_allow_html=True,
    )
    st.markdown("<br>", unsafe_allow_html=True)
    if selected_view == "Mesa del asesor":
        st.caption("Casos de referencia")
        for example_id, description in (
            ("CLI000001", "Completar hogar"),
            ("CLI000013", "Elegible MT"),
            ("CLI000018", "Cliente MT"),
        ):
            if st.button(f"{example_id}  ·  {description}", key=f"example_{example_id}", width="stretch"):
                try:
                    with st.spinner("Reconstruyendo contexto…"):
                        refresh_context(api, example_id)
                except AdvisorApiError as exc:
                    st.session_state.flash_error = str(exc)
                st.rerun()


if selected_view == "Demo guiada":
    render_guided_demo(api)
    st.stop()
if selected_view == "Impacto y evidencia":
    render_impact(api)
    st.stop()


st.markdown('<div class="eyebrow">Espacio del asesor</div>', unsafe_allow_html=True)
st.title("Siguiente mejor conversación")
st.markdown(
    '<p class="page-subtitle">Una recomendación accionable, con contexto y registro comercial en el mismo lugar.</p>',
    unsafe_allow_html=True,
)

with st.form("customer_search", border=False):
    search_col, button_col = st.columns([5, 1.2], vertical_alignment="bottom")
    with search_col:
        default_id = current_context().cliente_id if current_context() else ""
        client_id = st.text_input(
            "Cliente", value=default_id, placeholder="Ej. CLI000001",
            help="Consulta el perfil vigente y genera una nueva decisión trazable.",
        )
    with button_col:
        search = st.form_submit_button("Consultar cliente", type="primary", width="stretch")

if search:
    try:
        with st.spinner("Analizando perfil, elegibilidad e historial…"):
            set_context(load_context(api, client_id))
    except AdvisorApiError as exc:
        st.session_state.flash_error = str(exc)

if st.session_state.pop("flash_success", None):
    st.success(st.session_state.pop("flash_success_text", "Acción registrada correctamente."), icon=None)
if error_message := st.session_state.pop("flash_error", None):
    st.error(error_message, icon=None)

context = current_context()
if context is None:
    st.markdown(
        '<div class="empty-state"><div class="eyebrow">Comienza con un cliente</div>'
        '<h2>Todo el contexto comercial, sin ruido</h2>'
        '<p>Busca un identificador para ver la oferta prioritaria, el guion recomendado, '
        'las objeciones probables, el estado vigente y las acciones de seguimiento.</p></div>',
        unsafe_allow_html=True,
    )
    st.stop()


result = context.result
customer = result["cliente"]
top = result["recommendation"]
strategy = result["commercial_strategy"]
playbook = result["sales_playbook"]
confidence = result["evidence_confidence"]
state = context.state
attributes = state.get("attributes", {})

st.markdown(
    '<div class="context-strip">'
    f'<span class="stage-pill">{safe(label_stage(customer["etapa_mt"]))}</span>'
    f'<span class="context-item">Cliente <strong>{safe(context.cliente_id)}</strong></span>'
    '<span class="context-divider">·</span>'
    f'<span class="context-item">Objetivo <strong>{safe(label_objective(strategy["objective"]))}</strong></span>'
    '<span class="context-divider">·</span>'
    f'<span class="context-item">Estado <strong>v{context.state_version}</strong></span>'
    '<span class="context-divider">·</span>'
    f'<span class="context-item">{safe(confidence_summary(confidence))}</span>'
    '</div>',
    unsafe_allow_html=True,
)

main_col, side_col = st.columns([1.75, 1], gap="large")

with main_col:
    st.markdown(
        '<div class="offer-hero"><div class="offer-top"><div>'
        f'<div class="offer-id">Acción recomendada · {safe(top["oferta_id"])}</div>'
        f'<div class="offer-name">{safe(top["nombre_oferta"])}</div>'
        f'<span class="soft-pill">{safe(top["canal"])}</span>'
        f'<span class="soft-pill">{safe(top["momento"]["momento"].replace("_", " ").capitalize())}</span>'
        f'<span class="soft-pill">Prioridad {safe(top["momento"]["urgencia"])}</span>'
        '</div>'
        f'<div class="offer-price">{safe(money(top["precio_mensual"]))} / mes</div></div>'
        f'<div class="offer-next"><strong>Siguiente paso:</strong> {safe(strategy["next_step"])}</div></div>',
        unsafe_allow_html=True,
    )
    timing = top["momento"]
    if timing.get("recommended_weekday") or timing.get("recommended_date"):
        timing_text = " · ".join(filter(None, [
            timing.get("recommended_weekday", "").capitalize(), timing.get("recommended_date"),
        ]))
        st.caption(
            f"Próxima oportunidad: {timing_text} · base {timing.get('basis', 'operacional')} · "
            f"soporte {timing.get('support', 0)} · confianza {timing.get('confidence', 'baja')}."
        )

    metric_cols = st.columns(4)
    metric_cols[0].metric("Contacto", percentage(top["probabilidad_contacto"]), help="Probabilidad estimada de lograr contacto.")
    metric_cols[1].metric(
        "Propensión contextual", percentage(top["probabilidad_aceptacion"]),
        help=f"Condicionada al contacto · soporte {confidence['level']} ({confidence['relevant_support']} observaciones relevantes).",
    )
    metric_cols[2].metric("Venta estimada", percentage(top["probabilidad_venta"]), help="Contacto por aceptación; no es una garantía.")
    metric_cols[3].metric("Ajuste interno", f'{top["score"]:.2f}', help="Score de ranking; no debe comunicarse al cliente.")

    tab_script, tab_why, tab_alt, tab_detail = st.tabs([
        "Guion de conversación", "Por qué esta acción", "Alternativas", "Detalle del modelo",
    ])

    with tab_script:
        section_title("Conversación sugerida")
        script_line("Apertura", playbook["opening"])
        script_line("Pregunta de descubrimiento", playbook["discovery_question"])
        script_line("Argumento principal", playbook["main_argument"])
        script_line("Beneficio verificable", playbook["verified_benefit"])
        script_line("Cierre", playbook["close"])
        st.text_area(
            "Guion listo para usar", playbook["suggested_script"], height=130,
            help="Selecciona el texto para copiarlo al canal de atención.",
        )

        section_title("Si aparece una objeción")
        objections = result.get("rejection_prediction", [])
        for objection in objections:
            left, right = st.columns([4, 1])
            left.markdown(f"**{label_rejection(objection['motivo'])}**")
            right.markdown(f"<span class='muted'>{percentage(objection['probability'])}</span>", unsafe_allow_html=True)
        script_line("Respuesta sugerida", playbook["objection_response"])
        st.markdown(
            f'<div class="caution">{safe(playbook["post_rejection_guidance"])}</div>',
            unsafe_allow_html=True,
        )

    with tab_why:
        section_title("Evidencia a favor")
        positives = top.get("explanation", {}).get("positive", [])
        st.markdown(
            '<ul class="why-list">' + ''.join(f'<li>{safe(item)}</li>' for item in positives) + '</ul>',
            unsafe_allow_html=True,
        )
        negatives = top.get("explanation", {}).get("negative", [])
        if negatives:
            section_title("Precauciones")
            for item in negatives:
                st.markdown(f'<div class="caution">{safe(item)}</div><br>', unsafe_allow_html=True)
        section_title("Valor para la conversación")
        script_line("Para el cliente", top["beneficio_cliente"])
        script_line("Para el negocio", top["beneficio_negocio"])
        script_line("Razonamiento comercial", strategy["rationale"])

    with tab_alt:
        section_title("Opciones de respaldo elegibles")
        alternatives = alternative_rows(result.get("alternatives", []))
        if alternatives:
            st.dataframe(
                pd.DataFrame(alternatives), hide_index=True, width="stretch",
                column_config={"Motivo principal": st.column_config.TextColumn(width="large")},
            )
        else:
            st.info("No hay otras ofertas elegibles para este estado.", icon=None)
        rebate = result["rebate"]
        section_title("Ruta de rebate")
        script_line("Estrategia", rebate["strategy"].replace("_", " ").capitalize())
        script_line("Cómo presentarla", rebate["speech"])
        if rebate.get("alternative_offer_id"):
            st.caption(f"Alternativa sugerida: {rebate['alternative_offer_id']}")

    with tab_detail:
        section_title("Soporte de la decisión")
        profile_row("Nivel", confidence["level"].capitalize())
        profile_row("Eventos del cliente", confidence["client_events"])
        profile_row("Exposiciones a la oferta", confidence["client_offer_exposures"])
        profile_row("Contactos por canal", confidence["client_channel_contacts"])
        profile_row("Fuente contacto", confidence["contact_source"])
        profile_row("Fuente aceptación", confidence["acceptance_source"])
        st.caption(confidence["warning"])

        with st.expander("Trazabilidad de ranking"):
            trace = result["decision_trace"]
            profile_row("Pares evaluados", trace["total_offer_channel_pairs"])
            profile_row("Pares elegibles", trace["eligible_offer_channel_pairs"])
            profile_row("Pares bloqueados", trace["blocked_offer_channel_pairs"])
            st.caption(trace["selection_reason"])
            st.json({
                "bloqueos": trace["blocked_by_reason"],
                "componentes_top": trace["top_score_breakdown"],
            }, expanded=False)
        with st.expander("Versiones y auditoría"):
            profile_row("Decisión", result["decision_id"])
            profile_row("Esquema", result["decision_schema_version"])
            profile_row("Versión de estado", result["state_version"])
            profile_row("Estado calculado en", result.get("state_as_of", "—"))
            st.json({
                "versions": result["versions"],
                "eventos_estado": result.get("applied_state_event_ids", []),
                "experimento_playbook": result["playbook_experiment"],
            }, expanded=False)

with side_col:
    section_title("Contexto del cliente")
    services = service_summary(customer, state)
    st.markdown(
        ''.join(f'<span class="soft-pill">{safe(service)}</span>' for service in services),
        unsafe_allow_html=True,
    )
    profile_row("Tipo", str(attributes.get("tipo_cliente", customer["tipo_cliente"])).capitalize())
    profile_row("Plan móvil", attributes.get("plan_actual_id", customer["plan_actual_id"]))
    profile_row("Facturación promedio", money(attributes.get("monto_facturado_prom", customer["monto_facturado_prom"])))
    profile_row("Consumo de datos", f'{float(attributes.get("consumo_datos_gb_prom", customer["consumo_datos_gb_prom"])):.1f} GB')
    profile_row("Canal habitual", attributes.get("canal_mas_usado", customer["canal_mas_usado"]))
    profile_row("Reclamos", attributes.get("n_reclamos", customer["n_reclamos"]))
    profile_row("Meses con mora", attributes.get("meses_moroso", customer["meses_moroso"]))
    profile_row("Ofertas activas", ", ".join(state.get("active_offer_ids", [])) or "Ninguna")

    with st.expander("Ver perfil completo"):
        full_profile = {
            str(key).replace("_", " ").capitalize(): str(value)
            for key, value in attributes.items()
            if key != "cliente_id"
        }
        st.dataframe(
            pd.DataFrame(full_profile.items(), columns=["Dato", "Valor"]),
            hide_index=True, width="stretch",
        )

    section_title("Registrar interacción")
    with st.container(border=True):
        contact_key = f"contact_{context.decision_id}"
        if not st.session_state.get(contact_key):
            st.caption("Registra el contacto antes de capturar el resultado final.")
            if st.button("Marcar contacto iniciado", key=f"start_{context.decision_id}", width="stretch"):
                try:
                    for event_type in ("displayed", "contacted"):
                        payload = {
                            "decision_id": context.decision_id, "event_type": event_type,
                            "oferta_id": context.offer_id, "canal": top["canal"],
                        }
                        if event_type == "contacted":
                            payload["medio_probatorio"] = "registro_plataforma"
                            payload["evidencia_referencia"] = "advisor_dashboard"
                        try:
                            api.save_funnel_event(payload)
                        except AdvisorApiError as exc:
                            if exc.status_code != 422 or "ya fue registrado" not in str(exc):
                                raise
                    st.session_state[contact_key] = True
                    st.session_state.flash_success = True
                    st.session_state.flash_success_text = "Contacto iniciado y trazado."
                    st.rerun()
                except AdvisorApiError as exc:
                    st.error(str(exc), icon=None)
        else:
            st.caption("Contacto iniciado · listo para registrar resultado")

        feedback_state = st.session_state.get("feedback_recorded")
        if feedback_state is None:
            with st.form(f"feedback_{context.decision_id}"):
                outcome = st.radio(
                    "Resultado", ["Aceptada", "Rechazada", "No contactado"],
                    index=None, horizontal=True,
                )
                reason = None
                if outcome == "Rechazada":
                    reason_label = st.selectbox("Motivo", list({
                        "Precio": "precio", "No lo necesita": "no_necesita",
                        "Ya tiene algo similar": "ya_tiene_similar",
                        "No es un buen momento": "mal_momento",
                        "Necesita más confianza": "no_confia", "Otro": "otro",
                    }))
                    reason = {
                        "Precio": "precio", "No lo necesita": "no_necesita",
                        "Ya tiene algo similar": "ya_tiene_similar",
                        "No es un buen momento": "mal_momento",
                        "Necesita más confianza": "no_confia", "Otro": "otro",
                    }[reason_label]
                proof_label = st.selectbox(
                    "Evidencia", ["Registro en plataforma", "Chat", "Audio de llamada"],
                )
                rebate_used = False
                rebate_result = None
                if outcome in {"Aceptada", "Rechazada"}:
                    rebate_used = st.checkbox("Se utilizó la propuesta de rebate")
                    if rebate_used:
                        rebate_label = st.radio(
                            "Resultado del rebate", ["Aceptado", "Rechazado"],
                            index=None, horizontal=True,
                        )
                        if rebate_label is not None:
                            rebate_result = "aceptada" if rebate_label == "Aceptado" else "rechazada"
                submitted = st.form_submit_button("Guardar resultado", width="stretch")
            if submitted:
                if outcome is None:
                    st.warning("Selecciona un resultado antes de guardar.", icon=None)
                elif rebate_used and rebate_result is None:
                    st.warning("Selecciona el resultado del rebate.", icon=None)
                else:
                    final_map = {
                        "Aceptada": "aceptada", "Rechazada": "rechazada",
                        "No contactado": "no_contactado",
                    }
                    proof_map = {
                        "Registro en plataforma": "registro_plataforma",
                        "Chat": "chat_log", "Audio de llamada": "audio_llamada",
                    }
                    payload = {
                        "decision_id": context.decision_id,
                        "resultado_final": final_map[outcome],
                        "medio_probatorio": proof_map[proof_label],
                        "rebate_usado": rebate_used,
                    }
                    if reason:
                        payload["motivo_rechazo"] = reason
                    if rebate_used:
                        payload["resultado_rebate"] = rebate_result
                    try:
                        response = api.save_feedback(payload)
                        st.session_state.feedback_recorded = (
                            "aceptada" if rebate_result == "aceptada" else final_map[outcome]
                        )
                        st.session_state.recovery_action = response.get("post_rejection_action")
                        st.rerun()
                    except AdvisorApiError as exc:
                        st.error(str(exc), icon=None)
        elif feedback_state == "aceptada":
            st.success("Aceptación registrada. Los servicios aún no cambiaron.", icon=None)
            with st.form(f"activation_{context.decision_id}"):
                evidence_reference = st.text_input(
                    "Orden o constancia de activación", placeholder="Ej. ORDER-2026-001",
                )
                activate = st.form_submit_button(
                    "Confirmar activación", type="primary", width="stretch",
                )
            if activate:
                if not evidence_reference.strip():
                    st.warning("Ingresa la referencia de activación.", icon=None)
                else:
                    activation_payload = {
                        "cliente_id": context.cliente_id,
                        "event_type": "product_activated",
                        "effective_at": datetime.now(timezone.utc).isoformat(),
                        "source": "advisor_dashboard",
                        "idempotency_key": f"advisor:{context.decision_id}:{context.offer_id}:{evidence_reference.strip()}",
                        "expected_state_version": context.state_version,
                        "oferta_id": context.offer_id,
                        "decision_id": context.decision_id,
                        "evidence_type": "registro_plataforma",
                        "evidence_reference": evidence_reference.strip(),
                    }
                    try:
                        response = api.activate_product(activation_payload)
                        if response.get("recommendation"):
                            new_result = response["recommendation"]
                            new_state = response["new_state"]
                            new_events = api.customer_events(context.cliente_id)
                            set_context(AdvisorContext(new_result, new_state, new_events))
                        st.session_state.flash_success = True
                        st.session_state.flash_success_text = (
                            "Producto activado. La siguiente mejor acción fue recalculada."
                        )
                        st.rerun()
                    except AdvisorApiError as exc:
                        st.error(str(exc), icon=None)
        else:
            recovery = st.session_state.get("recovery_action")
            st.success("Resultado registrado en el historial comercial.", icon=None)
            if recovery:
                script_line("Próxima acción", recovery["objective"])
                profile_row("Recontactar desde", recovery["recontact_from"])
                profile_row("Canal", recovery["channel"])
                if recovery.get("alternative_offer_name"):
                    profile_row("Alternativa", recovery["alternative_offer_name"])
            if st.button("Recalcular siguiente acción", key=f"recalc_{context.decision_id}", width="stretch"):
                try:
                    with st.spinner("Recalculando con el resultado observado…"):
                        refresh_context(api, context.cliente_id)
                    st.rerun()
                except AdvisorApiError as exc:
                    st.error(str(exc), icon=None)

    section_title("Actividad operacional")
    recent_events = list(reversed(context.events[-5:]))
    if not recent_events:
        st.caption("Sin cambios operacionales registrados.")
    for event in recent_events:
        version = event.get("state_version_after", "—")
        offer = f" · {event['oferta_id']}" if event.get("oferta_id") else ""
        recorded = str(event.get("effective_at", ""))[:16].replace("T", " ")
        st.markdown(
            f'<div class="event-row"><div class="event-name">{safe(label_event(event["event_type"]))}{safe(offer)}</div>'
            f'<div class="event-meta">{safe(recorded)} · estado v{safe(version)} · {safe(event["source"])}</div></div>',
            unsafe_allow_html=True,
        )

st.caption(
    f"Decisión {result['decision_id']} · {result['versions']['model_version']} · "
    "Las probabilidades orientan la conversación y no garantizan un resultado."
)
