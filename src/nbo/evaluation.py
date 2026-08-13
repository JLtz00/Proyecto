from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .config import load_config
from .data import clean_semantic_nulls, load_raw
from .engine import NBOEngine
from .splits import load_split_manifest


def _ranking_metrics(targets: pd.Series, ranked: pd.DataFrame) -> dict[str, float]:
    target_map = targets.to_dict()
    ranks: list[int | None] = []
    for client_id, target in target_map.items():
        offers = ranked.loc[ranked["cliente_id"].eq(client_id), "oferta_id"].tolist()
        ranks.append(offers.index(target) + 1 if target in offers else None)
    return {
        "hit_at_1": float(np.mean([rank == 1 for rank in ranks])) if ranks else 0.0,
        "hit_at_3": float(np.mean([rank is not None and rank <= 3 for rank in ranks])) if ranks else 0.0,
        "ndcg_at_3": float(np.mean([1 / math.log2(rank + 1) if rank and rank <= 3 else 0 for rank in ranks])) if ranks else 0.0,
    }


def _score_with_weights(frame: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    return (
        float(weights["w_conversion"]) * frame["p_venta"]
        + float(weights["w_fit"]) * frame["fit_cliente"]
        + float(weights["w_business"]) * frame["valor_negocio"]
        + float(weights["w_mt"]) * frame["bonus_ruta_mt"]
        - float(weights["w_friction"]) * frame["friccion_candidato"]
        - frame["penalizacion_cooldown"]
    ).clip(0, 1)


def _rank_candidates(candidates: pd.DataFrame, weights: dict[str, float]) -> pd.DataFrame:
    best_channel = candidates.sort_values(
        ["cliente_id", "oferta_id", "p_venta", "score"], ascending=[True, True, False, False]
    ).drop_duplicates(["cliente_id", "oferta_id"], keep="first").copy()
    best_channel["score_trial"] = _score_with_weights(best_channel, weights)
    return best_channel.sort_values(
        ["cliente_id", "score_trial", "p_venta", "oferta_id"],
        ascending=[True, False, False, True],
    ).groupby("cliente_id", observed=True).head(3)


def _weight_candidates(config: dict, seed: int) -> list[dict[str, float]]:
    defaults = config["scoring"]
    candidates = [dict(defaults)]
    rng = np.random.default_rng(seed)
    while len(candidates) < int(config["ranking"]["weight_trials"]):
        friction = float(rng.uniform(.05, .15))
        conversion = float(rng.uniform(.45, .60))
        fit = float(rng.uniform(.18, .30))
        business = float(rng.uniform(.03, .10))
        mt = .90 - conversion - fit - business
        if not .03 <= mt <= .14:
            continue
        candidates.append({
            "w_conversion": conversion, "w_fit": fit,
            "w_business": business, "w_mt": mt,
            "w_friction": friction,
        })
    return candidates


def _event_universe(
    history: pd.DataFrame, assignments: dict[str, str], split_name: str, max_clients: int | None
) -> pd.DataFrame:
    mask = history["cliente_id"].map(assignments).eq(split_name) & history["resultado"].eq("aceptada")
    events = history.loc[mask].sort_values("fecha").drop_duplicates("cliente_id", keep="last")
    if max_clients:
        events = events.head(max_clients)
    return events[["cliente_id", "oferta_id", "canal", "fecha"]].rename(
        columns={"oferta_id": "target_offer", "canal": "target_channel"}
    )


def _build_candidate_universe(engine: NBOEngine, events: pd.DataFrame, chunk_size: int = 300) -> tuple[pd.DataFrame, pd.DataFrame]:
    blocks = []
    eligible_events = []
    work = events.assign(cutoff=events["fecha"].dt.to_period("M").dt.start_time)
    for cutoff, month_events in work.groupby("cutoff", observed=True):
        records = month_events.set_index("cliente_id")
        ids = records.index.tolist()
        for start in range(0, len(ids), chunk_size):
            chunk_ids = ids[start:start + chunk_size]
            candidates = engine.candidate_scores_as_of(chunk_ids, cutoff)
            target_map = records.loc[chunk_ids, "target_offer"]
            candidates["target_offer"] = candidates["cliente_id"].map(target_map)
            eligible = candidates.groupby("cliente_id", observed=True).apply(
                lambda group: bool(group["oferta_id"].eq(group["target_offer"].iloc[0]).any()),
                include_groups=False,
            )
            valid_ids = eligible[eligible].index.tolist()
            if valid_ids:
                blocks.append(candidates.loc[candidates["cliente_id"].isin(valid_ids)])
                eligible_events.append(month_events.loc[month_events["cliente_id"].isin(valid_ids)])
    return (
        pd.concat(blocks, ignore_index=True) if blocks else pd.DataFrame(),
        pd.concat(eligible_events, ignore_index=True) if eligible_events else pd.DataFrame(),
    )


def _popular_baselines(
    history: pd.DataFrame,
    customers: pd.DataFrame,
    assignments: dict[str, str],
    events: pd.DataFrame,
    candidates: pd.DataFrame,
) -> dict[str, dict[str, float]]:
    rankings: dict[str, list[dict]] = {"global_popular": [], "segment_popular": [], "channel_popular": []}
    customer_type = customers.set_index("cliente_id")["tipo_cliente"]
    for cutoff, month_events in events.assign(cutoff=events["fecha"].dt.to_period("M").dt.start_time).groupby("cutoff", observed=True):
        prior = history.loc[
            history["cliente_id"].map(assignments).eq("train")
            & history["resultado"].eq("aceptada")
            & history["fecha"].lt(cutoff)
        ].copy()
        prior["tipo_cliente_master"] = prior["cliente_id"].map(customer_type)
        global_order = prior["oferta_id"].value_counts().index.tolist()
        by_segment = prior.groupby("tipo_cliente_master", observed=True)["oferta_id"].agg(lambda values: values.value_counts().index.tolist()).to_dict()
        by_channel = prior.groupby("canal", observed=True)["oferta_id"].agg(lambda values: values.value_counts().index.tolist()).to_dict()
        for _, event in month_events.iterrows():
            client_id = event["cliente_id"]
            eligible = set(candidates.loc[candidates["cliente_id"].eq(client_id), "oferta_id"])
            orders = {
                "global_popular": global_order,
                "segment_popular": by_segment.get(customer_type.get(client_id), global_order),
                "channel_popular": by_channel.get(event["target_channel"], global_order),
            }
            for name, order in orders.items():
                rankings[name].extend({"cliente_id": client_id, "oferta_id": offer} for offer in order if offer in eligible)
    targets = events.set_index("cliente_id")["target_offer"]
    result = {}
    for name, rows in rankings.items():
        ranked = pd.DataFrame(rows, columns=["cliente_id", "oferta_id"])
        result[name] = _ranking_metrics(targets, ranked.groupby("cliente_id", observed=True).head(3))
    return result


def tune_ranking(config_path: str | None = None, max_clients: int | None = None) -> dict:
    config = load_config(config_path)
    engine = NBOEngine(config_path, persist=False)
    manifest = load_split_manifest(engine.artifact_dir / "split_manifest.json")
    events = _event_universe(engine.history, manifest["assignments"], "validation", max_clients)
    candidates, eligible_events = _build_candidate_universe(engine, events)
    if candidates.empty:
        raise RuntimeError("No hay eventos elegibles para optimizar ranking")
    targets = eligible_events.set_index("cliente_id")["target_offer"]
    trials = []
    for weights in _weight_candidates(config, int(config["project"]["seed"])):
        ranked = _rank_candidates(candidates, weights)
        metrics = _ranking_metrics(targets, ranked)
        top = ranked.groupby("cliente_id", observed=True).head(1)
        shares = top["oferta_id"].value_counts(normalize=True)
        diversity = {"top1_unique_offers": int(top["oferta_id"].nunique()), "max_offer_share": float(shares.max())}
        trials.append({"weights": weights, "metrics": metrics, "diversity": diversity})
    min_offers = int(config["ranking"]["min_top1_offers"])
    max_share = float(config["ranking"]["max_top1_offer_share"])
    diverse_trials = [item for item in trials if item["diversity"]["top1_unique_offers"] >= min_offers and item["diversity"]["max_offer_share"] <= max_share]
    pool = diverse_trials or trials
    best = max(pool, key=lambda item: (item["metrics"]["ndcg_at_3"], item["metrics"]["hit_at_3"], item["metrics"]["hit_at_1"]))
    baselines = _popular_baselines(engine.history, engine.customers, manifest["assignments"], eligible_events, candidates)
    best_baseline = max(value["ndcg_at_3"] for value in baselines.values())
    required = float(config["ranking"]["ndcg_relative_improvement"])
    relative = (best["metrics"]["ndcg_at_3"] - best_baseline) / max(best_baseline, 1e-12)
    report = {
        "split": "validation", "events_considered": len(events), "eligible_evaluable": len(eligible_events),
        "coverage": len(eligible_events) / max(len(events), 1), "weights": best["weights"],
        "metrics": best["metrics"], "diversity": best["diversity"], "baselines": baselines,
        "gate": {
            "passed": best["metrics"]["hit_at_3"] >= max(v["hit_at_3"] for v in baselines.values()) and relative >= required and bool(diverse_trials),
            "relative_ndcg_improvement": relative, "required": required,
            "diversity_passed": bool(diverse_trials), "min_top1_offers": min_offers, "max_top1_offer_share": max_share,
        },
        "trials": trials,
    }
    (engine.artifact_dir / "ranking_weights.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report


def _business_metrics(events: pd.DataFrame, ranked: pd.DataFrame, engine: NBOEngine) -> dict[str, Any]:
    top = ranked.groupby("cliente_id", observed=True).head(1).copy()
    customers = engine.customer_index
    top["eligible_mt"] = top["cliente_id"].map(customers["elegible_mt"])
    top["stage_mt"] = top["cliente_id"].map(customers.apply(lambda row: __import__("nbo.features", fromlist=["mt_stage"]).mt_stage(row), axis=1))
    top["recommended_mt"] = top["oferta_es_movistar_total"].astype(bool)
    completes_home = top["tipo_oferta"].eq("plan_hogar") & top["descripcion_bundle"].astype(str).str.contains("Internet", case=False)
    completes_mobile = top["tipo_oferta"].eq("plan_movil")
    return {
        "mt_capture_eligible": float(top.loc[top["eligible_mt"], "recommended_mt"].mean()) if top["eligible_mt"].any() else None,
        "mt_recommendation_share": float(top["recommended_mt"].mean()),
        "mean_recommended_price": float(top["precio_mensual"].mean()),
        "mean_acceptance_probability": float(top["p_aceptacion"].mean()),
        "mean_sale_probability": float(top["p_venta"].mean()),
        "route_home_completion_share": float(completes_home.loc[top["stage_mt"].eq("falta_internet_hogar")].mean()) if top["stage_mt"].eq("falta_internet_hogar").any() else None,
        "route_mobile_completion_share": float(completes_mobile.loc[top["stage_mt"].eq("falta_movil_postpago")].mean()) if top["stage_mt"].eq("falta_movil_postpago").any() else None,
    }


def evaluate(config_path: str | None = None, max_clients: int | None = None) -> dict:
    config = load_config(config_path)
    engine = NBOEngine(config_path, persist=False)
    manifest = load_split_manifest(engine.artifact_dir / "split_manifest.json")
    weights_path = engine.artifact_dir / "ranking_weights.json"
    if not weights_path.exists():
        tune_ranking(config_path, max_clients)
        engine = NBOEngine(config_path, persist=False)
    weights_report = json.loads(weights_path.read_text(encoding="utf-8"))
    events = _event_universe(engine.history, manifest["assignments"], "test", max_clients)
    candidates, eligible_events = _build_candidate_universe(engine, events)
    targets = eligible_events.set_index("cliente_id")["target_offer"]
    ranked = _rank_candidates(candidates, weights_report["weights"])
    ranking = _ranking_metrics(targets, ranked)
    baselines = _popular_baselines(engine.history, engine.customers, manifest["assignments"], eligible_events, candidates)
    best_baseline = max(value["ndcg_at_3"] for value in baselines.values()) if baselines else 0
    relative = (ranking["ndcg_at_3"] - best_baseline) / max(best_baseline, 1e-12)
    report = {
        "model_version": engine.versions["model_version"], "split": "test",
        "historical_cutoff_policy": "Solo meses completos anteriores al evento; se excluyen evento y mes actual.",
        "coverage": {"accepted_test_events_considered": len(events), "eligible_evaluable": len(eligible_events), "rate": len(eligible_events) / max(len(events), 1)},
        "ranking": ranking, "baselines": baselines,
        "ranking_gate": {
            "passed": ranking["hit_at_3"] >= max(v["hit_at_3"] for v in baselines.values()) and relative >= float(config["ranking"]["ndcg_relative_improvement"]),
            "relative_ndcg_improvement": relative,
        },
        "business": _business_metrics(eligible_events, ranked, engine),
        "diversity": {
            "top1_unique_offers": int(ranked.groupby("cliente_id", observed=True).head(1)["oferta_id"].nunique()),
            "max_offer_share": float(ranked.groupby("cliente_id", observed=True).head(1)["oferta_id"].value_counts(normalize=True).max()),
        },
        "limitations": [
            "La evaluación usa solo ofertas observadas por la política histórica y no identifica efectos causales.",
            "El perfil de clientes es un resumen estático de seis meses, no un snapshot mensual perfecto.",
            "Las metas MT hogar/móvil son referencias; estos datos no identifican el origen comercial de cada venta MT.",
        ],
    }
    output = Path(config["project"]["artifact_dir"]) / "evaluation_v2.json"
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    card = engine.artifact_dir / "MODEL_CARD.md"
    existing = card.read_text(encoding="utf-8")
    marker = "## Evaluación final de ranking"
    existing = existing.split(marker)[0].rstrip()
    ranking_section = f"""

## Evaluación final de ranking

- Cobertura evaluable: {report['coverage']['rate']:.1%} ({report['coverage']['eligible_evaluable']:,} de {report['coverage']['accepted_test_events_considered']:,}).
- Hit@1: {ranking['hit_at_1']:.3f}; Hit@3: {ranking['hit_at_3']:.3f}; NDCG@3: {ranking['ndcg_at_3']:.3f}.
- Mejora relativa NDCG@3 frente al mejor baseline: {relative:.1%}.
- Gate final: {'APROBADO' if report['ranking_gate']['passed'] else 'NO APROBADO'}.
- Política temporal: solo meses completos anteriores al evento evaluado.
"""
    card.write_text(existing + ranking_section, encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Evalúa ranking NBO sin fuga temporal.")
    parser.add_argument("--config")
    parser.add_argument("--max-clients", type=int, help="Omitir para usar todo el split.")
    parser.add_argument("--tune-ranking", action="store_true")
    args = parser.parse_args()
    report = tune_ranking(args.config, args.max_clients) if args.tune_ranking else evaluate(args.config, args.max_clients)
    print(json.dumps({key: value for key, value in report.items() if key != "trials"}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
