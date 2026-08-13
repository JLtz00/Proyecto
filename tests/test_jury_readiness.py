from __future__ import annotations

import numpy as np
import pandas as pd

from nbo.evaluation_v3 import _bootstrap, _metrics_from_ranks
from nbo.jury import demo_business_metrics, executive_report
from nbo.models import ModelArtifact


def test_demo_executive_metrics_are_explicit_and_coherent():
    report = executive_report({}, "demo")
    assert report["source"] == "demo"
    assert report["is_simulated"] is True
    assert "no representa" in report["disclaimer"]
    assert report["funnel"]["classified"] >= report["funnel"]["activated"]
    assert report["rates"]["activation_rate"] == (
        report["funnel"]["activated"] / report["funnel"]["accepted"]
    )
    assert demo_business_metrics() == demo_business_metrics()


def test_v3_absolute_metrics_count_non_evaluable_events_as_failures():
    ranks = pd.Series([1, 2, np.nan])
    conditioned = _metrics_from_ranks(ranks)
    absolute = _metrics_from_ranks(ranks, denominator=5)
    assert conditioned["hit_at_1"] == 1 / 3
    assert absolute["hit_at_1"] == 1 / 5
    assert absolute["ndcg_at_3"] < conditioned["ndcg_at_3"]


def test_bootstrap_is_grouped_and_deterministic():
    ranks = pd.DataFrame({
        "cliente_id": ["A", "A", "B", "C"],
        "rank": [1, 2, np.nan, 3],
    })
    first = _bootstrap(ranks, 25, 42)
    second = _bootstrap(ranks, 25, 42)
    assert first == second
    assert first["hit_at_1"]["low"] <= first["hit_at_1"]["high"]


class _Preprocessor:
    categorical: list[str] = []
    columns = ["feature"]

    def transform(self, frame):
        return frame[["feature"]]


class _Estimator:
    def get_feature_importance(self, pool, type):
        assert type == "ShapValues"
        return np.asarray([[0.25, -0.10], [0.50, -0.20]])


def test_catboost_contributions_are_reachable():
    artifact = ModelArtifact(_Estimator(), _Preprocessor(), [0, 1], model_kind="catboost")
    result = artifact.local_contributions(pd.DataFrame({"feature": [1.0, 2.0]}))
    assert result == [{"feature": 0.25}, {"feature": 0.5}]
