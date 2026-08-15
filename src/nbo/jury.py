from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import ROOT


DEMO_FUNNEL = {
    "classified": 1000,
    "displayed": 920,
    "contacted": 778,
    "negotiated": 436,
    "accepted": 291,
    "activated": 247,
    "rejected": 145,
}


def demo_business_metrics() -> dict[str, Any]:
    """Fixture determinista de presentación; nunca se mezcla con operación real."""
    return {
        "source": "demo",
        "is_simulated": True,
        "generated_at": "2026-08-13T00:00:00+00:00",
        "funnel": DEMO_FUNNEL,
        "channel_performance": {
            "Digital": {"contacted": 320, "accepted": 132, "activated": 113},
            "Call In": {"contacted": 188, "accepted": 72, "activated": 61},
            "Call Out": {"contacted": 147, "accepted": 49, "activated": 40},
            "Tienda": {"contacted": 123, "accepted": 38, "activated": 33},
        },
        "mt": {
            "recommendations": 137,
            "customers_converted_to_eligible": 84,
            "recalculated_after_activation": 247,
            "tier_distribution": {"Básico": 58, "Plus": 43, "Max": 36},
        },
        "rejection_reasons": {
            "precio": 61, "no_necesita": 31, "mal_momento": 23,
            "ya_tiene_similar": 16, "no_confia": 9, "otro": 5,
        },
        "rebate": {"used": 83, "accepted": 29},
        "evidence": {"registro_plataforma": 481, "chat_log": 190, "audio_llamada": 107},
        "guardrails": {"cooldowns_applied": 145, "fatigue_suppressed": 38, "incoherent_events_rejected": 7},
        "timing_seconds": {
            "acceptance_to_activation": 97200.0,
            "to_mt_eligibility": 97200.0,
            "to_mt_recommendation": 0.24,
        },
        "disclaimer": "Escenario demostrativo determinista; no representa resultados comerciales reales.",
    }


def normalize_operational_metrics(raw: dict[str, Any]) -> dict[str, Any]:
    feedback = {row["final_result"]: int(row["n"]) for row in raw.get("feedback_funnel", [])}
    event_funnel = {row["event_type"]: int(row["n"]) for row in raw.get("event_funnel", [])}
    decisions = int(raw.get("decisions", {}).get("n") or 0)
    accepted = int(feedback.get("aceptada", 0))
    rejected = int(feedback.get("rechazada", 0))
    activated = sum(
        int(row["n"]) for row in raw.get("customer_state_events", [])
        if row["event_type"] == "product_activated"
    )
    funnel = {
        "classified": decisions,
        "displayed": int(event_funnel.get("displayed", decisions)),
        "contacted": int(event_funnel.get("contacted", accepted + rejected)),
        "negotiated": int(event_funnel.get("negotiated", 0)),
        "accepted": accepted,
        "activated": activated,
        "rejected": rejected,
    }
    return {
        **raw,
        "source": "operational", "is_simulated": False,
        "generated_at": datetime.now(timezone.utc).isoformat(), "funnel": funnel,
        "mt": {
            "recommendations": int(raw.get("mt_recommendations", 0)),
            "customers_converted_to_eligible": int(raw.get("customers_converted_to_mt_eligible", 0)),
            "recalculated_after_activation": int(raw.get("recommendations_recalculated_after_activation", 0)),
            "tier_distribution": raw.get("mt_tier_distribution", {}),
        },
        "rejection_reasons": raw.get("rejection_reasons", {}),
        "channel_performance": raw.get("channel_performance", {}),
        "rebate": raw.get("rebate", {}), "evidence": raw.get("evidence", {}),
        "guardrails": {
            "cooldowns_applied": int(raw.get("post_rejection_actions", 0)),
            "fatigue_suppressed": 0,
            "incoherent_events_rejected": sum(raw.get("rejected_customer_events", {}).values()),
        },
        "timing_seconds": {
            "acceptance_to_activation": raw.get("average_acceptance_to_activation_seconds"),
            "to_mt_eligibility": raw.get("average_time_to_mt_eligibility_seconds"),
            "to_mt_recommendation": raw.get("average_time_to_mt_recommendation_seconds"),
        },
        "raw": raw,
        "disclaimer": "Métricas descriptivas de la base operacional local; no prueban impacto causal.",
    }


def executive_report(raw: dict[str, Any], source: str) -> dict[str, Any]:
    metrics = demo_business_metrics() if source == "demo" else normalize_operational_metrics(raw)
    funnel = metrics["funnel"]

    def rate(numerator: str, denominator: str) -> float | None:
        base = funnel.get(denominator, 0)
        return funnel.get(numerator, 0) / base if base else None

    metrics["rates"] = {
        "display_rate": rate("displayed", "classified"),
        "contact_rate": rate("contacted", "displayed"),
        "acceptance_rate": rate("accepted", "contacted"),
        "activation_rate": rate("activated", "accepted"),
        "end_to_end_rate": rate("activated", "classified"),
    }
    return metrics


def _read_versioned_json(
    path: Path, active_version: str, blocked: list[dict[str, str]], *, nested: bool = False,
) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        blocked.append({"report": path.name, "reason": f"reporte ilegible: {exc}"})
        return None
    version = (
        payload.get("versions", {}).get("model_version") if nested
        else payload.get("model_version")
    )
    if version != active_version:
        blocked.append({
            "report": path.name,
            "reason": f"version {version or 'ausente'}; motor activo {active_version}",
        })
        return None
    return payload


def load_mvp_evidence(engine: Any) -> dict[str, Any]:
    """Carga solo evidencia real cuya version coincide con el motor activo."""
    active = str(engine.versions["model_version"])
    blocked: list[dict[str, str]] = []
    metadata = _read_versioned_json(
        engine.artifact_dir / "metadata.json", active, blocked, nested=True,
    )
    audit = _read_versioned_json(engine.artifact_dir / "audit.json", active, blocked)
    evaluation_v2 = _read_versioned_json(
        Path(engine.config["project"]["artifact_dir"]) / "evaluation_v2.json", active, blocked,
    )
    evaluation_v3 = _read_versioned_json(ROOT / "reports" / "evaluation_v3.json", active, blocked)
    batch = _read_versioned_json(
        Path(engine.config["project"]["artifact_dir"]) / "recomendaciones.report.json",
        active,
        blocked,
    )
    verification = _read_versioned_json(ROOT / "reports" / "verification.json", active, blocked)

    selected_models: dict[str, str] = {}
    predictive: dict[str, Any] = {}
    if metadata:
        group = metadata.get("metrics", {}).get("group_split", {})
        for target in ("contact", "acceptance", "rejection"):
            values = group.get(target, {})
            selected_models[target] = values.get("selected_kind", "no reportado")
            predictive[target] = values.get("test", {})

    return {
        "model_version": active,
        "consistent": all((metadata, audit, evaluation_v2, evaluation_v3, batch)) and not blocked,
        "blocked_reports": blocked,
        "selected_models": selected_models,
        "predictive": predictive,
        "ranking": {
            "v2": evaluation_v2,
            "v3": evaluation_v3,
        },
        "batch": batch,
        "audit": audit,
        "verification": verification,
        "limitations": [
            "Contacto tiene poca capacidad discriminativa en el historico disponible.",
            "Aceptacion aporta una senal moderada; no demuestra uplift causal.",
            "Las metricas describen este dataset y no equivalen a ventas reales.",
        ],
    }
