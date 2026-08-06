"""Genera un dashboard comercial, autocontenido y reproducible desde los CSV limpios.

Ejecución:
    python build_dashboard.py

Salida:
    dashboard_EDA.html
"""

from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
from plotly.subplots import make_subplots


BASE_DIR = Path(__file__).resolve().parent
OUTPUT_PATH = BASE_DIR / "dashboard_EDA.html"

# Paleta sobria: verde salvia, arcilla y grises calidos.
COL = {
    "ink": "#27332F",
    "muted": "#6F7873",
    "grid": "#E7E9E5",
    "primary": "#5F756B",
    "primary_dark": "#3E574D",
    "primary_soft": "#AAB9B2",
    "clay": "#9A745B",
    "clay_soft": "#C6A992",
    "stone": "#A3A7A2",
    "sand": "#C7B995",
    "rose": "#9B6862",
    "blue_gray": "#75858B",
    "surface": "#FFFFFF",
}

TYPE_LABELS = {
    "plan_movil": "Plan móvil",
    "plan_hogar": "Plan hogar",
    "upgrade": "Upgrade",
    "equipo": "Equipo",
    "paquete_adicional": "Paquete adicional",
    "movistar_total": "Movistar Total",
}

REASON_LABELS = {
    "precio": "Precio",
    "no_necesita": "No lo necesita",
    "ya_tiene_similar": "Ya tiene algo similar",
    "mal_momento": "Mal momento",
    "no_confia": "No confía",
    "otro": "Otro",
}

AGE_ORDER = ["18-25", "26-35", "36-45", "46-55", "56-65", "65+"]


def require_columns(df: pd.DataFrame, columns: set[str], name: str) -> None:
    """Falla temprano si cambia el contrato de alguno de los CSV."""
    missing = sorted(columns.difference(df.columns))
    if missing:
        raise ValueError(f"{name}: faltan columnas requeridas: {', '.join(missing)}")


def fmt_int(value: float | int) -> str:
    return f"{int(round(value)):,}"


def fmt_pct(value: float) -> str:
    return f"{value:.1f}%"


def style_figure(fig: go.Figure, height: int = 390) -> go.Figure:
    """Aplica un tema visual comun a todas las figuras."""
    fig.update_layout(
        height=height,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter, Segoe UI, Arial, sans-serif", color=COL["ink"], size=12),
        margin=dict(t=18, r=28, b=48, l=58),
        hoverlabel=dict(
            bgcolor=COL["ink"],
            bordercolor=COL["ink"],
            font=dict(color="white", family="Inter, Segoe UI, Arial, sans-serif", size=12),
        ),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="left",
            x=0,
            font=dict(size=11, color=COL["muted"]),
            title=None,
        ),
        hovermode="closest",
    )
    fig.update_xaxes(
        showgrid=False,
        zeroline=False,
        linecolor=COL["grid"],
        tickfont=dict(color=COL["muted"]),
        title_font=dict(color=COL["muted"], size=11),
        automargin=True,
    )
    fig.update_yaxes(
        gridcolor=COL["grid"],
        zeroline=False,
        linecolor=COL["grid"],
        tickfont=dict(color=COL["muted"]),
        title_font=dict(color=COL["muted"], size=11),
        automargin=True,
    )
    return fig


def chart_html(fig: go.Figure, chart_id: str, include_library: bool = False) -> str:
    """Convierte una figura a HTML; la primera incorpora Plotly para uso sin internet."""
    return pio.to_html(
        fig,
        include_plotlyjs="inline" if include_library else False,
        full_html=False,
        div_id=f"chart-{chart_id}",
        config={
            "displayModeBar": False,
            "displaylogo": False,
            "responsive": True,
        },
    )


# -------------------------------------------------------------------------
# Carga y validacion
# -------------------------------------------------------------------------
cli = pd.read_csv(BASE_DIR / "clientes_limpio.csv")
cat = pd.read_csv(BASE_DIR / "catalogo_limpio.csv")
his = pd.read_csv(BASE_DIR / "historial_limpio.csv")

require_columns(
    cli,
    {
        "cliente_id",
        "elegible_mt",
        "es_movistar_total",
        "monto_facturado_prom",
        "dias_mora_prom",
        "tiene_movil",
        "tiene_hogar",
        "edad_rango",
        "ubicacion_departamento",
        "plan_actual_id",
        "oferta_hogar_id",
    },
    "clientes_limpio.csv",
)
require_columns(
    cat,
    {"oferta_id", "nombre_oferta", "tipo_oferta", "precio_mensual", "es_movistar_total"},
    "catalogo_limpio.csv",
)
require_columns(
    his,
    {
        "ofrecimiento_id",
        "cliente_id",
        "oferta_id",
        "fecha",
        "canal",
        "resultado",
        "motivo_rechazo",
        "es_rebate",
        "contactabilidad",
        "tipo_oferta",
        "oferta_es_mt",
    },
    "historial_limpio.csv",
)

his["fecha"] = pd.to_datetime(his["fecha"], errors="raise")
his["mes"] = his["fecha"].dt.to_period("M").astype(str)
his["aceptada"] = his["resultado"].eq("aceptada")
his["contactado"] = his["contactabilidad"].eq("contactado")

cli["segmento_mt"] = np.select(
    [cli["es_movistar_total"], cli["elegible_mt"]],
    ["Ya tiene MT", "Elegible MT"],
    default="Base general",
)
cli["cartera_servicios"] = np.select(
    [cli["tiene_movil"] & cli["tiene_hogar"], cli["tiene_movil"], cli["tiene_hogar"]],
    ["Móvil + hogar", "Solo móvil", "Solo hogar"],
    default="Sin móvil ni hogar",
)

value_cut = float(cli["monto_facturado_prom"].median())
risk_cut = 15.0
cli["segmento_valor_riesgo"] = np.select(
    [
        (cli["monto_facturado_prom"] >= value_cut) & (cli["dias_mora_prom"] <= risk_cut),
        (cli["monto_facturado_prom"] >= value_cut) & (cli["dias_mora_prom"] > risk_cut),
        (cli["monto_facturado_prom"] < value_cut) & (cli["dias_mora_prom"] <= risk_cut),
    ],
    ["Alto valor · Bajo riesgo", "Alto valor · Riesgo alto", "Valor medio · Bajo riesgo"],
    default="Valor medio · Riesgo alto",
)

