from __future__ import annotations

import numpy as np
import pandas as pd

from .features import _bundle_services, mt_stage


CHANNELS = ["Digital", "Tienda", "Call In", "Call Out"]


def generate_candidates(customer: pd.Series, catalog: pd.DataFrame) -> pd.DataFrame:
    offers = catalog.rename(columns={"es_movistar_total": "oferta_es_movistar_total"})
    offers = offers.loc[offers.index.repeat(len(CHANNELS))].reset_index(drop=True)
    offers["canal"] = CHANNELS * len(catalog)
    for column, value in customer.items():
        if column not in offers:
            offers[column] = value
    return offers


def _strict_home_expansion(customer: pd.Series, offer: pd.Series, catalog: pd.DataFrame) -> bool:
    current_id = customer.get("oferta_hogar_id")
    current = catalog.loc[catalog["oferta_id"].eq(current_id)]
    if current.empty:
        current_services = {"internet"} if bool(customer.get("tiene_internet_hogar")) else set()
    else:
        current_services = _bundle_services(current.iloc[0].get("descripcion_bundle"))
    offered_services = _bundle_services(offer.get("descripcion_bundle"))
    return bool(offered_services > current_services)


def eligibility_mask(customer: pd.Series, candidates: pd.DataFrame, catalog: pd.DataFrame, config: dict) -> pd.Series:
    valid = pd.Series(True, index=candidates.index)
    valid &= candidates["oferta_id"].ne(customer.get("plan_actual_id"))
    valid &= candidates["oferta_id"].ne(customer.get("oferta_hogar_id"))
    active_offer_ids = set(customer.get("active_offer_ids", []) or [])
    if active_offer_ids:
        valid &= ~candidates["oferta_id"].isin(active_offer_ids)
    if bool(customer.get("es_movistar_total")) or not bool(customer.get("elegible_mt")):
        valid &= ~candidates["oferta_es_movistar_total"].astype(bool)
    mobile_required = (
        ((candidates["tipo_oferta"].isin(["upgrade", "equipo"])) & candidates["segmento_objetivo"].eq("movil"))
        | candidates["oferta_id"].eq("OF019")
    )
    if not bool(customer.get("tiene_movil")):
        valid &= ~mobile_required
    if not bool(customer.get("tiene_internet_hogar")):
        valid &= ~candidates["oferta_id"].isin(["OF013", "OF016"])
    if not (bool(customer.get("tiene_movil")) or bool(customer.get("tiene_hogar"))):
        valid &= ~candidates["oferta_id"].isin(["OF017", "OF018"])
    if bool(customer.get("tiene_hogar")):
        home_plan = candidates["tipo_oferta"].eq("plan_hogar")
        expansion = candidates.apply(lambda row: _strict_home_expansion(customer, row, catalog), axis=1)
        valid &= ~(home_plan & ~expansion)
    block_days = int(config["rejection_block_days"])
    days = (pd.Timestamp(config.get("as_of_date", pd.Timestamp.now())) - pd.to_datetime(candidates["last_rejection_date"])).dt.days
    valid &= ~(days.notna() & days.between(0, block_days, inclusive="both"))
    return valid


def eligibility_mask_frame(candidates: pd.DataFrame, catalog: pd.DataFrame, config: dict) -> pd.Series:
    """Versión vectorizada de elegibilidad para batches multi-cliente."""
    data = candidates
    reasons = eligibility_reasons_frame(data, catalog, config)
    return ~reasons.any(axis=1)


