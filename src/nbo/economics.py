from __future__ import annotations

import pandas as pd

from .rules import best_channel_then_rank
from .schemas import EconomicOfferResult, EconomicSimulationRequest, EconomicSimulationResponse


FORMULA = "P(venta) × (precio × tasa_margen × meses) − costo_canal − tasa_uso_rebate × costo_rebate − friccion × penalizacion_experiencia"


def simulate_economics(engine, request: EconomicSimulationRequest) -> EconomicSimulationResponse:
    if request.cliente_id not in engine.customer_index.index:
        raise KeyError(request.cliente_id)
    customer = engine.customer_index.loc[request.cliente_id].copy()
    candidates, _ = engine._override_candidates(customer)
    official = best_channel_then_rank(candidates, len(engine.catalog)).copy().reset_index(drop=True)
    official["official_rank"] = official.index + 1
    assumptions = request.assumptions
    official["expected_margin"] = (
        official["precio_mensual"].astype(float) * assumptions.margin_rate * assumptions.expected_months
    )
    official["channel_cost"] = official["canal"].map(assumptions.channel_costs).fillna(0.0)
    official["rebate_cost_component"] = assumptions.expected_rebate_use_rate * assumptions.rebate_cost
    official["experience_penalty"] = official["friccion_candidato"] * assumptions.max_experience_penalty
    official["expected_value"] = (
        official["p_venta"] * official["expected_margin"] - official["channel_cost"]
        - official["rebate_cost_component"] - official["experience_penalty"]
    )
    ranked = official.sort_values(["expected_value", "score"], ascending=False).head(3).copy()
    ranked["economic_rank"] = range(1, len(ranked) + 1)
    rows = [EconomicOfferResult(
        oferta_id=str(row["oferta_id"]), nombre_oferta=str(row["nombre_oferta"]), canal=str(row["canal"]),
        official_rank=int(row["official_rank"]), economic_rank=int(row["economic_rank"]),
        expected_margin=float(row["expected_margin"]), expected_value=float(row["expected_value"]),
        components={
            "sale_weighted_margin": float(row["p_venta"] * row["expected_margin"]),
            "channel_cost": -float(row["channel_cost"]),
            "rebate_cost": -float(row["rebate_cost_component"]),
            "experience_penalty": -float(row["experience_penalty"]),
        },
    ) for _, row in ranked.iterrows()]
    return EconomicSimulationResponse(
        cliente_id=request.cliente_id, assumptions=assumptions, formula=FORMULA,
        official_offer_id=str(official.iloc[0]["oferta_id"]), economic_top3=rows,
        disclaimer="Escenario ilustrativo: el dataset no contiene margen, costos ni permanencia reales. No reemplaza el ranking oficial.",
    )
