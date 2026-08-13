from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd


CHANNELS = ["Digital", "Tienda", "Call In", "Call Out"]
TARGET_COLUMNS = {"resultado", "contactabilidad", "motivo_rechazo", "medio_probatorio", "es_rebate"}


def mt_stage(customer: pd.Series | dict) -> str:
    get = customer.get
    if bool(get("es_movistar_total", False)):
        return "ya_es_mt"
    if bool(get("elegible_mt", False)):
        return "elegible_mt"
    if bool(get("tiene_movil", False)) and get("tipo_cliente") == "postpago" and not bool(get("tiene_internet_hogar", False)):
        return "falta_internet_hogar"
    if bool(get("tiene_internet_hogar", False)) and not (bool(get("tiene_movil", False)) and get("tipo_cliente") == "postpago"):
        return "falta_movil_postpago"
    return "no_elegible_actual"


def _prior_month_aggregates(events: pd.DataFrame, keys: list[str], prefix: str) -> pd.DataFrame:
    work = events[keys + ["event_month", "_offer", "_contact", "_accept", "_reject", "_pending", "_price_reject"]].copy()
    grouped = work.groupby(keys + ["event_month"], observed=True, dropna=False)[
        ["_offer", "_contact", "_accept", "_reject", "_pending", "_price_reject"]
    ].sum().reset_index()
    grouped = grouped.sort_values(keys + ["event_month"])
    metrics = ["_offer", "_contact", "_accept", "_reject", "_pending", "_price_reject"]
    for metric in metrics:
        grouped[f"{prefix}{metric}"] = grouped.groupby(keys, observed=True, dropna=False)[metric].cumsum() - grouped[metric]
    return grouped[keys + ["event_month"] + [f"{prefix}{x}" for x in metrics]]


def _merge_prior(events: pd.DataFrame, keys: list[str], prefix: str) -> pd.DataFrame:
    aggregate = _prior_month_aggregates(events, keys, prefix)
    return events.merge(aggregate, on=keys + ["event_month"], how="left", validate="many_to_one")


def build_historical_features(
    customers: pd.DataFrame,
    catalog: pd.DataFrame,
    history: pd.DataFrame,
    alpha: float = 10.0,
    friction_weights: dict[str, float] | None = None,
) -> pd.DataFrame:
    """Build one training row per event using only completed earlier months."""
    duplicated_history = {"tipo_cliente", "antiguedad_meses", "elegible_mt", "es_movistar_total", "nombre_oferta", "tipo_oferta", "oferta_es_mt"}
    events = history.drop(columns=list(duplicated_history.intersection(history.columns))).copy()
    events = events.merge(customers, on="cliente_id", how="left", validate="many_to_one")
    offer_catalog = catalog.rename(columns={"es_movistar_total": "oferta_es_movistar_total"})
    events = events.merge(offer_catalog, on="oferta_id", how="left", validate="many_to_one")
    events["event_month"] = events["fecha"].dt.to_period("M").astype(str)
    events["_offer"] = 1
    events["_contact"] = events["contactabilidad"].eq("contactado").astype(int)
    events["_accept"] = events["resultado"].eq("aceptada").astype(int)
    events["_reject"] = events["resultado"].eq("rechazada").astype(int)
    events["_pending"] = events["resultado"].eq("pendiente").astype(int)
    events["_price_reject"] = ((events["resultado"] == "rechazada") & (events["motivo_rechazo"] == "precio")).astype(int)

    for keys, prefix in (
        (["cliente_id"], "hist_client"),
        (["cliente_id", "canal"], "hist_channel"),
        (["cliente_id", "oferta_id"], "hist_offer"),
        (["cliente_id", "tipo_oferta"], "hist_type"),
    ):
        events = _merge_prior(events, keys, prefix)

    segment = events["tipo_cliente"].fillna("sin_linea_movil")
    events["_segment"] = segment
    events = _merge_prior(events, ["_segment", "canal"], "hist_segment_channel")
    events = _merge_prior(events, ["canal"], "hist_global_channel")
    events = _merge_prior(events.assign(_all="all"), ["_all"], "hist_global")

    for keys, output in ((["cliente_id"], "last_client_event"), (["cliente_id", "oferta_id"], "last_offer_event")):
        monthly = events.groupby(keys + ["event_month"], observed=True, dropna=False)["fecha"].max().reset_index()
        monthly = monthly.sort_values(keys + ["event_month"])
        monthly[output] = monthly.groupby(keys, observed=True, dropna=False)["fecha"].shift(1).groupby(
            [monthly[key] for key in keys], observed=True, dropna=False
        ).cummax()
        events = events.merge(monthly[keys + ["event_month", output]], on=keys + ["event_month"], how="left", validate="many_to_one")
    events["days_since_last_client_offer"] = (events["fecha"] - events["last_client_event"]).dt.days
    events["days_since_last_offer"] = (events["fecha"] - events["last_offer_event"]).dt.days

    for col in [c for c in events if c.startswith("hist_")]:
        events[col] = events[col].fillna(0.0)
    global_contact = events["hist_global_contact"] / events["hist_global_offer"].clip(lower=1)
    global_accept = events["hist_global_accept"] / events["hist_global_contact"].clip(lower=1)
    channel_contact = (events["hist_global_channel_contact"] + alpha * global_contact) / (events["hist_global_channel_offer"] + alpha)
    channel_accept = (events["hist_global_channel_accept"] + alpha * global_accept) / (events["hist_global_channel_contact"] + alpha)
    segment_contact = (events["hist_segment_channel_contact"] + alpha * channel_contact) / (events["hist_segment_channel_offer"] + alpha)
    segment_accept = (events["hist_segment_channel_accept"] + alpha * channel_accept) / (events["hist_segment_channel_contact"] + alpha)
    events["hist_contact_rate_channel"] = (events["hist_channel_contact"] + alpha * segment_contact) / (events["hist_channel_offer"] + alpha)
    events["hist_accept_rate_channel"] = (events["hist_channel_accept"] + alpha * segment_accept) / (events["hist_channel_contact"] + alpha)
    return add_pair_features(events, friction_weights)


