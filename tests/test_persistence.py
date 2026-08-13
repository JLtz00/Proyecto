from nbo.persistence import DecisionStore
import sqlite3


def test_store_persists_decision_and_feedback(tmp_path):
    store = DecisionStore(tmp_path / "nbo.sqlite3")
    item = {
        "oferta_id": "OF001", "nombre_oferta": "Oferta", "canal": "Digital",
        "probabilidad_contacto": .8, "probabilidad_aceptacion": .5, "probabilidad_venta": .4,
        "score": .6, "es_mt": False, "precio_mensual": 40,
        "momento": {"momento": "proxima_interaccion_digital", "urgencia": "media"},
        "explanation": {"positive": ["fit"], "negative": []}, "reason_codes": ["FIT"],
    }
    payload = {
        "decision_id": "d1", "versions": {"model_version": "m", "feature_version": "f", "rules_version": "r", "catalog_version": "c"},
        "cliente": {"cliente_id": "CLI", "etapa_mt": "x", "elegible_mt": False, "es_movistar_total": False},
        "recommendation": item, "alternatives": [],
        "rejection_prediction": [{"motivo": "precio", "probability": .5}],
        "rebate": {"enabled": True, "strategy": "s", "speech": "x", "alternative_offer_id": None},
    }
    store.save_decision(payload)
    feedback_id = store.save_feedback({"decision_id": "d1", "resultado_final": "aceptada", "medio_probatorio": "chat_log", "rebate_usado": False})
    assert feedback_id == 1
    assert store.business_metrics()["decisions"]["n"] == 1
    displayed = store.save_funnel_event({"decision_id": "d1", "event_type": "displayed", "oferta_id": "OF001", "canal": "Digital"})
    contacted = store.save_funnel_event({"decision_id": "d1", "event_type": "contacted", "oferta_id": "OF001", "canal": "Digital", "medio_probatorio": "chat_log"})
    accepted = store.save_funnel_event({"decision_id": "d1", "event_type": "accepted", "oferta_id": "OF001", "canal": "Digital"})
    assert (displayed, contacted, accepted) == (2, 3, 4)


def test_migration_preserves_legacy_decisions_feedback_and_experiments(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    store = DecisionStore(path)
    with store.connect() as connection:
        connection.execute(
            """INSERT INTO nbo_decisions
            (decision_id, cliente_id, created_at, model_version, feature_version, rules_version,
             catalog_version, top_offer_id, top_channel, p_contact, p_acceptance, p_sale, score,
             predicted_rejection, rebate_strategy, response_json)
            VALUES ('legacy', 'CLI', '2026-01-01', 'm', 'f', 'r', 'c', 'OF001',
                    'Digital', .5, .5, .25, .4, NULL, 'none', '{}')"""
        )
        connection.execute(
            """INSERT INTO playbook_exposures
            VALUES ('exp', 'legacy', 'v1', 'benefit_first', 'Digital', 'x', '2026-01-01')"""
        )
        connection.execute(
            """INSERT INTO feedback_events
            (decision_id, created_at, final_result, proof_type, rebate_used)
            VALUES ('legacy', '2026-01-02', 'aceptada', 'chat_log', 0)"""
        )
    migrated = DecisionStore(path)
    assert migrated.get_decision("legacy")["state_version"] == 0
    with migrated.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM feedback_events").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM playbook_exposures").fetchone()[0] == 1
