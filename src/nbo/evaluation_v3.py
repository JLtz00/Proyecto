from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .config import load_config
from .engine import NBOEngine
from .splits import load_split_manifest


def _metrics_from_ranks(ranks: pd.Series, denominator: int | None = None) -> dict[str, float]:
    total = int(denominator if denominator is not None else len(ranks))
    if total == 0:
        return {"hit_at_1": 0.0, "hit_at_3": 0.0, "ndcg_at_3": 0.0}
    values = ranks.dropna().astype(int)
    return {
        "hit_at_1": float(values.eq(1).sum() / total),
        "hit_at_3": float(values.le(3).sum() / total),
        "ndcg_at_3": float(values.loc[values.le(3)].map(lambda rank: 1 / math.log2(rank + 1)).sum() / total),
    }


def _rank_events(candidates: pd.DataFrame, score_column: str = "score_v3") -> pd.DataFrame:
    best = candidates.sort_values(
        ["event_id", "oferta_id", "p_venta", score_column],
        ascending=[True, True, False, False],
    ).drop_duplicates(["event_id", "oferta_id"])
    top = best.sort_values(
        ["event_id", score_column, "p_venta", "oferta_id"],
        ascending=[True, False, False, True],
    ).groupby("event_id", observed=True).head(3).copy()
    top["rank"] = top.groupby("event_id", observed=True).cumcount() + 1
    return top


def _event_ranks(events: pd.DataFrame, ranked: pd.DataFrame) -> pd.DataFrame:
    targets = events[["event_id", "cliente_id", "target_offer"]]
    hits = ranked.loc[ranked["oferta_id"].eq(ranked["target_offer"]), ["event_id", "rank"]]
    return targets.merge(hits, on="event_id", how="left", validate="one_to_one")


def _bootstrap(ranks: pd.DataFrame, iterations: int, seed: int) -> dict[str, dict[str, float]]:
    rng = np.random.default_rng(seed)
    clients = ranks["cliente_id"].unique()
    samples = {name: [] for name in ("hit_at_1", "hit_at_3", "ndcg_at_3")}
    grouped = {client: group["rank"] for client, group in ranks.groupby("cliente_id", observed=True)}
    for _ in range(iterations):
        draw = rng.choice(clients, size=len(clients), replace=True)
        sampled = pd.concat([grouped[client] for client in draw], ignore_index=True)
        values = _metrics_from_ranks(sampled)
        for name, value in values.items():
            samples[name].append(value)
    return {
        name: {
            "low": float(np.quantile(values, 0.025)),
            "high": float(np.quantile(values, 0.975)),
        }
        for name, values in samples.items()
    }


def _accepted_events(engine: NBOEngine, assignments: dict[str, str], max_events: int | None) -> pd.DataFrame:
    events = engine.history.loc[
        engine.history["cliente_id"].map(assignments).eq("test")
        & engine.history["resultado"].eq("aceptada")
    ].sort_values(["fecha", "ofrecimiento_id"]).copy()
    if max_events:
        events = events.head(max_events)
    events["event_id"] = events["ofrecimiento_id"].astype(str)
    return events[["event_id", "cliente_id", "oferta_id", "canal", "fecha"]].rename(
        columns={"oferta_id": "target_offer", "canal": "target_channel"}
    )


