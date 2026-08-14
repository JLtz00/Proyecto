"""Modelos de enriquecimiento: churn proxy, personas y uplift de MT.

Se distribuyen como artefactos independientes de `nbo_v2` para que el motor
principal siga siendo reproducible aun sin ellos. Todo se degrada de forma
segura: si un artefacto falta, el campo asociado se marca como `no_disponible`
y el pipeline continúa.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
from sklearn.preprocessing import StandardScaler


CHURN_FEATURES = [
    "antiguedad_meses",
    "monto_facturado_prom",
    "monto_facturado_prom_6m",
    "consumo_datos_gb_prom",
    "consumo_voz_min_prom",
    "uso_app_movistar_prom",
    "n_actividad_canal",
    "n_reclamos",
    "dias_mora_prom",
    "meses_moroso",
    "elegible_mt",
    "es_movistar_total",
    "tiene_movil",
    "tiene_hogar",
]

PERSONA_FEATURES = [
    "antiguedad_meses",
    "monto_facturado_prom",
    "consumo_datos_gb_prom",
    "consumo_voz_min_prom",
    "uso_app_movistar_prom",
    "n_actividad_canal",
    "n_reclamos",
    "dias_mora_prom",
    "elegible_mt",
    "es_movistar_total",
]

CHURN_LEVELS = ((0.65, "alto"), (0.35, "medio"))


def _numeric_frame(customers: pd.DataFrame, features: list[str]) -> pd.DataFrame:
    frame = customers.reindex(columns=features).copy()
    for column in features:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame.fillna(frame.median(numeric_only=True)).fillna(0.0)


def _build_churn_proxy_target(customers: pd.DataFrame) -> pd.Series:
    """Etiqueta proxy de riesgo de fuga a partir de señales operacionales.

    Explícitamente **no** es churn observado: combina mora, reclamos, caída de
    facturación y ausencia de servicios activos para producir una variable
    binaria de referencia que el modelo aprende a suavizar. Ver model card.
    """
    facturacion = pd.to_numeric(customers["monto_facturado_prom"], errors="coerce")
    facturacion_6m = pd.to_numeric(customers["monto_facturado_prom_6m"], errors="coerce")
    caida = (facturacion_6m > 0) & (facturacion / facturacion_6m.clip(lower=1) < 0.70)
    inactivo = ~customers["tiene_movil"].astype(bool) & ~customers["tiene_hogar"].astype(bool)
    mora = pd.to_numeric(customers["dias_mora_prom"], errors="coerce") > 20
    delincuencia = pd.to_numeric(customers["meses_moroso"], errors="coerce") >= 3
    reclamos = pd.to_numeric(customers["n_reclamos"], errors="coerce") >= 3
    antiguedad = pd.to_numeric(customers["antiguedad_meses"], errors="coerce") >= 6
    proxy = ((caida & antiguedad) | inactivo | mora | delincuencia | reclamos).fillna(False)
    return proxy.astype(int)


@dataclass
class ChurnModel:
    """Regresión logística sobre un proxy operacional de riesgo de fuga."""

    model: LogisticRegression
    scaler: StandardScaler
    features: list[str]
    prevalence: float
    metrics: dict[str, float]
    proxy_definition: str
    model_kind: str = "logreg_proxy"

    def predict(self, frame: pd.DataFrame) -> np.ndarray:
        raw = _numeric_frame(frame, self.features)
        scaled = self.scaler.transform(raw.to_numpy())
        return np.clip(self.model.predict_proba(scaled)[:, 1], 0.0, 1.0)

    @staticmethod
    def level(probability: float) -> str:
        for threshold, name in CHURN_LEVELS:
            if probability >= threshold:
                return name
        return "bajo"


@dataclass
class PersonaModel:
    """Clustering K-Means auditable sobre features del perfil vigente."""

    kmeans: KMeans
    scaler: StandardScaler
    features: list[str]
    persona_names: dict[int, str]
    persona_descriptions: dict[int, str]
    persona_stats: dict[int, dict[str, float]]
    model_kind: str = "kmeans"

    def assign(self, frame: pd.DataFrame) -> np.ndarray:
        raw = _numeric_frame(frame, self.features)
        scaled = self.scaler.transform(raw.to_numpy())
        return self.kmeans.predict(scaled).astype(int)

    def describe(self, cluster_id: int) -> tuple[str, str]:
        name = self.persona_names.get(int(cluster_id), f"Persona {int(cluster_id)}")
        description = self.persona_descriptions.get(int(cluster_id), "")
        return name, description


def train_churn(customers: pd.DataFrame, seed: int = 42) -> ChurnModel:
    target = _build_churn_proxy_target(customers)
    frame = _numeric_frame(customers, CHURN_FEATURES)
    scaler = StandardScaler().fit(frame.to_numpy())
    features = scaler.transform(frame.to_numpy())
    model = LogisticRegression(max_iter=400, random_state=seed).fit(features, target.to_numpy())
    probability = model.predict_proba(features)[:, 1]
    metrics = {
        "brier": float(brier_score_loss(target, probability)),
        "log_loss": float(log_loss(target, np.clip(probability, 1e-6, 1 - 1e-6))),
        "roc_auc": float(roc_auc_score(target, probability)) if len(target.unique()) > 1 else float("nan"),
        "prevalence": float(target.mean()),
    }
    proxy_definition = (
        "Proxy: 1 si (caída_facturación<0.70 y antigüedad>=6) o sin servicios activos "
        "o dias_mora_prom>20 o meses_moroso>=3 o n_reclamos>=3. No es churn observado."
    )
    return ChurnModel(model, scaler, CHURN_FEATURES, float(target.mean()), metrics, proxy_definition)


def _name_cluster(centroid: dict[str, float], means: dict[str, float]) -> tuple[str, str]:
    """Nombra un cluster comparando su centroide con las medias globales."""
    def z(feature: str) -> float:
        value = centroid.get(feature, 0.0)
        base = means.get(feature, 0.0)
        return (value - base) / max(abs(base), 1.0)

    mt = centroid.get("es_movistar_total", 0.0) >= 0.5
    elegible = centroid.get("elegible_mt", 0.0) >= 0.5
    consumo_alto = z("consumo_datos_gb_prom") >= 0.2
    facturacion_alta = z("monto_facturado_prom") >= 0.2
    reclamos_altos = z("n_reclamos") >= 0.5
    antiguedad_baja = z("antiguedad_meses") <= -0.3
    antiguedad_alta = z("antiguedad_meses") >= 0.2
    app = z("uso_app_movistar_prom") >= 0.2

    if mt:
        name = "Cliente MT actual"
        description = "Ya posee Movistar Total; priorizar profundización y satisfacción."
    elif elegible and (facturacion_alta or consumo_alto):
        name = "Elegible MT alto valor"
        description = "Cumple condiciones MT y muestra facturación/consumo alto; blanco directo de MT."
    elif elegible:
        name = "Elegible MT estándar"
        description = "Cumple condiciones para MT; presentar tier acorde a facturación."
    elif reclamos_altos:
        name = "Perfil de riesgo"
        description = "Señales de fricción operacional; contactar con prudencia y ofertas de bajo riesgo."
    elif antiguedad_baja:
        name = "Nuevo en cartera"
        description = "Cliente reciente con historial corto; priorizar retención y valor claro."
    elif consumo_alto or app:
        name = "Digital consumidor"
        description = "Alto uso digital; canales Digital y upgrades móviles funcionan mejor."
    elif antiguedad_alta and not facturacion_alta:
        name = "Leal precio-sensible"
        description = "Cliente antiguo con facturación moderada; alternativas de precio funcionan mejor."
    else:
        name = "Estándar en crecimiento"
        description = "Perfil promedio sin señales fuertes; probar propuestas de valor incremental."
    return name, description


def train_personas(customers: pd.DataFrame, k: int = 5, seed: int = 42) -> PersonaModel:
    frame = _numeric_frame(customers, PERSONA_FEATURES)
    scaler = StandardScaler().fit(frame.to_numpy())
    scaled = scaler.transform(frame.to_numpy())
    kmeans = KMeans(n_clusters=k, random_state=seed, n_init=10).fit(scaled)
    assignments = kmeans.predict(scaled)
    global_means = {column: float(frame[column].mean()) for column in PERSONA_FEATURES}
    persona_names: dict[int, str] = {}
    persona_descriptions: dict[int, str] = {}
    persona_stats: dict[int, dict[str, float]] = {}
    for cluster_id in range(k):
        mask = assignments == cluster_id
        if not mask.any():
            centroid = {column: 0.0 for column in PERSONA_FEATURES}
        else:
            centroid = {column: float(frame.loc[mask, column].mean()) for column in PERSONA_FEATURES}
        name, description = _name_cluster(centroid, global_means)
        persona_names[cluster_id] = name
        persona_descriptions[cluster_id] = description
        persona_stats[cluster_id] = {"size": float(mask.sum()), **centroid}
    return PersonaModel(
        kmeans=kmeans,
        scaler=scaler,
        features=PERSONA_FEATURES,
        persona_names=persona_names,
        persona_descriptions=persona_descriptions,
        persona_stats=persona_stats,
    )


def compute_uplift_mt(
    candidates: pd.DataFrame, population_uplift: float | None = None
) -> float | None:
    """Estimación observacional de uplift de MT.

    Combina dos señales de forma conservadora:
    1. Modelo — Δ entre la mejor P(venta) de una oferta MT elegible y la mediana
       de las alternativas elegibles del mismo cliente.
    2. Población — cuando el modelo colapsa (fallbacks jerárquicos suavizados),
       usa como cota inferior el uplift observado en el histórico completo
       (tasa de aceptación de MT menos tasa del resto de ofertas).

    Se reporta el máximo entre ambas, siempre no negativo. **No** es un efecto
    causal y no debe interpretarse como uplift verificado en campo.
    """
    if "oferta_es_movistar_total" not in candidates.columns:
        return None
    mt_mask = candidates["oferta_es_movistar_total"].astype(bool)
    if not mt_mask.any() or not (~mt_mask).any():
        return None
    mt_top = float(candidates.loc[mt_mask, "p_venta"].max())
    other_median = float(candidates.loc[~mt_mask, "p_venta"].median())
    model_uplift = max(mt_top - other_median, 0.0)
    if population_uplift is not None:
        return max(model_uplift, float(population_uplift))
    return model_uplift


def population_uplift_mt(history: pd.DataFrame, catalog: pd.DataFrame) -> float:
    """Uplift observacional poblacional MT vs resto del portafolio.

    Se calcula sobre los contactos históricos: acepta / contactado por bandera
    `es_movistar_total` del catálogo. Es la referencia poblacional citada en
    las conclusiones del EDA (MT ≈ 69.7% vs resto ≈ 34.1%).
    """
    catalog_flag = catalog.set_index("oferta_id")["es_movistar_total"].astype(bool)
    events = history[["oferta_id", "contactabilidad", "resultado"]].copy()
    events["is_mt"] = events["oferta_id"].map(catalog_flag).fillna(False)
    events = events.loc[events["contactabilidad"].astype(str).eq("contactado")]
    if events.empty:
        return 0.0
    mt_rate = float(events.loc[events["is_mt"], "resultado"].eq("aceptada").mean() or 0.0)
    other = events.loc[~events["is_mt"]]
    other_rate = float(other["resultado"].eq("aceptada").mean() or 0.0)
    return max(mt_rate - other_rate, 0.0)


@dataclass
class EnrichmentArtifacts:
    churn: ChurnModel | None
    personas: PersonaModel | None

    @property
    def available(self) -> bool:
        return self.churn is not None and self.personas is not None


def load_enrichment(artifact_dir: str | Path) -> EnrichmentArtifacts:
    directory = Path(artifact_dir)
    churn = None
    personas = None
    churn_path = directory / "churn.joblib"
    persona_path = directory / "personas.joblib"
    if churn_path.exists():
        churn = joblib.load(churn_path)
    if persona_path.exists():
        personas = joblib.load(persona_path)
    return EnrichmentArtifacts(churn=churn, personas=personas)


def _load_customers(path: str | Path) -> pd.DataFrame:
    return pd.read_csv(path)


def train_all_enrichment(
    dataset_path: str | Path,
    artifact_dir: str | Path,
    seed: int = 42,
    k_personas: int = 5,
) -> dict[str, Any]:
    customers = _load_customers(dataset_path)
    churn = train_churn(customers, seed=seed)
    personas = train_personas(customers, k=k_personas, seed=seed)
    directory = Path(artifact_dir)
    directory.mkdir(parents=True, exist_ok=True)
    joblib.dump(churn, directory / "churn.joblib")
    joblib.dump(personas, directory / "personas.joblib")
    summary = {
        "churn": {
            "features": churn.features,
            "prevalence_proxy": churn.prevalence,
            "metrics": churn.metrics,
            "proxy_definition": churn.proxy_definition,
        },
        "personas": {
            "k": k_personas,
            "features": personas.features,
            "names": personas.persona_names,
            "descriptions": personas.persona_descriptions,
            "stats": personas.persona_stats,
        },
        "seed": seed,
    }
    (directory / "enrichment_metadata.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Entrena modelos de enriquecimiento (churn, personas).")
    parser.add_argument("--dataset", default="dataset/dataset_clientes.csv")
    parser.add_argument("--artifact-dir", default=None)
    parser.add_argument("--k-personas", type=int, default=5)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    artifact_dir = args.artifact_dir
    if artifact_dir is None:
        manifest_path = Path("artifacts/current.json")
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            path = Path(manifest["path"])
            artifact_dir = str(path if path.is_absolute() else Path("artifacts") / path)
        else:
            artifact_dir = "artifacts/nbo_v2"

    summary = train_all_enrichment(args.dataset, artifact_dir, seed=args.seed, k_personas=args.k_personas)
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
