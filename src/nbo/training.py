from __future__ import annotations

import argparse
import itertools
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import confusion_matrix

from .config import load_config
from .data import clean_semantic_nulls, load_raw
from .features import apply_smoothing_alpha, build_historical_features, model_feature_columns
from .models import (
    FramePreprocessor, ModelArtifact, RateArtifact, binary_metrics, fit_calibrator,
    fit_catboost, fit_hierarchical_multiclass_prior, fit_logistic_baseline,
    multiclass_metrics, save_artifact,
)
from .splits import (
    apply_group_assignments, make_group_assignments, save_split_manifest,
    temporal_split,
)
from .validation import validate_data


def group_split(client_ids: pd.Series, seed: int = 42) -> np.ndarray:
    """Compatibilidad pública; entrenamiento guarda además el manifiesto exacto."""
    return apply_group_assignments(client_ids, make_group_assignments(client_ids, seed))


def _slice(frame: pd.DataFrame, split: np.ndarray, name: str) -> pd.DataFrame:
    return frame.loc[split == name]


def _search_configs(config: dict, seed: int) -> list[dict[str, Any]]:
    grid = list(itertools.product(
        [5, 6, 7, 8], [0.03, 0.06, 0.10], [120, 220], [None, "Balanced"]
    ))
    rng = np.random.default_rng(seed)
    rng.shuffle(grid)
    trials = int(config.get("search_trials", 20))
    result = []
    for depth, rate, iterations, weights in grid[:trials]:
        candidate = dict(config)
        candidate.update({
            "catboost_depth": depth, "catboost_learning_rate": rate,
            "catboost_iterations": iterations, "auto_class_weights": weights,
        })
        result.append(candidate)
    # En smoke tests se respeta explícitamente la configuración pequeña solicitada.
    if trials == 1:
        candidate = dict(config)
        candidate["auto_class_weights"] = config.get("auto_class_weights")
        return [candidate]
    return result


def _search_sample(frame: pd.DataFrame, target: np.ndarray, size: int, seed: int) -> tuple[pd.DataFrame, np.ndarray]:
    if len(frame) <= size:
        return frame, target
    positions = pd.Series(np.arange(len(frame))).groupby(target, observed=True).apply(
        lambda values: values.sample(max(1, round(size * len(values) / len(frame))), random_state=seed)
    ).to_numpy(dtype=int)
    positions = positions[:size]
    return frame.iloc[positions], target[positions]


def _calibrated_rate(
    validation: pd.DataFrame, target: np.ndarray, rate_column: str, max_tie_rate: float
) -> tuple[RateArtifact, dict]:
    raw = pd.to_numeric(validation[rate_column], errors="coerce").fillna(float(np.mean(target))).to_numpy()
    method, calibrator, candidates = fit_calibrator(target, raw, max_tie_rate)
    artifact = RateArtifact(rate_column, calibrator, method, [0, 1])
    return artifact, {"selected_calibration": method, "calibration_candidates": candidates}


def _binary_slices(test: pd.DataFrame, target: np.ndarray, probability: np.ndarray) -> dict:
    slices: dict[str, dict] = {}
    for column in ("canal", "edad_rango", "ubicacion_departamento", "tipo_oferta", "etapa_mt", "oferta_es_mt"):
        slices[column] = {}
        for value, positions in test.reset_index(drop=True).groupby(column, observed=True).groups.items():
            indexes = np.asarray(list(positions), dtype=int)
            if len(indexes) >= 20 and len(np.unique(target[indexes])) > 1:
                compact = binary_metrics(target[indexes], probability[indexes])
                slices[column][str(value)] = {key: compact[key] for key in ("roc_auc", "pr_auc", "log_loss", "brier", "prevalence")}
    return slices


