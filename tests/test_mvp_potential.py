from __future__ import annotations

import json
import sqlite3

import pandas as pd

from nbo.economics import FORMULA, simulate_economics
from nbo.engine import NBOEngine
from nbo.llm_renderer import render_playbook
from nbo.schemas import (
    DemoJourneyRequest, EconomicSimulationRequest, SimulationAction, SimulationRequest,
)
from nbo.simulation import demo_journey, simulate


def test_trace_components_reconstruct_score_and_experiment_is_stable():
    engine = NBOEngine(persist=False)
    first = engine.recommend("CLI000013")
    second = engine.recommend("CLI000013")
    for item in first.decision_trace.top_score_breakdown:
        reconstructed = item.conversion + item.customer_fit + item.business_value + item.mt_priority + item.friction + item.cooldown
        assert abs(reconstructed - item.raw_score) < 1e-10
        assert min(max(item.raw_score, 0), 1) == item.final_score
    assert first.playbook_experiment.variant == second.playbook_experiment.variant
    assert first.playbook_experiment.exposure_id != second.playbook_experiment.exposure_id
    variants = [engine._playbook_experiment(f"CLI{i:06d}", str(i)).variant for i in range(1000)]
    benefit_share = variants.count("benefit_first") / len(variants)
    assert 0.45 <= benefit_share <= 0.55


def test_simulation_and_demo_are_isolated_and_preserve_mt_route():
    engine = NBOEngine(persist=False)
    original = engine.customer_index.loc["CLI000001"].copy(deep=True)
    result = simulate(engine, SimulationRequest(
        cliente_id="CLI000001",
        actions=[SimulationAction(action="acquire_offer", oferta_id="OF005")],
    ))
    assert result.persisted is False
    assert result.stage_change.endswith("elegible_mt")
    assert result.simulated.recommendation.es_mt is True
    pd.testing.assert_series_equal(original, engine.customer_index.loc["CLI000001"])

    journey = demo_journey(engine, DemoJourneyRequest(cliente_id="CLI000013", motivo_rechazo="precio"))
    assert journey.persisted is False
    assert journey.initial.recommendation.oferta_id != journey.immediate_after_rejection.recommendation.oferta_id
    assert journey.recovery_action.preserves_mt_path is True


def test_confidence_reports_fallback_and_economic_ranking_is_separate():
    engine = NBOEngine(persist=False)
    result = engine.recommend("CLI000013")
    assert result.evidence_confidence.contact_source == "hierarchical_rate"
    assert "no garantiza" in result.evidence_confidence.warning or "limitado" in result.evidence_confidence.warning
    economics = simulate_economics(engine, EconomicSimulationRequest(cliente_id="CLI000013"))
    assert economics.formula == FORMULA
    assert economics.official_offer_id == result.recommendation.oferta_id
    assert len(economics.economic_top3) == 3
    for offer in economics.economic_top3:
        assert abs(sum(offer.components.values()) - offer.expected_value) < 1e-8


class _Store:
    def __init__(self):
        self.events = []

    def save_llm_render_event(self, event):
        self.events.append(event)


class _Response:
    def __init__(self, script, decision):
        self.script = script
        self.decision = decision

    def raise_for_status(self):
        return None

    def json(self):
        offer = self.decision["recommendation"]
        output = {
            "offer_id": offer["oferta_id"], "offer_name": offer["nombre_oferta"],
            "price": offer["precio_mensual"], "channel": offer["canal"], "script": self.script,
        }
        return {"choices": [{"message": {"content": json.dumps(output)}}]}


def test_llm_renderer_validates_and_falls_back(monkeypatch):
    engine = NBOEngine(persist=False)
    decision = engine.recommend("CLI000013").model_dump()
    store = _Store()
    config = engine.config.copy()
    config["llm"] = {**engine.config["llm"], "enabled": True, "api_key_env": "NBO_TEST_KEY"}
    monkeypatch.setenv("NBO_TEST_KEY", "test")
    monkeypatch.setattr("nbo.llm_renderer.httpx.post", lambda *args, **kwargs: _Response("Podemos revisar esta alternativa y sus condiciones vigentes.", decision))
    generated = render_playbook(decision, "conciso", config, store)
    assert generated.render_status == "generated"

    monkeypatch.setattr("nbo.llm_renderer.httpx.post", lambda *args, **kwargs: _Response("Tiene 99% de probabilidad de aceptar.", decision))
    rejected = render_playbook(decision, "conciso", config, store)
    assert rejected.render_status == "fallback"
    assert rejected.fallback_reason in {"forbidden_content", "invented_number"}

    def timeout(*args, **kwargs):
        raise TimeoutError
    monkeypatch.setattr("nbo.llm_renderer.httpx.post", timeout)
    timed_out = render_playbook(decision, "conciso", config, store)
    assert timed_out.render_status == "fallback"
    assert timed_out.fallback_reason == "provider_error:TimeoutError"
    assert len(store.events) == 3


def test_sqlite_migration_keeps_legacy_feedback(tmp_path):
    from nbo.persistence import DecisionStore

    path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("""CREATE TABLE feedback_events (
            feedback_id INTEGER PRIMARY KEY AUTOINCREMENT,
            decision_id TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            final_result TEXT NOT NULL,
            rejection_reason TEXT,
            proof_type TEXT NOT NULL,
            rebate_used INTEGER NOT NULL,
            rebate_result TEXT
        )""")
        connection.execute(
            "INSERT INTO feedback_events VALUES (1, 'legacy', '2026-01-01', 'aceptada', NULL, 'chat_log', 0, NULL)"
        )
    store = DecisionStore(path)
    with store.connect() as connection:
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(feedback_events)")}
        assert "post_rejection_action_json" in columns
        assert connection.execute("SELECT COUNT(*) FROM feedback_events").fetchone()[0] == 1
        assert connection.execute("SELECT name FROM sqlite_master WHERE name='playbook_exposures'").fetchone()
