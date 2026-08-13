from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

import pandas as pd

from .engine import NBOEngine


def enrich_batch_report(output_path: Path, engine: NBOEngine, report: dict) -> dict:
    recommendations = pd.read_csv(output_path)
    offer_type = engine.catalog.set_index("oferta_id")["tipo_oferta"]
    offer_bundle = engine.catalog.set_index("oferta_id")["descripcion_bundle"]
    recommendations["tipo_oferta"] = recommendations["oferta_id"].map(offer_type)
    recommendations["bundle"] = recommendations["oferta_id"].map(offer_bundle)
    home_route = recommendations["etapa_mt"].eq("falta_internet_hogar")
    mobile_route = recommendations["etapa_mt"].eq("falta_movil_postpago")
    report["distribution"] = {
        "offers": recommendations["oferta_id"].value_counts().to_dict(),
        "top1_unique_offers": int(recommendations["oferta_id"].nunique()),
        "catalog_coverage": float(recommendations["oferta_id"].nunique() / 22),
        "max_offer_share": float(recommendations["oferta_id"].value_counts(normalize=True).max()),
        "channels": recommendations["canal"].value_counts().to_dict(),
        "mt_share": float(recommendations["es_mt"].mean()),
        "mean_acceptance_probability": float(recommendations["probabilidad_aceptacion"].mean()),
        "mean_sale_probability": float(recommendations["probabilidad_venta"].mean()),
        "stage_mt": recommendations["etapa_mt"].value_counts().to_dict(),
        "mt_capture_eligible": float(recommendations.loc[recommendations["etapa_mt"].eq("elegible_mt"), "es_mt"].mean()) if recommendations["etapa_mt"].eq("elegible_mt").any() else None,
        "route_home_completion_share": float((recommendations.loc[home_route, "tipo_oferta"].eq("plan_hogar") & recommendations.loc[home_route, "bundle"].astype(str).str.contains("Internet", case=False)).mean()) if home_route.any() else None,
        "route_mobile_completion_share": float(recommendations.loc[mobile_route, "tipo_oferta"].eq("plan_movil").mean()) if mobile_route.any() else None,
    }
    return report


def batch_recommend(output: str | Path, chunk_size: int = 1000, limit: int | None = None, config: str | None = None) -> Path:
    engine = NBOEngine(config, persist=True)
    ids = engine.customers["cliente_id"].tolist()
    if limit:
        ids = ids[:limit]
    rows: list[dict] = []
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    first = True
    latencies: list[float] = []
    errors: list[dict] = []
    processed = 0
    started_total = time.perf_counter()
    for start in range(0, len(ids), chunk_size):
        rows.clear()
        chunk_ids = ids[start: start + chunk_size]
        started_chunk = time.perf_counter()
        try:
            results = engine.rank_many(chunk_ids)
        except Exception as exc:
            errors.append({"start": start, "client_count": len(chunk_ids), "error": str(exc)})
            continue
        elapsed = time.perf_counter() - started_chunk
        latencies.extend([elapsed * 1000 / max(len(chunk_ids), 1)] * len(chunk_ids))
        persisted_at = pd.Timestamp.now(tz="UTC").isoformat()
        persistence_rows: list[dict] = []
        for _, item in results.iterrows():
            client_id = str(item["cliente_id"])
            decision_id = str(__import__("uuid").uuid4())
            rows.append({
                "decision_id": decision_id,
                "cliente_id": client_id,
                "etapa_mt": item["etapa_mt"],
                "oferta_id": item["oferta_id"],
                "canal": item["canal"],
                "probabilidad_contacto": item["p_contacto"],
                "probabilidad_aceptacion": item["p_aceptacion"],
                "probabilidad_venta": item["p_venta"],
                "score": item["score"],
                "es_mt": bool(item["oferta_es_movistar_total"]),
                "motivo_recomendacion": "ranking_batch_versionado",
            })
            persistence_rows.append({
                "decision_id": decision_id, "cliente_id": client_id, "created_at": persisted_at,
                "oferta_id": str(item["oferta_id"]), "canal": str(item["canal"]),
                "p_contacto": float(item["p_contacto"]), "p_aceptacion": float(item["p_aceptacion"]),
                "p_venta": float(item["p_venta"]), "score": float(item["score"]),
            })
            processed += 1
        if engine.store:
            engine.store.save_ranked_batch(persistence_rows, engine.versions)
        pd.DataFrame(rows).to_csv(output_path, mode="w" if first else "a", header=first, index=False)
        first = False
    report = {
        "model_version": engine.versions["model_version"], "requested": len(ids), "processed": processed,
        "coverage": processed / max(len(ids), 1), "errors": errors,
        "duration_seconds": time.perf_counter() - started_total,
        "latency_ms": {
            "p50": float(pd.Series(latencies).quantile(.50)) if latencies else None,
            "p95": float(pd.Series(latencies).quantile(.95)) if latencies else None,
        },
    }
    if output_path.exists():
        report = enrich_batch_report(output_path, engine, report)
    output_path.with_suffix(".report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Recomienda en chunks y exporta CSV.")
    parser.add_argument("--output", default="artifacts/batch_recommendations.csv")
    parser.add_argument("--chunk-size", type=int, default=1000)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--config")
    parser.add_argument("--report-only", action="store_true", help="Recalcula métricas del CSV sin generar decisiones.")
    args = parser.parse_args()
    if args.report_only:
        output = Path(args.output)
        engine = NBOEngine(args.config, persist=False)
        report_path = output.with_suffix(".report.json")
        report = json.loads(report_path.read_text(encoding="utf-8"))
        report = enrich_batch_report(output, engine, report)
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(report_path)
    else:
        print(batch_recommend(args.output, args.chunk_size, args.limit, args.config))


if __name__ == "__main__":
    main()