def _candidate_universe(engine: NBOEngine, events: pd.DataFrame, chunk_size: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    blocks: list[pd.DataFrame] = []
    coverage: list[dict[str, Any]] = []
    work = events.assign(cutoff=events["fecha"].dt.to_period("M").dt.start_time)
    for cutoff, monthly in work.groupby("cutoff", observed=True):
        ids = monthly["cliente_id"].unique().tolist()
        monthly_candidates = []
        for start in range(0, len(ids), chunk_size):
            monthly_candidates.append(engine.candidate_scores_as_of(ids[start:start + chunk_size], cutoff))
        base = pd.concat(monthly_candidates, ignore_index=True)
        expanded = monthly.merge(base, on="cliente_id", how="left", validate="many_to_many")
        eligible = expanded.groupby("event_id", observed=True).apply(
            lambda frame: bool(frame["oferta_id"].eq(frame["target_offer"].iloc[0]).any()),
            include_groups=False,
        )
        coverage.extend({"event_id": event_id, "evaluable": bool(value)} for event_id, value in eligible.items())
        valid = set(eligible[eligible].index)
        blocks.append(expanded.loc[expanded["event_id"].isin(valid)])
    return pd.concat(blocks, ignore_index=True), pd.DataFrame(coverage)


def _score(frame: pd.DataFrame, weights: dict[str, float], history: bool = True) -> pd.Series:
    sale = frame["p_venta"] if history else pd.Series(float(frame["p_venta"].mean()), index=frame.index)
    return (
        weights["w_conversion"] * sale
        + weights["w_fit"] * frame["fit_cliente"]
        + weights["w_business"] * frame["valor_negocio"]
        + weights["w_mt"] * frame["bonus_ruta_mt"]
        - weights["w_friction"] * frame["friccion_candidato"]
        - frame["penalizacion_cooldown"]
    ).clip(0, 1)


def _slice_metrics(ranks: pd.DataFrame, events: pd.DataFrame, engine: NBOEngine) -> dict[str, Any]:
    enriched = ranks.merge(events[["event_id", "target_channel"]], on="event_id", how="left")
    profiles = engine.customer_index
    enriched["mt_stage"] = enriched["cliente_id"].map(
        profiles.apply(lambda row: __import__("nbo.features", fromlist=["mt_stage"]).mt_stage(row), axis=1)
    )
    mt_ids = set(engine.catalog.loc[engine.catalog["es_movistar_total"], "oferta_id"])
    enriched["target_is_mt"] = enriched["target_offer"].isin(mt_ids).map({True: "MT", False: "No MT"})
    result: dict[str, Any] = {}
    for column in ("target_channel", "mt_stage", "target_is_mt"):
        result[column] = {
            str(value): {**_metrics_from_ranks(group["rank"]), "events": len(group)}
            for value, group in enriched.groupby(column, observed=True)
        }
    return result


def _event_baselines(
    engine: NBOEngine,
    assignments: dict[str, str],
    events: pd.DataFrame,
    candidates: pd.DataFrame,
    all_event_count: int,
) -> dict[str, Any]:
    customer_type = engine.customer_index["tipo_cliente"]
    rows = {name: [] for name in ("global_popular", "segment_popular", "channel_popular")}
    work = events.assign(cutoff=events["fecha"].dt.to_period("M").dt.start_time)
    for cutoff, monthly in work.groupby("cutoff", observed=True):
        prior = engine.history.loc[
            engine.history["cliente_id"].map(assignments).eq("train")
            & engine.history["resultado"].eq("aceptada")
            & engine.history["fecha"].lt(cutoff)
        ].copy()
        prior["tipo_cliente_master"] = prior["cliente_id"].map(customer_type)
        global_order = prior["oferta_id"].value_counts().index.tolist()
        segment_orders = prior.groupby("tipo_cliente_master", observed=True)["oferta_id"].agg(
            lambda values: values.value_counts().index.tolist()
        ).to_dict()
        channel_orders = prior.groupby("canal", observed=True)["oferta_id"].agg(
            lambda values: values.value_counts().index.tolist()
        ).to_dict()
        for event in monthly.itertuples(index=False):
            eligible = set(candidates.loc[candidates["event_id"].eq(event.event_id), "oferta_id"])
            orders = {
                "global_popular": global_order,
                "segment_popular": segment_orders.get(customer_type.get(event.cliente_id), global_order),
                "channel_popular": channel_orders.get(event.target_channel, global_order),
            }
            for name, order in orders.items():
                ranked = [offer for offer in order if offer in eligible][:3]
                rank = ranked.index(event.target_offer) + 1 if event.target_offer in ranked else np.nan
                rows[name].append({"event_id": event.event_id, "cliente_id": event.cliente_id, "rank": rank})
    return {
        name: {
            "conditioned": _metrics_from_ranks(pd.DataFrame(values)["rank"]),
            "all_accepted_events": _metrics_from_ranks(pd.DataFrame(values)["rank"], all_event_count),
        }
        for name, values in rows.items()
    }


def evaluate_v3(
    config_path: str | None = None,
    max_events: int | None = None,
    bootstrap_iterations: int = 1000,
    chunk_size: int = 250,
) -> dict[str, Any]:
    config = load_config(config_path)
    engine = NBOEngine(config_path, persist=False)
    assignments = load_split_manifest(engine.artifact_dir / "split_manifest.json")["assignments"]
    events = _accepted_events(engine, assignments, max_events)
    candidates, coverage = _candidate_universe(engine, events, chunk_size)
    evaluable_ids = set(coverage.loc[coverage["evaluable"], "event_id"])
    evaluable_events = events.loc[events["event_id"].isin(evaluable_ids)]
    weights = dict(engine.scoring)

    variants = {
        "full": (weights, True),
        "without_mt_priority": ({**weights, "w_mt": 0.0}, True),
        "without_customer_fit": ({**weights, "w_fit": 0.0}, True),
        "without_history": (weights, False),
        "without_friction": ({**weights, "w_friction": 0.0}, True),
        "conversion_only": ({key: (1.0 if key == "w_conversion" else 0.0) for key in weights}, True),
    }
    ablations: dict[str, Any] = {}
    full_ranked = pd.DataFrame()
    full_ranks = pd.DataFrame()
    for name, (variant_weights, use_history) in variants.items():
        scored = candidates.copy()
        scored["score_v3"] = _score(scored, variant_weights, use_history)
        ranked = _rank_events(scored)
        ranks = _event_ranks(evaluable_events, ranked)
        ablations[name] = _metrics_from_ranks(ranks["rank"])
        if name == "full":
            full_ranked, full_ranks = ranked, ranks

    conditioned = _metrics_from_ranks(full_ranks["rank"])
    absolute = _metrics_from_ranks(full_ranks["rank"], denominator=len(events))
    coverage_rate = len(evaluable_events) / max(len(events), 1)

    baselines = _event_baselines(
        engine, assignments, evaluable_events, candidates, len(events),
    )
    best_baseline_ndcg = max(value["conditioned"]["ndcg_at_3"] for value in baselines.values())
    relative_ndcg = (conditioned["ndcg_at_3"] - best_baseline_ndcg) / max(best_baseline_ndcg, 1e-12)

    top = full_ranked.loc[full_ranked["rank"].eq(1)]
    report = {
        "evaluation_version": "evaluation_v3",
        "model_version": engine.versions["model_version"],
        "split": "test",
        "unit": "accepted_offer_event",
        "historical_cutoff_policy": "Solo meses completos anteriores al evento; se excluyen evento y mes actual.",
        "coverage": {
            "accepted_events": len(events), "evaluable_events": len(evaluable_events),
            "non_evaluable_events": len(events) - len(evaluable_events), "rate": coverage_rate,
        },
        "ranking_conditioned": conditioned,
        "ranking_all_accepted_events": absolute,
        "confidence_intervals_95": _bootstrap(full_ranks, bootstrap_iterations, int(config["project"]["seed"])),
        "baselines": baselines,
        "relative_ndcg_improvement_vs_best_baseline": relative_ndcg,
        "ablations": ablations,
        "slices": _slice_metrics(full_ranks, evaluable_events, engine),
        "diversity": {
            "top1_unique_offers": int(top["oferta_id"].nunique()),
            "max_offer_share": float(top["oferta_id"].value_counts(normalize=True).max()),
        },
        "limitations": [
            "La evaluación observa decisiones de la política histórica y no estima uplift causal.",
            "El perfil maestro resume seis meses y no es un snapshot mensual perfecto.",
            "La comparación contra baselines comparte unidad de evento, elegibilidad y política temporal.",
        ],
        "parameters": {"seed": int(config["project"]["seed"]), "bootstrap_iterations": bootstrap_iterations, "max_events": max_events},
    }
    return report


def _markdown(report: dict[str, Any]) -> str:
    c = report["coverage"]
    conditional = report["ranking_conditioned"]
    absolute = report["ranking_all_accepted_events"]
    return f"""# Evaluación offline v3

Evaluación por evento aceptado, con separación por cliente y política temporal sin fuga.

## Cobertura

- Eventos aceptados: {c['accepted_events']:,}
- Evaluables: {c['evaluable_events']:,} ({c['rate']:.1%})
- No evaluables: {c['non_evaluable_events']:,}; cuentan como fallo en la métrica absoluta.

## Ranking

| Universo | Hit@1 | Hit@3 | NDCG@3 |
|---|---:|---:|---:|
| Evaluables | {conditional['hit_at_1']:.2%} | {conditional['hit_at_3']:.2%} | {conditional['ndcg_at_3']:.4f} |
| Todos los aceptados | {absolute['hit_at_1']:.2%} | {absolute['hit_at_3']:.2%} | {absolute['ndcg_at_3']:.4f} |

Mejora relativa NDCG@3 frente al mejor baseline comparable: **{report['relative_ndcg_improvement_vs_best_baseline']:.2%}**.

Estas métricas son offline y observacionales; no demuestran uplift ni causalidad.
"""


def write_report(report: dict[str, Any], output_dir: str | Path = "reports") -> tuple[Path, Path]:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / "evaluation_v3.json"
    md_path = directory / "evaluation_v3.md"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    md_path.write_text(_markdown(report), encoding="utf-8")
    return json_path, md_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluación v3 por evento con cobertura e incertidumbre.")
    parser.add_argument("--config")
    parser.add_argument("--max-events", type=int)
    parser.add_argument("--bootstrap-iterations", type=int, default=1000)
    parser.add_argument("--chunk-size", type=int, default=250)
    parser.add_argument("--output-dir", default="reports")
    args = parser.parse_args()
    report = evaluate_v3(args.config, args.max_events, args.bootstrap_iterations, args.chunk_size)
    paths = write_report(report, args.output_dir)
    print(json.dumps({"reports": [str(path) for path in paths], "coverage": report["coverage"], "ranking": report["ranking_conditioned"]}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
