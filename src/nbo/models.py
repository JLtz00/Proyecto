from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.calibration import calibration_curve
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score, average_precision_score, balanced_accuracy_score, brier_score_loss,
    f1_score, log_loss, roc_auc_score,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.multiclass import OneVsRestClassifier


@dataclass
class FramePreprocessor:
    categorical: list[str]
    numeric: list[str]
    medians: dict[str, float] | None = None

    @property
    def columns(self) -> list[str]:
        return self.categorical + self.numeric

    def fit(self, frame: pd.DataFrame) -> "FramePreprocessor":
        self.medians = {}
        for column in self.numeric:
            value = pd.to_numeric(frame[column], errors="coerce").median()
            self.medians[column] = float(value) if pd.notna(value) else 0.0
        return self

    def transform(self, frame: pd.DataFrame) -> pd.DataFrame:
        missing = sorted(set(self.columns).difference(frame.columns))
        if missing:
            raise ValueError(f"Feature schema incompatible; faltan: {missing}")
        output = frame[self.columns].copy()
        for column in self.categorical:
            output[column] = output[column].astype("object").where(output[column].notna(), "unknown").astype(str)
        for column in self.numeric:
            output[column] = pd.to_numeric(output[column], errors="coerce").fillna((self.medians or {}).get(column, 0.0)).astype(float)
        return output


@dataclass
class SigmoidCalibrator:
    model: LogisticRegression

    @staticmethod
    def _logit(probability: np.ndarray) -> np.ndarray:
        probability = np.clip(probability, 1e-6, 1 - 1e-6)
        return np.log(probability / (1 - probability)).reshape(-1, 1)

    @classmethod
    def fit(cls, probability: np.ndarray, target: np.ndarray) -> "SigmoidCalibrator":
        model = LogisticRegression(random_state=42).fit(cls._logit(probability), target)
        return cls(model)

    def predict(self, probability: np.ndarray) -> np.ndarray:
        return self.model.predict_proba(self._logit(probability))[:, 1]


@dataclass
class IsotonicCalibrator:
    model: IsotonicRegression

    @classmethod
    def fit(cls, probability: np.ndarray, target: np.ndarray) -> "IsotonicCalibrator":
        return cls(IsotonicRegression(out_of_bounds="clip").fit(probability, target))

    def predict(self, probability: np.ndarray) -> np.ndarray:
        return np.asarray(self.model.predict(probability), dtype=float)


@dataclass
class ModelArtifact:
    estimator: Any
    preprocessor: FramePreprocessor
    classes: list[Any]
    calibrator: Any = None
    calibration_method: str = "none"
    model_kind: str = "catboost"

    def raw_proba(self, frame: pd.DataFrame) -> np.ndarray:
        prepared = self.preprocessor.transform(frame)
        return np.asarray(self.estimator.predict_proba(prepared))

    def predict_positive(self, frame: pd.DataFrame) -> np.ndarray:
        probability = self.raw_proba(frame)[:, 1]
        if self.calibrator is not None:
            probability = self.calibrator.predict(probability)
        return np.clip(probability, 0, 1)

    def predict_multiclass(self, frame: pd.DataFrame) -> np.ndarray:
        return np.clip(self.raw_proba(frame), 0, 1)

    def local_contributions(self, frame: pd.DataFrame) -> list[dict[str, float]]:
        if self.model_kind != "catboost":
            return [{} for _ in range(len(frame))]
        try:
            from catboost import Pool

            prepared = self.preprocessor.transform(frame)
            pool = Pool(prepared, cat_features=self.preprocessor.categorical)
            values = np.asarray(self.estimator.get_feature_importance(pool, type="ShapValues"))
            if values.ndim == 3:
                values = values[:, 0, :]
            return [dict(zip(self.preprocessor.columns, row[:-1].astype(float))) for row in values]
        except Exception:
            return [{} for _ in range(len(frame))]


