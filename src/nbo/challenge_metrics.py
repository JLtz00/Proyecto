"""Cálculo de KPIs del Desafío 2 (MT share hogar/móvil, ΔARPU, uplift, churn,
ofertas repetidas evitadas) y renderizado a HTML autocontenido."""
from __future__ import annotations

import argparse
import html
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .engine import NBOEngine


REPETIDAS_REASONS = ("current_product", "already_active_offer")


def _channel_costs_default() -> dict[str, float]:
    return {"Digital": 1.0, "Tienda": 8.0, "Call In": 4.0, "Call Out": 6.0}


def _sample_customers(engine: NBOEngine, sample_size: int, seed: int = 42) -> list[str]:
    ids = engine.customers["cliente_id"].astype(str).tolist()
    rng = np.random.default_rng(seed)
    if sample_size >= len(ids):
        return ids
    return list(rng.choice(ids, size=sample_size, replace=False))


def _first_row(candidates: pd.DataFrame, cliente_id: str) -> pd.Series:
    subset = candidates.loc[candidates["cliente_id"].astype(str).eq(cliente_id)]
    return subset.iloc[0] if not subset.empty else pd.Series(dtype=object)


def _repeated_blocked_for(candidates: pd.DataFrame, cliente_id: str) -> int:
    row = _first_row(candidates, cliente_id)
    if row.empty:
        return 0
    total = 0
    for reason in REPETIDAS_REASONS:
        total += int(row.get(f"_blocked_{reason}", 0) or 0)
    return total


def compute_challenge_metrics(
    engine: NBOEngine,
    sample_size: int = 1000,
    seed: int = 42,
    margin_rate: float = 0.30,
    expected_months: int = 12,
) -> dict[str, Any]:
    """Ejecuta un batch determinista y computa los KPIs del desafío.

    Todas las métricas son **prospectivas simuladas** sobre la muestra: describen
    lo que el motor recomendaría hoy, no ventas reales ni impacto causal.
    """
    ids = _sample_customers(engine, sample_size, seed)
    ranked = engine.rank_many(ids, fecha=engine.config["features"]["as_of_date"])
    candidates_full = engine.candidate_scores_as_of(ids, engine.config["features"]["as_of_date"])

    personas: Counter[str] = Counter()
    churn_levels: Counter[str] = Counter()
    churn_scores: list[float] = []
    uplift_scores: list[float] = []
    repeated_avoided = 0
    for cliente_id in ids:
        summary = _first_row(candidates_full, cliente_id)
        if summary.empty:
            continue
        customer_row = pd.DataFrame([summary.to_dict()])
        if engine.enrichment.personas is not None:
            cluster = int(engine.enrichment.personas.assign(customer_row)[0])
            personas[engine.enrichment.personas.describe(cluster)[0]] += 1
        if engine.enrichment.churn is not None:
            probability = float(engine.enrichment.churn.predict(customer_row)[0])
            churn_scores.append(probability)
            churn_levels[engine.enrichment.churn.level(probability)] += 1
        client_candidates = candidates_full.loc[candidates_full["cliente_id"].astype(str).eq(cliente_id)]
        if not client_candidates.empty:
            mt_mask = client_candidates["oferta_es_movistar_total"].astype(bool)
            if mt_mask.any() and (~mt_mask).any():
                mt_top = float(client_candidates.loc[mt_mask, "p_venta"].max())
                other_median = float(client_candidates.loc[~mt_mask, "p_venta"].median())
                model_uplift = max(mt_top - other_median, 0.0)
                eligible_mt = bool(summary.get("elegible_mt"))
                combined = max(model_uplift, engine._population_uplift_mt) if eligible_mt else model_uplift
                uplift_scores.append(combined)
        repeated_avoided += _repeated_blocked_for(candidates_full, cliente_id)

    # Top-1 por cliente
    top = ranked.copy()
    top["is_mt"] = top["oferta_es_movistar_total"].astype(bool)
    top["is_home"] = top["tipo_oferta"].astype(str).eq("plan_hogar") | top["is_mt"]
    top["is_mobile"] = top["tipo_oferta"].astype(str).eq("plan_movil") | top["is_mt"]

    home_total = int(top["is_home"].sum())
    mobile_total = int(top["is_mobile"].sum())
    mt_home = int((top["is_home"] & top["is_mt"]).sum())
    mt_mobile = int((top["is_mobile"] & top["is_mt"]).sum())

    top["expected_uplift_arpu"] = (
        top["p_venta"].astype(float)
        * top["precio_mensual"].astype(float)
        * float(margin_rate)
        * float(expected_months)
    )
    arpu_base = float(pd.to_numeric(engine.customers["monto_facturado_prom"], errors="coerce").mean())
    delta_arpu_month = float(
        (top["p_venta"].astype(float) * top["precio_mensual"].astype(float)).mean()
    )
    delta_arpu_year = delta_arpu_month * expected_months * margin_rate
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sample_size": len(ids),
        "as_of_date": engine.config["features"]["as_of_date"],
        "mt_share": {
            "hogar_total": home_total,
            "mt_hogar": mt_home,
            "share_hogar": (mt_home / home_total) if home_total else 0.0,
            "meta_hogar": 0.50,
            "movil_total": mobile_total,
            "mt_movil": mt_mobile,
            "share_movil": (mt_mobile / mobile_total) if mobile_total else 0.0,
            "meta_movil": 0.10,
        },
        "delta_arpu": {
            "arpu_base_pen": arpu_base,
            "delta_arpu_mes_pen": delta_arpu_month,
            "delta_arpu_anual_esperado_pen": delta_arpu_year,
            "margin_rate": margin_rate,
            "expected_months": expected_months,
        },
        "repetidas": {
            "clientes_analizados": len(ids),
            "ofertas_repetidas_evitadas": int(repeated_avoided),
            "por_cliente_promedio": (float(repeated_avoided) / len(ids)) if ids else 0.0,
        },
        "personas": dict(personas),
        "churn": {
            "distribution": dict(churn_levels),
            "avg_probability": float(np.mean(churn_scores)) if churn_scores else None,
            "high_risk_share": (
                churn_levels.get("alto", 0) / max(sum(churn_levels.values()), 1)
                if churn_levels
                else None
            ),
        },
        "uplift_mt": {
            "avg_uplift": float(np.mean(uplift_scores)) if uplift_scores else None,
            "clientes_con_uplift_alto": int(sum(1 for value in uplift_scores if value >= 0.05)),
            "muestras_evaluadas": len(uplift_scores),
        },
        "disclaimer": (
            "KPIs prospectivos derivados de recomendaciones simuladas sobre la muestra. "
            "No son ventas reales, uplift causal ni churn observado."
        ),
    }