client_context = cli[
    [
        "cliente_id",
        "edad_rango",
        "ubicacion_departamento",
        "monto_facturado_prom",
        "segmento_valor_riesgo",
    ]
]
his_client = his.merge(client_context, on="cliente_id", how="left", validate="many_to_one")


# -------------------------------------------------------------------------
# Indicadores y tablas analiticas
# -------------------------------------------------------------------------
n_clientes = len(cli)
n_ofrecim = len(his)
n_contactados = int(his["contactado"].sum())
n_aceptados = int(his["aceptada"].sum())
n_rechazados = int(his["resultado"].eq("rechazada").sum())
n_no_contactados = n_ofrecim - n_contactados
n_elig_mt = int(cli["elegible_mt"].sum())
n_ya_mt = int(cli["es_movistar_total"].sum())
n_sin_historial = int(n_clientes - his["cliente_id"].nunique())

tasa_contacto = n_contactados / n_ofrecim * 100
tasa_acept_total = n_aceptados / n_ofrecim * 100
tasa_acept_contactados = n_aceptados / n_contactados * 100
arpu_prom = float(cli["monto_facturado_prom"].mean())

rejected = his.loc[his["resultado"].eq("rechazada")].copy()
reason = (
    rejected.groupby("motivo_rechazo", observed=True)
    .agg(rechazos=("ofrecimiento_id", "size"), rebates=("es_rebate", "sum"))
    .sort_values("rechazos", ascending=False)
)
reason["participacion"] = reason["rechazos"] / reason["rechazos"].sum() * 100
reason["acumulado"] = reason["participacion"].cumsum()
reason["cobertura_rebate"] = reason["rebates"] / reason["rechazos"] * 100
reason["motivo"] = reason.index.map(REASON_LABELS)
motivo_top_nombre = str(reason.iloc[0]["motivo"])
motivo_top_pct = float(reason.iloc[0]["participacion"])

channel = (
    his.groupby("canal", observed=True)
    .agg(
        ofrecimientos=("ofrecimiento_id", "size"),
        contactados=("contactado", "sum"),
        aceptados=("aceptada", "sum"),
    )
)
channel["contactabilidad"] = channel["contactados"] / channel["ofrecimientos"] * 100
channel["conversion_contactado"] = channel["aceptados"] / channel["contactados"] * 100
channel = channel.sort_values("conversion_contactado", ascending=False)
channel_gap = float(channel["conversion_contactado"].max() - channel["conversion_contactado"].min())

offer_type = (
    his.groupby("tipo_oferta", observed=True)
    .agg(
        ofrecimientos=("ofrecimiento_id", "size"),
        contactados=("contactado", "sum"),
        aceptados=("aceptada", "sum"),
    )
)
offer_type["conversion_contactado"] = offer_type["aceptados"] / offer_type["contactados"] * 100
offer_type["tipo"] = offer_type.index.map(TYPE_LABELS)
offer_type = offer_type.sort_values("conversion_contactado")

offer_perf = (
    his.groupby("oferta_id", observed=True)
    .agg(
        ofrecimientos=("ofrecimiento_id", "size"),
        contactados=("contactado", "sum"),
        aceptados=("aceptada", "sum"),
    )
    .reset_index()
)
offer_perf["conversion_contactado"] = offer_perf["aceptados"] / offer_perf["contactados"] * 100
offer_perf = offer_perf.merge(
    cat[["oferta_id", "nombre_oferta", "tipo_oferta", "precio_mensual", "es_movistar_total"]],
    on="oferta_id",
    how="left",
    validate="one_to_one",
)
offer_perf["tipo"] = offer_perf["tipo_oferta"].map(TYPE_LABELS)

mt_hist = (
    his.groupby("oferta_es_mt", observed=True)
    .agg(contactados=("contactado", "sum"), aceptados=("aceptada", "sum"))
)
mt_hist["conversion_contactado"] = mt_hist["aceptados"] / mt_hist["contactados"] * 100
mt_conversion = float(mt_hist.loc[True, "conversion_contactado"])
non_mt_conversion = float(mt_hist.loc[False, "conversion_contactado"])
mt_gap = mt_conversion - non_mt_conversion

monthly = (
    his.groupby("mes", observed=True)
    .agg(
        ofrecimientos=("ofrecimiento_id", "size"),
        contactados=("contactado", "sum"),
        aceptados=("aceptada", "sum"),
    )
)
monthly["conversion_contactado"] = monthly["aceptados"] / monthly["contactados"] * 100

channel_offer = (
    his.loc[his["contactado"]]
    .pivot_table(index="tipo_oferta", columns="canal", values="aceptada", aggfunc="mean")
    .mul(100)
)
channel_offer = channel_offer.reindex(offer_type.index)
channel_offer.index = channel_offer.index.map(TYPE_LABELS)

region = (
    cli.groupby("ubicacion_departamento", observed=True)
    .agg(
        clientes=("cliente_id", "size"),
        elegibles_mt=("elegible_mt", "sum"),
        ya_mt=("es_movistar_total", "sum"),
        arpu=("monto_facturado_prom", "mean"),
    )
)
region["pct_elegible"] = region["elegibles_mt"] / region["clientes"] * 100
region = region.sort_values("elegibles_mt")

age_mt = (
    cli.groupby(["edad_rango", "segmento_mt"], observed=True)
    .size()
    .unstack(fill_value=0)
    .reindex(AGE_ORDER)
)
age_mt_pct = age_mt.div(age_mt.sum(axis=1), axis=0).mul(100)

service_mix = cli["cartera_servicios"].value_counts()

vr_client = (
    cli.groupby("segmento_valor_riesgo", observed=True)
    .agg(
        clientes=("cliente_id", "size"),
        arpu=("monto_facturado_prom", "mean"),
        mora=("dias_mora_prom", "mean"),
        elegibles_mt=("elegible_mt", "sum"),
    )
)
vr_campaign = (
    his_client.groupby("segmento_valor_riesgo", observed=True)
    .agg(contactados=("contactado", "sum"), aceptados=("aceptada", "sum"))
)
vr_client = vr_client.join(vr_campaign)
vr_client["conversion_contactado"] = vr_client["aceptados"] / vr_client["contactados"] * 100