def _train_binary(
    frame: pd.DataFrame,
    target: pd.Series,
    split: np.ndarray,
    categorical: list[str],
    numeric: list[str],
    config: dict,
    rate_column: str,
    seed: int,
) -> tuple[Any, RateArtifact, dict]:
    train, validation, test = (_slice(frame, split, name) for name in ("train", "validation", "test"))
    y_train, y_validation, y_test = (target.loc[item.index].astype(int).to_numpy() for item in (train, validation, test))
    max_tie = float(config["calibration"]["max_tie_rate"])

    logistic = fit_logistic_baseline(train, y_train, categorical, numeric)
    logistic_validation = logistic.predict_proba(validation[categorical + numeric])[:, 1]
    logistic_metrics = binary_metrics(y_validation, logistic_validation)
    fallback, fallback_calibration = _calibrated_rate(validation, y_validation, rate_column, max_tie)
    fallback_metrics = binary_metrics(y_validation, fallback.predict_positive(validation))

    search_train, search_target = _search_sample(
        train, y_train, int(config.get("search_sample_size", 60000)), seed
    )
    pre_search = FramePreprocessor(categorical, numeric).fit(search_train)
    search_results = []
    for index, candidate_config in enumerate(_search_configs(config, seed), 1):
        model = fit_catboost(search_train, search_target, pre_search, candidate_config)
        probability = model.predict_proba(pre_search.transform(validation))[:, 1]
        metrics = binary_metrics(y_validation, probability)
        search_results.append({
            "trial": index,
            "params": {key: candidate_config.get(key) for key in ("catboost_iterations", "catboost_depth", "catboost_learning_rate", "auto_class_weights")},
            "metrics": metrics,
        })
    finalists = sorted(search_results, key=lambda item: (item["metrics"]["brier"], item["metrics"]["log_loss"]))[: int(config.get("finalists", 3))]
    preprocessor = FramePreprocessor(categorical, numeric).fit(train)
    full_models = []
    for item in finalists:
        candidate_config = {**config, **item["params"]}
        model = fit_catboost(train, y_train, preprocessor, candidate_config)
        raw = model.predict_proba(preprocessor.transform(validation))[:, 1]
        method, calibrator, calibration = fit_calibrator(y_validation, raw, max_tie)
        artifact = ModelArtifact(model, preprocessor, list(model.classes_), calibrator, method, "catboost")
        metrics = binary_metrics(y_validation, artifact.predict_positive(validation))
        full_models.append((artifact, item["params"], metrics, calibration))
    cat_artifact, cat_params, cat_metrics, cat_calibration = min(full_models, key=lambda item: (item[2]["brier"], item[2]["log_loss"]))

    reference = min((logistic_metrics, fallback_metrics), key=lambda value: (value["brier"], value["log_loss"]))
    relative_brier = (reference["brier"] - cat_metrics["brier"]) / max(reference["brier"], 1e-12)
    relative_logloss = (reference["log_loss"] - cat_metrics["log_loss"]) / max(reference["log_loss"], 1e-12)
    gate = config["champion_gate"]
    passed = (
        max(relative_brier, relative_logloss) >= float(gate["relative_loss_improvement"])
        and cat_metrics.get("roc_auc", 0.5) - reference.get("roc_auc", 0.5) >= float(gate["auc_improvement"])
    )
    selected = cat_artifact if passed else fallback
    test_probability = selected.predict_positive(test)
    metrics = {
        "rows": {"train": len(train), "validation": len(validation), "test": len(test)},
        "baseline_logistic_validation": logistic_metrics,
        "fallback_validation": fallback_metrics,
        "fallback_calibration": fallback_calibration,
        "search": search_results,
        "finalist_params": [item["params"] for item in finalists],
        "catboost_validation": cat_metrics,
        "catboost_calibration_candidates": cat_calibration,
        "selected_kind": selected.model_kind,
        "selected_calibration": selected.calibration_method,
        "gate": {"passed": passed, "relative_brier": relative_brier, "relative_log_loss": relative_logloss},
        "test": binary_metrics(y_test, test_probability),
        "test_slices": _binary_slices(test, y_test, test_probability),
    }
    return selected, fallback, metrics


