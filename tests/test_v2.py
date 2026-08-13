from __future__ import annotations

import pandas as pd

from nbo.engine import FEATURE_LABELS
from nbo.features import build_historical_features, summarize_history
from nbo.splits import apply_group_assignments, make_group_assignments


def test_split_assignments_are_reproducible_and_disjoint():
    ids = pd.Series([f"CLI{i:03d}" for i in range(100)])
    first = make_group_assignments(ids, 42)
    second = make_group_assignments(ids, 42)
    assert first == second
    split = apply_group_assignments(ids, first)
    assert (split == "train").sum() == 70
    assert (split == "validation").sum() == 15
    assert (split == "test").sum() == 15


def test_as_of_summary_excludes_current_month(customer, catalog):
    history = pd.DataFrame([
        {"cliente_id": "CLI_TEST", "oferta_id": "OF001", "fecha": pd.Timestamp("2026-01-10"), "canal": "Digital", "resultado": "aceptada", "motivo_rechazo": "sin_rechazo", "contactabilidad": "contactado", "tipo_cliente": "postpago"},
        {"cliente_id": "CLI_TEST", "oferta_id": "OF001", "fecha": pd.Timestamp("2026-02-10"), "canal": "Digital", "resultado": "rechazada", "motivo_rechazo": "precio", "contactabilidad": "contactado", "tipo_cliente": "postpago"},
    ])
    summary = summarize_history(history, catalog.iloc[[0]], "2026-02-01", alpha=10)
    assert summary.client.loc["CLI_TEST", "hist_client_offer"] == 1
    assert summary.client.loc["CLI_TEST", "hist_client_accept"] == 1
    assert summary.client.loc["CLI_TEST", "hist_client_reject"] == 0


def test_explanation_labels_have_distinct_semantics():
    for positive, negative in FEATURE_LABELS.values():
        assert positive != negative
        assert positive not in negative
