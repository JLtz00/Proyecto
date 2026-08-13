from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .config import load_config
from .data import clean_semantic_nulls, load_raw
from .features import apply_smoothing_alpha, build_historical_features, model_feature_columns
from .models import binary_metrics, fit_logistic_baseline, load_artifact
from .splits import apply_group_assignments, load_split_manifest


def _feature_groups(columns: list[str]) -> dict[str, list[str]]:
    definitions = {
        "profile": {
            "tipo_cliente", "antiguedad_meses", "tiene_movil", "tiene_hogar", "oferta_hogar_id",
            "tiene_internet_hogar", "plan_actual_id", "monto_facturado_prom", "edad_rango",
            "ubicacion_departamento", "es_usuario_app", "consumo_datos_gb_prom", "consumo_voz_min_prom",
            "consumo_sms_prom", "uso_app_movistar_prom", "monto_facturado_prom_6m", "n_actividad_canal",
        },
        "offer": {
            "oferta_id", "tipo_oferta", "segmento_objetivo", "precio_mensual", "ahorro_pct",
            "gb_incluidos", "cluster_hogar", "oferta_es_movil", "oferta_es_hogar", "oferta_es_upgrade",
            "oferta_es_equipo", "oferta_es_paquete", "oferta_es_mt", "oferta_es_ilimitada",
        },
        "channel": {"canal", "canal_mas_usado", "match_canal_preferido", "hist_contact_rate_channel", "hist_accept_rate_channel"},
        "price_capacity": {"delta_precio", "precio_vs_facturacion", "ratio_precio_facturacion", "gap_gb", "presion_precio"},
        "mt_path": {"es_movistar_total", "elegible_mt", "etapa_mt"},
        "friction": {"dias_mora_prom", "meses_moroso", "n_reclamos", "mora_riesgo", "reclamos_por_antiguedad", "fatiga_comercial", "friccion_cliente", "friccion_candidato", "sensibilidad_precio"},
        "history": {column for column in columns if column.startswith("hist_")} | {"days_since_last_client_offer", "days_since_last_offer"},
    }
    return {name: sorted(set(columns).intersection(values)) for name, values in definitions.items()}


def _slice_metrics(frame: pd.DataFrame, target: np.ndarray, probability: np.ndarray) -> dict:
    output = {}
    for column in ("canal", "edad_rango", "ubicacion_departamento", "tipo_oferta", "etapa_mt", "oferta_es_mt"):
        output[column] = {}
        groups = frame.reset_index(drop=True).groupby(column, observed=True).groups
        for value, positions in groups.items():
            indexes = np.asarray(list(positions), dtype=int)
            if len(indexes) >= 50 and len(np.unique(target[indexes])) > 1:
                metrics = binary_metrics(target[indexes], probability[indexes])
                output[column][str(value)] = {key: metrics[key] for key in ("roc_auc", "pr_auc", "brier", "log_loss", "prevalence")}
    return output


def audit(config_path: str | None = None) -> Path:
    config = load_config(config_path)
    artifact_root = Path(config["project"]["artifact_dir"])
    manifest = json.loads((artifact_root / "current.json").read_text(encoding="utf-8"))
    version_dir = Path(manifest["path"])
    metadata = json.loads((version_dir / "metadata.json").read_text(encoding="utf-8"))
    split_manifest = load_split_manifest(version_dir / "split_manifest.json")
    customers, catalog, history = load_raw(config["project"]["data_dir"])
    customers, catalog, history = clean_semantic_nulls(customers, catalog, history)
    frame = build_historical_features(
        customers, catalog, history, 10.0, config["features"]["friction_weights"]
    )
    frame = apply_smoothing_alpha(frame, float(metadata["selected_smoothing_alpha"]))
    split = apply_group_assignments(frame["cliente_id"], split_manifest["assignments"])
    categorical, numeric = model_feature_columns(frame)
    all_features = categorical + numeric

    contacted = frame["resultado"].isin(["aceptada", "rechazada"])
    acceptance = frame.loc[contacted]
    acceptance_split = split[contacted.to_numpy()]
    train = acceptance.loc[acceptance_split == "train"]
    validation = acceptance.loc[acceptance_split == "validation"]
    test = acceptance.loc[acceptance_split == "test"]
    y_train = train["resultado"].eq("aceptada").astype(int).to_numpy()
    y_validation = validation["resultado"].eq("aceptada").astype(int).to_numpy()
    y_test = test["resultado"].eq("aceptada").astype(int).to_numpy()
    selected = load_artifact(version_dir / "acceptance.joblib")
    probability = selected.predict_positive(test)

    groups = _feature_groups(all_features)
    ablations = []
    full_model = fit_logistic_baseline(train, y_train, categorical, numeric)
    full_metrics = binary_metrics(y_validation, full_model.predict_proba(validation[all_features])[:, 1])
    for name, removed in groups.items():
        kept_categorical = [column for column in categorical if column not in removed]
        kept_numeric = [column for column in numeric if column not in removed]
        model = fit_logistic_baseline(train, y_train, kept_categorical, kept_numeric)
        metrics = binary_metrics(y_validation, model.predict_proba(validation[kept_categorical + kept_numeric])[:, 1])
        ablations.append({
            "removed_group": name, "removed_features": removed, "metrics": metrics,
            "delta_brier_vs_full": metrics["brier"] - full_metrics["brier"],
            "delta_log_loss_vs_full": metrics["log_loss"] - full_metrics["log_loss"],
        })
    slices = _slice_metrics(test, y_test, probability)
    fairness_ranges = {}
    for dimension in ("edad_rango", "ubicacion_departamento"):
        values = list(slices[dimension].values())
        fairness_ranges[dimension] = {
            "brier_range": max(item["brier"] for item in values) - min(item["brier"] for item in values),
            "log_loss_range": max(item["log_loss"] for item in values) - min(item["log_loss"] for item in values),
            "note": "Diagnóstico descriptivo; no prueba discriminación ni causalidad.",
        }
    report = {
        "model_version": metadata["versions"]["model_version"],
        "acceptance_selected_kind": selected.model_kind,
        "acceptance_test": binary_metrics(y_test, probability),
        "acceptance_test_slices": slices,
        "acceptance_logistic_full_validation": full_metrics,
        "feature_group_ablations": ablations,
        "fairness_diagnostic": fairness_ranges,
    }
    output = version_dir / "audit.json"
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Auditoría segmentada y ablación de features.")
    parser.add_argument("--config")
    args = parser.parse_args()
    print(audit(args.config))


if __name__ == "__main__":
    main()