def apply_smoothing_alpha(frame: pd.DataFrame, alpha: float) -> pd.DataFrame:
    """Recalcula solo las tasas suavizadas a partir de acumulados ya leakage-safe."""
    data = frame.copy()
    global_contact = data["hist_global_contact"] / data["hist_global_offer"].clip(lower=1)
    global_accept = data["hist_global_accept"] / data["hist_global_contact"].clip(lower=1)
    channel_contact = (data["hist_global_channel_contact"] + alpha * global_contact) / (data["hist_global_channel_offer"] + alpha)
    channel_accept = (data["hist_global_channel_accept"] + alpha * global_accept) / (data["hist_global_channel_contact"] + alpha)
    segment_contact = (data["hist_segment_channel_contact"] + alpha * channel_contact) / (data["hist_segment_channel_offer"] + alpha)
    segment_accept = (data["hist_segment_channel_accept"] + alpha * channel_accept) / (data["hist_segment_channel_contact"] + alpha)
    data["hist_contact_rate_channel"] = (data["hist_channel_contact"] + alpha * segment_contact) / (data["hist_channel_offer"] + alpha)
    data["hist_accept_rate_channel"] = (data["hist_channel_accept"] + alpha * segment_accept) / (data["hist_channel_contact"] + alpha)
    return data


def _bundle_services(value: object) -> set[str]:
    text = str(value).lower()
    services = set()
    if "internet" in text:
        services.add("internet")
    if "tv" in text:
        services.add("tv")
    if "telefon" in text or "fijo" in text:
        services.add("fijo")
    return services