def eligibility_reasons_frame(candidates: pd.DataFrame, catalog: pd.DataFrame, config: dict) -> pd.DataFrame:
    """Diagnóstico auditable; una combinación puede tener más de un motivo de bloqueo."""
    data = candidates
    reasons = pd.DataFrame(index=data.index)
    reasons["current_product"] = data["oferta_id"].eq(data["plan_actual_id"]) | data["oferta_id"].eq(data["oferta_hogar_id"])
    if "active_offer_ids" in data:
        reasons["already_active_offer"] = data.apply(
            lambda row: row["oferta_id"] in set(row.get("active_offer_ids", []) or []), axis=1,
        )
    else:
        reasons["already_active_offer"] = False
    reasons["mt_ineligible_or_already_owned"] = (
        (data["es_movistar_total"].astype(bool) | ~data["elegible_mt"].astype(bool))
        & data["oferta_es_movistar_total"].astype(bool)
    )
    mobile_required = (
        (data["tipo_oferta"].isin(["upgrade", "equipo"]) & data["segmento_objetivo"].eq("movil"))
        | data["oferta_id"].eq("OF019")
    )
    reasons["mobile_service_required"] = ~data["tiene_movil"].astype(bool) & mobile_required
    reasons["home_internet_required"] = ~data["tiene_internet_hogar"].astype(bool) & data["oferta_id"].isin(["OF013", "OF016"])
    reasons["active_service_required"] = (
        ~data["tiene_movil"].astype(bool) & ~data["tiene_hogar"].astype(bool)
        & data["oferta_id"].isin(["OF017", "OF018"])
    )

    def code(value: object) -> int:
        services = _bundle_services(value)
        return int("internet" in services) + 2 * int("tv" in services) + 4 * int("fijo" in services)

    current_codes = catalog.set_index("oferta_id")["descripcion_bundle"].map(code)
    current = data["oferta_hogar_id"].map(current_codes)
    current = current.where(current.notna(), data["tiene_internet_hogar"].astype(int)).astype(int)
    offered = data["descripcion_bundle"].map(code).astype(int)
    expansion = offered.ne(current) & offered.map(int).combine(current.map(int), lambda left, right: (left | right) == left)
    home_plan = data["tipo_oferta"].eq("plan_hogar")
    reasons["home_not_strict_expansion"] = data["tiene_hogar"].astype(bool) & home_plan & ~expansion
    days = (pd.Timestamp(config.get("as_of_date", pd.Timestamp.now())) - pd.to_datetime(data["last_rejection_date"])).dt.days
    reasons["rejection_cooldown"] = days.notna() & days.between(0, int(config["rejection_block_days"]), inclusive="both")
    return reasons.astype(bool)


def score_candidates(customer: pd.Series, candidates: pd.DataFrame, catalog: pd.DataFrame, scoring: dict, rules: dict) -> pd.DataFrame:
    data = candidates.copy()
    bill = max(float(customer.get("monto_facturado_prom", 0) or 0), 1.0)
    price = data["precio_mensual"].astype(float)
    data["affordability_fit"] = (1 - np.maximum(price - bill, 0) / np.maximum(price, bill)).clip(0, 1)
    consumption = max(float(customer.get("consumo_datos_gb_prom", 0) or 0), 1.0)
    gb = data["gb_incluidos"].astype(float)
    capacity = np.where(
        gb.eq(9999), 1.0,
        np.where(gb.eq(0), 0.5, np.where(gb < consumption, (gb / consumption) ** 1.5, 1 / (1 + 0.25 * (gb - consumption) / consumption))),
    )
    data["capacity_fit"] = np.clip(capacity, 0, 1)
    stage = mt_stage(customer)
    completes_path = (
        ((stage == "falta_internet_hogar") & data["tipo_oferta"].eq("plan_hogar") & data["descripcion_bundle"].astype(str).str.contains("Internet", case=False))
        | ((stage == "falta_movil_postpago") & data["tipo_oferta"].eq("plan_movil"))
    )
    mt_direct = bool(customer.get("elegible_mt")) & data["oferta_es_movistar_total"].astype(bool)
    data["mt_path_fit"] = np.where(mt_direct | completes_path, 1.0, 0.5)
    data["fit_cliente"] = 0.40 * data["affordability_fit"] + 0.35 * data["capacity_fit"] + 0.25 * data["mt_path_fit"]
    low, high = float(catalog["precio_mensual"].min()), float(catalog["precio_mensual"].max())
    data["valor_negocio"] = ((price - low) / max(high - low, 1)).clip(0, 1)
    data["bonus_ruta_mt"] = np.where(mt_direct, 1.0, np.where(completes_path, 0.7, 0.0))
    days = (pd.Timestamp(rules.get("as_of_date", pd.Timestamp.now())) - pd.to_datetime(data["last_rejection_date"])).dt.days
    data["penalizacion_cooldown"] = np.where(
        days.between(int(rules["rejection_block_days"]) + 1, int(rules["rejection_penalty_days"]), inclusive="both"),
        float(rules["cooldown_penalty"]), 0.0,
    )
    data["p_venta"] = (data["p_contacto"] * data["p_aceptacion"]).clip(0, 1)
    data["score_conversion_component"] = float(scoring["w_conversion"]) * data["p_venta"]
    data["score_fit_component"] = float(scoring["w_fit"]) * data["fit_cliente"]
    data["score_business_component"] = float(scoring["w_business"]) * data["valor_negocio"]
    data["score_mt_component"] = float(scoring["w_mt"]) * data["bonus_ruta_mt"]
    data["score_friction_component"] = -float(scoring["w_friction"]) * data["friccion_candidato"]
    data["score_cooldown_component"] = -data["penalizacion_cooldown"]
    data["score_raw"] = data[[
        "score_conversion_component", "score_fit_component", "score_business_component",
        "score_mt_component", "score_friction_component", "score_cooldown_component",
    ]].sum(axis=1)
    data["score"] = data["score_raw"].clip(0, 1)
    return data


