from __future__ import annotations

import numpy as np
import pandas as pd

from nbo.features import add_pair_features, build_historical_features, model_feature_columns
from nbo.data import clean_semantic_nulls


def _history() -> pd.DataFrame:
    return pd.DataFrame([
        {"ofrecimiento_id": "E1", "cliente_id": "CLI_TEST", "oferta_id": "OF001", "fecha": pd.Timestamp("2026-01-10"), "canal": "Digital", "resultado": "aceptada", "motivo_rechazo": "sin_rechazo", "es_rebate": False, "contactabilidad": "contactado", "medio_probatorio": "chat_log"},
        {"ofrecimiento_id": "E2", "cliente_id": "CLI_TEST", "oferta_id": "OF001", "fecha": pd.Timestamp("2026-01-20"), "canal": "Digital", "resultado": "rechazada", "motivo_rechazo": "precio", "es_rebate": False, "contactabilidad": "contactado", "medio_probatorio": "chat_log"},
        {"ofrecimiento_id": "E3", "cliente_id": "CLI_TEST", "oferta_id": "OF001", "fecha": pd.Timestamp("2026-02-10"), "canal": "Digital", "resultado": "pendiente", "motivo_rechazo": "sin_rechazo", "es_rebate": False, "contactabilidad": "no_contactado", "medio_probatorio": "chat_log"},
    ])


def test_same_month_events_do_not_leak(customer, catalog):
    frame = build_historical_features(customer.to_frame().T, catalog.iloc[[0]], _history())
    january = frame.loc[frame["event_month"] == "2026-01"]
    february = frame.loc[frame["event_month"] == "2026-02"]
    assert january["hist_client_offer"].eq(0).all()
    assert february.iloc[0]["hist_client_offer"] == 2
    assert february.iloc[0]["hist_client_accept"] == 1
    assert february.iloc[0]["hist_client_reject"] == 1
    assert february.iloc[0]["days_since_last_offer"] == 21


def test_unlimited_and_zero_division_are_safe(customer, catalog):
    row = {**customer.to_dict(), **catalog.iloc[0].to_dict(), "canal": "Digital", "hist_client_offer": 0, "hist_client_reject": 0, "hist_client_price_reject": 0}
    row["monto_facturado_prom"] = 0
    row["gb_incluidos"] = 9999
    result = add_pair_features(pd.DataFrame([row]))
    assert result.loc[0, "oferta_es_ilimitada"] == 1
    assert np.isnan(result.loc[0, "gap_gb"])
    assert np.isfinite(result.loc[0, "ratio_precio_facturacion"])


def test_bayesian_rates_are_probabilities(customer, catalog):
    frame = build_historical_features(customer.to_frame().T, catalog.iloc[[0]], _history(), alpha=10)
    assert frame["hist_contact_rate_channel"].between(0, 1).all()
    assert frame["hist_accept_rate_channel"].between(0, 1).all()


def test_customer_id_is_excluded_from_model_features():
    frame = pd.DataFrame({"cliente_id": pd.Series(["CLI1"], dtype="str"), "value": [1.0]})
    categorical, numeric = model_feature_columns(frame)
    assert "cliente_id" not in categorical + numeric
    assert "value" in numeric


def test_semantic_nulls_are_not_replaced_with_zero(customer, catalog):
    customers = customer.to_frame().T
    customers.loc[:, "tipo_cliente"] = None
    customers.loc[:, "oferta_hogar_id"] = None
    customers.loc[:, "canal_mas_usado"] = None
    history = _history()
    history.loc[:, "motivo_rechazo"] = None
    cleaned, _, cleaned_history = clean_semantic_nulls(customers, catalog, history)
    assert cleaned.iloc[0]["tipo_cliente"] == "sin_linea_movil"
    assert cleaned.iloc[0]["oferta_hogar_id"] == "sin_hogar"
    assert cleaned.iloc[0]["canal_mas_usado"] == "sin_actividad"
    assert cleaned_history.iloc[0]["motivo_rechazo"] == "sin_rechazo"