def add_pair_features(frame: pd.DataFrame, friction_weights: dict[str, float] | None = None) -> pd.DataFrame:
    data = frame.copy()
    bill = pd.to_numeric(data["monto_facturado_prom"], errors="coerce").clip(lower=1.0)
    price = pd.to_numeric(data["precio_mensual"], errors="coerce")
    gb = pd.to_numeric(data["gb_incluidos"], errors="coerce")
    consumption = pd.to_numeric(data["consumo_datos_gb_prom"], errors="coerce").fillna(0)
    data["delta_precio"] = price - bill
    data["precio_vs_facturacion"] = data["delta_precio"] / bill
    data["ratio_precio_facturacion"] = price / bill
    data["ratio_facturacion_6m_actual"] = pd.to_numeric(data["monto_facturado_prom_6m"], errors="coerce") / bill
    data["actividad_por_mes"] = pd.to_numeric(data["n_actividad_canal"], errors="coerce") / 6.0
    data["reclamos_por_antiguedad"] = pd.to_numeric(data["n_reclamos"], errors="coerce") / pd.to_numeric(data["antiguedad_meses"], errors="coerce").clip(lower=1)
    data["mora_riesgo"] = (pd.to_numeric(data["dias_mora_prom"], errors="coerce").clip(0, 60) / 60 + pd.to_numeric(data["meses_moroso"], errors="coerce").clip(0, 6) / 6) / 2
    data["oferta_es_ilimitada"] = gb.eq(9999).astype(int)
    data["gap_gb"] = np.where(gb.eq(9999), np.nan, gb - consumption)
    data["etapa_mt"] = data.apply(mt_stage, axis=1)
    for kind, name in (
        ("plan_movil", "oferta_es_movil"), ("plan_hogar", "oferta_es_hogar"),
        ("upgrade", "oferta_es_upgrade"), ("equipo", "oferta_es_equipo"),
        ("paquete_adicional", "oferta_es_paquete"), ("movistar_total", "oferta_es_mt"),
    ):
        data[name] = data["tipo_oferta"].eq(kind).astype(int)
    data["match_canal_preferido"] = data["canal"].eq(data["canal_mas_usado"]).astype(int)
    rejects = data.get("hist_client_reject", pd.Series(0, index=data.index)).astype(float)
    price_rejects = data.get("hist_client_price_reject", pd.Series(0, index=data.index)).astype(float)
    data["sensibilidad_precio"] = price_rejects / rejects.clip(lower=1)
    recent = data.get("recent_offers_30d", pd.Series(0, index=data.index)).astype(float)
    data["fatiga_comercial"] = np.maximum(
        np.minimum(data.get("hist_client_offer", 0).astype(float) / 6.0, 1.0),
        np.minimum(recent / 4.0, 1.0),
    )
    weights = friction_weights or {"mora": 0.20, "delinquency": 0.20, "complaints": 0.20, "fatigue": 0.40}
    friction = (
        float(weights["mora"]) * pd.to_numeric(data["dias_mora_prom"], errors="coerce").clip(0, 60) / 60
        + float(weights["delinquency"]) * pd.to_numeric(data["meses_moroso"], errors="coerce").clip(0, 6) / 6
        + float(weights["complaints"]) * pd.to_numeric(data["n_reclamos"], errors="coerce").clip(0, 5) / 5
        + float(weights["fatigue"]) * data["fatiga_comercial"]
    )
    data["friccion_cliente"] = friction.clip(0, 1)
    data["presion_precio"] = np.maximum(price - bill, 0) / np.maximum(price, bill)
    data["friccion_candidato"] = (data["friccion_cliente"] * data["presion_precio"]).clip(0, 1)
    return data


@dataclass
class InferenceHistory:
    as_of: pd.Timestamp
    client: pd.DataFrame
    client_channel: pd.DataFrame
    client_offer: pd.DataFrame
    client_type: pd.DataFrame
    last_rejection: pd.DataFrame
    last_client_event: pd.DataFrame
    last_offer_event: pd.DataFrame
    recent_client: pd.DataFrame
    global_rates: dict
    segment_channel_rates: pd.DataFrame


def summarize_history(history: pd.DataFrame, catalog: pd.DataFrame, as_of: str | pd.Timestamp, alpha: float = 10.0) -> InferenceHistory:
    as_of_ts = pd.Timestamp(as_of)
    # El tipo de oferta del catálogo es maestro; se descarta su copia histórica.
    history_base = history.drop(columns=["tipo_oferta"], errors="ignore")
    events = history_base.loc[history_base["fecha"] < as_of_ts].merge(catalog[["oferta_id", "tipo_oferta"]], on="oferta_id", how="left")
    events = events.assign(
        offer=1,
        contact=events["contactabilidad"].eq("contactado").astype(int),
        accept=events["resultado"].eq("aceptada").astype(int),
        reject=events["resultado"].eq("rechazada").astype(int),
        pending=events["resultado"].eq("pendiente").astype(int),
        price_reject=((events["resultado"] == "rechazada") & (events["motivo_rechazo"] == "precio")).astype(int),
    )
    metrics = ["offer", "contact", "accept", "reject", "pending", "price_reject"]
    client = events.groupby("cliente_id", observed=True)[metrics].sum().add_prefix("hist_client_")
    client_channel = events.groupby(["cliente_id", "canal"], observed=True)[metrics].sum().add_prefix("hist_channel_")
    client_offer = events.groupby(["cliente_id", "oferta_id"], observed=True)[metrics].sum().add_prefix("hist_offer_")
    client_type = events.groupby(["cliente_id", "tipo_oferta"], observed=True)[metrics].sum().add_prefix("hist_type_")
    rejected = events.loc[events["resultado"] == "rechazada"]
    last_rejection = rejected.groupby(["cliente_id", "oferta_id"], observed=True)["fecha"].max().to_frame("last_rejection_date")
    last_client_event = events.groupby("cliente_id", observed=True)["fecha"].max().to_frame("last_client_event")
    last_offer_event = events.groupby(["cliente_id", "oferta_id"], observed=True)["fecha"].max().to_frame("last_offer_event")
    recent = events.loc[events["fecha"] >= as_of_ts - pd.Timedelta(days=30)].groupby("cliente_id", observed=True)["offer"].sum().to_frame("recent_offers_30d")
    global_offer = max(float(events["offer"].sum()), 1)
    global_contact = float(events["contact"].sum()) / global_offer
    global_accept = float(events["accept"].sum()) / max(float(events["contact"].sum()), 1)
    channel = events.groupby("canal", observed=True)[metrics].sum()
    channel["contact_rate"] = (channel["contact"] + alpha * global_contact) / (channel["offer"] + alpha)
    channel["accept_rate"] = (channel["accept"] + alpha * global_accept) / (channel["contact"] + alpha)
    segments = events.groupby(["tipo_cliente", "canal"], observed=True)[metrics].sum()
    channel_prior = channel[["contact_rate", "accept_rate"]].rename(
        columns={"contact_rate": "contact_rate_channel", "accept_rate": "accept_rate_channel"}
    )
    segments = segments.join(channel_prior, on="canal")
    segments["contact_rate"] = (segments["contact"] + alpha * segments["contact_rate_channel"]) / (segments["offer"] + alpha)
    segments["accept_rate"] = (segments["accept"] + alpha * segments["accept_rate_channel"]) / (segments["contact"] + alpha)
    return InferenceHistory(as_of_ts, client, client_channel, client_offer, client_type, last_rejection, last_client_event, last_offer_event, recent, {"contact": global_contact, "accept": global_accept, "channel": channel}, segments)