def score_candidate_frame(candidates: pd.DataFrame, catalog: pd.DataFrame, scoring: dict, rules: dict) -> pd.DataFrame:
    """Versión vectorizada del score, equivalente para candidatos con columnas de cliente."""
    data = candidates.copy()
    bill = pd.to_numeric(data["monto_facturado_prom"], errors="coerce").fillna(0).clip(lower=1.0)
    price = pd.to_numeric(data["precio_mensual"], errors="coerce")
    data["affordability_fit"] = (1 - np.maximum(price - bill, 0) / np.maximum(price, bill)).clip(0, 1)
    consumption = pd.to_numeric(data["consumo_datos_gb_prom"], errors="coerce").fillna(0).clip(lower=1.0)
    gb = pd.to_numeric(data["gb_incluidos"], errors="coerce")
    data["capacity_fit"] = np.clip(np.where(
        gb.eq(9999), 1.0,
        np.where(gb.eq(0), 0.5, np.where(gb < consumption, (gb / consumption) ** 1.5, 1 / (1 + .25 * (gb - consumption) / consumption))),
    ), 0, 1)
    completes_path = (
        (data["etapa_mt"].eq("falta_internet_hogar") & data["tipo_oferta"].eq("plan_hogar") & data["descripcion_bundle"].astype(str).str.contains("Internet", case=False))
        | (data["etapa_mt"].eq("falta_movil_postpago") & data["tipo_oferta"].eq("plan_movil"))
    )
    mt_direct = data["elegible_mt"].astype(bool) & data["oferta_es_movistar_total"].astype(bool)
    data["mt_path_fit"] = np.where(mt_direct | completes_path, 1.0, .5)
    data["fit_cliente"] = .40 * data["affordability_fit"] + .35 * data["capacity_fit"] + .25 * data["mt_path_fit"]
    low, high = float(catalog["precio_mensual"].min()), float(catalog["precio_mensual"].max())
    data["valor_negocio"] = ((price - low) / max(high - low, 1)).clip(0, 1)
    data["bonus_ruta_mt"] = np.where(mt_direct, 1.0, np.where(completes_path, .7, 0.0))
    days = (pd.Timestamp(rules.get("as_of_date", pd.Timestamp.now())) - pd.to_datetime(data["last_rejection_date"])).dt.days
    data["penalizacion_cooldown"] = np.where(
        days.between(int(rules["rejection_block_days"]) + 1, int(rules["rejection_penalty_days"]), inclusive="both"),
        float(rules["cooldown_penalty"]), 0.0,
    )
    data["p_venta"] = (data["p_contacto"] * data["p_aceptacion"]).clip(0, 1)
    data["score_conversion_component"] = float(scoring["w_conversion"]) * data["p_venta"]
    data["score_fit_component"] = float(scoring["w_fit"]) * data["fit_cliente"]
    data["score_business_component"] = float(scoring["w_business"]) * data["valor_negocio"]
    data["score_mt_component"] = float(scoring["w_mt"]) * data["bonus_ruta_mt"]
    data["score_friction_component"] = -float(scoring["w_friction"]) * data["friccion_candidato"]
    data["score_cooldown_component"] = -data["penalizacion_cooldown"]
    data["score_raw"] = data[[
        "score_conversion_component", "score_fit_component", "score_business_component",
        "score_mt_component", "score_friction_component", "score_cooldown_component",
    ]].sum(axis=1)
    data["score"] = data["score_raw"].clip(0, 1)
    return data


def best_channel_then_rank(candidates: pd.DataFrame, top_n: int = 3) -> pd.DataFrame:
    best = candidates.sort_values(["p_venta", "score"], ascending=False).drop_duplicates("oferta_id", keep="first")
    return best.sort_values(["score", "p_venta", "oferta_id"], ascending=[False, False, True]).head(top_n).reset_index(drop=True)
