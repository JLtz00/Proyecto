from __future__ import annotations

import yaml
from fastapi.testclient import TestClient

from nbo import api
from nbo.config import load_config
from nbo.engine import NBOEngine
from nbo.training import train_all


def test_minimum_training_engine_persistence_and_endpoints(tmp_path, monkeypatch):
    config = load_config()
    config["project"]["model_version"] = "integration_v1"
    config["project"]["artifact_dir"] = str(tmp_path / "artifacts")
    config["project"]["database_path"] = str(tmp_path / "nbo.sqlite3")
    config["training"].update({
        "catboost_iterations": 5, "catboost_depth": 4, "search_trials": 1,
        "search_sample_size": 2000, "finalists": 1, "smoothing_alphas": [10.0],
    })
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")

    artifact_dir = train_all(str(config_path), sample_size=6000)
    assert (artifact_dir / "contact.joblib").exists()
    assert (artifact_dir / "acceptance.joblib").exists()
    assert (artifact_dir / "rejection.joblib").exists()

    engine = NBOEngine(str(config_path), persist=True)
    result = engine.recommend("CLI000013")
    offers = [result.recommendation.oferta_id] + [item.oferta_id for item in result.alternatives]
    assert len(offers) == 3
    assert len(set(offers)) == 3
    assert all(0 <= value <= 1 for value in (
        result.recommendation.probabilidad_contacto,
        result.recommendation.probabilidad_aceptacion,
        result.recommendation.probabilidad_venta,
        result.recommendation.score,
    ))
    assert result.recommendation.momento.recommended_date
    assert result.recommendation.momento.basis in {
        "segment_channel_weekday_rate", "fallback_operational", "cooldown_operational",
    }

    monkeypatch.setattr(api, "get_engine", lambda: engine)
    monkeypatch.setattr(api, "get_store", lambda: engine.store)
    client = TestClient(api.app)
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["api_version"] == "1.5.0"
    assert health.json()["model_version"] == "integration_v1"
    recommendation = client.post("/api/v1/nbo/recommend", json={"cliente_id": "CLI000013"})
    assert recommendation.status_code == 200
    payload = recommendation.json()
    assert len(payload["alternatives"]) == 2
    assert payload["cliente"]["monto_facturado_prom"] >= 0
    assert payload["recommendation"]["beneficio_cliente"]
    assert payload["recommendation"]["beneficio_negocio"]
    assert payload["recommendation"]["speech_principal"]
    assert payload["commercial_strategy"]["objective"] == "convertir_a_mt"
    assert payload["commercial_strategy"]["mt_priority_applied"] is True
    assert payload["post_rejection_action"]["source"] == "predicted"
    assert payload["post_rejection_action"]["preserves_mt_path"] is True
    assert payload["sales_playbook"]["version"] == "playbook_v2"
    assert payload["sales_playbook"]["objective"] == "convertir_a_mt"
    assert payload["sales_playbook"]["likely_objection"] == payload["rejection_prediction"][0]["motivo"]
    assert payload["sales_playbook"]["discovery_question"]
    assert payload["sales_playbook"]["suggested_script"]
    assert any("probabilidades" in item for item in payload["sales_playbook"]["do_not_say"])
    assert payload["decision_schema_version"] == "decision_v4"
    assert payload["decision_trace"]["total_offer_channel_pairs"] == 88
    assert payload["decision_trace"]["top_score_breakdown"]
    assert payload["evidence_confidence"]["contact_source"]
    assert payload["playbook_experiment"]["variant"] in ["benefit_first", "strategic_path_first"]
    detail = client.get(f"/api/v1/nbo/decisions/{payload['decision_id']}")
    assert detail.status_code == 200
    assert detail.json()["decision_trace"] == payload["decision_trace"]

    before_simulation = engine.store.business_metrics()["decisions"]["n"]
    simulation = client.post("/api/v1/nbo/simulate", json={
        "cliente_id": "CLI000001",
        "actions": [{"action": "acquire_offer", "oferta_id": "OF005"}],
    })
    assert simulation.status_code == 200
    assert simulation.json()["persisted"] is False
    assert engine.store.business_metrics()["decisions"]["n"] == before_simulation
    journey = client.post("/api/v1/nbo/demo/journey", json={"cliente_id": "CLI000013", "motivo_rechazo": "precio"})
    assert journey.status_code == 200
    assert journey.json()["initial"]["recommendation"]["oferta_id"] != journey.json()["immediate_after_rejection"]["recommendation"]["oferta_id"]
    economics = client.post("/api/v1/nbo/economics/simulate", json={"cliente_id": "CLI000013"})
    assert economics.status_code == 200
    assert economics.json()["assumption_source"] == "demo_assumptions"
    rendered = client.post("/api/v1/nbo/playbook/render", json={"decision_id": payload["decision_id"], "tone": "conciso"})
    assert rendered.status_code == 200
    assert rendered.json()["render_status"] == "fallback"
    assert client.post("/api/v1/nbo/recommend", json={"cliente_id": "missing"}).status_code == 404
    assert client.post("/api/v1/nbo/batch", json={"cliente_ids": ["CLI000013"], "limit": 1}).status_code == 200
    executive = client.get("/api/v1/nbo/executive-report", params={"source": "demo"})
    assert executive.status_code == 200
    assert executive.json()["is_simulated"] is True

    feedback = client.post("/api/v1/nbo/feedback", json={
        "decision_id": payload["decision_id"], "resultado_final": "rechazada",
        "motivo_rechazo": "precio", "medio_probatorio": "chat_log",
        "rebate_usado": True, "resultado_rebate": "rechazada",
    })
    assert feedback.status_code == 201
    feedback_payload = feedback.json()
    assert feedback_payload["post_rejection_action"]["source"] == "observed"
    assert feedback_payload["post_rejection_action"]["trigger_reason"] == "precio"
    assert feedback_payload["post_rejection_action"]["wait_days"] >= 15
    assert feedback_payload["post_rejection_action"]["preserves_mt_path"] is True

    next_recommendation = client.post("/api/v1/nbo/recommend", json={"cliente_id": "CLI000013"})
    assert next_recommendation.status_code == 200
    next_payload = next_recommendation.json()
    next_offers = [next_payload["recommendation"]["oferta_id"]] + [
        item["oferta_id"] for item in next_payload["alternatives"]
    ]
    assert payload["recommendation"]["oferta_id"] not in next_offers
    incoherent = client.post("/api/v1/nbo/feedback", json={
        "decision_id": payload["decision_id"], "resultado_final": "rechazada", "medio_probatorio": "chat_log"
    })
    assert incoherent.status_code == 422
    displayed = client.post("/api/v1/nbo/events", json={
        "decision_id": payload["decision_id"], "event_type": "displayed",
        "oferta_id": payload["recommendation"]["oferta_id"], "canal": payload["recommendation"]["canal"],
    })
    assert displayed.status_code == 201

    # Closed loop: aceptar no cambia productos; activar si cambia estado y recalcula la NBO.
    initial_home = client.post("/api/v1/nbo/recommend", json={"cliente_id": "CLI000001"})
    assert initial_home.status_code == 200
    home_payload = initial_home.json()
    assert home_payload["recommendation"]["oferta_id"] == "OF005"
    accepted = client.post("/api/v1/nbo/feedback", json={
        "decision_id": home_payload["decision_id"], "resultado_final": "aceptada",
        "medio_probatorio": "chat_log", "rebate_usado": False,
    })
    assert accepted.status_code == 201
    unchanged = client.get("/api/v1/nbo/customer-state/CLI000001").json()
    assert unchanged["state_version"] == 0
    activated = client.post("/api/v1/nbo/customer-events", json={
        "cliente_id": "CLI000001", "event_type": "product_activated",
        "effective_at": "2026-08-13T12:00:00Z", "source": "provisioning",
        "idempotency_key": "integration-activate-of005", "expected_state_version": 0,
        "oferta_id": "OF005", "decision_id": home_payload["decision_id"],
        "evidence_type": "order", "evidence_reference": "ORDER-001",
    })
    assert activated.status_code == 201
    activated_payload = activated.json()
    assert activated_payload["new_state"]["state_version"] == 1
    assert activated_payload["new_state"]["mt_stage"] == "elegible_mt"
    assert activated_payload["recommendation"]["recommendation"]["oferta_id"] == "OF022"
    assert activated_payload["recommendation"]["state_version"] == 1
    replay = client.post("/api/v1/nbo/customer-events", json={
        "cliente_id": "CLI000001", "event_type": "product_activated",
        "effective_at": "2026-08-13T12:00:00Z", "source": "provisioning",
        "idempotency_key": "integration-activate-of005", "expected_state_version": 0,
        "oferta_id": "OF005", "decision_id": home_payload["decision_id"],
        "evidence_type": "order", "evidence_reference": "ORDER-001",
    })
    assert replay.status_code == 201 and replay.json()["idempotent_replay"] is True
    conflict = client.post("/api/v1/nbo/customer-events", json={
        "cliente_id": "CLI000001", "event_type": "usage_updated",
        "effective_at": "2026-08-13T13:00:00Z", "source": "crm",
        "idempotency_key": "integration-stale", "expected_state_version": 0,
        "changes": {"consumo_datos_gb_prom": 30},
    })
    assert conflict.status_code == 409
    assert len(client.get("/api/v1/nbo/customer-state/CLI000001/events").json()) == 1
    assert client.get("/api/v1/nbo/learning/readiness").status_code == 200
    assert client.get("/api/v1/nbo/metrics").json()["rejected_customer_events"]["version_conflict"] == 1