def attach_inference_history(candidates: pd.DataFrame, summary: InferenceHistory, alpha: float = 10.0, friction_weights: dict[str, float] | None = None) -> pd.DataFrame:
    data = candidates.copy()
    data = data.join(summary.client, on="cliente_id")
    data = data.join(summary.client_channel, on=["cliente_id", "canal"])
    data = data.join(summary.client_offer, on=["cliente_id", "oferta_id"])
    data = data.join(summary.client_type, on=["cliente_id", "tipo_oferta"])
    data = data.join(summary.last_rejection, on=["cliente_id", "oferta_id"])
    data = data.join(summary.last_client_event, on="cliente_id")
    data = data.join(summary.last_offer_event, on=["cliente_id", "oferta_id"])
    data = data.join(summary.recent_client, on="cliente_id")
    data["recent_offers_30d"] = data["recent_offers_30d"].fillna(0.0)
    data["days_since_last_client_offer"] = (summary.as_of - pd.to_datetime(data["last_client_event"])).dt.days
    data["days_since_last_offer"] = (summary.as_of - pd.to_datetime(data["last_offer_event"])).dt.days
    hist_cols = [col for col in data if col.startswith("hist_")]
    data[hist_cols] = data[hist_cols].fillna(0.0)
    segment_idx = pd.MultiIndex.from_arrays([data["tipo_cliente"], data["canal"]])
    segment_contact = summary.segment_channel_rates["contact_rate"].reindex(segment_idx).to_numpy()
    segment_accept = summary.segment_channel_rates["accept_rate"].reindex(segment_idx).to_numpy()
    channel_contact = data["canal"].map(summary.global_rates["channel"]["contact_rate"])
    channel_accept = data["canal"].map(summary.global_rates["channel"]["accept_rate"])
    segment_contact = np.where(pd.isna(segment_contact), channel_contact, segment_contact)
    segment_accept = np.where(pd.isna(segment_accept), channel_accept, segment_accept)
    data["hist_contact_rate_channel"] = (data["hist_channel_contact"] + alpha * segment_contact) / (data["hist_channel_offer"] + alpha)
    data["hist_accept_rate_channel"] = (data["hist_channel_accept"] + alpha * segment_accept) / (data["hist_channel_contact"] + alpha)
    return add_pair_features(data, friction_weights)


def model_feature_columns(frame: pd.DataFrame) -> tuple[list[str], list[str]]:
    excluded = TARGET_COLUMNS | {
        "ofrecimiento_id", "fecha", "event_month", "_all", "_segment", "last_rejection_date",
        "last_client_event", "last_offer_event", "descripcion_corta", "descripcion_bundle",
        "cliente_id", "nombre_oferta", "oferta_es_movistar_total",
    }
    features = [
        c for c in frame.columns
        if c not in excluded and not c.startswith("_")
        and not c.startswith("hist_segment_channel") and not c.startswith("hist_global")
    ]
    numeric = [c for c in features if pd.api.types.is_numeric_dtype(frame[c]) and not pd.api.types.is_bool_dtype(frame[c])]
    categorical = [c for c in features if c not in numeric]
    return categorical, numeric
