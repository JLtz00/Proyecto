from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pytest
import sqlite3

from nbo.persistence import DecisionStore, StateVersionConflict
from nbo.schemas import CustomerEventRequest
from nbo.state import CustomerStateService


def _service(tmp_path, customer, catalog):
    store = DecisionStore(tmp_path / "state.sqlite3")
    customers = pd.DataFrame([customer.to_dict()])
    return CustomerStateService(customers, catalog, store), store


def _event(**overrides):
    values = {
        "cliente_id": "CLI_TEST", "event_type": "product_activated",
        "effective_at": datetime.now(timezone.utc), "source": "provisioning",
        "idempotency_key": "activation-1", "expected_state_version": 0,
        "oferta_id": "OF017", "evidence_type": "order",
        "evidence_reference": "ORD-1",
    }
    values.update(overrides)
    return CustomerEventRequest(**values)


def test_activation_is_append_only_idempotent_and_blocks_active_offer(tmp_path, customer, catalog):
    service, store = _service(tmp_path, customer, catalog)
    original = customer.copy()
    event, before, after, changed, replay = service.register_event(_event())
    assert not replay
    assert before.state_version == 0 and after.state_version == 1
    assert "OF017" in after.active_offer_ids
    assert changed["active_offer_ids"]["after"] == after.active_offer_ids
    replayed, _, replay_state, _, is_replay = service.register_event(_event())
    assert is_replay and replayed.event_id == event.event_id
    assert replay_state.state_version == 1
    assert len(store.list_customer_events("CLI_TEST")) == 1
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        with store.connect() as connection:
            connection.execute(
                "DELETE FROM customer_state_events WHERE event_id=?", (event.event_id,)
            )
    pd.testing.assert_series_equal(customer, original)


def test_version_conflict_and_as_of_reconstruction(tmp_path, customer, catalog):
    service, _ = _service(tmp_path, customer, catalog)
    service.register_event(_event())
    with pytest.raises(StateVersionConflict):
        service.register_event(_event(
            idempotency_key="usage-2", event_type="usage_updated", oferta_id=None,
            changes={"consumo_datos_gb_prom": 99}, expected_state_version=0,
            evidence_type=None, evidence_reference=None,
        ))
    old = service.get_state("CLI_TEST", "2000-01-01T00:00:00Z")
    assert old.state_version == 0
    assert "OF017" not in old.active_offer_ids


def test_home_activation_derives_mt_and_cancellation_recalculates(tmp_path, customer, catalog):
    base = customer.copy()
    base["tiene_hogar"] = False
    base["tiene_internet_hogar"] = False
    base["oferta_hogar_id"] = "sin_hogar"
    base["elegible_mt"] = False
    service, _ = _service(tmp_path, base, catalog)
    _, _, activated, _, _ = service.register_event(_event(oferta_id="OF005"))
    assert activated.attributes["tiene_internet_hogar"] is True
    assert activated.attributes["elegible_mt"] is True
    assert activated.mt_stage == "elegible_mt"
    _, _, cancelled, _, _ = service.register_event(_event(
        event_type="product_cancelled", source="crm", idempotency_key="cancel-1",
        expected_state_version=1, oferta_id="OF005", evidence_type=None,
        evidence_reference=None,
    ))
    assert cancelled.attributes["tiene_hogar"] is False
    assert cancelled.attributes["elegible_mt"] is False


def test_acceptance_does_not_change_state_and_decision_activation_requires_it(tmp_path, customer, catalog):
    service, store = _service(tmp_path, customer, catalog)
    item = {
        "oferta_id": "OF017", "nombre_oferta": "Streaming", "canal": "Digital",
        "probabilidad_contacto": .8, "probabilidad_aceptacion": .5,
        "probabilidad_venta": .4, "score": .6, "es_mt": False,
        "precio_mensual": 20, "momento": {}, "explanation": {}, "reason_codes": [],
    }
    store.save_decision({
        "decision_id": "d1", "decision_schema_version": "decision_v3",
        "versions": {"model_version": "nbo_v2", "feature_version": "f", "rules_version": "rules_v4", "catalog_version": "c"},
        "cliente": {"cliente_id": "CLI_TEST", "etapa_mt": "elegible_mt"},
        "recommendation": item, "alternatives": [], "rejection_prediction": [],
        "rebate": {"strategy": "none"},
    })
    with pytest.raises(ValueError, match="aceptacion"):
        service.register_event(_event(decision_id="d1"))
    store.save_feedback({
        "decision_id": "d1", "resultado_final": "aceptada",
        "medio_probatorio": "chat_log", "rebate_usado": False,
    })
    assert service.get_state("CLI_TEST").state_version == 0
    _, _, after, _, _ = service.register_event(_event(decision_id="d1"))
    assert after.state_version == 1


def test_override_can_be_replaced_and_compensated(tmp_path, customer, catalog):
    service, _ = _service(tmp_path, customer, catalog)
    first, _, blocked, _, _ = service.register_event(_event(
        event_type="mt_eligibility_overridden", oferta_id=None, source="crm",
        idempotency_key="override-1", changes={"enabled": False},
        evidence_type="ticket", evidence_reference="T-1",
    ))
    assert blocked.attributes["elegible_mt"] is False
    _, _, enabled, _, _ = service.register_event(_event(
        event_type="mt_eligibility_overridden", oferta_id=None, source="crm",
        idempotency_key="override-2", expected_state_version=1,
        changes={"enabled": True}, evidence_type="ticket", evidence_reference="T-2",
    ))
    assert enabled.attributes["elegible_mt"] is True
    _, _, restored, _, _ = service.register_event(_event(
        event_type="customer_attribute_corrected", oferta_id=None, source="backoffice",
        idempotency_key="correction-1", expected_state_version=2,
        correction_of_event_id=first.event_id, changes={"restore_original": True},
        evidence_type=None, evidence_reference=None,
    ))
    assert restored.mt_override is None