owned = his.merge(
    cli[["cliente_id", "plan_actual_id", "oferta_hogar_id"]],
    on="cliente_id",
    how="left",
    validate="many_to_one",
)
n_same_plan = int(owned["oferta_id"].eq(owned["plan_actual_id"]).sum())
n_same_home = int(owned["oferta_id"].eq(owned["oferta_hogar_id"]).sum())


# -------------------------------------------------------------------------
# Figuras
# -------------------------------------------------------------------------
fig_funnel = go.Figure(
    go.Funnel(
        y=["Ofrecimientos", "Contactados", "Aceptados"],
        x=[n_ofrecim, n_contactados, n_aceptados],
        textinfo="value+percent initial",
        texttemplate="%{value:,.0f}<br>%{percentInitial:.1%} del inicio",
        marker=dict(color=[COL["stone"], COL["primary_soft"], COL["primary_dark"]]),
        connector=dict(line=dict(color=COL["grid"], width=1)),
        hovertemplate="%{label}: %{value:,.0f}<extra></extra>",
    )
)
style_figure(fig_funnel, 350)
fig_funnel.update_layout(margin=dict(t=10, r=35, b=20, l=105))

fig_channel = go.Figure()
fig_channel.add_trace(
    go.Bar(
        x=channel.index,
        y=channel["contactabilidad"],
        name="Contactabilidad",
        marker_color=COL["primary_soft"],
        text=[fmt_pct(v) for v in channel["contactabilidad"]],
        textposition="outside",
        hovertemplate="%{x}<br>Contactabilidad: %{y:.1f}%<extra></extra>",
    )
)
fig_channel.add_trace(
    go.Bar(
        x=channel.index,
        y=channel["conversion_contactado"],
        name="Conversión entre contactados",
        marker_color=COL["primary_dark"],
        text=[fmt_pct(v) for v in channel["conversion_contactado"]],
        textposition="outside",
        hovertemplate="%{x}<br>Conversión: %{y:.1f}%<extra></extra>",
    )
)
style_figure(fig_channel, 390)
fig_channel.update_layout(barmode="group", bargap=0.25)
fig_channel.update_yaxes(title="Porcentaje", range=[0, 100], ticksuffix="%")

fig_offer_type = go.Figure(
    go.Bar(
        x=offer_type["conversion_contactado"],
        y=offer_type["tipo"],
        orientation="h",
        marker_color=[COL["clay"] if t == "Movistar Total" else COL["primary"] for t in offer_type["tipo"]],
        text=[fmt_pct(v) for v in offer_type["conversion_contactado"]],
        textposition="outside",
        customdata=offer_type[["ofrecimientos", "contactados"]].to_numpy(),
        hovertemplate=(
            "%{y}<br>Conversión contactados: %{x:.1f}%"
            "<br>Ofrecimientos: %{customdata[0]:,.0f}"
            "<br>Contactados: %{customdata[1]:,.0f}<extra></extra>"
        ),
    )
)
style_figure(fig_offer_type, 390)
fig_offer_type.update_layout(margin=dict(t=18, r=48, b=48, l=128))
fig_offer_type.update_xaxes(title="Conversión entre contactados", ticksuffix="%", range=[0, 78])

fig_heatmap = go.Figure(
    go.Heatmap(
        z=channel_offer.values,
        x=channel_offer.columns,
        y=channel_offer.index,
        colorscale=[[0, "#EEF1EE"], [0.5, "#9BAEA5"], [1, "#3E574D"]],
        zmin=25,
        zmax=72,
        text=[[f"{value:.1f}%" for value in row] for row in channel_offer.values],
        texttemplate="%{text}",
        textfont=dict(size=11),
        showscale=False,
        hovertemplate="%{y}<br>%{x}<br>Conversión: %{z:.1f}%<extra></extra>",
    )
)
style_figure(fig_heatmap, 410)
fig_heatmap.update_layout(margin=dict(t=10, r=24, b=45, l=130))
fig_heatmap.update_yaxes(showgrid=False)

portfolio_colors = {
    "Plan móvil": COL["blue_gray"],
    "Plan hogar": COL["primary"],
    "Upgrade": COL["sand"],
    "Equipo": COL["stone"],
    "Paquete adicional": COL["clay_soft"],
    "Movistar Total": COL["clay"],
}
fig_portfolio = go.Figure()
for label in TYPE_LABELS.values():
    subset = offer_perf.loc[offer_perf["tipo"].eq(label)]
    fig_portfolio.add_trace(
        go.Scatter(
            x=subset["precio_mensual"],
            y=subset["conversion_contactado"],
            mode="markers",
            name=label,
            marker=dict(
                color=portfolio_colors[label],
                size=np.sqrt(subset["ofrecimientos"]) / 3.2,
                sizemin=12,
                line=dict(color="white", width=1.5),
                opacity=0.9,
            ),
            customdata=subset[["nombre_oferta", "ofrecimientos", "contactados"]].to_numpy(),
            hovertemplate=(
                "<b>%{customdata[0]}</b><br>Precio: S/ %{x:.1f}"
                "<br>Conversión contactados: %{y:.1f}%"
                "<br>Ofrecimientos: %{customdata[1]:,.0f}"
                "<br>Contactados: %{customdata[2]:,.0f}<extra></extra>"
            ),
        )
    )
style_figure(fig_portfolio, 470)
fig_portfolio.update_xaxes(title="Precio mensual de la oferta (S/)", rangemode="tozero")
fig_portfolio.update_yaxes(title="Conversión entre contactados", ticksuffix="%", range=[25, 75])

