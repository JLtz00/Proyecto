"""Smoke test rápido: valida que enrichment, what-if y KPIs corren end-to-end."""
from __future__ import annotations

import json

from nbo.advisor_local import LocalAdvisorApi
from nbo.engine import NBOEngine


def main() -> None:
    engine = NBOEngine(persist=True)
    api = LocalAdvisorApi(engine)

    print("== Recommendation CLI000013 ==")
    result = api.recommend("CLI000013")
    cliente = result["cliente"]
    print(json.dumps({
        "cliente_id": cliente["cliente_id"],
        "etapa_mt": cliente["etapa_mt"],
        "persona": cliente.get("persona"),
        "riesgo_fuga": cliente.get("riesgo_fuga"),
        "uplift_mt": cliente.get("uplift_mt"),
        "top_offer": result["recommendation"]["nombre_oferta"],
        "top_channel": result["recommendation"]["canal"],
        "top_score": result["recommendation"]["score"],
    }, indent=2, ensure_ascii=False))

    print("\n== What-if CLI000013 (más peso a MT) ==")
    whatif = api.what_if("CLI000013", {"w_mt": 0.30, "w_conversion": 0.30})
    base = whatif["base"]["recommendation"]
    sim = whatif["simulated"]["recommendation"]
    print(json.dumps({
        "base": {"oferta": base["nombre_oferta"], "canal": base["canal"], "score": base["score"]},
        "simulado": {"oferta": sim["nombre_oferta"], "canal": sim["canal"], "score": sim["score"]},
        "pesos_default": whatif["scoring_default"],
        "pesos_usados": whatif["scoring_used"],
    }, indent=2, ensure_ascii=False))

    print("\n== Challenge KPIs (100 clientes) ==")
    kpis = api.challenge_kpis(sample_size=100, seed=42)
    print(json.dumps({
        "sample": kpis["sample_size"],
        "mt_share": kpis["mt_share"],
        "delta_arpu": kpis["delta_arpu"],
        "repetidas": kpis["repetidas"],
        "personas": kpis["personas"],
        "churn": kpis["churn"],
        "uplift_mt": kpis["uplift_mt"],
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
