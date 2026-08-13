from __future__ import annotations

import argparse
import json
from pathlib import Path

from .config import load_config


def _metric_line(name: str, metrics: dict) -> str:
    fields = []
    for key in ("roc_auc", "pr_auc", "brier", "log_loss", "ece", "accuracy", "macro_f1", "top2_accuracy"):
        if key in metrics:
            fields.append(f"{key}={metrics[key]:.4f}")
    return f"- {name}: " + ", ".join(fields) + "."


def build_model_card(config_path: str | None = None) -> Path:
    config = load_config(config_path)
    artifact_root = Path(config["project"]["artifact_dir"])
    manifest = json.loads((artifact_root / "current.json").read_text(encoding="utf-8"))
    version_dir = Path(manifest["path"])
    metadata = json.loads((version_dir / "metadata.json").read_text(encoding="utf-8"))
    evaluation_path = artifact_root / "evaluation_v2.json"
    batch_path = artifact_root / "recomendaciones.report.json"
    evaluation = json.loads(evaluation_path.read_text(encoding="utf-8")) if evaluation_path.exists() else None
    batch = json.loads(batch_path.read_text(encoding="utf-8")) if batch_path.exists() else None
    audit_path = version_dir / "audit.json"
    audit = json.loads(audit_path.read_text(encoding="utf-8")) if audit_path.exists() else None
    tasks = metadata["metrics"]["group_split"]
    lines = [
        "# Model Card — Motor NBO v2", "", f"Creado: {metadata['created_at']}", "",
        "## Uso previsto", "",
        "Ranking explicable de ofertas elegibles y selección de canal para los datos sintéticos del desafío.", "",
        "## Datos y separación", "",
        "- 100,000 clientes; 22 ofertas; 300,112 ofrecimientos.",
        "- Split principal 70/15/15 por cliente, manifiesto persistente y semilla 42.",
        "- Robustez temporal enero–abril / mayo / junio.",
        "- Los acumulados excluyen el evento evaluado y todos los eventos de su mes.",
        f"- Alpha bayesiano seleccionado en validación: {metadata['selected_smoothing_alpha']}.", "",
        "## Selección honesta champion/fallback", "",
        f"- Contacto: `{tasks['contact']['selected_kind']}`; gate CatBoost: {'aprobado' if tasks['contact']['gate']['passed'] else 'no aprobado'}.",
        f"- Aceptación: `{tasks['acceptance']['selected_kind']}`; gate CatBoost: {'aprobado' if tasks['acceptance']['gate']['passed'] else 'no aprobado'}.",
        f"- Rechazo: `{tasks['rejection']['selected_kind']}`; gate CatBoost: {'aprobado' if tasks['rejection']['gate']['passed'] else 'no aprobado'}.",
        "- Los fallbacks jerárquicos se publican cuando CatBoost no demuestra mejora útil frente a baselines.", "",
        "## Métricas de test", "",
        _metric_line("Contacto", tasks["contact"]["test"]),
        _metric_line("Aceptación condicionada a contacto", tasks["acceptance"]["test"]),
        _metric_line("Motivo de rechazo", tasks["rejection"]["test"]),
    ]
    if evaluation:
        ranking = evaluation["ranking"]
        lines += [
            "", "## Evaluación final de ranking", "",
            f"- Cobertura: {evaluation['coverage']['rate']:.1%} ({evaluation['coverage']['eligible_evaluable']:,}/{evaluation['coverage']['accepted_test_events_considered']:,}).",
            f"- Hit@1={ranking['hit_at_1']:.3f}; Hit@3={ranking['hit_at_3']:.3f}; NDCG@3={ranking['ndcg_at_3']:.3f}.",
            f"- Mejora relativa NDCG@3: {evaluation['ranking_gate']['relative_ndcg_improvement']:.1%} frente al mejor baseline.",
            f"- Gate final: {'APROBADO' if evaluation['ranking_gate']['passed'] else 'NO APROBADO'}.",
            f"- Diversidad Top 1: {evaluation['diversity']['top1_unique_offers']} ofertas; concentración máxima {evaluation['diversity']['max_offer_share']:.1%}.",
            f"- Captura de elegibles MT: {evaluation['business']['mt_capture_eligible']:.1%}.",
            f"- Ruta MT: completa hogar {evaluation['business']['route_home_completion_share']:.1%}; completa móvil postpago {evaluation['business']['route_mobile_completion_share']:.1%}.",
        ]
    if batch:
        lines += [
            "", "## Validación operacional", "",
            f"- Batch: {batch['processed']:,}/{batch['requested']:,}; cobertura {batch['coverage']:.1%}; errores {len(batch['errors'])}.",
            f"- Duración: {batch['duration_seconds']:.1f}s; p50={batch['latency_ms']['p50']:.2f}ms; p95={batch['latency_ms']['p95']:.2f}ms por cliente en chunk.",
            f"- Participación MT recomendada: {batch['distribution']['mt_share']:.1%}; captura de elegibles: {batch['distribution']['mt_capture_eligible']:.1%}.",
            f"- Cobertura catálogo Top 1: {batch['distribution']['top1_unique_offers']}/22; concentración máxima {batch['distribution']['max_offer_share']:.1%}.",
            f"- Ruta MT batch: completa hogar {batch['distribution']['route_home_completion_share']:.1%}; completa móvil {batch['distribution']['route_mobile_completion_share']:.1%}.",
        ]
    if audit:
        important = sorted(audit["feature_group_ablations"], key=lambda item: item["delta_log_loss_vs_full"], reverse=True)
        lines += [
            "", "## Ablación y diagnóstico segmentado", "",
            "- Las ablaciones eliminan un grupo por vez de la regresión logística de aceptación y miden el cambio en validación.",
            "- Grupos con mayor pérdida al retirarlos: " + ", ".join(f"{item['removed_group']} (Δlogloss={item['delta_log_loss_vs_full']:.4f})" for item in important[:3]) + ".",
            f"- Rango Brier por edad: {audit['fairness_diagnostic']['edad_rango']['brier_range']:.4f}; por región: {audit['fairness_diagnostic']['ubicacion_departamento']['brier_range']:.4f}.",
            "- Estas diferencias son diagnósticas y no demuestran discriminación ni causalidad.",
        ]
    lines += [
        "", "## Features y auditoría", "",
        "- `cliente_id` y textos comerciales redundantes se excluyen del modelado.",
        "- Edad y región se usan como variables predictivas/auditoría, nunca como reglas de exclusión.",
        "- Versiones de modelo, features, reglas y catálogo acompañan cada decisión.", "",
        "## Limitaciones y uso responsable", "",
        "- El perfil es un resumen estático de seis meses, no un snapshot mensual perfecto.",
        "- La evaluación refleja la política histórica y no demuestra causalidad ni uplift.",
        "- Precio normalizado es un proxy de valor; no existe margen en los datos.",
        "- No se predice churn ni éxito de rebate por ausencia de targets válidos.",
        "- Las metas MT hogar/móvil son referencias; el dataset no identifica el origen comercial de cada venta MT.",
    ]
    output = version_dir / "MODEL_CARD.md"
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Actualiza model card desde artefactos verificados.")
    parser.add_argument("--config")
    args = parser.parse_args()
    print(build_model_card(args.config))


if __name__ == "__main__":
    main()