fig_month = make_subplots(specs=[[{"secondary_y": True}]])
fig_month.add_trace(
    go.Bar(
        x=["Ene 2026", "Feb 2026", "Mar 2026", "Abr 2026", "May 2026", "Jun 2026"],
        y=monthly["ofrecimientos"],
        name="Ofrecimientos",
        marker_color=COL["primary_soft"],
        text=[fmt_int(v) for v in monthly["ofrecimientos"]],
        textposition="inside",
        hovertemplate="%{x}<br>Ofrecimientos: %{y:,.0f}<extra></extra>",
    ),
    secondary_y=False,
)
fig_month.add_trace(
    go.Scatter(
        x=["Ene 2026", "Feb 2026", "Mar 2026", "Abr 2026", "May 2026", "Jun 2026"],
        y=monthly["conversion_contactado"],
        name="Conversión contactados",
        mode="lines+markers",
        line=dict(color=COL["clay"], width=2.5),
        marker=dict(size=8, color=COL["clay"], line=dict(color="white", width=1)),
        hovertemplate="%{x}<br>Conversión: %{y:.1f}%<extra></extra>",
    ),
    secondary_y=True,
)
style_figure(fig_month, 380)
fig_month.update_yaxes(title_text="Ofrecimientos", secondary_y=False, rangemode="tozero")
fig_month.update_yaxes(
    title_text="Conversión entre contactados",
    ticksuffix="%",
    range=[35, 40],
    gridcolor="rgba(0,0,0,0)",
    secondary_y=True,
)

fig_pareto = make_subplots(specs=[[{"secondary_y": True}]])
fig_pareto.add_trace(
    go.Bar(
        x=reason["motivo"],
        y=reason["rechazos"],
        name="Rechazos",
        marker_color=[COL["clay"]] + [COL["primary_soft"]] * (len(reason) - 1),
        text=[fmt_pct(v) for v in reason["participacion"]],
        textposition="outside",
        customdata=reason[["participacion", "cobertura_rebate"]].to_numpy(),
        hovertemplate=(
            "%{x}<br>Rechazos: %{y:,.0f}"
            "<br>Participacion: %{customdata[0]:.1f}%"
            "<br>Con rebate: %{customdata[1]:.1f}%<extra></extra>"
        ),
    ),
    secondary_y=False,
)
fig_pareto.add_trace(
    go.Scatter(
        x=reason["motivo"],
        y=reason["acumulado"],
        name="Acumulado",
        mode="lines+markers",
        line=dict(color=COL["ink"], width=2.2),
        marker=dict(size=7),
        hovertemplate="%{x}<br>Acumulado: %{y:.1f}%<extra></extra>",
    ),
    secondary_y=True,
)
style_figure(fig_pareto, 420)
fig_pareto.update_layout(margin=dict(t=18, r=55, b=70, l=58))
fig_pareto.update_xaxes(tickangle=-20)
fig_pareto.update_yaxes(title_text="Rechazos", secondary_y=False, rangemode="tozero")
fig_pareto.update_yaxes(
    title_text="Porcentaje acumulado",
    ticksuffix="%",
    range=[0, 108],
    gridcolor="rgba(0,0,0,0)",
    secondary_y=True,
)

fig_rebate = go.Figure(
    go.Bar(
        x=reason.sort_values("cobertura_rebate")["cobertura_rebate"],
        y=reason.sort_values("cobertura_rebate")["motivo"],
        orientation="h",
        marker_color=COL["clay_soft"],
        text=[fmt_pct(v) for v in reason.sort_values("cobertura_rebate")["cobertura_rebate"]],
        textposition="outside",
        customdata=reason.sort_values("cobertura_rebate")[["rechazos", "rebates"]].to_numpy(),
        hovertemplate=(
            "%{y}<br>Cobertura de rebate: %{x:.1f}%"
            "<br>Rechazos: %{customdata[0]:,.0f}"
            "<br>Con rebate: %{customdata[1]:,.0f}<extra></extra>"
        ),
    )
)
style_figure(fig_rebate, 420)
fig_rebate.update_layout(margin=dict(t=18, r=48, b=48, l=132))
fig_rebate.update_xaxes(title="Rechazos que recibieron rebate", ticksuffix="%", range=[0, 40])

fig_region = go.Figure(
    go.Bar(
        x=region["elegibles_mt"],
        y=region.index,
        orientation="h",
        marker_color=[COL["clay"] if dep == "Lima" else COL["primary"] for dep in region.index],
        text=[f"{fmt_int(n)} · {fmt_pct(p)}" for n, p in zip(region["elegibles_mt"], region["pct_elegible"])],
        textposition="outside",
        customdata=region[["clientes", "pct_elegible", "ya_mt", "arpu"]].to_numpy(),
        hovertemplate=(
            "%{y}<br>Elegibles MT: %{x:,.0f}"
            "<br>Base regional: %{customdata[0]:,.0f}"
            "<br>Elegibles/base: %{customdata[1]:.1f}%"
            "<br>Ya tienen MT: %{customdata[2]:,.0f}"
            "<br>ARPU medio: S/ %{customdata[3]:.1f}<extra></extra>"
        ),
    )
)
style_figure(fig_region, 450)
fig_region.update_layout(margin=dict(t=18, r=110, b=48, l=98))
fig_region.update_xaxes(title="Clientes elegibles para MT")
fig_region.update_xaxes(range=[0, float(region["elegibles_mt"].max()) * 1.22])

fig_age = go.Figure()
age_colors = {
    "Base general": COL["stone"],
    "Elegible MT": COL["clay"],
    "Ya tiene MT": COL["primary_dark"],
}
for segment in ["Base general", "Elegible MT", "Ya tiene MT"]:
    fig_age.add_trace(
        go.Bar(
            x=age_mt_pct.index,
            y=age_mt_pct[segment],
            name=segment,
            marker_color=age_colors[segment],
            customdata=age_mt[segment],
            hovertemplate=(
                "%{x}<br>" + segment + ": %{y:.1f}%"
                "<br>Clientes: %{customdata:,.0f}<extra></extra>"
            ),
        )
    )
style_figure(fig_age, 390)
fig_age.update_layout(barmode="stack")
fig_age.update_yaxes(title="Composición del rango de edad", ticksuffix="%", range=[0, 100])

fig_services = go.Figure(
    go.Pie(
        labels=service_mix.index,
        values=service_mix.values,
        hole=0.66,
        sort=False,
        marker=dict(colors=[COL["primary_dark"], COL["primary_soft"], COL["clay"], COL["stone"]]),
        textinfo="label+percent",
        textposition="outside",
        hovertemplate="%{label}<br>Clientes: %{value:,.0f}<br>Participacion: %{percent}<extra></extra>",
    )
)
style_figure(fig_services, 390)
fig_services.update_layout(showlegend=False, margin=dict(t=10, r=70, b=30, l=70))
fig_services.add_annotation(
    text=f"{fmt_int(n_clientes)}<br><span style='font-size:11px'>clientes</span>",
    x=0.5,
    y=0.5,
    showarrow=False,
    font=dict(size=17, color=COL["ink"]),
)

