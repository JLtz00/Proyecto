from __future__ import annotations

from pathlib import Path

import pandas as pd


CUSTOMER_FILE = "dataset_clientes.csv"
CATALOG_FILE = "catalogo_ofertas_entrega.csv"
HISTORY_FILE = "historial_campanias.csv"

BOOL_COLUMNS = {
    "customers": ["tiene_movil", "tiene_hogar", "tiene_internet_hogar", "es_movistar_total", "elegible_mt", "es_usuario_app"],
    "catalog": ["es_movistar_total"],
    "history": ["es_rebate", "elegible_mt", "es_movistar_total", "oferta_es_mt"],
}


def _coerce_bool(series: pd.Series) -> pd.Series:
    if pd.api.types.is_bool_dtype(series):
        return series.astype(bool)
    mapped = series.astype(str).str.strip().str.lower().map(
        {"true": True, "false": False, "1": True, "0": False}
    )
    return mapped.astype("boolean")


def load_raw(data_dir: str | Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    data_dir = Path(data_dir)
    customers = pd.read_csv(data_dir / CUSTOMER_FILE, low_memory=False)
    catalog = pd.read_csv(data_dir / CATALOG_FILE, low_memory=False)
    history = pd.read_csv(data_dir / HISTORY_FILE, low_memory=False)
    for name, frame in (("customers", customers), ("catalog", catalog), ("history", history)):
        for column in BOOL_COLUMNS[name]:
            if column in frame:
                frame[column] = _coerce_bool(frame[column])
    history["fecha"] = pd.to_datetime(history["fecha"], errors="coerce")
    return customers, catalog, history


def clean_semantic_nulls(
    customers: pd.DataFrame, catalog: pd.DataFrame, history: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    customers, catalog, history = customers.copy(), catalog.copy(), history.copy()
    customers["tipo_cliente"] = customers["tipo_cliente"].fillna("sin_linea_movil")
    customers["oferta_hogar_id"] = customers["oferta_hogar_id"].fillna("sin_hogar")
    customers["canal_mas_usado"] = customers["canal_mas_usado"].fillna("sin_actividad")
    history["motivo_rechazo"] = history["motivo_rechazo"].fillna("sin_rechazo")
    for frame in (customers, catalog, history):
        categorical = frame.select_dtypes(include=["object", "string"]).columns
        frame[categorical] = frame[categorical].fillna("unknown")
    return customers, catalog, history