def _train_rejection(
    frame: pd.DataFrame, split: np.ndarray, categorical: list[str], numeric: list[str], config: dict, seed: int
) -> tuple[Any, dict]:
    train, validation, test = (_slice(frame, split, name) for name in ("train", "validation", "test"))
    y_train = train["motivo_rechazo"].astype(str).to_numpy()
    y_validation = validation["motivo_rechazo"].astype(str).to_numpy()
    y_test = test["motivo_rechazo"].astype(str).to_numpy()
    logistic = fit_logistic_baseline(train, y_train, categorical, numeric)
    logistic_classes = list(logistic.classes_)
    logistic_metrics = multiclass_metrics(y_validation, logistic.predict_proba(validation[categorical + numeric]), logistic_classes)
    prior = fit_hierarchical_multiclass_prior(train, train["motivo_rechazo"], alpha=20)
    prior_metrics = multiclass_metrics(y_validation, prior.predict_multiclass(validation), prior.classes)

    search_train, search_target = _search_sample(train, y_train, int(config.get("search_sample_size", 60000)), seed)
    pre_search = FramePreprocessor(categorical, numeric).fit(search_train)
    search = []
    for index, candidate_config in enumerate(_search_configs(config, seed), 1):
        model = fit_catboost(search_train, search_target, pre_search, candidate_config, multiclass=True)
        probability = model.predict_proba(pre_search.transform(validation))
        metrics = multiclass_metrics(y_validation, probability, list(model.classes_))
        search.append({"trial": index, "params": {key: candidate_config.get(key) for key in ("catboost_iterations", "catboost_depth", "catboost_learning_rate", "auto_class_weights")}, "metrics": metrics})
    finalists = sorted(search, key=lambda item: (item["metrics"]["log_loss"], -item["metrics"]["macro_f1"]))[: int(config.get("finalists", 3))]
    preprocessor = FramePreprocessor(categorical, numeric).fit(train)
    full = []
    for item in finalists:
        model = fit_catboost(train, y_train, preprocessor, {**config, **item["params"]}, multiclass=True)
        artifact = ModelArtifact(model, preprocessor, list(model.classes_), model_kind="catboost")
        metrics = multiclass_metrics(y_validation, artifact.predict_multiclass(validation), artifact.classes)
        full.append((artifact, item["params"], metrics))
    cat_artifact, cat_params, cat_metrics = min(full, key=lambda item: (item[2]["log_loss"], -item[2]["macro_f1"]))
    reference = min((logistic_metrics, prior_metrics), key=lambda value: (value["log_loss"], -value["macro_f1"]))
    gate = config["champion_gate"]
    loss_improvement = (reference["log_loss"] - cat_metrics["log_loss"]) / max(reference["log_loss"], 1e-12)
    f1_improvement = cat_metrics["macro_f1"] - reference["macro_f1"]
    passed = loss_improvement >= float(gate["relative_loss_improvement"]) or f1_improvement >= float(gate["rejection_macro_f1_improvement"])
    selected = cat_artifact if passed else prior
    test_probability = selected.predict_multiclass(test)
    test_metrics = multiclass_metrics(y_test, test_probability, selected.classes)
    labels = selected.classes
    prediction = np.asarray(labels)[test_probability.argmax(axis=1)]
    return selected, {
        "rows": {"train": len(train), "validation": len(validation), "test": len(test)},
        "baseline_logistic_validation": logistic_metrics,
        "fallback_prior_validation": prior_metrics,
        "search": search,
        "finalist_params": [item["params"] for item in finalists],
        "catboost_validation": cat_metrics,
        "selected_kind": selected.model_kind,
        "gate": {"passed": passed, "relative_log_loss": loss_improvement, "macro_f1_improvement": f1_improvement},
        "test": test_metrics,
        "confusion_matrix": {"labels": labels, "values": confusion_matrix(y_test, prediction, labels=labels).tolist()},
    }