@dataclass
class LogisticArtifact:
    """Baseline sklearn persistible con la interfaz común del motor."""

    estimator: Any
    columns: list[str]
    classes: list[Any]
    calibration_method: str = "none"
    model_kind: str = "logistic"

    def predict_positive(self, frame: pd.DataFrame) -> np.ndarray:
        missing = sorted(set(self.columns).difference(frame.columns))
        if missing:
            raise ValueError(f"Feature schema incompatible; faltan: {missing}")
        probability = np.asarray(self.estimator.predict_proba(frame[self.columns]))
        positive_index = self.classes.index(1)
        return np.clip(probability[:, positive_index], 0, 1)

    def local_contributions(self, frame: pd.DataFrame) -> list[dict[str, float]]:
        return [{} for _ in range(len(frame))]


@dataclass
class RateArtifact:
    """Fallback auditable basado en una tasa histórica jerárquica calibrada."""

    rate_column: str
    calibrator: Any
    calibration_method: str
    classes: list[int]
    model_kind: str = "hierarchical_rate"

    def predict_positive(self, frame: pd.DataFrame) -> np.ndarray:
        probability = pd.to_numeric(frame[self.rate_column], errors="coerce").fillna(0.5).to_numpy(dtype=float)
        if self.calibrator is not None:
            probability = self.calibrator.predict(probability)
        return np.clip(probability, 0, 1)

    def local_contributions(self, frame: pd.DataFrame) -> list[dict[str, float]]:
        return [{self.rate_column: float(value) - 0.5} for value in frame[self.rate_column]]


@dataclass
class MulticlassPriorArtifact:
    """Fallback suavizado por tipo de oferta y canal para motivos de rechazo."""

    classes: list[str]
    global_probability: np.ndarray
    group_probability: dict[tuple[str, str], np.ndarray]
    model_kind: str = "hierarchical_prior"

    def predict_multiclass(self, frame: pd.DataFrame) -> np.ndarray:
        rows = []
        for _, row in frame.iterrows():
            rows.append(self.group_probability.get((str(row["tipo_oferta"]), str(row["canal"])), self.global_probability))
        return np.asarray(rows, dtype=float)

    def local_contributions(self, frame: pd.DataFrame) -> list[dict[str, float]]:
        return [{} for _ in range(len(frame))]


def binary_metrics(target: np.ndarray, probability: np.ndarray) -> dict[str, Any]:
    probability = np.clip(np.asarray(probability, dtype=float), 1e-7, 1 - 1e-7)
    result: dict[str, Any] = {
        "log_loss": float(log_loss(target, probability)),
        "brier": float(brier_score_loss(target, probability)),
        "mean_probability": float(probability.mean()),
        "prevalence": float(np.mean(target)),
    }
    if len(np.unique(target)) > 1:
        result["roc_auc"] = float(roc_auc_score(target, probability))
        result["pr_auc"] = float(average_precision_score(target, probability))
        true, pred = calibration_curve(target, probability, n_bins=10, strategy="quantile")
        result["calibration_curve"] = {"predicted": pred.tolist(), "observed": true.tolist()}
        result["ece"] = float(np.mean(np.abs(true - pred)))
    return result


def _tie_rate(probability: np.ndarray) -> float:
    if len(probability) <= 1:
        return 0.0
    return float(1 - len(np.unique(np.round(probability, 8))) / len(probability))


def fit_calibrator(
    target: np.ndarray, probability: np.ndarray, max_tie_rate: float = 1.0
) -> tuple[str, Any, dict]:
    candidates: list[tuple[str, Any, np.ndarray]] = [("none", None, probability)]
    if len(np.unique(target)) > 1:
        sigmoid = SigmoidCalibrator.fit(probability, target)
        isotonic = IsotonicCalibrator.fit(probability, target)
        candidates.extend([
            ("sigmoid", sigmoid, sigmoid.predict(probability)),
            ("isotonic", isotonic, isotonic.predict(probability)),
        ])
    metrics = {name: {**binary_metrics(target, pred), "tie_rate": _tie_rate(pred)} for name, _, pred in candidates}
    eligible = [item for item in candidates if item[0] != "isotonic" or metrics[item[0]]["tie_rate"] <= max_tie_rate]
    method, calibrator, _ = min(eligible, key=lambda item: (metrics[item[0]]["brier"], metrics[item[0]]["log_loss"]))
    return method, calibrator, metrics