def _bar(value: float, meta: float | None = None) -> str:
    percentage = max(0.0, min(1.0, value)) * 100
    meta_str = ""
    if meta is not None:
        meta_percent = max(0.0, min(1.0, meta)) * 100
        meta_str = (
            f'<div class="meta" style="left:{meta_percent:.1f}%" '
            f'title="Meta: {meta_percent:.0f}%"></div>'
        )
    fill_color = "#10b981" if meta is None or value >= meta else "#f59e0b"
    return (
        '<div class="bar">'
        f'<div class="fill" style="width:{percentage:.1f}%;background:{fill_color}"></div>'
        f'{meta_str}'
        "</div>"
    )


def render_html(metrics: dict[str, Any]) -> str:
    mt = metrics["mt_share"]
    arpu = metrics["delta_arpu"]
    repetidas = metrics["repetidas"]
    personas = metrics["personas"]
    churn = metrics["churn"]
    uplift = metrics["uplift_mt"]

    def money(value: float) -> str:
        return f"S/ {value:,.2f}"

    def pct(value: float | None) -> str:
        return f"{(value or 0) * 100:.1f}%"

    personas_rows = "".join(
        f'<tr><td>{html.escape(name)}</td><td class="num">{count}</td></tr>'
        for name, count in sorted(personas.items(), key=lambda item: -item[1])
    )
    churn_rows = "".join(
        f'<tr><td>{html.escape(level)}</td><td class="num">{count}</td></tr>'
        for level, count in sorted(churn["distribution"].items())
    )

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>KPIs Desafío 2 · Motor NBO</title>
<style>
  body {{ font-family: -apple-system, Segoe UI, Roboto, sans-serif; background: #0f172a; color: #f1f5f9; margin: 0; padding: 32px; }}
  h1 {{ margin: 0 0 4px 0; font-size: 28px; }}
  .sub {{ color: #94a3b8; margin-bottom: 24px; font-size: 14px; }}
  .grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; margin-bottom: 24px; }}
  .card {{ background: #1e293b; border-radius: 12px; padding: 20px; }}
  .card h2 {{ font-size: 12px; text-transform: uppercase; color: #94a3b8; margin: 0 0 12px 0; letter-spacing: .05em; }}
  .value {{ font-size: 28px; font-weight: 600; margin-bottom: 6px; }}
  .meta-label {{ color: #94a3b8; font-size: 12px; }}
  .bar {{ height: 10px; background: #334155; border-radius: 5px; margin: 8px 0; position: relative; overflow: visible; }}
  .fill {{ height: 100%; border-radius: 5px; }}
  .meta {{ position: absolute; top: -4px; width: 2px; height: 18px; background: #ef4444; }}
  table {{ width: 100%; border-collapse: collapse; }}
  th, td {{ padding: 8px; text-align: left; border-bottom: 1px solid #334155; font-size: 14px; }}
  th {{ color: #94a3b8; font-weight: 500; text-transform: uppercase; font-size: 11px; letter-spacing: .05em; }}
  td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  .disclaimer {{ margin-top: 24px; padding: 16px; background: #422006; border-left: 4px solid #f59e0b; border-radius: 8px; color: #fef3c7; font-size: 13px; line-height: 1.5; }}
  .row {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
</style>
</head>
<body>
<h1>KPIs Desafío 2 · Motor NBO</h1>
<div class="sub">Muestra {metrics['sample_size']:,} clientes · corte {metrics['as_of_date']} · generado {metrics['generated_at']}</div>

<div class="grid">
  <div class="card">
    <h2>MT share hogar</h2>
    <div class="value">{pct(mt['share_hogar'])}</div>
    {_bar(mt['share_hogar'], mt['meta_hogar'])}
    <div class="meta-label">{mt['mt_hogar']}/{mt['hogar_total']} recomendaciones de hogar son MT · meta &gt;50%</div>
  </div>
  <div class="card">
    <h2>MT share móvil</h2>
    <div class="value">{pct(mt['share_movil'])}</div>
    {_bar(mt['share_movil'], mt['meta_movil'])}
    <div class="meta-label">{mt['mt_movil']}/{mt['movil_total']} recomendaciones de móvil son MT · meta &gt;10%</div>
  </div>
  <div class="card">
    <h2>ΔARPU esperado (12m)</h2>
    <div class="value">{money(arpu['delta_arpu_anual_esperado_pen'])}</div>
    <div class="meta-label">ARPU base {money(arpu['arpu_base_pen'])}/mes · margen {arpu['margin_rate']:.0%} · {arpu['expected_months']} meses</div>
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2>Ofertas repetidas evitadas</h2>
    <div class="value">{repetidas['ofertas_repetidas_evitadas']:,}</div>
    <div class="meta-label">{repetidas['por_cliente_promedio']:.2f} por cliente en promedio · el motor filtró estas antes del ranking</div>
  </div>
  <div class="card">
    <h2>Uplift MT promedio</h2>
    <div class="value">{pct(uplift['avg_uplift'])}</div>
    <div class="meta-label">Δ P(venta) MT vs mediana de alternativas · {uplift['clientes_con_uplift_alto']} clientes con uplift ≥ 5%</div>
  </div>
  <div class="card">
    <h2>Riesgo de fuga (proxy)</h2>
    <div class="value">{pct(churn['avg_probability'])}</div>
    <div class="meta-label">Probabilidad promedio · {pct(churn['high_risk_share'])} en nivel alto</div>
  </div>
</div>

<div class="row">
  <div class="card">
    <h2>Distribución de personas (K-Means k={len(personas)})</h2>
    <table><thead><tr><th>Persona</th><th class="num">Clientes</th></tr></thead>
    <tbody>{personas_rows}</tbody></table>
  </div>
  <div class="card">
    <h2>Distribución riesgo de fuga</h2>
    <table><thead><tr><th>Nivel</th><th class="num">Clientes</th></tr></thead>
    <tbody>{churn_rows}</tbody></table>
  </div>
</div>

<div class="disclaimer">
  {html.escape(metrics['disclaimer'])}
</div>
</body>
</html>
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Genera KPIs del Desafío 2 y su reporte HTML.")
    parser.add_argument("--sample-size", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--margin-rate", type=float, default=0.30)
    parser.add_argument("--expected-months", type=int, default=12)
    parser.add_argument("--output", default="reports/challenge_kpis.html")
    parser.add_argument("--json-output", default="reports/challenge_kpis.json")
    args = parser.parse_args()

    engine = NBOEngine(persist=False)
    metrics = compute_challenge_metrics(
        engine,
        sample_size=args.sample_size,
        seed=args.seed,
        margin_rate=args.margin_rate,
        expected_months=args.expected_months,
    )
    output_html = Path(args.output)
    output_html.parent.mkdir(parents=True, exist_ok=True)
    output_html.write_text(render_html(metrics), encoding="utf-8")
    Path(args.json_output).write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps({"html": str(output_html), "json": args.json_output, "kpis": metrics}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