def _select_smoothing_alpha(frame: pd.DataFrame, split: np.ndarray, alphas: list[float]) -> tuple[float, list[dict]]:
    validation_mask = split == "validation"
    reports = []
    for alpha in alphas:
        candidate = apply_smoothing_alpha(frame, float(alpha))
        contact_target = candidate.loc[validation_mask, "contactabilidad"].eq("contactado").astype(int).to_numpy()
        contact_probability = candidate.loc[validation_mask, "hist_contact_rate_channel"].to_numpy()
        contacted = validation_mask & candidate["resultado"].isin(["aceptada", "rechazada"]).to_numpy()
        acceptance_target = candidate.loc[contacted, "resultado"].eq("aceptada").astype(int).to_numpy()
        acceptance_probability = candidate.loc[contacted, "hist_accept_rate_channel"].to_numpy()
        contact = binary_metrics(contact_target, contact_probability)
        acceptance = binary_metrics(acceptance_target, acceptance_probability)
        reports.append({"alpha": float(alpha), "contact_brier": contact["brier"], "acceptance_brier": acceptance["brier"], "mean_brier": (contact["brier"] + acceptance["brier"]) / 2})
    best = min(reports, key=lambda item: item["mean_brier"])
    return best["alpha"], reports


def _write_model_card(path: Path, metadata: dict) -> None:
    tasks = metadata["metrics"]["group_split"]
    lines = [
        "# Model Card — Motor NBO v2", "",
        f"Creado: {metadata['created_at']}", "",
        "## Uso previsto", "",
        "Ranking explicable de ofertas elegibles y selección de canal para datos sintéticos del desafío.", "",
        "## Datos y separación", "",
        "- 100,000 clientes; catálogo de 22 ofertas; 300,112 ofrecimientos.",
        "- Split principal 70/15/15 por cliente con semilla 42.",
        "- Robustez temporal enero–abril / mayo / junio.",
        "- Los acumulados excluyen el evento y todo su mes.", "",
        "## Modelos seleccionados", "",
        f"- Contacto: `{tasks['contact']['selected_kind']}`.",
        f"- Aceptación: `{tasks['acceptance']['selected_kind']}`.",
        f"- Rechazo: `{tasks['rejection']['selected_kind']}`.", "",
        "## Limitaciones y uso responsable", "",
        "- El perfil es un resumen estático de seis meses, no un snapshot mensual perfecto.",
        "- La evaluación observacional refleja la política histórica y no demuestra causalidad.",
        "- Precio normalizado es un proxy de valor; no existe margen en los datos.",
        "- No predice churn ni éxito de rebate por ausencia de targets válidos.",
        "- No usar edad o región para excluir ofertas; solo para auditoría de desempeño.",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def train_all(
    config_path: str | None = None,
    sample_size: int | None = None,
    quick: bool = False,
) -> Path:
    config = load_config(config_path)
    if quick:
        sample_size = sample_size or 6000
        config["project"]["model_version"] = "nbo_smoke"
        config["training"].update({
            "catboost_iterations": 5,
            "catboost_depth": 4,
            "search_trials": 1,
            "search_sample_size": min(int(sample_size), 6000),
            "finalists": 1,
            "smoothing_alphas": [10.0],
        })
    seed = int(config["project"]["seed"])
    customers, catalog, history = load_raw(config["project"]["data_dir"])
    quality = validate_data(customers, catalog, history, config["validation"])
    quality.raise_for_errors()
    customers, catalog, history = clean_semantic_nulls(customers, catalog, history)
    frame = build_historical_features(customers, catalog, history, 10.0, config["features"]["friction_weights"])
    if sample_size and sample_size < len(frame):
        frame = frame.sample(sample_size, random_state=seed).sort_index()

    assignments = make_group_assignments(customers["cliente_id"], seed)
    split = apply_group_assignments(frame["cliente_id"], assignments)
    alpha, alpha_report = _select_smoothing_alpha(frame, split, config["training"]["smoothing_alphas"])
    frame = apply_smoothing_alpha(frame, alpha)
    categorical, numeric = model_feature_columns(frame)
    training_config = config["training"]

    contact_target = frame["contactabilidad"].eq("contactado")
    contact, contact_fallback, contact_metrics = _train_binary(
        frame, contact_target, split, categorical, numeric, training_config,
        "hist_contact_rate_channel", seed,
    )
    contacted = frame["resultado"].isin(["aceptada", "rechazada"])
    acceptance_frame = frame.loc[contacted]
    acceptance_split = split[contacted.to_numpy()]
    acceptance_target = acceptance_frame["resultado"].eq("aceptada")
    acceptance, acceptance_fallback, acceptance_metrics = _train_binary(
        acceptance_frame, acceptance_target, acceptance_split, categorical, numeric,
        training_config, "hist_accept_rate_channel", seed + 1,
    )
    rejected = frame["resultado"].eq("rechazada")
    rejection, rejection_metrics = _train_rejection(
        frame.loc[rejected], split[rejected.to_numpy()], categorical, numeric, training_config, seed + 2
    )

    temporal = temporal_split(frame["fecha"])
    temporal_contact, _, temporal_contact_metrics = _train_binary(
        frame, contact_target, temporal, categorical, numeric, training_config,
        "hist_contact_rate_channel", seed + 3,
    )
    temporal_acceptance, _, temporal_acceptance_metrics = _train_binary(
        acceptance_frame, acceptance_target, temporal[contacted.to_numpy()], categorical,
        numeric, training_config, "hist_accept_rate_channel", seed + 4,
    )
    max_degradation = float(training_config["champion_gate"]["temporal_max_degradation"])
    if contact.model_kind == "catboost" and contact_metrics["test"].get("roc_auc", .5) - temporal_contact_metrics["test"].get("roc_auc", .5) > max_degradation:
        contact, contact_metrics["selected_kind"] = contact_fallback, contact_fallback.model_kind
        contact_metrics["temporal_gate_fallback"] = True
    if acceptance.model_kind == "catboost" and acceptance_metrics["test"].get("roc_auc", .5) - temporal_acceptance_metrics["test"].get("roc_auc", .5) > max_degradation:
        acceptance, acceptance_metrics["selected_kind"] = acceptance_fallback, acceptance_fallback.model_kind
        acceptance_metrics["temporal_gate_fallback"] = True

    version = config["project"]["model_version"]
    artifact_root = Path(config["project"]["artifact_dir"])
    version_dir = artifact_root / version
    version_dir.mkdir(parents=True, exist_ok=True)
    save_artifact(contact, version_dir / "contact.joblib")
    save_artifact(acceptance, version_dir / "acceptance.joblib")
    save_artifact(rejection, version_dir / "rejection.joblib")
    save_split_manifest(assignments, version_dir / "split_manifest.json", seed)
    schema = {"categorical": categorical, "numeric": numeric, "all": categorical + numeric}
    (version_dir / "feature_schema.json").write_text(json.dumps(schema, indent=2, ensure_ascii=False), encoding="utf-8")
    metadata = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "versions": {key: config["project"][key] for key in ("model_version", "feature_version", "rules_version", "catalog_version")},
        "seed": seed, "sample_size": sample_size, "quick_mode": quick,
        "selected_smoothing_alpha": alpha,
        "smoothing_search": alpha_report, "quality": quality.to_dict(),
        "excluded_features": ["cliente_id", "nombre_oferta", "oferta_es_movistar_total"],
        "metrics": {
            "group_split": {"contact": contact_metrics, "acceptance": acceptance_metrics, "rejection": rejection_metrics},
            "temporal_robustness": {"contact": temporal_contact_metrics, "acceptance": temporal_acceptance_metrics},
        },
        "temporal_limitation": "El perfil de clientes resume seis meses y no es un snapshot mensual perfecto.",
    }
    (version_dir / "metadata.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    _write_model_card(version_dir / "MODEL_CARD.md", metadata)
    # El manifiesto debe sobrevivir a clones y cambios de directorio.
    (artifact_root / "current.json").write_text(
        json.dumps({"version": version, "path": version}, indent=2), encoding="utf-8",
    )
    return version_dir


def main() -> None:
    parser = argparse.ArgumentParser(description="Entrena y audita los modelos NBO v2.")
    parser.add_argument("--config")
    parser.add_argument("--sample-size", type=int, help="Solo para smoke tests; el artefacto queda marcado.")
    parser.add_argument(
        "--quick", action="store_true",
        help="Smoke reproducible: 6,000 filas, un trial y cinco iteraciones; genera nbo_smoke.",
    )
    args = parser.parse_args()
    print(train_all(args.config, args.sample_size, quick=args.quick))


if __name__ == "__main__":
    main()