def fit_hierarchical_multiclass_prior(
    train: pd.DataFrame, target: pd.Series, alpha: float = 20.0
) -> MulticlassPriorArtifact:
    classes = sorted(target.astype(str).unique().tolist())
    counts = target.astype(str).value_counts().reindex(classes, fill_value=0).to_numpy(dtype=float)
    global_probability = counts / counts.sum()
    work = train[["tipo_oferta", "canal"]].copy()
    work["target"] = target.astype(str).to_numpy()
    group_probability: dict[tuple[str, str], np.ndarray] = {}
    for key, group in work.groupby(["tipo_oferta", "canal"], observed=True):
        group_counts = group["target"].value_counts().reindex(classes, fill_value=0).to_numpy(dtype=float)
        group_probability[(str(key[0]), str(key[1]))] = (group_counts + alpha * global_probability) / (len(group) + alpha)
    return MulticlassPriorArtifact(classes, global_probability, group_probability)


def multiclass_metrics(target: np.ndarray, probability: np.ndarray, classes: list[str]) -> dict[str, float]:
    labels = np.asarray(classes)
    prediction = labels[probability.argmax(axis=1)]
    top2 = labels[np.argsort(probability, axis=1)[:, -2:]]
    return {
        "accuracy": float(accuracy_score(target, prediction)),
        "balanced_accuracy": float(balanced_accuracy_score(target, prediction)),
        "macro_f1": float(f1_score(target, prediction, average="macro")),
        "top2_accuracy": float(np.mean([str(value) in row for value, row in zip(target, top2)])),
        "log_loss": float(log_loss(target, probability, labels=classes)),
    }


def fit_logistic_baseline(
    train: pd.DataFrame, target: np.ndarray, categorical: list[str], numeric: list[str]
) -> Pipeline:
    transformer = ColumnTransformer([
        ("categorical", Pipeline([
            ("imputer", SimpleImputer(strategy="most_frequent")),
            ("onehot", OneHotEncoder(handle_unknown="ignore", min_frequency=5)),
        ]), categorical),
        ("numeric", Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("scale", StandardScaler(with_mean=False)),
        ]), numeric),
    ])
    model = Pipeline([
        ("transform", transformer),
        ("model", OneVsRestClassifier(LogisticRegression(max_iter=400, random_state=42, solver="liblinear"))),
    ])
    return model.fit(train[categorical + numeric], target)


def fit_catboost(
    train: pd.DataFrame,
    target: np.ndarray,
    preprocessor: FramePreprocessor,
    config: dict,
    multiclass: bool = False,
) -> Any:
    from catboost import CatBoostClassifier

    params = {
        "iterations": int(config["catboost_iterations"]),
        "depth": int(config["catboost_depth"]),
        "learning_rate": float(config["catboost_learning_rate"]),
        "random_seed": 42,
        "verbose": False,
        "thread_count": int(config.get("thread_count", -1)),
        "loss_function": "MultiClass" if multiclass else "Logloss",
        "allow_writing_files": False,
    }
    if config.get("auto_class_weights"):
        params["auto_class_weights"] = config["auto_class_weights"]
    model = CatBoostClassifier(**params)
    prepared = preprocessor.transform(train)
    model.fit(prepared, target, cat_features=preprocessor.categorical)
    return model


def save_artifact(artifact: ModelArtifact, path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(artifact, path)


def load_artifact(path: str | Path) -> ModelArtifact:
    return joblib.load(path)