vr_colors = {
    "Alto valor · Bajo riesgo": COL["primary_dark"],
    "Alto valor · Riesgo alto": COL["clay"],
    "Valor medio · Bajo riesgo": COL["primary_soft"],
    "Valor medio · Riesgo alto": COL["stone"],
}
fig_value_risk = go.Figure()
for segment, row in vr_client.iterrows():
    fig_value_risk.add_trace(
        go.Scatter(
            x=[row["mora"]],
            y=[row["arpu"]],
            mode="markers+text",
            name=segment,
            text=[segment.replace(" · ", "<br>")],
            textposition="top center",
            marker=dict(
                size=max(34, np.sqrt(row["clientes"]) / 4.2),
                color=vr_colors[segment],
                opacity=0.9,
                line=dict(color="white", width=2),
            ),
            customdata=[
                [row["clientes"], row["elegibles_mt"], row["conversion_contactado"]]
            ],
            hovertemplate=(
                "<b>" + segment + "</b>"
                "<br>Clientes: %{customdata[0]:,.0f}"
                "<br>ARPU medio: S/ %{y:.1f}"
                "<br>Mora media: %{x:.1f} dias"
                "<br>Elegibles MT: %{customdata[1]:,.0f}"
                "<br>Conversión: %{customdata[2]:.1f}%<extra></extra>"
            ),
        )
    )
style_figure(fig_value_risk, 470)
fig_value_risk.update_layout(showlegend=False, margin=dict(t=20, r=38, b=55, l=65))
fig_value_risk.update_xaxes(title="Días de mora promedio", range=[0, max(24, vr_client["mora"].max() + 4)])
fig_value_risk.update_yaxes(title="ARPU promedio (S/)", range=[40, vr_client["arpu"].max() + 25])
fig_value_risk.add_vline(x=risk_cut, line_dash="dot", line_color=COL["clay_soft"], line_width=1.3)
fig_value_risk.add_hline(y=value_cut, line_dash="dot", line_color=COL["primary_soft"], line_width=1.3)


# -------------------------------------------------------------------------
# HTML
# -------------------------------------------------------------------------
top_three_reasons = reason.head(3)
top_three_share = float(top_three_reasons["participacion"].sum())
lima_share = float((cli["ubicacion_departamento"].eq("Lima").mean()) * 100)

html = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="description" content="Dashboard comercial de personalizacion de ofertas y Movistar Total">
<title>Dashboard comercial · Personalizacion inteligente</title>
<style>
:root {{
  --bg: #F3F2EE;
  --surface: #FFFFFF;
  --surface-soft: #E9EDE9;
  --ink: #27332F;
  --muted: #6F7873;
  --line: #DEE2DE;
  --primary: #5F756B;
  --primary-dark: #3E574D;
  --clay: #9A745B;
  --shadow: 0 12px 34px rgba(39, 51, 47, .06);
  --radius: 18px;
}}
* {{ box-sizing: border-box; }}
html {{ scroll-behavior: smooth; }}
body {{
  margin: 0;
  background: var(--bg);
  color: var(--ink);
  font-family: Inter, "Segoe UI", Arial, sans-serif;
  font-size: 15px;
  line-height: 1.55;
  -webkit-font-smoothing: antialiased;
}}
a {{ color: inherit; }}
.topbar {{
  position: sticky;
  top: 0;
  z-index: 20;
  background: rgba(243, 242, 238, .92);
  border-bottom: 1px solid rgba(62, 87, 77, .10);
  backdrop-filter: blur(16px);
}}
.nav {{
  max-width: 1420px;
  margin: auto;
  padding: 13px 28px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
}}
.brand {{ font-size: 13px; font-weight: 700; letter-spacing: .06em; text-transform: uppercase; }}
.nav-links {{ display: flex; gap: 8px; flex-wrap: wrap; }}
.nav-links a {{
  text-decoration: none;
  color: var(--muted);
  font-size: 12px;
  font-weight: 600;
  padding: 7px 10px;
  border-radius: 999px;
}}
.nav-links a:hover {{ color: var(--ink); background: var(--surface); }}
.hero {{ background: var(--ink); color: #F7F7F4; }}
.hero-inner {{ max-width: 1420px; margin: auto; padding: 70px 28px 62px; }}
.eyebrow {{
  color: #BFCBC5;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: .14em;
  text-transform: uppercase;
  margin-bottom: 18px;
}}
.hero h1 {{
  max-width: 820px;
  margin: 0;
  font-size: clamp(36px, 5vw, 64px);
  line-height: 1.04;
  letter-spacing: -.045em;
  font-weight: 620;
}}
.hero-copy {{ max-width: 760px; margin: 24px 0 0; color: #C9D0CC; font-size: 17px; }}
.hero-meta {{ display: flex; flex-wrap: wrap; gap: 10px; margin-top: 32px; }}
.pill {{
  border: 1px solid rgba(255,255,255,.16);
  color: #D8DEDA;
  border-radius: 999px;
  padding: 8px 13px;
  font-size: 12px;
}}
main {{ max-width: 1420px; margin: auto; padding: 34px 28px 70px; }}
.section {{ scroll-margin-top: 76px; padding: 42px 0 16px; }}
.section:first-child {{ padding-top: 10px; }}
.section-head {{ max-width: 820px; margin-bottom: 22px; }}
.section-kicker {{
  color: var(--primary);
  text-transform: uppercase;
  letter-spacing: .13em;
  font-size: 11px;
  font-weight: 800;
  margin-bottom: 8px;
}}
.section h2 {{ margin: 0; font-size: clamp(26px, 3vw, 38px); line-height: 1.15; letter-spacing: -.025em; }}
.section-intro {{ color: var(--muted); margin: 12px 0 0; max-width: 760px; }}
.kpi-grid {{ display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 12px; }}
.kpi {{
  background: var(--surface);
  border: 1px solid rgba(39,51,47,.06);
  border-radius: 15px;
  padding: 20px 18px;
  min-height: 132px;
  box-shadow: 0 5px 20px rgba(39,51,47,.035);
}}
.kpi-label {{ color: var(--muted); font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: .08em; }}
.kpi-value {{ margin-top: 9px; font-size: 27px; line-height: 1; font-weight: 650; letter-spacing: -.03em; }}
.kpi-sub {{ margin-top: 11px; color: var(--muted); font-size: 12px; line-height: 1.35; }}
.executive {{
  margin-top: 18px;
  display: grid;
  grid-template-columns: .8fr 1.2fr;
  background: var(--surface-soft);
  border: 1px solid rgba(62,87,77,.10);
  border-radius: var(--radius);
  overflow: hidden;
}}
.executive-lead {{ padding: 32px; background: var(--primary-dark); color: white; }}
.executive-lead span {{ color: #C8D3CE; font-size: 12px; text-transform: uppercase; letter-spacing: .10em; }}
.executive-lead strong {{ display: block; margin-top: 12px; font-size: 30px; line-height: 1.15; font-weight: 600; }}
.executive-lead p {{ color: #D5DDD9; font-size: 13px; margin: 16px 0 0; }}
.decision-list {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 1px; background: rgba(62,87,77,.10); }}
.decision {{ background: var(--surface-soft); padding: 23px 25px; }}
.decision-number {{ color: var(--clay); font-size: 12px; font-weight: 800; }}
.decision strong {{ display: block; margin: 5px 0 6px; font-size: 14px; }}
.decision p {{ margin: 0; color: var(--muted); font-size: 12px; }}
.grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }}
.grid + .grid {{ margin-top: 16px; }}
.wide {{ grid-column: 1 / -1; }}
.card {{
  background: var(--surface);
  border: 1px solid rgba(39,51,47,.06);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
  overflow: hidden;
}}
.card-head {{ padding: 22px 24px 0; }}
.question {{ color: var(--primary); font-size: 11px; font-weight: 800; letter-spacing: .08em; text-transform: uppercase; }}
.card h3 {{ font-size: 18px; line-height: 1.3; margin: 6px 0 6px; letter-spacing: -.015em; }}
.card-description {{ margin: 0; color: var(--muted); font-size: 12px; max-width: 760px; }}
.plot {{ padding: 4px 8px 8px; min-width: 0; }}
.insight-strip {{
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
  margin-top: 16px;
}}
.insight {{ border-top: 2px solid var(--primary); padding: 16px 4px 4px; }}
.insight.clay {{ border-color: var(--clay); }}
.insight-title {{ font-weight: 700; font-size: 13px; }}
.insight p {{ margin: 5px 0 0; color: var(--muted); font-size: 12px; }}
.ops-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 16px; }}
.ops {{ background: #E8EAE6; border-radius: 14px; padding: 19px; }}
.ops-value {{ font-size: 24px; font-weight: 650; letter-spacing: -.03em; }}
.ops-label {{ font-size: 12px; margin-top: 5px; }}
.ops-note {{ color: var(--muted); font-size: 11px; margin-top: 7px; }}
.method {{
  margin-top: 24px;
  background: transparent;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  padding: 24px;
  display: grid;
  grid-template-columns: 180px 1fr;
  gap: 28px;
}}
.method h3 {{ margin: 0; font-size: 16px; }}
.method ul {{ margin: 0; padding-left: 18px; color: var(--muted); font-size: 12px; columns: 2; column-gap: 38px; }}
.method li {{ margin-bottom: 8px; break-inside: avoid; }}
footer {{ border-top: 1px solid var(--line); color: var(--muted); font-size: 11px; padding: 24px 0 0; margin-top: 34px; }}
@media (max-width: 1120px) {{
  .kpi-grid {{ grid-template-columns: repeat(3, 1fr); }}
  .executive {{ grid-template-columns: 1fr; }}
}}
@media (max-width: 780px) {{
  .nav {{ padding: 11px 16px; }}
  .nav-links {{ display: none; }}
  .hero-inner {{ padding: 52px 18px 46px; }}
  main {{ padding: 24px 16px 52px; }}
  .grid, .insight-strip, .ops-grid {{ grid-template-columns: 1fr; }}
  .wide {{ grid-column: auto; }}
  .kpi-grid {{ grid-template-columns: repeat(2, 1fr); }}
  .decision-list {{ grid-template-columns: 1fr; }}
  .method {{ grid-template-columns: 1fr; }}
  .method ul {{ columns: 1; }}
}}
@media (max-width: 460px) {{ .kpi-grid {{ grid-template-columns: 1fr; }} }}
@media (prefers-reduced-motion: reduce) {{ html {{ scroll-behavior: auto; }} }}
</style>
</head>
<body>
<header class="topbar">
  <nav class="nav" aria-label="Navegacion del dashboard">
    <div class="brand">Inteligencia comercial</div>
    <div class="nav-links">
      <a href="#resumen">Resumen</a>
      <a href="#oferta-canal">Oferta y canal</a>
      <a href="#clientes">Clientes</a>
      <a href="#operacion">Operación</a>
    </div>
  </nav>
</header>

<section class="hero">
  <div class="hero-inner">
    <div class="eyebrow">Análisis comercial · Enero a junio de 2026</div>
    <h1>Decisiones comerciales basadas en evidencia.</h1>
    <p class="hero-copy">Una lectura ejecutiva de la cartera, las campañas y el portafolio para identificar dónde convertir mejor, cómo priorizar Movistar Total y qué fricciones corregir.</p>
    <div class="hero-meta">
      <span class="pill">{fmt_int(n_clientes)} clientes</span>
      <span class="pill">{fmt_int(n_ofrecim)} ofrecimientos</span>
      <span class="pill">22 ofertas</span>
      <span class="pill">Datos sintéticos anonimizados</span>
    </div>
  </div>
</section>

<main>
  <section class="section" id="resumen">
    <div class="section-head">
      <div class="section-kicker">01 · Resumen ejecutivo</div>
      <h2>Qué está ocurriendo en el negocio</h2>
      <p class="section-intro">Los indicadores separan alcance, contacto y conversión para evitar conclusiones engañosas. La conversión principal se calcula solo sobre clientes contactados.</p>
    </div>

    <div class="kpi-grid">
      <article class="kpi"><div class="kpi-label">Base de clientes</div><div class="kpi-value">{fmt_int(n_clientes)}</div><div class="kpi-sub">Universo comercial analizado</div></article>
      <article class="kpi"><div class="kpi-label">Contactabilidad</div><div class="kpi-value">{fmt_pct(tasa_contacto)}</div><div class="kpi-sub">{fmt_int(n_contactados)} contactos efectivos</div></article>
      <article class="kpi"><div class="kpi-label">Conversión contactados</div><div class="kpi-value">{fmt_pct(tasa_acept_contactados)}</div><div class="kpi-sub">{fmt_pct(tasa_acept_total)} sobre todos los intentos</div></article>
      <article class="kpi"><div class="kpi-label">Oportunidad MT</div><div class="kpi-value">{fmt_int(n_elig_mt)}</div><div class="kpi-sub">{fmt_pct(n_elig_mt / n_clientes * 100)} de la cartera</div></article>
      <article class="kpi"><div class="kpi-label">Clientes con MT</div><div class="kpi-value">{fmt_int(n_ya_mt)}</div><div class="kpi-sub">{fmt_pct(n_ya_mt / n_clientes * 100)} de penetración actual</div></article>
      <article class="kpi"><div class="kpi-label">ARPU promedio</div><div class="kpi-value">S/ {arpu_prom:.1f}</div><div class="kpi-sub">Facturación mensual media</div></article>
    </div>

    <div class="executive">
      <div class="executive-lead">
        <span>Lectura ejecutiva</span>
        <strong>MT concentra la mayor respuesta comercial.</strong>
        <p>Entre clientes contactados, las ofertas MT convierten {fmt_pct(mt_conversion)}, frente a {fmt_pct(non_mt_conversion)} para el resto del portafolio. Es una asociación descriptiva: MT solo fue ofrecido a elegibles.</p>
      </div>
      <div class="decision-list">
        <div class="decision"><div class="decision-number">01</div><strong>Priorizar elegibles MT</strong><p>Existe una bolsa de {fmt_int(n_elig_mt)} clientes que cumple las condiciones y aún no tiene el producto.</p></div>
        <div class="decision"><div class="decision-number">02</div><strong>Mejorar contacto antes que canal</strong><p>{fmt_int(n_no_contactados)} intentos no llegaron al cliente, mientras la brecha de conversión entre canales es solo {channel_gap:.1f} pp.</p></div>
        <div class="decision"><div class="decision-number">03</div><strong>Atacar el precio</strong><p>{motivo_top_nombre} explica {fmt_pct(motivo_top_pct)} de los rechazos; es el primer frente para probar rebate y argumentación.</p></div>
        <div class="decision"><div class="decision-number">04</div><strong>Evitar ofertas redundantes</strong><p>{fmt_int(n_same_plan)} eventos repitieron el plan actual; se necesitan reglas previas al scoring.</p></div>
      </div>
    </div>
  </section>

  <section class="section" id="oferta-canal">
    <div class="section-head">
      <div class="section-kicker">02 · Oferta y canal</div>
      <h2>Dónde se genera la conversión</h2>
      <p class="section-intro">La comparación combina volumen, contacto y aceptación. Permite distinguir una oferta atractiva de una campaña simplemente más grande.</p>
    </div>
    <div class="grid">
      <article class="card">
        <div class="card-head"><div class="question">Pregunta comercial</div><h3>¿Cuántos intentos llegan a una venta?</h3><p class="card-description">Embudo completo desde el ofrecimiento hasta la aceptación.</p></div>
        <div class="plot">{chart_html(fig_funnel, "funnel", include_library=True)}</div>
      </article>
      <article class="card">
        <div class="card-head"><div class="question">Pregunta comercial</div><h3>¿El canal cambia realmente el resultado?</h3><p class="card-description">Contactabilidad y conversión sobre los clientes que sí fueron contactados.</p></div>
        <div class="plot">{chart_html(fig_channel, "channel")}</div>
      </article>
    </div>
    <div class="grid">
      <article class="card">
        <div class="card-head"><div class="question">Pregunta comercial</div><h3>¿Qué familia de oferta convierte mejor?</h3><p class="card-description">MT destaca; las demás categorías forman un bloque mucho más parejo.</p></div>
        <div class="plot">{chart_html(fig_offer_type, "offer-type")}</div>
      </article>
      <article class="card">
        <div class="card-head"><div class="question">Pregunta comercial</div><h3>¿Qué combinación oferta–canal funciona?</h3><p class="card-description">La intensidad representa conversión entre contactados, no volumen.</p></div>
        <div class="plot">{chart_html(fig_heatmap, "heatmap")}</div>
      </article>
    </div>
    <div class="grid">
      <article class="card wide">
        <div class="card-head"><div class="question">Lectura de portafolio</div><h3>Precio, conversión y escala de cada oferta</h3><p class="card-description">Cada burbuja es una oferta; su tamaño representa el volumen de campaña. Pase el cursor para revisar producto y resultados.</p></div>
        <div class="plot">{chart_html(fig_portfolio, "portfolio")}</div>
      </article>
    </div>
    <div class="grid">
      <article class="card wide">
        <div class="card-head"><div class="question">Estabilidad del proceso</div><h3>¿La conversión cambia con el tiempo?</h3><p class="card-description">El eje derecho se acota para hacer visible una variación pequeña; el nivel mensual permanece estable.</p></div>
        <div class="plot">{chart_html(fig_month, "month")}</div>
      </article>
    </div>
    <div class="insight-strip">
      <div class="insight"><div class="insight-title">Canal: elegir por costo y alcance</div><p>La diferencia entre el mejor y el peor canal es {channel_gap:.1f} puntos porcentuales entre contactados.</p></div>
      <div class="insight clay"><div class="insight-title">MT: ventaja de {mt_gap:.1f} pp</div><p>La señal es fuerte, pero debe validarse porque todas las ofertas MT fueron dirigidas a elegibles.</p></div>
      <div class="insight"><div class="insight-title">Meses comparables</div><p>El volumen ronda 50 mil intentos mensuales y la conversión permanece cerca de {fmt_pct(tasa_acept_contactados)}.</p></div>
    </div>
  </section>

  <section class="section" id="clientes">
    <div class="section-head">
      <div class="section-kicker">03 · Clientes y oportunidad</div>
      <h2>Donde concentrar el esfuerzo comercial</h2>
      <p class="section-intro">La oportunidad se lee por territorio, edad, cartera de servicios y equilibrio entre valor y riesgo.</p>
    </div>
    <div class="grid">
      <article class="card">
        <div class="card-head"><div class="question">Priorización territorial</div><h3>¿Dónde están los elegibles para MT?</h3><p class="card-description">La etiqueta combina cantidad absoluta y porcentaje de la base regional.</p></div>
        <div class="plot">{chart_html(fig_region, "region")}</div>
      </article>
      <article class="card">
        <div class="card-head"><div class="question">Composición por edad</div><h3>¿Cómo cambia la oportunidad MT?</h3><p class="card-description">Distribución porcentual dentro de cada rango de edad.</p></div>
        <div class="plot">{chart_html(fig_age, "age")}</div>
      </article>
    </div>
    <div class="grid">
      <article class="card">
        <div class="card-head"><div class="question">Cartera actual</div><h3>¿Qué combinación de servicios tiene la base?</h3><p class="card-description">Punto de partida para cross-sell entre móvil y hogar.</p></div>
        <div class="plot">{chart_html(fig_services, "services")}</div>
      </article>
      <article class="card">
        <div class="card-head"><div class="question">Matriz de decisión</div><h3>Valor comercial frente a riesgo de mora</h3><p class="card-description">Corte de valor: mediana de facturación (S/ {value_cut:.1f}); riesgo alto: más de {risk_cut:.0f} días de mora promedio.</p></div>
        <div class="plot">{chart_html(fig_value_risk, "value-risk")}</div>
      </article>
    </div>
    <div class="insight-strip">
      <div class="insight clay"><div class="insight-title">Lima concentra {lima_share:.1f}%</div><p>Es el mayor mercado por volumen, pero conviene monitorear conversión y cobertura por región.</p></div>
      <div class="insight"><div class="insight-title">Cross-sell visible</div><p>La separación entre solo móvil, solo hogar y cartera combinada permite orientar el siguiente producto.</p></div>
      <div class="insight"><div class="insight-title">No maximizar venta ignorando riesgo</div><p>Los segmentos de alto valor con mora alta requieren una política distinta a un upsell convencional.</p></div>
    </div>
  </section>

  <section class="section" id="operacion">
    <div class="section-head">
      <div class="section-kicker">04 · Fricciones y acciones</div>
      <h2>Qué corregir en el proceso comercial</h2>
      <p class="section-intro">El Pareto identifica los motivos que concentran el rechazo; la cobertura de rebate muestra dónde ya existe una respuesta comercial.</p>
    </div>
    <div class="ops-grid">
      <div class="ops"><div class="ops-value">{fmt_int(n_no_contactados)}</div><div class="ops-label">Intentos sin contacto</div><div class="ops-note">{fmt_pct(n_no_contactados / n_ofrecim * 100)} del volumen de campaña</div></div>
      <div class="ops"><div class="ops-value">{fmt_int(n_same_plan)}</div><div class="ops-label">Ofertas del plan actual</div><div class="ops-note">Redundancia evitable con reglas de elegibilidad</div></div>
      <div class="ops"><div class="ops-value">{fmt_int(n_same_home)}</div><div class="ops-label">Ofertas hogar ya contratadas</div><div class="ops-note">Posible fricción por repetición</div></div>
      <div class="ops"><div class="ops-value">{fmt_int(n_sin_historial)}</div><div class="ops-label">Clientes sin campañas</div><div class="ops-note">Segmento cold start para el futuro modelo</div></div>
    </div>
    <div class="grid">
      <article class="card">
        <div class="card-head"><div class="question">Análisis de Pareto</div><h3>¿Qué explica la mayor parte del rechazo?</h3><p class="card-description">Los tres primeros motivos concentran {fmt_pct(top_three_share)} de todos los rechazos.</p></div>
        <div class="plot">{chart_html(fig_pareto, "pareto")}</div>
      </article>
      <article class="card">
        <div class="card-head"><div class="question">Respuesta al rechazo</div><h3>¿En qué motivos se usa el rebate?</h3><p class="card-description">Porcentaje de rechazos de cada motivo que recibió una contraoferta.</p></div>
        <div class="plot">{chart_html(fig_rebate, "rebate")}</div>
      </article>
    </div>
    <div class="insight-strip">
      <div class="insight clay"><div class="insight-title">Primera prueba: precio</div><p>Diseñar rebates acotados y medir margen incremental, no solo conversión.</p></div>
      <div class="insight"><div class="insight-title">Segunda prueba: relevancia</div><p>“No lo necesita” y “ya tiene algo similar” apuntan a mejorar targeting y reglas de exclusión.</p></div>
      <div class="insight"><div class="insight-title">Gestionar el cold start</div><p>{fmt_int(n_sin_historial)} clientes requieren reglas de negocio o perfiles similares antes de tener historial propio.</p></div>
    </div>

    <aside class="method">
      <h3>Cómo leer este dashboard</h3>
      <ul>
        <li>Todos los calculos provienen de <code>clientes_limpio.csv</code>, <code>catalogo_limpio.csv</code> e <code>historial_limpio.csv</code>.</li>
        <li>La conversión principal es aceptados/contactados; “pendiente” equivale a no contactado.</li>
        <li>Los resultados son descriptivos y no prueban causalidad.</li>
        <li>Las ofertas MT solo aparecen en clientes elegibles; su ventaja histórica debe validarse en una evaluación temporal.</li>
        <li>El historial contiene seis fechas mensuales, por lo que no permite concluir el mejor día u hora.</li>
        <li>Los datos son sintéticos y anonimizados; sirven para prototipo y análisis académico.</li>
      </ul>
    </aside>
  </section>

  <footer>Dashboard comercial · Personalizacion Comercial Inteligente · Generado directamente desde CSV · Enero–junio de 2026</footer>
</main>
</body>
</html>
"""

# Normaliza espacios finales que pueden venir incluidos en la libreria embebida.
html = "\n".join(line.rstrip() for line in html.splitlines()) + "\n"
OUTPUT_PATH.write_text(html, encoding="utf-8")
print(f"Dashboard creado: {OUTPUT_PATH.name}")
print(f"Tamaño: {OUTPUT_PATH.stat().st_size / 1024 / 1024:.2f} MB")
print("Gráficos: 12")
