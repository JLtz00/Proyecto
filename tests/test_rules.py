from __future__ import annotations

import pandas as pd

from nbo.rules import (
    best_channel_then_rank, eligibility_mask, eligibility_mask_frame, generate_candidates,
    score_candidate_frame, score_candidates,
)


RULES = {"rejection_block_days": 14, "rejection_penalty_days": 30, "cooldown_penalty": 0.12, "fatigue_threshold": 3, "as_of_date": "2026-08-13"}
SCORING = {"w_conversion": .5, "w_fit": .2, "w_business": .1, "w_mt": .1, "w_friction": .1}


def eligible_ids(customer, catalog):
    candidates = generate_candidates(customer, catalog)
    candidates["last_rejection_date"] = pd.NaT
    return set(candidates.loc[eligibility_mask(customer, candidates, catalog, RULES), "oferta_id"])


def test_eligible_mt_can_receive_mt(customer, catalog):
    assert "OF020" in eligible_ids(customer, catalog)


def test_existing_mt_cannot_receive_mt(customer, catalog):
    customer["es_movistar_total"] = True
    customer["elegible_mt"] = False
    assert "OF020" not in eligible_ids(customer, catalog)


def test_customer_without_mobile_can_acquire_plan_but_not_upgrade(customer, catalog):
    customer["tiene_movil"] = False
    customer["tipo_cliente"] = "sin_linea_movil"
    customer["elegible_mt"] = False
    ids = eligible_ids(customer, catalog)
    assert "OF001" in ids
    assert "OF011" not in ids
    assert "OF019" not in ids


def test_existing_home_only_allows_strict_bundle_expansion(customer, catalog):
    ids = eligible_ids(customer, catalog)
    assert "OF005" not in ids
    assert "OF008" in ids


def test_home_upgrade_and_router_require_internet(customer, catalog):
    customer["tiene_internet_hogar"] = False
    customer["elegible_mt"] = False
    ids = eligible_ids(customer, catalog)
    assert "OF013" not in ids
    assert "OF016" not in ids


def test_current_product_and_recent_rejection_are_blocked(customer, catalog):
    candidates = generate_candidates(customer, catalog)
    candidates["last_rejection_date"] = pd.NaT
    candidates.loc[candidates["oferta_id"].eq("OF001"), "last_rejection_date"] = pd.Timestamp("2026-08-05")
    ids = set(candidates.loc[eligibility_mask(customer, candidates, catalog, RULES), "oferta_id"])
    assert "OF002" not in ids
    assert "OF001" not in ids


def test_score_formula_and_unique_top_three(customer, catalog):
    candidates = generate_candidates(customer, catalog.iloc[[0, 3, 9]])
    candidates["p_contacto"] = .8
    candidates["p_aceptacion"] = .5
    candidates["friccion_candidato"] = .2
    candidates["last_rejection_date"] = pd.NaT
    scored = score_candidates(customer, candidates, catalog, SCORING, RULES)
    expected = .5 * .4 + .2 * scored.iloc[0]["fit_cliente"] + .1 * scored.iloc[0]["valor_negocio"] + .1 * scored.iloc[0]["bonus_ruta_mt"] - .1 * .2
    assert scored.iloc[0]["score"] == max(0, min(1, expected))
    top = best_channel_then_rank(scored)
    assert top["oferta_id"].is_unique
    assert top["score"].is_monotonic_decreasing


def test_vectorized_rules_and_score_match_scalar(customer, catalog):
    candidates = generate_candidates(customer, catalog)
    candidates["last_rejection_date"] = pd.NaT
    scalar_mask = eligibility_mask(customer, candidates, catalog, RULES)
    frame_mask = eligibility_mask_frame(candidates, catalog, RULES)
    assert scalar_mask.tolist() == frame_mask.tolist()
    eligible = candidates.loc[scalar_mask].copy()
    eligible["p_contacto"] = .8
    eligible["p_aceptacion"] = .5
    eligible["friccion_candidato"] = .2
    eligible["etapa_mt"] = "elegible_mt"
    scalar = score_candidates(customer, eligible, catalog, SCORING, RULES)
    vectorized = score_candidate_frame(eligible, catalog, SCORING, RULES)
    assert scalar["score"].round(12).tolist() == vectorized["score"].round(12).tolist()
